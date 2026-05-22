"""Localhost demo for the DimOS prototype.

Run:  python -m dimos_proto.server
Open: http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .agent import run as agent_run
from .go2_sim import Go2Sim
from .memory import AgentMemory

app = FastAPI()
ROBOT = Go2Sim()
MEMORY = AgentMemory()
LOCK = threading.Lock()
CANCEL = threading.Event()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/notes", response_class=HTMLResponse)
def notes() -> str:
    """Private ELI5 brief. Reads NOTES.md from disk so the content stays local
    (the file is gitignored). Only reachable on localhost."""
    candidates = [Path.cwd() / "NOTES.md",
                  Path(__file__).resolve().parent.parent / "NOTES.md"]
    text = None
    for p in candidates:
        if p.exists():
            text = p.read_text()
            break
    if text is None:
        return _notes_shell("NOTES.md not found on this machine.")
    return _notes_shell(text)


def _notes_shell(markdown: str) -> str:
    safe = (markdown
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>NOTES · private</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
 body {{ max-width: 760px; margin: 40px auto; padding: 0 24px 80px;
   font: 15px/1.6 -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
   color: #1a1f29; background: #fffdf6; }}
 h1, h2, h3 {{ line-height: 1.25; }}
 h1 {{ font-size: 26px; border-bottom: 1px solid #e8d8a0; padding-bottom: 8px; }}
 h2 {{ font-size: 19px; margin-top: 32px; }}
 code {{ font-family: ui-monospace, Menlo, monospace; font-size: 13px;
   background: #f0eadb; padding: 2px 5px; border-radius: 4px; }}
 pre code {{ display: block; padding: 12px; overflow-x: auto; }}
 table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
 th, td {{ border: 1px solid #e3d8b8; padding: 6px 10px; text-align: left; font-size: 13px; }}
 th {{ background: #f7efd0; }}
 blockquote {{ border-left: 4px solid #d4b840; margin: 0; padding: 8px 14px;
   background: #fff8d6; color: #6a5212; font-size: 14px; }}
 .pill {{ display: inline-block; padding: 2px 9px; border-radius: 999px;
   background: #d4b840; color: #fff; font-size: 11px; font-weight: 600;
   letter-spacing: .05em; vertical-align: middle; margin-left: 8px; }}
 a.back {{ display: inline-block; margin-bottom: 10px; color: #6a5212; font-size: 13px; }}
</style></head><body>
<a class="back" href="/">← back to operator console</a>
<span class="pill">PRIVATE · localhost only</span>
<article id="md"></article>
<script>
 const raw = {json.dumps(safe)};
 document.getElementById('md').innerHTML = marked.parse(raw.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>'));
</script>
</body></html>"""


