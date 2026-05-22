"""Claude-driven agent loop. Issues tool calls against Go2Sim until `done`."""
from __future__ import annotations

import json
import os
import threading
from typing import Iterator

from anthropic import Anthropic

from .go2_sim import Fleet, Go2Sim
from .memory import AgentMemory
from .tools import TOOLS, dispatch

MODEL = os.environ.get("DIMOS_MODEL", "claude-sonnet-4-6")
MAX_STEPS = 25

# Pricing (USD per 1M tokens) for Sonnet 4.6 as of late 2025. Used only for
# rough cost telemetry shown to the operator.
PRICE_IN = 3.0 / 1_000_000
PRICE_OUT = 15.0 / 1_000_000

SYSTEM = """You are DimOS-Agent, the brain coordinating a fleet of Unitree Go2 quadrupeds.

You receive natural-language goals from an operator and accomplish them by
calling tools against one or more robots. Every robot-level tool accepts an
optional `robot_id`; omit it to target the primary inspector. Use
`list_fleet` to see what robots are available.

Rules:

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
- You have persistent memory across missions: `remember(key, value)` to save
  discoveries (e.g. an object's last-known position), `recall(query)` to
  retrieve them. At the start of a mission, prior memories are injected for
  you; use them to skip rediscovery, but verify before trusting old positions.
- For warehouse inspection: the current manifest and zone bounds are injected
  at mission start. Walk the zones, perceive what's actually there, and call
  `report_discrepancy(name, kind, note)` for each mismatch. Use `say` to
  speak a final summary to the operator before calling `done`.
- When more than one robot is available, split the work: send go2-1 to one
  zone and go2-2 to another, then aggregate findings. You can call multiple
  tools (with different `robot_id`s) in a single response to act in parallel.
- When the goal is satisfied (or cannot be), call `done` with a one-sentence
  summary including any failure reason.
- Keep reasoning text terse. Operators care about actions, not narration.
"""


def run(
    goal: str,
    target: Fleet | Go2Sim | None = None,
    cancel: threading.Event | None = None,
    memory: AgentMemory | None = None,
) -> Iterator[str]:
    """Yield human-readable trace lines while executing `goal`.

    `target` may be a single Go2Sim (backwards-compatible) or a Fleet. If
    `cancel` is set mid-loop, the agent stops at the next step boundary.
    """
    if target is None:
        target = Fleet.default()
    if isinstance(target, Go2Sim):
        # wrap in a one-robot fleet so the rest of the loop is uniform
        f = Fleet()
        f.robots["go2-1"] = target
        target = f
    fleet: Fleet = target
    robot = fleet.get(None)  # primary, for preamble facts
    cancel = cancel or threading.Event()
    memory = memory or AgentMemory()
    client = Anthropic()

    prior = memory.all()
    parts: list[str] = []
    if len(fleet.robots) > 1:
        roster = ", ".join(fleet.robots.keys())
        parts.append(f"Fleet roster: {roster}. Primary is '{fleet.primary_id}'.")
    if robot.manifest:
        manifest_lines = [f"  {m['name']} -> zone {m['zone']}" for m in robot.manifest]
        zone_lines = [f"  {z}: x in [{x1},{x2}], y in [{y1},{y2}]"
                      for z, (x1, y1, x2, y2) in robot.zones.items()]
        parts.append(
            "Warehouse manifest (expected):\n" + "\n".join(manifest_lines)
            + "\nZones:\n" + "\n".join(zone_lines)
        )
    if prior:
        parts.append("Prior memory (verify before relying on positional facts):\n"
                     + "\n".join(f"  {k} = {v}" for k, v in prior.items()))
    preamble = ("\n\n".join(parts) + "\n\n") if parts else ""
    messages: list[dict] = [{"role": "user", "content": preamble + "Goal: " + goal}]
    yield f"GOAL: {goal}"
    if len(fleet.robots) > 1:
        yield f"  fleet: {len(fleet.robots)} robot(s) — {', '.join(fleet.robots.keys())}"
    if robot.manifest:
        yield f"  manifest: {len(robot.manifest)} expected item(s) across {len(robot.zones)} zone(s)"
    if prior:
        yield f"  memory: loaded {len(prior)} fact(s)"

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
            result = dispatch(fleet, block.name, block.input, memory)
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
