"""Diff two `EvalReport`s — the core of regression detection.

Phase 3 #26. Categorizes every (run_id, scorer_name, step_id?) entry across
two reports into one of: regression (was passing, now failing), improvement
(was failing, now passing), score delta (pass status unchanged but score
moved), or absent-in-one. The diff is itself a Pydantic model so the CLI's
`--format json` flag can serialize it for the future GitHub-Action consumer.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from pipewise.core.report import EvalReport, RunEvalResult
from pipewise.core.scorer import ScoreResult


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
    passed_a: bool
    passed_b: bool

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
    """Entries that passed in A but fail in B."""

    improvements: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries that failed in A but pass in B."""

    score_deltas: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries whose pass status is unchanged but whose score moved."""

    absent_in_a: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries present in B but missing from A (same run, new scorer)."""

    absent_in_b: list[ScoreDiffEntry] = Field(default_factory=list)
    """Entries present in A but missing from B (same run, removed scorer)."""

    def has_regressions(self) -> bool:
        return bool(self.regressions)

    def total_changes(self) -> int:
        return (
            len(self.regressions)
            + len(self.improvements)
            + len(self.score_deltas)
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
        passed_a=a.status == "passed",
        passed_b=b.status == "passed",
    )


def _placeholder_result() -> ScoreResult:
    """Sentinel used when an entry is absent from one side of the diff."""
    return ScoreResult(status="failed", score=0.0, reasoning="(absent)")


def compute_diff(report_a: EvalReport, report_b: EvalReport) -> ReportDiff:
    """Compare two `EvalReport`s and return a categorized `ReportDiff`."""
    runs_a = {r.run_id: r for r in report_a.runs}
    runs_b = {r.run_id: r for r in report_b.runs}

    runs_a_only = sorted(set(runs_a) - set(runs_b))
    runs_b_only = sorted(set(runs_b) - set(runs_a))

    regressions: list[ScoreDiffEntry] = []
    improvements: list[ScoreDiffEntry] = []
    score_deltas: list[ScoreDiffEntry] = []
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
            if entry.passed_a and not entry.passed_b:
                regressions.append(entry)
            elif not entry.passed_a and entry.passed_b:
                improvements.append(entry)
            elif (
                entry.score_a is not None
                and entry.score_b is not None
                and entry.score_a != entry.score_b
            ):
                score_deltas.append(entry)

    return ReportDiff(
        runs_a_only=runs_a_only,
        runs_b_only=runs_b_only,
        regressions=regressions,
        improvements=improvements,
        score_deltas=score_deltas,
        absent_in_a=absent_in_a,
        absent_in_b=absent_in_b,
    )


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
            f"passed {entry.passed_a} → {entry.passed_b}"
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
    _section("Absent in A (new in B)", diff.absent_in_a)
    _section("Absent in B (removed from A)", diff.absent_in_b)

    summary = (
        f"Summary: {len(diff.regressions)} regressed, "
        f"{len(diff.improvements)} improved, "
        f"{len(diff.score_deltas)} score deltas"
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
