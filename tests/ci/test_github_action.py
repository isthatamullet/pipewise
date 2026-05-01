"""Tests for `pipewise.ci.github_action.render_pr_comment` (#36)."""

from __future__ import annotations

from datetime import UTC, datetime

from pipewise import (
    EvalReport,
    RunEvalResult,
    RunScoreEntry,
    ScoreResult,
    StepScoreEntry,
)
from pipewise.ci import render_pr_comment

NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC)


def _result(score: float, passed: bool) -> ScoreResult:
    return ScoreResult(status="passed" if passed else "failed", score=score)


def _step_entry(step_id: str, scorer_name: str, score: float, passed: bool) -> StepScoreEntry:
    return StepScoreEntry(step_id=step_id, scorer_name=scorer_name, result=_result(score, passed))


def _run_entry(scorer_name: str, score: float, passed: bool) -> RunScoreEntry:
    return RunScoreEntry(scorer_name=scorer_name, result=_result(score, passed))


def _skipped_step_entry(step_id: str, scorer_name: str) -> StepScoreEntry:
    return StepScoreEntry(
        step_id=step_id,
        scorer_name=scorer_name,
        result=ScoreResult(status="skipped", reasoning="test skip"),
    )


def _skipped_run_entry(scorer_name: str) -> RunScoreEntry:
    return RunScoreEntry(
        scorer_name=scorer_name,
        result=ScoreResult(status="skipped", reasoning="test skip"),
    )


def _run(
    *,
    run_id: str = "run_1",
    step_scores: list[StepScoreEntry] | None = None,
    run_scores: list[RunScoreEntry] | None = None,
) -> RunEvalResult:
    return RunEvalResult(
        run_id=run_id,
        pipeline_name="news-analysis",
        adapter_name="news_analysis_pipewise",
        adapter_version="0.0.1",
        step_scores=step_scores or [],
        run_scores=run_scores or [],
    )


def _report(
    *,
    runs: list[RunEvalResult],
    dataset_name: str | None = "golden.jsonl",
) -> EvalReport:
    return EvalReport(
        report_id="test-report",
        generated_at=NOW,
        pipewise_version="0.0.1",
        dataset_name=dataset_name,
        scorer_names=["any"],
        runs=runs,
    )


# ─── Reference state A: passing, no change vs main ───────────────────────────


class TestPassingNoChange:
    def _identical_pair(self) -> tuple[EvalReport, EvalReport]:
        run_steps = [
            _step_entry("extract", "ExactMatch", 0.94, True),
            _step_entry("analyze", "LlmJudge", 0.88, True),
            _step_entry("format", "Regex", 1.00, True),
        ]
        baseline = _report(runs=[_run(run_id="r1", step_scores=run_steps)])
        report = _report(runs=[_run(run_id="r1", step_scores=list(run_steps))])
        return baseline, report

    def test_verdict_says_no_change(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc1234"
        )
        assert "✅ All scorers passing · no change vs main" in out

    def test_delta_column_shows_dash_for_unchanged(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc1234"
        )
        # Three rollup rows; each Δ cell should be the em-dash placeholder.
        # Match `| — |` at line ends (the trailing pipe of the Δ column).
        assert out.count("| — |") >= 3

    def test_counts_show_zero_regressions_zero_improvements(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc1234"
        )
        assert "**Regressions:** 0 🔴" in out
        assert "**Improvements:** 0 🟢" in out
        assert "**Unchanged:** 3" in out

    def test_no_newly_failing_section_when_no_regressions(self) -> None:
        baseline, report = self._identical_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc1234"
        )
        assert "Newly failing checks" not in out


# ─── Reference state B: passing with improvements ────────────────────────────


class TestPassingWithImprovements:
    def _improved_pair(self) -> tuple[EvalReport, EvalReport]:
        # Two scorers improved by flipping fail→pass; one unchanged.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.40, False),
                        _step_entry("analyze", "LlmJudge", 0.45, False),
                        _step_entry("format", "Regex", 1.00, True),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.97, True),
                        _step_entry("analyze", "LlmJudge", 0.91, True),
                        _step_entry("format", "Regex", 1.00, True),
                    ],
                )
            ]
        )
        return baseline, report

    def test_verdict_announces_improvements(self) -> None:
        baseline, report = self._improved_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="def5678"
        )
        assert "✅ All scorers passing · 2 improvements 🟢" in out

    def test_delta_column_shows_signed_positives(self) -> None:
        baseline, report = self._improved_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="def5678"
        )
        assert "+0.57 🟢" in out  # 0.97 - 0.40
        assert "+0.46 🟢" in out  # 0.91 - 0.45

    def test_counts_show_two_improvements_one_unchanged(self) -> None:
        baseline, report = self._improved_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="def5678"
        )
        assert "**Regressions:** 0 🔴" in out
        assert "**Improvements:** 2 🟢" in out
        assert "**Unchanged:** 1" in out


