# pipewise-langgraph

Reference adapter that captures runs from a [LangGraph](https://langchain-ai.github.io/langgraph/) `create_react_agent` graph into pipewise's `PipelineRun` schema. Demonstrates pipewise's schema coverage of declarative-graph orchestration: iterated nodes, branched/skipped paths, per-step token capture.

## Quickstart

```bash
cd examples/langgraph
uv sync
uv run pytest                           # runs the adapter test suite
GOOGLE_API_KEY=... uv run python capture_runs.py   # regenerate sample dataset
```

Then from anywhere:

```bash
uv run pipewise inspect examples/langgraph/runs/golden-001-iteration.json
uv run pipewise eval --dataset examples/langgraph/runs/dataset.jsonl \
                     --adapter pipewise_langgraph.adapter
```

## What the adapter captures

The example graph is `create_react_agent` with two deterministic tools:

- `calculator(expression)` — safe arithmetic eval (no network)
- `lookup_country(name)` — small hardcoded dataset of ~10 countries

Two sample runs are committed under `runs/`:

| Run | User input | What it demonstrates |
|---|---|---|
| `golden-001-iteration.json` | "What is 47 * 23 + 100? Then tell me the capital of France." | Multi-tool ReAct loop. Captures `agent__1`, `tools__1`, `tools__2`, `agent__2`. |
| `golden-002-skipped.json` | "Hello! What can you help with?" | Agent answers directly; `tools` node never fires. Captured as `tools__1` with `status="skipped"`. |

Together they cover iteration (`<node>__N` step_ids), the skipped-step semantic, and per-step token attribution from `AIMessage.usage_metadata`.

## Iteration-naming convention

Every node invocation gets a `__N` suffix, indexed from 1 — including single-fire nodes. A node that exists in the compiled graph topology but never fires during a run gets one synthesized step with `status="skipped"` and suffix `__1`.

This convention is reused by the Anthropic Quickstarts adapter (see issue [#79](https://github.com/isthatamullet/pipewise/issues/79)). Refinements (e.g., nested-subgraph paths) should land here first.

## File layout

```
examples/langgraph/
├── pyproject.toml                  # independent package; pins langgraph 1.x
├── pipewise_langgraph/
│   ├── adapter.py                  # eval-time: load_run + default_scorers
│   ├── capture.py                  # run-time: capture_run + write_run
│   ├── tools.py                    # calculator + lookup_country
│   └── graph.py                    # build_react_agent helper
├── tests/                          # unit tests; no LLM calls
├── runs/                           # captured PipelineRun JSON + dataset.jsonl
└── capture_runs.py                 # regenerate sample dataset (calls the LLM)
```

The boundary between `capture.py` and `adapter.py` enforces pipewise's
determinism rule: capture is run-time and may call LLMs; adapter reads only
from disk and never makes network calls. Same JSON in, same scores out.

## Default scorers

`adapter.default_scorers()` returns a small suite covering both step and run
scope:

- **`langgraph_messages_shape`** (step) — `JsonSchemaScorer` validating that
  every non-skipped step's outputs conform to the LangGraph messages-update
  shape. Catches adapter regressions that drop or mangle the message stream.
- **`run_latency_30s`** (run) — `LatencyBudgetScorer` with a 30 s cap. Generous
  enough that free-tier LLM captures pass on first run; tighten as needed.

To add scorers, import them from `pipewise.scorers` and append to the lists
returned by `default_scorers()`. Common additions for ReAct pipelines:

- `RegexScorer` against a derived `text` field if you flatten message content
  during capture
- `EmbeddingSimilarityScorer` against a golden answer for response-quality
  drift detection
- `CostBudgetScorer` once you start tracking `cost_usd` per step

## Swapping LLM providers

The adapter pattern is provider-agnostic. The default `capture_runs.py` uses
Gemini via `langchain-google-genai` (free-tier-friendly). To switch:

1. Add the desired LangChain provider to `pyproject.toml`
   (`langchain-anthropic`, `langchain-openai`, etc.)
2. Edit `_build_model` in `capture_runs.py` to construct the new `ChatModel`
3. Re-run `capture_runs.py` to regenerate the sample dataset

The captured `PipelineRun` JSON does not carry provider-specific fields
beyond `model` and `provider` strings.

## Known limitations (v0.1)

- **Nested subgraphs** are not specially handled. A graph with subgraphs would
  emit chunks the capture primitive doesn't recursively walk; step_ids may
  collide. File an issue if you need this.
- **Per-step latency is not measured.** `stream_mode="updates"` yields each
  chunk *after* the corresponding node has finished, so per-node duration is
  not measurable from outside. Run-level latency (`total_latency_ms`) is
  recorded.
- **Scorer step-id targeting uses literal `in` matching.** Pipewise core does
  not yet support glob/wildcard `applies_to_step_ids` (e.g., `tools__*`); the
  default scorer suite avoids needing it. If you regenerate captures and the
  iteration count differs from the committed runs, scorer configs that
  enumerate explicit step_ids may need updating.

## License

Apache-2.0, matching pipewise core.
