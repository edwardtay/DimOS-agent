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
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<style>
 :root {
   color-scheme: light;
   --bg:#ffffff; --panel:#f7f8fa; --grid:#eef0f3; --grid-strong:#dde1e7;
   --border:#e3e6eb; --text:#1a1f29; --muted:#6b7480;
   --accent:#2a6df4; --accent-soft:rgba(42,109,244,0.10);
   --goal:#2a6df4; --think:#6b7480; --tool:#1f8a4c; --done:#b4791a; --err:#c43030;
   --chip:#eef2f8; --chip-hover:#dde6f5; --chip-text:#3a4a63;
 }
 * { box-sizing: border-box; }
 html, body { height: 100%; }
 body { margin:0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
   background:var(--bg); color:var(--text); -webkit-text-size-adjust:100%; }
 header { padding:14px 18px; border-bottom:1px solid var(--border);
   display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
 header h1 { font-size:14px; margin:0; letter-spacing:.04em; font-weight:600; }
 main { display:grid; grid-template-columns: 460px 1fr; gap:0; height: calc(100dvh - 53px); }
 #left { border-right:1px solid var(--border); display:flex; flex-direction:column;
   background:var(--panel); min-height:0; }
 #right { position:relative; background:var(--bg); min-height:0; }
 canvas { background:var(--bg); display:block; width:100%; height:100%; }
 .panel { padding:14px 16px; border-top:1px solid var(--border); background:var(--panel); }
 .panel:first-child { border-top:none; }
 .row { display:flex; gap:8px; }
 input[type=text], input[type=password] {
   flex:1; min-width:0; padding:10px 12px; background:#fff; border:1px solid var(--border);
   color:var(--text); border-radius:8px; font: inherit; font-size:14px;
 }
 input:focus { outline:2px solid var(--accent-soft); border-color:var(--accent); }
 button { padding:10px 14px; background:var(--accent); color:#fff; border:none;
   border-radius:8px; cursor:pointer; font: inherit; font-size:14px; white-space:nowrap; }
 button.secondary { background:#fff; color:var(--text); border:1px solid var(--border); }
 button:disabled { opacity:.55; cursor:wait; }
 #trace { flex:1; overflow:auto; padding:12px 16px; font-size:12.5px;
   line-height:1.55; white-space:pre-wrap; background:#fff;
   -webkit-overflow-scrolling: touch; }
 .t-goal { color:var(--goal); font-weight:600; }
 .t-think { color:var(--think); }
 .t-tool { color:var(--tool); }
 .t-done { color:var(--done); font-weight:600; }
 .t-err  { color:var(--err); }
 .kv { color:var(--muted); font-size:12px; }
 .examples { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
 .examples span { font-size:12px; padding:5px 10px; background:var(--chip);
   border-radius:999px; cursor:pointer; color:var(--chip-text); }
 .examples span:hover { background:var(--chip-hover); }
 #hud { position:absolute; top:10px; left:14px; right:14px;
   font-size:12px; color:var(--muted); pointer-events:none; }

 @media (max-width: 800px) {
   header h1 + .kv { display:none; }
   main { grid-template-columns: 1fr; grid-template-rows: 44vh 1fr; height: calc(100dvh - 53px); }
   #left { border-right:none; border-top:1px solid var(--border); order:2; }
   #right { order:1; border-bottom:1px solid var(--border); }
   #trace { font-size:12px; padding:10px 14px; }
   .panel { padding:12px 14px; }
   .row { flex-wrap:wrap; }
   .row > input { flex: 1 1 100%; }
   .row > button { flex: 1 1 auto; }
   .examples span { font-size:12.5px; padding:6px 11px; }
   input, button { font-size:16px; }  /* avoid iOS zoom */
 }
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
  <div id="right">
    <canvas id="map"></canvas>
    <div id="hud"></div>
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
  const css = getComputedStyle(document.documentElement);
  const cGrid = css.getPropertyValue('--grid').trim() || '#eef0f3';
  const cGridStrong = css.getPropertyValue('--grid-strong').trim() || '#dde1e7';
  const cAccent = css.getPropertyValue('--accent').trim() || '#2a6df4';
  const cText = css.getPropertyValue('--text').trim() || '#1a1f29';

  // scale so map fits viewport on mobile too
  const scale = Math.max(28, Math.min(70, Math.min(W, H) / 14));
  const cx = W/2, cy = H/2;
  ctx.strokeStyle = cGrid; ctx.lineWidth = 1;
  for (let i=-12;i<=12;i++){
    ctx.beginPath(); ctx.moveTo(cx+i*scale,0); ctx.lineTo(cx+i*scale,H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0,cy-i*scale); ctx.lineTo(W,cy-i*scale); ctx.stroke();
  }
  ctx.strokeStyle = cGridStrong;
  ctx.beginPath(); ctx.moveTo(cx,0); ctx.lineTo(cx,H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0,cy); ctx.lineTo(W,cy); ctx.stroke();

  // world objects
  const tagColor = { person:'#2a6df4', ball:'#d93636', chair:'#c98a14' };
  for (const o of state.world) {
    const px = cx + o.x*scale, py = cy - o.y*scale;
    ctx.fillStyle = tagColor[o.tag] || '#888';
    ctx.beginPath(); ctx.arc(px,py,7,0,Math.PI*2); ctx.fill();
    ctx.fillStyle = cText; ctx.font = '12px ui-monospace';
    ctx.fillText(o.name, px+11, py+4);
  }

  // robot
  const rx = cx + state.pose.x*scale, ry = cy - state.pose.y*scale;
  const h = state.pose.heading_deg * Math.PI/180;
  ctx.fillStyle = 'rgba(42,109,244,0.14)';
  ctx.beginPath();
  ctx.moveTo(rx,ry);
  ctx.arc(rx,ry, 5*scale, -h - Math.PI/4, -h + Math.PI/4);
  ctx.closePath(); ctx.fill();
  ctx.fillStyle = cAccent;
  ctx.beginPath(); ctx.arc(rx,ry,10,0,Math.PI*2); ctx.fill();
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