# ─── Reference state C: regressing with newly-failing checks ─────────────────


class TestRegressing:
    def _regressed_pair(self) -> tuple[EvalReport, EvalReport]:
        # One true regression (pass→fail) + one score_delta with negative delta.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.94, True),
                        _step_entry("analyze", "LlmJudge", 0.88, True),
                        _step_entry("format", "Regex", 1.00, True),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("extract", "ExactMatch", 0.81, True),
                        _step_entry("analyze", "LlmJudge", 0.85, True),
                        _step_entry("format", "Regex", 0.45, False),
                    ],
                )
            ]
        )
        return baseline, report

    def test_verdict_announces_regressions(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="9abc012"
        )
        assert out.startswith("<!-- pipewise-eval-report:news-analysis -->")
        assert "❌ 1 regression · was passing on main, failing here" in out

    def test_delta_column_shows_signed_negatives_with_red_emoji(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="9abc012"
        )
        assert "-0.55 🔴" in out  # 0.45 - 1.00 (the regression)
        assert "-0.13 🔴" in out  # 0.81 - 0.94 (score delta)
        assert "-0.03 🔴" in out  # 0.85 - 0.88 (score delta)

    def test_newly_failing_section_lists_regression_with_run_id(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="9abc012"
        )
        assert "<details><summary><b>Newly failing checks (1)</b></summary>" in out
        assert "`Regex` × `format`" in out
        assert "run `r1`" in out
        assert "passed → failed" in out

    def test_counts_show_one_regression(self) -> None:
        baseline, report = self._regressed_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="9abc012"
        )
        assert "**Regressions:** 1 🔴" in out
        assert "**Improvements:** 0 🟢" in out


# ─── Missing baseline ────────────────────────────────────────────────────────


class TestNoBaseline:
    def test_verdict_announces_no_baseline(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.94, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc1234")
        assert "🆕 1 run · 1/1 scorers passing · no baseline" in out

    def test_no_counts_row_when_baseline_missing(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.94, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc1234")
        # Counts row only renders with a baseline.
        assert "**Regressions:**" not in out
        assert "**Improvements:**" not in out

    def test_delta_column_shows_dash_when_baseline_missing(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.94, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc1234")
        # Main column should be `—` and Δ column should be `—`.
        assert "| — | 0.94 | — |" in out


# ─── Structural / cross-cutting checks ───────────────────────────────────────


class TestStructure:
    def test_sticky_marker_is_first_line_and_keyed_by_adapter_name(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 1.0, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="my-adapter", short_sha="abc")
        assert out.startswith("<!-- pipewise-eval-report:my-adapter -->\n")

    def test_h2_header_includes_adapter_name(self) -> None:
        report = _report(runs=[_run(run_id="r1")])
        out = render_pr_comment(report, adapter_name="branching_pipeline", short_sha="abc")
        assert "## Pipewise eval report — branching_pipeline" in out

    def test_short_sha_appears_in_footer(self) -> None:
        report = _report(runs=[_run(run_id="r1")])
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="deadbee")
        assert "<sub>Updated for `deadbee` ·" in out

    def test_run_level_scorers_appear_with_run_level_label(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    run_scores=[_run_entry("CostBudget", 1.0, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        assert "`CostBudget` (run-level)" in out

    def test_rollup_header_uses_right_aligned_separators(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 1.0, True)],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        # Right-aligned numeric columns per the locked design spec.
        assert "| :--- | ---: | ---: | ---: |" in out

    def test_full_report_details_lists_each_case(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="run_a",
                    step_scores=[
                        _step_entry("s1", "ExactMatch", 0.9, True),
                        _step_entry("s2", "Regex", 0.5, False),
                    ],
                ),
                _run(
                    run_id="run_b",
                    step_scores=[
                        _step_entry("s1", "ExactMatch", 1.0, True),
                    ],
                ),
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        assert "<summary>Full report (2 runs · dataset: golden.jsonl)</summary>" in out
        assert "`run_a` | `s1` | `ExactMatch`" in out
        assert "`run_a` | `s2` | `Regex`" in out
        assert "`run_b` | `s1` | `ExactMatch`" in out
        # Pass/fail emoji per row.
        assert " ✅ |" in out
        assert " ❌ |" in out

    def test_output_ends_with_single_trailing_newline(self) -> None:
        report = _report(runs=[_run(run_id="r1")])
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        assert out.endswith("\n")
        assert not out.endswith("\n\n")

    def test_dataset_name_falls_back_to_dash_when_missing(self) -> None:
        report = _report(runs=[_run(run_id="r1")], dataset_name=None)
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        assert "dataset: —" in out

    def test_empty_report_renders_gracefully(self) -> None:
        report = _report(runs=[])
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        # No table rows but header + placeholder still renders.
        assert "_No scorer results in this report._" in out
        assert "_No runs in this report._" in out


# ─── Floating-point precision robustness ─────────────────────────────────────


class TestFloatingPointPrecision:
    def test_tiny_precision_error_renders_as_unchanged_dash(self) -> None:
        # Realistic scenario: an average of 0.7 + 0.7 + 0.7 / 3 vs 2.1 / 3
        # produces a microscopic precision delta. The cell should still
        # render the em-dash "no change" placeholder, not "+0.00 🟢".
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("step", "Scorer", 0.7, True)],
                ),
                _run(
                    run_id="r2",
                    step_scores=[_step_entry("step", "Scorer", 0.7, True)],
                ),
                _run(
                    run_id="r3",
                    step_scores=[_step_entry("step", "Scorer", 0.7, True)],
                ),
            ]
        )
        # Same logical average, written as 2.1/3 (introduces precision noise).
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("step", "Scorer", 0.1, True)],
                ),
                _run(
                    run_id="r2",
                    step_scores=[_step_entry("step", "Scorer", 1.0, True)],
                ),
                _run(
                    run_id="r3",
                    step_scores=[_step_entry("step", "Scorer", 1.0, True)],
                ),
            ]
        )
        # Sanity: the average difference IS exactly 0 in arithmetic but may
        # not be exactly 0 in float. Average baseline = 0.7; average report =
        # (0.1 + 1.0 + 1.0) / 3 = 0.7 (with possible precision noise).
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        # The Δ cell should be "—" (not "+0.00 🟢" or similar).
        assert "+0.00 🟢" not in out
        assert "-0.00 🔴" not in out


