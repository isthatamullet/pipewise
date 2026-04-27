# pipewise — CLAUDE.md

> Project conventions and rules for any Claude Code session in this repo.
> If a `CLAUDE.local.md` is present alongside this file, read it too — it
> contains operational notes and pointers that aren't part of the public repo.

## Project Overview

**pipewise** is an open-source Python library + CLI for evaluating multi-step LLM pipelines. It is pipeline-agnostic: any pipeline plugs in via an adapter file. Two real-world reference integrations validate the abstraction across different pipeline shapes (one linear news-analysis pipeline, one branching/conditional resume-tailoring pipeline).

**Goal:** v1.0 in 6-8 weeks.

## Documentation Hierarchy

Read in this order when starting fresh:
1. **PLAN.md** — architecture, phases, schema, risks/decisions table
2. **POSITIONING.md** — the canonical pitch (used by README, posts, etc.)
3. **BACKLOG.md** — deferred items with explicit triggers
4. **CLAUDE.local.md** (if present) — local-only working notes

When information conflicts, the most recent doc update wins. Update both source and any derived surfaces (README, etc.).

## Architectural Non-Negotiables

These rules are load-bearing for the project's positioning. Violating any of them undermines the "general framework" narrative that justifies the project.

- **Adapter pattern is sacred.** `pipewise/` core never imports from any specific pipeline. If you find yourself writing `if pipeline_name == "X"` in core code, stop and refactor.
- **Adapters live in their pipeline's repo, not in pipewise.** Pipewise's `examples/` directory only links to external adapter implementations.
- **Pipeline runs are immutable, append-only.** New runs never overwrite old runs. Filenames are timestamped. (See PLAN.md §4.5.)
- **Pipewise EVALUATES, does not EXECUTE.** Adapters produce `PipelineRun`s; pipewise reads them and runs scorers. Pipeline execution is parked in BACKLOG.md. Don't sneak it in.
- **No ChromaDB / no PostgreSQL / no cloud dependency in v1 core.** File-based storage only. Database support is parked.
- **No telemetry.** Pipewise does not phone home, ever.

## Tech Stack (locked decisions — see PLAN.md §7)

- **Language:** Python 3.11+
- **Build:** uv + pyproject.toml
- **Validation:** Pydantic v2
- **License:** Apache 2.0
- **CLI framework:** Typer (decided informally; revisit if needed)
- **Test framework:** pytest
- **Lint/format:** ruff
- **Type check:** mypy
- **CI:** GitHub Actions

## Repo Structure (target — built incrementally in phases)

```
pipewise/
├── pipewise/
│   ├── core/         # schema, scorer protocol, report
│   ├── scorers/      # built-in scorers
│   ├── runner/       # eval execution, parallelism
│   └── cli.py        # Typer CLI
├── tests/
├── docs/
├── examples/         # links to external adapters
└── .github/workflows/
```

## Commands

```bash
# Install dev environment
uv sync

# Run tests
uv run pytest

# Lint + type check
uv run ruff check . && uv run mypy pipewise/

# CLI (once Phase 3 ships)
uv run pipewise inspect <run.json>
uv run pipewise eval --dataset golden.jsonl --adapter <adapter-name>
uv run pipewise diff <report1.json> <report2.json>
```

## Communication Channels

- **GitHub issues** — feature requests, bugs
- **GitHub Projects** — task tracking
- **Show HN (Phase 6)** — v1.0 launch
