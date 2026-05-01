"""Capture sample LangGraph runs into ``runs/`` for the reference adapter.

Adopters run this once to (re)generate the committed golden runs. CI does not
invoke this script — captured runs are static artifacts.

Usage::

    GOOGLE_API_KEY=... uv run python capture_runs.py

To swap LLM providers, edit ``_build_model`` below — the adapter is provider
agnostic; only this capture script needs to know which SDK to call.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from pipewise_langgraph.capture import capture_run, write_run
from pipewise_langgraph.graph import build_react_agent

MODEL_NAME = "gemini-3.1-pro-preview"
PROVIDER = "google"

CAPTURES: list[dict[str, Any]] = [
    {
        "run_id": "golden-001-iteration",
        "pipeline_name": "langgraph-react-agent",
        "user_message": ("What is 47 * 23 + 100? Then tell me the capital of France."),
    },
    {
        "run_id": "golden-002-skipped",
        "pipeline_name": "langgraph-react-agent",
        "user_message": "Hello! What can you help with?",
    },
]


def _build_model() -> ChatGoogleGenerativeAI:
    if "GOOGLE_API_KEY" not in os.environ:
        print("error: GOOGLE_API_KEY env var not set", file=sys.stderr)
        sys.exit(1)
    return ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)


def main() -> None:
    model = _build_model()
    graph = build_react_agent(model)
    runs_dir = Path(__file__).parent / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    captured_runs = []
    for cfg in CAPTURES:
        print(f"=== Capturing {cfg['run_id']} ===")
        run = capture_run(
            graph,
            {"messages": [{"role": "user", "content": cfg["user_message"]}]},
            run_id=cfg["run_id"],
            pipeline_name=cfg["pipeline_name"],
            model=MODEL_NAME,
            provider=PROVIDER,
        )
        out_path = write_run(run, runs_dir)
        captured_runs.append(run)
        print(f"  wrote {out_path}")
        print(
            f"  steps: {len(run.steps)} | tokens: in={run.total_input_tokens} out={run.total_output_tokens}"
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
