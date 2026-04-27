"""pipewise — evaluation framework for multi-step LLM pipelines."""

from importlib.metadata import PackageNotFoundError, version

from pipewise.core.schema import (
    PipelineRun,
    RunStatus,
    StepExecution,
    StepStatus,
)
from pipewise.core.scorer import (
    RunScorer,
    ScoreResult,
    StepScorer,
)

try:
    __version__ = version("pipewise")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"

__all__ = [
    "PipelineRun",
    "RunScorer",
    "RunStatus",
    "ScoreResult",
    "StepExecution",
    "StepScorer",
    "StepStatus",
    "__version__",
]
