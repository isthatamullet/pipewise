"""Eval-time adapter API: ``load_run`` + ``default_scorers``.

Deterministic by construction — reads ``PipelineRun`` JSON from disk and
exposes the default scorer suite. No LLM calls, no network, no agent
invocation. Same JSON in, same scores out.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pipewise.core.schema import PipelineRun
from pipewise.scorers.budget import CostBudgetScorer, LatencyBudgetScorer
from pipewise.scorers.json_schema import JsonSchemaScorer

if TYPE_CHECKING:
    from pipewise.core.scorer import RunScorer, StepScorer


def load_run(path: str | Path) -> PipelineRun:
    """Read a captured ``PipelineRun`` from a JSON file."""
    text = Path(path).read_text(encoding="utf-8")
    return PipelineRun.model_validate_json(text)


_AGENT_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["content", "stop_reason"],
    "properties": {
        "content": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type"],
            },
        },
        "stop_reason": {"type": ["string", "null"]},
    },
}


def default_scorers() -> tuple[list[StepScorer], list[RunScorer]]:
    """Return ``(step_scorers, run_scorers)`` for typical Anthropic captures.

    The default suite covers step + run scope:

    * ``JsonSchemaScorer`` validates that every non-skipped *agent* step's
      outputs conform to the Anthropic ``Message`` shape (content blocks +
      ``stop_reason``). Tool steps are out of scope here — pipewise's runner
      auto-skips scopes that don't match.
    * ``LatencyBudgetScorer`` caps total run latency at 60 s, generous for
      multi-iteration agent loops on Sonnet/Opus.
    * ``CostBudgetScorer`` caps total run cost at $0.10 USD with
      ``on_missing="skip"`` so adopters running models outside our small
      pricing table aren't penalized for missing-cost data.

    Adopters extend these lists with regex / embedding / exact-match scorers
    targeted at their specific output shapes.
    """
    step_scorers: list[StepScorer] = [
        JsonSchemaScorer(
            schema=_AGENT_OUTPUT_SCHEMA,
            name="anthropic_agent_response_shape",
            applies_to_step_ids=[f"agent__{i}" for i in range(1, 9)],
        ),
    ]
    run_scorers: list[RunScorer] = [
        LatencyBudgetScorer(budget_ms=60_000, name="run_latency_60s"),
        CostBudgetScorer(budget_usd=0.10, on_missing="skip", name="run_cost_10c"),
    ]
    return step_scorers, run_scorers
