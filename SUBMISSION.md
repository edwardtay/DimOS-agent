# DimOS-Agent — Hackathon Submission

**Track:** Agents
**Team / Builder:** Edward Tay
**Repo:** https://github.com/edwardtay/DimOS-agent
**Demo:** `python -m dimos_proto.server` → http://127.0.0.1:8000
**Demo video:** *recorded at code freeze*

---

## 100-word project description

DimOS-Agent turns a Unitree Go2 into a Claude-driven warehouse-inspection
robot you command in plain English. The agent loop calls a small set of
tools — `perceive`, `move`, `turn`, `say`, `report_discrepancy` — against
either a local simulator or, via a one-file adapter, a real Go2 over the
DimOS SDK. The robot walks a multi-zone floor, compares what it sees to a
loaded manifest, and reports missing or unexpected items. A second Go2 in
the fleet can split the patrol in parallel. Every mission persists facts
to memory, streams a token-cost telemetry line, and surfaces a live
labor-savings ROI panel for the operator.

## What's here

| Capability | Where it lives | Why it matters |
|---|---|---|
| LLM tool-use loop with safety prompt | `dimos_proto/agent.py` | Plug-and-play Claude reasoning over robot primitives |
| Go2 simulator (walls, collision, sensor noise, battery, FOV occlusion) | `dimos_proto/go2_sim.py` | Develop without hardware; tests assert physics |
| Multi-robot Fleet sharing one world | `Fleet` in `go2_sim.py` | Parallel inspection — go2-1 to zone A, go2-2 to zone B |
| Warehouse vertical: zones, manifest, discrepancies | seeded in `Go2Sim` defaults | Closed-loop business outcome judges can grade |
| Persistent agent memory across missions | `dimos_proto/memory.py` | Robot remembers "alice last seen at (3.1, 0.4)" |
| Operator console (light-theme, mobile-responsive) | `dimos_proto/server.py` HTML | Voice goal input, drag-to-arrange world, e-stop, mission queue, TTS |
| Mission analytics + ROI card | `/analytics` endpoint + UI grid | $ saved, ROI multiple, mission count, total Claude spend |
| Real-hardware adapter | `dimos_proto/dimos_adapter.py` | The "swap one file" claim, written out |
| JSONL mission log | `missions.jsonl` | Auditability — every action timestamped |
| Pytest suite (18 tests) + GitHub Actions | `tests/`, `.github/workflows/test.yml` | CI gate on every push |
| Dockerfile | `Dockerfile` | `docker run -p 8000:8000 -e ANTHROPIC_API_KEY=...` |

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│  Operator (browser, voice or text)                                    │
└────────────────────────────────┬──────────────────────────────────────┘
                                 │ goal (NL)
                                 ▼
┌───────────────────────────────────────────────────────────────────────┐
│  FastAPI server (SSE stream, /run /state /estop /analytics ...)       │
└────────────────────────────────┬──────────────────────────────────────┘
                                 │
                                 ▼
            ┌─────────────────────────────────────────────┐
            │  Agent loop (Claude Sonnet 4.6, tool use)   │
            │  ┌──────────────────────────────────────┐   │
            │  │ system prompt + cache_control        │   │
            │  │ manifest + zones + memory preamble   │   │
            │  └──────────────────────────────────────┘   │
            └────────────┬────────────────┬───────────────┘
              tool_use   │                │  tool_result
                         ▼                ▲
            ┌──────────────────────────────────────────────┐
            │  dispatch(fleet, name, args, memory)         │
            └────┬─────────────┬──────────────┬────────────┘
                 │             │              │
                 ▼             ▼              ▼
            ┌─────────┐  ┌──────────┐  ┌────────────────┐
            │ Fleet   │  │ Memory   │  │ Discrepancies  │
            │ (Go2×2) │  │ (JSON)   │  │ (audit log)    │
            └────┬────┘  └──────────┘  └────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
   ┌──────────┐    ┌──────────────────┐
   │ Go2Sim   │    │ RealGo2          │
   │ (sim)    │    │ (DimOS SDK adapt)│
   └──────────┘    └──────────────────┘
