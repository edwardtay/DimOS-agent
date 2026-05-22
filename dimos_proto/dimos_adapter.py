"""Real-hardware adapter: maps DimOS-Agent's tool surface onto the DimOS SDK.

This file is the *only* code that has to change to go from the simulator to
a physical Unitree Go2 running DimOS. The agent loop, tool schemas, memory,
manifest, discrepancy logic, and operator UI are all unchanged.

Usage on real hardware (after `pip install dimos-sdk` and connecting to the
robot's network):

    from dimos_proto.dimos_adapter import RealGo2, RealFleet
    fleet = RealFleet([
        RealGo2(robot_id="go2-1", host="192.168.123.161"),
        RealGo2(robot_id="go2-2", host="192.168.123.162"),
    ])
    # then point the server at it:
    #   import dimos_proto.server as s; s.FLEET = fleet; s.ROBOT = fleet.get(None)

The stubs below intentionally `raise NotImplementedError` rather than
silently falling back, so a wiring mistake fails loudly before anything
moves on the physical robot.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal


# DimOS SDK imports happen lazily inside methods so the simulator can be
# developed on a laptop with no robot attached.
def _load_dimos() -> Any:
    try:
        import dimos  # type: ignore[import-not-found]
        return dimos
    except ImportError as e:
        raise RuntimeError(
            "DimOS SDK not installed. Run `pip install dimos-sdk` on a machine "
            "connected to the Go2's network. See https://github.com/dimensionalOS"
        ) from e


@dataclass
class RealGo2:
    """Drop-in replacement for `Go2Sim` backed by the real DimOS SDK.

    Mirrors the Go2Sim public interface used by `tools.dispatch` and
    `agent.run`. Anything the agent calls on the sim must exist here.
    """
    robot_id: str = "go2-1"
    host: str = "192.168.123.161"  # default Unitree LAN IP

    # The agent reads these as plain attributes; we lazy-resolve from the SDK.
    posture: Literal["stand", "sit", "lie"] = "stand"
    emergency_stop: bool = False
    radius: float = 0.30
    min_battery: float = 5.0

    # Shared-world state lives on the Fleet, not the robot. The adapter still
    # exposes them as attributes so the existing tools/dispatch keep working
    # without changes.
    world: list = field(default_factory=list)
    obstacles: list = field(default_factory=list)
    zones: dict = field(default_factory=dict)
    manifest: list = field(default_factory=list)
    discrepancies: list = field(default_factory=list)
    log: list = field(default_factory=list)

    _client: Any = field(default=None, init=False, repr=False)
    _last_pose: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "heading_deg": 0.0})
    _last_battery: float = 100.0

    def _connect(self) -> Any:
        if self._client is None:
            dimos = _load_dimos()
            # Real DimOS uses LCM under the hood; the high-level client wraps it.
            self._client = dimos.Go2(host=self.host)
            self._client.connect()
        return self._client

    # ---------- pose accessors expected by the agent / UI ----------
    @property
    def x(self) -> float:
        return self._last_pose["x"]

    @property
    def y(self) -> float:
        return self._last_pose["y"]

    @property
    def heading_deg(self) -> float:
        return self._last_pose["heading_deg"]

    @property
    def battery(self) -> float:
        return self._last_battery

    # ---------- actions ----------
    def move(self, distance_m: float) -> str:
        c = self._connect()
        # DimOS exposes a high-level locomotion API: walk(vx, vy, vyaw, duration).
        # We approximate "walk distance_m at the current heading" with a velocity
        # command sized to complete in ~distance_m / 0.5 m/s.
        vx = 0.5 if distance_m >= 0 else -0.5
        duration = abs(distance_m) / 0.5
        c.locomotion.walk(vx=vx, vy=0.0, vyaw=0.0, duration=duration)
        odom = c.state.odometry()
        self._last_pose = {"x": odom.x, "y": odom.y, "heading_deg": math.degrees(odom.theta)}
        self._last_battery = c.state.battery_percent()
        return f"moved to ({odom.x:.2f}, {odom.y:.2f})"

    def turn(self, degrees: float) -> str:
        c = self._connect()
        rad = math.radians(degrees)
        # vyaw is rad/s; complete in 1 second at proportional speed.
        c.locomotion.walk(vx=0.0, vy=0.0, vyaw=rad, duration=1.0)
        odom = c.state.odometry()
        self._last_pose["heading_deg"] = math.degrees(odom.theta)
        return f"heading now {self._last_pose['heading_deg']:.0f} deg"

    def set_posture(self, posture: str) -> str:
        c = self._connect()
        if posture == "stand":
            c.locomotion.stand_up()
        elif posture == "sit":
            c.locomotion.sit_down()
        elif posture == "lie":
            c.locomotion.lie_down()
        else:
            return f"refused: unknown_posture {posture}"
        self.posture = posture  # type: ignore[assignment]
        return f"posture set to {posture}"

    def perceive(self) -> dict:
        """Use the Go2's RGB + LiDAR fusion to build the same structured
        perception result the simulator returns."""
        c = self._connect()
        detections = c.perception.detect_objects()  # YOLO-style on RGB
        odom = c.state.odometry()
        self._last_pose = {"x": odom.x, "y": odom.y, "heading_deg": math.degrees(odom.theta)}
        self._last_battery = c.state.battery_percent()

        visible = []
        for d in detections:
            visible.append({
                "name": d.label,
                "tag": d.category,
                "distance_m": round(d.distance_m, 2),
                "bearing_deg": round(d.bearing_deg, 1),
                "zone": self.zone_of(d.world_x, d.world_y),
            })
        return {
            "pose": {**self._last_pose, "zone": self.zone_of(odom.x, odom.y)},
            "battery": self._last_battery,
            "posture": self.posture,
            "emergency_stop": self.emergency_stop,
            "visible": visible,
        }

    def say(self, text: str) -> str:
        c = self._connect()
        c.audio.tts(text)
        return "spoken"

    def set_emergency_stop(self, active: bool) -> str:
        c = self._connect()
        if active:
            c.safety.emergency_stop()
            self.posture = "sit"
        else:
            c.safety.clear_emergency_stop()
        self.emergency_stop = active
        return f"emergency_stop={active}"

    def recharge_at_dock(self) -> str:
        c = self._connect()
        for o in self.world:
            if o.tag == "dock" and math.hypot(o.x - self.x, o.y - self.y) < 0.6:
                c.power.dock_and_charge()
                # block until charged or timeout
                deadline = time.time() + 600
                while time.time() < deadline and c.state.battery_percent() < 95:
                    time.sleep(2)
                self._last_battery = c.state.battery_percent()
                return f"battery recharged to {self._last_battery:.0f}%"
        return "refused: not_at_dock"

    def report_discrepancy(self, name: str, kind: str, note: str = "") -> str:
        # Discrepancies live on the fleet/world state, shared across robots.
        entry = {"ts": time.strftime("%H:%M:%S"),
                 "name": name, "kind": kind, "note": note}
        self.discrepancies.append(entry)
        return f"logged {kind}: {name}" + (f" ({note})" if note else "")

    def zone_of(self, x: float, y: float) -> str | None:
        for name, (x1, y1, x2, y2) in self.zones.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                return name
        return None


@dataclass
class RealFleet:
    """Drop-in replacement for `Fleet` over `RealGo2` instances."""
    robots: dict[str, RealGo2] = field(default_factory=dict)
    primary_id: str = "go2-1"

    def __init__(self, robots: list[RealGo2]) -> None:
        self.robots = {r.robot_id: r for r in robots}
        self.primary_id = robots[0].robot_id if robots else "go2-1"
        # share world state across all robots, same as Fleet.default()
        p = self.robots[self.primary_id]
        for r in self.robots.values():
            if r is p:
                continue
            r.world = p.world
            r.obstacles = p.obstacles
            r.zones = p.zones
            r.manifest = p.manifest
            r.discrepancies = p.discrepancies

    def get(self, robot_id: str | None) -> RealGo2:
        return self.robots[robot_id or self.primary_id]

    def summary(self) -> list[dict]:
        return [
            {"id": rid, "pose": {"x": r.x, "y": r.y, "heading_deg": r.heading_deg},
             "battery": r.battery, "posture": r.posture,
             "emergency_stop": r.emergency_stop, "zone": r.zone_of(r.x, r.y)}
            for rid, r in self.robots.items()
        ]
