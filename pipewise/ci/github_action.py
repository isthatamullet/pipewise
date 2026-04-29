"""Render an `EvalReport` (with optional baseline) as a markdown PR comment.

Phase 5 #36. Produces the sticky comment that the pipewise-eval GitHub Action
posts on every PR. Format follows conventions distilled from prior art
(Braintrust, Codecov, Vercel): sticky-comment HTML marker keyed by adapter
name, verdict line as the most prominent element, scorer × step roll-up
table with signed Δ column, per-case detail in collapsibles.

The renderer is pure-Python and takes pre-built `EvalReport` objects;
fetching reports from artifacts and posting comments via the GitHub API is
the Action's responsibility (see `.github/actions/pipewise-eval/`, #37).
"""

from __future__ import annotations

from collections import defaultdict

from pipewise import __version__ as _PIPEWISE_VERSION
from pipewise.core.report import EvalReport
from pipewise.core.scorer import ScoreResult
from pipewise.runner.diff import ReportDiff, ScoreDiffEntry, compute_diff

_STICKY_MARKER_TEMPLATE = "<!-- pipewise-eval-report:{adapter_name} -->"


def render_pr_comment(
    report: EvalReport,
    *,
    adapter_name: str,
    short_sha: str,
    baseline: EvalReport | None = None,
) -> str:
    """Render a markdown PR comment for `report`, optionally diffed against `baseline`.

    Args:
        report: The eval report from the current PR's pipeline run.
        adapter_name: The adapter package name. Used as the sticky-comment marker
            key so multi-adapter repos can post multiple comments without
            clobbering. Also shown in the comment header.
        short_sha: Short Git SHA of the commit this report was generated for.
            Shown in the footer for staleness verification by reviewers.
        baseline: The eval report from the comparison reference (typically main).
            If `None`, the comment shows absolute values with no Δ column.

    Returns:
        Markdown string ready to post as a GitHub PR comment. Always ends in
        a single trailing newline.
    """
    diff = compute_diff(baseline, report) if baseline is not None else None

    parts: list[str] = [
        _STICKY_MARKER_TEMPLATE.format(adapter_name=adapter_name),
        f"## Pipewise eval report — {adapter_name}",
        "",
        _render_verdict_line(report, diff),
        "",
        _render_rollup_table(report, baseline),
        "",
    ]

    if diff is not None:
        parts.append(_render_counts(report, baseline, diff))
        parts.append("")
        if diff.regressions:
            parts.append(_render_newly_failing(diff.regressions))
            parts.append("")

    parts.append(_render_full_report_details(report))
    parts.append("")
    parts.append(_render_footer(short_sha))

    return "\n".join(parts).rstrip() + "\n"


# ─── Verdict line ────────────────────────────────────────────────────────────


def _render_verdict_line(report: EvalReport, diff: ReportDiff | None) -> str:
    if diff is None:
        passing = report.passing_score_count()
        total = report.total_score_count()
        run_word = "run" if len(report.runs) == 1 else "runs"
        return f"🆕 {len(report.runs)} {run_word} · {passing}/{total} scorers passing · no baseline"

    if diff.regressions:
        n = len(diff.regressions)
        plural = "" if n == 1 else "s"
        return f"❌ {n} regression{plural} · was passing on main, failing here"

    failing = report.failing_score_count()
    if failing > 0:
        plural = "" if failing == 1 else "s"
        return f"⚠️ {failing} failing scorer{plural} · no regressions vs main"

    improvements = len(diff.improvements)
    if improvements > 0:
        plural = "" if improvements == 1 else "s"
        return f"✅ All scorers passing · {improvements} improvement{plural} 🟢"

    # At this point: no regressions, no failing, no improvements. But scores
    # may have moved (`score_deltas`), or scorers/runs may have been added or
    # removed. Any of those means "no regressions" is honest; "no change" is
    # a lie. Reserve "no change vs main" for the truly identical case.
    if (
        diff.score_deltas
        or diff.absent_in_a
        or diff.absent_in_b
        or diff.runs_a_only
        or diff.runs_b_only
    ):
        return "✅ All scorers passing · no regressions vs main"
    return "✅ All scorers passing · no change vs main"


