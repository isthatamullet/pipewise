# pipewise

**Evaluation framework for multi-step LLM pipelines.**

> **Status:** Phase 5 shipped — the `pipewise-eval` GitHub Action posts sticky eval-report comments on PRs, validated end-to-end against a real production pipeline (FactSpark). Phase 6 (polish toward v1.0 launch) is in progress, with 380+ tests passing. Schema and CLI surfaces are not yet frozen — pin your install until v1.0. Star/watch to follow progress.

[![CI](https://github.com/isthatamullet/pipewise/actions/workflows/ci.yml/badge.svg)](https://github.com/isthatamullet/pipewise/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

---

## Quickstart

Install (no PyPI release yet — local install during pre-v1):

```bash
git clone https://github.com/isthatamullet/pipewise
cd pipewise
uv sync
```

A pipewise eval needs three things: a **dataset** of `PipelineRun`s (JSONL), an **adapter** module that knows how to load runs for your pipeline, and a **scorer config** (TOML) — or your adapter's defaults. Sketch:

```bash
# 1. Run scorers across a dataset and write a timestamped report.
uv run pipewise eval \
  --dataset path/to/golden.jsonl \
  --adapter mypipeline.integrations.pipewise.adapter \
  --scorers path/to/scorers.toml

# Output:
#   Evaluated 2 run(s) with 1 step scorer(s) + 2 run scorer(s).
#   Scores: 14/16 passing (2 failing).
#   Report: pipewise/reports/20260427T103015Z_factspark/report.json

# 2. Diff two reports — exits non-zero if there are regressions.
uv run pipewise diff \
  pipewise/reports/<earlier>/report.json \
  pipewise/reports/<later>/report.json

# 3. Pretty-print a single run for sanity-checking.
uv run pipewise inspect path/to/run.json
```

A scorer config is plain TOML — section keys become scorer names, `class` is a dotted import path, the rest are constructor kwargs:

```toml
[scorers.title-exact]
class = "pipewise.scorers.exact_match.ExactMatchScorer"
fields = ["title"]

[scorers.cost-cap]
class = "pipewise.scorers.budget.CostBudgetScorer"
budget_usd = 0.50
on_missing = "skip"

[scorers.summary-quality]
class = "pipewise.scorers.llm_judge.LlmJudgeScorer"
rubric = "Is this step's output accurate, concise, and free of hallucinated facts?"
consensus_n = 3   # majority-vote across 3 judge calls; recommended for CI
```

See [`docs/scorers.md`](docs/scorers.md) for all 8 built-in scorers and [`docs/adapter-guide.md`](docs/adapter-guide.md) for writing an adapter.

---

## What it is

pipewise is a Python library + CLI for evaluating multi-step LLM pipelines. It defines a pipeline-agnostic schema (`PipelineRun` + `StepExecution`) that any pipeline can produce via an adapter, then runs scorers across runs and reports regressions, cost drift, and quality changes per step.

Local-first. Apache 2.0. No telemetry. No vendor lock-in. Provider-neutral.

## The problem it solves

Multi-step LLM pipelines silently break in ways that are nearly invisible until customers report them:

- **Prompt edits cascade unpredictably.** Editing the prompt in step 3 of a 7-step pipeline can shift output distributions in step 5 without warning.
- **Model swaps create silent drift.** Swapping Claude Opus → Sonnet for cost reasons can change a step's behavior subtly enough that no one notices for days.
- **Cost is opaque.** Most teams know their total monthly API spend. Almost none can tell you which step in their pipeline costs 60% of the bill. Pipewise's schema captures cost per step and `CostBudgetScorer` enforces budgets — *when your pipeline can measure it*. (See [Cost capture status](#cost-capture-status) below.)
- **Existing eval tools assume single-prompt.** Promptfoo, Braintrust, LangSmith, and DeepEval were designed for testing one prompt → one output. They have to be contorted to evaluate multi-step pipelines, and the contortion loses fidelity at the step level.

Pipewise treats the **pipeline run** as the unit of evaluation, with step-level scoring, cost attribution support, and regression diffing across pipeline structure changes.

## Cost capture status

Pipewise's `PipelineRun` schema and `CostBudgetScorer` / `LatencyBudgetScorer` are ready to enforce budgets per step or per run. Whether they have data to enforce against depends on your pipeline:

- **SDK-based pipelines** (direct `anthropic.messages.create(...)` calls or equivalent): your adapter can capture `usage.input_tokens` / `usage.output_tokens`, compute cost from a per-model price table, and populate the cost/latency fields on both the steps (`step.cost_usd`, `step.latency_ms`) AND the run-level totals (`run.total_cost_usd`, `run.total_latency_ms`). The run-level totals are what `CostBudgetScorer` and `LatencyBudgetScorer` evaluate against. Budget scorers work end-to-end.
- **Claude-Code-orchestrated pipelines** (steps run as `.claude/agents/*.md` files): Claude Code does not currently expose per-agent usage telemetry to user code. Adapters for these pipelines populate cost fields with `None` and use `on_missing="skip"` on budget scorers. The schema is forward-compatible — once the data is available, no migration needed.

Cost capture for Claude-Code-orchestrated pipelines is on the roadmap once Claude Code exposes per-agent usage telemetry. (Separately, the cost-attribution path is also demonstrable in this repo as soon as a contributor opens a PR with an SDK-based pipeline integration — that's a different reference adapter, not a fix for the Claude Code path.)

## How it's positioned vs. existing tools

| Tool | Their core strength | Where pipewise differs |
|---|---|---|
| **Promptfoo** | Single-prompt CI eval, mature, large test-type library | Promptfoo treats a "test" as one prompt → one output. Pipewise treats a test as a multi-step run with step-level scoring and cost attribution. The two complement rather than compete. |
| **Braintrust** | Hosted dashboard, great UX, dataset management | Braintrust is hosted-first; pipewise is local-first / self-hosted. Pipewise's adapter pattern decouples eval from any one execution framework. |
| **LangSmith** | Tightly integrated with LangChain, great tracing UX | Pipewise works with any pipeline (not just LangChain). |
| **Langfuse** | OSS observability + evals, strong tracing | Langfuse is tracing-first with eval as a feature. Pipewise is eval-first with regression detection as the core loop. They're complementary — pipewise can consume Langfuse traces via an adapter. |
| **DeepEval** | Pytest-style assertions, RAG-specific scorers | Single-call eval. Pipewise targets multi-step pipelines explicitly and is not RAG-specific. |

## What it is *not*

- **Not a pipeline execution framework.** Use LangChain, LlamaIndex, the raw Anthropic SDK, or roll your own — pipewise evaluates pipelines you've already run.
- **Not a hosted SaaS in v1.** Local-first / self-hosted by default. No telemetry, no signup, no cloud dependency.
- **Not a chatbot eval tool.** Pipewise's value starts at step count ≥ 2.
- **Not a tracing/observability tool.** Use Langfuse, LangSmith, or Datadog LLM Observability for tracing. Pipewise consumes their output via an adapter; it doesn't replace them.
- **Not coupled to any model provider.** Anthropic for the v1 `LlmJudgeScorer` only because that's what the maintainer has access to during development; pluggable from v1.1.
- **Not a token-capture / instrumentation tool.** Pipewise consumes cost / latency / token data when your pipeline can measure it; it does not instrument your pipeline for you. SDK-based pipelines do this in the adapter; Claude-Code-orchestrated pipelines wait on upstream telemetry.

## The adapter pattern (the key architectural commitment)

```
┌──────────────────────────┐
│   pipewise core (pkg)    │
│  ─────────────────────   │
│  PipelineRun schema      │
│  Scorer protocol         │
│  Eval runner + CLI       │
│  Built-in scorers        │
└────────────┬─────────────┘
             │ imports nothing pipeline-specific
             │
   ┌─────────┴──────────────────┐
   │                            │
┌──▼─────────────────────┐  ┌───▼────────────────────┐
│  factspark_adapter.py  │  │  resume_adapter.py     │
│  ────────────────────  │  │  ──────────────────    │
│  Reads step1..7.json   │  │  Reads jobs/<co>/*     │
│  → PipelineRun         │  │  → PipelineRun         │
│  Lives IN pipeline 1   │  │  Lives IN pipeline 2   │
└────────────────────────┘  └────────────────────────┘
```

Pipewise core has zero dependencies on either reference pipeline. Each pipeline plugs in via an adapter file that lives **inside the pipeline's own repo**. Adapters depend on pipewise (via PyPI install); pipewise has no knowledge of any specific pipeline. A reviewer cloning this repo sees a clean library — that's the verification of the "general framework" claim.

## Reference integrations (validate the abstraction)

Two production pipelines in different domains, with completely different architectures, are the proof the framework is genuinely pipeline-agnostic:

1. **FactSpark** — 7-step linear-ish news article analysis pipeline (Claude + Gemini), 186+ articles in production. A prototype adapter already drives the [Phase 3 end-to-end validation gate](tests/integration/test_phase3_validation_gate.py) against real article data.
2. **Resume-tailor** — 7-step branching/conditional pipeline with mixed JSON/Markdown/PDF outputs.

Full adapter links land here once Phase 4 ships.

## Documentation

- [**Schema reference**](docs/schema.md) — `PipelineRun`, `StepExecution`, `ScoreResult`, `EvalReport`. Read this first if you're writing an adapter.
- [**Adapter guide**](docs/adapter-guide.md) — how to integrate your own pipeline.
- [**Scorer reference**](docs/scorers.md) — the 8 built-in scorers and how to choose between them.
- [**CI integration**](docs/ci-integration.md) — wire pipewise into your CI to post a sticky eval-report comment on every PR.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo, scaffolding, CI, docs structure | ✅ Shipped |
| 1 | `PipelineRun` + `StepExecution` schemas, scorer protocols | ✅ Shipped |
| 2 | 8 built-in scorers (exact match, regex, numeric tolerance, JSON schema, cost / latency budgets, LLM judge, embedding similarity) | ✅ Shipped |
| 3 | `pipewise inspect`, `pipewise eval`, `pipewise diff` CLI | ✅ Shipped |
| 4 | FactSpark + resume-tailor reference adapters | ✅ Shipped |
| 5 | GitHub Action for PR-comment eval reports | ✅ Shipped |
| 6 | Polish + v1.0 launch | In progress |

Each phase ships incrementally to `main` with tests and CI, with reference-pipeline validation gates at the end of every architectural phase.

## Versioning

Pipewise follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

### Pre-1.0 (current)

While pipewise is on `0.x`, **any release may include breaking changes**. This is the standard SemVer convention for pre-stable software. Pin tightly:

```toml
# Pin to a specific patch version pre-1.0:
pipewise = "==0.1.2"

# Or pin to a minor range if you accept patch-level changes:
pipewise = ">=0.1,<0.2"
```

The schema, CLI, and scorer protocols are still settling. v1.0 will lock them in; until then, expect occasional breakage and pin accordingly.

### Post-1.0 (planned)

Once pipewise reaches v1.0, the following stability commitments apply:

- **MAJOR** bumps (1.x → 2.x) — may include breaking changes to any public API. We commit to **at most one major bump every 12 months** so adopters have a predictable upgrade cadence.
- **MINOR** bumps (1.0 → 1.1) — additive only. New features, new optional fields, new scorers, new CLI flags. Existing public API stays source-compatible.
- **PATCH** bumps (1.0.0 → 1.0.1) — bug fixes only.

### What counts as the "public API"

Stable across MINOR bumps post-1.0:

- The `pipewise.PipelineRun`, `pipewise.StepExecution`, `pipewise.ScoreResult`, and `pipewise.EvalReport` Pydantic models, including all field names and types
- The `pipewise.StepScorer` and `pipewise.RunScorer` Protocol signatures
- All built-in scorers' constructor signatures and documented behavior
- All `pipewise <command>` CLI commands and their documented flags
- The **`EvalReport` JSON schema** written by `pipewise eval` (CI workflows depending on this format will not break across minor versions — see "Schema stability" below)
- The adapter contract: `load_run(path) -> PipelineRun` and `default_scorers() -> tuple[list[StepScorer], list[RunScorer]]`

NOT part of the public API (may change in any release):

- Anything under `pipewise._*` or with a name starting with an underscore
- The internal scorer-execution pipeline (how scorers are dispatched, what order they run in, etc. — only the protocols and built-in behavior are stable contracts)
- Exact text of error messages
- The `__repr__` output of any class
- The `metadata: dict[str, Any]` extension field on schema models — adapters may put anything there, but pipewise makes no surface promises about how it's exposed

### Schema stability (for adapter authors)

The Pydantic schema is the load-bearing contract for adapter authors. Post-1.0:

- **Adding a new optional field** is allowed in a minor release.
- **Making a previously optional field required** requires a major bump.
- **Removing or renaming a field** requires a major bump.
- **Tightening validation** (e.g., narrowing accepted types) requires a major bump.

If you write an adapter against pipewise v1.x, it will continue to work with pipewise v1.y for any y > x without changes.

### Deprecation policy

When a feature is deprecated post-1.0:

1. A `DeprecationWarning` is added in a minor release, with the warning text pointing to the replacement.
2. The deprecated feature continues to work for the remaining lifetime of the current major version.
3. Removal happens in the next major release (≤12 months later).

Practically: anything deprecated in v1.x stays available until v2.0. You always have at least the time between deprecation and the next major bump to migrate, with a 12-month ceiling.

### Python version support

Pipewise targets actively supported Python releases per the [official Python release schedule](https://devguide.python.org/versions/). Currently: **Python 3.11+**.

When a Python version reaches its end-of-life, pipewise drops support for it in the next release (minor pre-1.0, major post-1.0). EOL'd Python versions don't receive security patches, so continuing to support them is a liability for adopters as well as for pipewise.

## License

[Apache 2.0](LICENSE) — patent-protective, enterprise-friendly, no rug-pulls.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Pre-v1, the project is opinionated and moving fast — bug reports and adapter contributions are welcome; large feature PRs should start with a discussion.

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
