"""Localhost demo for the DimOS prototype.

Run:  python -m dimos_proto.server
Open: http://localhost:8000

Streams agent steps via SSE and renders the Go2 + world on an HTML canvas.
"""
from __future__ import annotations

import json
import os
import queue
import threading
from typing import Iterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from .agent import run as agent_run
from .go2_sim import Go2Sim

app = FastAPI()
ROBOT = Go2Sim()
LOCK = threading.Lock()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/state")
def state() -> JSONResponse:
    with LOCK:
        return JSONResponse({
            "pose": {"x": ROBOT.x, "y": ROBOT.y, "heading_deg": ROBOT.heading_deg},
            "battery": ROBOT.battery,
            "posture": ROBOT.posture,
            "world": [{"name": o.name, "tag": o.tag, "x": o.x, "y": o.y}
                      for o in ROBOT.world],
            "log_tail": ROBOT.log[-12:],
        })


@app.post("/reset")
def reset() -> dict:
    global ROBOT
    with LOCK:
        ROBOT = Go2Sim()
    return {"ok": True}


@app.get("/run")
def run_goal(goal: str, api_key: str | None = None) -> StreamingResponse:
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    q: queue.Queue[str | None] = queue.Queue()

    def worker() -> None:
        try:
            for line in agent_run(goal, ROBOT):
                q.put(line)
        except Exception as e:  # surface errors to the client
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
            payload = json.dumps({"line": item})
            yield f"data: {payload}\n\n".encode()

    return StreamingResponse(sse(), media_type="text/event-stream")


