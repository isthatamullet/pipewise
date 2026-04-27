"""Tests for the pipewise CLI scaffolding (Phase 3 #19).

These tests exercise only the scaffold: `--version`, `--help`, and the three
not-implemented subcommand stubs. The real behavior of inspect/eval/diff is
tested in their own issues (#24/#25/#26).
"""

from __future__ import annotations

from typer.testing import CliRunner

from pipewise import __version__
from pipewise.cli import app

runner = CliRunner()


class TestVersion:
    def test_version_flag_prints_package_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout


class TestHelp:
    def test_help_lists_all_three_subcommands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Typer renders help to stdout; subcommand names appear in the Commands box.
        assert "inspect" in result.stdout
        assert "eval" in result.stdout
        assert "diff" in result.stdout

    def test_no_args_shows_help(self) -> None:
        # `no_args_is_help=True` on the Typer app means bare invocation prints help.
        result = runner.invoke(app, [])
        # Typer exits 2 (usage) when no_args_is_help fires; either way help text shows.
        assert "inspect" in result.stdout
        assert "eval" in result.stdout
        assert "diff" in result.stdout


class TestInspectStub:
    def test_inspect_exits_with_not_implemented_message(self) -> None:
        result = runner.invoke(app, ["inspect", "some_run.json"])
        assert result.exit_code != 0
        # Typer/Click route `err=True` echo to stderr by default.
        combined = result.stdout + (result.stderr if result.stderr is not None else "")
        assert "not implemented" in combined.lower()
        assert "inspect" in combined.lower()


class TestEvalStub:
    def test_eval_exits_with_not_implemented_message(self) -> None:
        result = runner.invoke(
            app,
            ["eval", "--dataset", "golden.jsonl", "--adapter", "factspark.adapter"],
        )
        assert result.exit_code != 0
        combined = result.stdout + (result.stderr if result.stderr is not None else "")
        assert "not implemented" in combined.lower()
        assert "eval" in combined.lower()

    def test_eval_requires_dataset_and_adapter(self) -> None:
        # Sanity: the CLI signature enforces the two required options. Typer
        # surfaces a usage error (exit code 2) when they're missing.
        result = runner.invoke(app, ["eval"])
        assert result.exit_code != 0


class TestDiffStub:
    def test_diff_exits_with_not_implemented_message(self) -> None:
        result = runner.invoke(app, ["diff", "a.json", "b.json"])
        assert result.exit_code != 0
        combined = result.stdout + (result.stderr if result.stderr is not None else "")
        assert "not implemented" in combined.lower()
        assert "diff" in combined.lower()
