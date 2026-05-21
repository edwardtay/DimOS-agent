"""Claude-driven agent loop. Issues tool calls against Go2Sim until `done`."""
from __future__ import annotations

import json
import os
from typing import Iterator

from anthropic import Anthropic

from .go2_sim import Go2Sim
from .tools import TOOLS, dispatch

MODEL = os.environ.get("DIMOS_MODEL", "claude-sonnet-4-6")
MAX_STEPS = 20

SYSTEM = """You are DimOS-Agent, the brain of a Unitree Go2 quadruped.

You receive natural-language goals from an operator and accomplish them by
calling tools to perceive the environment and actuate the robot. Rules:

- Always `perceive` before acting on the world if you lack fresh info.
- Move in small steps (<=1.0m) and re-perceive frequently.
- Never move while posture is not 'stand'.
- When the goal is satisfied, call `done` with a one-sentence summary.
- Be terse in your reasoning text; the operator only sees actions + final summary.
"""


def run(goal: str, robot: Go2Sim | None = None) -> Iterator[str]:
    """Yield human-readable trace lines while executing `goal`."""
    robot = robot or Go2Sim()
    client = Anthropic()

    messages: list[dict] = [{"role": "user", "content": goal}]
    yield f"GOAL: {goal}"

    for step in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=[{
                "type": "text",
                "text": SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=TOOLS,
            messages=messages,
        )

        # Surface any thinking text
        for block in resp.content:
            if block.type == "text" and block.text.strip():
                yield f"  think: {block.text.strip()}"

        if resp.stop_reason != "tool_use":
            yield "agent stopped without calling `done`."
            return

        messages.append({"role": "assistant", "content": resp.content})

        tool_results = []
        finished = False
        final_summary = ""
        for block in resp.content:
            if block.type != "tool_use":
                continue
            result = dispatch(robot, block.name, block.input)
            yield f"  -> {block.name}({_fmt_args(block.input)}) = {_fmt_result(result)}"
            if isinstance(result, dict) and result.get("_done"):
                finished = True
                final_summary = result["summary"]
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result if not isinstance(result, dict) or "_done" not in result else {"ok": True}),
            })

        if finished:
            yield f"DONE: {final_summary}"
            return

        messages.append({"role": "user", "content": tool_results})

    yield f"hit MAX_STEPS={MAX_STEPS} without finishing."


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _fmt_result(r) -> str:
    if isinstance(r, dict):
        return json.dumps(r, separators=(",", ":"))
    return str(r)
