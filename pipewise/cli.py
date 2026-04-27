"""pipewise CLI entry point.

Phase 3 scaffolding: this module exposes a `typer.Typer` app with the three
subcommand stubs (`inspect`, `eval`, `diff`). Each subcommand exits with a
clear "not implemented yet" message until its own issue lands.
"""

from __future__ import annotations

import typer

from pipewise import __version__

app = typer.Typer(
    name="pipewise",
    help="Evaluation framework for multi-step LLM pipelines.",
    no_args_is_help=True,
    add_completion=False,
)

_NOT_IMPLEMENTED_EXIT_CODE = 2


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pipewise {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the pipewise version and exit.",
    ),
) -> None:
    """pipewise — evaluate multi-step LLM pipelines."""


@app.command("inspect")
def inspect_cmd(
    run_path: str = typer.Argument(..., help="Path to a PipelineRun JSON file."),
) -> None:
    """Pretty-print a single PipelineRun JSON file. (Phase 3 #24.)"""
    typer.echo("pipewise inspect: not implemented yet (Phase 3 #24).", err=True)
    raise typer.Exit(code=_NOT_IMPLEMENTED_EXIT_CODE)


@app.command("eval")
def eval_cmd(
    dataset: str = typer.Option(..., "--dataset", help="Path to a JSONL dataset of pipeline runs."),
    adapter: str = typer.Option(..., "--adapter", help="Module path of the adapter."),
    scorers: str | None = typer.Option(
        None,
        "--scorers",
        help="Optional path to a TOML file overriding adapter-default scorers.",
    ),
) -> None:
    """Run scorers across a dataset and write an EvalReport. (Phase 3 #25.)"""
    typer.echo("pipewise eval: not implemented yet (Phase 3 #25).", err=True)
    raise typer.Exit(code=_NOT_IMPLEMENTED_EXIT_CODE)


@app.command("diff")
def diff_cmd(
    report_a: str = typer.Argument(..., help="Path to the baseline EvalReport JSON."),
    report_b: str = typer.Argument(..., help="Path to the comparison EvalReport JSON."),
) -> None:
    """Diff two EvalReport files. (Phase 3 #26.)"""
    typer.echo("pipewise diff: not implemented yet (Phase 3 #26).", err=True)
    raise typer.Exit(code=_NOT_IMPLEMENTED_EXIT_CODE)


if __name__ == "__main__":  # pragma: no cover
    app()
