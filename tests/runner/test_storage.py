"""Tests for report storage (Phase 3 #23)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipewise import EvalReport, RunEvalResult
from pipewise.runner.storage import write_report

NOW = datetime(2026, 4, 27, 9, 15, 0, tzinfo=UTC)


def _report(
    *,
    generated_at: datetime = NOW,
    dataset_name: str | None = "factspark-golden-v1",
    report_id: str | None = None,
) -> EvalReport:
    return EvalReport(
        report_id=report_id or f"{dataset_name or 'adhoc'}_test",
        generated_at=generated_at,
        pipewise_version="0.0.1",
        dataset_name=dataset_name,
        scorer_names=["fake-scorer"],
        runs=[
            RunEvalResult(
                run_id="run_1",
                pipeline_name="fake",
                adapter_name="fake-adapter",
                adapter_version="0.0.1",
            )
        ],
    )


class TestWriteReport:
    def test_writes_report_to_timestamped_subdirectory(self, tmp_path: Path) -> None:
        report_path = write_report(_report(), output_root=tmp_path)

        assert report_path.exists()
        assert report_path.name == "report.json"
        assert report_path.parent.name == "20260427T091500Z_factspark-golden-v1"
        assert report_path.parent.parent == tmp_path

    def test_returned_path_contents_round_trip(self, tmp_path: Path) -> None:
        original = _report()
        path = write_report(original, output_root=tmp_path)

        roundtripped = EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
        assert roundtripped == original

    def test_adhoc_label_when_dataset_name_is_none(self, tmp_path: Path) -> None:
        path = write_report(
            _report(dataset_name=None, report_id="adhoc_test"),
            output_root=tmp_path,
        )
        assert path.parent.name == "20260427T091500Z_adhoc"

    def test_two_reports_with_different_timestamps_create_two_dirs(self, tmp_path: Path) -> None:
        first = _report(generated_at=NOW)
        second = _report(generated_at=NOW.replace(minute=16))

        first_path = write_report(first, output_root=tmp_path)
        second_path = write_report(second, output_root=tmp_path)

        assert first_path != second_path
        assert first_path.parent != second_path.parent
        assert {p.name for p in tmp_path.iterdir()} == {
            "20260427T091500Z_factspark-golden-v1",
            "20260427T091600Z_factspark-golden-v1",
        }

    def test_output_root_is_created_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "does" / "not" / "exist"
        assert not nested.exists()

        path = write_report(_report(), output_root=nested)

        assert path.exists()
        assert nested.exists()

    def test_collision_raises_file_exists_error(self, tmp_path: Path) -> None:
        # Same timestamp + same dataset name = collision. The append-only
        # rule means we must refuse to overwrite, not silently clobber.
        write_report(_report(), output_root=tmp_path)

        with pytest.raises(FileExistsError, match="append-only"):
            write_report(_report(), output_root=tmp_path)

    def test_json_is_indented_for_readability(self, tmp_path: Path) -> None:
        path = write_report(_report(), output_root=tmp_path)
        text = path.read_text(encoding="utf-8")
        # 2-space indent is human-reviewable; one-line JSON is not.
        assert "\n  " in text

    def test_directory_basename_is_iso_8601_basic_format(self, tmp_path: Path) -> None:
        path = write_report(_report(), output_root=tmp_path)
        # ISO 8601 basic: YYYYMMDDTHHMMSSZ — no separators inside date or time.
        prefix = path.parent.name.split("_")[0]
        assert len(prefix) == 16
        assert prefix[8] == "T"
        assert prefix.endswith("Z")
        assert prefix[:8].isdigit()
        assert prefix[9:15].isdigit()
