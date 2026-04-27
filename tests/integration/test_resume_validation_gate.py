"""Phase 1 validation gate (issue #7): can the pipewise schema ingest a real
resume-tailor run, including the hard-case branching and conditional steps?

Resume-tailor is "the hard case" per PLAN.md §2 — it stresses every part of
the abstraction:

- **Optional step 2** (discovery — often skipped). Captured here as
  `status="skipped"` with no source file present.
- **Step 4 vs step 4b branch** (chronological vs. hybrid). The schema captures
  which branch ran via `step_id`.
- **Mixed output formats** — steps 1-5 are JSON; step 6 produces Markdown
  (`*_ats_safe.md`); step 7 (Canva export) produces a PDF when it runs at all.
- **Conditional step 7** — gated by step 5 status. When it doesn't run, it's
  simply absent from the `steps` list (PLAN.md §4 design decision: "Single
  PipelineRun is always linear … branches are recorded by which step_id ran").

This is a *prototype* adapter — NOT the full Phase 4 adapter (which will live
at `tyler/integrations/pipewise/`). Pipewise core has zero runtime dependency
on the resume pipeline (PLAN.md §3); this test runs locally only.

Per PLAN.md §6 Phase 1 validation gate:
    > If both pass: the abstraction is correct. If either fails: redesign
    > before moving on.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipewise import PipelineRun, StepExecution

RESUME_DEEPINTENT_DIR = Path("/home/user/tyler/jobs/resumes/deepintent")
JOB_BASE = "deepintent_senior_program_manager"

pytestmark = pytest.mark.skipif(
    not RESUME_DEEPINTENT_DIR.exists(),
    reason="Resume pipeline data not present — gate runs locally only.",
)


def _build_resume_run() -> PipelineRun:
    """Build a `PipelineRun` from a real DeepIntent SPM job folder.

    Demonstrates: skipped step 2, chronological step 4 (not 4b), markdown
    output in step 6, and an absent step 7 (gated off by step 5).
    """
    base = datetime(2026, 4, 1, 8, 0, 0, tzinfo=UTC)
    steps: list[StepExecution] = []

    # Step 1 — analyze posting (always present).
    step1_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_step1.json"
    steps.append(
        StepExecution(
            step_id="analyze_posting",
            step_name="Analyze Posting",
            started_at=base,
            completed_at=base + timedelta(seconds=10),
            status="completed",
            executor="resume-step1-analyze-posting",
            model="claude-opus-4-7",
            provider="anthropic",
            outputs=json.loads(step1_path.read_text()),
        )
    )

    # Step 2 — discovery. Skipped: no file produced.
    step2_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_step2.json"
    if not step2_path.exists():
        steps.append(
            StepExecution(
                step_id="discovery",
                step_name="Discovery",
                started_at=base + timedelta(seconds=10),
                # No completed_at: the step never ran. Schema allows None on
                # `skipped` per PLAN.md §7 D11.
                status="skipped",
                metadata={"skip_reason": "step2 file absent — discovery not needed for this role"},
            )
        )

    # Step 3 — research company.
    step3_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_step3.json"
    steps.append(
        StepExecution(
            step_id="research_company",
            step_name="Research Company",
            started_at=base + timedelta(seconds=20),
            completed_at=base + timedelta(seconds=30),
            status="completed",
            executor="resume-step3",
            model="claude-opus-4-7",
            provider="anthropic",
            outputs=json.loads(step3_path.read_text()),
        )
    )

    # Step 4 — chronological branch (not 4b). The branch chosen is encoded
    # in `step_id`. If the file were named `*_step4b.json`, we'd use
    # `step_id="write_resume_hybrid"` instead.
    step4_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_step4.json"
    step4b_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_step4b.json"
    if step4_path.exists():
        chosen_step_id = "write_resume_chronological"
        chosen_path = step4_path
    elif step4b_path.exists():
        chosen_step_id = "write_resume_hybrid"
        chosen_path = step4b_path
    else:
        pytest.fail(f"Expected either step4 or step4b file in {RESUME_DEEPINTENT_DIR}")
    steps.append(
        StepExecution(
            step_id=chosen_step_id,
            step_name=chosen_step_id.replace("_", " ").title(),
            started_at=base + timedelta(seconds=30),
            completed_at=base + timedelta(seconds=60),
            status="completed",
            executor=f"resume-{chosen_step_id.replace('write_resume_', 'step4-write-resume-').replace('_', '-')}",
            model="claude-opus-4-7",
            provider="anthropic",
            outputs=json.loads(chosen_path.read_text()),
        )
    )

    # Step 5 — hiring-manager critique.
    step5_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_step5.json"
    steps.append(
        StepExecution(
            step_id="critique",
            step_name="Hiring Manager Critique",
            started_at=base + timedelta(seconds=60),
            completed_at=base + timedelta(seconds=80),
            status="completed",
            executor="resume-step5-hiring-manager-critique",
            model="claude-opus-4-7",
            provider="anthropic",
            outputs=json.loads(step5_path.read_text()),
        )
    )

    # Step 6 — format & export. Markdown output (different shape from JSON
    # steps). The adapter wraps the raw markdown in a typed dict so the
    # schema's `outputs: dict[str, Any]` can express it without coupling.
    step6_md_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_ats_safe.md"
    if step6_md_path.exists():
        steps.append(
            StepExecution(
                step_id="format_export",
                step_name="Format & Export",
                started_at=base + timedelta(seconds=80),
                completed_at=base + timedelta(seconds=90),
                status="completed",
                executor="resume-step6-format-export",
                outputs={
                    "format": "markdown",
                    "ats_target": "ats_safe",
                    "content": step6_md_path.read_text(),
                    # An adapter could also include `byte_size`, `line_count`,
                    # or any other adapter-relevant metadata.
                },
            )
        )

    # Step 7 — Canva export (gated off — no PDF artifact for this run).

    return PipelineRun(
        run_id=JOB_BASE,
        pipeline_name="resume-tailor",
        started_at=base,
        # status="partial" because step 7 was gated off — the run did not
        # finish all the steps the pipeline definition allows.
        status="partial",
        initial_input={"company": "DeepIntent", "role": "Senior Program Manager"},
        steps=steps,
        adapter_name="resume-tailor-prototype-validation-adapter",
        adapter_version="0.0.0-prototype",
    )


def test_can_ingest_real_resume_run() -> None:
    run = _build_resume_run()
    assert run.run_id == JOB_BASE
    assert run.pipeline_name == "resume-tailor"
    assert run.status == "partial"


def test_skipped_step_recorded_correctly() -> None:
    """Step 2 (discovery) was skipped — represented with status='skipped'
    and no completed_at, per PLAN.md §7 D11."""
    run = _build_resume_run()
    skipped = [s for s in run.steps if s.status == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].step_id == "discovery"
    assert skipped[0].completed_at is None


def test_step4_branch_captured_via_step_id() -> None:
    """Branching is recorded by which step_id ran (PLAN.md §4 design decision).
    Either 'write_resume_chronological' or 'write_resume_hybrid' — never both."""
    run = _build_resume_run()
    step4_ids = {s.step_id for s in run.steps if s.step_id.startswith("write_resume")}
    assert len(step4_ids) == 1
    assert step4_ids.pop() in {"write_resume_chronological", "write_resume_hybrid"}


def test_step6_markdown_output_round_trips() -> None:
    """Mixed-format output: step 6 is markdown, not JSON. The opaque outputs
    dict carries it without coupling the schema to any specific format."""
    run = _build_resume_run()
    step6 = next(s for s in run.steps if s.step_id == "format_export")
    assert step6.outputs["format"] == "markdown"
    assert isinstance(step6.outputs["content"], str)
    assert "TYLER GOHR" in step6.outputs["content"]


def test_step7_absent_when_gated_off() -> None:
    """Step 7 didn't run for this job — it's simply absent from the steps
    list. PLAN.md §4: 'Single PipelineRun is always linear … branches are
    recorded by which step_id ran.'"""
    run = _build_resume_run()
    assert not any(s.step_id == "export_canva" for s in run.steps)


def test_round_trips_without_data_loss() -> None:
    """Crux of the validation gate: every byte of every step's output —
    including the markdown step's text content — survives JSON round-trip."""
    run = _build_resume_run()
    serialized = run.model_dump_json()
    restored = PipelineRun.model_validate_json(serialized)
    assert restored == run

    # Spot-check: the markdown content survives byte-for-byte (catches any
    # silent newline / encoding mangling).
    original_md = next(s for s in run.steps if s.step_id == "format_export").outputs["content"]
    restored_md = next(s for s in restored.steps if s.step_id == "format_export").outputs["content"]
    assert original_md == restored_md


def test_step_outputs_match_source_json_for_json_steps() -> None:
    """JSON steps' outputs equal the raw source JSON byte-for-byte."""
    run = _build_resume_run()
    json_step_files = {
        "analyze_posting": "step1.json",
        "research_company": "step3.json",
        "critique": "step5.json",
    }
    for step in run.steps:
        if step.step_id in json_step_files:
            source_path = RESUME_DEEPINTENT_DIR / f"{JOB_BASE}_{json_step_files[step.step_id]}"
            source = json.loads(source_path.read_text())
            assert step.outputs == source, f"{step.step_id} outputs diverge from {source_path.name}"
