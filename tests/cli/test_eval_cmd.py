"""End-to-end tests for `pipewise eval` (Phase 3 #25).

Wires CLI → adapter resolver → dataset loader → scorer config / defaults →
runner → storage. Each test uses a synthetic in-memory adapter module so we
don't depend on any specific reference adapter being installed.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pipewise import EvalReport, PipelineRun, StepExecution
from pipewise.cli import app

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
runner = CliRunner()


def _make_run(run_id: str = "run_1") -> PipelineRun:
    return PipelineRun(
        run_id=run_id,
        pipeline_name="fake",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status="completed",
        adapter_name="fake-adapter",
        adapter_version="0.0.1",
        steps=[
            StepExecution(
                step_id="s1",
                step_name="S1",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
                status="completed",
                outputs={"value": "ok"},
            )
        ],
    )


def _install_adapter(name: str, attrs: dict[str, object]) -> None:
    module = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(module, k, v)
    sys.modules[name] = module


def _write_dataset(path: Path, runs: list[PipelineRun]) -> None:
    path.write_text("\n".join(r.model_dump_json() for r in runs))


@pytest.fixture
def adapter_with_defaults(monkeypatch: pytest.MonkeyPatch) -> str:
    """Synthetic adapter module that provides a passing default step scorer."""
    from pipewise import ScoreResult

    class _AlwaysPassStepScorer:
        name = "always-pass"

        def score(
            self, actual: StepExecution, expected: StepExecution | None = None
        ) -> ScoreResult:
            return ScoreResult(score=1.0, status="passed")

    def default_scorers() -> tuple[list[object], list[object]]:
        return ([_AlwaysPassStepScorer()], [])

    name = "fake_eval_adapter_pass"
    _install_adapter(name, {"load_run": lambda p: None, "default_scorers": default_scorers})
    monkeypatch.setitem(sys.modules, name, sys.modules[name])
    return name


@pytest.fixture
def adapter_with_failing_defaults(monkeypatch: pytest.MonkeyPatch) -> str:
    from pipewise import ScoreResult

    class _AlwaysFailStepScorer:
        name = "always-fail"

        def score(
            self, actual: StepExecution, expected: StepExecution | None = None
        ) -> ScoreResult:
            return ScoreResult(score=0.0, status="failed", reasoning="nope")

    def default_scorers() -> tuple[list[object], list[object]]:
        return ([_AlwaysFailStepScorer()], [])

    name = "fake_eval_adapter_fail"
    _install_adapter(name, {"load_run": lambda p: None, "default_scorers": default_scorers})
    monkeypatch.setitem(sys.modules, name, sys.modules[name])
    return name


@pytest.fixture
def adapter_no_defaults(monkeypatch: pytest.MonkeyPatch) -> str:
    name = "fake_eval_adapter_no_defaults"
    _install_adapter(name, {"load_run": lambda p: None})
    monkeypatch.setitem(sys.modules, name, sys.modules[name])
    return name


class TestEvalCommand:
    def test_end_to_end_passing_eval_writes_report_and_exits_zero(
        self, tmp_path: Path, adapter_with_defaults: str
    ) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1"), _make_run("run_2")])
        output_root = tmp_path / "reports"

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                adapter_with_defaults,
                "--output-root",
                str(output_root),
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert "Evaluated 2 run(s)" in result.stdout
        assert "2/2 passing" in result.stdout

        # Exactly one timestamped subdir; report.json round-trips.
        subdirs = list(output_root.iterdir())
        assert len(subdirs) == 1
        report_path = subdirs[0] / "report.json"
        assert report_path.exists()
        report = EvalReport.model_validate_json(report_path.read_text())
        assert len(report.runs) == 2

    def test_failing_scorer_yields_nonzero_exit(
        self, tmp_path: Path, adapter_with_failing_defaults: str
    ) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])
        output_root = tmp_path / "reports"

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                adapter_with_failing_defaults,
                "--output-root",
                str(output_root),
            ],
        )

        assert result.exit_code == 1
        assert "0/1 passing" in result.stdout

    def test_explicit_scorers_override_adapter_defaults(
        self, tmp_path: Path, adapter_with_failing_defaults: str
    ) -> None:
        # Adapter provides a failing scorer; --scorers passes a different
        # config that uses a built-in passing-pattern scorer.
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])
        config = tmp_path / "scorers.toml"
        config.write_text(
            """
            [scorers.regex-passes]
            class = "pipewise.scorers.regex.RegexScorer"
            field = "value"
            pattern = "^ok$"
            """
        )
        output_root = tmp_path / "reports"

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                adapter_with_failing_defaults,
                "--scorers",
                str(config),
                "--output-root",
                str(output_root),
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert "1/1 passing" in result.stdout

    def test_adapter_without_defaults_and_no_scorers_flag_is_clear_error(
        self, tmp_path: Path, adapter_no_defaults: str
    ) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                adapter_no_defaults,
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )
        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "default_scorers" in combined
        assert "--scorers" in combined

    def test_unknown_adapter_module_is_clear_error(self, tmp_path: Path) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])
        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                "definitely.not.real.zzz_module",
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )
        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "could not import" in combined.lower()

    def test_missing_dataset_is_clear_error(
        self, tmp_path: Path, adapter_with_defaults: str
    ) -> None:
        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(tmp_path / "nope.jsonl"),
                "--adapter",
                adapter_with_defaults,
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )
        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "not found" in combined.lower()

    def test_scorers_toml_works_without_adapter_flag(self, tmp_path: Path) -> None:
        # When --scorers is supplied, --adapter is no longer required: the
        # explicit-scorers branch never resolves the adapter.
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])
        config = tmp_path / "scorers.toml"
        config.write_text(
            """
            [scorers.regex-passes]
            class = "pipewise.scorers.regex.RegexScorer"
            field = "value"
            pattern = "^ok$"
            """
        )
        output_root = tmp_path / "reports"

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--scorers",
                str(config),
                "--output-root",
                str(output_root),
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert "1/1 passing" in result.stdout

    def test_multi_run_failure_cluster_surfaces_top_failure_line(
        self, tmp_path: Path, adapter_with_failing_defaults: str
    ) -> None:
        # 3 runs x always-fail step scorer = 3 identical failures.
        # The eval summary should emit a "Top failure: 3 of s1/always-fail (nope)" line.
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(
            dataset,
            [_make_run("run_1"), _make_run("run_2"), _make_run("run_3")],
        )

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                adapter_with_failing_defaults,
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )

        assert result.exit_code == 1
        assert "0/3 passing" in result.stdout
        assert "Top failure:" in result.stdout
        assert "3 of s1/always-fail" in result.stdout
        assert "nope" in result.stdout

    def test_single_failure_suppresses_top_failure_line(
        self, tmp_path: Path, adapter_with_failing_defaults: str
    ) -> None:
        # Only 1 run → top cluster has count=1 → no "Top failure" line
        # (clustering hint only adds value when there's an actual cluster).
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                adapter_with_failing_defaults,
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )

        assert result.exit_code == 1
        assert "0/1 passing" in result.stdout
        assert "Top failure:" not in result.stdout

    def test_run_scorer_cluster_omits_step_id_from_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A run scorer that always fails should produce a cluster keyed on
        # the scorer name only (no step_id) — output line shows "N of <name>"
        # without a step prefix.
        from pipewise import ScoreResult

        class _AlwaysFailRunScorer:
            name = "run-fail"

            def score(self, run: PipelineRun) -> ScoreResult:
                return ScoreResult(score=0.0, status="failed", reasoning="run-level-fail")

        def default_scorers() -> tuple[list[object], list[object]]:
            return ([], [_AlwaysFailRunScorer()])

        name = "fake_run_scorer_fail"
        _install_adapter(name, {"load_run": lambda p: None, "default_scorers": default_scorers})
        monkeypatch.setitem(sys.modules, name, sys.modules[name])

        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1"), _make_run("run_2")])

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                name,
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )

        assert result.exit_code == 1
        assert "Top failure: 2 of run-fail" in result.stdout
        # No step_id slash for run-level scorers.
        assert "/run-fail" not in result.stdout
        assert "run-level-fail" in result.stdout

    def test_long_reasoning_is_truncated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reasoning longer than 80 chars should appear with a "..." suffix.
        from pipewise import ScoreResult

        long_reason = "x" * 200

        class _LongReasonStepScorer:
            name = "long-reason"

            def score(
                self, actual: StepExecution, expected: StepExecution | None = None
            ) -> ScoreResult:
                return ScoreResult(score=0.0, status="failed", reasoning=long_reason)

        def default_scorers() -> tuple[list[object], list[object]]:
            return ([_LongReasonStepScorer()], [])

        name = "fake_long_reason"
        _install_adapter(name, {"load_run": lambda p: None, "default_scorers": default_scorers})
        monkeypatch.setitem(sys.modules, name, sys.modules[name])

        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1"), _make_run("run_2")])

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                name,
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )

        assert result.exit_code == 1
        assert "Top failure:" in result.stdout
        assert "..." in result.stdout
        # The full 200-char reasoning should NOT be in the summary line.
        assert long_reason not in result.stdout

    def test_neither_adapter_nor_scorers_is_clear_error(self, tmp_path: Path) -> None:
        dataset = tmp_path / "ds.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--output-root",
                str(tmp_path / "reports"),
            ],
        )

        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "--adapter" in combined
        assert "--scorers" in combined

    def test_dataset_name_defaults_to_filename_stem(
        self, tmp_path: Path, adapter_with_defaults: str
    ) -> None:
        dataset = tmp_path / "news-analysis-golden.jsonl"
        _write_dataset(dataset, [_make_run("run_1")])
        output_root = tmp_path / "reports"

        result = runner.invoke(
            app,
            [
                "eval",
                "--dataset",
                str(dataset),
                "--adapter",
                adapter_with_defaults,
                "--output-root",
                str(output_root),
            ],
        )

        assert result.exit_code == 0
        subdir = next(output_root.iterdir())
        assert subdir.name.endswith("_news-analysis-golden")
