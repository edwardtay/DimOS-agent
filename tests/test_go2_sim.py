"""Sim physics + safety tests. Run with: pytest -q tests/"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

# avoid touching the real log on disk during tests
os.environ.setdefault("DIMOS_LOG", "/tmp/dimos_test_missions.jsonl")

from dimos_proto.go2_sim import Go2Sim, WorldObject
from dimos_proto.memory import AgentMemory


@pytest.fixture
def robot(tmp_path: Path) -> Go2Sim:
    r = Go2Sim()
    r.log_path = tmp_path / "missions.jsonl"
    # deterministic perception for tests
    r.sensor_noise_m = 0.0
    r.sensor_noise_deg = 0.0
    return r


def test_move_advances_pose(robot: Go2Sim) -> None:
    out = robot.move(1.0)
    assert "moved" in out
    assert robot.x == pytest.approx(1.0)
    assert robot.y == pytest.approx(0.0)


def test_move_blocked_by_wall(robot: Go2Sim) -> None:
    # Eastern wall is at x=4.5. From x=0 heading 0, a 6m walk must be blocked.
    out = robot.move(6.0)
    assert "blocked" in out
    assert robot.x < 4.5  # stopped short of wall


def test_estop_refuses_motion(robot: Go2Sim) -> None:
    robot.set_emergency_stop(True)
    out = robot.move(1.0)
    assert "refused" in out
    assert robot.x == 0.0


def test_estop_collapses_posture(robot: Go2Sim) -> None:
    assert robot.posture == "stand"
    robot.set_emergency_stop(True)
    assert robot.posture == "sit"


def test_battery_floor(robot: Go2Sim) -> None:
    robot.battery = 4.0
    out = robot.move(0.5)
    assert "battery_too_low" in out


def test_cannot_move_while_sitting(robot: Go2Sim) -> None:
    robot.set_posture("sit")
    out = robot.move(0.5)
    assert "posture_not_stand" in out


def test_perceive_sees_alice_forward(robot: Go2Sim) -> None:
    seen = robot.perceive()["visible"]
    names = {o["name"] for o in seen}
    assert "alice" in names  # alice at (3, 0.5), within FOV from origin


def test_perceive_occluded_by_wall(robot: Go2Sim) -> None:
    # Put a target behind a wall. The partial wall at x=1.0 from y=1.5..4.5
    # occludes (1.5, 3.0) from the origin facing +x with heading 0... actually
    # bearing to (1.5,3.0) is ~63deg which is outside 45deg FOV. Aim there.
    robot.world.append(WorldObject("hidden", 1.5, 3.0, "ball"))
    robot.turn(63)  # aim toward hidden
    visible = {o["name"] for o in robot.perceive()["visible"]}
    assert "hidden" not in visible


def test_recharge_requires_dock_proximity(robot: Go2Sim) -> None:
    out = robot.recharge_at_dock()
    assert "not_at_dock" in out
    # teleport next to dock
    dock = next(o for o in robot.world if o.tag == "dock")
    robot.x, robot.y = dock.x + 0.3, dock.y
    robot.battery = 20.0
    out = robot.recharge_at_dock()
    assert robot.battery == 100.0


def test_memory_roundtrip(tmp_path: Path) -> None:
    m = AgentMemory(tmp_path / "mem.json")
    m.remember("alice_seen", "(3, 0.5)")
    m.remember("notes", "she likes the chair")
    # new instance, same file
    m2 = AgentMemory(tmp_path / "mem.json")
    assert m2.recall("alice") == {"alice_seen": "(3, 0.5)"}
    assert m2.recall() == {"alice_seen": "(3, 0.5)", "notes": "she likes the chair"}
    m2.forget("alice_seen")
    assert "alice_seen" not in AgentMemory(tmp_path / "mem.json").all()
