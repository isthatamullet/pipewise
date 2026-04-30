"""Tests for `pipewise inspect` and the underlying `format_run` formatter (#24)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pipewise import PipelineRun, StepExecution
from pipewise.cli import app
from pipewise.runner.inspect import format_run

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
runner = CliRunner()


def _run(steps: list[StepExecution] | None = None) -> PipelineRun:
    return PipelineRun(
        run_id="run_42",
        pipeline_name="factspark",
        pipeline_version="1.2.0",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=12),
        status="completed",
        adapter_name="factspark-adapter",
        adapter_version="0.1.0",
        steps=steps if steps is not None else [],
        total_cost_usd=0.0349,
        total_latency_ms=12000,
        total_input_tokens=2000,
        total_output_tokens=500,
    )


def _step(step_id: str = "s1", outputs: dict[str, object] | None = None) -> StepExecution:
    return StepExecution(
        step_id=step_id,
        step_name=step_id.upper(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1, milliseconds=500),
        status="completed",
        executor="stupid-meter",
        model="claude-opus-4-7",
        cost_usd=0.0123,
        latency_ms=1500,
        outputs=outputs or {"value": "ok"},
    )


class TestFormatRun:
    def test_includes_run_pipeline_adapter_identifiers(self) -> None:
        out = format_run(_run([_step()]))
        assert "Run:" in out
        assert "run_42" in out
        assert "factspark@1.2.0" in out
        assert "factspark-adapter@0.1.0" in out

    def test_pipeline_id_omits_at_when_no_version(self) -> None:
        run = _run([_step()])
        run = run.model_copy(update={"pipeline_version": None})
        out = format_run(run)
        assert "factspark@" not in out
        assert "factspark" in out

    def test_lists_steps(self) -> None:
        out = format_run(_run([_step("s1"), _step("s2")]))
        assert "Steps (2)" in out
        assert "1. s1 [completed]" in out
        assert "2. s2 [completed]" in out

    def test_no_steps_renders_none_marker(self) -> None:
        out = format_run(_run([]))
        assert "Steps (0)" in out
        assert "(none)" in out

    def test_truncates_long_output_values_by_default(self) -> None:
        long_value = "x" * 500
        out = format_run(_run([_step(outputs={"value": long_value})]))
        assert long_value not in out  # too long, must be truncated
        assert "…" in out

    def test_full_flag_disables_truncation(self) -> None:
        long_value = "x" * 500
        out = format_run(_run([_step(outputs={"value": long_value})]), full=True)
        assert long_value in out

    def test_includes_totals_when_present(self) -> None:
        out = format_run(_run([_step()]))
        assert "Totals:" in out
        assert "cost=$0.0349" in out
        assert "latency=12000ms" in out
        assert "input_tokens=2000" in out
        assert "output_tokens=500" in out

    def test_omits_totals_when_all_missing(self) -> None:
        run = _run([_step()]).model_copy(
            update={
                "total_cost_usd": None,
                "total_latency_ms": None,
                "total_input_tokens": None,
                "total_output_tokens": None,
            }
        )
        assert "Totals:" not in format_run(run)

    def test_keys_mode_renders_top_level_structure(self) -> None:
        # Real-pipeline-shaped step: nested dict + list + scalar.
        outputs = {
            "article_metadata": {"title": "T", "source": "BBC", "author": "X"},
            "extracted_claims": [{"id": 1}, {"id": 2}, {"id": 3}],
            "full_article_content": "lots of text here " * 100,
            "score": 7,
        }
        out = format_run(_run([_step(outputs=outputs)]), keys=True)
        assert "article_metadata: dict[3]" in out
        assert "extracted_claims: list[3]" in out
        assert "full_article_content: str" in out
        assert "score: int" in out
        # Values must NOT appear in keys mode.
        assert "BBC" not in out
        assert "lots of text here" not in out

    def test_keys_mode_handles_empty_dict(self) -> None:
        # Build a step with explicitly-empty outputs (bypassing _step's
        # `outputs or default` falsy-coalesce so we actually get `{}`).
        empty_step = StepExecution(
            step_id="s1",
            step_name="S1",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=1),
            status="completed",
            outputs={},
        )
        out = format_run(_run([empty_step]), keys=True)
        # Empty outputs render as `{}` (same as the default mode).
        assert "outputs: {}" in out

    def test_keys_mode_handles_none_and_bool_and_float(self) -> None:
        outputs = {"missing": None, "flag": True, "ratio": 0.42}
        out = format_run(_run([_step(outputs=outputs)]), keys=True)
        assert "missing: None" in out
        assert "flag: bool" in out
        assert "ratio: float" in out

    def test_keys_and_full_together_raise(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            format_run(_run([_step()]), full=True, keys=True)


class TestInspectCommand:
    def test_inspect_prints_text_summary_by_default(self, tmp_path: Path) -> None:
        run = _run([_step()])
        run_path = tmp_path / "run.json"
        run_path.write_text(run.model_dump_json())

        result = runner.invoke(app, ["inspect", str(run_path)])

        assert result.exit_code == 0, result.stdout
        assert "run_42" in result.stdout
        assert "factspark" in result.stdout

    def test_inspect_format_json_emits_valid_json_round_trip(self, tmp_path: Path) -> None:
        run = _run([_step()])
        run_path = tmp_path / "run.json"
        run_path.write_text(run.model_dump_json())

        result = runner.invoke(app, ["inspect", str(run_path), "--format", "json"])

        assert result.exit_code == 0
        roundtripped = PipelineRun.model_validate_json(result.stdout)
        assert roundtripped == run

    def test_inspect_full_flag_skips_truncation(self, tmp_path: Path) -> None:
        long_value = "x" * 500
        run = _run([_step(outputs={"value": long_value})])
        run_path = tmp_path / "run.json"
        run_path.write_text(run.model_dump_json())

        result = runner.invoke(app, ["inspect", str(run_path), "--full"])

        assert result.exit_code == 0
        assert long_value in result.stdout

    def test_inspect_missing_file_exits_with_clear_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        result = runner.invoke(app, ["inspect", str(missing)])
        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "file not found" in combined.lower()

    def test_inspect_invalid_pipelinerun_json_exits_with_clear_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text('{"this": "is not a PipelineRun"}')
        result = runner.invoke(app, ["inspect", str(bad)])
        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "not a valid pipelinerun" in combined.lower()

    def test_inspect_unknown_format_exits(self, tmp_path: Path) -> None:
        run = _run([_step()])
        run_path = tmp_path / "run.json"
        run_path.write_text(run.model_dump_json())

        result = runner.invoke(app, ["inspect", str(run_path), "--format", "xml"])
        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "unknown" in combined.lower()

    def test_inspect_keys_flag_renders_structural_summary(self, tmp_path: Path) -> None:
        outputs = {
            "article_metadata": {"a": 1, "b": 2, "c": 3},
            "claims": [{"id": 1}, {"id": 2}],
            "score": 42,
        }
        run = _run([_step(outputs=outputs)])
        run_path = tmp_path / "run.json"
        run_path.write_text(run.model_dump_json())

        result = runner.invoke(app, ["inspect", str(run_path), "--keys"])

        assert result.exit_code == 0, result.stdout
        assert "article_metadata: dict[3]" in result.stdout
        assert "claims: list[2]" in result.stdout
        assert "score: int" in result.stdout

    def test_inspect_keys_and_full_together_is_clear_error(self, tmp_path: Path) -> None:
        run = _run([_step()])
        run_path = tmp_path / "run.json"
        run_path.write_text(run.model_dump_json())

        result = runner.invoke(app, ["inspect", str(run_path), "--keys", "--full"])

        assert result.exit_code == 2
        combined = result.stdout + (result.stderr or "")
        assert "mutually exclusive" in combined.lower()