# ─── Verdict accuracy: score deltas without flips ────────────────────────────


class TestScoreDeltasWithoutFlips:
    def _score_delta_pair(self) -> tuple[EvalReport, EvalReport]:
        # Both reports pass; scores moved but pass status didn't flip.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("step", "Scorer", 0.85, True)],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("step", "Scorer", 0.92, True)],
                )
            ]
        )
        return baseline, report

    def test_verdict_says_no_regressions_not_no_change(self) -> None:
        baseline, report = self._score_delta_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        # Score moved up but didn't flip pass status. We don't claim "no
        # change" because the rollup table will show a non-zero Δ.
        assert "✅ All scorers passing · no regressions vs main" in out
        assert "no change vs main" not in out

    def test_extras_footnote_lists_score_deltas(self) -> None:
        baseline, report = self._score_delta_pair()
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "_Plus: 1 score delta._" in out


class TestExtrasFootnote:
    def test_lists_newly_added_scorers(self) -> None:
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("step", "ExactMatch", 1.0, True)],
                )
            ]
        )
        # Same step, but a new scorer joins.
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("step", "ExactMatch", 1.0, True),
                        _step_entry("step", "Regex", 1.0, True),
                    ],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "_Plus: 1 newly added._" in out

    def test_lists_removed_scorers(self) -> None:
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("step", "ExactMatch", 1.0, True),
                        _step_entry("step", "Regex", 1.0, True),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("step", "ExactMatch", 1.0, True)],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "_Plus: 1 removed._" in out

    def test_no_footnote_when_categories_are_empty(self) -> None:
        # The TestPassingNoChange fixture has no extras; the footnote should
        # be absent.
        run_steps = [_step_entry("extract", "ExactMatch", 0.94, True)]
        baseline = _report(runs=[_run(run_id="r1", step_scores=run_steps)])
        report = _report(runs=[_run(run_id="r1", step_scores=list(run_steps))])
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "_Plus:" not in out


# ─── Failing-but-not-regressed (warning) state ───────────────────────────────


class TestFailingButNoRegressions:
    def test_verdict_warns_when_failing_already_failing(self) -> None:
        # Scorer was already failing on main and is still failing here.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.20, False)],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("extract", "ExactMatch", 0.20, False)],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "⚠️ 1 failing scorer · no regressions vs main" in out


