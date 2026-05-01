# CI integration

How to wire pipewise into your repo's CI so every PR gets an eval report posted as a sticky comment, with a diff against `main` when one's available.

> **Status:** the GitHub Action is at [`.github/actions/pipewise-eval/`](../.github/actions/pipewise-eval/) and is usable today. Pin to a SHA pre-v1.0 and to a release tag once v1.0 ships.

---

## What you get

A single sticky comment per adapter on every PR, updated in place across pushes:

```markdown
<!-- pipewise-eval-report:pipewise_anthropic_quickstarts -->
## Pipewise eval report — pipewise_anthropic_quickstarts

✅ All scorers passing · 2 improvements 🟢

| Scorer × Step | Main | This PR | Δ |
| :--- | ---: | ---: | ---: |
| `anthropic_agent_response_shape` × `agent__1` | 1.00 | 1.00 | — |
| `anthropic_agent_response_shape` × `agent__2` | 1.00 | 1.00 | — |
| `run_latency_60s` (run-level) | 0.85 | 0.97 | +0.12 🟢 |
| `run_cost_10c` (run-level) | 0.75 | 0.92 | +0.17 🟢 |

**Regressions:** 0 🔴 · **Improvements:** 2 🟢 · **Unchanged:** 2

<details><summary>Full report (2 runs · dataset: golden.jsonl)</summary>
…
</details>

<sub>Updated for `a1b2c3d` · pipewise v0.1.0</sub>
```

The verdict line is the most prominent element — reviewers can tell at a glance whether the PR is safe (`✅`), warning (`⚠️`), or breaking (`❌`). The `Δ` column shows signed deltas vs `main` with 🟢/🔴 emoji as the color channel (GitHub markdown strips inline color). Newly-failing checks expand into a `<details>` block with the specific case + scorer + reason. The full per-case table lives in another `<details>` block — collapsed by default so the comment stays scannable.

### Real-world example: regression caught

The example above is illustrative; the snippet below shows what the comment looks like when the action catches a real regression. Imagine a capture-code change that inadvertently dropped the `stop_reason` field from one of the agent step's serialized outputs — the `anthropic_agent_response_shape` scorer (a `JsonSchemaScorer` requiring `content` and `stop_reason`) flips to failing on the affected step. The action surfaces it in the verdict line, drops the offending case into the "Newly failing checks" detail block, and leaves the unaffected steps and run-level scorers green — the operational signal a reviewer needs to know whether to merge.

```markdown
<!-- pipewise-eval-report:pipewise_anthropic_quickstarts -->
## Pipewise eval report — pipewise_anthropic_quickstarts

❌ 1 regression · was passing on main, failing here

| Scorer × Step | Main | This PR | Δ |
| :--- | ---: | ---: | ---: |
| `run_latency_60s` (run-level) | 1.00 | 1.00 | — |
| `run_cost_10c` (run-level) | 1.00 | 1.00 | — |
| `anthropic_agent_response_shape` × `agent__1` | 1.00 | 1.00 | — |
| `anthropic_agent_response_shape` × `agent__2` | 1.00 | 0.00 | -1.00 🔴 |

**Regressions:** 1 🔴 · **Improvements:** 0 🟢 · **Unchanged:** 3

<details><summary><b>Newly failing checks (1)</b></summary>

- `anthropic_agent_response_shape` × `agent__2` · run `golden-001-iteration` — score 1.00 → 0.00 (passed → failed)

</details>

<details><summary>Full report (1 run · dataset: golden.jsonl)</summary>
…per-case table omitted for brevity…
</details>

<sub>Updated for `592e250` · pipewise v0.1.0</sub>
```

The "Newly failing checks" block names the specific run and step, so reviewers navigate directly to the failing case without scanning the full report. Run-level scorers (`run_latency_60s`, `run_cost_10c`) stay green because the regression was structural — output-shape, not budget-shape.

---

## The two-step CI pattern

