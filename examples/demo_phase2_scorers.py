"""Demo: run all eight Phase 2 scorers against a representative pipeline step.

Loads a real FactSpark step output from the local checkout if one is
available; otherwise falls back to a synthetic step with the same shape so
the demo always runs.

Usage::

    uv run python examples/demo_phase2_scorers.py
    uv run python examples/demo_phase2_scorers.py --use-llm    # real Anthropic API call

The `--use-llm` flag enables `LlmJudgeScorer` against the real Anthropic
API. Requires `ANTHROPIC_API_KEY` in the environment and the `[llm-judge]`
extra installed. Without the flag, `LlmJudgeScorer` is reported as skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pipewise import PipelineRun, StepExecution
from pipewise.scorers import (
    CostBudgetScorer,
    ExactMatchScorer,
    JsonSchemaScorer,
    LatencyBudgetScorer,
    NumericToleranceScorer,
    RegexScorer,
)

# These two are gated behind extras; import inside the demo functions so the
# script still runs when extras aren't installed.

# Sample FactSpark article — used when running locally with FactSpark checked out.
_LOCAL_FACTSPARK_STEP = (
    Path.home() / "factspark" / "articles" / "02242026_bbc_trump_tariffs_supreme_court_step5.json"
)


def _load_step() -> tuple[StepExecution, dict[str, Any]]:
    """Load a real FactSpark step output if available, else synthesize one."""
    if _LOCAL_FACTSPARK_STEP.exists():
        outputs = json.loads(_LOCAL_FACTSPARK_STEP.read_text())
        source = f"real FactSpark step ({_LOCAL_FACTSPARK_STEP.name})"
    else:
        outputs = {
            "article_metadata": {
                "title": "Example Article",
                "source": "Example News",
                "published_date": "2026-04-27",
            },
            "extracted_claims": [
                {
                    "claim_id": 1,
                    "text": "Example claim text.",
                    "stupidity_rating": 75,
                }
            ],
        }
        source = "synthetic step (FactSpark not present locally)"

    started = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
    step = StepExecution(
        step_id="stupid_meter",
        step_name="Stupid Meter",
        started_at=started,
        completed_at=started + timedelta(seconds=5),
        status="completed",
        executor="stupid-meter",
        model="claude-opus-4-7",
        provider="anthropic",
        outputs=outputs,
    )
    return step, {"source": source}


def _expected_step_for(actual: StepExecution) -> StepExecution:
    """Build a near-copy of `actual` to use as the comparison target.

    Mutate one numeric field by 5 so the tolerance scorer has something
    interesting to report rather than always passing trivially.
    """
    expected_outputs = json.loads(json.dumps(actual.outputs))
    claims = expected_outputs.get("extracted_claims") or []
    if claims and isinstance(claims[0], dict) and "stupidity_rating" in claims[0]:
        claims[0]["stupidity_rating"] = max(0, claims[0]["stupidity_rating"] - 5)
    return actual.model_copy(update={"outputs": expected_outputs})


def _build_run(step: StepExecution) -> PipelineRun:
    return PipelineRun(
        run_id="demo-run",
        pipeline_name="factspark",
        started_at=step.started_at,
        completed_at=step.completed_at,
        status="completed",
        steps=[step],
        adapter_name="demo-adapter",
        adapter_version="0.0.0-demo",
        total_cost_usd=0.025,
        total_latency_ms=4321,
    )


def _print_result(scorer_name: str, result: Any) -> None:
    verdict = "PASS" if result.passed else "FAIL"
    line = f"  [{verdict:4}] score={result.score:.3f}  {scorer_name}"
    print(line)
    if result.reasoning:
        first_line = result.reasoning.splitlines()[0]
        if len(first_line) > 80:
            first_line = first_line[:77] + "..."
        print(f"           reasoning: {first_line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Run LlmJudgeScorer against the real Anthropic API (costs money).",
    )
    args = parser.parse_args(argv)

    step, meta = _load_step()
    expected = _expected_step_for(step)
    run = _build_run(step)

    print(f"Source: {meta['source']}")
    print(f"Step: {step.step_id} ({step.step_name})")
    print()
    print("Running scorers:")

    # 1-4: trivial step scorers
    _print_result(
        "ExactMatchScorer(fields=['article_metadata'])",
        ExactMatchScorer(fields=["article_metadata"]).score(step, expected),
    )

    _print_result(
        "RegexScorer(field='article_metadata.title' wrapper, pattern=r'.+')",
        # outputs is a nested dict; demonstrate the scorer on a string field
        # by pulling a top-level reference value into a flattened view. For
        # this demo we just regex the whole step's serialized outputs.
        RegexScorer(field="_serialized", pattern=r"Trump|Example").score(
            step.model_copy(update={"outputs": {"_serialized": json.dumps(step.outputs)}})
        ),
    )

    if (
        step.outputs.get("extracted_claims")
        and isinstance(step.outputs["extracted_claims"], list)
        and step.outputs["extracted_claims"]
    ):
        # Numeric tolerance demo: pull stupidity_rating up to top-level for the demo
        rating = step.outputs["extracted_claims"][0].get("stupidity_rating")
        if rating is not None:
            actual_flat = step.model_copy(update={"outputs": {"rating": rating}})
            expected_rating = expected.outputs["extracted_claims"][0]["stupidity_rating"]
            expected_flat = expected.model_copy(update={"outputs": {"rating": expected_rating}})
            _print_result(
                "NumericToleranceScorer(field='rating', tolerance=10)",
                NumericToleranceScorer(field="rating", tolerance=10).score(
                    actual_flat, expected_flat
                ),
            )

    _print_result(
        "JsonSchemaScorer(schema=...)",
        JsonSchemaScorer(
            schema={
                "type": "object",
                "required": ["article_metadata"],
                "properties": {
                    "article_metadata": {
                        "type": "object",
                        "required": ["title"],
                        "properties": {"title": {"type": "string"}},
                    },
                },
            }
        ).score(step),
    )

    # 5: embedding similarity (gated behind [embeddings])
    try:
        from pipewise.scorers import EmbeddingSimilarityScorer

        emb_scorer = EmbeddingSimilarityScorer(field="title", threshold=0.7)
        # Flatten title to top-level for the demo
        actual_title = step.outputs.get("article_metadata", {}).get("title", "")
        expected_title = expected.outputs.get("article_metadata", {}).get("title", "")
        actual_flat = step.model_copy(update={"outputs": {"title": actual_title}})
        expected_flat = expected.model_copy(update={"outputs": {"title": expected_title}})
        try:
            _print_result(
                "EmbeddingSimilarityScorer(field='title', threshold=0.7)",
                emb_scorer.score(actual_flat, expected_flat),
            )
        except ImportError:
            print(
                "  [SKIP] EmbeddingSimilarityScorer "
                "(install with: pip install 'pipewise[embeddings]')"
            )
    except ImportError:
        print("  [SKIP] EmbeddingSimilarityScorer (extra not installed)")

    # 6: LLM judge (only with --use-llm)
    if args.use_llm:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("  [SKIP] LlmJudgeScorer (--use-llm given but ANTHROPIC_API_KEY not set)")
        else:
            try:
                from pipewise.scorers import LlmJudgeScorer

                judge = LlmJudgeScorer(
                    rubric=(
                        "The step's outputs must include an article_metadata "
                        "object with a non-empty title. Score 1.0 for "
                        "well-formed, 0.5 for partial, 0.0 for missing."
                    ),
                    cost_ceiling_usd=0.50,
                )
                _print_result("LlmJudgeScorer (real API)", judge.score(step))
                print(f"           ${judge.cumulative_cost_usd:.4f} spent")
            except ImportError:
                print("  [SKIP] LlmJudgeScorer (install with: pip install 'pipewise[llm-judge]')")
    else:
        print("  [SKIP] LlmJudgeScorer (pass --use-llm to enable)")

    # 7-8: run scorers
    _print_result(
        "CostBudgetScorer(budget_usd=0.05)",
        CostBudgetScorer(budget_usd=0.05).score(run),
    )
    _print_result(
        "LatencyBudgetScorer(budget_ms=10_000)",
        LatencyBudgetScorer(budget_ms=10_000).score(run),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
