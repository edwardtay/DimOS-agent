"""Render a robot-centered top-down 'camera view' as a PNG for Claude Vision.

The real Go2 has RGB cameras and a LiDAR; in the simulator we approximate
the same intent — give Claude pixels grounded in the actual scene — with a
synthetic top-down render. Returns a base64-encoded PNG suitable for an
Anthropic `image` content block.

If Pillow is not installed, returns None and the perceive tool result falls
back to structured-text only.
"""
from __future__ import annotations

import base64
import io
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .go2_sim import Go2Sim

try:
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


PX = 320  # square image side
RANGE_M = 5.0  # half-extent of the rendered area, meters
TAG_COLORS = {
    "person": (42, 109, 244),
    "ball":   (217, 54, 54),
    "chair":  (201, 138, 20),
    "dock":   (31, 138, 76),
}


def render_top_down(robot: "Go2Sim") -> str | None:
    """Return a base64 PNG showing what the robot's top-down LiDAR+RGB fusion
    would see within RANGE_M meters of its current pose. None if Pillow
    is unavailable."""
    if not _HAS_PIL:
        return None

    img = Image.new("RGB", (PX, PX), (250, 250, 248))
    d = ImageDraw.Draw(img, "RGBA")

    cx, cy = PX // 2, PX // 2
    scale = (PX / 2) / RANGE_M  # pixels per meter

    def to_px(wx: float, wy: float) -> tuple[int, int]:
        # robot-relative; rotate so robot's heading points up
        rad = math.radians(robot.heading_deg)
        dx, dy = wx - robot.x, wy - robot.y
        # rotate (-(heading - 90)) so +x (heading 0) maps to up
        ang = -math.radians(robot.heading_deg - 90.0)
        rx = dx * math.cos(ang) - dy * math.sin(ang)
        ry = dx * math.sin(ang) + dy * math.cos(ang)
        return (int(cx + rx * scale), int(cy - ry * scale))

    # FOV cone (90deg, RANGE_M deep, pointing up)
    fov_color = (42, 109, 244, 40)
    cone_r = int(RANGE_M * scale)
    d.pieslice([cx - cone_r, cy - cone_r, cx + cone_r, cy + cone_r],
               start=225, end=315, fill=fov_color, outline=None)

    # 1m grid rings around the robot for scale reference
    for r in (1, 2, 3, 4, 5):
        rr = int(r * scale)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(220, 222, 226), width=1)

    # walls visible within the box
    for (p, q) in robot.obstacles:
        a = to_px(*p)
        b = to_px(*q)
        d.line([a, b], fill=(60, 80, 110), width=3)

    # objects within FOV (90 / 5m)
    rad = math.radians(robot.heading_deg)
    fx, fy = math.cos(rad), math.sin(rad)
    for obj in robot.world:
        ddx, ddy = obj.x - robot.x, obj.y - robot.y
        dist = math.hypot(ddx, ddy)
        if dist > RANGE_M or dist < 1e-6:
            continue
        cos_angle = (ddx * fx + ddy * fy) / dist
        if cos_angle < math.cos(math.radians(45)):
            continue
        # occlusion (same logic as perceive)
        from .go2_sim import _seg_seg_intersect  # local import to avoid cycle at module load
        occluded = any(_seg_seg_intersect((robot.x, robot.y), (obj.x, obj.y), p, q)
                       for (p, q) in robot.obstacles)
        if occluded:
            continue
        px, py = to_px(obj.x, obj.y)
        color = TAG_COLORS.get(obj.tag, (120, 120, 120))
        if obj.tag == "dock":
            d.rectangle([px - 8, py - 8, px + 8, py + 8], outline=color, width=2)
        else:
            d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=color)
        d.text((px + 8, py - 6), obj.name, fill=(40, 50, 65))

    # robot at center, heading up
    d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(42, 109, 244))
    d.line([(cx, cy), (cx, cy - 16)], fill=(255, 255, 255), width=2)

    # compass + scale legend
    d.text((6, 6), f"top-down · {RANGE_M:.0f}m radius · heading up", fill=(120, 130, 145))
    d.text((PX - 60, PX - 18), f"bat {robot.battery:.0f}%", fill=(120, 130, 145))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")
