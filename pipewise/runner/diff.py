"""Diff two `EvalReport`s — the core of regression detection.

Phase 3 #26. Categorizes every (run_id, scorer_name, step_id?) entry across
two reports into one of: regression (was passing, now failing), improvement
(was failing, now passing), score delta (pass status unchanged but score
moved), newly_skipped / newly_running (transitions involving the `skipped`
state), or absent-in-one. The diff is itself a Pydantic model so the CLI's
`--format json` flag can serialize it for the GitHub-Action consumer.

Skipped semantics: `passed → skipped` is NOT a regression by default
(narrowing scope via `applies_to_step_ids` is intentional). Use the
`pipewise diff --strict` flag to treat `passed → skipped` transitions as
regressions for CI-exit-code purposes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from pipewise.core.report import EvalReport, RunEvalResult
from pipewise.core.scorer import ScoreResult, ScoreStatus


class _ScoreEntryKey(NamedTuple):
    run_id: str
    step_id: str | None
    scorer_name: str


class ScoreDiffEntry(BaseModel):
    """One scorer entry's transition between two reports."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    step_id: str | None = None
    scorer_name: str
    score_a: float | None
    score_b: float | None
    status_a: ScoreStatus
    status_b: ScoreStatus

    @property
    def delta(self) -> float | None:
        if self.score_a is None or self.score_b is None:
            return None
        return self.score_b - self.score_a


