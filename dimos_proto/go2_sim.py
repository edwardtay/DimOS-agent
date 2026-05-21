"""Minimal Unitree Go2 simulator standing in for the DimOS SDK.

Tracks pose on a 2D grid, holds a tiny scripted world of objects the robot
can "see," and logs every action so the agent's behavior is auditable.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class WorldObject:
    name: str
    x: float
    y: float
    tag: str  # e.g. "person", "ball", "chair"


@dataclass
class Go2Sim:
    x: float = 0.0
    y: float = 0.0
    heading_deg: float = 0.0  # 0 = +x, 90 = +y
    battery: float = 100.0
    posture: Literal["stand", "sit", "lie"] = "stand"
    world: list[WorldObject] = field(default_factory=lambda: [
        WorldObject("alice", 3.0, 0.5, "person"),
        WorldObject("red_ball", 1.5, -1.0, "ball"),
        WorldObject("chair_1", -2.0, 2.0, "chair"),
    ])
    log: list[str] = field(default_factory=list)

    def _record(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {msg}")

    def move(self, distance_m: float) -> str:
        if self.posture != "stand":
            return f"refused: cannot move while posture={self.posture}"
        rad = math.radians(self.heading_deg)
        self.x += distance_m * math.cos(rad)
        self.y += distance_m * math.sin(rad)
        self.battery -= abs(distance_m) * 0.4
        self._record(f"move {distance_m:+.2f}m -> ({self.x:.2f},{self.y:.2f})")
        return f"moved to ({self.x:.2f}, {self.y:.2f})"

    def turn(self, degrees: float) -> str:
        self.heading_deg = (self.heading_deg + degrees) % 360
        self.battery -= abs(degrees) * 0.01
        self._record(f"turn {degrees:+.0f}deg -> heading {self.heading_deg:.0f}")
        return f"heading now {self.heading_deg:.0f} deg"

    def set_posture(self, posture: str) -> str:
        if posture not in ("stand", "sit", "lie"):
            return f"refused: unknown posture {posture}"
        self.posture = posture  # type: ignore[assignment]
        self._record(f"posture -> {posture}")
        return f"posture set to {posture}"

    def perceive(self) -> dict:
        # Simple FOV: 90 deg cone, 5m range
        rad = math.radians(self.heading_deg)
        fx, fy = math.cos(rad), math.sin(rad)
        seen = []
        for obj in self.world:
            dx, dy = obj.x - self.x, obj.y - self.y
            dist = math.hypot(dx, dy)
            if dist > 5.0 or dist < 1e-6:
                continue
            # angle between heading and object
            cos_angle = (dx * fx + dy * fy) / dist
            if cos_angle < math.cos(math.radians(45)):
                continue
            bearing = math.degrees(math.atan2(dy, dx)) - self.heading_deg
            bearing = (bearing + 180) % 360 - 180
            seen.append({
                "name": obj.name,
                "tag": obj.tag,
                "distance_m": round(dist, 2),
                "bearing_deg": round(bearing, 1),
            })
        self._record(f"perceive -> {len(seen)} object(s)")
        return {
            "pose": {"x": round(self.x, 2), "y": round(self.y, 2),
                     "heading_deg": round(self.heading_deg, 1)},
            "battery": round(self.battery, 1),
            "posture": self.posture,
            "visible": seen,
        }

    def say(self, text: str) -> str:
        self._record(f'say "{text}"')
        return "spoken"
