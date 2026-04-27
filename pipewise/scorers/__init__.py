"""Built-in scorers.

The eight scorers shipped in v1 cover the most common evaluation needs:

| Scorer | Kind | What it scores |
|---|---|---|
| `ExactMatchScorer` | step | Field-level deep equality on `outputs` |
| `RegexScorer` | step | Regex match against a string field |
| `NumericToleranceScorer` | step | `|actual - expected| <= tolerance` on a numeric field |
| `JsonSchemaScorer` | step | Validates `outputs` against a JSON Schema |
| `EmbeddingSimilarityScorer` | step | Cosine similarity on sentence-transformers embeddings (gated behind `[embeddings]`) |
| `LlmJudgeScorer` | step | Claude-as-judge with rubric + structured output (gated behind `[llm-judge]`) |
| `CostBudgetScorer` | run | `total_cost_usd <= budget_usd` |
| `LatencyBudgetScorer` | run | `total_latency_ms <= budget_ms` |

Adapter authors and pipeline owners typically pick a few of these per step.
Custom scorers implement the `StepScorer` / `RunScorer` protocols; see
`pipewise.core.scorer`.
"""

from pipewise.scorers.budget import CostBudgetScorer, LatencyBudgetScorer, OnMissing
from pipewise.scorers.embedding import EmbeddingSimilarityScorer
from pipewise.scorers.exact_match import ExactMatchScorer
from pipewise.scorers.json_schema import JsonSchemaScorer
from pipewise.scorers.llm_judge import CostCeilingExceeded, LlmJudgeScorer
from pipewise.scorers.numeric_tolerance import NumericToleranceScorer
from pipewise.scorers.regex import MatchMode, RegexScorer

__all__ = [
    "CostBudgetScorer",
    "CostCeilingExceeded",
    "EmbeddingSimilarityScorer",
    "ExactMatchScorer",
    "JsonSchemaScorer",
    "LatencyBudgetScorer",
    "LlmJudgeScorer",
    "MatchMode",
    "NumericToleranceScorer",
    "OnMissing",
    "RegexScorer",
]
