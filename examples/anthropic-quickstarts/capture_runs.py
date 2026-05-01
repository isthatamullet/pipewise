"""Capture sample agent runs into ``runs/`` for the reference adapter.

Adopters run this once to (re)generate the committed golden runs. CI does not
invoke this script — captured runs are static artifacts.

Usage::

    ANTHROPIC_API_KEY=... uv run python capture_runs.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from pipewise_anthropic_quickstarts.capture import capture_run, write_run
from pipewise_anthropic_quickstarts.tools import TOOL_EXECUTORS, TOOL_SCHEMAS

MODEL_NAME = "claude-haiku-4-5-20251001"
SYSTEM_PROMPT = (
    "You are a helpful assistant with access to a calculator and a country-info "
    "lookup tool. Use the tools when they are useful, and reply directly when "
    "they aren't."
)

CAPTURES: list[dict[str, Any]] = [
    {
        "run_id": "golden-001-iteration",
        "pipeline_name": "anthropic-agent-react",
        "user_input": ("What is 47 * 23 + 100? Then tell me the capital of France."),
    },
    {
        "run_id": "golden-002-skipped",
        "pipeline_name": "anthropic-agent-react",
        "user_input": "Hello! What can you help with?",
    },
]


def main() -> None:
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("error: ANTHROPIC_API_KEY env var not set", file=sys.stderr)
        sys.exit(1)
    client = Anthropic()
    runs_dir = Path(__file__).parent / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    captured_runs = []
    for cfg in CAPTURES:
        print(f"=== Capturing {cfg['run_id']} ===")
        run = capture_run(
            client,
            cfg["user_input"],
            run_id=cfg["run_id"],
            pipeline_name=cfg["pipeline_name"],
            system=SYSTEM_PROMPT,
            tool_schemas=TOOL_SCHEMAS,
            tool_executors=TOOL_EXECUTORS,
            model=MODEL_NAME,
        )
        out_path = write_run(run, runs_dir)
        captured_runs.append(run)
        print(f"  wrote {out_path}")
        print(
            f"  steps: {len(run.steps)} | tokens: in={run.total_input_tokens} "
            f"out={run.total_output_tokens} | cost: ${run.total_cost_usd:.5f}"
            if run.total_cost_usd is not None
            else f"  steps: {len(run.steps)} | tokens: in={run.total_input_tokens} out={run.total_output_tokens}"
        )
        for step in run.steps:
            print(f"    [{step.status:9s}] {step.step_id}")

    dataset_path = runs_dir / "dataset.jsonl"
    with dataset_path.open("w", encoding="utf-8") as f:
        for run in captured_runs:
            f.write(run.model_dump_json() + "\n")
    print(f"=== Wrote dataset {dataset_path} ({len(captured_runs)} runs) ===")


if __name__ == "__main__":
    main()
