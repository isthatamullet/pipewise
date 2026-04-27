"""Tests for the JSONL dataset loader (Phase 3 #20)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipewise import PipelineRun
from pipewise.runner.dataset import DatasetError, load_dataset

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _make_run(run_id: str = "run_1") -> dict[str, object]:
    return {
        "run_id": run_id,
        "pipeline_name": "factspark",
        "started_at": NOW.isoformat(),
        "completed_at": NOW.isoformat(),
        "status": "completed",
        "adapter_name": "factspark-adapter",
        "adapter_version": "0.1.0",
        "steps": [],
    }


class TestLoadDataset:
    def test_yields_runs_from_valid_dataset(self, tmp_path: Path) -> None:
        dataset = tmp_path / "golden.jsonl"
        dataset.write_text(
            json.dumps(_make_run("run_1")) + "\n" + json.dumps(_make_run("run_2")) + "\n"
        )

        runs = list(load_dataset(dataset))

        assert len(runs) == 2
        assert all(isinstance(r, PipelineRun) for r in runs)
        assert [r.run_id for r in runs] == ["run_1", "run_2"]

    def test_skips_blank_and_comment_lines(self, tmp_path: Path) -> None:
        dataset = tmp_path / "golden.jsonl"
        dataset.write_text(
            "# comment at top\n"
            "\n"
            f"{json.dumps(_make_run('run_1'))}\n"
            "   \n"
            "# another comment\n"
            f"{json.dumps(_make_run('run_2'))}\n"
        )

        runs = list(load_dataset(dataset))

        assert [r.run_id for r in runs] == ["run_1", "run_2"]

    def test_empty_file_yields_nothing(self, tmp_path: Path) -> None:
        dataset = tmp_path / "empty.jsonl"
        dataset.write_text("")

        assert list(load_dataset(dataset)) == []

    def test_file_only_blank_and_comments_yields_nothing(self, tmp_path: Path) -> None:
        dataset = tmp_path / "comments.jsonl"
        dataset.write_text("\n# comment\n\n# another\n")

        assert list(load_dataset(dataset)) == []

    def test_missing_file_raises_filenotfound(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.jsonl"

        with pytest.raises(FileNotFoundError, match=r"does_not_exist\.jsonl"):
            list(load_dataset(missing))

    def test_invalid_json_raises_with_line_number(self, tmp_path: Path) -> None:
        dataset = tmp_path / "bad.jsonl"
        dataset.write_text(
            f"{json.dumps(_make_run('run_1'))}\n"
            "not valid json {\n"
            f"{json.dumps(_make_run('run_3'))}\n"
        )

        with pytest.raises(DatasetError, match=r":2: invalid JSON"):
            list(load_dataset(dataset))

    def test_invalid_pipeline_run_raises_with_line_number(self, tmp_path: Path) -> None:
        bad_run = _make_run("run_1")
        del bad_run["pipeline_name"]  # required field
        dataset = tmp_path / "bad_schema.jsonl"
        dataset.write_text(f"{json.dumps(_make_run('run_0'))}\n{json.dumps(bad_run)}\n")

        with pytest.raises(DatasetError, match=r":2: invalid PipelineRun"):
            list(load_dataset(dataset))

    def test_iterator_is_lazy(self, tmp_path: Path) -> None:
        # If a dataset has a bad line, we should still see runs before it via
        # iteration before the error fires. This documents the streaming
        # contract — `load_dataset` doesn't pre-validate the whole file.
        dataset = tmp_path / "mixed.jsonl"
        dataset.write_text(f"{json.dumps(_make_run('run_1'))}\ngarbage{{\n")

        it = load_dataset(dataset)
        first = next(it)
        assert first.run_id == "run_1"
        with pytest.raises(DatasetError):
            next(it)
