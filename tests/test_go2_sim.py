"""Sim physics + safety tests. Run with: pytest -q tests/"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

# avoid touching the real log on disk during tests
os.environ.setdefault("DIMOS_LOG", "/tmp/dimos_test_missions.jsonl")

from dimos_proto.go2_sim import Fleet, Go2Sim, WorldObject
from dimos_proto.memory import AgentMemory
from dimos_proto.tools import dispatch


@pytest.fixture
def robot(tmp_path: Path) -> Go2Sim:
    r = Go2Sim()
    r.log_path = tmp_path / "missions.jsonl"
    r.sensor_noise_m = 0.0
    r.sensor_noise_deg = 0.0
    # normalize to origin facing +x for legacy motion/perception tests
    r.x, r.y, r.heading_deg = 0.0, 0.0, 0.0
    # ensure alice is in front of the robot for perception test
    for o in r.world:
        if o.name == "alice":
            o.x, o.y = 3.0, 0.5
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
    # Wall at y=-1 from x=-1.5 to x=1.5 occludes anything beyond it from origin.
    robot.world.append(WorldObject("hidden", 0.0, -3.0, "ball"))
    robot.turn(-90)  # face -y
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


def test_zone_assignment(robot: Go2Sim) -> None:
    assert robot.zone_of(-3.0, 3.0) == "A"
    assert robot.zone_of(2.0, 3.0) == "B"
    assert robot.zone_of(0.0, -3.0) == "C"
    assert robot.zone_of(10.0, 10.0) is None


def test_perceive_includes_zone(robot: Go2Sim) -> None:
    seen = {o["name"]: o["zone"] for o in robot.perceive()["visible"]}
    for name, zone in seen.items():
        assert zone in ("A", "B", "C", None)


def test_report_discrepancy_logs(robot: Go2Sim) -> None:
    out = robot.report_discrepancy("chair_3", "missing", "expected in zone A")
    assert "missing" in out
    assert robot.discrepancies[0]["name"] == "chair_3"
    assert robot.discrepancies[0]["kind"] == "missing"


def test_seed_world_has_known_gap(robot: Go2Sim) -> None:
    names_in_world = {o.name for o in robot.world}
    manifest_names = {m["name"] for m in robot.manifest}
    assert "chair_3" in manifest_names and "chair_3" not in names_in_world
    assert "rogue_box" in names_in_world and "rogue_box" not in manifest_names


def test_fleet_shares_world() -> None:
    f = Fleet.default()
    assert set(f.robots.keys()) == {"go2-1", "go2-2"}
    # mutating manifest via one robot is visible via the other
    f.robots["go2-1"].manifest.append({"name": "extra_item", "zone": "C"})
    assert any(m["name"] == "extra_item" for m in f.robots["go2-2"].manifest)


def test_fleet_summary_shape() -> None:
    f = Fleet.default()
    s = f.summary()
    assert len(s) == 2
    for entry in s:
        assert {"id", "pose", "battery", "posture", "emergency_stop", "zone"} <= entry.keys()


def test_dispatch_targets_robot_by_id() -> None:
    f = Fleet.default()
    out = dispatch(f, "turn", {"degrees": 45, "robot_id": "go2-2"})
    assert "heading" in out
    assert f.robots["go2-2"].heading_deg == pytest.approx((90.0 + 45.0) % 360.0)
    assert f.robots["go2-1"].heading_deg == pytest.approx(90.0)  # untouched


def test_dispatch_list_fleet() -> None:
    f = Fleet.default()
    out = dispatch(f, "list_fleet", {})
    assert isinstance(out, list) and len(out) == 2
    assert {r["id"] for r in out} == {"go2-1", "go2-2"}


def test_vision_renders_png_or_skips() -> None:
    from dimos_proto.vision import render_top_down, _HAS_PIL
    r = Go2Sim()
    out = render_top_down(r)
    if _HAS_PIL:
        assert isinstance(out, str) and len(out) > 500  # base64 PNG
        # validate it really is PNG bytes
        import base64
        assert base64.b64decode(out)[:8] == b"\x89PNG\r\n\x1a\n"
    else:
        assert out is None


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