INDEX_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>DimOS Prototype</title>
<style>
 :root { color-scheme: dark; }
 body { margin:0; font-family: ui-monospace, Menlo, monospace; background:#0b0d10; color:#dbe3ea; }
 header { padding:14px 20px; border-bottom:1px solid #1f2630; display:flex; gap:14px; align-items:center; }
 header h1 { font-size:15px; margin:0; letter-spacing:.04em; }
 main { display:grid; grid-template-columns: 480px 1fr; gap:0; height: calc(100vh - 52px); }
 #left { border-right:1px solid #1f2630; display:flex; flex-direction:column; }
 canvas { background:#11151b; display:block; }
 .panel { padding:14px 18px; border-top:1px solid #1f2630; }
 .panel:first-child { border-top:none; }
 .row { display:flex; gap:10px; }
 input[type=text], input[type=password] {
   flex:1; padding:9px 11px; background:#11151b; border:1px solid #243040;
   color:#dbe3ea; border-radius:6px; font: inherit;
 }
 button { padding:9px 14px; background:#2a6df4; color:white; border:none;
   border-radius:6px; cursor:pointer; font: inherit; }
 button.secondary { background:#243040; }
 button:disabled { opacity:.5; cursor:wait; }
 #trace { flex:1; overflow:auto; padding:14px 18px; font-size:12.5px; line-height:1.55; white-space:pre-wrap; }
 .t-goal { color:#7fc7ff; }
 .t-think { color:#9aa4ad; }
 .t-tool { color:#b6f0a3; }
 .t-done { color:#ffd479; font-weight:600; }
 .t-err  { color:#ff7a7a; }
 .kv { color:#9aa4ad; font-size:12px; }
 .kv b { color:#dbe3ea; font-weight:500; }
 .examples { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
 .examples span { font-size:11.5px; padding:4px 9px; background:#1a2230;
   border-radius:999px; cursor:pointer; color:#9fb3cc; }
 .examples span:hover { background:#243246; color:#fff; }
</style></head>
<body>
<header>
  <h1>DIMOS · GO2 PROTOTYPE</h1>
  <span class="kv">localhost simulator · Claude agent loop</span>
</header>
<main>
  <div id="left">
    <div class="panel">
      <div class="row">
        <input id="key" type="password" placeholder="ANTHROPIC_API_KEY (kept in this tab only)" />
      </div>
      <div class="row" style="margin-top:8px;">
        <input id="goal" type="text" placeholder='e.g. "find alice and say hello"' />
        <button id="go">Run</button>
        <button id="reset" class="secondary">Reset</button>
      </div>
      <div class="examples">
        <span>find alice and say hello</span>
        <span>look around and report what you see</span>
        <span>walk to the red ball</span>
        <span>sit down then stand back up</span>
      </div>
    </div>
    <div id="trace"></div>
  </div>
  <div style="position:relative;">
    <canvas id="map" width="900" height="900"></canvas>
    <div id="hud" style="position:absolute; top:12px; left:14px; font-size:12px; color:#9aa4ad;"></div>
  </div>
</main>
<script>
const cvs = document.getElementById('map');
const ctx = cvs.getContext('2d');
const trace = document.getElementById('trace');
const hud = document.getElementById('hud');
let state = null;

function fitCanvas() {
  const r = cvs.getBoundingClientRect();
  cvs.width = r.width * devicePixelRatio;
  cvs.height = r.height * devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
}
window.addEventListener('resize', () => { fitCanvas(); draw(); });

function draw() {
  if (!state) return;
  const W = cvs.width / devicePixelRatio, H = cvs.height / devicePixelRatio;
  ctx.clearRect(0,0,W,H);
  // grid
  const scale = 60; // px per meter
  const cx = W/2, cy = H/2;
  ctx.strokeStyle = '#1a2230'; ctx.lineWidth = 1;
  for (let i=-10;i<=10;i++){
    ctx.beginPath(); ctx.moveTo(cx+i*scale,0); ctx.lineTo(cx+i*scale,H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0,cy-i*scale); ctx.lineTo(W,cy-i*scale); ctx.stroke();
  }
  ctx.strokeStyle = '#2a3648';
  ctx.beginPath(); ctx.moveTo(cx,0); ctx.lineTo(cx,H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0,cy); ctx.lineTo(W,cy); ctx.stroke();

  // world objects
  const tagColor = { person:'#7fc7ff', ball:'#ff7a7a', chair:'#ffd479' };
  for (const o of state.world) {
    const px = cx + o.x*scale, py = cy - o.y*scale;
    ctx.fillStyle = tagColor[o.tag] || '#aaa';
    ctx.beginPath(); ctx.arc(px,py,8,0,Math.PI*2); ctx.fill();
    ctx.fillStyle = '#dbe3ea'; ctx.font = '12px ui-monospace';
    ctx.fillText(o.name, px+12, py+4);
  }

  // robot
  const rx = cx + state.pose.x*scale, ry = cy - state.pose.y*scale;
  const h = state.pose.heading_deg * Math.PI/180;
  // FOV cone
  ctx.fillStyle = 'rgba(42,109,244,0.12)';
  ctx.beginPath();
  ctx.moveTo(rx,ry);
  ctx.arc(rx,ry, 5*scale, -h - Math.PI/4, -h + Math.PI/4);
  ctx.closePath(); ctx.fill();
  // body
  ctx.fillStyle = '#2a6df4';
  ctx.beginPath(); ctx.arc(rx,ry,11,0,Math.PI*2); ctx.fill();
  // heading
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(rx,ry);
  ctx.lineTo(rx + Math.cos(-h)*18, ry + Math.sin(-h)*18); ctx.stroke();

  hud.innerHTML = `pose (${state.pose.x.toFixed(2)}, ${state.pose.y.toFixed(2)})
    · heading ${state.pose.heading_deg.toFixed(0)}°
    · posture ${state.posture}
    · battery ${state.battery.toFixed(1)}%`;
}

async function refresh() {
  const r = await fetch('/state'); state = await r.json(); draw();
}
setInterval(refresh, 600); refresh(); fitCanvas();

function addLine(text) {
  const div = document.createElement('div');
  let cls = '';
  if (text.startsWith('GOAL:')) cls = 't-goal';
  else if (text.startsWith('  think:')) cls = 't-think';
  else if (text.startsWith('  ->')) cls = 't-tool';
  else if (text.startsWith('DONE:')) cls = 't-done';
  else if (text.startsWith('ERROR')) cls = 't-err';
  div.className = cls;
  div.textContent = text;
  trace.appendChild(div);
  trace.scrollTop = trace.scrollHeight;
}

document.getElementById('go').onclick = () => {
  const goal = document.getElementById('goal').value.trim();
  const key  = document.getElementById('key').value.trim();
  if (!goal) return;
  trace.innerHTML = '';
  const btn = document.getElementById('go'); btn.disabled = true;
  const url = '/run?goal=' + encodeURIComponent(goal)
    + (key ? '&api_key=' + encodeURIComponent(key) : '');
  const es = new EventSource(url);
  es.onmessage = (e) => { const d = JSON.parse(e.data); addLine(d.line); refresh(); };
  es.addEventListener('end', () => { es.close(); btn.disabled = false; });
  es.onerror = () => { addLine('ERROR: stream closed'); es.close(); btn.disabled = false; };
};
document.getElementById('reset').onclick = async () => {
  await fetch('/reset', {method:'POST'}); trace.innerHTML=''; refresh();
};
document.querySelectorAll('.examples span').forEach(el => {
  el.onclick = () => { document.getElementById('goal').value = el.textContent; };
});
document.getElementById('goal').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('go').click();
});
</script>
</body></html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
