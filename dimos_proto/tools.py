"""Tool schema + dispatch for the Claude agent driving a Fleet of Go2s."""
from __future__ import annotations

from .go2_sim import Fleet, Go2Sim
from .memory import AgentMemory

_RID = {"type": "string",
        "description": "Robot id to target. Defaults to the primary inspector if omitted."}

TOOLS = [
    {
        "name": "list_fleet",
        "description": "List every robot in the fleet with its current pose, battery, posture, and zone.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "move",
        "description": "Walk forward (positive) or backward (negative) along current heading, in meters.",
        "input_schema": {
            "type": "object",
            "properties": {"distance_m": {"type": "number"}, "robot_id": _RID},
            "required": ["distance_m"],
        },
    },
    {
        "name": "turn",
        "description": "Rotate in place. Positive = counter-clockwise, in degrees.",
        "input_schema": {
            "type": "object",
            "properties": {"degrees": {"type": "number"}, "robot_id": _RID},
            "required": ["degrees"],
        },
    },
    {
        "name": "set_posture",
        "description": "Set body posture: 'stand', 'sit', or 'lie'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "posture": {"type": "string", "enum": ["stand", "sit", "lie"]},
                "robot_id": _RID,
            },
            "required": ["posture"],
        },
    },
    {
        "name": "perceive",
        "description": "Return pose, battery, posture, zone, and objects visible in the 90deg / 5m FOV.",
        "input_schema": {
            "type": "object",
            "properties": {"robot_id": _RID},
        },
    },
    {
        "name": "say",
        "description": "Speak text out loud over the robot's speaker.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "robot_id": _RID},
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
        "input_schema": {
            "type": "object",
            "properties": {"robot_id": _RID},
        },
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


def dispatch(target: Fleet | Go2Sim, name: str, args: dict,
             memory: AgentMemory | None = None):
    """Resolve robot from `args.robot_id` if `target` is a Fleet."""
    if isinstance(target, Fleet):
        fleet = target
        rid = args.get("robot_id")
        if name == "list_fleet":
            return fleet.summary()
        robot = fleet.get(rid)
    else:
        fleet = None
        robot = target
        if name == "list_fleet":
            return [{"id": "go2-1", **{
                "pose": {"x": robot.x, "y": robot.y, "heading_deg": robot.heading_deg},
                "battery": robot.battery, "posture": robot.posture,
                "emergency_stop": robot.emergency_stop,
            }}]

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
