"""Small local web dashboard for live Jev runs and deterministic replays."""

from __future__ import annotations

import base64
import binascii
import copy
import json
import logging
import struct
import threading
import webbrowser
import zlib
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)


INITIAL_STATE: dict[str, Any] = {
    "status": "waiting",
    "kind": "run",
    "env": "SuperMarioBros-1-1-v0",
    "policy": "jev",
    "model": "jev-latest",
    "episode": 0,
    "episodes": 1,
    "decision": 0,
    "decisions_total": 0,
    "x": 40,
    "y": 176,
    "max_x": 40,
    "reward": 0.0,
    "time_remaining": 400,
    "flag_get": False,
    "action": "wait",
    "frames_executed": 0,
    "latency_ms": 0.0,
    "decision_detail": {},
    "events": [],
    "history": [],
    "x_history": [],
    "message": "Waiting for a run",
    "frame": "",
}


def frame_data_url(frame) -> str:
    """Encode an RGB emulator frame as a browser-ready PNG data URL."""
    return "data:image/png;base64," + base64.b64encode(frame_png_bytes(frame)).decode("ascii")


def frame_png_bytes(frame) -> bytes:
    """Encode an RGB emulator frame as PNG bytes."""
    height, width = frame.shape[:2]
    scanlines = b"".join(b"\x00" + frame[row].tobytes() for row in range(height))

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(scanlines, level=3))
    png += chunk(b"IEND", b"")
    return png


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jev Plays Super Mario Bros.</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #080b14;
      --surface: rgba(18, 24, 39, .88);
      --surface-2: rgba(25, 33, 53, .82);
      --line: rgba(152, 168, 206, .15);
      --text: #edf2ff;
      --muted: #8d99b5;
      --cyan: #55d6ff;
      --violet: #9d8cff;
      --green: #63e6a3;
      --yellow: #ffd166;
      --red: #ff7893;
      --shadow: 0 22px 70px rgba(0, 0, 0, .34);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 82% -10%, rgba(85, 214, 255, .16), transparent 31rem),
        radial-gradient(circle at -5% 55%, rgba(157, 140, 255, .12), transparent 28rem),
        var(--bg);
    }
    .shell { max-width: 1240px; margin: 0 auto; padding: 28px 24px 36px; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 28px; }
    .brand { display: flex; align-items: center; gap: 13px; }
    .brand-mark {
      width: 40px; height: 40px; display: grid; place-items: center;
      border: 1px solid rgba(85, 214, 255, .34); border-radius: 13px;
      color: var(--cyan); background: linear-gradient(145deg, rgba(85, 214, 255, .16), rgba(157, 140, 255, .16));
      box-shadow: 0 0 34px rgba(85, 214, 255, .11);
      font-weight: 700; letter-spacing: -.06em;
    }
    .brand h1 { margin: 0; font-size: 17px; font-weight: 650; letter-spacing: -.02em; }
    .brand p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
    .status {
      display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px;
      border: 1px solid var(--line); border-radius: 999px; color: var(--muted);
      background: rgba(18, 24, 39, .7); font-size: 12px; font-weight: 650; letter-spacing: .07em; text-transform: uppercase;
    }
    .status::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--yellow); box-shadow: 0 0 12px currentColor; }
    .status.live { color: var(--green); border-color: rgba(99, 230, 163, .3); }
    .status.live::before { background: var(--green); }
    .status.complete { color: var(--cyan); border-color: rgba(85, 214, 255, .3); }
    .status.complete::before { background: var(--cyan); }
    .status.error, .status.stopped { color: var(--red); border-color: rgba(255, 120, 147, .3); }
    .status.error::before, .status.stopped::before { background: var(--red); }
    .hero { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(280px, .75fr); gap: 16px; margin-bottom: 16px; }
    .panel { border: 1px solid var(--line); border-radius: 20px; background: var(--surface); box-shadow: var(--shadow); backdrop-filter: blur(18px); }
    .hero-panel { padding: 23px 24px 21px; }
    .eyebrow { margin: 0 0 10px; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
    .level-line { display: flex; align-items: baseline; justify-content: space-between; gap: 20px; }
    .level-line h2 { margin: 0; font-size: clamp(25px, 4vw, 38px); letter-spacing: -.045em; line-height: 1; font-weight: 650; }
    .level-line span { color: var(--muted); font-size: 13px; white-space: nowrap; }
    .progress-wrap { margin-top: 26px; }
    .progress-meta { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 12px; }
    .progress-meta strong { color: var(--text); font-weight: 600; }
    .track { height: 9px; margin-top: 10px; overflow: hidden; border-radius: 999px; background: rgba(141, 153, 181, .14); }
    .fill { height: 100%; width: 0%; border-radius: inherit; background: linear-gradient(90deg, var(--violet), var(--cyan)); box-shadow: 0 0 24px rgba(85, 214, 255, .28); transition: width .35s ease; }
    .hero-note { margin: 18px 0 0; color: var(--muted); font-size: 12px; }
    .hero-note strong { color: var(--text); font-weight: 550; }
    .decision-panel { padding: 21px; display: flex; flex-direction: column; justify-content: space-between; min-height: 185px; }
    .decision-head { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
    .decision-label { color: var(--muted); font-size: 12px; }
    .decision-number { color: var(--cyan); font-variant-numeric: tabular-nums; font-size: 30px; font-weight: 650; letter-spacing: -.04em; }
    .action { margin-top: 20px; color: var(--text); font-size: 23px; font-weight: 600; letter-spacing: -.04em; }
    .action span { color: var(--violet); }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
    .metric { padding: 16px 17px; min-height: 93px; }
    .metric-label { color: var(--muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    .metric-value { margin-top: 11px; color: var(--text); font-size: 23px; line-height: 1; font-weight: 600; letter-spacing: -.035em; font-variant-numeric: tabular-nums; }
    .metric-sub { margin-top: 8px; color: var(--muted); font-size: 11px; }
    .lower { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(300px, .8fr); gap: 16px; }
    .chart-panel, .feed-panel { padding: 20px; min-height: 320px; }
    .panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 17px; }
    .panel-head h3 { margin: 0; font-size: 14px; font-weight: 620; letter-spacing: -.015em; }
    .panel-head span { color: var(--muted); font-size: 11px; }
    .chart { width: 100%; height: 230px; display: block; overflow: visible; }
    .chart .gridline { stroke: rgba(141, 153, 181, .13); stroke-width: 1; }
    .chart .axis { fill: var(--muted); font-size: 10px; }
    .chart .line { fill: none; stroke: var(--cyan); stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; filter: drop-shadow(0 0 6px rgba(85, 214, 255, .35)); }
    .chart .dot { fill: var(--cyan); stroke: var(--bg); stroke-width: 2; }
    .empty { display: grid; place-items: center; height: 230px; color: var(--muted); font-size: 12px; }
    .feed { display: grid; gap: 8px; }
    .feed-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 9px 10px; border-radius: 11px; background: var(--surface-2); font-size: 12px; }
    .feed-row .num { color: var(--muted); font-variant-numeric: tabular-nums; }
    .feed-row .move { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .feed-row .move strong { color: var(--text); font-weight: 550; }
    .feed-row .move small { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; }
    .feed-row .x { color: var(--cyan); font-variant-numeric: tabular-nums; }
    .decision-details { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; }
    .chip { padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; color: var(--muted); background: rgba(141, 153, 181, .07); font-size: 11px; }
    .chip strong { color: var(--text); font-weight: 550; }
    .game-panel { padding: 20px; margin-bottom: 16px; }
    .game-stage { position: relative; display: grid; place-items: center; overflow: hidden; min-height: 280px; aspect-ratio: 256 / 240; border: 1px solid var(--line); border-radius: 13px; background: #05070d; }
    .game-stage img { display: block; width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; }
    .game-empty { color: var(--muted); font-size: 12px; }
    .game-empty[hidden], .game-stage img[hidden] { display: none; }
    footer { display: flex; justify-content: space-between; gap: 14px; margin-top: 18px; color: var(--muted); font-size: 11px; }
    @media (min-width: 1001px) {
      body { overflow: hidden; }
      .shell { max-width: 1440px; height: 100vh; padding: 18px 22px 12px; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 12px; overflow: hidden; }
      .topbar { margin-bottom: 0; min-height: 42px; }
      .workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(390px, .85fr); grid-template-rows: minmax(145px, auto) minmax(110px, auto) minmax(0, 1fr); gap: 12px 14px; min-height: 0; overflow: hidden; }
      .workspace > .game-panel { grid-column: 1; grid-row: 1 / span 3; min-height: 0; height: 100%; margin: 0; padding: 15px; display: flex; flex-direction: column; }
      .workspace > .game-panel .panel-head { margin-bottom: 10px; }
      .workspace > .game-panel .game-stage { flex: 1; min-height: 0; aspect-ratio: auto; }
      .workspace > .hero { grid-column: 2; grid-row: 1; grid-template-columns: 1fr; grid-template-rows: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; min-height: 0; margin: 0; }
      .workspace > .hero .hero-panel, .workspace > .hero .decision-panel { min-height: 0; padding: 14px 16px; }
      .workspace > .hero .progress-wrap { margin-top: 16px; }
      .workspace > .hero .hero-note { margin-top: 12px; }
      .workspace > .hero .decision-panel { min-height: 0; }
      .workspace > .hero .action { margin-top: 10px; font-size: 19px; }
      .workspace > .hero .decision-details { margin-top: 8px; gap: 6px; }
      .workspace > .hero .chip { padding: 4px 6px; }
      .workspace > .grid { grid-column: 2; grid-row: 2; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; min-height: 0; margin: 0; }
      .workspace > .grid .metric { min-height: 0; padding: 11px 13px; }
      .workspace > .grid .metric-value { margin-top: 8px; font-size: 20px; }
      .workspace > .grid .metric-sub { margin-top: 5px; }
      .workspace > .lower { grid-column: 2; grid-row: 3; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; min-height: 0; margin: 0; }
      .workspace > .lower .chart-panel, .workspace > .lower .feed-panel { min-height: 0; padding: 13px; overflow: hidden; }
      .workspace > .lower .panel-head { margin-bottom: 9px; }
      .workspace > .lower .chart { height: 150px; }
      .workspace > .lower .empty { height: 150px; }
      .workspace > .lower .feed { gap: 5px; }
      .workspace > .lower .feed-row { grid-template-columns: 32px minmax(0, 1fr) auto; gap: 6px; padding: 6px 7px; font-size: 10px; }
      .workspace > .lower .feed-row .move small { margin-top: 2px; font-size: 9px; }
      footer { margin-top: 0; }
    }
    @media (min-width: 1001px) and (max-height: 720px) {
      .shell { padding-top: 10px; padding-bottom: 8px; gap: 8px; }
      .workspace { gap: 8px 10px; grid-template-rows: minmax(125px, auto) minmax(95px, auto) minmax(0, 1fr); }
      .workspace > .game-panel { padding: 11px; }
      .workspace > .hero .hero-panel, .workspace > .hero .decision-panel { padding: 10px 12px; }
      .workspace > .hero .eyebrow { margin-bottom: 6px; }
      .workspace > .hero .progress-wrap { margin-top: 10px; }
      .workspace > .hero .hero-note { margin-top: 8px; }
      .workspace > .grid { gap: 7px; }
      .workspace > .grid .metric { padding: 8px 10px; }
      .workspace > .lower .chart { height: 120px; }
      .workspace > .lower .empty { height: 120px; }
    }
    @media (max-width: 1000px) {
      .workspace { display: block; }
      .workspace > .game-panel { margin-bottom: 16px; }
      .workspace > .hero, .workspace > .grid, .workspace > .lower { margin-bottom: 16px; }
    }
    @media (max-width: 850px) { .hero, .lower { grid-template-columns: 1fr; } .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 500px) { .shell { padding: 20px 14px 28px; } .topbar { margin-bottom: 20px; } .grid { gap: 8px; } .metric { padding: 13px; } .metric-value { font-size: 19px; } .level-line { display: block; } .level-line span { display: block; margin-top: 9px; } }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">J</div>
        <div><h1>Jev Plays Super Mario Bros.</h1><p>Super Mario Bros. control telemetry</p></div>
      </div>
      <div id="status" class="status">WAITING</div>
    </header>

    <div class="workspace">
    <section class="hero">
      <div class="panel hero-panel">
        <p class="eyebrow">Current mission</p>
        <div class="level-line"><h2 id="level">World 1-1</h2><span id="policy">Jev · jev-latest</span></div>
        <div class="progress-wrap">
          <div class="progress-meta"><span>Level progress</span><strong id="progress-text">0%</strong></div>
          <div class="track" role="progressbar" aria-label="Level progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div id="progress" class="fill"></div></div>
        </div>
        <p id="message" class="hero-note">Waiting for a run.</p>
      </div>
      <div class="panel decision-panel">
        <div class="decision-head"><span class="decision-label">Decision stream</span><strong id="decision" class="decision-number">—</strong></div>
        <div id="action" class="action">Standing by <span>·</span></div>
        <div id="decision-details" class="decision-details"></div>
      </div>
    </section>

    <section class="panel game-panel">
      <div class="panel-head"><h3>Live emulator</h3><span id="frame-meta">waiting for frame</span></div>
      <div class="game-stage"><img id="game-frame" alt="Current Super Mario Bros. emulator frame" hidden><div id="game-empty" class="game-empty">The emulator frame will appear when the run starts.</div></div>
    </section>

    <section class="grid" aria-label="Live metrics">
      <div class="panel metric"><div class="metric-label">Mario X</div><div id="x" class="metric-value">40 px</div><div class="metric-sub">furthest <span id="max-x">40</span> px</div></div>
      <div class="panel metric"><div class="metric-label">Vertical</div><div id="y" class="metric-value">176 px</div><div id="motion" class="metric-sub">position</div></div>
      <div class="panel metric"><div class="metric-label">Reward</div><div id="reward" class="metric-value">0</div><div class="metric-sub">episode total</div></div>
      <div class="panel metric"><div class="metric-label">Jev latency</div><div id="latency" class="metric-value">—</div><div id="frames" class="metric-sub">frames per action</div></div>
    </section>

    <section class="lower">
      <div class="panel chart-panel">
        <div class="panel-head"><h3>Position trace</h3><span id="chart-meta">waiting for telemetry</span></div>
        <div id="chart-empty" class="empty">The trace will appear when the run starts.</div>
        <svg id="chart" class="chart" viewBox="0 0 760 230" role="img" aria-label="Mario horizontal position over decisions" hidden>
          <line class="gridline" x1="44" y1="24" x2="742" y2="24"/><line class="gridline" x1="44" y1="124" x2="742" y2="124"/><line class="gridline" x1="44" y1="224" x2="742" y2="224"/>
          <text class="axis" x="7" y="28">x max</text><text class="axis" x="17" y="128">x/2</text><text class="axis" x="24" y="228">0</text>
          <text class="axis" x="44" y="229">start</text><text id="chart-end" class="axis" x="716" y="229">now</text>
          <polyline id="chart-line" class="line" points=""/><circle id="chart-dot" class="dot" cx="44" cy="224" r="4"/>
        </svg>
      </div>
      <div class="panel feed-panel">
        <div class="panel-head"><h3>Recent decisions</h3><span id="feed-meta">0 actions</span></div>
        <div id="feed" class="feed"><div class="empty" style="height: 230px">No decisions yet.</div></div>
      </div>
    </section>
    </div>
    <footer><span id="episode">Episode 1 of 1</span><span id="updated">Waiting for connection</span></footer>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    const envLabel = (env) => { const m = String(env || '').match(/SuperMarioBros-(\d+)-(\d+)/); return m ? `World ${m[1]}-${m[2]}` : env || 'Mario'; };
    const pct = (state) => Math.max(0, Math.min(100, Math.round((Number(state.max_x || state.x || 0) / 3161) * 100)));
    function renderChart(points) {
      const chart = $('chart');
      if (!points || points.length < 2) { chart.hidden = true; $('chart-empty').hidden = false; return; }
      chart.hidden = false; $('chart-empty').hidden = true;
      const values = points.map((p) => Number(p.x || 0));
      const ceiling = Math.max(100, ...values);
      const left = 44, right = 742, top = 24, bottom = 224;
      const path = points.map((p, i) => {
        const x = left + (i / Math.max(1, points.length - 1)) * (right - left);
        const y = bottom - (Number(p.x || 0) / ceiling) * (bottom - top);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ');
      $('chart-line').setAttribute('points', path);
      const last = path.split(' ').at(-1).split(',');
      $('chart-dot').setAttribute('cx', last[0]); $('chart-dot').setAttribute('cy', last[1]);
      $('chart-meta').textContent = `${points.length} samples · max ${Math.round(ceiling)} px`;
    }
    function renderFeed(history) {
      const rows = (history || []).slice(-7).reverse();
      $('feed-meta').textContent = `${history?.length || 0} actions`;
      $('feed').innerHTML = rows.length ? rows.map((item) => {
        const events = (item.events || []).join(' · ') || 'steady movement';
        return `<div class="feed-row"><span class="num">#${esc(item.decision)}</span><div class="move"><strong>${esc(item.action)}</strong><small>${esc(events)}</small></div><span class="x">${Math.round(Number(item.x || 0))} px</span></div>`;
      }).join('') : '<div class="empty" style="height: 230px">No decisions yet.</div>';
    }
    function render(state) {
      const status = String(state.status || 'waiting');
      $('status').textContent = status.toUpperCase(); $('status').className = `status ${status}`;
      $('level').textContent = envLabel(state.env); $('policy').textContent = `${state.policy || 'run'} · ${state.model || 'local'}`;
      const progress = pct(state); $('progress').style.width = `${progress}%`; $('progress-text').textContent = `${progress}%`;
      $('progress').parentElement.parentElement.setAttribute('aria-valuenow', progress);
      $('message').innerHTML = esc(state.message || (state.flag_get ? 'Flag reached.' : 'Run in progress.'));
      $('decision').textContent = state.decision ?? '—'; $('action').innerHTML = `${esc(state.action || 'Standing by')} <span>·</span>`;
      const details = state.decision_detail || {};
      $('decision-details').innerHTML = [
        ['movement', details.movement], ['jump', details.jump_pressed ? 'pressed' : 'released'], ['source', details.jump_timing_source]
      ].filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => `<span class="chip">${esc(k)} <strong>${esc(v)}</strong></span>`).join('');
      $('x').textContent = `${Math.round(Number(state.x || 0))} px`; $('max-x').textContent = Math.round(Number(state.max_x || 0));
      $('y').textContent = `${Math.round(Number(state.y || 0))} px`; $('motion').textContent = state.motion || 'position';
      $('reward').textContent = Number(state.reward || 0).toFixed(0); $('latency').textContent = state.latency_ms ? `${Math.round(state.latency_ms)} ms` : '—';
      $('frames').textContent = state.frames_executed ? `${state.frames_executed} frames per action` : 'frames per action';
      $('episode').textContent = `Episode ${Number(state.episode || 0) + 1} of ${state.episodes || 1}`;
      $('updated').textContent = state.updated_at ? `Updated ${new Date(state.updated_at).toLocaleTimeString()}` : 'Connected';
      renderChart(state.x_history); renderFeed(state.history);
    }
    let activeFrameUrl = '';
    async function pollFrame() {
      try {
        const response = await fetch(`/api/frame?tick=${Date.now()}`, {cache: 'no-store'});
        if (response.ok) {
          const nextUrl = URL.createObjectURL(await response.blob());
          const previousUrl = activeFrameUrl; activeFrameUrl = nextUrl;
          $('game-frame').src = nextUrl; $('game-frame').hidden = false; $('game-empty').hidden = true;
          $('frame-meta').textContent = 'live frame · 30 fps target';
          if (previousUrl) URL.revokeObjectURL(previousUrl);
        }
      } catch (_) { /* the telemetry loop reports reconnects */ }
      setTimeout(pollFrame, 33);
    }
    async function poll() {
      try { const response = await fetch('/api/state', {cache: 'no-store'}); if (response.ok) render(await response.json()); }
      catch (_) { $('updated').textContent = 'Reconnecting…'; }
      setTimeout(poll, 250);
    }
    pollFrame(); poll();
  </script>
</body>
</html>
"""


class _DashboardHandler(BaseHTTPRequestHandler):
    server: _DashboardHTTPServer

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route == "/api/state":
            body = json.dumps(self.server.dashboard_state(), separators=(",", ":")).encode()
            content_type = "application/json; charset=utf-8"
        elif route == "/api/frame":
            body = self.server.dashboard_frame()
            if not body:
                self.send_response(204)
                self.end_headers()
                return
            content_type = "image/png"
        elif route in {"/", "/index.html"}:
            body = HTML.encode()
            content_type = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class _DashboardHTTPServer(ThreadingHTTPServer):
    def __init__(self, address, state):
        super().__init__(address, _DashboardHandler)
        self._state = state
        self._state_lock = threading.Lock()
        self._frame = b""

    def dashboard_state(self):
        with self._state_lock:
            return copy.deepcopy(self._state)

    def publish(self, update):
        with self._state_lock:
            self._state.update(copy.deepcopy(update))

    def publish_frame(self, frame):
        with self._state_lock:
            self._frame = frame
            self._state["frame_ready"] = True

    def dashboard_frame(self):
        with self._state_lock:
            return self._frame


class DashboardServer:
    """Threaded dashboard server with a tiny publish API for the emulator loop."""

    def __init__(self, port=8765, open_browser=True):
        self.port = port
        self.open_browser = open_browser
        self._server: _DashboardHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def start(self):
        if self._server is not None:
            return self
        self._server = _DashboardHTTPServer(("127.0.0.1", self.port), copy.deepcopy(INITIAL_STATE))
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        self._thread = threading.Thread(target=self._server.serve_forever, name="jev-dashboard", daemon=True)
        self._thread.start()
        print(f"Dashboard: {self.url}")
        if self.open_browser:
            try:
                webbrowser.open(self.url, new=2)
            except Exception:
                logger.debug("Could not open dashboard in a browser", exc_info=True)
        return self

    def publish(self, update):
        if self._server is not None:
            frame = update.pop("frame", None)
            if frame:
                prefix, encoded = frame.split(",", 1)
                if prefix == "data:image/png;base64":
                    self.publish_frame(base64.b64decode(encoded))
            self._server.publish({"updated_at": datetime.now().astimezone().isoformat(), **update})

    def publish_frame(self, frame):
        if self._server is not None:
            self._server.publish_frame(frame_png_bytes(frame))

    def stop(self):
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._server = None
        self._thread = None
