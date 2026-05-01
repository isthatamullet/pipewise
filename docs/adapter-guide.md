# Writing a pipewise adapter

This guide walks through building a pipewise adapter using the two reference integrations as worked examples — a declarative-graph agent ([LangGraph](https://langchain-ai.github.io/langgraph/) `create_react_agent`) and an imperative-loop agent ([Anthropic Quickstarts `agents`](https://github.com/anthropics/anthropic-quickstarts/tree/main/agents) shape). Both adapters live in-tree under `examples/<framework>/`, are a few hundred lines of Python with full unit-test coverage, and are designed to be cloned and adapted to your own pipeline in an afternoon.

## What an adapter does

An adapter is a small Python package that lives **inside the pipeline you want to evaluate** and converts that pipeline's outputs into a `pipewise.PipelineRun`. Pipewise core never imports your pipeline — your adapter imports pipewise.

In one sentence: **your pipeline produces raw outputs, your adapter translates those into canonical `PipelineRun`s, pipewise scores them.** Translation happens in your code, before pipewise ever sees the data.

```
your-pipeline-repo/
└── integrations/
    └── pipewise/
        ├── pyproject.toml             # declares pipewise as a dependency
        ├── README.md
        ├── your_pipeline_pipewise/    # your package
        │   ├── __init__.py
        │   └── adapter.py             # exports load_run + default_scorers
        └── tests/
            └── test_adapter.py
```

## Smoke-test adapter in 5 minutes

Before you wire an adapter into your real pipeline, it's worth confirming pipewise installs and runs end-to-end on your machine. This section walks through a self-contained smoke test — two short files in `/tmp/`, three synthetic runs, one clean pass.

```python
# /tmp/smoke/adapter.py
"""Smoke-test adapter — a 3-step toy pipeline. Real adapters are larger
and live in their pipeline's repo (see "Why the adapter lives in your
repo" below); this one is intentionally tiny."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipewise import PipelineRun, RunScorer, StepExecution, StepScorer
from pipewise.scorers.budget import LatencyBudgetScorer
from pipewise.scorers.regex import RegexScorer


def load_run(path: Path) -> PipelineRun:
    """Translate one raw run file into a canonical PipelineRun."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    base = datetime.now(UTC)

    def step(idx: int, step_id: str, name: str) -> StepExecution:
        return StepExecution(
            step_id=step_id,
            step_name=name,
            started_at=base + timedelta(seconds=idx),
            completed_at=base + timedelta(seconds=idx + 1),
            status="completed",
            latency_ms=1000,
            outputs={"status": "ok", "topic": raw["topic"]},
        )

    return PipelineRun(
        run_id=raw["run_id"],
        pipeline_name="smoke-test",
        started_at=base,
        completed_at=base + timedelta(seconds=3),
        status="completed",
        total_latency_ms=3000,
        steps=[
            step(0, "load_article", "Load Article"),
            step(1, "summarize", "Summarize"),
            step(2, "check_hallucinations", "Check Hallucinations"),
        ],
        adapter_name="smoke-test-adapter",
        adapter_version="0.1.0",
    )


def default_scorers() -> tuple[list[StepScorer], list[RunScorer]]:
    """One step scorer + one run scorer — both pass cleanly on the data above."""
    return (
        [RegexScorer(field="status", pattern=r"^ok$", name="status-ok")],
        [LatencyBudgetScorer(budget_ms=10_000, name="latency-cap")],
    )
```

```python
# /tmp/smoke/build_dataset.py
"""Materialize synthetic PipelineRuns into a JSONL dataset for `pipewise eval`."""
import json
from pathlib import Path

from adapter import load_run

# Synthetic raw run inputs (would normally be your pipeline's actual outputs).
runs_dir = Path("runs/")
runs_dir.mkdir(exist_ok=True)
for fx in [
    {"run_id": "run_001", "topic": "weather-forecast"},
    {"run_id": "run_002", "topic": "earnings-report"},
    {"run_id": "run_003", "topic": "product-launch"},
]:
    (runs_dir / f"{fx['run_id']}.json").write_text(json.dumps(fx), encoding="utf-8")

# Call adapter.load_run on each raw file, write JSONL — one PipelineRun per line.
with Path("dataset.jsonl").open("w", encoding="utf-8") as out:
    for raw_path in sorted(runs_dir.glob("*.json")):
        out.write(load_run(raw_path).model_dump_json() + "\n")
```

Then run it:

```bash
mkdir -p /tmp/smoke && cd /tmp/smoke
# (paste the two files above into adapter.py and build_dataset.py)
python build_dataset.py
PYTHONPATH=. pipewise eval --adapter adapter --dataset dataset.jsonl
```

`PYTHONPATH=.` is required so pipewise can `import adapter` from the current directory; in a real adapter installed via `pip install -e .` (see the package layout below), this isn't needed. Expected output:

```
Evaluated 3 run(s) with 1 step scorer(s) + 1 run scorer(s).
Scores: 12/12 passing (0 failing).
Report: pipewise/reports/<timestamp>_dataset/report.json
```

Bonus — inspect a single run to see pipewise's pretty-printer output:

```bash
head -n 1 dataset.jsonl > one-run.json
pipewise inspect one-run.json
```

```
Run:      run_001
Pipeline: smoke-test
Adapter:  smoke-test-adapter@0.1.0
Status:   completed  Started: ...  Duration: 3.00s

Steps (3):
  1. load_article [completed] latency=1000ms  (1.00s)
     inputs:  {}
     outputs: {'status': 'ok', 'topic': 'weather-forecast'}
  ...
```

If both commands succeed, pipewise is installed correctly and the adapter contract is intact. Now you're ready to write a real adapter for your pipeline — read on.

## Why the adapter lives in your repo, not in pipewise

This is the architectural commitment that makes pipewise's "general framework" claim verifiable. Your pipeline depends on pipewise (via `pip install pipewise`); pipewise has zero knowledge of your pipeline. A reviewer cloning the pipewise repo sees no traces of any specific pipeline in the core code.

It also keeps the dependency graph clean: pipewise stays small (no optional pipeline-specific extras to maintain), and your pipeline can iterate on its adapter without coordinating releases with pipewise.

The two reference adapters under `examples/<framework>/` are the one carve-out: when the upstream pipeline isn't controlled by the adopter (as with the LangGraph and Anthropic Quickstarts reference adapters), the adapter ships as an in-tree subpackage with its own `pyproject.toml` and dep stack. Pipewise core still doesn't import them; the carve-out gives reference adapters a home for a category of pipeline that wouldn't otherwise have one.

## The contract

An adapter package exposes two functions at module level:

```python
from pathlib import Path
from pipewise import PipelineRun, StepExecution, RunScorer, StepScorer

def load_run(path: Path) -> PipelineRun:
    """Translate one completed pipeline run on disk into a canonical PipelineRun.

    Called by *your* pipeline runner (or a small materialization script you
    write) — not by pipewise. The output of this function gets serialized
    to one row of a JSONL dataset that `pipewise eval` later consumes.
    See "Where PipelineRun JSONL files come from" below."""

def default_scorers() -> tuple[list[StepScorer], list[RunScorer]]:
    """Return the canonical scorer set for this pipeline. Used by
    `pipewise eval --adapter <module>` when no `--scorers <toml>` is
    supplied. Optional — if your adapter omits `default_scorers`, every
    `pipewise eval` invocation must pass `--scorers <toml>` explicitly."""
```

`load_run` is required; `default_scorers` is optional. Pipewise's `--adapter` flag accepts a dotted module path (e.g., `--adapter pipewise_langgraph.adapter`) and resolves `default_scorers` via `importlib.import_module` at eval time. **Pipewise never calls `load_run` itself** — `load_run` is a helper your own code uses to build the JSONL dataset that pipewise consumes.

## Capture vs adapter: the run-time / eval-time split

Both reference adapters split their code into two halves:

- **`capture.py` — run-time.** Wraps your pipeline's invocation, observes each step as it executes, and emits a complete `PipelineRun` JSON to disk. May call LLMs, hit network, depend on the framework SDK, etc.
- **`adapter.py` — eval-time.** Exposes `load_run` + `default_scorers`. `load_run` is a one-liner: `PipelineRun.model_validate_json(Path(path).read_text(encoding="utf-8"))`. No LLM calls, no network, no framework dependency at eval time.

This split is the simplest way to honor pipewise's determinism rule — same JSON in, same scores out — without making adapter authors think about it. The capture half can be as messy as the underlying framework requires; eval-time stays a deterministic file read.

If your pipeline already writes a native on-disk format you can't change (typical for pre-existing or third-party pipelines), the alternative is to put the translation logic *inside* `load_run` itself, mapping per-step files into a `PipelineRun` at materialization time. This works but blurs the determinism boundary — keep the translation pure (no network, no LLM calls) so re-running materialization on the same inputs produces the same JSON.

The recommended pattern for new adapters is the capture/adapter split. Both reference adapters demonstrate it in detail (`examples/langgraph/pipewise_langgraph/{capture,adapter}.py` and `examples/anthropic-quickstarts/pipewise_anthropic_quickstarts/{capture,adapter}.py`).

## Where PipelineRun JSONL files come from

`pipewise eval --dataset <path.jsonl>` consumes a JSONL file where **each line is a complete serialized `PipelineRun`** (not a path or pointer). That JSONL is built upstream of pipewise, by your own code, in four steps:

1. **Your pipeline runs** against your dataset of *inputs* and produces some on-disk record of each completed run — either a raw native format (per-step JSON files, log dumps, etc.) or, in the recommended pattern, a complete `PipelineRun` JSON written by a capture primitive (see "Capture vs adapter: run-time / eval-time split" below; both reference adapters take this approach).
2. **Your runner code calls `adapter.load_run(raw_path)`** for each completed run, getting back a `PipelineRun` object.
3. **Your runner serializes each `PipelineRun` to one line of JSONL** via `run.model_dump_json()` and writes the lines to your golden dataset file.
4. **`pipewise eval --dataset golden.jsonl --adapter <module>`** reads the JSONL, validates each row as a `PipelineRun`, and runs your default scorers (or the ones in `--scorers <toml>` if supplied).

A minimal materialization script — call it `build_dataset.py` and check it into your pipeline repo:

```python
# build_dataset.py — runs once after your pipeline finishes, before pipewise eval
from pathlib import Path
from your_pipeline_pipewise.adapter import load_run

raw_run_paths = sorted(Path("path/to/outputs/").glob("*.json"))  # Adjust to your pipeline's output shape
with Path("golden.jsonl").open("w", encoding="utf-8") as out:
    for path in raw_run_paths:
        run = load_run(path)
        out.write(run.model_dump_json() + "\n")
```

Then:

```bash
pipewise eval --dataset golden.jsonl --adapter your_pipeline_pipewise.adapter
```

This separation has three useful properties:

- **Pipewise never imports or executes your pipeline code at eval time.** It only imports your adapter module to look up `default_scorers`. CI environments running `pipewise eval` don't need your pipeline's runtime dependencies.
- **`golden.jsonl` is a stable, self-contained artifact.** You can commit it to git, hand it to another tool, or eval it with a future version of pipewise without re-running your pipeline.
- **`load_run` failures are debuggable in your own code, not buried in pipewise output.** If your adapter raises, it raises in your runner script, with your stack trace — not inside `pipewise eval`.

## Worked example 1 — declarative-graph agent (LangGraph)

The LangGraph reference adapter targets `create_react_agent` — a node-and-edge graph where the runtime alternates between an `agent` node (LLM call) and a `tools` node (parallel tool execution) until the agent stops emitting tool calls. Iteration is part of the schema: a single user input commonly produces `agent__1` → `tools__1` → `agent__2`, and a graph topology node that the run never visits is recorded as `status="skipped"`.

Lives at [`examples/langgraph/pipewise_langgraph/`](../examples/langgraph/pipewise_langgraph/). Capture handles the run-time mess (graph streaming, message normalization, topology walk for skipped nodes); the eval-time adapter is short enough to read top-to-bottom in one sitting. Below, both halves abridged to focus on the structurally interesting code.

### Capture half

```python
# pipewise_langgraph/capture.py — abridged
from collections import defaultdict
from datetime import UTC, datetime
import time

from pipewise.core.schema import PipelineRun, StepExecution


def capture_run(graph, initial_input, *, run_id, pipeline_name,
                pipeline_version="0.1.0", adapter_version="0.1.0",
                model=None, provider=None) -> PipelineRun:
    started_at = datetime.now(UTC)
    t_run_start = time.perf_counter()

    iteration_counter: dict[str, int] = defaultdict(int)
    seen_nodes: set[str] = set()
    steps: list[StepExecution] = []

    # Each chunk carries one node's state diff. Node names repeat for iterated
    # nodes; we suffix with __N (always, even single-fire) so step_ids stay
    # mechanically uniform and match adopter expectations.
    for chunk in graph.stream(initial_input, stream_mode="updates"):
        for node_name, state_update in chunk.items():
            iteration_counter[node_name] += 1
            n = iteration_counter[node_name]
            seen_nodes.add(node_name)

            new_messages = (state_update or {}).get("messages") or []
            input_tokens, output_tokens = _extract_usage(new_messages)

            captured_at = datetime.now(UTC)
            steps.append(StepExecution(
                step_id=f"{node_name}__{n}",
                step_name=f"{node_name.replace('_', ' ').title()} (iteration {n})",
                executor=node_name, model=model, provider=provider,
                inputs={}, outputs=_serialize(state_update),
                started_at=captured_at, completed_at=captured_at,
                status="completed",
                input_tokens=input_tokens or None,
                output_tokens=output_tokens or None,
                latency_ms=None,  # stream_mode="updates" fires after node finishes
            ))

    # Record skipped nodes — every topology node we never saw in the stream.
    for node_name in _topology_nodes(graph):
        if node_name not in seen_nodes:
            steps.append(StepExecution(
                step_id=f"{node_name}__1",
                step_name=f"{node_name.replace('_', ' ').title()} (iteration 1)",
                executor=node_name, model=model, provider=provider,
                inputs={}, outputs={},
                started_at=datetime.now(UTC), completed_at=None,
                status="skipped",
            ))

    total_latency_ms = int((time.perf_counter() - t_run_start) * 1000)
    return PipelineRun(
        run_id=run_id, pipeline_name=pipeline_name,
        adapter_name="pipewise-langgraph", adapter_version="0.1.0",
        started_at=started_at, completed_at=datetime.now(UTC),
        status="completed",
        initial_input=_serialize(initial_input),
        steps=steps,
        total_input_tokens=sum(s.input_tokens or 0 for s in steps) or None,
        total_output_tokens=sum(s.output_tokens or 0 for s in steps) or None,
        total_latency_ms=total_latency_ms,
    )
```

### Eval-time adapter

```python
# pipewise_langgraph/adapter.py — full
from pathlib import Path

from pipewise.core.schema import PipelineRun
from pipewise.scorers.budget import LatencyBudgetScorer
from pipewise.scorers.json_schema import JsonSchemaScorer


def load_run(path: str | Path) -> PipelineRun:
    return PipelineRun.model_validate_json(Path(path).read_text(encoding="utf-8"))


_LANGGRAPH_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["type", "content"],
        }},
    },
}


def default_scorers():
    return (
        [JsonSchemaScorer(schema=_LANGGRAPH_OUTPUT_SCHEMA, name="langgraph_messages_shape")],
        [LatencyBudgetScorer(budget_ms=30_000, name="run_latency_30s")],
    )
```

Things worth noting:

- **`load_run` is one line.** Run-time mess (LLM calls, framework SDK, message normalization) lives in `capture.py`. Eval-time `adapter.py` is purely deterministic. This is the pattern the §"Capture vs adapter" section recommends; it falls out naturally when a framework already produces structured run state.
- **`<node>__N` step_ids are an adapter-side convention,** not a pipewise core concept. Always-suffixed (single-fire nodes get `__1` too) so adapter code never branches on iteration count.
- **Skipped nodes are explicit.** Walking the compiled graph's topology after streaming lets the adapter record any node that never fired with `status="skipped"`. A scorer can then spot a run that *should* have invoked tools but didn't.
- **Per-step latency is not measured.** `stream_mode="updates"` yields each chunk *after* its node has finished; the timestamp the chunk was received is the only signal available. Run-level latency is the honest cap. The adapter records `latency_ms=None` per step rather than fabricating a number.

## Worked example 2 — imperative-loop agent (Anthropic SDK)

The Anthropic Quickstarts reference adapter targets a hand-rolled agent loop in the shape of the upstream [`agents`](https://github.com/anthropics/anthropic-quickstarts/tree/main/agents) Quickstart — a `while True:` over `client.messages.create(...)` that keeps appending tool results until the model stops emitting `tool_use` blocks. The same iteration-naming convention as worked example 1 (`<step>__N`, always suffixed) covers both the agent step and each tool execution.

Lives at [`examples/anthropic-quickstarts/pipewise_anthropic_quickstarts/`](../examples/anthropic-quickstarts/pipewise_anthropic_quickstarts/). Because upstream's `agents` Quickstart [explicitly is not packaged for installation](https://github.com/anthropics/anthropic-quickstarts/tree/main/agents), the adapter ships a small bundled `MinimalAgent` that mirrors upstream's loop shape — adopters with their own production agent code skip this and apply the same capture pattern to their existing loop directly.

The structurally interesting bit is how capture observes each LLM call and tool call via an event sink the agent calls inline:

### Capture half

```python
# pipewise_anthropic_quickstarts/capture.py — abridged
from collections import defaultdict
from datetime import UTC, datetime
import time

from pipewise.core.schema import PipelineRun, StepExecution
from .agent import MinimalAgent
from .pricing import estimate_cost_usd


def capture_run(client, user_input, *, run_id, pipeline_name, system,
                tool_schemas, tool_executors,
                pipeline_version="0.1.0", adapter_version="0.1.0",
                model=None) -> PipelineRun:
    agent = MinimalAgent(client=client, system=system,
                        tool_schemas=tool_schemas, tool_executors=tool_executors,
                        **({"model": model} if model else {}))

    started_at = datetime.now(UTC)
    t_run_start = time.perf_counter()

    iteration_counter: dict[str, int] = defaultdict(int)
    steps: list[StepExecution] = []

    def sink(event_kind: str, event_data: dict) -> None:
        captured_at = datetime.now(UTC)
        if event_kind == "llm_call":
            response = event_data["response"]
            iteration_counter["agent"] += 1
            n = iteration_counter["agent"]
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
            steps.append(StepExecution(
                step_id=f"agent__{n}",
                step_name=f"Agent (iteration {n})",
                executor="agent",
                model=getattr(response, "model", None), provider="anthropic",
                inputs={"messages": event_data["messages_in"]},
                outputs=_serialize_response(response),
                started_at=captured_at, completed_at=captured_at,
                status="completed",
                input_tokens=input_tokens or None,
                output_tokens=output_tokens or None,
                cost_usd=estimate_cost_usd(
                    getattr(response, "model", "") or "",
                    input_tokens, output_tokens,
                ),
            ))
        elif event_kind == "tool_call":
            name = event_data["name"]
            iteration_counter[name] += 1
            n = iteration_counter[name]
            steps.append(StepExecution(
                step_id=f"{name}__{n}",
                step_name=f"{name.replace('_', ' ').title()} (iteration {n})",
                executor=name, provider="anthropic",
                inputs={"input": event_data.get("input"),
                        "tool_use_id": event_data.get("id")},
                outputs={"output": event_data.get("output")},
                started_at=captured_at, completed_at=captured_at,
                status="completed",
            ))

    final_text = agent.run(user_input, sink=sink)
    total_latency_ms = int((time.perf_counter() - t_run_start) * 1000)

    return PipelineRun(
        run_id=run_id, pipeline_name=pipeline_name,
        adapter_name="pipewise-anthropic-quickstarts", adapter_version="0.1.0",
        started_at=started_at, completed_at=datetime.now(UTC),
        status="completed",
        initial_input={"user_input": user_input},
        steps=steps,
        total_input_tokens=sum(s.input_tokens or 0 for s in steps) or None,
        total_output_tokens=sum(s.output_tokens or 0 for s in steps) or None,
        total_cost_usd=sum((s.cost_usd or 0.0) for s in steps) or None,
        total_latency_ms=total_latency_ms,
        final_output={"text": final_text},
    )
```

### Eval-time adapter

```python
# pipewise_anthropic_quickstarts/adapter.py — full
from pathlib import Path

from pipewise.core.schema import PipelineRun
from pipewise.scorers.budget import CostBudgetScorer, LatencyBudgetScorer
from pipewise.scorers.json_schema import JsonSchemaScorer


def load_run(path: str | Path) -> PipelineRun:
    return PipelineRun.model_validate_json(Path(path).read_text(encoding="utf-8"))


_AGENT_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["content", "stop_reason"],
    "properties": {
        "content": {"type": "array", "items": {
            "type": "object", "required": ["type"],
        }},
        "stop_reason": {"type": ["string", "null"]},
    },
}


def default_scorers():
    return (
        [JsonSchemaScorer(
            schema=_AGENT_OUTPUT_SCHEMA,
            name="anthropic_agent_response_shape",
            applies_to_step_ids=[f"agent__{i}" for i in range(1, 9)],
        )],
        [
            LatencyBudgetScorer(budget_ms=60_000, name="run_latency_60s"),
            CostBudgetScorer(budget_usd=0.10, on_missing="skip", name="run_cost_10c"),
        ],
    )
```

Things worth noting:

- **The sink is the integration surface.** `MinimalAgent.run(...)` exposes a callback hook that fires once per LLM call and once per tool call. Capture is just two `if event_kind == ...` branches. Adopters with their own production agent code apply the same pattern: pass a sink-shaped callback into your existing agent and let it record `StepExecution`s as the loop runs.
- **Per-tool step_ids.** A run that calls `calculator` twice produces `calculator__1` and `calculator__2`. A regression where the agent stops calling `lookup_country` shows up as a missing `lookup_country__1` step rather than as a subtle output diff.
- **Cost is captured, latency is not.** `Message.usage` exposes input/output tokens directly; combined with a small per-model price table (`pricing.py`), per-step `cost_usd` round-trips meaningfully. Per-step latency is left `None` for the same reason as worked example 1 — the sink fires after each call completes, so duration isn't observable from outside.
- **`applies_to_step_ids` scopes the agent-shape scorer** to `agent__1..8` (matching the agent's `DEFAULT_MAX_ITERATIONS`). Tool steps have a different output shape and would fail the schema; the runner auto-skips them. See the §"Runner skip semantics" section below for details.

## The `default_scorers()` contract

`default_scorers()` returns the canonical scorer set used by `pipewise eval` when no `--scorers <toml>` is supplied. The two reference adapters demonstrate the same conventions with different scorer choices:

```python
# pipewise_langgraph/adapter.py — default_scorers
def default_scorers():
    return (
        [JsonSchemaScorer(schema=_LANGGRAPH_OUTPUT_SCHEMA,
                          name="langgraph_messages_shape")],
        [LatencyBudgetScorer(budget_ms=30_000, name="run_latency_30s")],
    )

# pipewise_anthropic_quickstarts/adapter.py — default_scorers
def default_scorers():
    return (
        [JsonSchemaScorer(
            schema=_AGENT_OUTPUT_SCHEMA,
            name="anthropic_agent_response_shape",
            applies_to_step_ids=[f"agent__{i}" for i in range(1, 9)],
        )],
        [
            LatencyBudgetScorer(budget_ms=60_000, name="run_latency_60s"),
            CostBudgetScorer(budget_usd=0.10, on_missing="skip", name="run_cost_10c"),
        ],
    )
```

**Convention: exclude `LlmJudgeScorer` from defaults.** It's the only built-in scorer that calls a paid API, and surprise costs hurt UX for first-time users. Power users opt in explicitly via `pipewise eval --scorers <toml>`. (See [`docs/scorers.md`](scorers.md) for the matching guidance on scorer config files.)

**Convention: pick step-level scorers that produce a meaningful pass/fail signal.** A `JsonSchemaScorer` over the canonical step-output shape catches adapter regressions that mangle or drop messages — a stronger guardrail than a tautological "the step has outputs" check. The LangGraph adapter validates that every non-skipped step's outputs conform to LangGraph's `{messages: [{type, content}, …]}` shape; the Anthropic adapter validates that each agent step has a `content` array and a `stop_reason`. Both surface real bugs (a capture that lost a tool-call message; a serializer that dropped `stop_reason`).

**Convention: use `applies_to_step_ids` to scope step scorers honestly.** A scorer that only makes sense on certain step types (e.g., the Anthropic agent-shape scorer that only applies to `agent__N` steps, not tool steps) should declare its scope via the `applies_to_step_ids` kwarg rather than letting failures pile up on out-of-scope steps:

```python
JsonSchemaScorer(
    schema=_AGENT_OUTPUT_SCHEMA,
    name="anthropic_agent_response_shape",
    applies_to_step_ids=[f"agent__{i}" for i in range(1, 9)],  # NOT calculator__N etc.
)
```

The runner emits `status="skipped"` for any step not listed, without invoking the scorer. Reports stay readable: "this scorer covered each agent iteration that actually fired" is a real eval shape, where the alternative "the schema scorer failed on every tool step" would be incorrect noise. See [`docs/scorers.md`](scorers.md) for the full skipped-state semantics.

**Convention: budget scorers use `on_missing="skip"` when the underlying datum isn't always available.** Both reference adapters capture `input_tokens` and `output_tokens` per LLM-call step from the framework's native usage signal, but `cost_usd` requires a per-model price table and falls back to `None` for unknown models. The Anthropic `CostBudgetScorer` is configured with `on_missing="skip"` so unrecognized-model runs emit `status="skipped"` (no signal) rather than fabricating a pass or fail. The same pattern applies to any pipeline whose telemetry is incomplete — set `None` honestly, configure `on_missing="skip"`, and signal lights up automatically as data becomes available.

### Runner skip semantics

Two skip behaviors the runner handles automatically:

1. **Out-of-scope steps** — if a step scorer declares `applies_to_step_ids=[...]`, the runner emits `status="skipped"` for steps whose `step_id` isn't listed.
2. **Steps with `status="skipped"`** — when an adapter marks a step skipped (e.g., a branching pipeline that didn't execute one branch), the runner auto-skips every scorer for that step.

In both cases the scorer's `score()` body is never invoked. Failed steps (`status="failed"`) DO get scored — partial outputs may carry signal worth checking.

This means adapters do not need to filter scorers or step lists themselves to express scope. Declare intent on the scorer (`applies_to_step_ids`) or on the step (`status="skipped"`); the runner does the rest.

## Cost / latency / tokens

Pipewise's schema has first-class fields for cost, latency, and token counts (`StepExecution.cost_usd`, `latency_ms`, `input_tokens`, `output_tokens`, plus run-level totals). When your pipeline captures this data, populate it — the budget scorers and any future cost-aware reporting come along for free. Both reference adapters capture per-step input/output tokens directly from the framework's native usage signal, and the Anthropic adapter computes per-step `cost_usd` via a small price table.

What's measurable from outside the pipeline depends on the framework. **Per-step latency is honest-`None`** for both reference adapters: each chunk arrives *after* its node has finished (LangGraph's `stream_mode="updates"`) or each event fires after the LLM/tool call has returned (the Anthropic agent's sink), so duration is not measurable from outside. Run-level latency is wall-clock and meaningful in both cases. **Per-step `cost_usd`** requires either a billing API or a price-table lookup; the Anthropic adapter does the latter and falls back to `None` for unknown models.

When your pipeline doesn't capture a particular signal, leave those fields as `None` and use `on_missing="skip"` on the budget scorers. Pipewise's schema is forward-compatible: turning the data on later is purely additive — no adapter contract changes, no schema migrations.

## Testing your adapter

Both reference adapters ship a `tests/test_adapter.py` organized into three classes; each new adapter should mirror the same shape.

```python
class TestLoadRun:
    def test_loads_iteration_capture(self): ...    # parses a real captured run
    def test_loads_skipped_capture(self): ...      # parses a run with skipped steps
    def test_accepts_string_path(self): ...        # adapter accepts str + Path
    def test_raises_on_missing_file(self): ...     # surfaces a clean error

class TestDefaultScorers:
    def test_returns_step_and_run_scorers(self): ...   # tuple shape, list contents
    def test_scorer_names_stable(self): ...            # names round-trip into reports

class TestEndToEndEval:
    def test_iteration_run_passes_all_step_scorers(self): ...   # run_eval round-trip
    def test_skipped_step_results_in_skipped_score(self): ...   # status passes through
```

Both adapters' suites run without LLM calls — the captured `golden-*.json` runs under each adapter's `runs/` directory are the test fixtures. Re-running `capture_runs.py` regenerates them and is the only place where actual API calls happen.

When you add an adapter to your own pipeline, point its tests at runs your pipeline has already captured. The test suites in `examples/langgraph/tests/` and `examples/anthropic-quickstarts/tests/` are good starting points to copy.

## Reference adapters

See [`examples/README.md`](../examples/README.md) for the canonical inventory, and [`docs/schema.md`](schema.md) for the field-by-field schema reference.

- **`pipewise-langgraph`** ([`examples/langgraph/`](../examples/langgraph/)) — declarative-graph agent (LangGraph `create_react_agent`). Demonstrates: iterated graph nodes, explicit-skipped semantics for unfired topology nodes, per-step token capture from `AIMessage.usage_metadata`.
- **`pipewise-anthropic-quickstarts`** ([`examples/anthropic-quickstarts/`](../examples/anthropic-quickstarts/)) — imperative-loop agent (Anthropic SDK in the shape of the upstream `agents` Quickstart). Demonstrates: per-tool step_ids, per-step cost via a small price table, sink-callback integration with an existing agent loop.
