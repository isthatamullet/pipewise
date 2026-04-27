<!--
  Pipewise PR template. Adapter-pattern + non-negotiables in CLAUDE.md
  apply to every PR. Skim before submitting.
-->

## Summary

<!-- 1-3 sentences. What this PR does and why. Link the issue with `Closes #N`. -->

## Changes

<!-- Bulleted list of the substantive changes. Skip mechanical formatting / lint-only churn. -->

## How was this tested?

<!-- Pre-push checklist: ruff check, ruff format --check, mypy, pytest. Note any local validation gates that ran. -->

- [ ] `uv run ruff check pipewise/ tests/`
- [ ] `uv run ruff format --check pipewise/ tests/`
- [ ] `uv run mypy pipewise/`
- [ ] `uv run pytest`

## Architectural rules touched

<!-- Tick anything this PR interacts with. If unsure, leave blank. -->

- [ ] Adapter pattern (no pipeline-specific code in `pipewise/` core)
- [ ] Schema (`PipelineRun`, `StepExecution`) — backward-compatibility implications?
- [ ] Scorer protocol (`StepScorer`, `RunScorer`)
- [ ] CLI surface (`inspect`, `eval`, `diff`)
- [ ] Storage layout (timestamped, immutable reports)
- [ ] None — internal change

## Notes for the reviewer

<!-- Optional. Tradeoffs considered, follow-up work intentionally deferred, anything non-obvious. -->
