# Schema reference

> The canonical Python source lives in [`pipewise/core/schema.py`](../pipewise/core/schema.py),
> [`scorer.py`](../pipewise/core/scorer.py), and [`report.py`](../pipewise/core/report.py).
> If anything in this document disagrees with the source, the **source wins**
> — please open an issue.

This document is for **adapter authors** — engineers writing code that
converts their pipeline's outputs into pipewise data structures. If you're
new to the project, start with [`README.md`](../README.md), then
[`docs/adapter-guide.md`](adapter-guide.md), then this reference.

---

## 1. The mental model

Pipewise has one big idea worth understanding before you read any field
list:

> **A pipeline definition can be a DAG with branches and conditional steps.
> A single pipeline run is always a linear sequence of "what actually
> happened."**

Pipewise records *runs*, not *definitions*. Branches are captured by which
`step_id` was executed. A step that didn't fire can either be **explicitly
recorded** with `status="skipped"` (useful when the adapter wants the absence
to be visible — e.g., the LangGraph reference adapter emits a `tools__1`
skipped step when the agent answers without tool calls) or **simply omitted**
from the steps list. Iteration (a node firing multiple times) is captured by
emitting one `StepExecution` per iteration; the reference adapters use a
`<step>__N` suffix (`agent__1`, `agent__2`, …), but adopters can use any
convention as long as `step_id`s are unique within a run.

This collapses an entire class of complexity (DAG-aware schemas, conditional-
edge encoding, cycle detection) into a flat ordered list. Anything you'd
want to know about how a run actually unfolded is recoverable from the
sequence of `step_id`s and statuses.

The two worked examples in §7 and §8 below show what this looks like for two
agent-orchestration paradigms — an imperative-loop agent (Anthropic SDK) and
a declarative-graph agent (LangGraph) — exercising iteration and skipped-step
semantics respectively.

---

## 2. The four data types

