"""pipewise CLI entry point.

Three commands wired in Phase 3:
- `pipewise inspect <run.json>` (#24): pretty-print a `PipelineRun` JSON file.
- `pipewise eval --dataset --adapter [--scorers]` (#25): run scorers across
  a dataset and persist an `EvalReport`.
- `pipewise diff <report_a> <report_b>` (#26): compare two `EvalReport`s.

The CLI is the wiring layer; logic lives in `pipewise.runner.*`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from pipewise import __version__
from pipewise.core.report import EvalReport
from pipewise.core.schema import PipelineRun
from pipewise.runner.adapter import (
    AdapterError,
    resolve_default_scorers,
)
from pipewise.runner.dataset import DatasetError, load_dataset
from pipewise.runner.diff import compute_diff, format_diff
from pipewise.runner.eval import run_eval
from pipewise.runner.inspect import format_run
from pipewise.runner.scorer_config import ScorerConfigError, load_scorer_config
from pipewise.runner.storage import write_report

app = typer.Typer(
    name="pipewise",
    help="Evaluation framework for multi-step LLM pipelines.",
    no_args_is_help=True,
    add_completion=False,
)

_USAGE_ERROR_EXIT_CODE = 2
_REGRESSION_EXIT_CODE = 1


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pipewise {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the pipewise version and exit.",
        ),
    ] = False,
) -> None:
    """pipewise — evaluate multi-step LLM pipelines."""


# ─── inspect (#24) ────────────────────────────────────────────────────────────


@app.command("inspect")
def inspect_cmd(
    run_path: Annotated[Path, typer.Argument(help="Path to a PipelineRun JSON file.")],
    fmt: Annotated[
        str,
        typer.Option("--format", help="Output format: 'text' (default) or 'json'."),
    ] = "text",
    full: Annotated[
        bool,
        typer.Option("--full", help="Show full inputs/outputs without truncation."),
    ] = False,
) -> None:
    """Pretty-print a single PipelineRun JSON file."""
    if not run_path.exists():
        typer.echo(f"Error: file not found: {run_path}", err=True)
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE)

    raw = run_path.read_text(encoding="utf-8")
    try:
        run = PipelineRun.model_validate_json(raw)
    except ValidationError as exc:
        typer.echo(
            f"Error: {run_path} is not a valid PipelineRun:\n{exc}",
            err=True,
        )
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE) from exc

    if fmt == "json":
        typer.echo(run.model_dump_json(indent=2))
    elif fmt == "text":
        typer.echo(format_run(run, full=full))
    else:
        typer.echo(
            f"Error: unknown --format value: {fmt!r}. Use 'text' or 'json'.",
            err=True,
        )
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE)


# ─── eval (#25) ───────────────────────────────────────────────────────────────


@app.command("eval")
def eval_cmd(
    dataset: Annotated[
        Path,
        typer.Option("--dataset", help="Path to a JSONL dataset of pipeline runs."),
    ],
    adapter: Annotated[
        str | None,
        typer.Option(
            "--adapter",
            help="Module path of the adapter (e.g. 'factspark.integrations.pipewise.adapter'). "
            "Required unless --scorers <toml> is supplied.",
        ),
    ] = None,
    scorers_path: Annotated[
        Path | None,
        typer.Option(
            "--scorers",
            help="Optional path to a TOML file overriding adapter-default scorers.",
        ),
    ] = None,
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            help="Directory under which the timestamped report subdirectory is written.",
        ),
    ] = Path("pipewise/reports"),
    dataset_name: Annotated[
        str | None,
        typer.Option(
            "--dataset-name",
            help="Human-readable label snapshotted into the report. "
            "Defaults to the dataset filename stem.",
        ),
    ] = None,
) -> None:
    """Run scorers across a dataset and persist an EvalReport."""
    if adapter is None and scorers_path is None:
        typer.echo(
            "Error: must supply at least one of --adapter or --scorers.",
            err=True,
        )
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE)

    # Resolve scorers — either explicit override or adapter defaults.
    if scorers_path is not None:
        try:
            step_scorers, run_scorers = load_scorer_config(scorers_path)
        except (FileNotFoundError, ScorerConfigError) as exc:
            typer.echo(f"Error loading scorer config: {exc}", err=True)
            raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE) from exc
    else:
        assert adapter is not None  # narrowed by the guard above
        try:
            defaults = resolve_default_scorers(adapter)
        except AdapterError as exc:
            typer.echo(f"Error resolving adapter: {exc}", err=True)
            raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE) from exc
        if defaults is None:
            typer.echo(
                f"Error: adapter '{adapter}' does not expose default_scorers(); "
                "pass --scorers <toml-file> to specify scorers explicitly.",
                err=True,
            )
            raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE)
        step_scorers, run_scorers = defaults

    # Load dataset.
    try:
        runs = list(load_dataset(dataset))
    except (FileNotFoundError, DatasetError) as exc:
        typer.echo(f"Error loading dataset: {exc}", err=True)
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE) from exc

    label = dataset_name if dataset_name is not None else dataset.stem

    report = run_eval(runs, step_scorers, run_scorers, dataset_name=label)
    report_path = write_report(report, output_root=output_root)

    # Summary line.
    total = report.total_score_count()
    passing = report.passing_score_count()
    failing = report.failing_score_count()
    typer.echo(
        f"Evaluated {len(report.runs)} run(s) with "
        f"{len(step_scorers)} step scorer(s) + {len(run_scorers)} run scorer(s)."
    )
    typer.echo(f"Scores: {passing}/{total} passing ({failing} failing).")
    typer.echo(f"Report: {report_path}")

    if failing > 0:
        raise typer.Exit(code=_REGRESSION_EXIT_CODE)


# ─── diff (#26) ───────────────────────────────────────────────────────────────


@app.command("diff")
def diff_cmd(
    report_a: Annotated[Path, typer.Argument(help="Path to the baseline EvalReport JSON.")],
    report_b: Annotated[Path, typer.Argument(help="Path to the comparison EvalReport JSON.")],
    fmt: Annotated[
        str,
        typer.Option("--format", help="Output format: 'text' (default) or 'json'."),
    ] = "text",
) -> None:
    """Diff two EvalReport files. Exits non-zero if there are regressions."""
    a = _load_report(report_a)
    b = _load_report(report_b)

    diff = compute_diff(a, b)

    if fmt == "json":
        typer.echo(diff.model_dump_json(indent=2))
    elif fmt == "text":
        typer.echo(format_diff(diff))
    else:
        typer.echo(
            f"Error: unknown --format value: {fmt!r}. Use 'text' or 'json'.",
            err=True,
        )
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE)

    if diff.has_regressions():
        raise typer.Exit(code=_REGRESSION_EXIT_CODE)


def _load_report(path: Path) -> EvalReport:
    if not path.exists():
        typer.echo(f"Error: file not found: {path}", err=True)
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE)
    try:
        return EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        typer.echo(f"Error: {path} is not a valid EvalReport:\n{exc}", err=True)
        raise typer.Exit(code=_USAGE_ERROR_EXIT_CODE) from exc


if __name__ == "__main__":  # pragma: no cover
    app()
