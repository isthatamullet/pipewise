# pipewise

**Evaluation framework for multi-step LLM pipelines.**

> ⚠️ **Status:** Pre-alpha — under active development toward v1.0. Schema and CLI are not yet stable. Star/watch the repo to follow progress.

[![CI](https://github.com/isthatamullet/pipewise/actions/workflows/ci.yml/badge.svg)](https://github.com/isthatamullet/pipewise/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

---

## What it is

pipewise is a Python library + CLI for evaluating multi-step LLM pipelines. It defines a pipeline-agnostic schema (`PipelineRun` + `StepExecution`) that any pipeline can produce via an adapter, then runs scorers across runs and reports regressions, cost drift, and quality changes per step.

Local-first. Apache 2.0. No telemetry. No vendor lock-in. Provider-neutral.

## The problem it solves

Multi-step LLM pipelines silently break in ways that are nearly invisible until customers report them:

- **Prompt edits cascade unpredictably.** Editing the prompt in step 3 of a 7-step pipeline can shift output distributions in step 5 without warning.
- **Model swaps create silent drift.** Swapping Claude Opus → Sonnet for cost reasons can change a step's behavior subtly enough that no one notices for days.
- **Cost is opaque.** Most teams know their total monthly API spend. Almost none can tell you which step in their pipeline costs 60% of the bill.
- **Existing eval tools assume single-prompt.** Promptfoo, Braintrust, LangSmith, and DeepEval were designed for testing one prompt → one output. They have to be contorted to evaluate multi-step pipelines, and the contortion loses fidelity at the step level.

Pipewise treats the **pipeline run** as the unit of evaluation, with step-level scoring, cost attribution per step, and regression diffing across pipeline structure changes.

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

1. **FactSpark** — 7-step linear-ish news article analysis pipeline (Claude + Gemini), 186+ articles in production
2. **Resume-tailor** — 7-step branching/conditional pipeline with mixed JSON/Markdown/PDF outputs

Adapter links land here once Phase 4 ships.

## Documentation

- [**Schema reference**](docs/schema.md) — `PipelineRun`, `StepExecution`, `ScoreResult`, `EvalReport`. Read this first if you're writing an adapter.
- [**Adapter guide**](docs/adapter-guide.md) — how to integrate your own pipeline.

## Roadmap

| Phase | Scope | Target |
|---|---|---|
| 0 | Repo, scaffolding, CI, docs structure | Week 1 |
| 1 | `PipelineRun` + `StepExecution` schemas, scorer protocols | Week 1-2 |
| 2 | Built-in scorers (exact match, JSON schema, numeric tolerance, LLM judge, cost/latency budgets) | Week 2-3 |
| 3 | `pipewise inspect`, `pipewise eval`, `pipewise diff` CLI | Week 3 |
| 4 | FactSpark + resume-tailor reference adapters | Week 3-4 |
| 5 | GitHub Action for PR-comment eval reports | Week 4-5 |
| 6 | Polish + v1.0 launch | Week 5-6 |

Each phase ships incrementally to `main` with tests and CI, with reference-pipeline validation gates at the end of every architectural phase.

## Install

> Not on PyPI yet. Local install during development:

```bash
git clone https://github.com/isthatamullet/pipewise
cd pipewise
uv sync
```

## License

[Apache 2.0](LICENSE) — patent-protective, enterprise-friendly, no rug-pulls.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Pre-v1, the project is opinionated and moving fast — bug reports and adapter contributions are welcome; large feature PRs should start with a discussion.