| Type | Purpose | Where it's used |
|---|---|---|
| [`PipelineRun`](#pipelinerun) | One execution of a pipeline | Adapters produce these; scorers consume them |
| [`StepExecution`](#stepexecution) | One step within a run | Nested inside `PipelineRun.steps` |
| [`ScoreResult`](#scoreresult) | One scorer's verdict on a step or run | Scorers produce; reports collect |
| [`EvalReport`](#evalreport) | All scoring results from one `pipewise eval` invocation | The CLI writes these; the PR-comment bot reads them |

You'll spend most of your adapter time producing `PipelineRun` and
`StepExecution`. The other two types are the framework's job.

---

## 3. `PipelineRun`

Source: [`pipewise/core/schema.py`](../pipewise/core/schema.py).

```python
from pipewise import PipelineRun
```

### Required fields

| Field | Type | Notes |
|---|---|---|
| `run_id` | `str` (non-empty) | Globally unique. Used in default filenames; pick something filesystem-safe. |
| `pipeline_name` | `str` (non-empty) | Stable name for the pipeline (e.g., `"langgraph-react-agent"`, `"anthropic-agent-react"`). |
| `started_at` | `AwareDatetime` | Naive datetimes are rejected — see [§6.2](#62-timezone-aware-datetimes-required). |
| `status` | `RunStatus` | `"completed"` / `"partial"` / `"failed"`. No `"running"` (see [§6.4](#64-no-running-status)). |
| `adapter_name` | `str` (non-empty) | Identifies which adapter produced this run. Required for reproducibility. |
| `adapter_version` | `str` (non-empty) | Semver for the adapter. Required for the same reason. |

### Optional fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `pipeline_version` | `str \| None` | `None` | Semver of your prompts/pipeline definition, if you version them. |
| `completed_at` | `AwareDatetime \| None` | `None` | **Required when `status="completed"`** (see [§6.5](#65-terminal-status-validators)). |
| `initial_input` | `dict[str, Any]` | `{}` | The input that started the run (user message, prompt template, etc.). |
| `steps` | `list[StepExecution]` | `[]` | Steps in the order they actually executed. |
| `final_output` | `dict[str, Any] \| None` | `None` | Aggregated final output, if distinct from `steps[-1].outputs`. **Not auto-derived** (see [§6.6](#66-no-auto-derivation)). |
| `total_cost_usd` | `float \| None` | `None` | `>= 0`. Adapter-set; not auto-summed from steps. |
| `total_input_tokens` / `total_output_tokens` | `int \| None` | `None` | `>= 0`. |
| `total_latency_ms` | `int \| None` | `None` | `>= 0`. |
| `metadata` | `dict[str, Any]` | `{}` | Adapter-specific data — see [§6.1](#61-extension-via-metadata). |

---

## 4. `StepExecution`

Source: [`pipewise/core/schema.py`](../pipewise/core/schema.py).

```python
from pipewise import StepExecution
```

### Required fields

| Field | Type | Notes |
|---|---|---|
| `step_id` | `str` (non-empty) | Stable identifier — **NOT** `"step_N"`. Use a name from your pipeline's vocabulary (e.g., `"agent"`, `"tools"`, `"calculator"`). For iteration or branching variants, derive a stable suffix (e.g., `"agent__1"` for the first iteration, `"agent__2"` for the second). |
| `step_name` | `str` (non-empty) | Human-readable display name. |
| `started_at` | `AwareDatetime` | Naive datetimes rejected. |
| `status` | `StepStatus` | `"completed"` / `"skipped"` / `"failed"`. No `"running"`. |

### Optional fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `completed_at` | `AwareDatetime \| None` | `None` | **Required when `status="completed"`**. |
| `error` | `str \| None` | `None` | Free-form error message. Optional even on `"failed"` — adapters that don't have an error string leave it `None` rather than fabricating one. |
| `executor` | `str \| None` | `None` | Agent / skill / script name (e.g., `"agent"`, `"calculator"`). |
| `model` | `str \| None` | `None` | Model identifier (e.g., `"claude-opus-4-7"`). |
| `provider` | `str \| None` | `None` | Model provider (e.g., `"anthropic"`, `"google"`). |
| `inputs` / `outputs` | `dict[str, Any]` | `{}` | Opaque payloads. Pipewise doesn't interpret content; scorers do. |
| `input_tokens` / `output_tokens` | `int \| None` | `None` | `>= 0`. |
| `cost_usd` | `float \| None` | `None` | `>= 0`. |
| `latency_ms` | `int \| None` | `None` | `>= 0`. |
| `metadata` | `dict[str, Any]` | `{}` | Adapter-specific data. |

---

## 5. `ScoreResult` and the scorer protocols

Source: [`pipewise/core/scorer.py`](../pipewise/core/scorer.py).

```python
from pipewise import ScoreResult, StepScorer, RunScorer
```

### `ScoreResult`

| Field | Type | Notes |
|---|---|---|
| `score` | `float` | Canonical `[0.0, 1.0]`. `1.0` = perfect, `0.0` = total mismatch. |
| `passed` | `bool` | Threshold-based verdict. Each scorer decides what "pass" means. |
| `reasoning` | `str \| None` | Free-text. Required reading for LLM-judge scorers; optional for mechanical ones. |
| `metadata` | `dict[str, Any]` | Scorer-specific data (per-field diff, judge model/temperature, etc.). |

### Scorer protocols

Both are `@runtime_checkable` Protocols — duck-typed structurally. Any object
exposing `name: str` and a matching `score()` method satisfies the contract.

```python
class StepScorer(Protocol):
    name: str
    def score(
        self,
        actual: StepExecution,
        expected: StepExecution | None = None,
    ) -> ScoreResult: ...


class RunScorer(Protocol):
    name: str
    def score(
        self,
        actual: PipelineRun,
        expected: PipelineRun | None = None,
    ) -> ScoreResult: ...
```

A scorer MAY ignore `expected` when its scoring logic is self-contained
(e.g., a regex match on `actual.outputs`).

> Note: because both protocols share the same shape (`name` + `score(actual, expected)`),
> `isinstance(obj, StepScorer)` and `isinstance(obj, RunScorer)` will both
> return `True` for any compliant object. mypy is the source of truth for
> type compatibility; `isinstance` is a coarse "does this look like a scorer?"
> filter.

---

## 6. Schema-level conventions

These conventions apply uniformly across every model. Each has a
documented rationale below.

### 6.1 Extension via `metadata`

Every model has `model_config = ConfigDict(extra="forbid")`. Unknown
top-level fields raise `ValidationError` rather than being silently
dropped.

The encouraged extension mechanism is the `metadata: dict[str, Any]` field
on `PipelineRun`, `StepExecution`, `ScoreResult`, and `EvalReport`.
Adapter-specific data goes there.

```python
StepExecution(
    step_id="agent__1",
    step_name="Agent",
    started_at=now,
    completed_at=now,
    status="completed",
    metadata={"my_adapter_field": "some_value"},   # ✅ goes in metadata
)

StepExecution(
    step_id="agent__1",
    ...,
    my_adapter_field="some_value",   # ❌ ValidationError
)
```

> Why: a v1 schema gets one chance to teach adapter authors the convention.
> Loud errors do that; silent drops don't.

### 6.2 Timezone-aware datetimes required

Every datetime field uses Pydantic's `AwareDatetime`. Naive datetimes raise
`ValidationError`. UTC is recommended but any offset is accepted.

```python
from datetime import datetime, UTC

started_at = datetime.now(UTC)   # ✅
started_at = datetime.now()      # ❌ ValidationError (naive)
```

> Why: pipewise data is portable across machines/CI runners and comparable
> for regression detection; mixed-tz vs. naive datetimes are a known
> footgun for sorting and subtraction.

### 6.3 Non-negative numerics

Cost, token counts, and latency all have `Field(ge=0)`. Negative values
raise `ValidationError`.

> Why: not policy — sanity. Negative tokens, negative dollars, negative
> milliseconds are physically impossible.

### 6.4 No `"running"` status

`StepStatus` and `RunStatus` only contain terminal states. There is no
`"running"`. Pipewise EVALUATES completed runs; an in-flight step has no
meaningful semantics in v1.

If your source pipeline crashed mid-execution and the step's end time is
unknown, use `status="failed"` with `completed_at=None` (not "running").

> Why: aligns with pipewise's evaluate-not-execute scope. Re-add condition
> reconsidered when execution mode lands.

### 6.5 Terminal-status validators

A step or run with `status="completed"` MUST have `completed_at` set.
The schema raises `ValidationError` otherwise.

`status="skipped"` and `status="failed"` allow `completed_at=None` —
forcing fabrication for failed pipelines that crashed before recording
end time would be worse than honest absence.

> Why: a `"completed"` step without an end time is self-contradictory data;
> every consumer would have to guard against it. The other terminal states
> have legitimate end-time-unknown cases.

### 6.6 No auto-derivation

Pipewise does NOT auto-derive:

- `final_output` from `steps[-1].outputs`
- `total_cost_usd`, `total_input_tokens`, etc. from sums over step values

Adapters set these explicitly. This lets adapters record values from
authoritative sources (e.g., a billing-API total) rather than re-summing
from imperfect step data.

> Why: explicit > implicit, and "I summed N step costs" lies about the
> precision of cost data that adapters often only have at run-level granularity.
>

### 6.7 Clock skew tolerated

Pipewise does NOT enforce `started_at <= completed_at`. Clock skew across
distributed systems / CI runners makes strict ordering a frequent
false-positive. Adapters that want strict ordering can validate at their own
layer.

> Why: pragmatic — the pain of false positives outweighs the value of
> catching the rare backwards timestamp.

### 6.8 Mutability and immutability

Models are mutable in-memory. Pipewise does NOT use `frozen=True`.

Persistent immutability is enforced at the *filesystem layer*: the runner
writes timestamped files that are never overwritten. Once
a run has been written to disk, it stays exactly as written. This is the
immutability that matters for regression detection and audit.

> Why: scorers transform / aggregate models in-memory. `frozen=True` would
> add ceremony with no real failure mode it prevents.

---

## 7. Worked example 1 — imperative-loop agent (Anthropic SDK)

A two-iteration ReAct agent loop running on Claude Haiku 4.5. The first
iteration asks for two tool calls in parallel; the tools execute; the second
iteration synthesizes the final answer. The Python below is condensed from a
real captured run; the full JSON lives at
[`examples/anthropic-quickstarts/runs/golden-001-iteration.json`](../examples/anthropic-quickstarts/runs/golden-001-iteration.json).

```python
from datetime import datetime, timedelta, UTC
from pipewise import PipelineRun, StepExecution

base = datetime(2026, 5, 1, 11, 56, 31, tzinfo=UTC)

run = PipelineRun(
    run_id="golden-001-iteration",
    pipeline_name="anthropic-agent-react",
    pipeline_version="0.1.0",
    started_at=base,
    completed_at=base + timedelta(seconds=2),
    status="completed",
    initial_input={
        "user_input": "What is 47 * 23 + 100? Then tell me the capital of France.",
    },
    steps=[
        StepExecution(
            step_id="agent__1",                # ← iteration 1 of the agent loop
            step_name="Agent (iteration 1)",
            started_at=base + timedelta(seconds=1),
            completed_at=base + timedelta(seconds=1),
            status="completed",
            executor="agent",
            model="claude-haiku-4-5-20251001",
            provider="anthropic",
            outputs={
                "stop_reason": "tool_use",
                "content": [
                    {"type": "tool_use", "name": "calculator",
                     "input": {"expression": "47 * 23 + 100"}},
                    {"type": "tool_use", "name": "lookup_country",
                     "input": {"name": "France"}},
                ],
            },
            input_tokens=729, output_tokens=96, cost_usd=0.001209,
        ),
        StepExecution(
            step_id="calculator__1",           # ← per-tool step_ids
            step_name="Calculator (iteration 1)",
            started_at=base + timedelta(seconds=1),
            completed_at=base + timedelta(seconds=1),
            status="completed",
            executor="calculator",
            outputs={"output": "1181"},
        ),
        StepExecution(
            step_id="lookup_country__1",
            step_name="Lookup Country (iteration 1)",
            started_at=base + timedelta(seconds=1),
            completed_at=base + timedelta(seconds=1),
            status="completed",
            executor="lookup_country",
            outputs={"output": {"capital": "Paris", "population": 67750000}},
        ),
        StepExecution(
            step_id="agent__2",                # ← iteration 2: synthesizes final answer
            step_name="Agent (iteration 2)",
            started_at=base + timedelta(seconds=2),
            completed_at=base + timedelta(seconds=2),
            status="completed",
            executor="agent",
            model="claude-haiku-4-5-20251001",
            provider="anthropic",
            outputs={
                "stop_reason": "end_turn",
                "content": [{"type": "text",
                             "text": "**47 * 23 + 100 = 1,181** ..."}],
            },
            input_tokens=903, output_tokens=44, cost_usd=0.001123,
        ),
    ],
    final_output={"text": "**47 * 23 + 100 = 1,181** ..."},
    total_cost_usd=0.002332,
    total_input_tokens=1632,
    total_output_tokens=140,
    total_latency_ms=1916,
    adapter_name="pipewise-anthropic-quickstarts",
    adapter_version="0.1.0",
)
```

Two things this example teaches:

- **`agent__1` and `agent__2` have structurally different `outputs`.** The
  first stops on `tool_use` and emits `tool_use` content blocks; the second
  stops on `end_turn` and emits a single `text` block. The opaque
  `outputs: dict[str, Any]` field absorbs this difference without forcing a
  per-step schema.
- **Iteration is in the `step_id`, not the schema.** `agent__1`, `agent__2`
  and `calculator__1` are conventional adapter-side identifiers. Pipewise
  itself only requires uniqueness within a run.

The full working capture-and-adapter pair lives at
[`examples/anthropic-quickstarts/`](../examples/anthropic-quickstarts/).

---

## 8. Worked example 2 — declarative-graph agent with skipped path (LangGraph)

A LangGraph `create_react_agent` graph — same agent shape as §7 but with a
different orchestration paradigm (declarative graph rather than imperative
loop). This run shows the user greeting the agent without giving it tool
work, so the `tools` node never fires. The adapter records that absence
explicitly as `status="skipped"`. Condensed from
[`examples/langgraph/runs/golden-002-skipped.json`](../examples/langgraph/runs/golden-002-skipped.json).

```python
from datetime import datetime, timedelta, UTC
from pipewise import PipelineRun, StepExecution

base = datetime(2026, 5, 1, 11, 26, 28, tzinfo=UTC)

run = PipelineRun(
    run_id="golden-002-skipped",
    pipeline_name="langgraph-react-agent",
    pipeline_version="0.1.0",
    started_at=base,
    completed_at=base + timedelta(seconds=5),
    status="completed",
    initial_input={
        "messages": [
            {"role": "user", "content": "Hello! What can you help with?"},
        ],
    },
    steps=[
        StepExecution(
            step_id="agent__1",
            step_name="Agent (iteration 1)",
            started_at=base + timedelta(seconds=4),
            completed_at=base + timedelta(seconds=4),
            status="completed",
            executor="agent",
            model="gemini-3.1-pro-preview",
            provider="google",
            outputs={
                "messages": [{
                    "type": "ai",
                    "content": [{
                        "type": "text",
                        "text": "Hello! I can help you with...",
                    }],
                }],
            },
            input_tokens=186, output_tokens=336,
        ),
        StepExecution(
            step_id="tools__1",
            step_name="Tools (iteration 1)",
            started_at=base + timedelta(seconds=4),
            status="skipped",                  # ← node existed in the graph; never fired
            completed_at=None,                  # ← legitimately absent for "skipped"; see §6.5
            executor="tools",
            inputs={},
            outputs={},
        ),
    ],
    total_input_tokens=186,
    total_output_tokens=336,
    total_latency_ms=4518,
    adapter_name="pipewise-langgraph",
    adapter_version="0.1.0",
)
```

The `tools__1` step is recorded **explicitly** with `status="skipped"`
rather than omitted from the list. This is an adapter-level choice: the
LangGraph reference adapter records nodes that the compiled graph topology
*could* have fired but didn't, so a downstream scorer can spot a run that
*should* have invoked tools but didn't. An adapter that prefers the
omitted-on-skip convention can simply leave the entry out — pipewise
tolerates either pattern.

For the iterated counterpart of this run — same graph, an input that
exercises both tools and produces `agent__1` → `tools__1` → `tools__2` →
`agent__2` — see
[`runs/golden-001-iteration.json`](../examples/langgraph/runs/golden-001-iteration.json).
The full working capture-and-adapter pair lives at
[`examples/langgraph/`](../examples/langgraph/).

---

## 9. `EvalReport` (advanced — adapter authors usually skip this)

Source: [`pipewise/core/report.py`](../pipewise/core/report.py).

You only need `EvalReport` if you're building tooling that consumes
pipewise eval output (a custom CI integration, an alternative report
viewer, etc.). The standard CLI handles report I/O for you.

The hierarchy:

```
EvalReport
├── runs: list[RunEvalResult]
│   ├── run_id, pipeline_name, adapter_name, adapter_version
│   ├── step_scores: list[StepScoreEntry] (step_id + scorer_name + ScoreResult)
│   └── run_scores:  list[RunScoreEntry]  (scorer_name + ScoreResult)
└── (provenance) report_id, generated_at, pipewise_version, dataset_name, scorer_names
```

Useful methods:

```python
report.total_score_count()
report.passing_score_count()
report.failing_score_count()
report.passing_run_ids()
report.failing_run_ids()
report.find_run(run_id)
report.find_scorer_result(run_id, scorer_name, step_id=None)
```

These are methods, not `@computed_field` — they're not in the JSON. The
JSON shape is intentionally minimal so it's stable across pipewise releases.

---

## 10. Where to go next

- [`docs/adapter-guide.md`](adapter-guide.md) — how to build an adapter for *your* pipeline
- [`examples/anthropic-quickstarts/`](../examples/anthropic-quickstarts/) — full working imperative-loop reference adapter (Anthropic SDK)
- [`examples/langgraph/`](../examples/langgraph/) — full working declarative-graph reference adapter (LangGraph)