# ─── Roll-up table ───────────────────────────────────────────────────────────

_RollupKey = tuple[str | None, str]


def _aggregate_scores(report: EvalReport) -> dict[_RollupKey, list[ScoreResult]]:
    """Bucket every `ScoreResult` by (step_id, scorer_name).

    `step_id=None` represents run-level scorers.
    """
    buckets: dict[_RollupKey, list[ScoreResult]] = defaultdict(list)
    for run in report.runs:
        for step_entry in run.step_scores:
            buckets[(step_entry.step_id, step_entry.scorer_name)].append(step_entry.result)
        for run_entry in run.run_scores:
            buckets[(None, run_entry.scorer_name)].append(run_entry.result)
    return buckets


def _avg_score(results: list[ScoreResult]) -> float | None:
    if not results:
        return None
    return sum(r.score for r in results) / len(results)


def _format_score(score: float | None) -> str:
    if score is None:
        return "—"
    return f"{score:.2f}"


# Epsilon for treating floating-point deltas as "no change". Scores live in
# [0.0, 1.0] and the rendered cell shows two decimal places, so anything
# smaller than 1e-6 is precision noise from averaging — not a real signal.
_DELTA_EPSILON = 1e-6


def _format_delta(baseline: float | None, current: float | None) -> str:
    if current is None:
        return "removed"
    if baseline is None:
        return "newly added"
    delta = current - baseline
    if abs(delta) < _DELTA_EPSILON:
        return "—"
    sign = "+" if delta > 0 else ""
    emoji = "🟢" if delta > 0 else "🔴"
    return f"{sign}{delta:.2f} {emoji}"


def _format_rollup_label(step_id: str | None, scorer_name: str) -> str:
    if step_id is None:
        return f"`{scorer_name}` (run-level)"
    return f"`{scorer_name}` × `{step_id}`"


def _sort_rollup_keys(keys: set[_RollupKey]) -> list[_RollupKey]:
    # Run-level entries (step_id=None) sort before step-level. Within each
    # group, alphabetical by step_id then scorer_name. Matches `compute_diff`'s
    # ordering convention for consistency between the table and the diff.
    return sorted(keys, key=lambda k: (k[0] is not None, k[0] or "", k[1]))


def _render_rollup_table(report: EvalReport, baseline: EvalReport | None) -> str:
    report_buckets = _aggregate_scores(report)
    baseline_buckets = _aggregate_scores(baseline) if baseline is not None else {}
    all_keys = set(report_buckets) | set(baseline_buckets)

    if not all_keys:
        return "_No scorer results in this report._"

    has_baseline = baseline is not None
    lines = ["| Scorer × Step | Main | This PR | Δ |", "| :--- | ---: | ---: | ---: |"]
    for key in _sort_rollup_keys(all_keys):
        step_id, scorer_name = key
        report_avg = _avg_score(report_buckets.get(key, []))
        baseline_avg = _avg_score(baseline_buckets.get(key, []))
        label = _format_rollup_label(step_id, scorer_name)
        main_cell = _format_score(baseline_avg) if has_baseline else "—"
        pr_cell = _format_score(report_avg)
        delta_cell = _format_delta(baseline_avg, report_avg) if has_baseline else "—"
        lines.append(f"| {label} | {main_cell} | {pr_cell} | {delta_cell} |")
    return "\n".join(lines)


# ─── Counts row ──────────────────────────────────────────────────────────────


def _count_unchanged(report: EvalReport, baseline: EvalReport, diff: ReportDiff) -> int:
    """Entries present in both reports with same pass status AND same score."""
    matched_in_report = report.total_score_count() - len(diff.absent_in_a)
    changed = len(diff.regressions) + len(diff.improvements) + len(diff.score_deltas)
    return max(matched_in_report - changed, 0)


