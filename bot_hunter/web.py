from __future__ import annotations

import argparse
import json
import tempfile
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
        elif parsed.path == "/api/features":
            params = parse_qs(parsed.query)
            offset = _parse_int(params.get("offset", ["0"])[0], default=0)
            limit = min(_parse_int(params.get("limit", ["200"])[0], default=200), 1000)
            self._send_json(_read_features(ROOT / "artifacts" / "features.tsv", offset=offset, limit=limit))
        elif parsed.path == "/features":
            self._send_html(_features_html())
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/upload":
            self.send_error(404)
            return

        content_type = self.headers.get("Content-Type", "")
        content_length = _parse_int(self.headers.get("Content-Length", "0"), default=0)
        if content_length <= 0:
            self._send_json({"error": "Upload a TSV file before running the pipeline"}, status=400)
            return

        body = self.rfile.read(content_length)
        try:
            fields, files = _parse_multipart_form(content_type, body)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        upload = files.get("file")
        if not upload or not upload.get("filename"):
            self._send_json({"error": "Upload a TSV file before running the pipeline"}, status=400)
            return

        suffix = Path(upload.get("filename") or "upload.tsv").suffix or ".tsv"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as handle:
                handle.write(upload["content"])
                tmp_path = Path(handle.name)
            summary = run_pipeline(tmp_path, ROOT)
        except (OSError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
        else:
            self._send_json(summary)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

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


def _parse_int(value: str, default: int) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return default


def _parse_multipart_form(content_type: str, body: bytes) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    marker = "boundary="
    if "multipart/form-data" not in content_type or marker not in content_type:
        raise ValueError("Upload request must use multipart/form-data")
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    if not boundary:
        raise ValueError("Upload request is missing a multipart boundary")

    fields: dict[str, str] = {}
    files: dict[str, dict[str, object]] = {}
    boundary_bytes = ("--" + boundary).encode("utf-8")
    for part in body.split(boundary_bytes):
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"--\r\n"):
            part = part[:-4]
        elif part.endswith(b"--"):
            part = part[:-2]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, content = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", errors="replace").split("\r\n")
        disposition = next((line for line in headers if line.lower().startswith("content-disposition:")), "")
        params = _parse_content_disposition(disposition)
        name = params.get("name")
        if not name:
            continue
        filename = params.get("filename")
        if filename is not None:
            files[name] = {"filename": filename, "content": content}
        else:
            fields[name] = content.decode("utf-8", errors="replace")
    return fields, files


