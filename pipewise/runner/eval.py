"""Eval execution engine — run scorers across `PipelineRun`s into an `EvalReport`.

Phase 3 #22. Sequential execution; parallelism is intentionally deferred until
v1 ships (open an issue if users hit the wall in practice).

Failure semantics: a scorer raising an exception does NOT abort the eval. The
exception is caught, recorded as a failed `ScoreResult` with the exception
message in `reasoning`, and the eval continues. Rationale: one flaky scorer on
one step shouldn't tank a 1000-row dataset eval — users want to see the rest
of the results.

Skip semantics: the runner emits `status="skipped"` BEFORE invoking the scorer
when (a) the scorer's `applies_to_step_ids` excludes this step, or (b) the
step itself has `status="skipped"` (the upstream pipeline didn't execute it).
A scorer's own decision to emit `"skipped"` is also honored — e.g., budget
scorers with `on_missing="skip"`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from pipewise import __version__
from pipewise.core.report import (
    EvalReport,
    RunEvalResult,
    RunScoreEntry,
    StepScoreEntry,
)
from pipewise.core.schema import PipelineRun
from pipewise.core.scorer import RunScorer, ScoreResult, StepScorer


def _safe_step_score(scorer: StepScorer, run: PipelineRun, step_idx: int) -> ScoreResult:
    """Invoke a step scorer, wrapping any exception as a failed result."""
    try:
        return scorer.score(run.steps[step_idx])
    except Exception as exc:
        return ScoreResult(
            status="failed",
            score=0.0,
            reasoning=f"{scorer.name} raised {type(exc).__name__}: {exc}",
        )


def _safe_run_score(scorer: RunScorer, run: PipelineRun) -> ScoreResult:
    """Invoke a run scorer, wrapping any exception as a failed result."""
    try:
        return scorer.score(run)
    except Exception as exc:
        return ScoreResult(
            status="failed",
            score=0.0,
            reasoning=f"{scorer.name} raised {type(exc).__name__}: {exc}",
        )


def _resolve_step_score(scorer: StepScorer, run: PipelineRun, step_idx: int) -> ScoreResult:
    """Decide whether to invoke the step scorer or short-circuit to `skipped`.

    Two short-circuit cases produce a `skipped` result without calling the
    scorer:
    - `scorer.applies_to_step_ids` is set and the step's `step_id` is not in it.
    - The step itself has `status="skipped"` (upstream pipeline didn't execute).

    Failed steps DO get scored (they may have partial outputs worth checking).
    """
    step = run.steps[step_idx]
    applies_to: Sequence[str] | None = getattr(scorer, "applies_to_step_ids", None)
    if applies_to is not None and step.step_id not in applies_to:
        return ScoreResult(
            status="skipped",
            score=None,
            reasoning=f"step_id '{step.step_id}' not in applies_to_step_ids",
        )
    if step.status == "skipped":
        return ScoreResult(
            status="skipped",
            score=None,
            reasoning=f"step '{step.step_id}' status is 'skipped'; scorer not invoked",
        )
    return _safe_step_score(scorer, run, step_idx)


def run_eval(
    runs: Iterable[PipelineRun],
    step_scorers: list[StepScorer],
    run_scorers: list[RunScorer],
    dataset_name: str | None = None,
) -> EvalReport:
    """Run the given scorers across `runs`, returning an aggregated `EvalReport`.

    Args:
        runs: The pipeline runs to evaluate. Iterable so callers can stream
            from `load_dataset` without materializing.
        step_scorers: Scorers invoked once per step, per run.
        run_scorers: Scorers invoked once per whole run.
        dataset_name: Optional human-readable label snapshotted into the report.

    Returns:
        An `EvalReport` containing every `ScoreResult` produced. Scorer
        exceptions are recorded as failed results with the exception message
        in `reasoning` — the eval never aborts mid-stream.
    """
    generated_at = datetime.now(UTC)
    scorer_names = [s.name for s in step_scorers] + [s.name for s in run_scorers]
    label = dataset_name if dataset_name is not None else "adhoc"
    report_id = f"{label}_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"

    run_results: list[RunEvalResult] = []
    for run in runs:
        step_entries: list[StepScoreEntry] = []
        for idx, step in enumerate(run.steps):
            for scorer in step_scorers:
                step_entries.append(
                    StepScoreEntry(
                        step_id=step.step_id,
                        scorer_name=scorer.name,
                        result=_resolve_step_score(scorer, run, idx),
                    )
                )

        run_entries: list[RunScoreEntry] = [
            RunScoreEntry(scorer_name=scorer.name, result=_safe_run_score(scorer, run))
            for scorer in run_scorers
        ]

        run_results.append(
            RunEvalResult(
                run_id=run.run_id,
                pipeline_name=run.pipeline_name,
                pipeline_version=run.pipeline_version,
                adapter_name=run.adapter_name,
                adapter_version=run.adapter_version,
                step_scores=step_entries,
                run_scores=run_entries,
            )
        )

    return EvalReport(
        report_id=report_id,
        generated_at=generated_at,
        pipewise_version=__version__,
        dataset_name=dataset_name,
        scorer_names=scorer_names,
        runs=run_results,
    )


__all__ = ["run_eval"]
