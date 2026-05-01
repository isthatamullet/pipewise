"""PipelineRun and StepExecution — the central pipewise data model.

A `PipelineRun` is the record of one execution of any multi-step LLM pipeline,
expressed as an ordered sequence of `StepExecution`s.

Pipeline definitions can be DAGs with branches and conditional steps, but a
single run is always a linear "what actually happened." Branches are captured
by which `step_id` was executed; skipped steps are recorded with
`status="skipped"`. This keeps the schema small while still expressing both
linear (FactSpark-shape) and branching (resume-tailor-shape) pipelines.

Design rationale and locked decisions are tracked in the project's internal
plan + decisions log.

## Schema-level conventions worth knowing

- **`extra="forbid"`**: unknown top-level fields raise `ValidationError`. The
  encouraged extension mechanism is the `metadata` dict on each model. Why:
  silent-drop (Pydantic's default) would let adapter typos lose data without
  warning; forbid surfaces the convention loudly.
- **Timezone-aware datetimes only**: naive datetimes are rejected. Pipewise
  data is meant to be portable across machines/CI runners and comparable for
  regression detection; mixed tz-aware and tz-naive datetimes are a footgun.
- **Append-only / immutable**: not enforced by `frozen=True` on the models
  (scorers need to compute on these structures in-memory). Immutability is
  enforced at the filesystem layer via timestamped, never-overwritten files
 .
"""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

StepStatus = Literal["completed", "skipped", "failed"]
"""Lifecycle states for a single step execution.

`"running"` is intentionally absent — pipewise EVALUATES completed pipeline
runs, not in-flight ones. Adapters MUST emit steps with a terminal status.
If the step's source pipeline crashed mid-execution, record `status="failed"`
with whatever `error` and `completed_at` data is available (both can be None
if the source pipeline didn't capture them — pipewise prefers honest absence
over fabrication).
"""

RunStatus = Literal["completed", "partial", "failed"]
"""Lifecycle states for an entire pipeline run.

`partial` means at least one step completed but the run did not finish cleanly
(e.g., a non-terminal step failed or was skipped in a way that prevented later
steps from running).
"""


class StepExecution(BaseModel):
    """Record of one step's execution within a `PipelineRun`.

    Adapters produce these by reading their pipeline's outputs and mapping
    each step onto this shape. The `inputs` and `outputs` dicts are opaque
    to pipewise — scorers know how to interpret per-pipeline content.

    See the worked examples in this docstring + the schema reference docs.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    """Stable identifier for this step (e.g., "analyze_posting", "write_resume_hybrid").

    Adapters MUST use stable, meaningful IDs — not "step_N" — because pipelines
    with variants (e.g., resume's step 4 vs. step 4b) need to record which
    variant ran. The `step_id` is what survives schema-level reasoning about
    "did the same step run last time?"
    """

    step_name: str = Field(min_length=1)
    """Human-readable name for display."""

    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    status: StepStatus
    error: str | None = None

    executor: str | None = None
    """Agent / skill / script name that ran this step (e.g., "quality-check")."""

    model: str | None = None
    """Model identifier (e.g., "claude-opus-4-7", "gemini-3.1-pro")."""

    provider: str | None = None
    """Model provider (e.g., "anthropic", "google")."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    """Opaque input payload. Schema doesn't interpret content; scorers do."""

    outputs: dict[str, Any] = Field(default_factory=dict)
    """Opaque output payload. Schema doesn't interpret content; scorers do."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Adapter-specific data that doesn't fit the core fields. The encouraged
    extension point — `extra="forbid"` rejects unknown top-level fields, so
    everything pipeline-specific belongs here."""

    @model_validator(mode="after")
    def _completed_status_requires_completed_at(self) -> Self:
        if self.status == "completed" and self.completed_at is None:
            raise ValueError(
                "completed_at is required when status='completed' "
                "(use 'failed' or 'skipped' if the end time is unknown)"
            )
        return self


class PipelineRun(BaseModel):
    """Record of one execution of any multi-step LLM pipeline.

    The central pipewise data structure. Adapters convert their pipeline's
    raw outputs into this shape; scorers consume it; the CLI inspects, evals,
    and diffs runs of this shape.

    A single run is always a linear sequence of `StepExecution`s, even when
    the underlying pipeline definition is a DAG. Branches and conditional
    steps are captured by which `step_id` actually ran; skips are recorded
    with `status="skipped"`. /* doc continued */
    §4.5 for storage / immutability rules.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    """Globally unique identifier for this run.

    Used in default filenames, so it must produce a sensible
    filename slug — adapters typically use a UUID or a human-readable
    composite like `<pipeline>_<input-key>_<timestamp>`.
    """

    pipeline_name: str = Field(min_length=1)
    """Stable name for the pipeline (e.g., "factspark", "resume-tailor")."""

    pipeline_version: str | None = None
    """Semver of the pipeline definition (your prompts), if versioned."""

    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    status: RunStatus

    initial_input: dict[str, Any] = Field(default_factory=dict)
    """Original input that started the run (article URL, job posting, etc.)."""

    steps: list[StepExecution] = Field(default_factory=list)
    """Steps in the order they actually executed."""

    final_output: dict[str, Any] | None = None
    """Aggregated final output. Often equal to `steps[-1].outputs`; populate
    only when the pipeline produces a distinct end-of-run summary."""

    total_cost_usd: float | None = Field(default=None, ge=0)
    total_input_tokens: int | None = Field(default=None, ge=0)
    total_output_tokens: int | None = Field(default=None, ge=0)
    total_latency_ms: int | None = Field(default=None, ge=0)

    adapter_name: str = Field(min_length=1)
    """Name of the pipewise adapter that produced this run."""

    adapter_version: str = Field(min_length=1)
    """Version of that adapter — required so a run can always be traced
    back to the converter that built it (see the storage rules)."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Adapter-specific data that doesn't fit the core fields. Same role
    as `StepExecution.metadata` — see that field's docstring."""

    @model_validator(mode="after")
    def _completed_status_requires_completed_at(self) -> Self:
        if self.status == "completed" and self.completed_at is None:
            raise ValueError(
                "completed_at is required when status='completed' "
                "(use 'partial' or 'failed' if the end time is unknown)"
            )
        return self


# Re-export `datetime` for convenience: most adapters need it for the
# `started_at` / `completed_at` fields, and importing it from pipewise
# alongside the schema keeps adapter code tidy.
__all__ = [
    "PipelineRun",
    "RunStatus",
    "StepExecution",
    "StepStatus",
    "datetime",
]
