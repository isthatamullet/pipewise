"""pipewise runner — eval execution, dataset loading, adapter resolution."""

from pipewise.runner.adapter import (
    AdapterCallable,
    AdapterError,
    resolve_adapter,
    resolve_default_scorers,
)
from pipewise.runner.dataset import DatasetError, load_dataset
from pipewise.runner.diff import ReportDiff, ScoreDiffEntry, compute_diff, format_diff
from pipewise.runner.eval import run_eval
from pipewise.runner.inspect import format_run
from pipewise.runner.scorer_config import ScorerConfigError, load_scorer_config
from pipewise.runner.storage import write_report

__all__ = [
    "AdapterCallable",
    "AdapterError",
    "DatasetError",
    "ReportDiff",
    "ScoreDiffEntry",
    "ScorerConfigError",
    "compute_diff",
    "format_diff",
    "format_run",
    "load_dataset",
    "load_scorer_config",
    "resolve_adapter",
    "resolve_default_scorers",
    "run_eval",
    "write_report",
]