def _format_extras_line(diff: ReportDiff) -> str | None:
    """Footnote listing diff categories not surfaced in the main counts row.

    The main row tracks regressions / improvements / unchanged (strict pass-
    fail framing). Score-only deltas, newly-added scorers, and removed
    scorers are real changes too — without surfacing them, the displayed
    counts won't sum to the number of rows in the rollup table when those
    categories are non-empty. Returns `None` when nothing to report.
    """
    extras: list[str] = []
    if diff.score_deltas:
        n = len(diff.score_deltas)
        extras.append(f"{n} score delta{'' if n == 1 else 's'}")
    if diff.absent_in_a:
        n = len(diff.absent_in_a)
        extras.append(f"{n} newly added")
    if diff.absent_in_b:
        n = len(diff.absent_in_b)
        extras.append(f"{n} removed")
    if not extras:
        return None
    return f"_Plus: {', '.join(extras)}._"


def _render_counts(report: EvalReport, baseline: EvalReport | None, diff: ReportDiff) -> str:
    assert baseline is not None  # narrowed by call site
    unchanged = _count_unchanged(report, baseline, diff)
    line = (
        f"**Regressions:** {len(diff.regressions)} 🔴 · "
        f"**Improvements:** {len(diff.improvements)} 🟢 · "
        f"**Unchanged:** {unchanged}"
    )
    extras = _format_extras_line(diff)
    if extras is not None:
        line += f"\n\n{extras}"
    return line


# ─── Newly-failing checks detail ─────────────────────────────────────────────


def _format_regression_line(entry: ScoreDiffEntry) -> str:
    location = f"`{entry.scorer_name}`"
    if entry.step_id is not None:
        location += f" × `{entry.step_id}`"
    location += f" · run `{entry.run_id}`"
    return f"- {location} — score {entry.score_a:.2f} → {entry.score_b:.2f} (passed → failed)"


def _render_newly_failing(regressions: list[ScoreDiffEntry]) -> str:
    n = len(regressions)
    body = "\n".join(_format_regression_line(e) for e in regressions)
    return f"<details><summary><b>Newly failing checks ({n})</b></summary>\n\n{body}\n\n</details>"


# ─── Full report detail ──────────────────────────────────────────────────────


def _render_full_report_details(report: EvalReport) -> str:
    n_runs = len(report.runs)
    run_word = "run" if n_runs == 1 else "runs"
    dataset = report.dataset_name or "—"
    summary = f"<summary>Full report ({n_runs} {run_word} · dataset: {dataset})</summary>"

    if not report.runs:
        return f"<details>{summary}\n\n_No runs in this report._\n\n</details>"

    rows = [
        "| Run | Step | Scorer | Score | Passed |",
        "| :--- | :--- | :--- | ---: | :---: |",
    ]
    for run in report.runs:
        for step_entry in sorted(run.step_scores, key=lambda e: (e.step_id, e.scorer_name)):
            rows.append(
                f"| `{run.run_id}` | `{step_entry.step_id}` | `{step_entry.scorer_name}` "
                f"| {step_entry.result.score:.2f} | "
                f"{'✅' if step_entry.result.passed else '❌'} |"
            )
        for run_entry in sorted(run.run_scores, key=lambda e: e.scorer_name):
            rows.append(
                f"| `{run.run_id}` | _(run-level)_ | `{run_entry.scorer_name}` "
                f"| {run_entry.result.score:.2f} | "
                f"{'✅' if run_entry.result.passed else '❌'} |"
            )

    body = "\n".join(rows)
    return f"<details>{summary}\n\n{body}\n\n</details>"


# ─── Footer ──────────────────────────────────────────────────────────────────


def _render_footer(short_sha: str) -> str:
    return f"<sub>Updated for `{short_sha}` · pipewise v{_PIPEWISE_VERSION}</sub>"


__all__ = ["render_pr_comment"]
