"""Scorer protocols and `ScoreResult` — the contract every scorer implements.

A scorer evaluates one aspect of a step or run. Pipewise ships built-in
scorers in Phase 2 (`ExactMatchScorer`, `LlmJudgeScorer`, `CostBudgetScorer`,
etc.); third parties can implement their own by satisfying these Protocols.

Two flavors:
- `StepScorer` — operates on a single `StepExecution` (with optional expected)
- `RunScorer` — operates on an entire `PipelineRun` (e.g., total-cost budget)

Design rationale and the broader scoring contract live in the internal design notes.
"""

from typing import Any, Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipewise.core.schema import PipelineRun, StepExecution

ScoreStatus = Literal["passed", "failed", "skipped"]


class ScoreResult(BaseModel):
    """The output of one scorer evaluating one step or run.

    `status` is the tri-state verdict. `score` is canonical 0.0-1.0 when
    the scorer actually ran; `None` when `status == "skipped"` because a
    skipped scorer didn't compute a score and forcing a sentinel would lie
    about the absence of signal.
    """

    model_config = ConfigDict(extra="forbid")

    status: ScoreStatus
    """`"passed"`, `"failed"`, or `"skipped"`. `"skipped"` means the
    scorer did not actually evaluate — e.g., the step was out of the
    scorer's `applies_to_step_ids` scope, or a budget scorer's
    `on_missing="skip"` path fired with no upstream data."""

    score: float | None = Field(default=None, ge=0.0, le=1.0)
    """Canonical score in [0.0, 1.0] when the scorer ran; `None` iff
    `status == "skipped"`. Required when `status` is `"passed"` or
    `"failed"` (enforced by validator)."""

    reasoning: str | None = None
    """Free-text explanation. Required reading for LLM-judge scorers and
    valuable for human review of regressions; optional for mechanical
    scorers (e.g., `ExactMatchScorer`) where the verdict is self-evident."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Scorer-specific data (e.g., per-field diff for `ExactMatchScorer`,
    judge-model/temperature for `LlmJudgeScorer`). Same role as the
    `metadata` escape hatch on `PipelineRun` and `StepExecution`."""

    @model_validator(mode="after")
    def _score_required_unless_skipped(self) -> Self:
        if self.status != "skipped" and self.score is None:
            raise ValueError("score is required when status is 'passed' or 'failed'")
        return self


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
