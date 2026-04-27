"""pipewise runner — eval execution, dataset loading, adapter resolution."""

from pipewise.runner.adapter import AdapterCallable, AdapterError, resolve_adapter
from pipewise.runner.dataset import DatasetError, load_dataset
from pipewise.runner.eval import run_eval
from pipewise.runner.storage import write_report

__all__ = [
    "AdapterCallable",
    "AdapterError",
    "DatasetError",
    "load_dataset",
    "resolve_adapter",
    "run_eval",
    "write_report",
]
