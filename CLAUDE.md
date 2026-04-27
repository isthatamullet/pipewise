# pipewise — CLAUDE.md

> Project conventions and rules for any Claude Code session in this repo.
> If a `CLAUDE.local.md` is present alongside this file, read it too — it
> contains operational notes and pointers that aren't part of the public repo.

## Project Overview

**pipewise** is an open-source Python library + CLI for evaluating multi-step LLM pipelines. It is pipeline-agnostic: any pipeline plugs in via an adapter file. Reference integrations: FactSpark and a resume-tailoring pipeline.

**Goal:** v1.0 in 6-8 weeks.

## Documentation Hierarchy

Read in this order when starting fresh:
1. **PLAN.md** — architecture, phases, schema, risks/decisions table
2. **POSITIONING.md** — the canonical pitch (used by README, posts, cover letters)
3. **BACKLOG.md** — deferred items with explicit triggers
4. **CLAUDE.local.md** (if present) — local-only working notes

When information conflicts, the most recent doc update wins. Update both source and any derived surfaces (README, etc.).

## Architectural Non-Negotiables

These rules exist because they're load-bearing for the project's positioning. Violating any of them undermines the "general framework" narrative that justifies the project.

- **Adapter pattern is sacred.** `pipewise/` core never imports from FactSpark, the resume pipeline, or any specific pipeline. If you find yourself writing `if pipeline_name == "factspark"` in core code, stop and refactor.
- **Adapters live in their pipeline's repo, not in pipewise.** FactSpark adapter lives in `/home/user/factspark/integrations/pipewise/`. Resume adapter lives in `/home/user/tyler/integrations/pipewise/`. Pipewise's `examples/` directory only links to them.
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
├── posts/            # LinkedIn/Twitter/blog drafts
└── .github/workflows/
```

## Working Style — Tyler's Preferences

- **Brief responses.** Tyler reads quickly; tight summaries beat exhaustive prose.
- **Prefer action over planning when in auto mode.** Don't re-debate decided things.
- **Real codebase research before recommendations.** Use Read/Grep/Explore agent. Don't guess.
- **Honest pushback, especially on technical decisions.** Tyler explicitly wants critical review, not yes-manning.
- **No messy code shipped.** Tyler holds to 2-week shipping cycles rather than ship half-done work.
- **No mock/dummy data in production-like code.** If validating, use real data.
- **iPad-only development.** Tyler has no local terminal and no browser dev tools. Don't ask him to "open the console" or "check the network tab."
- **Use localhost URLs for testing**, never proxy URLs (carries over from FactSpark conventions).

## Anti-Patterns to Avoid

- **Don't use `sed -i` on JSON files.** Backup → edit → validate → atomic move. (Carries over from FactSpark.)
- **Don't skip git hooks** (`--no-verify`, etc.) without explicit approval.
- **Don't auto-deploy without confirmation.** Maintainer reviews before deploying.
- **Don't optimize prematurely.** v1 is file-based; database optimization is parked. Don't add it.
- **Don't add features users haven't asked for.** Stay on PLAN.md scope.

## Commands (filled in as built)

```bash
# Install dev environment
uv sync

# Run tests
uv run pytest

# Lint + type check
uv run ruff check . && uv run mypy pipewise/

# CLI (once Phase 3 ships)
uv run pipewise inspect <run.json>
uv run pipewise eval --dataset golden.jsonl --adapter factspark
uv run pipewise diff <report1.json> <report2.json>
```

## Communication Channels

- **GitHub issues** — feature requests, bugs (post-Phase 0)
- **GitHub Projects** — task tracking
- **Show HN (Phase 6)** — v1.0 launch

## Workflow Rhythm — Match Ceremony to Risk

Pipewise is a small (~2-3K LOC) library with no users until v1.0+ launches. **Resist FactSpark-style heavy planning ceremony — it doesn't pay back at this scale.**

Three tiers of workflow, calibrated to change risk:

- **Tier 1 — Trivial changes (most work):** Read → Edit → Test → Commit. No plan doc, no code-reviewer, no PR ceremony.
- **Tier 2 — Substantial changes (a few per phase):** Quick chat-based plan → implement → tests → self-review → commit. Skip code-reviewer agent unless there's a specific concern.
- **Tier 3 — Architectural decisions (rare; mostly already made):** Use built-in Plan agent → decision in PLAN.md §7 → implement → code-reviewer IS justified here. Expect ~3-5 of these in the whole build.

**Skip these tools for pipewise:** PRP/PRD skills, factspark-architecture-planner, factspark-docs-maintainer, create-implementation-guide. They're designed for product features at orgs with multiple stakeholders, not for solo library development.

**Use these tools for pipewise:** built-in Plan agent (rare), Explore agent (when researching), code-reviewer (~3 times total — schema in Phase 1, CLI in Phase 3, adapter contract in Phase 4), Gemini Code Assist on PRs (Phase 4+), `simplify` skill (once per phase).

**Branching strategy:**
- **Phases 0-3:** push to `main` directly (no users, no risk, faster shipping)
- **Phase 4+:** switch to PR-per-feature (now there are reference integrations and potential external eyes)
- **Phase 6+:** maintain PR discipline; engage Gemini Code Assist productively

The artifacts already produced (PLAN, POSITIONING, BACKLOG) are sufficient up-front planning. Don't re-plan unless the situation actually changes.

## Companion Codebases

- **FactSpark** at `/home/user/factspark/` — first reference integration; adapter will live in `/home/user/factspark/integrations/pipewise/`
- **Resume pipeline** at `/home/user/tyler/` — second reference integration; adapter will live in `/home/user/tyler/integrations/pipewise/`
- Both have their own CLAUDE.md, agents, and conventions. Respect them.

## When Tyler Says...

- **"ship it"** — means commit + push. Does NOT mean deploy unless explicitly stated.
- **"deploy"** — means deploy. Always confirm scope before acting.
- **"let's plan"** — produce a written plan; don't start coding until approved.
- **"what do you think?"** — give honest opinion with tradeoffs, not validation.
- **"any concerns?"** — surface real concerns; "no" is suspicious if there obviously are some.