class ReportDiff(BaseModel):
    """Aggregate diff of two `EvalReport`s."""

    model_config = ConfigDict(extra="forbid")

    runs_a_only: list[str] = Field(default_factory=list)
    """`run_id`s present in report A but not B."""

    runs_b_only: list[str] = Field(default_factory=list)
    """`run_id`s present in report B but not A."""

    regressions: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries that passed in A but failed in B (`passed → failed`)."""

    improvements: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries that failed in A but passed in B (`failed → passed`)."""

    score_deltas: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries whose pass/fail status is unchanged but whose score moved.
    Excludes entries where either side is skipped (no comparable score)."""

    newly_skipped: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries that ran in A but were skipped in B (`passed → skipped` or
    `failed → skipped`). Not a regression by default — narrowing scope is
    intentional. The `--strict` flag on `pipewise diff` treats
    `passed → skipped` transitions as regressions for CI-exit-code purposes."""

    newly_running: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries that were skipped in A but ran in B (`skipped → passed` or
    `skipped → failed`). Not an improvement by default — the new signal
    may or may not be good news, surfaced for visibility only."""

    absent_in_a: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries present in B but missing from A (same run, new scorer)."""

    absent_in_b: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries present in A but missing from B (same run, removed scorer)."""

    def has_regressions(self) -> bool:
        """True iff there are any `passed → failed` transitions.

        This is what `pipewise diff` uses for its non-zero exit code by
        default. The `--strict` flag widens the gate via `has_strict_regressions()`.
        """
        return bool(self.regressions)

    def has_strict_regressions(self) -> bool:
        """True iff there are regressions OR any `passed → skipped` transition.

        Used by `pipewise diff --strict` to refuse intentional scope narrowing
        as a CI-passing change. `failed → skipped` is still allowed because
        the scorer wasn't passing before either.
        """
        if self.regressions:
            return True
        return any(e.status_a == "passed" for e in self.newly_skipped)

    def total_changes(self) -> int:
        return (
            len(self.regressions)
            + len(self.improvements)
            + len(self.score_deltas)
            + len(self.newly_skipped)
            + len(self.newly_running)
            + len(self.absent_in_a)
            + len(self.absent_in_b)
        )


def _index_run(run: RunEvalResult) -> dict[_ScoreEntryKey, ScoreResult]:
    index: dict[_ScoreEntryKey, ScoreResult] = {}
    for step_entry in run.step_scores:
        index[_ScoreEntryKey(run.run_id, step_entry.step_id, step_entry.scorer_name)] = (
            step_entry.result
        )
    for run_entry in run.run_scores:
        index[_ScoreEntryKey(run.run_id, None, run_entry.scorer_name)] = run_entry.result
    return index


def _make_entry(key: _ScoreEntryKey, a: ScoreResult, b: ScoreResult) -> ScoreDiffEntry:
    return ScoreDiffEntry(
        run_id=key.run_id,
        step_id=key.step_id,
        scorer_name=key.scorer_name,
        score_a=a.score,
        score_b=b.score,
        status_a=a.status,
        status_b=b.status,
    )


def _placeholder_result() -> ScoreResult:
    """Sentinel for entries absent from one side of the diff.

    Uses `status="skipped"` because absent-here genuinely means "the scorer
    didn't produce a result for this side" — same semantic as runner-level
    skip. Distinct from regression/improvement transitions in classification.
    """
    return ScoreResult(status="skipped", score=None, reasoning="(absent)")


def compute_diff(report_a: EvalReport, report_b: EvalReport) -> ReportDiff:
    """Compare two `EvalReport`s and return a categorized `ReportDiff`."""
    runs_a = {r.run_id: r for r in report_a.runs}
    runs_b = {r.run_id: r for r in report_b.runs}

    runs_a_only = sorted(set(runs_a) - set(runs_b))
    runs_b_only = sorted(set(runs_b) - set(runs_a))

    regressions: list[ScoreDiffEntry] = []
    improvements: list[ScoreDiffEntry] = []
    score_deltas: list[ScoreDiffEntry] = []
    newly_skipped: list[ScoreDiffEntry] = []
    newly_running: list[ScoreDiffEntry] = []
    absent_in_a: list[ScoreDiffEntry] = []
    absent_in_b: list[ScoreDiffEntry] = []

    shared_run_ids = sorted(set(runs_a) & set(runs_b))
    for run_id in shared_run_ids:
        idx_a = _index_run(runs_a[run_id])
        idx_b = _index_run(runs_b[run_id])

        for key in sorted(
            set(idx_a) | set(idx_b),
            # `step_id` is `str | None`. Python can't compare None to str,
            # so we sort run-level entries (step_id=None) before step-level
            # entries via the `(is_run_level, step_id, scorer_name)` tuple.
            key=lambda k: (k.step_id is not None, k.step_id or "", k.scorer_name),
        ):
            in_a = key in idx_a
            in_b = key in idx_b
            if in_a and not in_b:
                absent_in_b.append(_make_entry(key, idx_a[key], _placeholder_result()))
                continue
            if in_b and not in_a:
                absent_in_a.append(_make_entry(key, _placeholder_result(), idx_b[key]))
                continue

            entry = _make_entry(key, idx_a[key], idx_b[key])
            _classify(
                entry,
                regressions=regressions,
                improvements=improvements,
                score_deltas=score_deltas,
                newly_skipped=newly_skipped,
                newly_running=newly_running,
            )

    return ReportDiff(
        runs_a_only=runs_a_only,
        runs_b_only=runs_b_only,
        regressions=regressions,
        improvements=improvements,
        score_deltas=score_deltas,
        newly_skipped=newly_skipped,
        newly_running=newly_running,
        absent_in_a=absent_in_a,
        absent_in_b=absent_in_b,
    )


def _classify(
    entry: ScoreDiffEntry,
    *,
    regressions: list[ScoreDiffEntry],
    improvements: list[ScoreDiffEntry],
    score_deltas: list[ScoreDiffEntry],
    newly_skipped: list[ScoreDiffEntry],
    newly_running: list[ScoreDiffEntry],
) -> None:
    """Sort one entry into the right bucket based on its (status_a, status_b).

    The 3x3 transition table:
                    | passed_b      | failed_b      | skipped_b
        passed_a    | score_delta?  | regression    | newly_skipped
        failed_a    | improvement   | score_delta?  | newly_skipped
        skipped_a   | newly_running | newly_running | (ignored)

    Cells marked `score_delta?` go to score_deltas only when the score
    actually moved AND both sides are non-None.
    """
    a, b = entry.status_a, entry.status_b
    if a == "skipped" and b == "skipped":
        return
    if b == "skipped":
        newly_skipped.append(entry)
        return
    if a == "skipped":
        newly_running.append(entry)
        return
    if a == "passed" and b == "failed":
        regressions.append(entry)
        return
    if a == "failed" and b == "passed":
        improvements.append(entry)
        return
    # Same pass/fail status; only score moved.
    if entry.score_a is not None and entry.score_b is not None and entry.score_a != entry.score_b:
        score_deltas.append(entry)


def format_diff(diff: ReportDiff) -> str:
    """Render a `ReportDiff` as a human-readable plain-text report."""
    lines: list[str] = []
    summary_runs: list[str] = []
    if diff.runs_a_only:
        summary_runs.append(f"removed: {len(diff.runs_a_only)}")
    if diff.runs_b_only:
        summary_runs.append(f"added: {len(diff.runs_b_only)}")
    if summary_runs:
        lines.append("Runs: " + " | ".join(summary_runs))
        if diff.runs_a_only:
            lines.append("  Removed: " + ", ".join(diff.runs_a_only))
        if diff.runs_b_only:
            lines.append("  Added:   " + ", ".join(diff.runs_b_only))
        lines.append("")

    def _fmt_score(s: float | None) -> str:
        return "—" if s is None else f"{s:.3f}"

    def _entry_line(entry: ScoreDiffEntry) -> str:
        loc = entry.run_id
        if entry.step_id is not None:
            loc += f" / {entry.step_id}"
        loc += f" / {entry.scorer_name}"
        return (
            f"  {loc}  "
            f"score {_fmt_score(entry.score_a)} → {_fmt_score(entry.score_b)}  "
            f"status {entry.status_a} → {entry.status_b}"
        )

    def _section(title: str, entries: Iterable[ScoreDiffEntry]) -> None:
        items = list(entries)
        if not items:
            return
        lines.append(f"{title} ({len(items)}):")
        for e in items:
            lines.append(_entry_line(e))
        lines.append("")

    _section("Newly failing (regressions)", diff.regressions)
    _section("Newly passing (improvements)", diff.improvements)
    _section("Score deltas", diff.score_deltas)
    _section("Newly skipped", diff.newly_skipped)
    _section("Newly running (was skipped)", diff.newly_running)
    _section("Absent in A (new in B)", diff.absent_in_a)
    _section("Absent in B (removed from A)", diff.absent_in_b)

    summary = (
        f"Summary: {len(diff.regressions)} regressed, "
        f"{len(diff.improvements)} improved, "
        f"{len(diff.score_deltas)} score deltas"
    )
    if diff.newly_skipped or diff.newly_running:
        summary += (
            f", {len(diff.newly_skipped)} newly skipped, {len(diff.newly_running)} newly running"
        )
    if diff.absent_in_a or diff.absent_in_b:
        summary += f", {len(diff.absent_in_a)} absent in A, {len(diff.absent_in_b)} absent in B"
    lines.append(summary)
    return "\n".join(lines)


__all__: list[Any] = [
    "ReportDiff",
    "ScoreDiffEntry",
    "compute_diff",
    "format_diff",
]
