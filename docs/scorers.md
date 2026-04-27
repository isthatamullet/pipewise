# Scorers reference

> Quick reference for the eight built-in scorers shipped in v1. For the
> full schema and adapter contract, see [`schema.md`](schema.md) and
> [`adapter-guide.md`](adapter-guide.md).

A scorer evaluates one aspect of a step or run. Pipewise ships two protocol shapes:

- **`StepScorer`** — evaluates a single `StepExecution`, optionally with an `expected` reference step.
- **`RunScorer`** — evaluates an entire `PipelineRun`.

Every scorer returns a `ScoreResult` with a normalized `score: float` in `[0.0, 1.0]`, a boolean `passed`, optional `reasoning` text, and a metadata dict.

Implement either protocol on your own class to add a custom scorer; pipewise's runner doesn't care whether a scorer is built-in or external.

## At a glance

| Scorer | Kind | Requires `expected`? | Optional extra |
|---|---|---|---|
| [`ExactMatchScorer`](#exactmatchscorer) | step | yes | — |
| [`RegexScorer`](#regexscorer) | step | no | — |
| [`NumericToleranceScorer`](#numerictolerancescorer) | step | yes | — |
| [`JsonSchemaScorer`](#jsonschemascorer) | step | no | — |
| [`EmbeddingSimilarityScorer`](#embeddingsimilarityscorer) | step | yes | `[embeddings]` |
| [`LlmJudgeScorer`](#llmjudgescorer) | step | optional | `[llm-judge]` |
| [`CostBudgetScorer`](#costbudgetscorer) | run | no | — |
| [`LatencyBudgetScorer`](#latencybudgetscorer) | run | no | — |

---

## `ExactMatchScorer`

Field-level deep equality. Score is the fraction of fields that matched; `passed` is True iff every requested field matched.

```python
from pipewise.scorers import ExactMatchScorer

scorer = ExactMatchScorer(fields=["title", "stupidity_rating"])
result = scorer.score(actual=actual_step, expected=golden_step)
# result.score == 1.0 if both fields match; 0.5 if one matches; 0.0 if neither
```

Useful for golden-output testing where structured output is supposed to be byte-stable.

## `RegexScorer`

Regex match against a string field in `outputs`. Self-contained — no `expected` required.

```python
import re
from pipewise.scorers import RegexScorer

scorer = RegexScorer(field="title", pattern=r"^[A-Z]")          # default: search
scorer = RegexScorer(field="id", pattern=r"\d{4}", match_mode="fullmatch")
scorer = RegexScorer(field="text", pattern=re.compile(r"foo"))  # accepts compiled patterns
```

`match_mode` is one of `"search"` (default), `"fullmatch"`, or `"match"`. Missing or non-string fields fail with explanatory `reasoning`.

## `NumericToleranceScorer`

Pass when `|actual - expected| <= tolerance` for a numeric field. Two modes: absolute (default) or relative (`tolerance` interpreted as a fraction).

```python
from pipewise.scorers import NumericToleranceScorer

# Absolute: catch FactSpark's stupidity_rating shifting by more than 10 points
abs_scorer = NumericToleranceScorer(field="stupidity_rating", tolerance=10)

# Relative: catch a cost field drifting more than 10% from baseline
rel_scorer = NumericToleranceScorer(field="cost_usd", tolerance=0.1, relative=True)
```

Bools are explicitly rejected (Python `bool` is technically `int`, but `True/1` shouldn't compare numerically).

## `JsonSchemaScorer`

Validate `outputs` against a JSON Schema document. The schema is checked once at construction so typos and malformed `type` keywords surface there rather than on the first scoring call.

```python
from pipewise.scorers import JsonSchemaScorer

scorer = JsonSchemaScorer(schema={
    "type": "object",
    "required": ["title", "stupidity_rating"],
    "properties": {
        "title": {"type": "string"},
        "stupidity_rating": {"type": "integer", "minimum": 0, "maximum": 100},
    },
})
result = scorer.score(actual_step)
# Reasoning lists up to the first 5 errors with their JSON-pointer paths
```

## `EmbeddingSimilarityScorer`

Cosine similarity on sentence-transformers embeddings of a text field. Default model is `all-MiniLM-L6-v2` (~80MB). Lazy-loaded — the import doesn't fire until `.score()` is called.

```python
# Requires: pip install 'pipewise[embeddings]'
from pipewise.scorers import EmbeddingSimilarityScorer

scorer = EmbeddingSimilarityScorer(field="summary", threshold=0.8)
result = scorer.score(actual=actual_step, expected=golden_step)
# result.score is the cosine similarity (clamped to [0, 1])
# result.passed is score >= threshold
```

Negative cosine similarity (near-opposite meanings) is clamped to 0; the raw value is preserved in `metadata["raw_similarity"]`.

## `LlmJudgeScorer`

Use Claude as a judge to score a step's output against a rubric. Anthropic-only in v1.

```python
# Requires: pip install 'pipewise[llm-judge]'
# Requires: ANTHROPIC_API_KEY env var
from pipewise.scorers import LlmJudgeScorer

scorer = LlmJudgeScorer(
    rubric=(
        "The output must include a 'title' field that accurately summarizes "
        "the article. Score 1.0 for accurate, 0.5 for partial, 0.0 for missing."
    ),
    model="claude-sonnet-4-6",   # default
    consensus_n=1,                # set to 3 in CI for non-determinism mitigation
    cost_ceiling_usd=5.0,         # per scorer instance; reset_cost() to start fresh
)
result = scorer.score(actual_step)
print(f"${scorer.cumulative_cost_usd:.4f} spent so far")
```

**Caching:** the rubric + examples are wrapped in a `cache_control` system block, so the first call writes the cache and every subsequent call reads it at ~0.1x the input cost.

**Consensus:** `consensus_n=3` makes three independent judge calls per step; the verdict passes when at least `(n // 2) + 1` agree (majority). Trades cost for noise tolerance.

**Cost ceiling:** the scorer aborts pre-call once its cumulative spend has met or exceeded `cost_ceiling_usd`. A single call may slightly overshoot. Set to `None` to disable.

## `CostBudgetScorer`

Run-level scorer. Pass when `run.total_cost_usd <= budget_usd`.

```python
from pipewise.scorers import CostBudgetScorer

scorer = CostBudgetScorer(budget_usd=0.50)
result = scorer.score(pipeline_run)
```

When `total_cost_usd` is `None` (the adapter didn't capture it), default behavior is `on_missing="fail"` — silent passing on missing data masks real problems. Override with `on_missing="skip"` for adapters that don't track cost.

## `LatencyBudgetScorer`

Run-level scorer. Pass when `run.total_latency_ms <= budget_ms`.

```python
from pipewise.scorers import LatencyBudgetScorer

scorer = LatencyBudgetScorer(budget_ms=30_000)
result = scorer.score(pipeline_run)
```

Same `on_missing` semantics as `CostBudgetScorer`.

---

## Running scorers end-to-end

The runnable script [`examples/demo_phase2_scorers.py`](../examples/demo_phase2_scorers.py) exercises all eight scorers on a representative pipeline step. It loads a real FactSpark step output if one is available locally; otherwise it falls back to a synthetic step with the same shape.

```bash
uv run python examples/demo_phase2_scorers.py
# Add --use-llm to also run LlmJudgeScorer against the real Anthropic API
# (requires ANTHROPIC_API_KEY and the [llm-judge] extra installed).
```

---

## Writing your own scorer

A scorer is any class with a `name` attribute and a `score()` method matching the protocol shape. The simplest possible step scorer:

```python
from pipewise import ScoreResult, StepExecution

class IsNonEmptyScorer:
    name = "outputs_non_empty"

    def score(self, actual: StepExecution, expected: StepExecution | None = None) -> ScoreResult:
        is_non_empty = bool(actual.outputs)
        return ScoreResult(
            score=1.0 if is_non_empty else 0.0,
            passed=is_non_empty,
            reasoning=None if is_non_empty else "outputs dict is empty",
        )
```

Pipewise's runner accepts any object satisfying the protocol — built-in or yours — without further registration.
