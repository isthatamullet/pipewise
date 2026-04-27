"""Smoke tests for the CLI scaffolding (Phase 3 #19).

Behavior of inspect/eval/diff is tested in their own files alongside the
runner modules they delegate to. These tests just pin the top-level CLI
shape: --version, --help, and that the three subcommands are registered.
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
        assert "inspect" in result.stdout
        assert "eval" in result.stdout
        assert "diff" in result.stdout

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert "inspect" in result.stdout
        assert "eval" in result.stdout
        assert "diff" in result.stdout