class TestSkippedVerdicts:
    """Verdict-line cases involving the `skipped` state."""

    def test_all_skipped_says_no_signal(self) -> None:
        # Every scorer was skipped (e.g., applies_to_step_ids excluded all
        # steps, or every step had `status="skipped"`). Special-case verdict
        # so adopters don't read "passing 0/2" as "broken."
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _skipped_step_entry("a", "Regex"),
                        _skipped_step_entry("b", "Regex"),
                    ],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        assert "⏭ All scorers skipped · no signal" in out

    def test_all_skipped_says_no_signal_with_baseline(self) -> None:
        # Same all-skipped state but with a baseline. Verdict still flags
        # "no signal" because the diff is meaningless when one side is
        # entirely skipped.
        baseline = _report(
            runs=[_run(run_id="r1", step_scores=[_step_entry("a", "Regex", 1.0, True)])]
        )
        report = _report(runs=[_run(run_id="r1", step_scores=[_skipped_step_entry("a", "Regex")])])
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "⏭ All scorers skipped · no signal" in out

    def test_newly_skipped_without_regressions_uses_skipped_verdict(self) -> None:
        # Some scorers narrowed scope (passed → skipped) but other scorers
        # still passed. Verdict should call out the scope-narrowing rather
        # than read "all green."
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),
                        _step_entry("b", "Regex", 1.0, True),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),
                        _skipped_step_entry("b", "Regex"),
                    ],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "⏭ 1 newly-skipped scorer · no regressions vs main" in out

    def test_passing_with_skipped_scorers_says_non_skipped_passing(self) -> None:
        # Mixed state with PR-side skipped entries that aren't transitions
        # (skipped on both sides). The verdict copy adapts to "non-skipped"
        # because "all scorers passing" would be a lie.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),
                        _skipped_step_entry("b", "Regex"),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 0.95, True),  # score moved
                        _skipped_step_entry("b", "Regex"),
                    ],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "✅ All non-skipped scorers passing" in out

    def test_no_baseline_surfaces_skipped_count(self) -> None:
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),
                        _skipped_step_entry("b", "Regex"),
                    ],
                )
            ]
        )
        out = render_pr_comment(report, adapter_name="news-analysis", short_sha="abc")
        # 1 passing of 2 total; (1 skipped) annotation included.
        assert "1/2 scorers passing (1 skipped)" in out

    def test_extras_lists_newly_skipped_and_newly_running(self) -> None:
        # `passed → skipped` lands in newly_skipped; `skipped → passed` in
        # newly_running. Both surface in the "Plus:" extras footnote so the
        # rollup table row count reconciles with main counts.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),  # → skipped
                        _skipped_step_entry("b", "Regex"),  # → passing
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _skipped_step_entry("a", "Regex"),
                        _step_entry("b", "Regex", 1.0, True),
                    ],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        assert "1 newly skipped" in out
        assert "1 newly running" in out

    def test_unchanged_count_excludes_entries_from_runs_b_only(self) -> None:
        # Brand-new run in B (not in baseline) — its scorer entries are
        # NOT "unchanged"; they're added. Without subtracting them from
        # matched_in_report, the unchanged count would over-count.
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("a", "Regex", 1.0, True)],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[_step_entry("a", "Regex", 1.0, True)],
                ),
                _run(
                    run_id="r2",  # NEW run, no baseline counterpart
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),
                        _step_entry("b", "Regex", 1.0, True),
                    ],
                ),
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        # Only r1's single entry is genuinely unchanged. r2's two entries
        # are from a new run; counting them as "unchanged" would be a lie.
        assert "**Unchanged:** 1" in out

    def test_unchanged_count_excludes_skipped_transitions(self) -> None:
        # `passed → skipped` is a transition, not "unchanged."
        baseline = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),
                        _step_entry("b", "Regex", 1.0, True),
                        _step_entry("c", "Regex", 1.0, True),
                    ],
                )
            ]
        )
        report = _report(
            runs=[
                _run(
                    run_id="r1",
                    step_scores=[
                        _step_entry("a", "Regex", 1.0, True),  # unchanged
                        _step_entry("b", "Regex", 1.0, True),  # unchanged
                        _skipped_step_entry("c", "Regex"),  # newly_skipped
                    ],
                )
            ]
        )
        out = render_pr_comment(
            report, baseline=baseline, adapter_name="news-analysis", short_sha="abc"
        )
        # Only 2 are truly unchanged; the third is a transition.
        assert "**Unchanged:** 2" in out
