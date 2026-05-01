# Scorers reference

> Quick reference for the eight built-in scorers shipped in v1. For the
> full schema and adapter contract, see [`schema.md`](schema.md) and
> [`adapter-guide.md`](adapter-guide.md).
>
> **`LlmJudgeScorer` is the only scorer that calls a paid API.** Adapter
> authors should NOT include it in `default_scorers()` — surprise API
> costs hurt UX for first-time users. Document it as a recommended
> opt-in; users enable it explicitly via `pipewise eval --scorers <toml>`.

A scorer evaluates one aspect of a step or run. Pipewise ships two protocol shapes:

- **`StepScorer`** — evaluates a single `StepExecution`, optionally with an `expected` reference step.
- **`RunScorer`** — evaluates an entire `PipelineRun`.

Every scorer returns a `ScoreResult` with these fields:

- `status: Literal["passed", "failed", "skipped"]` — the verdict.
- `score: float | None` — normalized in `[0.0, 1.0]` when `status` is `"passed"` or `"failed"`; `None` when `"skipped"` (a skipped scorer didn't compute a score).
- `reasoning: str | None` — optional free-text explanation.
- `metadata: dict[str, Any]` — scorer-specific extension data.

See [Skipped scorers and `applies_to_step_ids`](#skipped-scorers-and-applies_to_step_ids) below for when scorers emit `"skipped"`.

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

All step scorers accept an `applies_to_step_ids: Sequence[str] | None` kwarg — see the next section.

---

## Skipped scorers and `applies_to_step_ids`

A scorer can emit `status="skipped"` when it didn't actually evaluate. Three places this happens:

1. **Out-of-scope step** — every built-in step scorer accepts an `applies_to_step_ids: Sequence[str] | None` kwarg. When set, the runner emits a `skipped` `ScoreResult` for steps whose `step_id` isn't listed, without invoking the scorer's `score()` body.

2. **Upstream step skipped** — when a step's own `status` is `"skipped"` (e.g., a branching pipeline that didn't execute one of two mutually exclusive branches), the runner auto-skips every scorer for that step. Failed steps still get scored — partial outputs may carry signal.

3. **Budget scorers with `on_missing="skip"`** — `CostBudgetScorer` and `LatencyBudgetScorer` emit `skipped` when their `total_*` field is missing on the run AND `on_missing="skip"` is configured. Indicates the scorer didn't have data to evaluate against.

### Example: scoping a regex to specific steps

A regex check that only makes sense on steps producing user-facing text:

```python
from pipewise.scorers import RegexScorer

scorer = RegexScorer(
    field="body_text",
    pattern=r".{100,}",
    applies_to_step_ids=["analyze", "step_b", "step_c"],
    name="body-text-present",
)
```

The runner skips this scorer on every other `step_id`. Reports show `status="skipped"` with reasoning `"step_id '<id>' not in applies_to_step_ids"` for those entries, so adopters can see at a glance which steps the scorer covered and which it didn't.

(For a worked example using a real adapter's step IDs, see [`docs/adapter-guide.md`](adapter-guide.md#the-default_scorers-contract).)

### Why "skipped" and not just "passed"

A scorer that returns `passed=True` for steps it didn't validate creates false passing results — reports show "all green" on un-scored data. The `skipped` state lets reports carry the truth: the scorer didn't run, so the result has no signal.

This affects `EvalReport.all_passed()` (skipped scorers don't disqualify "all passed"; they're absence-of-signal, not failure) and `pipewise diff` (skipped-state transitions land in dedicated `newly_skipped` / `newly_running` buckets, distinct from regressions/improvements).

### CI behavior on `passed → skipped` transitions

By default, `pipewise diff` does NOT exit non-zero on `passed → skipped` transitions. Narrowing scope via `applies_to_step_ids` is intentional, and CI shouldn't penalize it. If you want the stricter behavior — where `passed → skipped` (or removing a previously-passing scorer entirely) should require explicit acknowledgment — pass `--strict` to `pipewise diff`.

Trade-off: `--strict` catches drift from coverage-narrowing PRs that quietly drop scorers, at the cost of refusing legitimate scope reductions until the diff is reviewed. Most adopters can leave it off.

---

## `ExactMatchScorer`

Field-level deep equality. Score is the fraction of fields that matched; `passed` is True iff every requested field matched.

```python
from pipewise.scorers import ExactMatchScorer

scorer = ExactMatchScorer(fields=["title", "confidence_score"])
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

# Absolute: catch a confidence_score field shifting by more than 10 points
abs_scorer = NumericToleranceScorer(field="confidence_score", tolerance=10)

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
    "required": ["title", "confidence_score"],
    "properties": {
        "title": {"type": "string"},
        "confidence_score": {"type": "integer", "minimum": 0, "maximum": 100},
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
    consensus_n=1,                # default — see "Consensus" below before using in CI
    cost_ceiling_usd=5.0,         # per scorer instance; reset_cost() to start fresh
)
result = scorer.score(actual_step)
print(f"${scorer.cumulative_cost_usd:.4f} spent so far")
```

**Caching:** the rubric + examples are wrapped in a `cache_control` system block, so the first call writes the cache and every subsequent call reads it at ~0.1x the input cost.

**Consensus:** the default `consensus_n=1` is for local exploration and rubric iteration — it's cheap and fast, but a single judge call is **noisy**: the same input and same prompt can produce different verdicts across runs. **For CI or any decision-making use, set `consensus_n=3`** — three independent calls vote, and the verdict passes when at least `(n // 2) + 1` agree (majority of 2/3). The 3x cost (~$0.015-0.09 per step at default model) is the price of reproducibility. Use higher odd values (5, 7) for highest-stakes gates.

**Cost ceiling:** the scorer aborts pre-call once its cumulative spend has met or exceeded `cost_ceiling_usd`. A single call may slightly overshoot. Set to `None` to disable.

## `CostBudgetScorer`

Run-level scorer. Pass when `run.total_cost_usd <= budget_usd`.

```python
from pipewise.scorers import CostBudgetScorer

scorer = CostBudgetScorer(budget_usd=0.50)
result = scorer.score(pipeline_run)
```

When `total_cost_usd` is `None` (the adapter didn't capture it), default behavior is `on_missing="fail"` — silent passing on missing data masks real problems. Override with `on_missing="skip"` for adapters that don't track cost.

> **Cost and latency data unavailable for Claude-Code-orchestrated pipelines.** Pipelines whose steps run as Claude Code agents (or any tool that doesn't expose per-call usage to user code) cannot populate `total_cost_usd` or `total_latency_ms` in v1. Pipewise's schema and budget scorers are ready when the data is — but for these pipelines today, set `on_missing="skip"` in the adapter's `default_scorers()`. This telemetry is on the roadmap once Claude Code exposes per-agent usage data; SDK-based reference integrations can demonstrate the feature path independently.

## `LatencyBudgetScorer`

Run-level scorer. Pass when `run.total_latency_ms <= budget_ms`.

```python
from pipewise.scorers import LatencyBudgetScorer

scorer = LatencyBudgetScorer(budget_ms=30_000)
result = scorer.score(pipeline_run)
```

Same `on_missing` semantics as `CostBudgetScorer` — including the cost-and-latency-data-unavailable note above for Claude-Code-orchestrated pipelines.

---

## Running scorers end-to-end

The runnable script [`examples/demo_phase2_scorers.py`](../examples/demo_phase2_scorers.py) exercises all eight scorers on a synthetic pipeline step shaped like real adapter output.

```bash
uv run python examples/demo_phase2_scorers.py
# Add --use-llm to also run LlmJudgeScorer against the real Anthropic API
# (requires ANTHROPIC_API_KEY and the [llm-judge] extra installed).
```

---

## Reading `report.json`

Each `pipewise eval` invocation writes a JSON report to `<output-root>/<timestamp>_<dataset-name>/report.json`. The report is the canonical record of what was scored — adopters wiring CI, dashboards, or downstream tooling read this file directly.

### Shape

```json
{
  "report_id": "news-analysis-runs_20260430T051313Z",
  "generated_at": "2026-04-30T05:13:13Z",
  "pipewise_version": "0.0.1",
  "dataset_name": "news-analysis-runs",
  "scorer_names": ["body-text-present", "cost-cap", "latency-cap"],
  "runs": [
    {
      "run_id": "news-sample-001",
      "pipeline_name": "news-analysis",
      "adapter_name": "news-analysis-pipewise-adapter",
      "adapter_version": "0.1.0",
      "step_scores": [
        {
          "step_id": "analyze",
          "scorer_name": "body-text-present",
          "result": {
            "status": "passed",
            "score": 1.0,
            "reasoning": null,
            "metadata": {"pattern": ".{100,}", "mode": "search"}
          }
        }
      ],
      "run_scores": [
        {
          "scorer_name": "cost-cap",
          "result": {
            "status": "skipped",
            "score": null,
            "reasoning": "total_cost_usd is None; on_missing='skip' so scorer did not evaluate",
            "metadata": {"missing": true, "budget": 1.0, "unit": "usd"}
          }
        }
      ]
    }
  ],
  "metadata": {}
}
```

### Field guide

- **`step_scores` and `run_scores`** (not `step_results` / `run_results`). Each entry is a *scoring*, not a step execution. `StepScoreEntry` carries `step_id` + `scorer_name` + the nested `result`; `RunScoreEntry` carries `scorer_name` + the nested `result`.
- **The `result` object is nested.** `status`, `score`, `reasoning`, and `metadata` all live inside `step_scores[].result.*` (or `run_scores[].result.*`). Code that wants the verdict reads `entry.result.status`; code that wants the score reads `entry.result.score` and must handle `None` for skipped entries.
- **`status` is `"passed" | "failed" | "skipped"`**. See [Skipped scorers and `applies_to_step_ids`](#skipped-scorers-and-applies_to_step_ids) for what `"skipped"` means.
- **`score` is `null` when `status` is `"skipped"`** — a skipped scorer didn't compute a score; forcing a sentinel like `0.0` would lie about the absence of signal.
- **`metadata` on a result is the scorer's own config** (regex `pattern`, budget `unit`, etc.) — useful for downstream consumers wanting to know how a scorer was parameterized, not for surfacing failure detail. Detail goes in `reasoning`.
- **`scorer_names` (top-level)** snapshots every scorer that ran across the eval. If a name is in this list but absent from a particular run's entries, the scorer crashed or was filtered out for that run.

### Reports do not carry step outputs

The report tracks *scores*, not the underlying step data. To inspect what a step actually produced, go back to the dataset JSONL row — the same source row that pipewise scored. This keeps reports compact (KB instead of MB on real-pipeline data) and means reports remain meaningful even after the source dataset moves or rotates.

```python
# Programmatic access — load report + dataset side by side.
from pipewise.core.report import EvalReport
from pipewise.runner.dataset import load_dataset
from pathlib import Path

report = EvalReport.model_validate_json(Path("reports/.../report.json").read_text(encoding="utf-8"))
runs_by_id = {r.run_id: r for r in load_dataset(Path("dataset.jsonl"))}

for run in report.runs:
    for entry in run.step_scores:
        if entry.result.status == "failed":
            run_data = runs_by_id[run.run_id]
            step = next(s for s in run_data.steps if s.step_id == entry.step_id)
            print(f"{run.run_id}/{entry.step_id}: {entry.result.reasoning}")
            print(f"  outputs: {step.outputs}")  # the actual step data
```

### Aggregation helpers

`EvalReport` provides built-in helpers so consumers don't reinvent counting:

```python
report.total_score_count()    # int — every (step_score + run_score) entry
report.passing_score_count()  # int — count where result.status == "passed"
report.failing_score_count()  # int — count where result.status == "failed"
report.skipped_score_count()  # int — count where result.status == "skipped"
report.passing_run_ids()      # list[str] — run_ids where no score failed
report.failing_run_ids()      # list[str] — run_ids where at least one score failed
report.find_run(run_id)       # RunEvalResult | None
report.find_scorer_result(run_id, scorer_name, step_id=None)  # ScoreResult | None
```

`passing_run_ids()` includes runs where every scorer was skipped (vacuously). Consumers that want to distinguish "all passed" from "all skipped" should also check `skipped_score_count()`.

These are methods (not JSON fields) so they don't bloat the file — derive them on read.

---

## Configuring scorers via TOML

`pipewise eval --scorers <path.toml>` overrides the adapter's `default_scorers()` with a TOML-defined scorer set. Use this when the canonical scorer set differs by environment — e.g., a tighter `LatencyBudgetScorer` budget on CI than on local dev, or opting into `LlmJudgeScorer` only on the baseline workflow where reproducibility matters and the API cost is acceptable.

The file format is a `[scorers.<name>]` table per scorer. The section key becomes the scorer's `name`; `class` is a dotted import path; all other keys are forwarded as constructor kwargs:

```toml
[scorers.has-status]
class = "pipewise.scorers.regex.RegexScorer"
field = "status"
pattern = "^ok$"

[scorers.cost-cap]
class = "pipewise.scorers.budget.CostBudgetScorer"
budget_usd = 0.10
on_missing = "skip"

[scorers.latency-cap]
class = "pipewise.scorers.budget.LatencyBudgetScorer"
budget_ms = 10000
on_missing = "skip"
```

Save as `scorers.toml` and invoke:

```bash
pipewise eval --adapter your_pipeline_pipewise.adapter \
              --dataset path/to/dataset.jsonl \
              --scorers scorers.toml
```

Expected output for a 3-run dataset where every step has `status: "ok"`:

```
Evaluated 3 run(s) with 1 step scorer(s) + 2 run scorer(s).
Scores: 15/15 passing (0 failing).
Report: pipewise/reports/<timestamp>_dataset/report.json
```

A few rules worth knowing:

- **Step vs. run classification is automatic.** Pipewise inspects each scorer's `score(actual=...)` annotation: `StepExecution` → step scorer, `PipelineRun` → run scorer. Custom scorers that don't have resolvable type hints fall back to Protocol-isinstance fits.
- **Missing-class errors surface at config-load time, not eval time.** A typo in `class = "..."` produces a `ScorerConfigError` *before* the eval starts, so failed runs are never partially scored.
- **Constructor kwargs are forwarded as-is.** If a scorer's `__init__` signature changes, your TOML breaks at load time with a clear `TypeError`-shaped message — no silent ignore.
- **`name` is auto-supplied from the section key.** You can override with an explicit `name = "..."` line if you want a different display name than the TOML key.
- **TOML inline tables work** for nested config (e.g., `JsonSchemaScorer`'s `schema = { type = "object", ... }`).

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
            status="passed" if is_non_empty else "failed",
            score=1.0 if is_non_empty else 0.0,
            reasoning=None if is_non_empty else "outputs dict is empty",
        )
```

To support `applies_to_step_ids` (recommended for any scorer that doesn't apply universally), expose it as an optional kwarg and store it on the instance — the runner reads `scorer.applies_to_step_ids` via `getattr`:

```python
from collections.abc import Sequence

class IsNonEmptyScorer:
    name = "outputs_non_empty"

    def __init__(self, *, applies_to_step_ids: Sequence[str] | None = None) -> None:
        self.applies_to_step_ids: Sequence[str] | None = (
            tuple(applies_to_step_ids) if applies_to_step_ids is not None else None
        )

    def score(self, actual: StepExecution, expected: StepExecution | None = None) -> ScoreResult:
        is_non_empty = bool(actual.outputs)
        return ScoreResult(
            status="passed" if is_non_empty else "failed",
            score=1.0 if is_non_empty else 0.0,
            reasoning=None if is_non_empty else "outputs dict is empty",
        )
```

The runner short-circuits to `status="skipped"` for out-of-scope steps without invoking your `score()` body, so you never need to emit `"skipped"` from this path yourself. Emit `"skipped"` from `score()` only when there's a legitimate "scorer can't evaluate" reason (e.g., budget scorers' `on_missing="skip"` path).

Pipewise's runner accepts any object satisfying the protocol — built-in or yours — without further registration.

---

## Comparing two reports with `pipewise diff`

`pipewise eval` writes a timestamped `EvalReport` per run; `pipewise diff` compares two of them and surfaces what changed. Same code path the GitHub Action uses internally — the standalone CLI is for local "did my change improve scores or regress?" checks before pushing.

```bash
pipewise diff path/to/baseline/report.json path/to/current/report.json
```

The diff categorizes every `(run_id, step_id, scorer_name)` triple into one of: regression (was passing, now failing), improvement (was failing, now passing), score delta (status unchanged but score moved), newly_skipped (was running, now skipped), newly_running (was skipped, now running), or absent-in-one (scorer added/removed across reports). The text output groups them with counts:

```
Newly failing (regressions) (3):
  run_001 / latency-cap  score 1.000 → 0.000  status passed → failed
  run_002 / latency-cap  score 1.000 → 0.000  status passed → failed
  run_003 / latency-cap  score 1.000 → 0.000  status passed → failed

Summary: 3 regressed, 0 improved, 0 score deltas
```

When nothing changed across the two reports:

```
Summary: 0 regressed, 0 improved, 0 score deltas
```

**Exit codes** make `pipewise diff` usable as a CI gate even outside the GitHub Action:

- `0` — no regressions (improvements, score-deltas, and skipped-state transitions don't affect exit status)
- `1` — at least one regression (`passed → failed`)
- `2` — usage error (file not found, malformed JSON, etc.)

**`--strict` flag.** Pass `--strict` to widen the exit-1 gate to also include `passed → skipped` transitions and `passed`-scorers that were removed entirely from the comparison report (`absent_in_b` with `status_a == "passed"`). Use this when scope-narrowing should require explicit acknowledgment instead of silently passing CI:

```bash
pipewise diff --strict baseline/report.json current/report.json
```

`failed → skipped` and `failed → absent` are still allowed under `--strict` — the scorer wasn't passing before either, so narrowing scope masks no signal.

**JSON format** is available via `--format json` for tooling that wants the structured `ReportDiff` shape:

```bash
pipewise diff --format json baseline/report.json current/report.json
```

```json
{
  "runs_a_only": [],
  "runs_b_only": [],
  "regressions": [
    {
      "run_id": "run_001",
      "step_id": null,
      "scorer_name": "latency-cap",
      "score_a": 1.0,
      "score_b": 0.0,
      "status_a": "passed",
      "status_b": "failed"
    }
  ],
  "improvements": [],
  "score_deltas": [],
  "newly_skipped": [],
  "newly_running": [],
  "absent_in_a": [],
  "absent_in_b": []
}
```

`score_a` and `score_b` are `float | null` — entries with `status_a == "skipped"` or `status_b == "skipped"` carry `null` for the corresponding score.

### What `pipewise diff` answers (and what it doesn't)

Diff is keyed on the `(run_id, step_id, scorer_name)` triple. It compares two reports score-by-score for the *same* triple — that's why deterministic re-runs of the same dataset produce `0 regressed, 0 improved, 0 score deltas`.

**Diff is for:**

- "Did re-running this dataset surface a regression?" (e.g., after editing a scorer config or upgrading the pipeline.) Same dataset, two evals.
- "Did this LLM-judge or other non-deterministic scorer's verdicts move?" (consensus stability checks.)
- "Did adding a new scorer break previously-passing runs?" (existing runs flagged as score-delta or absent.)
- The CI gate path — the GitHub Action's PR-comment renderer is built on `compute_diff()`.

**Diff is NOT for:**

- "Is my pipeline producing better outputs over time?" Two reports built from *different* datasets (different `run_id`s) have no key overlap; diff will report 0/0/0 score-deltas with all runs in the `runs_a_only` / `runs_b_only` sets. For trend-over-time analysis, compare aggregate metrics across runs (mean score per scorer, pass rate over the dataset) rather than per-triple deltas.
- Comparing different *scorer sets* across reports. Scorers absent from one report show up as `absent_in_a` / `absent_in_b`, but the diff doesn't tell you "your scorer set got bigger or smaller" — it tells you which specific triples are unique to each side.

For the automated PR-comment form of the same diff (sticky comment with verdict line + roll-up table), see [`docs/ci-integration.md`](ci-integration.md) — the `pipewise-eval` GitHub Action wraps `compute_diff()` and renders the result as Markdown.
