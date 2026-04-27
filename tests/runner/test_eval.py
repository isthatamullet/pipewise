"""Tests for the eval execution engine (Phase 3 #22)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pipewise import (
    PipelineRun,
    RunScorer,
    ScoreResult,
    StepExecution,
    StepScorer,
)
from pipewise.runner.eval import run_eval

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _step(step_id: str, output: str = "ok") -> StepExecution:
    return StepExecution(
        step_id=step_id,
        step_name=step_id.upper(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status="completed",
        outputs={"value": output},
    )


def _run(run_id: str = "run_1", steps: list[StepExecution] | None = None) -> PipelineRun:
    return PipelineRun(
        run_id=run_id,
        pipeline_name="fake",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=10),
        status="completed",
        adapter_name="fake-adapter",
        adapter_version="0.0.1",
        steps=steps or [_step("s1"), _step("s2")],
    )


class _PassingStepScorer:
    name = "passing-step"

    def score(self, actual: StepExecution, expected: StepExecution | None = None) -> ScoreResult:
        return ScoreResult(score=1.0, passed=True, reasoning="ok")


class _FailingStepScorer:
    name = "failing-step"

    def score(self, actual: StepExecution, expected: StepExecution | None = None) -> ScoreResult:
        return ScoreResult(score=0.0, passed=False, reasoning="bad")


class _RaisingStepScorer:
    name = "raising-step"

    def score(self, actual: StepExecution, expected: StepExecution | None = None) -> ScoreResult:
        raise RuntimeError("boom")


class _PassingRunScorer:
    name = "passing-run"

    def score(self, actual: PipelineRun, expected: PipelineRun | None = None) -> ScoreResult:
        return ScoreResult(score=1.0, passed=True)


class _RaisingRunScorer:
    name = "raising-run"

    def score(self, actual: PipelineRun, expected: PipelineRun | None = None) -> ScoreResult:
        raise ValueError("nope")


class TestRunEval:
    def test_satisfies_protocols(self) -> None:
        # Sanity: the test fixtures actually conform to the runtime protocols.
        assert isinstance(_PassingStepScorer(), StepScorer)
        assert isinstance(_PassingRunScorer(), RunScorer)

    def test_happy_path_step_scorer_runs_per_step(self) -> None:
        run = _run(steps=[_step("s1"), _step("s2"), _step("s3")])
        report = run_eval([run], [_PassingStepScorer()], [])

        assert len(report.runs) == 1
        run_result = report.runs[0]
        assert len(run_result.step_scores) == 3
        assert {e.step_id for e in run_result.step_scores} == {"s1", "s2", "s3"}
        assert all(e.result.passed for e in run_result.step_scores)

    def test_run_scorer_runs_once_per_run(self) -> None:
        runs = [_run("run_1"), _run("run_2")]
        report = run_eval(runs, [], [_PassingRunScorer()])

        assert len(report.runs) == 2
        for run_result in report.runs:
            assert len(run_result.step_scores) == 0
            assert len(run_result.run_scores) == 1
            assert run_result.run_scores[0].result.passed

    def test_step_scorer_exception_recorded_as_failed_result(self) -> None:
        run = _run(steps=[_step("s1")])
        report = run_eval([run], [_RaisingStepScorer()], [])

        entry = report.runs[0].step_scores[0]
        assert entry.scorer_name == "raising-step"
        assert entry.result.passed is False
        assert entry.result.score == 0.0
        assert entry.result.reasoning is not None
        assert "RuntimeError" in entry.result.reasoning
        assert "boom" in entry.result.reasoning

    def test_run_scorer_exception_recorded_as_failed_result(self) -> None:
        run = _run()
        report = run_eval([run], [], [_RaisingRunScorer()])

        entry = report.runs[0].run_scores[0]
        assert entry.scorer_name == "raising-run"
        assert entry.result.passed is False
        assert entry.result.reasoning is not None
        assert "ValueError" in entry.result.reasoning

    def test_eval_does_not_abort_when_one_scorer_raises(self) -> None:
        # A raising scorer must not stop other scorers or other runs from running.
        runs = [_run("run_1"), _run("run_2")]
        report = run_eval(
            runs,
            [_RaisingStepScorer(), _PassingStepScorer()],
            [],
        )
        assert len(report.runs) == 2
        for run_result in report.runs:
            # Each step gets two entries (one per scorer); first fails, second passes.
            scorers_seen = {e.scorer_name for e in run_result.step_scores}
            assert scorers_seen == {"raising-step", "passing-step"}

    def test_dataset_name_recorded_in_report(self) -> None:
        report = run_eval([_run()], [], [], dataset_name="factspark-golden-v1")
        assert report.dataset_name == "factspark-golden-v1"
        assert "factspark-golden-v1" in report.report_id

    def test_dataset_name_omitted_uses_adhoc_label(self) -> None:
        report = run_eval([_run()], [], [])
        assert report.dataset_name is None
        assert "adhoc" in report.report_id

    def test_scorer_names_snapshotted(self) -> None:
        report = run_eval(
            [_run()],
            [_PassingStepScorer(), _FailingStepScorer()],
            [_PassingRunScorer()],
        )
        assert report.scorer_names == ["passing-step", "failing-step", "passing-run"]

    def test_no_runs_yields_empty_report(self) -> None:
        report = run_eval([], [_PassingStepScorer()], [_PassingRunScorer()])
        assert report.runs == []
        assert report.scorer_names == ["passing-step", "passing-run"]

    def test_no_scorers_yields_runs_with_empty_score_lists(self) -> None:
        report = run_eval([_run()], [], [])
        assert len(report.runs) == 1
        assert report.runs[0].step_scores == []
        assert report.runs[0].run_scores == []

    def test_report_provenance_fields_copied_from_run(self) -> None:
        run = _run("run_1")
        report = run_eval([run], [], [])
        run_result = report.runs[0]
        assert run_result.run_id == "run_1"
        assert run_result.pipeline_name == "fake"
        assert run_result.adapter_name == "fake-adapter"
        assert run_result.adapter_version == "0.0.1"

    def test_iterable_input_supported(self) -> None:
        # `run_eval` takes Iterable, not list — generator should work.
        def gen() -> object:
            yield _run("a")
            yield _run("b")

        report = run_eval(gen(), [], [_PassingRunScorer()])  # type: ignore[arg-type]
        assert [r.run_id for r in report.runs] == ["a", "b"]

    def test_pipewise_version_recorded(self) -> None:
        from pipewise import __version__ as pkg_version

        report = run_eval([_run()], [], [])
        assert report.pipewise_version == pkg_version

    @pytest.mark.parametrize("status", ["completed", "partial", "failed"])
    def test_evaluates_runs_with_any_status(self, status: str) -> None:
        # Eval must work on completed AND failed runs — that's often when
        # users care most about the diagnostic detail.
        run = PipelineRun(
            run_id="r",
            pipeline_name="fake",
            started_at=NOW,
            completed_at=NOW if status != "completed" else NOW + timedelta(seconds=1),
            status=status,  # type: ignore[arg-type]
            adapter_name="fake-adapter",
            adapter_version="0.0.1",
            steps=[_step("s1")],
        )
        if status == "completed":
            run = _run(steps=[_step("s1")])  # ensure completed_at set
        report = run_eval([run], [_PassingStepScorer()], [])
        assert len(report.runs) == 1
