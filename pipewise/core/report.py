"""`EvalReport` — the result of running scorers across one or more `PipelineRun`s.

A report captures every `ScoreResult` produced during one eval invocation:
- per-step scores (`StepScorer` outputs, scoped to a specific step)
- per-run scores (`RunScorer` outputs, scoped to a whole run)

The JSON shape is intentionally stable and minimal. The Phase 3 CLI
(`pipewise diff`) and the Phase 5 GitHub Action PR-comment bot both consume
this schema; breaking the JSON shape post-v1.0 would break both consumers.

Storage layout: each `pipewise eval`
invocation writes to a timestamped directory under `pipewise/reports/`,
never overwriting prior output.
"""

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from pipewise.core.scorer import ScoreResult


class StepScoreEntry(BaseModel):
    """One scorer's result for one step within a run."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    """`step_id` of the `StepExecution` that was scored."""

    scorer_name: str = Field(min_length=1)
    """The scoring scorer's `name` attribute (must be unique within the
    report's scorer set so consumers can find it deterministically)."""

    result: ScoreResult


class RunScoreEntry(BaseModel):
    """One scorer's result for the entire run."""

    model_config = ConfigDict(extra="forbid")

    scorer_name: str = Field(min_length=1)
    result: ScoreResult


class RunEvalResult(BaseModel):
    """All scorer results for a single `PipelineRun`.

    Provenance fields (`pipeline_name`, `adapter_name`, `adapter_version`)
    duplicate the source `PipelineRun` — they're snapshotted into the report
    so the report stays interpretable even after the source run is moved or
    archived. (Runs are immutable / append-only at the filesystem layer, but reports
    should not depend on the source files still being reachable.)
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    pipeline_name: str = Field(min_length=1)
    adapter_name: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    pipeline_version: str | None = None

    step_scores: list[StepScoreEntry] = Field(default_factory=list)
    run_scores: list[RunScoreEntry] = Field(default_factory=list)

    def all_results(self) -> list[ScoreResult]:
        """All `ScoreResult`s for this run, step + run-level concatenated."""
        return [e.result for e in self.step_scores] + [e.result for e in self.run_scores]

    def all_passed(self) -> bool:
        """True iff no score in this run failed (skipped scores are ignored).

        Note: vacuously True when no scorers ran AND when every scorer was
        skipped. Consumers that want to distinguish "all passed" from
        "nothing scored" or "everything skipped" should check
        `len(self.all_results())` and `skipped_score_count()` first.
        """
        return all(r.status != "failed" for r in self.all_results())


class EvalReport(BaseModel):
    """Aggregate result of one `pipewise eval` invocation."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    """Unique identifier for this report. The runner generates it per
    invocation — typically `<dataset_name>_<ISO8601-timestamp>`."""

    generated_at: AwareDatetime

    pipewise_version: str = Field(min_length=1)
    """`pipewise.__version__` at the time of generation. Affects how
    consumers should interpret schema fields if pipewise's schema evolves
    across releases."""

    dataset_name: str | None = None
    """Human-readable name of the dataset that was evaluated, if any
    (e.g., `"news-analysis-golden-v1"`). Optional — ad-hoc evals may not
    have a named dataset."""

    scorer_names: list[str] = Field(default_factory=list)
    """All scorer names that were invoked across this eval. Snapshotted
    by the runner before execution begins. Useful for distinguishing
    "scorer didn't produce a result" from "scorer never ran" — if a name
    is in this list but absent from a run's entries, the scorer failed
    or was filtered out for that specific run."""

    runs: list[RunEvalResult] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Adapter / runner-specific data. Same role as the `metadata` escape
    hatch on `PipelineRun` and `StepExecution`."""

    # ─── Aggregation helpers ──────────────────────────────────────────────
    # These are methods (not @computed_field) so they don't bloat the JSON.
    # The CLI / PR-comment bot can derive them on read.

    def all_results(self) -> list[ScoreResult]:
        """Every `ScoreResult` in the report, across all runs."""
        return [r for run in self.runs for r in run.all_results()]

    def total_score_count(self) -> int:
        return sum(len(r.all_results()) for r in self.runs)

    def passing_score_count(self) -> int:
        return sum(1 for r in self.all_results() if r.status == "passed")

    def failing_score_count(self) -> int:
        return sum(1 for r in self.all_results() if r.status == "failed")

    def skipped_score_count(self) -> int:
        return sum(1 for r in self.all_results() if r.status == "skipped")

    def passing_run_ids(self) -> list[str]:
        """`run_id`s where every scorer passed (vacuously includes runs
        with zero scorers — see `RunEvalResult.all_passed`)."""
        return [r.run_id for r in self.runs if r.all_passed()]

    def failing_run_ids(self) -> list[str]:
        """`run_id`s where at least one scorer failed."""
        return [r.run_id for r in self.runs if not r.all_passed()]

    def find_run(self, run_id: str) -> RunEvalResult | None:
        """Return the `RunEvalResult` for a specific run, if present."""
        for r in self.runs:
            if r.run_id == run_id:
                return r
        return None

    def find_scorer_result(
        self,
        run_id: str,
        scorer_name: str,
        step_id: str | None = None,
    ) -> ScoreResult | None:
        """Find a specific scorer's result.

        If `step_id` is given, searches step-level scores; otherwise searches
        run-level scores. Returns None when no matching entry exists (rather
        than raising) so consumers can distinguish absent from failing.
        """
        run_result = self.find_run(run_id)
        if run_result is None:
            return None
        if step_id is not None:
            for step_entry in run_result.step_scores:
                if step_entry.step_id == step_id and step_entry.scorer_name == scorer_name:
                    return step_entry.result
            return None
        for run_entry in run_result.run_scores:
            if run_entry.scorer_name == scorer_name:
                return run_entry.result
        return None
