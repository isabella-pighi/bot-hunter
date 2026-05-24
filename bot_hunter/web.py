from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .pipeline import run_pipeline


ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(_dashboard_html())
        elif parsed.path == "/api/summary":
            self._send_json(_read_json(ROOT / "artifacts" / "summary.json"))
        elif parsed.path == "/api/events":
            self._send_json(_read_json(ROOT / "artifacts" / "sample_events.json"))
        elif parsed.path == "/report":
            self._send_html((ROOT / "docs" / "analysis_report.html").read_text(encoding="utf-8"))
        elif parsed.path == "/run":
            params = parse_qs(parsed.query)
            input_path = params.get("input", [""])[0]
            if not input_path:
                self._send_json({"error": "Pass ?input=/path/to/raw.tsv"}, status=400)
                return
            try:
                summary = run_pipeline(input_path, ROOT)
            except (OSError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)
            else:
                self._send_json(summary)
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str, status: int = 200) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _read_json(path: Path) -> object:
    if not path.exists():
        return {"error": f"{path.name} not found; run the pipeline first"}
    return json.loads(path.read_text(encoding="utf-8"))


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bot Hunter Dashboard</title>
  <style>
    :root { color-scheme: light; --ink:#172026; --muted:#5f6b74; --line:#d8dee4; --bg:#f7f9fb; --panel:#ffffff; --accent:#16697a; --warn:#b95000; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }
    header { background:#ffffff; border-bottom:1px solid var(--line); padding:22px 28px; display:flex; align-items:center; justify-content:space-between; gap:16px; }
    h1 { font-size:24px; margin:0; letter-spacing:0; }
    main { max-width:1240px; margin:0 auto; padding:26px; }
    .grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:20px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .metric { font-size:30px; font-weight:700; margin-top:8px; }
    .label { color:var(--muted); font-size:13px; }
    .wide { display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:20px; }
    .bar { height:24px; background:#e7edf0; border-radius:4px; overflow:hidden; margin:8px 0 13px; }
    .bar > span { display:block; height:100%; background:var(--accent); }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; vertical-align:top; }
    th { color:var(--muted); font-weight:600; }
    .score { font-variant-numeric:tabular-nums; font-weight:650; }
    .bot { color:var(--warn); }
    .actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    a, button { color:#ffffff; background:var(--accent); border:0; border-radius:6px; padding:9px 12px; text-decoration:none; font-weight:650; cursor:pointer; }
    input { min-width:330px; padding:9px 10px; border:1px solid var(--line); border-radius:6px; }
    @media (max-width: 850px) { .grid, .wide { grid-template-columns:1fr; } header { align-items:flex-start; flex-direction:column; } input { min-width:100%; } }
  </style>
</head>
<body>
  <header>
    <h1>Bot Hunter</h1>
    <div class="actions">
      <input id="inputPath" value="/Users/isabella/Downloads/bot-hunter-dataset.tsv" aria-label="Input path">
      <button onclick="runPipeline()">Run</button>
      <a href="/report">Report</a>
    </div>
  </header>
  <main>
    <section class="grid" id="metrics"></section>
    <section class="wide">
      <div class="card"><h2>Top Bot Signals</h2><div id="reasons"></div></div>
      <div class="card"><h2>Flagged Regions</h2><div id="regions"></div></div>
    </section>
    <section class="card">
      <h2>Highest Risk Events</h2>
      <table>
        <thead><tr><th>Event</th><th>Time</th><th>Device</th><th>Domain</th><th>Query</th><th>Scores</th><th>Reasons</th></tr></thead>
        <tbody id="events"></tbody>
      </table>
    </section>
  </main>
  <script>
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      })[ch]);
    }
    async function load() {
      const [summary, events] = await Promise.all([fetch('/api/summary').then(r => r.json()), fetch('/api/events').then(r => r.json())]);
      if (summary.error) { document.getElementById('metrics').innerHTML = `<div class="card">${escapeHtml(summary.error)}</div>`; return; }
      renderSummary(summary);
      renderEvents(events);
    }
    function pct(x) { return (100 * x).toFixed(2) + '%'; }
    function renderSummary(s) {
      const metrics = [
        ['Events analyzed', s.total_events.toLocaleString()],
        ['Flagged bots', s.bot_events.toLocaleString()],
        ['Bot rate', pct(s.bot_rate)],
        ['Estimated fraud probability', pct(s.estimated_precision)]
      ];
      document.getElementById('metrics').innerHTML = metrics.map(([k,v]) => `<div class="card"><div class="label">${k}</div><div class="metric">${v}</div></div>`).join('');
      renderBars('reasons', s.top_reasons || []);
      renderBars('regions', s.bot_regions || []);
    }
    function renderBars(id, rows) {
      const max = Math.max(...rows.map(r => r[1]), 1);
      document.getElementById(id).innerHTML = rows.map(r => `<div class="label">${escapeHtml(r[0])} (${r[1].toLocaleString()})</div><div class="bar"><span style="width:${100*r[1]/max}%"></span></div>`).join('');
    }
    function renderEvents(events) {
      document.getElementById('events').innerHTML = events.slice(0, 80).map(e => `<tr>
        <td>${escapeHtml(e.event_id)}</td><td>${escapeHtml(e.event_time)}</td><td>${escapeHtml(e.region)}<br>${escapeHtml(e.browser)} / ${escapeHtml(e.os)}</td>
        <td>${escapeHtml(e.domain)}</td><td>${escapeHtml(e.query)}</td>
        <td class="score bot">combined ${escapeHtml(e.combined_score)}<br>rules ${escapeHtml(e.heuristic_score)}<br>ml ${escapeHtml(e.ml_score)}</td>
        <td>${(e.reasons || []).map(escapeHtml).join('<br>')}</td>
      </tr>`).join('');
    }
    async function runPipeline() {
      const input = encodeURIComponent(document.getElementById('inputPath').value);
      document.getElementById('metrics').innerHTML = '<div class="card">Running pipeline...</div>';
      const response = await fetch('/run?input=' + input);
      if (!response.ok) {
        const payload = await response.json();
        document.getElementById('metrics').innerHTML = `<div class="card">${escapeHtml(payload.error || 'Pipeline run failed')}</div>`;
        return;
      }
      await load();
    }
    load();
  </script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving Bot Hunter at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
