"""pipewise — evaluation framework for multi-step LLM pipelines."""

from importlib.metadata import PackageNotFoundError, version

from pipewise.core.report import (
    EvalReport,
    RunEvalResult,
    RunScoreEntry,
    StepScoreEntry,
)
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
    "EvalReport",
    "PipelineRun",
    "RunEvalResult",
    "RunScoreEntry",
    "RunScorer",
    "RunStatus",
    "ScoreResult",
    "StepExecution",
    "StepScoreEntry",
    "StepScorer",
    "StepStatus",
    "__version__",
]
