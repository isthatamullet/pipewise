"""Append-only, timestamped report storage.

Phase 3 #23. Each `pipewise eval` invocation writes to a fresh subdirectory
named after its `generated_at` timestamp + a dataset label. Reports are never
overwritten — same dataset run twice produces two directories.

Layout (per CLAUDE.md immutability rule):
    <output_root>/
    └── 20260427T091500Z_<dataset_or_adhoc>/
        └── report.json

Filename uses ISO 8601 basic format in UTC so directory listings sort
chronologically without extra tooling.
"""

from __future__ import annotations

from pathlib import Path

from pipewise.core.report import EvalReport

_DEFAULT_OUTPUT_ROOT = Path("pipewise/reports")
_REPORT_FILENAME = "report.json"


def _format_directory_name(report: EvalReport) -> str:
    """Build the timestamped directory name for one report."""
    timestamp = report.generated_at.strftime("%Y%m%dT%H%M%SZ")
    label = report.dataset_name if report.dataset_name is not None else "adhoc"
    return f"{timestamp}_{label}"


def write_report(
    report: EvalReport,
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
) -> Path:
    """Persist an `EvalReport` to a fresh timestamped subdirectory.

    Args:
        report: The report to persist.
        output_root: Parent directory for all reports. Created with
            `parents=True, exist_ok=True` if missing.

    Returns:
        Absolute-form `Path` to the written `report.json`.

    Raises:
        FileExistsError: A directory for this exact timestamp + dataset label
            already exists. Reports are immutable — never overwrites prior
            output. (In practice this only fires if two evals are kicked off
            within the same UTC second with the same dataset name.)
    """
    output_root.mkdir(parents=True, exist_ok=True)

    report_dir = output_root / _format_directory_name(report)
    if report_dir.exists():
        raise FileExistsError(
            f"Report directory already exists: {report_dir}. Reports are "
            "append-only and never overwrite prior output."
        )
    report_dir.mkdir()

    report_path = report_dir / _REPORT_FILENAME
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report_path


__all__ = ["write_report"]