```

## 90-second demo storyboard

| Time | What happens | What the judge sees |
|---|---|---|
| 0:00–0:10 | Open the console. Two Go2 dots wait in front aisle. Manifest panel shows 7 expected items across 3 zones. | "Real fleet. Real manifest. Real warehouse problem." |
| 0:10–0:25 | Operator clicks the 🎤 mic. Says: *"Walk the patrol route. go2-1 takes zone A, go2-2 takes zone B. Report any discrepancies."* | Voice input → goal field → trace begins streaming. |
| 0:25–0:55 | Both robots move in parallel. FOV cones sweep. `perceive` calls visible in the trace. Each robot reports findings via `report_discrepancy`. | Two dots moving = visible parallelism. Red/amber pills appear on the left as discrepancies land. |
| 0:55–1:10 | Robots converge on the front aisle. One speaks the audit summary aloud (Web Speech TTS): *"Audit complete. Found one missing item: chair_3 in zone A. Found one unexpected item: rogue_box in zone B."* | The dog *talks*. |
| 1:10–1:25 | Camera cuts to the analytics card: *labor saved: $130. ROI: 87×. Discrepancies caught: 2. Total spend: $0.015.* | The slide judges remember. |
| 1:25–1:30 | Title card: *"Same loop runs on real Go2 via one adapter file. github.com/edwardtay/DimOS-agent"* | The close. |

## How to run

```bash
# 1. Install
pip install -r requirements.txt

# 2. Provide your key (or paste it into the UI)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Start the operator console
python -m dimos_proto.server

# 4. Open http://127.0.0.1:8000
```

Or via Docker:

```bash
docker build -t dimos-agent .
docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... dimos-agent
```

Run the test suite:

```bash
pip install pytest
pytest -q tests/   # 18 passing
```

## Real-hardware path

`dimos_proto/dimos_adapter.py` defines `RealGo2` and `RealFleet` — drop-in
replacements for `Go2Sim` and `Fleet` that call the DimOS SDK directly. To
switch from sim to real:

```python
from dimos_proto.dimos_adapter import RealGo2, RealFleet
import dimos_proto.server as s

s.FLEET = RealFleet([
    RealGo2(robot_id="go2-1", host="192.168.123.161"),
    RealGo2(robot_id="go2-2", host="192.168.123.162"),
])
s.ROBOT = s.FLEET.get(None)
```

Nothing else in the stack changes. The agent loop, tool schemas, manifest
logic, memory, operator UI, and tests are all SDK-agnostic.

## Why this submission can win the Agents track

1. **Closed-loop business outcome.** This isn't a chatbot — the agent
   produces a verifiable artifact (the discrepancy list) with a quantified
   business value (labor $ saved).
2. **Parallel multi-robot coordination from a single prompt.** *"Send go2-1
   to A and go2-2 to B"* is one of the canonical agent challenges, and it
   works here today.
3. **Persistent memory makes day-2 missions smarter than day-1.** Real
   warehouses do daily cycle counts — our robot gets better over time.
4. **Safety is a feature, not a footnote.** Emergency stop, battery floor,
   collision detection, posture lock, mid-mission cancel — all enforced
   by the simulator and the system prompt.
5. **Production discipline.** Tests, CI, Docker, mobile UI, structured
   audit log, token telemetry. Judges who run the repo find it works.

## What's next (if we win)

- Real Claude Vision in `perceive`: render a top-down PNG and attach as an
  image block in tool_result so the VLM grounds its reasoning in pixels.
- Mission replay from `missions.jsonl` — operator scrubs back through any
  past inspection on the canvas.
- Live patrol scheduler (cron-style) for unattended overnight audits.
- Plug-in vertical packs: security patrol, perimeter inspection, retail
  shelf gap detection — same loop, different manifest.

---

*Built in 48 hours for the [DIMENSIONAL (DimOS) Robot Hackathon](https://luma.com/vprodwg0).*