@app.get("/state")
def state() -> JSONResponse:
    with LOCK:
        return JSONResponse({
            "pose": {"x": ROBOT.x, "y": ROBOT.y, "heading_deg": ROBOT.heading_deg},
            "battery": ROBOT.battery,
            "posture": ROBOT.posture,
            "emergency_stop": ROBOT.emergency_stop,
            "world": [{"name": o.name, "tag": o.tag, "x": o.x, "y": o.y}
                      for o in ROBOT.world],
            "obstacles": [
                {"x1": p[0], "y1": p[1], "x2": q[0], "y2": q[1]}
                for (p, q) in ROBOT.obstacles
            ],
            "zones": [
                {"name": z, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
                for z, (x1, y1, x2, y2) in ROBOT.zones.items()
            ],
            "manifest": ROBOT.manifest,
            "discrepancies": ROBOT.discrepancies,
            "log_tail": ROBOT.log[-12:],
        })


@app.post("/reset")
def reset() -> dict:
    global ROBOT
    with LOCK:
        ROBOT = Go2Sim()
    CANCEL.clear()
    return {"ok": True}


class EStopBody(BaseModel):
    active: bool


@app.post("/estop")
def estop(body: EStopBody) -> dict:
    with LOCK:
        ROBOT.set_emergency_stop(body.active)
    if body.active:
        CANCEL.set()
    return {"emergency_stop": ROBOT.emergency_stop}


@app.post("/cancel")
def cancel() -> dict:
    CANCEL.set()
    return {"cancelled": True}


class PlaceBody(BaseModel):
    name: str
    x: float
    y: float


@app.post("/place")
def place(body: PlaceBody) -> dict:
    with LOCK:
        ROBOT.place_object(body.name, body.x, body.y)
    return {"ok": True}


class ManifestBody(BaseModel):
    manifest: list[dict]


@app.post("/manifest")
def set_manifest(body: ManifestBody) -> dict:
    with LOCK:
        ROBOT.manifest = body.manifest
        ROBOT.discrepancies.clear()
    return {"ok": True, "count": len(ROBOT.manifest)}


@app.post("/discrepancies/clear")
def clear_discrepancies() -> dict:
    with LOCK:
        ROBOT.discrepancies.clear()
    return {"ok": True}


@app.get("/memory")
def memory_view() -> JSONResponse:
    return JSONResponse(MEMORY.all())


@app.post("/memory/clear")
def memory_clear() -> dict:
    for k in list(MEMORY.all().keys()):
        MEMORY.forget(k)
    return {"ok": True}


@app.get("/run")
def run_goal(goal: str, api_key: str | None = None) -> StreamingResponse:
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    CANCEL.clear()
    q: queue.Queue[str | None] = queue.Queue()

    def worker() -> None:
        try:
            for line in agent_run(goal, ROBOT, CANCEL, MEMORY):
                q.put(line)
        except Exception as e:
            q.put(f"ERROR: {type(e).__name__}: {e}")
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def sse() -> Iterator[bytes]:
        while True:
            item = q.get()
            if item is None:
                yield b"event: end\ndata: {}\n\n"
                return
            yield f"data: {json.dumps({'line': item})}\n\n".encode()

    return StreamingResponse(sse(), media_type="text/event-stream")


INDEX_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>DimOS · Go2 Operator Console</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<style>
 :root {
   color-scheme: light;
   --bg:#ffffff; --panel:#f7f8fa; --grid:#eef0f3; --grid-strong:#dde1e7;
   --wall:#3a4a63; --border:#e3e6eb; --text:#1a1f29; --muted:#6b7480;
   --accent:#2a6df4; --accent-soft:rgba(42,109,244,0.10);
   --danger:#c43030; --danger-soft:#fdecec;
   --warn:#b4791a; --good:#1f8a4c;
   --chip:#eef2f8; --chip-hover:#dde6f5; --chip-text:#3a4a63;
 }
 * { box-sizing: border-box; }
 html, body { height: 100%; }
 body { margin:0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
   background:var(--bg); color:var(--text); -webkit-text-size-adjust:100%; }
 header { padding:12px 18px; border-bottom:1px solid var(--border);
   display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
 header h1 { font-size:14px; margin:0; letter-spacing:.04em; font-weight:600; }
 .badge { font-size:11px; color:var(--muted); padding:3px 8px;
   background:var(--chip); border-radius:999px; }
 .estop { margin-left:auto; padding:8px 14px; background:var(--danger);
   color:#fff; border:none; border-radius:8px; cursor:pointer; font-weight:600;
   letter-spacing:.05em; font-size:12px; font-family:inherit; }
 .estop.active { background:#fff; color:var(--danger); border:2px solid var(--danger); }
 main { display:grid; grid-template-columns: 460px 1fr; gap:0;
   height: calc(100dvh - 53px); }
 #left { border-right:1px solid var(--border); display:flex; flex-direction:column;
   background:var(--panel); min-height:0; }
 #right { position:relative; background:var(--bg); min-height:0; }
 canvas { display:block; width:100%; height:100%; touch-action:none; cursor:grab; }
 canvas.dragging { cursor:grabbing; }
 .panel { padding:12px 16px; border-top:1px solid var(--border); background:var(--panel); }
 .panel:first-child { border-top:none; }
 .row { display:flex; gap:8px; align-items:center; }
 input[type=text], input[type=password] {
   flex:1; min-width:0; padding:10px 12px; background:#fff; border:1px solid var(--border);
   color:var(--text); border-radius:8px; font: inherit; font-size:14px;
 }
 input:focus { outline:2px solid var(--accent-soft); border-color:var(--accent); }
 button { padding:10px 14px; background:var(--accent); color:#fff; border:none;
   border-radius:8px; cursor:pointer; font: inherit; font-size:14px; white-space:nowrap; }
 button.secondary { background:#fff; color:var(--text); border:1px solid var(--border); }
 button.danger { background:var(--danger-soft); color:var(--danger);
   border:1px solid var(--danger); }
 button:disabled { opacity:.55; cursor:wait; }
 #trace { flex:1; overflow:auto; padding:12px 16px; font-size:12.5px;
   line-height:1.55; white-space:pre-wrap; background:#fff;
   -webkit-overflow-scrolling: touch; }
 .t-goal { color:var(--accent); font-weight:600; }
 .t-think { color:var(--muted); }
 .t-tool { color:var(--good); }
 .t-done { color:var(--warn); font-weight:600; }
 .t-err  { color:var(--danger); }
 .t-cancel { color:var(--danger); font-weight:600; }
 .t-usage { color:var(--muted); font-style:italic; }
 .kv { color:var(--muted); font-size:12px; }
 #mic.recording { background:var(--danger); color:#fff; border-color:var(--danger);
   animation: pulse 1s infinite; }
 @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.5;} }
 .queue, .memory, .discrepancies { margin-top:10px; display:flex; flex-wrap:wrap; gap:6px; }
 .queue:empty, .memory:empty, .discrepancies:empty { display:none; }
 .queue .q-item, .memory .m-item, .discrepancies .d-item {
   display:inline-flex; align-items:center; gap:6px;
   font-size:12px; padding:5px 4px 5px 10px; background:#fff;
   border:1px solid var(--border); border-radius:6px; color:var(--text);
 }
 .queue .q-item b { color:var(--accent); }
 .memory .m-item { background:var(--chip); border-color:transparent; color:var(--chip-text); }
 .discrepancies .d-item { background:#fdecec; border-color:#f3c5c5; color:var(--danger); font-weight:500; }
 .discrepancies .d-item.kind-extra { background:#fff5e0; border-color:#f0d28a; color:#8a5a14; }
 .discrepancies .d-item.kind-wrong_zone { background:#fff5e0; border-color:#f0d28a; color:#8a5a14; }
 .manifest-block { margin-top:10px; font-size:12px; color:var(--muted); }
 .manifest-block summary { cursor:pointer; padding:4px 0; user-select:none; }
 .manifest-block textarea { width:100%; margin-top:6px; padding:8px; border-radius:6px;
   border:1px solid var(--border); font: 12px ui-monospace; background:#fff; color:var(--text);
   resize:vertical; min-height:90px; }
 .q-item button { padding:2px 7px; background:transparent; color:var(--muted);
   border:none; font-size:14px; cursor:pointer; }
 .examples { display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }
 .examples span { font-size:12px; padding:5px 10px; background:var(--chip);
   border-radius:999px; cursor:pointer; color:var(--chip-text); }
 .examples span:hover { background:var(--chip-hover); }
 #hud { position:absolute; top:10px; left:14px; right:14px;
   font-size:12px; color:var(--muted); pointer-events:none;
   display:flex; gap:14px; flex-wrap:wrap; }
 #hud b { color:var(--text); font-weight:500; }
 #hud .bat-low { color:var(--danger); }
 .estop-banner { position:absolute; left:50%; top:14px; transform:translateX(-50%);
   background:var(--danger); color:#fff; padding:6px 14px; border-radius:999px;
   font-size:12px; font-weight:600; letter-spacing:.05em; display:none; }
 .estop-banner.on { display:block; }

 @media (max-width: 820px) {
   header .badge { display:none; }
   main { grid-template-columns: 1fr; grid-template-rows: 46vh 1fr;
     height: calc(100dvh - 53px); }
   #left { border-right:none; border-top:1px solid var(--border); order:2; }
   #right { order:1; border-bottom:1px solid var(--border); }
   .panel { padding:12px 14px; }
   .row { flex-wrap:wrap; }
   .row > input { flex: 1 1 100%; }
   .row > button { flex: 1 1 auto; }
   input, button { font-size:16px; }
 }
</style></head>
<body>
<header>
  <h1>DIMOS · GO2 OPERATOR CONSOLE</h1>
  <span class="badge">localhost simulator</span>
  <span class="badge">Claude tool-use loop</span>
  <a href="/notes" target="_blank" class="badge" style="text-decoration:none;">📓 notes</a>
  <button class="estop" id="estop">EMERGENCY STOP</button>
</header>
<main>
  <div id="left">
    <div class="panel">
      <div class="row">
        <input id="key" type="password" placeholder="ANTHROPIC_API_KEY (this tab only)" />
      </div>
      <div class="row" style="margin-top:8px;">
        <input id="goal" type="text" placeholder='e.g. "find alice and say hello"' />
        <button id="mic" class="secondary" title="voice input">🎤</button>
        <button id="queue-add" class="secondary" title="add to queue">+</button>
        <button id="go">Run</button>
      </div>
      <div class="row" style="margin-top:8px;">
        <button id="cancel" class="danger" disabled>Cancel mission</button>
        <button id="reset" class="secondary">Reset world</button>
        <button id="forget" class="secondary" title="clear agent memory">forget all</button>
        <label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px;">
          <input type="checkbox" id="tts" checked> speech
        </label>
      </div>
      <div id="queue" class="queue"></div>
      <div id="discrepancies" class="discrepancies"></div>
      <div id="memory" class="memory"></div>
      <details class="manifest-block">
        <summary>Manifest (<span id="manifest-count">0</span> items)</summary>
        <textarea id="manifest" spellcheck="false" rows="6"></textarea>
        <div class="row" style="margin-top:6px;">
          <button id="manifest-save" class="secondary">Save manifest</button>
          <button id="discrepancies-clear" class="secondary">Clear discrepancies</button>
        </div>
      </details>
      <div class="examples">
        <span>walk the patrol route and report any manifest discrepancies</span>
        <span>visit zone A, B, and C and tell me what you see in each</span>
        <span>find alice and say hello</span>
        <span>battery low — return to the dock and recharge</span>
      </div>
    </div>
    <div id="trace"></div>
  </div>
  <div id="right">
    <canvas id="map"></canvas>
    <div id="hud"></div>
    <div id="banner" class="estop-banner">EMERGENCY STOP ACTIVE</div>
  </div>
</main>
<script>
const cvs = document.getElementById('map');
const ctx = cvs.getContext('2d');
const trace = document.getElementById('trace');
const hud = document.getElementById('hud');
const banner = document.getElementById('banner');
let state = null;
let drag = null;

function viewMetrics() {
  const W = cvs.width / devicePixelRatio, H = cvs.height / devicePixelRatio;
  const scale = Math.max(28, Math.min(70, Math.min(W, H) / 11));
  return { W, H, scale, cx: W/2, cy: H/2 };
}
function worldFromScreen(sx, sy) {
  const m = viewMetrics();
  return { x: (sx - m.cx) / m.scale, y: -(sy - m.cy) / m.scale };
}

function fitCanvas() {
  const r = cvs.getBoundingClientRect();
  cvs.width = r.width * devicePixelRatio;
  cvs.height = r.height * devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
}
window.addEventListener('resize', () => { fitCanvas(); draw(); });

function draw() {
  if (!state) return;
  const m = viewMetrics();
  const { W, H, scale, cx, cy } = m;
  ctx.clearRect(0,0,W,H);

  // zones (filled tinted rectangles)
  const zoneColors = { A:'rgba(42,109,244,0.06)', B:'rgba(31,138,76,0.07)', C:'rgba(180,121,26,0.06)' };
  ctx.font = '13px ui-monospace';
  for (const z of (state.zones || [])) {
    const x = cx + z.x1*scale, y = cy - z.y2*scale;
    const w = (z.x2 - z.x1)*scale, h = (z.y2 - z.y1)*scale;
    ctx.fillStyle = zoneColors[z.name] || 'rgba(100,100,100,0.05)';
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = 'rgba(60,80,110,0.18)'; ctx.setLineDash([4,4]); ctx.lineWidth = 1;
    ctx.strokeRect(x, y, w, h); ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(60,80,110,0.55)';
    ctx.fillText('zone ' + z.name, x + 8, y + 18);
  }

  // grid
  ctx.strokeStyle = getCss('--grid'); ctx.lineWidth = 1;
  for (let i=-14;i<=14;i++){
    ctx.beginPath(); ctx.moveTo(cx+i*scale,0); ctx.lineTo(cx+i*scale,H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0,cy-i*scale); ctx.lineTo(W,cy-i*scale); ctx.stroke();
  }
  ctx.strokeStyle = getCss('--grid-strong');
  ctx.beginPath(); ctx.moveTo(cx,0); ctx.lineTo(cx,H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0,cy); ctx.lineTo(W,cy); ctx.stroke();

  // walls
  ctx.strokeStyle = getCss('--wall'); ctx.lineWidth = 4; ctx.lineCap = 'round';
  for (const w of state.obstacles) {
    ctx.beginPath();
    ctx.moveTo(cx + w.x1*scale, cy - w.y1*scale);
    ctx.lineTo(cx + w.x2*scale, cy - w.y2*scale);
    ctx.stroke();
  }

  // world objects
  const tagColor = { person:'#2a6df4', ball:'#d93636', chair:'#c98a14', dock:'#1f8a4c' };
  for (const o of state.world) {
    const px = cx + o.x*scale, py = cy - o.y*scale;
    if (o.tag === 'dock') {
      ctx.strokeStyle = tagColor[o.tag]; ctx.lineWidth = 2;
      ctx.strokeRect(px-12, py-12, 24, 24);
    } else {
      ctx.fillStyle = tagColor[o.tag] || '#888';
      ctx.beginPath(); ctx.arc(px,py,8,0,Math.PI*2); ctx.fill();
    }
    ctx.fillStyle = getCss('--text'); ctx.font = '12px ui-monospace';
    ctx.fillText(o.name, px+12, py+4);
  }

  // robot
  const rx = cx + state.pose.x*scale, ry = cy - state.pose.y*scale;
  const h = state.pose.heading_deg * Math.PI/180;
  ctx.fillStyle = 'rgba(42,109,244,0.14)';
  ctx.beginPath();
  ctx.moveTo(rx,ry);
  ctx.arc(rx,ry, 5*scale, -h - Math.PI/4, -h + Math.PI/4);
  ctx.closePath(); ctx.fill();
  ctx.fillStyle = state.emergency_stop ? getCss('--danger') : getCss('--accent');
  ctx.beginPath(); ctx.arc(rx,ry,10,0,Math.PI*2); ctx.fill();
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(rx,ry);
  ctx.lineTo(rx + Math.cos(-h)*18, ry + Math.sin(-h)*18); ctx.stroke();

  // HUD
  const bClass = state.battery < 15 ? 'bat-low' : '';
  hud.innerHTML =
    `<span>pose <b>(${state.pose.x.toFixed(2)}, ${state.pose.y.toFixed(2)})</b></span>` +
    `<span>heading <b>${state.pose.heading_deg.toFixed(0)}°</b></span>` +
    `<span>posture <b>${state.posture}</b></span>` +
    `<span class="${bClass}">battery <b>${state.battery.toFixed(1)}%</b></span>` +
    (usage.in_tok ? `<span>tokens <b>${usage.in_tok}/${usage.out_tok}</b> · <b>$${usage.cost.toFixed(4)}</b></span>` : '');
  banner.classList.toggle('on', !!state.emergency_stop);
}
function getCss(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

let usage = { in_tok: 0, out_tok: 0, cost: 0 };

async function refresh() {
  try { const r = await fetch('/state'); state = await r.json(); draw(); } catch(e) {}
}
setInterval(refresh, 500); fitCanvas(); refresh();

// --- drag objects ---
function hitObject(sx, sy) {
  if (!state) return null;
  const m = viewMetrics();
  for (const o of state.world) {
    const px = m.cx + o.x*m.scale, py = m.cy - o.y*m.scale;
    if (Math.hypot(sx - px, sy - py) < 14) return o;
  }
  return null;
}
function evtPos(e) {
  const r = cvs.getBoundingClientRect();
  const p = e.touches ? e.touches[0] : e;
  return { x: p.clientX - r.left, y: p.clientY - r.top };
}
function onDown(e) {
  const { x, y } = evtPos(e);
  const o = hitObject(x, y);
  if (o) { drag = o.name; cvs.classList.add('dragging'); e.preventDefault(); }
}
function onMove(e) {
  if (!drag) return;
  const { x, y } = evtPos(e);
  const w = worldFromScreen(x, y);
  fetch('/place', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({name: drag, x: w.x, y: w.y})});
  e.preventDefault();
}
function onUp() { drag = null; cvs.classList.remove('dragging'); }
cvs.addEventListener('mousedown', onDown);
cvs.addEventListener('mousemove', onMove);
window.addEventListener('mouseup', onUp);
cvs.addEventListener('touchstart', onDown, {passive:false});
cvs.addEventListener('touchmove', onMove, {passive:false});
window.addEventListener('touchend', onUp);

// --- trace ---
function addLine(text) {
  const div = document.createElement('div');
  let cls = '';
  if (text.startsWith('GOAL:')) cls = 't-goal';
  else if (text.startsWith('  think:')) cls = 't-think';
  else if (text.startsWith('  ->')) cls = 't-tool';
  else if (text.startsWith('DONE:')) cls = 't-done';
  else if (text.startsWith('CANCELLED')) cls = 't-cancel';
  else if (text.startsWith('ERROR')) cls = 't-err';
  else if (text.startsWith('USAGE:')) {
    cls = 't-usage';
    const m = text.match(/in=(\d+)\s+out=(\d+)\s+cost=\$([\d.]+)/);
    if (m) { usage = { in_tok:+m[1], out_tok:+m[2], cost:+m[3] }; draw(); }
  }
  div.className = cls;
  div.textContent = text;
  trace.appendChild(div);
  trace.scrollTop = trace.scrollHeight;

  if (text.startsWith('DONE:') || text.startsWith('CANCELLED') || text.startsWith('ERROR')) {
    if (typeof refreshMemory === 'function') refreshMemory();
    if (typeof autoAdvance === 'function') setTimeout(autoAdvance, 400);
  }

  // TTS for `say` tool calls
  const ttsOn = document.getElementById('tts').checked;
  if (ttsOn && text.includes('-> say(text=')) {
    const m = text.match(/text=(['"])((?:\\.|(?!\1).)*)\1/);
    if (m && 'speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(m[2]);
      u.rate = 1.05; window.speechSynthesis.speak(u);
    }
  }
}

const goBtn = document.getElementById('go');
const cancelBtn = document.getElementById('cancel');
goBtn.onclick = () => {
  const goal = document.getElementById('goal').value.trim();
  const key  = document.getElementById('key').value.trim();
  if (!goal) return;
  trace.innerHTML = '';
  usage = { in_tok:0, out_tok:0, cost:0 };
  goBtn.disabled = true; cancelBtn.disabled = false;
  const url = '/run?goal=' + encodeURIComponent(goal)
    + (key ? '&api_key=' + encodeURIComponent(key) : '');
  const es = new EventSource(url);
  es.onmessage = (e) => { const d = JSON.parse(e.data); addLine(d.line); refresh(); };
  es.addEventListener('end', () => { es.close(); goBtn.disabled=false; cancelBtn.disabled=true; });
  es.onerror = () => { addLine('ERROR: stream closed'); es.close(); goBtn.disabled=false; cancelBtn.disabled=true; };
};
cancelBtn.onclick = () => fetch('/cancel', {method:'POST'});
document.getElementById('reset').onclick = async () => {
  await fetch('/reset', {method:'POST'}); trace.innerHTML=''; usage = {in_tok:0,out_tok:0,cost:0}; refresh();
};
const estopBtn = document.getElementById('estop');
estopBtn.onclick = async () => {
  const active = !state?.emergency_stop;
  await fetch('/estop', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({active})});
  estopBtn.classList.toggle('active', active);
  refresh();
};
document.querySelectorAll('.examples span').forEach(el => {
  el.onclick = () => { document.getElementById('goal').value = el.textContent; };
});
document.getElementById('goal').addEventListener('keydown', e => {
  if (e.key === 'Enter') goBtn.click();
});

// --- mission queue ---
const queueEl = document.getElementById('queue');
const queue = [];
function renderQueue() {
  queueEl.innerHTML = '';
  queue.forEach((g, i) => {
    const div = document.createElement('div'); div.className = 'q-item';
    div.innerHTML = `<span><b>${i+1}.</b> ${escapeHtml(g)}</span>`;
    const x = document.createElement('button'); x.textContent = '×';
    x.onclick = () => { queue.splice(i,1); renderQueue(); };
    div.appendChild(x); queueEl.appendChild(div);
  });
}
function escapeHtml(s) { return s.replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
document.getElementById('queue-add').onclick = () => {
  const g = document.getElementById('goal').value.trim();
  if (!g) return;
  queue.push(g);
  document.getElementById('goal').value = '';
  renderQueue();
};

// --- voice input ---
const micBtn = document.getElementById('mic');
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SR) { micBtn.disabled = true; micBtn.title = 'speech recognition unsupported'; }
else {
  const rec = new SR();
  rec.lang = 'en-US'; rec.interimResults = false;
  let recording = false;
  micBtn.onclick = () => {
    if (recording) { rec.stop(); return; }
    try { rec.start(); recording = true; micBtn.classList.add('recording'); }
    catch(e) {}
  };
  rec.onresult = (e) => {
    const text = e.results[0][0].transcript;
    document.getElementById('goal').value = text;
    setTimeout(() => goBtn.click(), 80);
  };
  rec.onend = () => { recording = false; micBtn.classList.remove('recording'); };
  rec.onerror = () => { recording = false; micBtn.classList.remove('recording'); };
}

// --- memory display + clear ---
async function refreshMemory() {
  try {
    const r = await fetch('/memory'); const m = await r.json();
    const el = document.getElementById('memory'); el.innerHTML = '';
    for (const [k,v] of Object.entries(m)) {
      const d = document.createElement('div'); d.className = 'm-item';
      d.textContent = `${k}: ${v}`;
      el.appendChild(d);
    }
  } catch(e) {}
}
setInterval(refreshMemory, 1500); refreshMemory();
document.getElementById('forget').onclick = async () => {
  await fetch('/memory/clear', {method:'POST'}); refreshMemory();
};

// --- manifest + discrepancies ---
const manifestEl = document.getElementById('manifest');
const manifestCount = document.getElementById('manifest-count');
const discEl = document.getElementById('discrepancies');
let manifestDirty = false;
manifestEl.addEventListener('input', () => { manifestDirty = true; });
function renderManifest() {
  if (!state || manifestDirty) return;
  manifestEl.value = JSON.stringify(state.manifest || [], null, 2);
  manifestCount.textContent = (state.manifest || []).length;
}
function renderDiscrepancies() {
  if (!state) return;
  discEl.innerHTML = '';
  for (const d of (state.discrepancies || [])) {
    const div = document.createElement('div');
    div.className = 'd-item kind-' + d.kind;
    div.textContent = `${d.kind.toUpperCase()}: ${d.name}` + (d.note ? ` — ${d.note}` : '');
    discEl.appendChild(div);
  }
}
const _draw = draw;
draw = function() { _draw(); renderManifest(); renderDiscrepancies(); };

document.getElementById('manifest-save').onclick = async () => {
  try {
    const parsed = JSON.parse(manifestEl.value);
    await fetch('/manifest', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({manifest: parsed})});
    manifestDirty = false;
    refresh();
  } catch(e) { alert('Manifest JSON parse error: ' + e.message); }
};
document.getElementById('discrepancies-clear').onclick = async () => {
  await fetch('/discrepancies/clear', {method:'POST'}); refresh();
};

// --- wrap Run to auto-advance queue ---
const _origGo = goBtn.onclick;
goBtn.onclick = function() {
  const goal = document.getElementById('goal').value.trim();
  if (!goal && queue.length) {
    document.getElementById('goal').value = queue.shift();
    renderQueue();
  }
  _origGo.call(this);
};
function autoAdvance() {
  if (queue.length && !goBtn.disabled) {
    document.getElementById('goal').value = queue.shift();
    renderQueue();
    setTimeout(() => goBtn.click(), 600);
  }
}
</script>
</body></html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
