"""Tool schema + dispatch for the Claude agent driving Go2Sim."""
from __future__ import annotations

from .go2_sim import Go2Sim
from .memory import AgentMemory

TOOLS = [
    {
        "name": "move",
        "description": "Walk forward (positive) or backward (negative) along current heading, in meters.",
        "input_schema": {
            "type": "object",
            "properties": {"distance_m": {"type": "number"}},
            "required": ["distance_m"],
        },
    },
    {
        "name": "turn",
        "description": "Rotate in place. Positive = counter-clockwise, in degrees.",
        "input_schema": {
            "type": "object",
            "properties": {"degrees": {"type": "number"}},
            "required": ["degrees"],
        },
    },
    {
        "name": "set_posture",
        "description": "Set body posture: 'stand', 'sit', or 'lie'.",
        "input_schema": {
            "type": "object",
            "properties": {"posture": {"type": "string", "enum": ["stand", "sit", "lie"]}},
            "required": ["posture"],
        },
    },
    {
        "name": "perceive",
        "description": "Return current pose, battery, posture, and objects visible in the 90deg / 5m field of view.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "say",
        "description": "Speak text out loud over the robot's speaker.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "remember",
        "description": "Persist a fact across missions (e.g. 'alice_last_seen' -> '(3.1, 0.4) at 14:22').",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall",
        "description": "Retrieve previously-remembered facts. Pass an optional substring to filter.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    },
    {
        "name": "forget",
        "description": "Delete a remembered fact by key.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "report_discrepancy",
        "description": (
            "Flag a manifest mismatch found during an inspection. "
            "kind='missing' (expected but not seen), 'extra' (seen but not on manifest), "
            "or 'wrong_zone' (seen but in the wrong zone)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": ["missing", "extra", "wrong_zone"]},
                "note": {"type": "string"},
            },
            "required": ["name", "kind"],
        },
    },
    {
        "name": "recharge_at_dock",
        "description": "If the robot is within 0.6m of the charging dock, recharge to 100%. Otherwise refuses.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "done",
        "description": "Call when the user's request is fully satisfied. Provide a short summary.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


def dispatch(robot: Go2Sim, name: str, args: dict, memory: AgentMemory | None = None):
    if name == "move":
        return robot.move(float(args["distance_m"]))
    if name == "turn":
        return robot.turn(float(args["degrees"]))
    if name == "set_posture":
        return robot.set_posture(args["posture"])
    if name == "perceive":
        return robot.perceive()
    if name == "say":
        return robot.say(args["text"])
    if name == "recharge_at_dock":
        return robot.recharge_at_dock()
    if name == "report_discrepancy":
        return robot.report_discrepancy(
            args["name"], args["kind"], args.get("note", ""))
    if name == "remember":
        return (memory or AgentMemory()).remember(args["key"], args["value"])
    if name == "recall":
        return (memory or AgentMemory()).recall(args.get("query", ""))
    if name == "forget":
        return (memory or AgentMemory()).forget(args["key"])
    if name == "done":
        return {"_done": True, "summary": args["summary"]}
    return f"unknown tool: {name}"
