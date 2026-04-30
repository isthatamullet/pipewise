"""Tests for `python -m pipewise.ci` (#37).

The CLI is the entry point that the pipewise-eval GitHub Action invokes.
These tests subprocess the same module-run invocation the action uses, so
"the action calls render_pr_comment with the right args" is exercised end
to end at the same boundary the YAML hits.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pipewise import (
    EvalReport,
    RunEvalResult,
    ScoreResult,
    StepScoreEntry,
)
from pipewise.ci.__main__ import main as cli_main

NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC)


def _build_report(
    *,
    run_id: str = "r1",
    score: float = 1.0,
    passed: bool = True,
    dataset_name: str | None = "golden.jsonl",
) -> EvalReport:
    return EvalReport(
        report_id="test",
        generated_at=NOW,
        pipewise_version="0.0.1",
        dataset_name=dataset_name,
        scorer_names=["ExactMatch"],
        runs=[
            RunEvalResult(
                run_id=run_id,
                pipeline_name="factspark",
                adapter_name="factspark_pipewise",
                adapter_version="0.0.1",
                step_scores=[
                    StepScoreEntry(
                        step_id="step",
                        scorer_name="ExactMatch",
                        result=ScoreResult(status="passed" if passed else "failed", score=score),
                    )
                ],
            )
        ],
    )


def _write_report(path: Path, report: EvalReport) -> None:
    path.write_text(report.model_dump_json(), encoding="utf-8")


# ─── In-process tests via cli_main() ─────────────────────────────────────────


class TestCliInProcess:
    def test_writes_markdown_to_output_path(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        output_path = tmp_path / "comment.md"
        _write_report(report_path, _build_report())

        rc = cli_main(
            [
                "--report",
                str(report_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc1234",
                "--output",
                str(output_path),
            ]
        )

        assert rc == 0
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert content.startswith("<!-- pipewise-eval-report:factspark -->")
        assert "## Pipewise eval report — factspark" in content
        assert "<sub>Updated for `abc1234`" in content

    def test_no_baseline_path_renders_no_diff_comment(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        output_path = tmp_path / "comment.md"
        _write_report(report_path, _build_report())

        rc = cli_main(
            [
                "--report",
                str(report_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc",
                "--output",
                str(output_path),
            ]
        )

        assert rc == 0
        content = output_path.read_text(encoding="utf-8")
        assert "🆕" in content
        assert "no baseline" in content

    def test_baseline_present_on_disk_renders_diff_comment(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        baseline_path = tmp_path / "baseline.json"
        output_path = tmp_path / "comment.md"
        _write_report(report_path, _build_report(score=0.97, passed=True))
        _write_report(baseline_path, _build_report(score=0.40, passed=False))

        rc = cli_main(
            [
                "--report",
                str(report_path),
                "--baseline",
                str(baseline_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc",
                "--output",
                str(output_path),
            ]
        )

        assert rc == 0
        content = output_path.read_text(encoding="utf-8")
        # Improvement: failed→passed.
        assert "1 improvement" in content

    def test_baseline_path_pointing_to_missing_file_falls_back_silently(
        self, tmp_path: Path
    ) -> None:
        # Common operational scenario: the workflow's download-artifact step
        # didn't find a baseline (first PR / expired retention) and writes
        # nothing to the expected path. The action passes the path anyway;
        # the CLI must NOT fail — it should treat the missing file as
        # "no baseline" and still render a useful comment.
        report_path = tmp_path / "report.json"
        baseline_path = tmp_path / "does-not-exist.json"
        output_path = tmp_path / "comment.md"
        _write_report(report_path, _build_report())
        assert not baseline_path.exists()

        rc = cli_main(
            [
                "--report",
                str(report_path),
                "--baseline",
                str(baseline_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc",
                "--output",
                str(output_path),
            ]
        )

        assert rc == 0
        content = output_path.read_text(encoding="utf-8")
        assert "no baseline" in content

    def test_creates_output_parent_directory_if_missing(self, tmp_path: Path) -> None:
        # The action writes to $RUNNER_TEMP/pipewise-comment.md which exists,
        # but defensive handling of nested paths matters for non-CI usage.
        report_path = tmp_path / "report.json"
        output_path = tmp_path / "nested" / "subdir" / "comment.md"
        _write_report(report_path, _build_report())

        rc = cli_main(
            [
                "--report",
                str(report_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc",
                "--output",
                str(output_path),
            ]
        )

        assert rc == 0
        assert output_path.exists()

    def test_invalid_report_json_raises_validation_error(self, tmp_path: Path) -> None:
        # Pydantic raises ValidationError for malformed JSON — that's the
        # expected failure mode for a corrupt report. Pin the test to that
        # specific exception so a future change that swallows it (e.g., adds
        # a generic try/except) fails the test loudly.
        from pydantic import ValidationError

        report_path = tmp_path / "report.json"
        report_path.write_text("not json", encoding="utf-8")
        output_path = tmp_path / "comment.md"

        with pytest.raises(ValidationError):
            cli_main(
                [
                    "--report",
                    str(report_path),
                    "--adapter-name",
                    "factspark",
                    "--short-sha",
                    "abc",
                    "--output",
                    str(output_path),
                ]
            )

    def test_missing_report_file_returns_nonzero_with_clean_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # CLIs shouldn't dump tracebacks for user-facing input errors —
        # that's just confusing in CI logs. Verify the missing-file case
        # gets a clean stderr message + non-zero exit.
        missing_path = tmp_path / "does-not-exist.json"
        output_path = tmp_path / "comment.md"

        rc = cli_main(
            [
                "--report",
                str(missing_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc",
                "--output",
                str(output_path),
            ]
        )

        assert rc == 1
        captured = capsys.readouterr()
        assert "is not a file" in captured.err
        assert str(missing_path) in captured.err
        assert not output_path.exists()

    def test_baseline_pointing_to_directory_falls_back_silently(self, tmp_path: Path) -> None:
        # `is_file()` rejects directories where `exists()` would accept.
        # Verify a baseline path that happens to be a directory falls back
        # to "no baseline" rather than crashing inside read_text().
        report_path = tmp_path / "report.json"
        baseline_dir = tmp_path / "baseline-dir"
        baseline_dir.mkdir()
        output_path = tmp_path / "comment.md"
        _write_report(report_path, _build_report())

        rc = cli_main(
            [
                "--report",
                str(report_path),
                "--baseline",
                str(baseline_dir),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc",
                "--output",
                str(output_path),
            ]
        )

        assert rc == 0
        assert "no baseline" in output_path.read_text(encoding="utf-8")


# ─── End-to-end via `python -m pipewise.ci` subprocess ───────────────────────


class TestCliSubprocess:
    """Exercise the same invocation path the GitHub Action uses.

    The action's YAML runs `python -m pipewise.ci ...`. Subprocessing here
    catches breakage in the `__main__` plumbing that in-process `main()`
    calls would miss (missing `if __name__` guard, broken imports under
    `-m`, etc.).
    """

    def test_module_run_produces_expected_markdown(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        output_path = tmp_path / "comment.md"
        _write_report(report_path, _build_report())

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pipewise.ci",
                "--report",
                str(report_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "deadbee",
                "--output",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        content = output_path.read_text(encoding="utf-8")
        assert content.startswith("<!-- pipewise-eval-report:factspark -->")
        assert "<sub>Updated for `deadbee`" in content

    def test_module_run_help_flag_succeeds(self) -> None:
        # If the `python -m` plumbing is broken, even --help fails.
        result = subprocess.run(
            [sys.executable, "-m", "pipewise.ci", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Render a pipewise EvalReport" in result.stdout


# ─── Ensure round-trip via model_dump_json works ─────────────────────────────


class TestReportRoundTrip:
    """Pipewise.runner.storage produces report JSON via `model_dump_json`.
    The CLI must accept that exact serialization. Sanity check the round-
    trip rather than rely on hand-written JSON to stay in sync with the
    schema.
    """

    def test_round_trip_via_model_dump_json(self, tmp_path: Path) -> None:
        report = _build_report()
        serialized = report.model_dump_json()
        # Sanity: confirm it parses as JSON before writing.
        parsed: dict[str, Any] = json.loads(serialized)
        assert "runs" in parsed

        report_path = tmp_path / "report.json"
        report_path.write_text(serialized, encoding="utf-8")
        output_path = tmp_path / "comment.md"

        rc = cli_main(
            [
                "--report",
                str(report_path),
                "--adapter-name",
                "factspark",
                "--short-sha",
                "abc",
                "--output",
                str(output_path),
            ]
        )
        assert rc == 0
