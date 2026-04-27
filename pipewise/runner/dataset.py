"""JSONL dataset loader for `PipelineRun` golden datasets.

Phase 3 #20. The eval runner reads a dataset of `PipelineRun`s from a JSONL
file — one `PipelineRun` per line. Empty lines and `#`-prefixed comment lines
are skipped to make the format ergonomic for hand-edited goldens.

Pydantic validation errors are wrapped with the offending line number so the
user can fix the dataset without grepping line counts by hand.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from pipewise.core.schema import PipelineRun


class DatasetError(ValueError):
    """Raised when a dataset file cannot be parsed into PipelineRuns."""


def load_dataset(path: Path) -> Iterator[PipelineRun]:
    """Yield each `PipelineRun` from a JSONL dataset.

    The file is opened lazily; callers can stream large datasets without
    loading the whole file into memory. Errors include the 1-indexed line
    number of the offending line.

    Skipped:
        - Lines that are empty or whitespace-only
        - Lines whose first non-whitespace character is `#` (comments)

    Raises:
        FileNotFoundError: the dataset path does not exist.
        DatasetError: a non-skipped line is not valid JSON, or the parsed
            JSON does not satisfy the `PipelineRun` schema.
    """
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{path}:{line_no}: invalid JSON ({exc.msg})") from exc
            try:
                yield PipelineRun.model_validate(obj)
            except ValidationError as exc:
                raise DatasetError(
                    f"{path}:{line_no}: invalid PipelineRun ({exc.error_count()} "
                    f"validation error{'s' if exc.error_count() != 1 else ''})\n{exc}"
                ) from exc


__all__ = ["DatasetError", "load_dataset"]
