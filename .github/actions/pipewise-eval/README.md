# `pipewise-eval` GitHub Action

Posts a sticky PR comment showing eval results for a pipewise-evaluated pipeline, with a diff against a baseline from main when available.

## What it does

1. Reads a pre-built [`EvalReport`](../../../docs/schema.md) JSON for the current PR.
2. Optionally diffs against a baseline `EvalReport` (typically the most recent report from `main`).
3. Renders sticky-comment markdown via [`pipewise.ci.render_pr_comment`](../../../pipewise/ci/github_action.py).
4. Finds the existing pipewise eval comment on the PR (matched by a hidden HTML marker keyed by adapter name) and updates it, or creates a new one if none exists.

## Architectural pattern: artifact-input only

This action does **not** run your pipeline. It expects you to produce the `EvalReport` JSON yourself in an upstream step — typically by running `pipewise eval` after your pipeline finishes — and pass the file path in. This separation keeps your pipeline's secrets (LLM API keys, etc.) out of pipewise's action surface and means the action works for any pipeline shape regardless of execution complexity.

The two-step pattern in your CI:

1. **Run your pipeline + run `pipewise eval`** in your own job. Upload the resulting `EvalReport` JSON as a workflow artifact.
2. **Use this action** in a subsequent job. Download the artifact (and a baseline artifact from a separate `main`-branch workflow if you want diffs), then call this action with the paths.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `report-path` | yes | — | Path to the `EvalReport` JSON for this PR. |
| `baseline-report-path` | no | `''` | Path to the baseline `EvalReport` JSON. If omitted or the file is missing, the comment shows absolute values with no Δ column. |
| `adapter-name` | yes | — | Adapter package name (e.g. `factspark_pipewise`). Also the sticky-comment marker key — multi-adapter repos get one comment per adapter. |
| `github-token` | yes | — | Token with `pull-requests: write` permission. Default `GITHUB_TOKEN` is fine. |
| `python-version` | no | `'3.11'` | Python version used to run the renderer. |

## Minimal example workflow

```yaml
name: pipewise eval

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write
  actions: read  # required to download artifacts from other workflows

jobs:
  run-and-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run pipeline + pipewise eval
        run: |
          python -m my_pipeline.run --output runs/
          pip install pipewise
          pipewise eval \
            --adapter my_pipeline_pipewise.adapter \
            --dataset golden.jsonl \
            --output report.json

      - uses: actions/upload-artifact@v4
        with:
          name: pipewise-report
          path: report.json
          retention-days: 7

  comment-on-pr:
    needs: run-and-eval
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: pipewise-report
          path: ./report

      - name: Download baseline report from main
        uses: dawidd6/action-download-artifact@v6
        with:
          workflow: pipewise-baseline.yml
          name: pipewise-baseline-my-pipeline
          path: ./baseline
          if_no_artifact_found: warn  # silent fallback if baseline is missing

      - uses: isthatamullet/pipewise/.github/actions/pipewise-eval@main
        with:
          report-path: ./report/report.json
          baseline-report-path: ./baseline/report.json
          adapter-name: my_pipeline_pipewise
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

A separate workflow on `main` should produce the baseline artifact (use `actions/upload-artifact` with a long retention period to feed the `download-artifact` step above). See [`docs/ci-integration.md`](../../../docs/ci-integration.md) for the full baseline-artifact pattern.

## How the sticky comment works

The action embeds a hidden HTML marker `<!-- pipewise-eval-report:{adapter_name} -->` in the comment body. On every push, the action searches the PR's comments for that marker:

- **Found:** the matching comment is edited in place.
- **Not found:** a new comment is created.

The `adapter-name` input keys the marker — this means a repo with multiple adapters gets one sticky comment per adapter, and they don't clobber each other. Just call the action once per adapter with a different `adapter-name` each time.

## Multi-adapter example

```yaml
- uses: isthatamullet/pipewise/.github/actions/pipewise-eval@main
  with:
    report-path: ./report-fast.json
    adapter-name: my_pipeline_fast
    github-token: ${{ secrets.GITHUB_TOKEN }}

- uses: isthatamullet/pipewise/.github/actions/pipewise-eval@main
  with:
    report-path: ./report-detailed.json
    adapter-name: my_pipeline_detailed
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

Each call manages its own sticky comment.

## Comment format

See [`pipewise/ci/github_action.py`](../../../pipewise/ci/github_action.py) and the unit tests in [`tests/ci/test_github_action.py`](../../../tests/ci/test_github_action.py) for the full rendered shape. At a glance:

```markdown
<!-- pipewise-eval-report:factspark_pipewise -->
## Pipewise eval report — factspark_pipewise

✅ All scorers passing · 2 improvements 🟢

| Scorer × Step | Main | This PR | Δ |
| :--- | ---: | ---: | ---: |
| `ExactMatch` × `extract` | 0.40 | 0.97 | +0.57 🟢 |
| `LlmJudge` × `analyze` | 0.45 | 0.91 | +0.46 🟢 |
| `Regex` × `format` | 1.00 | 1.00 | — |

**Regressions:** 0 🔴 · **Improvements:** 2 🟢 · **Unchanged:** 1

<details><summary>Full report (1 run · dataset: golden.jsonl)</summary>
…
</details>

<sub>Updated for `a1b2c3d` · pipewise v0.0.2</sub>
```

## Troubleshooting

- **Comment doesn't appear.** Check that the calling workflow has `pull-requests: write` permission and is running on a `pull_request` event.
- **Comment isn't updating across pushes.** Each adapter must use a unique `adapter-name` — that's the marker key. If two action calls share the same name, the second will overwrite the first.
- **Baseline not found / no Δ column.** Expected on the first PR for a new repo, after artifact retention expires, or when the upstream `download-artifact` step doesn't find a baseline. Verify the baseline artifact actually exists on `main`'s most recent build.

## Versioning

Pin the action to a tag (e.g. `@v0.0.2`) once pipewise tags a release including the action. Pre-release, pin to `@main` or a specific SHA.
