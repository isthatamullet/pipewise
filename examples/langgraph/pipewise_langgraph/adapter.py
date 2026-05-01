"""Eval-time adapter API: ``load_run`` + ``default_scorers``.

This module is the deterministic half of the adapter — it reads ``PipelineRun``
JSON from disk and exposes the default scorer suite. No LLM calls, no network,
no graph invocation. Same JSON in, same scores out.

Adopters extend the scorer set by importing additional pipewise scorers and
appending them to the lists returned by :func:`default_scorers`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pipewise.core.schema import PipelineRun
from pipewise.scorers.budget import LatencyBudgetScorer
from pipewise.scorers.json_schema import JsonSchemaScorer

if TYPE_CHECKING:
    from pipewise.core.scorer import RunScorer, StepScorer


def load_run(path: str | Path) -> PipelineRun:
    """Read a captured ``PipelineRun`` from a JSON file."""
    text = Path(path).read_text(encoding="utf-8")
    return PipelineRun.model_validate_json(text)


_LANGGRAPH_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["type", "content"],
                "properties": {
                    "type": {"type": "string"},
                },
            },
        },
    },
}


def default_scorers() -> tuple[list[StepScorer], list[RunScorer]]:
    """Return ``(step_scorers, run_scorers)`` for typical LangGraph captures.

    The default suite is intentionally small:

    * ``JsonSchemaScorer`` validates that every non-skipped step's outputs
      conform to the LangGraph messages-update shape (``{messages: [{type,
      content}, ...]}``). Catches adapter regressions that drop or mangle
      the message stream.
    * ``LatencyBudgetScorer`` caps total run latency at 30s — generous
      enough that free-tier LLM captures pass on first run.

    Adopters add their own scorers (regex on a derived ``text`` field, exact-
    match on tool outputs, embedding similarity on final responses, etc.) by
    extending these lists.
    """
    step_scorers: list[StepScorer] = [
        JsonSchemaScorer(schema=_LANGGRAPH_OUTPUT_SCHEMA, name="langgraph_messages_shape"),
    ]
    run_scorers: list[RunScorer] = [
        LatencyBudgetScorer(budget_ms=30_000, name="run_latency_30s"),
    ]
    return step_scorers, run_scorers
