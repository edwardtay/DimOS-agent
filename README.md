# DimOS-Agent

Claude-driven agent prototype for the [DIMENSIONAL (DimOS) Robot Hackathon](https://luma.com/vprodwg0).
Turns a Unitree Go2 into a natural-language field assistant: you give it a goal in
plain English, and a tool-use loop drives `perceive` → `move`/`turn`/`say` → `done`
against either a local simulator or (swap one file) the real DimOS SDK.

## What's in it

- `dimos_proto/go2_sim.py` — mock Go2 SDK: pose, posture, battery, 90° / 5m FOV perception, action log.
- `dimos_proto/tools.py` — Anthropic tool schemas + dispatcher (`move`, `turn`, `set_posture`, `perceive`, `say`, `done`).
- `dimos_proto/agent.py` — Claude tool-use loop with a cached safety-rule system prompt, 20-step cap.
- `dimos_proto/server.py` — FastAPI + SSE localhost demo with a 2D canvas of the robot and world.
- `dimos_proto/main.py` — CLI entry.

The agent never sees the simulator directly — it only sees the tool schema.
The same loop runs against real hardware once `Go2Sim` is replaced with the DimOS SDK shim.

## Run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# CLI
python -m dimos_proto.main "find alice and say hello"

# Web demo
python -m dimos_proto.server   # then open http://127.0.0.1:8000
```

In the web demo: paste your API key, type a goal, watch the dog walk on the
canvas while tool calls stream in. Try:

- `find alice and say hello`
- `look around and report what you see`
- `walk to the red ball`
- `sit down then stand back up`

## What makes it not-a-toy

- **Walls + collision** — the simulator has axis-aligned wall segments; `move`
  raycasts the path and stops short on contact, returning a `blocked by wall`
  signal the agent must reason about.
- **Emergency stop** — operator button + `/estop` endpoint. Sets a flag the
  simulator honors (refuses motion, collapses to `sit`) and cancels any
  in-flight mission mid-step.
- **Cancellable missions** — `/cancel` and an in-loop `threading.Event` make
  the agent abort at the next step boundary.
- **Sensor noise** — `perceive` adds gaussian noise (~4 cm / 1.5°) to ranges
  and bearings, and occludes anything behind a wall.
- **Battery enforcement** — actions cost battery; below 5% the robot refuses
  to move. There is a charging dock in the world and a `recharge_at_dock` tool.
- **Token + cost telemetry** — every mission yields a `USAGE:` line with
  input/output tokens and an estimated USD cost (Sonnet 4.6 pricing).
- **Persistent log** — every event (move, blocked, refused, perceive, say,
  estop, etc.) is appended to `missions.jsonl` with a session id and timestamp.
- **Operator UX** — drag any world object on the canvas to reposition it;
  click `EMERGENCY STOP` for an instant halt; toggle TTS to hear the robot
  actually speak its `say()` calls via Web Speech.

## Agent safety rules (in the system prompt)

- Always `perceive` before acting if info is stale.
- Move in small steps (≤ 1.0 m) and re-perceive frequently.
- On `blocked by wall`, turn and try a new heading — never repeat the same move.
- Never move while posture is not `stand` or while `emergency_stop` is true.
- Below 15% battery, route to the dock and `recharge_at_dock`.
- Call `done` with a one-sentence summary when the goal is satisfied (or cannot be).

## License

MIT
