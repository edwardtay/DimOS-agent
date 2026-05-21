"""Unitree Go2 simulator stand-in for the DimOS SDK.

Tracks pose on a 2D world that includes axis-aligned wall segments, enforces
collision and battery limits, supports an emergency stop, and appends every
event to a JSONL mission log.
"""
from __future__ import annotations

import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class WorldObject:
    name: str
    x: float
    y: float
    tag: str  # "person" | "ball" | "chair" | "dock"


# Wall as ((x1,y1),(x2,y2)) line segment.
Wall = tuple[tuple[float, float], tuple[float, float]]


def _seg_seg_intersect(a1, a2, b1, b2) -> bool:
    """Return True if segment a1-a2 intersects b1-b2."""
    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) > (q[1] - p[1]) * (r[0] - p[0])
    return ccw(a1, b1, b2) != ccw(a2, b1, b2) and ccw(a1, a2, b1) != ccw(a1, a2, b2)


def _point_seg_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


@dataclass
class Go2Sim:
    x: float = 0.0
    y: float = 0.0
    heading_deg: float = 0.0
    battery: float = 100.0
    posture: Literal["stand", "sit", "lie"] = "stand"
    emergency_stop: bool = False
    radius: float = 0.30  # Go2 footprint, meters
    min_battery: float = 5.0
    sensor_noise_m: float = 0.04
    sensor_noise_deg: float = 1.5

    world: list[WorldObject] = field(default_factory=lambda: [
        WorldObject("alice", 3.0, 0.5, "person"),
        WorldObject("red_ball", 1.5, -1.0, "ball"),
        WorldObject("chair_1", -2.0, 2.0, "chair"),
        WorldObject("dock", -4.0, -3.5, "dock"),
    ])
    obstacles: list[Wall] = field(default_factory=lambda: [
        # Room outline (8m x 8m)
        ((-4.5, -4.5), (4.5, -4.5)),
        ((4.5, -4.5), (4.5, 4.5)),
        ((4.5, 4.5), (-4.5, 4.5)),
        ((-4.5, 4.5), (-4.5, -4.5)),
        # Interior partial walls
        ((1.0, 1.5), (1.0, 4.5)),
        ((-1.5, -1.0), (1.5, -1.0)),
    ])
    log: list[dict] = field(default_factory=list)
    log_path: Path = field(default_factory=lambda: Path(
        os.environ.get("DIMOS_LOG", "missions.jsonl")))
    session_id: str = field(default_factory=lambda: time.strftime("%Y%m%dT%H%M%S"))

    # ---------- logging ----------
    def _record(self, event: str, **fields) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session": self.session_id,
            "event": event,
            "pose": {"x": round(self.x, 3), "y": round(self.y, 3),
                     "heading_deg": round(self.heading_deg, 1)},
            "battery": round(self.battery, 1),
            **fields,
        }
        self.log.append(entry)
        try:
            with self.log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # best-effort

    # ---------- safety / state ----------
    def set_emergency_stop(self, active: bool) -> str:
        self.emergency_stop = active
        if active and self.posture == "stand":
            # collapse to a safer posture on e-stop
            self.posture = "sit"
        self._record("estop", active=active)
        return f"emergency_stop={active}"

    def _refuse(self, reason: str, **fields) -> str:
        self._record("refused", reason=reason, **fields)
        return f"refused: {reason}"

    # ---------- collision ----------
    def _collides(self, x: float, y: float) -> Wall | None:
        for (p, q) in self.obstacles:
            if _point_seg_dist(x, y, p[0], p[1], q[0], q[1]) < self.radius:
                return (p, q)
        return None

    def _path_blocked(self, x1, y1, x2, y2) -> Wall | None:
        # Use a few sample points along the path to find an obstacle.
        steps = max(4, int(math.hypot(x2 - x1, y2 - y1) / 0.05))
        for i in range(1, steps + 1):
            t = i / steps
            hit = self._collides(x1 + t * (x2 - x1), y1 + t * (y2 - y1))
            if hit:
                return hit
        return None

    # ---------- actions ----------
    def move(self, distance_m: float) -> str:
        if self.emergency_stop:
            return self._refuse("emergency_stop_active")
        if self.posture != "stand":
            return self._refuse("posture_not_stand", posture=self.posture)
        if self.battery < self.min_battery:
            return self._refuse("battery_too_low", battery=self.battery)

        rad = math.radians(self.heading_deg)
        tx = self.x + distance_m * math.cos(rad)
        ty = self.y + distance_m * math.sin(rad)
        blocked = self._path_blocked(self.x, self.y, tx, ty)
        if blocked:
            # Stop just shy of the obstacle.
            steps = max(4, int(abs(distance_m) / 0.05))
            stop_at = None
            for i in range(1, steps + 1):
                t = i / steps
                px = self.x + t * (tx - self.x)
                py = self.y + t * (ty - self.y)
                if self._collides(px, py):
                    break
                stop_at = (px, py)
            if stop_at:
                self.x, self.y = stop_at
                self.battery -= abs(distance_m) * 0.4
                self._record("move_blocked", requested=distance_m,
                             stopped_at={"x": self.x, "y": self.y})
                return (f"blocked by wall; stopped at "
                        f"({self.x:.2f}, {self.y:.2f})")
            return self._refuse("immediate_collision")

        self.x, self.y = tx, ty
        self.battery -= abs(distance_m) * 0.4
        self._record("move", distance_m=distance_m)
        return f"moved to ({self.x:.2f}, {self.y:.2f})"

    def turn(self, degrees: float) -> str:
        if self.emergency_stop:
            return self._refuse("emergency_stop_active")
        if self.battery < self.min_battery:
            return self._refuse("battery_too_low", battery=self.battery)
        self.heading_deg = (self.heading_deg + degrees) % 360
        self.battery -= abs(degrees) * 0.01
        self._record("turn", degrees=degrees)
        return f"heading now {self.heading_deg:.0f} deg"

    def set_posture(self, posture: str) -> str:
        if posture not in ("stand", "sit", "lie"):
            return self._refuse("unknown_posture", posture=posture)
        if self.emergency_stop and posture == "stand":
            return self._refuse("emergency_stop_active")
        self.posture = posture  # type: ignore[assignment]
        self._record("posture", posture=posture)
        return f"posture set to {posture}"

    def perceive(self) -> dict:
        rad = math.radians(self.heading_deg)
        fx, fy = math.cos(rad), math.sin(rad)
        seen = []
        for obj in self.world:
            dx, dy = obj.x - self.x, obj.y - self.y
            dist = math.hypot(dx, dy)
            if dist > 5.0 or dist < 1e-6:
                continue
            cos_angle = (dx * fx + dy * fy) / dist
            if cos_angle < math.cos(math.radians(45)):
                continue
            # Occlusion check: any wall between robot and object?
            occluded = False
            for (p, q) in self.obstacles:
                if _seg_seg_intersect((self.x, self.y), (obj.x, obj.y), p, q):
                    occluded = True
                    break
            if occluded:
                continue
            bearing = math.degrees(math.atan2(dy, dx)) - self.heading_deg
            bearing = (bearing + 180) % 360 - 180
            seen.append({
                "name": obj.name,
                "tag": obj.tag,
                "distance_m": round(dist + random.gauss(0, self.sensor_noise_m), 2),
                "bearing_deg": round(bearing + random.gauss(0, self.sensor_noise_deg), 1),
            })
        result = {
            "pose": {"x": round(self.x, 2), "y": round(self.y, 2),
                     "heading_deg": round(self.heading_deg, 1)},
            "battery": round(self.battery, 1),
            "posture": self.posture,
            "emergency_stop": self.emergency_stop,
            "visible": seen,
        }
        self._record("perceive", count=len(seen))
        return result

    def say(self, text: str) -> str:
        self._record("say", text=text)
        return "spoken"

    # ---------- operator-only world edits ----------
    def place_object(self, name: str, x: float, y: float) -> None:
        for o in self.world:
            if o.name == name:
                o.x, o.y = x, y
                self._record("world_edit_move", name=name, x=x, y=y)
                return
        # treat as add
        self.world.append(WorldObject(name=name, x=x, y=y, tag="ball"))
        self._record("world_edit_add", name=name, x=x, y=y)

    def recharge_at_dock(self) -> str:
        for o in self.world:
            if o.tag == "dock" and math.hypot(o.x - self.x, o.y - self.y) < 0.6:
                self.battery = 100.0
                self._record("recharge", battery=100.0)
                return "battery recharged to 100%"
        return self._refuse("not_at_dock")