Pipewise [evaluates, it does not execute](../README.md#what-it-is-not) — and the GitHub Action follows the same separation. The action does NOT run your pipeline. Your CI does that, then hands pipewise a pre-built `EvalReport` JSON to render.

**Step 1 — your CI:** run your pipeline against a small canonical dataset, run `pipewise eval` against the resulting runs, upload the `EvalReport` as a workflow artifact.

**Step 2 — `pipewise-eval` action:** download the artifact (and a baseline `EvalReport` from a separate `main`-branch workflow), call the action, get a sticky comment.

Why split:

- **Your pipeline's secrets stay yours.** Your LLM API keys, vendor tokens, etc. live in the run-and-eval job. The pipewise action only needs `pull-requests: write` — no secret handling on the comment side.
- **Pipewise stays adapter-shape-agnostic.** Any pipeline that produces an `EvalReport` (one of [the JSON shape pipewise defines](schema.md)) gets a comment. The action doesn't care whether your pipeline is LangChain, raw Anthropic SDK, a shell script, or all three glued together.
- **You get a clean cache story.** `pipewise eval` produces an immutable timestamped report; the artifact upload preserves it; subsequent steps just read it.

---

## Minimal example workflow

A complete, copy-pasteable `.github/workflows/pipewise-eval.yml` for an adopter's repo:

```yaml
name: pipewise eval

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write
  actions: read  # required for cross-workflow artifact downloads

jobs:
  run-and-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run pipeline + pipewise eval
        env:
          # Your pipeline's secrets — only this job sees them.
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          # Pre-v1.0 / pre-PyPI install — pin to a SHA or tag in CI.
          pip install git+https://github.com/isthatamullet/pipewise.git@main

          # 1. Run your pipeline against your canonical inputs (shape is
          #    your pipeline's concern; this is just an example invocation).
          python -m my_pipeline.run --inputs canonical-inputs.jsonl --output-dir runs/

          # 2. Materialize PipelineRuns: call your adapter's load_run once
          #    per completed run and write the results as JSONL — one
          #    serialized PipelineRun per line. See `docs/adapter-guide.md`
          #    "Where PipelineRun JSONL files come from" for the canonical
          #    materialization-script pattern.
          python -m my_pipeline_pipewise.build_dataset \
            --runs-dir runs/ --output runs.jsonl

          # 3. Run pipewise eval on the JSONL of PipelineRuns. Pipewise
          #    writes to a timestamped subdirectory under --output-root;
          #    we copy the produced file to a stable path for the artifact
          #    upload below. The per-adapter segment under reports/ keeps
          #    the glob unambiguous in multi-adapter repos.
          pipewise eval \
            --adapter my_pipeline_pipewise.adapter \
            --dataset runs.jsonl \
            --output-root reports/my_pipeline_pipewise/
          cp reports/my_pipeline_pipewise/*/report.json report.json

      - uses: actions/upload-artifact@v4
        with:
          name: pipewise-report
          path: report.json
          retention-days: 7

  comment-on-pr:
    needs: run-and-eval
    runs-on: ubuntu-latest
    steps:
      - name: Download this PR's report
        uses: actions/download-artifact@v4
        with:
          name: pipewise-report
          path: ./report

      - name: Download baseline report from main
        # See "Silent baseline fallback" below — `continue-on-error: true`
        # is the catch-all that keeps the comment job running when the
        # baseline workflow has never run, has no artifacts yet, or
        # otherwise can't be reached. The pipewise-eval action then
        # silently falls back to absolute-values rendering.
        continue-on-error: true
        uses: dawidd6/action-download-artifact@v8
        with:
          workflow: pipewise-baseline.yml
          name: pipewise-baseline-my-pipeline
          path: ./baseline
          if_no_artifact_found: warn

      - uses: isthatamullet/pipewise/.github/actions/pipewise-eval@main
        with:
          report-path: ./report/report.json
          baseline-report-path: ./baseline/report.json
          adapter-name: my_pipeline_pipewise
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

> **Pin the action and pipewise install in production CI.** Both examples above use `@main` for readability, but main can move under your feet — a breaking change merged upstream would silently flow into your CI. Pin both `pipewise/.github/actions/pipewise-eval@<sha-or-tag>` and `git+https://...@<sha-or-tag>` to a specific commit SHA pre-v1.0, then switch to a release tag once v1.0 ships.

A few details worth understanding:

- **`needs: run-and-eval`** sequences the comment job after the eval job. They're separate jobs (not steps in one job) so the second one can stay tightly scoped — checkout-free, secret-free.
- **`actions: read` permission** is required by the cross-workflow artifact download. Without it, `dawidd6/action-download-artifact` can't reach the baseline workflow's artifact.
- **`if_no_artifact_found: warn`** is the right setting for the baseline. If there's no baseline yet (first PR on a new repo, retention expired, baseline workflow hasn't run yet), the comment job continues without a baseline and the action renders an absolute-values comment with no `Δ` column — see the [silent baseline fallback](#silent-baseline-fallback) section below.

---

## Baseline strategy

The action diffs your PR's report against a "baseline" report from `main`. You produce that baseline yourself, in a separate workflow that runs on every push to `main`:

```yaml
# .github/workflows/pipewise-baseline.yml
name: pipewise baseline

on:
  push:
    branches: [main]

jobs:
  produce-baseline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run pipeline + pipewise eval
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          # Pre-v1.0 / pre-PyPI install — pin to a SHA or tag in CI.
          pip install git+https://github.com/isthatamullet/pipewise.git@main
          python -m my_pipeline.run --inputs canonical-inputs.jsonl --output-dir runs/
          python -m my_pipeline_pipewise.build_dataset \
            --runs-dir runs/ --output runs.jsonl
          pipewise eval \
            --adapter my_pipeline_pipewise.adapter \
            --dataset runs.jsonl \
            --output-root reports/my_pipeline_pipewise/
          cp reports/my_pipeline_pipewise/*/report.json report.json

      - uses: actions/upload-artifact@v4
        with:
          name: pipewise-baseline-my-pipeline
          path: report.json
          retention-days: 90  # long enough that long-lived PRs find it
```

**Naming convention.** `pipewise-baseline-<adapter>` lets a multi-adapter repo carry parallel baselines. The PR-side `download-artifact` step references the matching name.

**Retention.** Default GitHub artifact retention is 90 days; that's the right ceiling for the baseline. PRs that sit open longer than that lose their baseline and revert to absolute-values comments — usually a signal the PR is stale and worth force-pushing anyway.

**Determinism.** A baseline that re-runs the pipeline produces fresh `LlmJudge` calls, fresh latency, fresh costs. If your scorers are stable across runs (deterministic models, fixed temperatures, etc.) the baseline is meaningful. If they're not, the comment will show spurious `Δ`s; that's a correctness signal you may want to address by tightening determinism in the pipeline itself rather than papering over in pipewise.

---

## Silent baseline fallback

If the `baseline-report-path` input is unset, OR the path is set but no file exists at it, the action renders the comment with absolute values and no `Δ` column. The verdict line in that case is:

```
🆕 N runs · P/T scorers passing · no baseline
```

Common operational scenarios where this kicks in:

- First PR on a new repo (baseline workflow hasn't run yet)
- The baseline workflow failed on the most recent `main` push, so no artifact exists
- Artifact retention expired
- The PR was opened from a fork without access to the baseline artifact

In all of these, the action *still* posts a useful comment showing what your PR's eval looks like in absolute terms. No silent failure.

> **Important: use `continue-on-error: true` on the baseline-download step.** `dawidd6/action-download-artifact`'s `if_no_artifact_found: warn` only handles "workflow exists but has no matching artifact" — it does NOT handle "workflow has never run", which 404s on the underlying GitHub API. Both cases land in the same operational state ("no baseline available"), so wrapping the step with `continue-on-error: true` is the simpler catch-all. When the download step fails, the `./baseline` directory just stays empty, and the pipewise-eval action's silent-baseline-fallback behavior takes over.

---

## Multi-adapter repos

Each call to the action posts its own sticky comment, keyed by `adapter-name`. A repo with multiple adapters just calls the action multiple times:

```yaml
- uses: isthatamullet/pipewise/.github/actions/pipewise-eval@main
  with:
    report-path: ./report-fast/report.json
    baseline-report-path: ./baseline-fast/report.json
    adapter-name: my_pipeline_fast
    github-token: ${{ secrets.GITHUB_TOKEN }}

- uses: isthatamullet/pipewise/.github/actions/pipewise-eval@main
  with:
    report-path: ./report-detailed/report.json
    baseline-report-path: ./baseline-detailed/report.json
    adapter-name: my_pipeline_detailed
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

Two sticky comments will appear on the PR, one per adapter, each updated in place on every push. The hidden HTML marker in the comment body is `<!-- pipewise-eval-report:{adapter-name} -->`, so as long as `adapter-name` is unique per call, the comments stay independent.

The action also reuses a single Python venv across calls in the same job — see [the action's README](../.github/actions/pipewise-eval/README.md) for the implementation detail.

---

## Comment format walkthrough

The comment is rendered by [`pipewise.ci.render_pr_comment()`](../pipewise/ci/github_action.py). The structure is:

| Section | Purpose |
|---|---|
| **Sticky marker** (HTML comment, line 1) | Hidden token keyed by adapter name. The action uses it to find-and-update the existing comment. |
| **H2 header** | Identifies the report at a glance — `## Pipewise eval report — {adapter_name}`. |
| **Verdict line** | Most prominent element. Single line with emoji + plain-English summary: `✅ All scorers passing · no change vs main` / `❌ N regressions` / `🆕 N runs · no baseline`. |
| **Roll-up table** | One row per `(scorer, step)` combination. Numeric columns right-aligned; `Δ` column shows signed deltas with 🟢/🔴 emoji or `—` for no change. Em-dash placeholder is used for "unchanged" so the eye skips over noise. |
| **Counts row** | `**Regressions:** N 🔴 · **Improvements:** N 🟢 · **Unchanged:** N`. Reservation: regressions/improvements are strict pass/fail flips, not score-only deltas. |
| **Extras footnote** *(when relevant)* | `_Plus: N score deltas, M newly added, K removed._` — only renders when those categories are non-empty. Keeps the clean common case clean. |
| **Newly-failing checks** *(when relevant)* | Collapsible `<details>` listing each scorer that flipped passing → failing, with the specific case ID and reason. |
| **Full report** | Collapsible `<details>` with the per-case table — every `(run, step, scorer)` combination. |
| **Footer** | `<sub>Updated for {short_sha} · pipewise v{version}</sub>` — short SHA lets reviewers verify the comment matches the latest push. |

For the full set of states the renderer handles (passing-no-change, passing-improvements, regressing, missing-baseline, score-deltas-without-flips, etc.), see the [renderer's unit tests](../tests/ci/test_github_action.py).

---

## Worked example: pipewise-anthropic-quickstarts

`pipewise-anthropic-quickstarts` is one of pipewise's two in-tree reference adapters. Its CI integration follows the pattern documented above, with these specifics:

- **Canonical dataset:** the two committed golden runs at [`examples/anthropic-quickstarts/runs/`](../examples/anthropic-quickstarts/runs/) — `golden-001-iteration.json` (multi-iteration agent loop with two parallel tool calls) and `golden-002-skipped.json` (greeting input, no tool calls). Together they exercise iteration, per-tool steps, and an agent that stops on `end_turn` without using tools.
- **Adapter name:** `pipewise_anthropic_quickstarts`.
- **Baseline retention:** 90 days (default).
- **Default scorer suite:** `anthropic_agent_response_shape` (step, scoped to `agent__1..8` matching the agent's `DEFAULT_MAX_ITERATIONS`), `run_latency_60s`, `run_cost_10c` with `on_missing="skip"`. See [`examples/anthropic-quickstarts/pipewise_anthropic_quickstarts/adapter.py`](../examples/anthropic-quickstarts/pipewise_anthropic_quickstarts/adapter.py) for the source.

For the LangGraph reference adapter, the same pattern applies — substitute `pipewise_langgraph` for the adapter name and point at [`examples/langgraph/runs/`](../examples/langgraph/runs/) for the dataset.

---

## Troubleshooting

### Comment doesn't appear

- The calling workflow needs `pull-requests: write` permission. Add it under `permissions:` at the workflow or job level.
- The workflow must run on a `pull_request` event (or a related event with `pull_request` context). The action uses `github.event.pull_request.number` to identify the target PR.
- Check the action's logs in the workflow run — if the `Find existing pipewise eval comment` step shows an auth error, the `github-token` input doesn't have the right scope.

### Comment isn't updating across pushes

- Each call must use a unique `adapter-name`. That's the marker key. Two calls with the same name will overwrite each other's comments.
- If you renamed the adapter mid-PR, the action will create a new comment under the new name and orphan the old one. Either keep the name stable or accept the orphan.

### Δ column is missing

- Expected when no baseline is provided. See [Silent baseline fallback](#silent-baseline-fallback).
- If you DID provide a baseline-report-path but the column is still missing, verify the file actually exists at that path in the runner — the action treats missing files as "no baseline" rather than failing. Check the `Render PR comment markdown` step's logs.

### Comment shows spurious `Δ`s on every push

- Your scorers aren't deterministic. `LlmJudgeScorer` calls produce different results across runs unless you've pinned model temperature, used `consensus_n` aggressively, or are evaluating on cached outputs. The fix is in your pipeline / scorer config, not pipewise.

### A pure `git revert` on a PR doesn't update the comment

- If a PR has only one commit and you push a `git revert` that exactly cancels it, the cumulative diff vs `main` becomes empty — the workflow's `paths:` filter has nothing to match against, so the workflow doesn't run, and the sticky comment isn't updated. This is GitHub Actions behaving correctly: there's nothing meaningful to test. To trigger an update, push a non-trivial change instead of a pure revert (e.g., add a benign whitespace edit somewhere in the path-filter scope).

### Action fails on `pip install pipewise`

- Pre-v1.0, pipewise isn't on PyPI yet. Use `pip install git+https://github.com/isthatamullet/pipewise.git@<ref>` instead, where `<ref>` is `main`, a tag, or a specific commit SHA. The action itself installs pipewise the same way internally — see [its `Install pipewise` step](../.github/actions/pipewise-eval/action.yml).
- Pin the action to a specific commit SHA pre-v1.0 (browse [recent commits](https://github.com/isthatamullet/pipewise/commits/main) for one); switch to a release tag once one exists that includes the action.

### Comment doesn't appear on PRs from forks

- For PRs opened from a fork, GitHub restricts the default `GITHUB_TOKEN` to read-only scopes — the action's `find-comment` and `create-or-update-comment` calls will fail with permission errors. Two ways to handle it:
  - **`pull_request_target` event** — runs the workflow with full write tokens against the base branch's code. ⚠️ Security caveat: never check out the fork's code in this workflow without careful sandboxing; a malicious fork could steal secrets. Safe pattern: keep the run-and-eval job on `pull_request` (read-only) and the comment-on-pr job on `pull_request_target` reading the artifact produced by the run-and-eval job.
  - **`workflow_run` event** — runs after the PR's CI completes, has full write access. More complex to wire (requires looking up the original PR number from the workflow run context) but is the conservative default for public repos.
- Internal-only repos (no fork PRs) can ignore this — the default `GITHUB_TOKEN` has write access for non-fork PRs.

---

## Related docs

- [Schema reference](schema.md) — the `EvalReport` JSON shape your CI is producing.
- [Adapter guide](adapter-guide.md) — how to write the adapter that the run-and-eval job uses.
- [Action README](../.github/actions/pipewise-eval/README.md) — the action's input/output reference.
