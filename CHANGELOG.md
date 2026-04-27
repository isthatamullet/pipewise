# Changelog

All notable changes to pipewise are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Until v1.0, **minor and patch versions may include breaking changes** — pipewise is pre-stable and the public API is still settling.

## [Unreleased]

_Phase 5 — GitHub Action for PR-comment eval reports — in progress._

## [0.0.1] — 2026-04-27

First milestone tag. Schema, runner, CLI, and 8 built-in scorers are in place; both reference adapters (FactSpark + resume-tailor) ship in their own pipeline repos with end-to-end validation gates against pipewise's runner.

Not a release-quality promise — v1.0 remains the launch target.

### Added

- **Schema** (`pipewise.PipelineRun`, `pipewise.StepExecution`) — Pydantic v2 models with `extra="forbid"` to surface adapter typos, `AwareDatetime` to reject naive datetimes, and an `metadata: dict[str, Any]` extension point on every model.
- **Scorer protocols** — `StepScorer` operates on a single `StepExecution`; `RunScorer` operates on a whole `PipelineRun`. Both are Python `Protocol`s so adapters can supply custom scorers without inheriting from a base class.
- **Eight built-in scorers**:
  - `ExactMatchScorer` — strict equality against an expected value.
  - `RegexScorer` — pattern match against a top-level string field in `outputs`.
  - `JsonSchemaScorer` — JSON Schema validation of step outputs.
  - `NumericToleranceScorer` — within-tolerance comparison of numeric fields.
  - `EmbeddingSimilarityScorer` — cosine similarity between step outputs and expected text. Optional `[embeddings]` extra.
  - `CostBudgetScorer` — run-level cost cap with `on_missing="skip"` for pipelines without per-call usage telemetry.
  - `LatencyBudgetScorer` — run-level latency cap with the same `on_missing` behavior.
  - `LlmJudgeScorer` — Anthropic-API-backed rubric judge with structured-output parsing, prompt caching on the rubric, and an N-call consensus mode. Optional `[llm-judge]` extra; excluded from adapter `default_scorers()` by convention (paid API).
- **Runner**:
  - `pipewise.runner.eval.run_eval` — sequential scorer execution across a dataset; scorer exceptions caught and recorded as failed `ScoreResult`s rather than aborting the eval.
  - `pipewise.runner.storage` — timestamped, never-overwritten JSON report files. Same-second collisions raise `FileExistsError`.
- **CLI** (`pipewise <command>`):
  - `pipewise inspect <run.json>` — pretty-prints a `PipelineRun`.
  - `pipewise eval --dataset <jsonl> --adapter <module> [--scorers <toml>]` — runs scorers across a dataset of pipeline runs and writes a timestamped report.
  - `pipewise diff <report-a.json> <report-b.json>` — surfaces score-level differences between two eval reports.
- **Adapter resolution** — `--adapter <dotted.module.path>` resolves via `importlib.import_module`. Adapters expose `load_run(path) -> PipelineRun` and `default_scorers() -> tuple[list[StepScorer], list[RunScorer]]` at module level.
- **Reference adapters** — both ship in their own pipeline repos and go public alongside v1.0:
  - `factspark-app/integrations/pipewise/` — linear-ish 7-step news-analysis pipeline (mixed Anthropic / Google models).
  - `job-search/integrations/pipewise/` — branching/conditional resume-tailor pipeline (optional steps, step 4 vs step 4b mutex via two step IDs with one always skipped, mixed JSON / Markdown side-products).
- **Validation gates**:
  - `tests/integration/test_phase3_validation_gate.py` — Phase 3 prototype gate against FactSpark.
  - `tests/integration/test_phase4_factspark_gate.py` — production-shape gate driving `run_eval` through `factspark_pipewise.adapter`.
  - `tests/integration/test_phase4_resume_tailor_gate.py` — production-shape gate driving `run_eval` through `resume_tailor_pipewise.adapter`. Reference runs discovered dynamically by `(resume_format, step2_status)` shape categories so personal application identifiers stay out of the public test history.
- **Docs**:
  - `README.md` — pitch, quickstart, roadmap.
  - `docs/schema.md` — full schema reference for adapter authors.
  - `docs/adapter-guide.md` — adapter-authoring guide with worked examples for both linear (FactSpark) and branching (resume-tailor) pipelines, plus the `default_scorers()` convention and the no-token-capture pattern.
  - `docs/scorers.md` — built-in scorer reference + the `LlmJudgeScorer`-not-in-defaults guidance.
  - `examples/README.md` — index of reference adapters.
  - `.github/pull_request_template.md` — pre-merge checklist (lint, format, types, tests, architectural rules).

### Decided and intentionally deferred

- **Cost / latency / token capture in v1 core** — neither reference pipeline runs inside an SDK that exposes per-call usage to user code (both are Claude-Code-orchestrated). Adapters set the relevant fields to `None` and rely on `CostBudgetScorer(on_missing="skip")` / `LatencyBudgetScorer(on_missing="skip")`. Pipewise's schema is forward-compatible — when telemetry becomes available, the change is purely additive (no schema migration, no adapter contract change).
- **Database storage backend** — file-based storage only in v1; ChromaDB / PostgreSQL parked.
- **Telemetry / phone-home** — pipewise does not.
- **Pipeline execution** — out of scope. Pipewise *evaluates* completed runs; adapters supply them.

[Unreleased]: https://github.com/isthatamullet/pipewise/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/isthatamullet/pipewise/releases/tag/v0.0.1
