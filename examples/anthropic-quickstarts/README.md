# pipewise-anthropic-quickstarts

Reference adapter that captures runs from a minimal Anthropic-SDK agent loop into pipewise's `PipelineRun` schema. Demonstrates pipewise's schema coverage of imperative-loop agent orchestration (Anthropic SDK), paralleling the [LangGraph adapter](../langgraph/) which covers declarative-graph orchestration.

> **Status:** Phase 5.5.4 work (Issue [#79](https://github.com/isthatamullet/pipewise/issues/79)).

## Quickstart

```bash
cd examples/anthropic-quickstarts
uv sync
uv run pytest                                          # run the adapter test suite
ANTHROPIC_API_KEY=... uv run python capture_runs.py    # regenerate sample dataset
```

Then from anywhere in the repo:

```bash
uv run pipewise inspect examples/anthropic-quickstarts/runs/golden-001-iteration.json
uv run pipewise eval --dataset examples/anthropic-quickstarts/runs/dataset.jsonl \
                     --adapter pipewise_anthropic_quickstarts.adapter
```

## Relationship to upstream `agents` Quickstart

The reference here is the [`agents`](https://github.com/anthropics/anthropic-quickstarts/tree/main/agents) Quickstart from `anthropics/anthropic-quickstarts` — Anthropic's "minimal educational implementation" of an agent loop.

That upstream is **not** packaged for `pip install` (its README explicitly states "This is NOT an SDK"; adopters are expected to translate the patterns into their own code). Following that guidance, our adapter ships a small `MinimalAgent` (~80 LOC in `agent.py`) that mirrors the upstream's loop shape — single LLM call per turn, tool execution, iterate to terminal stop reason. Adopters with their own production agent code apply the same `StepCapture` primitive directly to their `client.messages.create(...)` calls.

## What the adapter captures

The example agent has access to two deterministic tools (intentionally identical to the LangGraph adapter's tools, so the two reference adapters can be compared side by side):

- `calculator(expression)` — safe arithmetic eval (no network)
- `lookup_country(name)` — ~10-country hardcoded dataset

Two sample runs are committed under `runs/`:

| Run | User input | What it demonstrates |
|---|---|---|
| `golden-001-iteration.json` | "What is 47 * 23 + 100? Then tell me the capital of France." | Multi-turn agent loop. Captures `agent__1`, `calculator__1`, `lookup_country__1`, `agent__2` (or similar — Claude may interleave differently). |
| `golden-002-skipped.json` | "Hello! What can you help with?" | Agent answers directly without using tools. Single `agent__1` step, no tool steps. |

Together they cover iteration (`<step>__N` step_ids), per-tool granularity, and per-step token + cost attribution from `Message.usage`.

## Iteration-naming convention

Identical to the LangGraph adapter: every step invocation gets a `__N` suffix, indexed from 1. Each LLM call is `agent__N`; each tool execution is `<tool_name>__N`. The convention is shared deliberately so adopters reading both adapters see one consistent rule.

## File layout

```
examples/anthropic-quickstarts/
├── pyproject.toml                                  # independent package; pins anthropic SDK
├── pipewise_anthropic_quickstarts/
│   ├── adapter.py                                  # eval-time: load_run + default_scorers
│   ├── capture.py                                  # run-time: capture_run + write_run
│   ├── agent.py                                    # MinimalAgent loop (modeled on upstream)
│   ├── tools.py                                    # calculator + lookup_country
│   └── pricing.py                                  # per-model price table for cost calc
├── tests/                                          # unit tests; no LLM calls
├── runs/                                           # captured PipelineRun JSON + dataset.jsonl
└── capture_runs.py                                 # regenerate sample dataset (calls Anthropic API)
```

The boundary between `capture.py` and `adapter.py` enforces pipewise's
determinism rule: capture is run-time and may call LLMs; adapter reads only
from disk. Same JSON in, same scores out.

## Default scorers

`adapter.default_scorers()` returns a small step + run suite:

- **`anthropic_agent_response_shape`** (step) — `JsonSchemaScorer` validating that each agent step's outputs include a `content` array and `stop_reason`. Scoped to `agent__1..4`; tool steps are out-of-scope and auto-skipped by the runner.
- **`run_latency_60s`** (run) — `LatencyBudgetScorer` with a 60 s cap. Generous for multi-iteration loops on Sonnet/Opus.
- **`run_cost_10c`** (run) — `CostBudgetScorer` with a $0.10 USD cap. `on_missing="skip"` so models outside `pricing.py`'s table don't fail the score.

To extend: import additional pipewise scorers and append them to the lists returned by `default_scorers()`. Common additions:

- `RegexScorer` against the captured `final_output.text` for response-format checks
- `EmbeddingSimilarityScorer` against a golden answer for response-quality drift detection
- `ExactMatchScorer` on tool-call inputs for behavior regression tests

## Swapping the model

Edit `MODEL_NAME` in `capture_runs.py` to switch between Haiku, Sonnet, or Opus. The default is Haiku for low-cost regeneration. Update `pricing.py` if you use a model not in the small built-in table.

The adapter pattern itself is provider-agnostic — `capture.py`'s `MinimalAgent` calls `client.messages.create()` directly, so any Anthropic-compatible client works.

## Known limitations (v0.1)

- **Async agent loops** are not exercised. The upstream `agents` Quickstart has both `run` and `run_async`; we only model the synchronous path. Async would just need `await` plumbing.
- **MCP tool servers** are not wired up. Upstream supports them; the reference here uses native Python tool functions only.
- **Per-step latency is not measured.** The capture event sink fires after each LLM/tool call has completed. Run-level latency is the honest signal.
- **Cost estimates require a model in `pricing.py`.** Unknown models report `cost_usd=None`; the `CostBudgetScorer` is configured with `on_missing="skip"` so this doesn't fail evals.

## License

Apache-2.0, matching pipewise core.
