"""CLI entry point for pipewise.ci — `python -m pipewise.ci`.

Used by the pipewise-eval GitHub Action (`.github/actions/pipewise-eval/`)
to render an `EvalReport` (plus optional baseline) into the sticky-comment
markdown that gets posted on a PR. Kept as a tiny argparse wrapper around
`render_pr_comment` so adapters and CI integrations don't need to write
any Python — they just shell out to this entry point.

The "shell out to a CLI" pattern is intentional: it keeps the action's
shell-side logic minimal (one `python -m` invocation), keeps the Python
side fully unit-testable, and avoids embedding Python inside YAML where
quoting bugs hide.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipewise.ci import render_pr_comment
from pipewise.core.report import EvalReport


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipewise.ci",
        description=("Render a pipewise EvalReport as markdown for a GitHub PR comment."),
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to the EvalReport JSON for this PR's pipeline run.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=(
            "Path to the baseline EvalReport JSON (typically the most recent "
            "report from main). If the path is omitted OR the file does not "
            "exist, the rendered comment shows absolute values with no Δ "
            "column. Silent fallback is intentional — baseline artifacts may "
            "be missing on the first PR for a new repo or after retention "
            "expires; the action should still produce a useful comment."
        ),
    )
    parser.add_argument(
        "--adapter-name",
        required=True,
        help=(
            "Adapter package name. Used as the sticky-comment marker key so "
            "multi-adapter repos can post one comment per adapter."
        ),
    )
    parser.add_argument(
        "--short-sha",
        required=True,
        help="Short Git SHA of the commit this report was generated for.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path where the rendered markdown will be written (UTF-8).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    report = EvalReport.model_validate_json(args.report.read_text(encoding="utf-8"))

    baseline: EvalReport | None = None
    if args.baseline is not None and args.baseline.exists():
        baseline = EvalReport.model_validate_json(args.baseline.read_text(encoding="utf-8"))

    markdown = render_pr_comment(
        report,
        adapter_name=args.adapter_name,
        short_sha=args.short_sha,
        baseline=baseline,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
