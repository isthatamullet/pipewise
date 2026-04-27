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
`step_id` was executed; skipped steps are recorded with `status="skipped"`.
Conditional steps that didn't run are simply absent from the steps list.

This collapses an entire class of complexity (DAG-aware schemas, conditional-
edge encoding, cycle detection) into a flat ordered list. Anything you'd
want to know about how a run actually unfolded is recoverable from the
sequence of `step_id`s and statuses.

The two worked examples in §7 and §8 below show what this looks like for both a linear pipeline and a branching one.

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
| `pipeline_name` | `str` (non-empty) | Stable name for the pipeline (e.g., `"factspark"`, `"resume-tailor"`). |
| `started_at` | `AwareDatetime` | Naive datetimes are rejected — see [§6.2](#62-timezone-aware-datetimes-required). |
| `status` | `RunStatus` | `"completed"` / `"partial"` / `"failed"`. No `"running"` (see [§6.4](#64-no-running-status)). |
| `adapter_name` | `str` (non-empty) | Identifies which adapter produced this run. Required for reproducibility. |
| `adapter_version` | `str` (non-empty) | Semver for the adapter. Required for the same reason. |

### Optional fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `pipeline_version` | `str \| None` | `None` | Semver of your prompts/pipeline definition, if you version them. |
| `completed_at` | `AwareDatetime \| None` | `None` | **Required when `status="completed"`** (see [§6.5](#65-terminal-status-validators)). |
| `initial_input` | `dict[str, Any]` | `{}` | The input that started the run (article URL, job posting, etc.). |
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
| `step_id` | `str` (non-empty) | Stable identifier — **NOT** `"step_N"`. Pipelines with variants need stable IDs (e.g., `"write_resume_chronological"` vs. `"write_resume_hybrid"`). |
| `step_name` | `str` (non-empty) | Human-readable display name. |
| `started_at` | `AwareDatetime` | Naive datetimes rejected. |
| `status` | `StepStatus` | `"completed"` / `"skipped"` / `"failed"`. No `"running"`. |

### Optional fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `completed_at` | `AwareDatetime \| None` | `None` | **Required when `status="completed"`**. |
| `error` | `str \| None` | `None` | Free-form error message. Optional even on `"failed"` — adapters that don't have an error string leave it `None` rather than fabricating one. |
| `executor` | `str \| None` | `None` | Agent / skill / script name (e.g., `"stupid-meter"`). |
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
    step_id="analyze",
    step_name="Analyze",
    started_at=now,
    completed_at=now,
    status="completed",
    metadata={"my_adapter_field": "some_value"},   # ✅ goes in metadata
)

StepExecution(
    step_id="analyze",
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

> Why: explicit > implicit, and "I summed 7 step costs" lies about the
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

## 7. Worked example 1 — linear pipeline (FactSpark-shape)

A 7-step news-analysis pipeline: each step processes the article further,
all-Claude except step 7 (Gemini for verification).

```python
from datetime import datetime, timedelta, UTC
from pipewise import PipelineRun, StepExecution

base = datetime(2026, 2, 24, 8, 0, 0, tzinfo=UTC)

run = PipelineRun(
    run_id="bbc_trump_tariffs_supreme_court_20260224",
    pipeline_name="factspark",
    started_at=base,
    completed_at=base + timedelta(seconds=70),
    status="completed",
    initial_input={
        "url": "https://www.bbc.com/...",
        "title": "Trump threatens countries that 'play games'...",
    },
    steps=[
        StepExecution(
            step_id="analyze",
            step_name="Analyze Article",
            started_at=base,
            completed_at=base + timedelta(seconds=10),
            status="completed",
            executor="analyze-article",
            model="claude-opus-4-7",
            provider="anthropic",
            outputs={"article_metadata": {...}, "extracted_claims": [...]},
        ),
        StepExecution(
            step_id="enhance_entities",
            step_name="Enhance Entities",
            started_at=base + timedelta(seconds=10),
            completed_at=base + timedelta(seconds=20),
            status="completed",
            executor="enhance-entities-geographic",
            model="claude-opus-4-7",
            provider="anthropic",
            outputs={"key_entities": [...], "article_metadata": {...}},
        ),
        # ... steps 3-6 ...
        StepExecution(
            step_id="verify_claims",
            step_name="Verify Claims",
            started_at=base + timedelta(seconds=60),
            completed_at=base + timedelta(seconds=70),
            status="completed",
            executor="verify-claims",
            model="gemini-3.1-pro",        # different provider
            provider="google",
            outputs={"verification_metadata": {...}, "claim_verifications": [...]},
        ),
    ],
    adapter_name="factspark-pipewise-adapter",
    adapter_version="1.0.0",
)
```

Note that **step 7's output shape is completely different** from steps 1-6
(`verification_metadata`, `claim_verifications` vs. `article_metadata`,
`extracted_claims`). The opaque `outputs: dict[str, Any]` field handles
this without coupling.

The full prototype adapter that built this from real `step1-7.json` files
lives at
[`tests/integration/test_factspark_validation_gate.py`](../tests/integration/test_factspark_validation_gate.py).

---

## 8. Worked example 2 — branching / conditional pipeline (resume-tailor-shape)

A 7-agent pipeline with branches and gates. The same source pipeline can
produce wildly different runs depending on inputs. Pipewise captures one
specific run:

- **Step 2 was skipped** (`discovery` — not needed for this role)
- **Step 4 chronological branch ran** (not 4b hybrid). Branch captured via `step_id`
- **Step 6 outputs Markdown** (not JSON like the other steps)
- **Step 7 was gated off** by step 5's PASS/FAIL → simply absent from the list

```python
from pipewise import PipelineRun, StepExecution

run = PipelineRun(
    run_id="deepintent_senior_program_manager",
    pipeline_name="resume-tailor",
    started_at=base,
    status="partial",                       # gated step → didn't finish all stages
    initial_input={"company": "DeepIntent", "role": "Senior Program Manager"},
    steps=[
        StepExecution(
            step_id="analyze_posting",
            step_name="Analyze Posting",
            ...,
            status="completed",
            outputs={"job_metadata": {...}, "required_skills": [...]},
        ),
        StepExecution(
            step_id="discovery",
            step_name="Discovery",
            started_at=...,
            status="skipped",               # ← step explicitly skipped
            metadata={"skip_reason": "discovery not needed for this role"},
            # completed_at intentionally None — see §6.5
        ),
        StepExecution(
            step_id="research_company",
            ...,
            status="completed",
        ),
        StepExecution(
            step_id="write_resume_chronological",  # ← branch captured by step_id
            step_name="Write Resume (Chronological)",
            ...,
            status="completed",
            outputs={"formatted_resume": {...}, "character_counts": {...}},
        ),
        # NOT "write_resume_hybrid" — that's the OTHER branch and is absent here
        StepExecution(
            step_id="critique",
            ...,
            status="completed",
        ),
        StepExecution(
            step_id="format_export",
            ...,
            status="completed",
            outputs={
                "format": "markdown",       # ← mixed-format outputs are fine
                "ats_target": "ats_safe",
                "content": "# TYLER GOHR\n\n...",   # the actual markdown body
            },
        ),
        # Step 7 (export_canva) deliberately absent — gated off by step 5's status.
        # branches are recorded by which step_id ran;
        # absent steps mean they didn't run."
    ],
    adapter_name="resume-tailor-pipewise-adapter",
    adapter_version="1.0.0",
)
```

The full prototype adapter — including reading real Markdown from `_ats_safe.md`
files and confirming byte-for-byte JSON round-trip survives smart quotes
and em-dashes — lives at
[`tests/integration/test_resume_validation_gate.py`](../tests/integration/test_resume_validation_gate.py).

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
- [`tests/integration/test_factspark_validation_gate.py`](../tests/integration/test_factspark_validation_gate.py) — full working linear-pipeline adapter (~80 lines)
- [`tests/integration/test_resume_validation_gate.py`](../tests/integration/test_resume_validation_gate.py) — full working branching-pipeline adapter

