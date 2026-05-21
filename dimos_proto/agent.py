"""Claude-driven agent loop. Issues tool calls against Go2Sim until `done`."""
from __future__ import annotations

import json
import os
import threading
from typing import Iterator

from anthropic import Anthropic

from .go2_sim import Go2Sim
from .tools import TOOLS, dispatch

MODEL = os.environ.get("DIMOS_MODEL", "claude-sonnet-4-6")
MAX_STEPS = 25

# Pricing (USD per 1M tokens) for Sonnet 4.6 as of late 2025. Used only for
# rough cost telemetry shown to the operator.
PRICE_IN = 3.0 / 1_000_000
PRICE_OUT = 15.0 / 1_000_000

SYSTEM = """You are DimOS-Agent, the brain of a Unitree Go2 quadruped.

You receive natural-language goals from an operator and accomplish them by
calling tools against the robot. Rules:

- Always `perceive` before acting if you lack fresh sensor data.
- Move in small steps (<= 1.0 m) and re-perceive frequently.
- The world has walls; if a move comes back "blocked by wall", turn and try
  an alternate heading. Do not repeat the same blocked move.
- Sensor readings are noisy (~few cm, ~1 deg). Cross-check by perceiving twice
  if a measurement looks off.
- Never move while posture is not 'stand'.
- If `emergency_stop` is true in a perception, do not attempt to move; call
  `done` and explain.
- If battery drops below 15%, route to the dock and `recharge_at_dock`.
- When the goal is satisfied (or cannot be), call `done` with a one-sentence
  summary including any failure reason.
- Keep reasoning text terse. Operators care about actions, not narration.
"""


def run(
    goal: str,
    robot: Go2Sim | None = None,
    cancel: threading.Event | None = None,
) -> Iterator[str]:
    """Yield human-readable trace lines while executing `goal`.

    If `cancel` is set mid-loop, the agent stops at the next step boundary.
    """
    robot = robot or Go2Sim()
    cancel = cancel or threading.Event()
    client = Anthropic()

    messages: list[dict] = [{"role": "user", "content": goal}]
    yield f"GOAL: {goal}"

    in_tok = out_tok = 0

    for step in range(MAX_STEPS):
        if cancel.is_set():
            yield "CANCELLED by operator."
            return

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

        usage = getattr(resp, "usage", None)
        if usage is not None:
            in_tok += getattr(usage, "input_tokens", 0) or 0
            out_tok += getattr(usage, "output_tokens", 0) or 0

        for block in resp.content:
            if block.type == "text" and block.text.strip():
                yield f"  think: {block.text.strip()}"

        if resp.stop_reason != "tool_use":
            yield "agent stopped without calling `done`."
            break

        messages.append({"role": "assistant", "content": resp.content})

        tool_results = []
        finished = False
        final_summary = ""
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if cancel.is_set():
                yield "CANCELLED by operator."
                return
            result = dispatch(robot, block.name, block.input)
            yield f"  -> {block.name}({_fmt_args(block.input)}) = {_fmt_result(result)}"
            if isinstance(result, dict) and result.get("_done"):
                finished = True
                final_summary = result["summary"]
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(
                    result if not (isinstance(result, dict) and "_done" in result)
                    else {"ok": True}
                ),
            })

        if finished:
            yield f"DONE: {final_summary}"
            break

        messages.append({"role": "user", "content": tool_results})
    else:
        yield f"hit MAX_STEPS={MAX_STEPS} without finishing."

    cost = in_tok * PRICE_IN + out_tok * PRICE_OUT
    yield f"USAGE: in={in_tok} out={out_tok} cost=${cost:.4f}"


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _fmt_result(r) -> str:
    if isinstance(r, dict):
        return json.dumps(r, separators=(",", ":"))
    return str(r)
