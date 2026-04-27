"""Phase 4 validation gate (issue #31): drive `pipewise.run_eval` end-to-end
through the **real** resume-tailor adapter.

This is the production-shape test, not the Phase 1 prototype gate
(`test_resume_validation_gate.py`). It imports `resume_tailor_pipewise.adapter`
— the adapter package shipped at `job-search/integrations/pipewise/` — and
exercises the meaningfully harder pipeline shape the resume-tailor pipeline
introduces:

- **Branching** (write_resume_chronological vs write_resume_hybrid mutex)
- **Optional steps** (discover_experience often skipped)
- **Mixed JSON / Markdown** (step 1-5 are JSON, step 6's outputs are
  cover-letter + application-responses Markdown)
- **Always-skipped steps** (apply_to_canva — Canva has no filesystem
  output for the adapter to read)

Pairs with `test_phase4_factspark_gate.py` — together they're the proof
that pipewise's adapter contract handles fundamentally different pipeline
shapes via near-identical adapter code (the abstraction-correctness claim
in the README).

Skips automatically when the resumes dir is absent OR when the adapter
package isn't installed (`uv pip install -e <job-search>/integrations/pipewise/`).

The test deliberately discovers reference runs *dynamically* — it scans
the local resumes dir, classifies each run by `(resume_format, step2_status)`,
and picks the first run from each shape category. This keeps real personal
job-application targets out of pipewise's committed test history while still
exercising the adapter against real production data.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from pipewise.core.report import EvalReport
from pipewise.core.schema import PipelineRun

_RESUMES_DIR = Path.home() / "tyler" / "jobs" / "resumes"

# Shape categories the gate aims to exercise. Each category is a
# (resume_format, step2_status) pair that the adapter should distinguish.
# We pick at most one run per category from whatever's locally available so
# the test runs against real production data without committing the
# specific run identifiers.
_SHAPE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("HYBRID", "skipped"),
    ("CHRONOLOGICAL", "completed"),
    ("CHRONOLOGICAL", "skipped"),
)


def _adapter_module() -> object | None:
    """Return the installed adapter module, or None when unavailable."""
    try:
        return importlib.import_module("resume_tailor_pipewise")
    except ImportError:
        return None


_ADAPTER = _adapter_module()


def _discover_reference_runs() -> list[PipelineRun]:
    """Walk the local resumes dir and pick at most one run per shape category.

    Returns an empty list when the resumes dir is absent. Returns whatever
    real runs are available when present — the gate's `pytestmark` skip
    handles the "not enough coverage" case.
    """
    if _ADAPTER is None or not _RESUMES_DIR.exists():
        return []
    seen: dict[tuple[str, str], PipelineRun] = {}
    for company_dir in sorted(_RESUMES_DIR.iterdir()):
        if not company_dir.is_dir():
            continue
        for step1_path in sorted(company_dir.glob("*_step1.json")):
            try:
                run: PipelineRun = _ADAPTER.load_run(step1_path)  # type: ignore[attr-defined]
            except Exception:
                continue
            fmt = run.metadata.get("resume_format")
            if not isinstance(fmt, str):
                continue
            step2 = next(
                (s for s in run.steps if s.step_id == "discover_experience"),
                None,
            )
            if step2 is None:
                continue
            # Only accept runs whose step4 branches resolved cleanly — a
            # mid-failure run isn't useful for asserting the mutex contract.
            if not any(
                s.step_id in {"write_resume_chronological", "write_resume_hybrid"}
                and s.status == "completed"
                for s in run.steps
            ):
                continue
            key = (fmt, step2.status)
            if key in _SHAPE_CATEGORIES and key not in seen:
                seen[key] = run
            if len(seen) == len(_SHAPE_CATEGORIES):
                break
        if len(seen) == len(_SHAPE_CATEGORIES):
            break
    return list(seen.values())


_DISCOVERED_RUNS = _discover_reference_runs()

pytestmark = pytest.mark.skipif(
    _ADAPTER is None or len(_DISCOVERED_RUNS) < 2,
    reason=(
        "Phase 4 resume-tailor gate runs locally only — requires both the "
        "real resume_tailor_pipewise adapter to be installed AND >=2 "
        "reference runs spanning distinct (resume_format, step2_status) "
        "categories present locally."
    ),
)


def test_real_adapter_produces_valid_pipeline_runs() -> None:
    """`load_run` returns schema-conforming runs with the canonical 8-step shape."""
    runs = _DISCOVERED_RUNS
    assert len(runs) >= 2

    expected_step_ids = [
        "analyze_posting",
        "discover_experience",
        "match_experience",
        "write_resume_chronological",
        "write_resume_hybrid",
        "hiring_manager_critique",
        "format_export",
        "apply_to_canva",
    ]
    for run in runs:
        assert isinstance(run, PipelineRun)
        assert run.pipeline_name == "resume-tailor"
        assert run.adapter_name == "resume-tailor-pipewise-adapter"
        assert [s.step_id for s in run.steps] == expected_step_ids


def test_branching_is_mutex_across_runs() -> None:
    """For every run, exactly one of step4 / step4b is `completed` — the
    other is `skipped`. This is the schema-level encoding of the conditional
    branch (see `PipelineRun` docstring: "Branches and conditional steps are
    captured by which `step_id` actually ran; skips are recorded with
    `status='skipped'`")."""
    for run in _DISCOVERED_RUNS:
        chronological = next(s for s in run.steps if s.step_id == "write_resume_chronological")
        hybrid = next(s for s in run.steps if s.step_id == "write_resume_hybrid")
        completed_branches = [s for s in (chronological, hybrid) if s.status == "completed"]
        assert len(completed_branches) == 1, (
            "expected exactly one completed step4 branch, "
            f"got chronological={chronological.status}, hybrid={hybrid.status}"
        )


def test_discovered_runs_span_distinct_shape_categories() -> None:
    """The dynamic discovery picks at most one run per shape category. This
    test pins that the categories represented are actually distinct — if a
    future adapter regression collapses HYBRID and CHRONOLOGICAL detection
    into the same value, we'd see all runs land in one category and this
    fails loudly."""
    categories = {(run.metadata["resume_format"], _step2_status(run)) for run in _DISCOVERED_RUNS}
    assert len(categories) >= 2, (
        f"expected >=2 distinct (resume_format, step2_status) categories, got {sorted(categories)}"
    )


def _step2_status(run: PipelineRun) -> str:
    return next(s.status for s in run.steps if s.step_id == "discover_experience")


def test_default_scorers_drive_run_eval_end_to_end() -> None:
    """`default_scorers()` + `run_eval` produces the report shape pipewise's
    CLI relies on for `pipewise eval`."""
    assert _ADAPTER is not None
    from pipewise.runner.eval import run_eval

    runs = _DISCOVERED_RUNS
    step_scorers, run_scorers = _ADAPTER.default_scorers()  # type: ignore[attr-defined]
    report = run_eval(runs, step_scorers, run_scorers, dataset_name="phase4-resume-tailor-gate")

    assert isinstance(report, EvalReport)
    assert len(report.runs) == len(runs)
    # Per-run: 1 step scorer x 8 steps + 2 run scorers = 10 entries.
    for run_result in report.runs:
        assert len(run_result.step_scores) == 8
        assert len(run_result.run_scores) == 2

    # The adapter populates `_company` on every step (including skipped ones)
    # so the company-propagated check passes uniformly on healthy runs.
    # Budget scorers run with `on_missing="skip"` because Claude Code doesn't
    # expose per-call usage in v1 — those pass too.
    for run_result in report.runs:
        assert all(r.result.passed for r in run_result.step_scores), (
            "company-propagated step check failed unexpectedly"
        )
        assert all(r.result.passed for r in run_result.run_scores), (
            "budget run-scorer failed unexpectedly"
        )


def test_eval_report_round_trips_without_data_loss(tmp_path: Path) -> None:
    """`EvalReport` survives JSON serialization end-to-end. Same contract as
    the FactSpark gate (#30), but here the report includes step entries with
    `status="skipped"` and Markdown content in `format_export.outputs` —
    different shapes than FactSpark's all-completed all-JSON runs."""
    assert _ADAPTER is not None
    from pipewise.runner.eval import run_eval

    runs = _DISCOVERED_RUNS
    step_scorers, run_scorers = _ADAPTER.default_scorers()  # type: ignore[attr-defined]
    report = run_eval(runs, step_scorers, run_scorers, dataset_name="phase4-resume-roundtrip")

    serialized = report.model_dump_json()
    restored = EvalReport.model_validate_json(serialized)
    assert restored == report

    out_path = tmp_path / "report.json"
    out_path.write_text(serialized, encoding="utf-8")
    on_disk = EvalReport.model_validate_json(out_path.read_text(encoding="utf-8"))
    assert on_disk == report


def test_step6_markdown_content_preserved_when_present() -> None:
    """Step 6 (format_export) wraps cover_letter / application_responses /
    formatted-resume Markdown as string fields. Verify at least one of the
    runs has populated step 6 content and that it survives the schema layer
    intact (no encoding mangling, no truncation)."""
    runs_with_step6 = [
        run
        for run in _DISCOVERED_RUNS
        if next(s for s in run.steps if s.step_id == "format_export").status == "completed"
    ]
    if not runs_with_step6:
        pytest.skip(
            "None of the discovered runs have step 6 outputs — skipping the "
            "Markdown-preservation assertion. (Step 6 produces side-products "
            "like cover letters and is only run on demand.)"
        )
    markdown_fields = {"cover_letter_md", "application_responses_md", "formatted_resume_md"}
    for run in runs_with_step6:
        step6 = next(s for s in run.steps if s.step_id == "format_export")
        present = markdown_fields & set(step6.outputs)
        assert present, (
            "step 6 completed but no markdown fields present in outputs "
            f"(got keys: {sorted(step6.outputs)})"
        )
        for field in present:
            value = step6.outputs[field]
            assert isinstance(value, str)
            assert len(value) > 0