def _parse_content_disposition(header: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in header.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        params[key.strip().lower()] = value.strip().strip('"')
    return params


def _read_features(path: Path, offset: int = 0, limit: int = 200) -> object:
    if not path.exists():
        return {"error": f"{path.name} not found; run the pipeline first"}
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        feature_names = header[1:]
        rows = []
        for idx, line in enumerate(handle):
            if idx < offset:
                continue
            if len(rows) >= limit:
                break
            parts = line.rstrip("\n").split("\t")
            if len(parts) != len(header):
                continue
            rows.append({"event_id": parts[0], "features": [float(value) for value in parts[1:]]})
    return {
        "feature_names": feature_names,
        "offset": offset,
        "limit": limit,
        "rows": rows,
        "next_offset": offset + len(rows),
    }


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bot Hunter Dashboard</title>
  <style>
    :root { color-scheme: light; --ink:#172026; --muted:#5f6b74; --line:#d8dee4; --bg:#f7f9fb; --panel:#ffffff; --accent:#16697a; --accent-weak:#e5f1f3; --warn:#b95000; }
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
    h2 { font-size:18px; margin:0 0 14px; }
    .bar { height:24px; background:#e7edf0; border-radius:4px; overflow:hidden; margin:8px 0 13px; }
    .bar > span { display:block; height:100%; background:var(--accent); }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; vertical-align:top; }
    th { color:var(--muted); font-weight:600; }
    .table-wrap { overflow:auto; }
    .wrap { max-width:240px; overflow-wrap:anywhere; }
    .score { font-variant-numeric:tabular-nums; font-weight:650; }
    .bot { color:var(--warn); }
    .actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    a, button, select, input { font:inherit; }
    a, button { color:#ffffff; background:var(--accent); border:0; border-radius:6px; padding:9px 12px; text-decoration:none; font-weight:650; cursor:pointer; }
    button.mode { color:var(--accent); background:var(--accent-weak); border:1px solid transparent; }
    button.mode[aria-pressed="true"] { color:#ffffff; background:var(--accent); }
    a.secondary { color:var(--accent); background:var(--accent-weak); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    input, select { min-height:38px; padding:8px 10px; border:1px solid var(--line); border-radius:6px; background:#ffffff; }
    input { width:min(420px, 42vw); }
    select { color:var(--ink); }
    .dataset { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    .mode-group { display:flex; gap:4px; padding:3px; border:1px solid var(--line); border-radius:8px; background:#ffffff; }
    .input-panel { display:block; }
    .input-panel.is-hidden { display:none; }
    .input-help { flex-basis:100%; color:var(--muted); font-size:12px; margin:3px 0 0; }
    @media (max-width: 850px) { .grid, .wide { grid-template-columns:1fr; } header { align-items:flex-start; flex-direction:column; } input { width:100%; } .actions, .dataset, .input-panel { width:100%; } .mode-group { width:100%; } .mode-group button { flex:1; } }
  </style>
</head>
<body>
  <header>
    <h1>Bot Hunter</h1>
    <div class="actions">
      <div class="dataset" aria-label="Dataset source">
        <div class="mode-group" role="group" aria-label="Dataset input mode">
          <button id="uploadModeButton" class="mode" type="button" aria-pressed="true" onclick="setInputMode('upload')">Upload TSV</button>
          <button id="pathModeButton" class="mode" type="button" aria-pressed="false" onclick="setInputMode('path')">Server path</button>
        </div>
        <div id="uploadInputPanel" class="input-panel">
          <input id="inputFile" class="dataset-field" type="file" accept=".tsv,text/tab-separated-values,text/plain" aria-label="Upload input TSV">
          <p class="input-help">Choose a local .tsv file to upload and analyze.</p>
        </div>
        <div id="pathInputPanel" class="input-panel is-hidden">
          <input id="inputPath" class="dataset-field" placeholder="/path/to/bot-hunter-dataset.tsv" aria-label="Input path">
          <p class="input-help">Use only when the TSV already exists on the machine running this dashboard.</p>
        </div>
      </div>
      <button id="runButton" onclick="runPipeline()">Run</button>
      <a class="secondary" href="/features">Features</a>
      <a class="secondary" href="/report">Report</a>
    </div>
  </header>
  <main>
    <section class="grid" id="metrics"></section>
    <section class="wide">
      <div class="card"><h2>Top Bot Signals</h2><div id="reasons"></div></div>
      <div class="card"><h2>Flagged Regions</h2><div id="regions"></div></div>
    </section>
    <section class="card" style="margin-bottom:20px;">
      <h2>Method Disagreement</h2>
      <div class="label" id="disagreementNote"></div>
      <div id="disagreement"></div>
    </section>
    <section class="card" style="margin-bottom:20px;">
      <h2>Operational Tiers</h2>
      <div id="tiers"></div>
    </section>
    <section class="card">
      <h2>Highest Risk Events</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Event</th><th>Time</th><th>Device</th><th>Domain</th><th>Query</th><th>Scores</th><th>Tier</th><th>Reasons</th></tr></thead>
        <tbody id="events"></tbody>
      </table></div>
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
        ['Operational confidence', pct(s.estimated_precision)]
      ];
      document.getElementById('metrics').innerHTML = metrics.map(([k,v]) => `<div class="card"><div class="label">${k}</div><div class="metric">${v}</div></div>`).join('');
      renderBars('reasons', s.top_reasons || []);
      renderBars('regions', s.bot_regions || []);
      renderBars('disagreement', s.method_disagreement || []);
      renderDisagreementNote(s);
      renderBars('tiers', Object.entries(s.tier_counts || {}));
    }
    function renderDisagreementNote(s) {
      const thresholds = s.tier_thresholds || {};
      const heuristic = Number(thresholds.suppress_agreement_heuristic_score ?? 0.62).toFixed(2);
      const ml = Number(thresholds.suppress_agreement_ml_score ?? 0.995).toFixed(3);
      document.getElementById('disagreementNote').textContent =
        `Buckets use rules >= ${heuristic} and EIF tail >= ${ml}. ML only means extreme EIF evidence without a high rules score.`;
    }
    function renderBars(id, rows) {
      const max = Math.max(...rows.map(r => r[1]), 1);
      document.getElementById(id).innerHTML = rows.map(r => `<div class="label">${escapeHtml(r[0])} (${r[1].toLocaleString()})</div><div class="bar"><span style="width:${100*r[1]/max}%"></span></div>`).join('');
    }
    function renderEvents(events) {
      document.getElementById('events').innerHTML = events.slice(0, 80).map(e => `<tr>
        <td>${escapeHtml(e.event_id)}</td><td>${escapeHtml(e.event_time)}</td><td>${escapeHtml(e.region)}<br>${escapeHtml(e.browser)} / ${escapeHtml(e.os)}</td>
        <td class="wrap">${escapeHtml(e.domain)}</td><td class="wrap">${escapeHtml(e.query)}</td>
        <td class="score bot">combined ${escapeHtml(e.combined_score)}<br>rules ${escapeHtml(e.heuristic_score)}<br>ml ${escapeHtml(e.ml_score)}</td>
        <td>${escapeHtml(e.operational_tier)}</td>
        <td class="wrap">${(e.reasons || []).map(escapeHtml).join('<br>')}</td>
      </tr>`).join('');
    }
    let inputMode = 'upload';
    function setInputMode(mode) {
      inputMode = mode;
      const uploadMode = mode === 'upload';
      document.getElementById('uploadModeButton').setAttribute('aria-pressed', String(uploadMode));
      document.getElementById('pathModeButton').setAttribute('aria-pressed', String(!uploadMode));
      document.getElementById('uploadInputPanel').classList.toggle('is-hidden', !uploadMode);
      document.getElementById('pathInputPanel').classList.toggle('is-hidden', uploadMode);
      if (uploadMode) {
        document.getElementById('inputPath').value = '';
      } else {
        document.getElementById('inputFile').value = '';
      }
    }
    async function runPipeline() {
      const file = document.getElementById('inputFile').files[0];
      const inputPath = document.getElementById('inputPath').value.trim();
      if (inputMode === 'upload' && !file) {
        document.getElementById('metrics').innerHTML = '<div class="card">Choose a TSV file before running the pipeline.</div>';
        return;
      }
      if (inputMode === 'path' && !inputPath) {
        document.getElementById('metrics').innerHTML = '<div class="card">Enter a file path before running the pipeline.</div>';
        return;
      }
      document.getElementById('runButton').disabled = true;
      document.getElementById('metrics').innerHTML = '<div class="card">Running pipeline...</div>';
      try {
        // Only the active mode is submitted; the other input is ignored regardless of its state.
        const response = inputMode === 'upload' ? await uploadAndRun(file) : await runPath(inputPath);
        if (!response.ok) {
          const payload = await response.json();
          document.getElementById('metrics').innerHTML = `<div class="card">${escapeHtml(payload.error || 'Pipeline run failed')}</div>`;
          return;
        }
        await load();
      } finally {
        document.getElementById('runButton').disabled = false;
      }
    }
    function runPath(inputPath) {
      return fetch('/run?input=' + encodeURIComponent(inputPath));
    }
    function uploadAndRun(file) {
      const data = new FormData();
      data.append('file', file);
      return fetch('/upload', { method: 'POST', body: data });
    }
    load();
  </script>
</body>
</html>"""


def _features_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bot Hunter Features</title>
  <style>
    :root { color-scheme: light; --ink:#172026; --muted:#5f6b74; --line:#d8dee4; --bg:#f7f9fb; --panel:#ffffff; --accent:#16697a; --accent-weak:#e5f1f3; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }
    header { background:#ffffff; border-bottom:1px solid var(--line); padding:22px 28px; display:flex; align-items:center; justify-content:space-between; gap:16px; }
    h1 { font-size:24px; margin:0; letter-spacing:0; }
    main { max-width:1240px; margin:0 auto; padding:26px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    a, button { color:#ffffff; background:var(--accent); border:0; border-radius:6px; padding:9px 12px; text-decoration:none; font-weight:650; cursor:pointer; }
    a.secondary { color:var(--accent); background:var(--accent-weak); }
    .label { color:var(--muted); font-size:13px; }
    .table-wrap { overflow:auto; max-height:72vh; border:1px solid var(--line); border-radius:6px; margin-top:12px; }
    table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; }
    th, td { border-bottom:1px solid var(--line); padding:8px; text-align:right; font-variant-numeric:tabular-nums; }
    th:first-child, td:first-child { text-align:left; position:sticky; left:0; background:#ffffff; }
    th { color:var(--muted); font-weight:600; background:#ffffff; position:sticky; top:0; }
  </style>
</head>
<body>
  <header>
    <h1>Bot Hunter Features</h1>
    <div class="actions">
      <a class="secondary" href="/">Dashboard</a>
      <a class="secondary" href="/report">Report</a>
    </div>
  </header>
  <main>
    <section class="panel">
      <div class="actions">
        <button onclick="loadFeatures(0)">First Page</button>
        <button id="nextButton" onclick="loadFeatures(nextOffset)">Next Page</button>
        <span class="label" id="status"></span>
      </div>
      <div class="table-wrap">
        <table>
          <thead id="featureHead"></thead>
          <tbody id="featureRows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    let nextOffset = 0;
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      })[ch]);
    }
    async function loadFeatures(offset) {
      document.getElementById('status').textContent = 'Loading...';
      const payload = await fetch('/api/features?offset=' + encodeURIComponent(offset) + '&limit=200').then(r => r.json());
      if (payload.error) {
        document.getElementById('status').textContent = payload.error;
        return;
      }
      const columns = ['event_id', ...(payload.feature_names || [])];
      document.getElementById('featureHead').innerHTML = `<tr>${columns.map(name => `<th>${escapeHtml(name)}</th>`).join('')}</tr>`;
      document.getElementById('featureRows').innerHTML = (payload.rows || []).map(row => `<tr>
        <td>${escapeHtml(row.event_id)}</td>${(row.features || []).map(value => `<td>${escapeHtml(Number(value).toFixed(6))}</td>`).join('')}
      </tr>`).join('');
      nextOffset = payload.next_offset || 0;
      const rowsShown = (payload.rows || []).length;
      document.getElementById('nextButton').disabled = rowsShown < payload.limit;
      document.getElementById('status').textContent = rowsShown
        ? `Showing rows ${payload.offset} through ${payload.next_offset - 1}`
        : `No rows found at offset ${payload.offset}`;
    }
    loadFeatures(0);
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
