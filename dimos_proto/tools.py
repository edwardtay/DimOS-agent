"""Tool schema + dispatch for the Claude agent driving Go2Sim."""
from __future__ import annotations

from .go2_sim import Go2Sim

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
        "name": "done",
        "description": "Call when the user's request is fully satisfied. Provide a short summary.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


def dispatch(robot: Go2Sim, name: str, args: dict):
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
    if name == "done":
        return {"_done": True, "summary": args["summary"]}
    return f"unknown tool: {name}"
