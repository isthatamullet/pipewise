# Contributing to pipewise

Thanks for your interest! Pipewise is a small, opinionated library moving steadily toward a v1.0 launch. The fastest path to a merged contribution is to skim this file, match the patterns already in the repo, and open an issue first if your change is non-trivial.

## What's welcome right now

- **Bug reports.** Open an issue with a minimal reproduction. The smaller the repro, the faster the fix.
- **Adapter contributions.** If you write a pipewise adapter for an open-source pipeline, link it from `examples/README.md` via a PR.
- **Schema feedback.** If `PipelineRun` / `StepExecution` doesn't fit your pipeline shape, that's exactly the kind of feedback I want before v1.0 locks the schema.
- **Documentation improvements.** Typos, clarifications, missing examples — all welcome via PR.

## What to discuss first

- **Large feature PRs.** Open an issue or discussion before sending code — pipewise is opinionated about staying focused (see [`README.md`](README.md) "What it is *not*"), and unsolicited large PRs may be rejected for scope. A 5-minute discussion is much better than a 5-hour PR that has to be closed.
- **New built-in scorers.** Often better as a third-party package; only the most universal scorers ship in core. Open an issue describing the use case so we can discuss whether `pipewise.scorers/` is the right home.
- **Schema changes.** Anything touching `PipelineRun` / `StepExecution` / `ScoreResult` / `EvalReport` is load-bearing for adapter authors. Discuss in an issue before changing.

## Architectural non-negotiables

These rules are load-bearing for the project's positioning. PRs that violate any of them will be rejected on principle, not nitpicked into shape:

- **Adapter pattern is sacred.** `pipewise/` core never imports from any specific pipeline. If you find yourself writing `if pipeline_name == "X"` in core code, stop and refactor.
- **Adapters live in their pipeline's repo, not in pipewise.** Pipewise's `examples/` directory only links to external adapter implementations.
- **Pipeline runs are immutable, append-only.** New runs never overwrite old runs. Filenames are timestamped.
- **Pipewise EVALUATES, does not EXECUTE.** Adapters produce `PipelineRun`s; pipewise reads them and runs scorers. Pipeline execution is out of scope for v1.
- **No ChromaDB / no PostgreSQL / no cloud dependency in v1 core.** File-based storage only. Database support is parked.
- **No telemetry.** Pipewise does not phone home, ever.

## Local dev setup

```bash
git clone https://github.com/isthatamullet/pipewise
cd pipewise
uv sync
```

### Running checks

Before pushing, run the same gates CI runs:

```bash
uv run pytest                    # Test suite (380+ tests)
uv run ruff format --check       # Formatting (CI fails if not formatted)
uv run ruff check .              # Lint
uv run mypy pipewise/            # Type-check
```

If `ruff format --check` fails, run `uv run ruff format` to auto-fix.

### Optional extras

Some scorers depend on optional packages:

- `pipewise[embeddings]` — installs the embedding-similarity scorer's dependencies (`sentence-transformers`).
- `pipewise[llm-judge]` — installs the LLM-judge scorer's dependencies (`anthropic`).

These extras are not pulled by default to keep the base install lean.

## Commit conventions

Pipewise follows a relaxed flavor of [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new user-facing functionality
- `fix:` — bug fix
- `docs:` — documentation only
- `chore:` — internal housekeeping (deps, CI config, etc.)
- `refactor:` — code change that doesn't add features or fix bugs
- `test:` — test-only changes

For larger pieces of phased work, the prefix `Phase N #M:` (e.g., `Phase 5 #36:`) is used to tie commits to the corresponding GitHub issue. This is purely a maintainer convention; outside contributors should use the standard prefixes above.

## Pull request process

1. **Branch from `origin/main`.** Branch names are limited to ≤15 characters per the project's CI naming rules — keep them short and topical (`fix/typo`, `feat/scorer-x`, `docs/quickstart`).
2. **Open the PR against `main`.** All PRs are squash-merged, so individual commit messages within a branch are absorbed into one tidy commit on main.
3. **Fill in the PR template.** [`.github/pull_request_template.md`](.github/pull_request_template.md) walks through the checklist items pipewise expects: lint clean, format clean, types pass, tests pass, architectural rules respected.
4. **Wait for CI to pass.** GitHub Actions runs the full test suite + formatting + lint + type-check on Python 3.11 and 3.12. Both must pass.
5. **Address Gemini Code Assist comments.** Pipewise uses Google's Gemini Code Assist for an automated first-pass review on every PR. It often surfaces medium-priority comments (clarity, edge cases, consistency); please address them before requesting human review. False positives are rare but happen — explain in a reply why a suggestion doesn't apply if needed.
6. **Maintainer review.** Once CI is green and Gemini comments are addressed, the maintainer reviews. Small documentation PRs may be merged directly; non-trivial code changes typically get one round of review feedback.

## AI / automated PRs

You're encouraged to use AI tools (Claude, Copilot, Cursor, etc.) to help with your work — they make solid contributors more productive. **However, contributions need meaningful human intervention, judgment, and context.**

If the human effort that went into your PR is less than the maintainer effort needed to review it, the PR is at risk of being closed. Practically:

- PRs that look like raw LLM output without curation will likely be closed without review.
- Comments / PR descriptions copy-pasted directly from an LLM are a red flag.
- Bulk PRs from automation that hasn't been carefully validated are not welcome.

The bar is: *would a thoughtful contributor be willing to put their name on this?* If yes, ship it. If you'd be embarrassed to have your name on it, don't.

## Code of conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it. Report unacceptable behavior to [hello@pipewise.dev](mailto:hello@pipewise.dev).

## License

By contributing, you agree your contributions are licensed under [Apache 2.0](LICENSE).
