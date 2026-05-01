"""Demo: run all eight Phase 2 scorers against a representative pipeline step.

Uses synthetic step data shaped like real news-analysis pipeline output so
the demo runs identically in every environment.

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


def _load_step() -> tuple[StepExecution, dict[str, Any]]:
    """Synthesize a representative pipeline step for the demo."""
    outputs = {
        "metadata": {
            "title": "Example Article",
            "source": "Example News",
            "published_date": "2026-04-27",
        },
        "extracted_items": [
            {
                "item_id": 1,
                "text": "Example item text.",
                "confidence_score": 75,
            }
        ],
    }

    started = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
    step = StepExecution(
        step_id="quality_check",
        step_name="Quality Check",
        started_at=started,
        completed_at=started + timedelta(seconds=5),
        status="completed",
        executor="quality-check",
        model="claude-opus-4-7",
        provider="anthropic",
        outputs=outputs,
    )
    return step, {"source": "synthetic step"}


def _expected_step_for(actual: StepExecution) -> StepExecution:
    """Build a near-copy of `actual` to use as the comparison target.

    Mutate one numeric field by 5 so the tolerance scorer has something
    interesting to report rather than always passing trivially.
    """
    expected_outputs = json.loads(json.dumps(actual.outputs))
    items = expected_outputs.get("extracted_items") or []
    if items and isinstance(items[0], dict) and "confidence_score" in items[0]:
        items[0]["confidence_score"] = max(0, items[0]["confidence_score"] - 5)
    return actual.model_copy(update={"outputs": expected_outputs})


def _build_run(step: StepExecution) -> PipelineRun:
    return PipelineRun(
        run_id="demo-run",
        pipeline_name="news-analysis",
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
    verdict_map = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}
    verdict = verdict_map.get(result.status, "?")
    score_str = f"score={result.score:.3f}" if result.score is not None else "score= --- "
    line = f"  [{verdict:4}] {score_str}  {scorer_name}"
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
        "ExactMatchScorer(fields=['metadata'])",
        ExactMatchScorer(fields=["metadata"]).score(step, expected),
    )

    _print_result(
        "RegexScorer(field='_serialized', pattern=r'Example|Article')",
        # outputs is a nested dict; demonstrate the scorer on a string field
        # by regexing the whole step's serialized outputs.
        RegexScorer(field="_serialized", pattern=r"Example|Article").score(
            step.model_copy(update={"outputs": {"_serialized": json.dumps(step.outputs)}})
        ),
    )

    if (
        step.outputs.get("extracted_items")
        and isinstance(step.outputs["extracted_items"], list)
        and step.outputs["extracted_items"]
    ):
        # Numeric tolerance demo: pull confidence_score up to top-level for the demo
        confidence = step.outputs["extracted_items"][0].get("confidence_score")
        if confidence is not None:
            actual_flat = step.model_copy(update={"outputs": {"confidence_score": confidence}})
            expected_confidence = expected.outputs["extracted_items"][0]["confidence_score"]
            expected_flat = expected.model_copy(
                update={"outputs": {"confidence_score": expected_confidence}}
            )
            _print_result(
                "NumericToleranceScorer(field='confidence_score', tolerance=10)",
                NumericToleranceScorer(field="confidence_score", tolerance=10).score(
                    actual_flat, expected_flat
                ),
            )

    _print_result(
        "JsonSchemaScorer(schema=...)",
        JsonSchemaScorer(
            schema={
                "type": "object",
                "required": ["metadata"],
                "properties": {
                    "metadata": {
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
        actual_title = step.outputs.get("metadata", {}).get("title", "")
        expected_title = expected.outputs.get("metadata", {}).get("title", "")
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
                        "The step's outputs must include a metadata "
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
