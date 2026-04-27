"""Scorer protocols and `ScoreResult` — the contract every scorer implements.

A scorer evaluates one aspect of a step or run. Pipewise ships built-in
scorers in Phase 2 (`ExactMatchScorer`, `LlmJudgeScorer`, `CostBudgetScorer`,
etc.); third parties can implement their own by satisfying these Protocols.

Two flavors:
- `StepScorer` — operates on a single `StepExecution` (with optional expected)
- `RunScorer` — operates on an entire `PipelineRun` (e.g., total-cost budget)

Design rationale lives in `PLAN.md` §5.
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from pipewise.core.schema import PipelineRun, StepExecution


class ScoreResult(BaseModel):
    """The output of one scorer evaluating one step or run.

    `score` is canonical 0.0-1.0 so reports can compare results across
    scorers. `passed` is the boolean verdict (typically threshold-based —
    each scorer decides what "pass" means for itself).
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    """Canonical score in [0.0, 1.0]. 1.0 = perfect; 0.0 = total mismatch."""

    passed: bool
    """Whether this score crosses the scorer's pass threshold. Scorers
    define their own threshold; the boolean is what reports aggregate."""

    reasoning: str | None = None
    """Free-text explanation. Required reading for LLM-judge scorers and
    valuable for human review of regressions; optional for mechanical
    scorers (e.g., `ExactMatchScorer`) where the verdict is self-evident."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Scorer-specific data (e.g., per-field diff for `ExactMatchScorer`,
    judge-model/temperature for `LlmJudgeScorer`). Same role as the
    `metadata` escape hatch on `PipelineRun` and `StepExecution`."""


@runtime_checkable
class StepScorer(Protocol):
    """Evaluates one step. Optionally compares actual vs. expected.

    Concrete scorers expose a `name` attribute (used in eval reports) and
    a `score()` method. They MAY ignore `expected` if the scoring logic
    is self-contained (e.g., a regex match against `actual.outputs`).
    """

    name: str

    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult: ...


@runtime_checkable
class RunScorer(Protocol):
    """Evaluates an entire run. Optionally compares actual vs. expected.

    Useful for cross-step properties — total cost, total latency,
    end-to-end correctness, regression diffing across two runs.
    """

    name: str

    def score(
        self,
        actual: PipelineRun,
        expected: PipelineRun | None = None,
    ) -> ScoreResult: ...
