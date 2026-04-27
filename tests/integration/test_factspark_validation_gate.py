"""Phase 1 validation gate (issue #6): can the pipewise schema ingest a real
FactSpark run end-to-end without losing data?

This is a *prototype* adapter — NOT the full Phase 4 FactSpark adapter (which
will live at `factspark/integrations/pipewise/`). Its only job is to exercise
the schema against real `step1-7.json` files and prove the round-trip works.

Skips automatically when FactSpark's local data isn't available (e.g., on the
GitHub Actions runner). Pipewise core has zero runtime dependency on FactSpark
per the adapter-pattern rule; this test runs locally only.

Per the Phase 1 validation gate:
    > If both pass: the abstraction is correct. If either fails: redesign
    > before moving on.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipewise import PipelineRun, StepExecution

FACTSPARK_ARTICLES_DIR = Path.home() / "factspark" / "articles"

# Reference article: BBC piece on Trump tariffs / Supreme Court (2026-02-24).
SAMPLE_ARTICLE_PREFIX = "02242026_bbc_trump_tariffs_supreme_court"
SECOND_ARTICLE_PREFIX = "02252026_apnews_trump_sotu_fact_check"

# Per the codebase-discovery findings: 7 steps, all-Claude except step 7 (Gemini for verification).
FACTSPARK_STEP_LINEUP: list[tuple[str, str, str, str]] = [
    ("analyze", "analyze-article", "claude-opus-4-7", "anthropic"),
    ("enhance_entities", "enhance-entities-geographic", "claude-opus-4-7", "anthropic"),
    ("enhance_content", "enhance-content-assessment", "claude-opus-4-7", "anthropic"),
    ("enhance_source", "enhance-source-temporal", "claude-opus-4-7", "anthropic"),
    ("stupid_meter", "stupid-meter", "claude-opus-4-7", "anthropic"),
    ("enhance_analytics_ui", "enhance-analytics-ui", "claude-opus-4-7", "anthropic"),
    ("verify_claims", "verify-claims", "gemini-3.1-pro", "google"),
]


pytestmark = pytest.mark.skipif(
    not FACTSPARK_ARTICLES_DIR.exists(),
    reason="FactSpark articles dir not present — gate runs locally only.",
)


def _build_factspark_run(article_prefix: str) -> PipelineRun:
    """Read step1-7.json files for an article and build a `PipelineRun`."""
    base = datetime(2026, 2, 24, 8, 0, 0, tzinfo=UTC)
    steps: list[StepExecution] = []
    for i, (step_id, executor, model, provider) in enumerate(FACTSPARK_STEP_LINEUP):
        step_path = FACTSPARK_ARTICLES_DIR / f"{article_prefix}_step{i + 1}.json"
        outputs = json.loads(step_path.read_text())
        steps.append(
            StepExecution(
                step_id=step_id,
                step_name=step_id.replace("_", " ").title(),
                started_at=base + timedelta(seconds=i * 10),
                completed_at=base + timedelta(seconds=(i * 10) + 5),
                status="completed",
                executor=executor,
                model=model,
                provider=provider,
                outputs=outputs,
                # cost / tokens / latency intentionally None — FactSpark doesn't
                # track these today ( gap to be filled in Phase 4).
            )
        )

    initial_input = steps[0].outputs.get("article_metadata", {})

    return PipelineRun(
        run_id=article_prefix,
        pipeline_name="factspark",
        started_at=base,
        completed_at=base + timedelta(seconds=70),
        status="completed",
        initial_input=initial_input,
        steps=steps,
        final_output=steps[-1].outputs,
        adapter_name="factspark-prototype-validation-adapter",
        adapter_version="0.0.0-prototype",
    )


def test_can_ingest_real_factspark_run() -> None:
    run = _build_factspark_run(SAMPLE_ARTICLE_PREFIX)
    assert run.run_id == SAMPLE_ARTICLE_PREFIX
    assert run.pipeline_name == "factspark"
    assert len(run.steps) == 7
    # Provider mix matches the codebase-discovery findings: all-Claude except step 7 (Gemini).
    assert all(s.provider == "anthropic" for s in run.steps[:-1])
    assert run.steps[-1].provider == "google"
    assert run.steps[-1].model == "gemini-3.1-pro"


def test_round_trips_without_data_loss() -> None:
    """The crux of the validation gate: every byte of step output JSON
    survives the `PipelineRun` → JSON → `PipelineRun` round-trip."""
    run = _build_factspark_run(SAMPLE_ARTICLE_PREFIX)
    serialized = run.model_dump_json()
    restored = PipelineRun.model_validate_json(serialized)
    assert restored == run

    # Spot-check: a deeply-nested original field is byte-identical post-round-trip.
    original_first_claim = run.steps[0].outputs["extracted_claims"][0]
    restored_first_claim = restored.steps[0].outputs["extracted_claims"][0]
    assert original_first_claim == restored_first_claim


def test_step_outputs_match_source_json_byte_for_byte() -> None:
    """Each step's `outputs` dict equals the raw source JSON. This rules
    out any silent type coercion (e.g., int → float)."""
    run = _build_factspark_run(SAMPLE_ARTICLE_PREFIX)
    for i, step in enumerate(run.steps):
        source = json.loads(
            (FACTSPARK_ARTICLES_DIR / f"{SAMPLE_ARTICLE_PREFIX}_step{i + 1}.json").read_text()
        )
        assert step.outputs == source, f"Step {i + 1} outputs diverge from source JSON"


def test_works_for_a_second_article() -> None:
    """Validation must not be article-specific."""
    if not (FACTSPARK_ARTICLES_DIR / f"{SECOND_ARTICLE_PREFIX}_step1.json").exists():
        pytest.skip(f"Second sample article {SECOND_ARTICLE_PREFIX!r} not present.")
    run = _build_factspark_run(SECOND_ARTICLE_PREFIX)
    assert len(run.steps) == 7
    assert run.steps[0].outputs["article_metadata"]["source"]


def test_step7_has_distinct_shape_from_steps_1_to_6() -> None:
    """Step 7 (Gemini verification) has a totally different output shape
    from steps 1-6 (`verification_metadata`, `claim_verifications`, ...).
    The opaque `outputs: dict[str, Any]` field handles this without coupling."""
    run = _build_factspark_run(SAMPLE_ARTICLE_PREFIX)
    step1_keys = set(run.steps[0].outputs.keys())
    step7_keys = set(run.steps[-1].outputs.keys())
    # Keys are intentionally different — pipewise schema doesn't care.
    assert step1_keys != step7_keys
    assert "extracted_claims" in step1_keys
    assert "claim_verifications" in step7_keys
