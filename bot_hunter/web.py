from __future__ import annotations

# pylint: disable=too-many-lines

import argparse
import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from .pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PIPELINE_LOCK = Lock()


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
            self._send_json(
                _read_features(
                    ROOT / "artifacts" / "features.tsv", offset=offset, limit=limit
                )
            )
        elif parsed.path == "/features":
            self._send_html(_features_html())
        elif parsed.path == "/report":
            self._send_html(
                (ROOT / "docs" / "analysis_report.html").read_text(encoding="utf-8")
            )
        elif parsed.path == "/run":
            params = parse_qs(parsed.query)
            input_path = params.get("input", [""])[0]
            if not input_path:
                self._send_json({"error": "Pass ?input=/path/to/raw.tsv"}, status=400)
                return
            try:
                safe_input_path = _validate_server_input_path(input_path)
                with PIPELINE_LOCK:
                    summary = run_pipeline(safe_input_path, ROOT)
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
            self._send_json(
                {"error": "Upload a TSV file before running the pipeline"}, status=400
            )
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(
                {"error": f"Upload exceeds the {MAX_UPLOAD_BYTES} byte limit"},
                status=413,
            )
            return

        body = self.rfile.read(content_length)
        try:
            fields, files = _parse_multipart_form(content_type, body)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        upload = files.get("file")
        if not upload or not upload.get("filename"):
            self._send_json(
                {"error": "Upload a TSV file before running the pipeline"}, status=400
            )
            return

        suffix = Path(upload.get("filename") or "upload.tsv").suffix or ".tsv"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb", suffix=suffix, delete=False
            ) as handle:
                handle.write(upload["content"])
                tmp_path = Path(handle.name)
            with PIPELINE_LOCK:
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


def _validate_server_input_path(input_path: str) -> Path:
    root = ROOT.resolve()
    path = Path(input_path).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Server-side input path must be under {root}") from exc
    return path


def _parse_multipart_form(
    content_type: str, body: bytes
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
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
        disposition = next(
            (
                line
                for line in headers
                if line.lower().startswith("content-disposition:")
            ),
            "",
        )
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
            rows.append(
                {
                    "event_id": parts[0],
                    "features": [float(value) for value in parts[1:]],
                }
            )
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
    :root {
      color-scheme: light; --ink:#142027; --muted:#5c6870; --line:#d8dee4;
      --bg:#f5f7f8; --panel:#ffffff; --accent:#0f6674;
      --accent-weak:#e2f0f2; --amber:#a35b00; --red:#aa4238;
    }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:var(--bg); }
    header {
      position:sticky; top:0; z-index:10; background:#fff;
      border-bottom:1px solid var(--line); padding:14px 22px;
      display:grid; grid-template-columns:minmax(230px,1fr) auto; gap:14px;
    }
    h1 { font-size:24px; margin:0; letter-spacing:0; }
    h2 { font-size:18px; margin:0 0 12px; }
    h3 { font-size:15px; margin:0 0 8px; }
    p { margin:0 0 10px; }
    main { max-width:1320px; margin:0 auto; padding:22px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td {
      border-bottom:1px solid var(--line);
      padding:9px 8px;
      text-align:left;
      vertical-align:top;
    }
    th { color:var(--muted); font-weight:600; }
    .actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    a, button, select, input { font:inherit; }
    a, button {
      color:#fff; background:var(--accent); border:0; border-radius:6px;
      padding:9px 12px; text-decoration:none; font-weight:650; cursor:pointer;
    }
    button.mode, button.nav, button.help-link { color:var(--accent); background:var(--accent-weak); }
    button.mode[aria-pressed="true"] { color:#ffffff; background:var(--accent); }
    button.nav[aria-current="page"] { color:#fff; background:var(--accent); }
    button.help-link { padding:5px 8px; font-size:12px; }
    a.secondary { color:var(--accent); background:var(--accent-weak); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    input, select { min-height:38px; padding:8px 10px; border:1px solid var(--line); border-radius:6px; background:#fff; }
    input { width:min(420px, 42vw); }
    .dataset { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    .menu { display:flex; gap:6px; flex-wrap:wrap; margin-top:12px; }
    .mode-group { display:flex; gap:4px; padding:3px; border:1px solid var(--line); border-radius:8px; background:#fff; }
    .input-panel { display:block; }
    .input-panel.is-hidden { display:none; }
    .input-help { flex-basis:100%; color:var(--muted); font-size:12px; margin:3px 0 0; }
    .topline { color:var(--muted); font-size:13px; margin-top:4px; }
    .page { display:none; }
    .page.active { display:block; }
    .panel, .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    .panel { margin-bottom:16px; }
    .story, .chart-grid, .split { display:grid; grid-template-columns:1.2fr .8fr; gap:16px; align-items:start; }
    .three { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .metric-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
    .metric { border:1px solid var(--line); border-radius:8px; padding:13px; background:#fff; min-height:104px; }
    .metric-value { font-size:28px; font-weight:750; font-variant-numeric:tabular-nums; margin:6px 0; }
    .metric-label, .label { color:var(--muted); font-size:13px; }
    .chart-grid { grid-template-columns:repeat(3,minmax(0,1fr)); margin-bottom:16px; }
    .chart-body { display:grid; grid-template-columns:142px minmax(0,1fr); gap:14px; align-items:center; }
    .donut { width:142px; height:142px; }
    .legend { display:grid; gap:7px; }
    .legend-row { display:grid; grid-template-columns:14px minmax(0,1fr) auto; gap:7px; align-items:center; font-size:12px; }
    .swatch { width:12px; height:12px; border-radius:3px; }
    .method-bars { display:grid; gap:10px; width:100%; }
    .method-row { display:grid; grid-template-columns:minmax(120px,1fr) minmax(120px,1.4fr) auto; gap:8px; align-items:center; font-size:12px; }
    .method-track { height:14px; background:#e8edf0; border-radius:999px; overflow:hidden; }
    .method-fill { display:block; height:100%; min-width:2px; }
    .chart-note { color:var(--muted); font-size:12px; line-height:1.4; margin:2px 0 0; }
    .class-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .class-card { display:grid; gap:8px; }
    .class-meta { display:flex; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:12px; }
    .pill { display:inline-flex; align-items:center; border:1px solid var(--line); border-radius:999px; padding:3px 8px; background:#f9fbfb; white-space:nowrap; }
    .example { border-top:1px solid var(--line); padding-top:8px; color:var(--muted); font-size:13px; }
    .action-grid, .filter-grid, .term-grid, .help-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .action-card { min-height:142px; }
    .caveat, .notice { border-left:4px solid var(--amber); background:#fff8ee; padding:12px; margin-top:12px; color:#50320a; }
    .technical-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
    .bar { height:22px; background:#e8edf0; border-radius:4px; overflow:hidden; margin:7px 0 12px; }
    .bar > span { display:block; height:100%; background:var(--accent); }
    .table-wrap { overflow:auto; }
    .wrap { max-width:260px; overflow-wrap:anywhere; }
    .score { font-variant-numeric:tabular-nums; font-weight:650; }
    .bot { color:var(--red); }
    .loading { padding:20px; color:var(--muted); }
    .active-filters { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; }
    .modal-backdrop { position:fixed; inset:0; background:rgba(20,32,39,.45); display:none; align-items:center; justify-content:center; padding:20px; z-index:30; }
    .modal-backdrop.open { display:flex; }
    .modal { background:#fff; color:var(--ink); max-width:560px; width:min(560px,100%); border-radius:8px; padding:18px; box-shadow:0 18px 60px rgba(0,0,0,.25); }
    .modal-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
    @media (max-width: 1000px) {
      header, .story, .chart-grid, .technical-grid, .split { grid-template-columns:1fr; }
      .metric-grid, .three, .action-grid, .filter-grid, .term-grid, .help-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .class-grid { grid-template-columns:1fr; }
    }
    @media (max-width: 700px) {
      main { padding:14px; }
      input { width:100%; }
      .actions, .dataset, .input-panel, .mode-group { width:100%; }
      .mode-group button { flex:1; }
      .metric-grid, .three, .action-grid, .filter-grid, .term-grid, .help-grid { grid-template-columns:1fr; }
      .chart-body { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Bot Hunter Business Dashboard</h1>
      <div class="topline">Operational review view for current bot-click results.</div>
      <nav class="menu" aria-label="Dashboard pages">
        <button class="nav" data-page="overview" aria-current="page">Overview</button>
        <button class="nav" data-page="classes">Anomaly Classes</button>
        <button class="nav" data-page="explorer">Traffic Explorer</button>
        <button class="nav" data-page="queries">Query Terms</button>
        <button class="nav" data-page="breakdown">Method/Tier Breakdown</button>
        <button class="nav" data-page="technical">Technical Evidence</button>
        <button class="nav" data-page="help">Help</button>
      </nav>
    </div>
    <div class="actions">
      <div class="dataset" aria-label="Dataset source">
        <div class="mode-group" role="group" aria-label="Dataset input mode">
          <button id="uploadModeButton" class="mode" type="button" aria-pressed="true" onclick="setInputMode('upload')">Upload TSV</button>
          <button id="pathModeButton" class="mode" type="button" aria-pressed="false" onclick="setInputMode('path')">Server path</button>
        </div>
        <div id="uploadInputPanel" class="input-panel">
          <input id="inputFile" class="dataset-field" type="file" accept=".tsv,text/tab-separated-values,text/plain" aria-label="Upload input TSV">
          <p class="input-help">Choose a local .tsv file to upload and analyse.</p>
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
    <section class="page active" id="page-overview">
      <div class="story">
      <div class="panel">
        <h2>What this run says</h2>
        <p id="storyLead" class="loading">Loading current run...</p>
        <div class="three">
          <div class="card">
            <h3>Business problem</h3>
            <p>Find traffic that looks automated enough to review, without
            claiming each event is proven fraud.</p>
          </div>
          <div class="card">
            <h3>What was analysed</h3>
            <p id="storyAnalysed">Current click-log artefacts from the latest
            pipeline run.</p>
          </div>
          <div class="card">
            <h3>How to act</h3>
            <p>Use the operational tier first: suppress needs policy approval,
            quarantine means review or sample, monitor stays in trend tracking.</p>
          </div>
        </div>
        <div class="caveat">
          Anomaly classes are operational review groups, not proven fraud labels.
          ML-only traffic should be sampled or quarantined rather than
          automatically suppressed.
        </div>
      </div>
      <div class="panel">
        <h2>Run at a glance</h2>
        <div class="metric-grid" id="metrics"></div>
      </div>
      </div>
      <div class="chart-grid" aria-label="Current result proportions">
      <div class="card">
        <h2>Operational tiers</h2>
        <div class="chart-body" id="tierChart"></div>
      </div>
      <div class="card">
        <h2>Method buckets</h2>
        <div id="methodChart"></div>
      </div>
      <div class="card">
        <h2>Anomaly classes</h2>
        <div class="chart-body" id="classChart"></div>
      </div>
      </div>
      <section class="panel">
        <h2>Recommended actions</h2>
        <div class="action-grid" id="actionGuidance"></div>
      </section>
    </section>
    <section class="page" id="page-classes">
      <section class="panel">
      <h2>Anomaly classes and handling</h2>
      <div class="label" id="classScope"></div>
      <div class="class-grid" id="classCards"></div>
      </section>
    </section>
    <section class="page" id="page-explorer">
      <section class="panel">
      <h2>Traffic Explorer</h2>
      <p class="label">Rows below come from `artifacts/sample_events.json`, a
      250-row highest-risk suppress sample of detected anomaly traffic.
      Full-population event rows, quarantine/monitor rows, ML-only event rows,
      anomaly class per row, and raw `ct`/country values are not available
      through the current dashboard API.</p>
      <div class="filter-grid" id="filters"></div>
      <div class="active-filters" id="activeFilters"></div>
      <div class="table-wrap"><table>
        <thead><tr><th>Event</th><th>Method</th><th>Device cluster</th><th>Domain</th><th>Query</th><th>Scores</th><th>Tier</th></tr></thead>
        <tbody id="filteredEvents"></tbody>
      </table></div>
      </section>
    </section>
    <section class="page" id="page-queries">
      <section class="panel">
      <h2>Query Terms</h2>
      <p class="label">Query visualisations use the detected-event sample for
      anomaly rows, which is currently the 250 highest-risk suppress events.
      The top-query reference table uses the current summary artefact and should
      not be read as row-level full-population filtering.</p>
      <div class="split">
        <div class="card"><h3>Top query terms in anomaly sample</h3><div id="sampleQueries"></div></div>
        <div class="card"><h3>Top query/domain combinations</h3><div id="queryDomainPairs"></div></div>
      </div>
      <div class="panel"><h3>Summary top queries</h3><div id="summaryQueries"></div></div>
      </section>
    </section>
    <section class="page" id="page-breakdown">
      <section class="panel">
      <h2>Method/Tier Breakdown</h2>
      <div class="chart-grid" aria-label="Breakdown charts">
        <div class="card"><h3>Operational tiers</h3><div class="chart-body" id="tierChartBreakdown"></div></div>
        <div class="card"><h3>Review method buckets</h3><div id="methodChartBreakdown"></div></div>
        <div class="card"><h3>Anomaly classes</h3><div class="chart-body" id="classChartBreakdown"></div></div>
      </div>
      </section>
      <section class="panel">
      <div class="caveat">
        Filtering options are review controls for similar unlabelled datasets,
        not ground-truth fraud rules.
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Filter</th><th>Use</th></tr></thead>
        <tbody id="filteringOptions"></tbody>
      </table></div>
      </section>
    </section>
    <section class="page" id="page-technical">
      <section class="panel">
      <h2>Technical evidence</h2>
      <p class="label">Detailed evidence remains available for reviewers who
      need to audit the scores, thresholds, and individual events.</p>
      <div class="technical-grid">
        <div class="card">
          <h3>Top bot signals</h3>
          <div id="reasons"></div>
        </div>
        <div class="card">
          <h3>Flagged regions</h3>
          <div id="regions"></div>
        </div>
      </div>
      </section>
      <section class="panel">
      <h2>Adaptive rule thresholds</h2>
      <div class="label" id="ruleStrengths"></div>
      <div class="table-wrap"><table>
        <thead><tr><th>Rule</th><th>Threshold</th><th>Basis</th></tr></thead>
        <tbody id="heuristicThresholds"></tbody>
      </table></div>
      </section>
      <section class="panel">
      <h2>Highest Risk Events</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Event</th><th>Time</th><th>Device</th><th>Domain</th><th>Query</th><th>Scores</th><th>Tier</th><th>Rule evidence</th></tr></thead>
        <tbody id="events"></tbody>
      </table></div>
      </section>
    </section>
    <section class="page" id="page-help">
      <section class="panel">
      <h2>Help</h2>
      <p>Open a term for a short business definition and example.</p>
      <div class="help-grid" id="definitionButtons"></div>
      </section>
    </section>
  </main>
  <div class="modal-backdrop" id="helpModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle" onclick="if(event.target===this)closeDefinition()">
    <div class="modal">
      <div class="modal-head">
        <h2 id="modalTitle">Definition</h2>
        <button type="button" onclick="closeDefinition()">Close</button>
      </div>
      <p id="modalBody"></p>
      <p class="label" id="modalExample"></p>
    </div>
  </div>
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
    const colours = ['#0f6674', '#327a52', '#a35b00', '#4361a6',
      '#7157a8', '#aa4238', '#61717a', '#8a6f3f'];
    let sampleEvents = [];
    let summaryData = {};
    let lastHelpButton = null;
    const filters = { anomalyOnly: true, method: '', region: '', device: '', domain: '', query: '' };
    const definitions = {
      'is_bot': ['The required yes/no output. A value of 1 means Bot Hunter selected the event for bot review.', 'Example: an event marked is_bot = 1 appears in the detected anomaly sample.'],
      'operational tier': ['The suggested business handling after prediction.', 'Example: suppress is stronger than quarantine, but still needs policy approval.'],
      'suppress': ['A high-confidence candidate for removal from billing or metrics after approval.', 'Example: repeated query/domain traffic with strong rule and ML evidence.'],
      'quarantine': ['Traffic to hold, delay, sample, or manually review before suppression.', 'Example: ML-only events should usually start here.'],
      'monitor': ['Traffic not selected for action, kept for trends and future labels.', 'Example: normal-looking traffic remains useful for drift checks.'],
      'heuristic score': ['Evidence from transparent rules, such as repetition, bursts, or unusual timing.', 'Example: repeated query/domain pairs raise this score.'],
      'ML score': ['How unusual the event looks compared with this batch. It does not prove fraud.', 'Example: a rare combination of features can score high.'],
      'combined score': ['The score used for selection: 0.58 rule evidence plus 0.42 anomaly-model evidence.', 'Example: a high combined score can pass the run threshold.'],
      'anomaly class': ['A review group that explains the main pattern. It is not a confirmed fraud label.', 'Example: Compound burst/replay means repetition and burst timing appeared together.'],
      'operational confidence estimate': ['A signal-based confidence estimate for prioritising review. It is not measured precision.', 'Example: use it to plan review effort, not as a fraud probability.'],
      'threshold': ['The run-specific cutoff used to select likely bot traffic.', 'Example: events above the combined-score cutoff are selected unless policy later rejects them.'],
      'unlabelled data': ['Data without known right answers. Precision, recall, and calibrated fraud probability cannot be measured yet.', 'Example: manual review labels would be needed to calculate precision.']
    };
    async function load() {
      const [summary, events] = await Promise.all([fetch('/api/summary').then(r => r.json()), fetch('/api/events').then(r => r.json())]);
      if (summary.error) { document.getElementById('metrics').innerHTML = `<div class="card">${escapeHtml(summary.error)}</div>`; return; }
      summaryData = summary;
      sampleEvents = Array.isArray(events) ? events : [];
      attachNavigation();
      renderDefinitions();
      renderSummary(summary);
      renderCharts(summary);
      renderAnomalyClasses(summary);
      renderActions(summary);
      renderFilters(sampleEvents, summary);
      renderExplorer();
      renderQueries(sampleEvents, summary);
      renderEvents(sampleEvents);
    }
    function pct(x) { return (100 * Number(x || 0)).toFixed(2) + '%'; }
    function count(x) { return Number(x || 0).toLocaleString(); }
    function score(x) { return Number(x || 0).toFixed(4); }
    function renderSummary(s) {
      const total = Number(s.total_events || 0);
      const selected = Number(s.bot_events || 0);
      const confidence = pct(s.estimated_precision);
      const threshold = score(s.threshold);
      document.getElementById('storyLead').textContent =
        `Bot Hunter analysed ${count(total)} click events and selected ` +
        `${count(selected)} (${pct(s.bot_rate)}) as likely bot traffic for ` +
        `operational review. The current operational confidence estimate is ` +
        `${confidence}; it is not measured precision or a fraud probability.`;
      document.getElementById('storyAnalysed').textContent =
        `Input ${escapeHtml(s.input_path || 'current dataset')}; selected ` +
        `traffic uses threshold ${threshold} and the heuristic override.`;
      const metrics = [
        ['Events analysed', count(total), 'Click events in the current run.'],
        ['Selected as likely bot', count(selected), '`is_bot = 1` events.'],
        ['Selected rate', pct(s.bot_rate), 'Share of traffic selected.'],
        ['Operational confidence estimate', confidence, 'Not measured precision.'],
        ['Selection threshold', threshold, 'Run-specific combined-score cutoff.'],
        ['Suppress tier', count((s.tier_counts || {}).suppress), 'Policy approval required.'],
        ['Quarantine tier', count((s.tier_counts || {}).quarantine), 'Review or sample first.'],
        ['Monitor tier', count((s.tier_counts || {}).monitor), 'Keep for trend tracking.']
      ];
      document.getElementById('metrics').innerHTML = metrics.map(([k, v, note]) => `
        <div class="metric">
          <div class="metric-label">${escapeHtml(k)}</div>
          <div class="metric-value">${escapeHtml(v)}</div>
          <div class="label">${escapeHtml(note)}</div>
        </div>`).join('');
      renderBars('reasons', s.top_reasons || []);
      renderBars('regions', s.bot_regions || []);
      renderRuleStrengths(s.rule_strengths || {});
      renderHeuristicThresholds(s.heuristic_thresholds || {});
    }
    function renderDefinitions() {
      document.getElementById('definitionButtons').innerHTML = Object.keys(definitions)
        .map(term => `<button type="button" class="help-link" onclick="openDefinition('${escapeHtml(term)}')">${escapeHtml(term)}</button>`)
        .join('');
    }
    function renderCharts(s) {
      renderDonut('tierChart', 'Operational tiers', Object.entries(s.tier_counts || {}), 'traffic');
      renderMethodChart(s.method_disagreement || []);
      const classes = ((s.anomaly_classes || {}).classes || [])
        .map(item => [item.label, item.count]);
      renderDonut('classChart', 'Anomaly classes', classes, 'selected');
      renderDonut('tierChartBreakdown', 'Operational tiers', Object.entries(s.tier_counts || {}), 'traffic');
      renderMethodChart(s.method_disagreement || [], 'methodChartBreakdown');
      renderDonut('classChartBreakdown', 'Anomaly classes', classes, 'selected');
    }
    function renderBars(id, rows) {
      const max = Math.max(...rows.map(r => r[1]), 1);
      document.getElementById(id).innerHTML = rows.map(r => `<div class="label">${escapeHtml(r[0])} (${r[1].toLocaleString()})</div><div class="bar"><span style="width:${100*r[1]/max}%"></span></div>`).join('');
    }
    function renderMethodChart(rows, targetId = 'methodChart') {
      const reviewRows = rows.filter(([label]) => label !== 'Neither strong');
      const neither = rows.find(([label]) => label === 'Neither strong');
      const reviewTotal = reviewRows.reduce((sum, row) => sum + Number(row[1] || 0), 0);
      const max = Math.max(...reviewRows.map(row => Number(row[1] || 0)), 1);
      const bars = reviewRows.map(([label, raw], index) => {
        const value = Number(raw || 0);
        const share = reviewTotal ? `${((value / reviewTotal) * 100).toFixed(1)}%` : '0.0%';
        return `<div class="method-row">
          <span>${escapeHtml(label)}</span>
          <span class="method-track" aria-hidden="true">
            <span class="method-fill" style="width:${(100 * value) / max}%; background:${colours[index % colours.length]}"></span>
          </span>
          <strong>${count(value)} (${share})</strong>
        </div>`;
      }).join('');
      const neitherNote = neither
        ? `${count(neither[1])} events were not strongly indicated by either method and are excluded from this review-bucket chart.`
        : 'No neither-strong bucket was reported for this run.';
      document.getElementById(targetId).innerHTML = `
        <div class="method-bars" role="img"
          aria-label="Method buckets bar chart for review-relevant events">
          ${bars}
        </div>
        <p class="chart-note">${escapeHtml(neitherNote)}</p>`;
    }
    function renderDonut(id, label, rows, noun) {
      const total = rows.reduce((sum, row) => sum + Number(row[1] || 0), 0);
      const radius = 46;
      const circumference = 2 * Math.PI * radius;
      let offset = 0;
      const segments = rows.map(([label, raw], index) => {
        const value = Number(raw || 0);
        const length = total ? (value / total) * circumference : 0;
        const gap = total && length > 3 ? 1.2 : 0;
        const dash = `${Math.max(length - gap, 0)} ${circumference}`;
        const element = `<circle r="${radius}" cx="60" cy="60"
          fill="transparent" stroke="${colours[index % colours.length]}"
          stroke-width="22" stroke-dasharray="${dash}"
          stroke-dashoffset="${-offset}" transform="rotate(-90 60 60)">
          <title>${escapeHtml(label)}: ${count(value)} ${noun}</title></circle>`;
        offset += length;
        return element;
      }).join('');
      const legend = rows.map(([label, raw], index) => {
        const value = Number(raw || 0);
        const share = total ? `${((value / total) * 100).toFixed(1)}%` : '0.0%';
        return `<div class="legend-row">
          <span class="swatch" style="background:${colours[index % colours.length]}"></span>
          <span>${escapeHtml(label)}</span>
          <strong>${count(value)} (${share})</strong>
        </div>`;
      }).join('');
      document.getElementById(id).innerHTML = `
        <svg class="donut" viewBox="0 0 120 120" role="img"
          aria-label="${escapeHtml(label)} donut chart">
          <circle r="${radius}" cx="60" cy="60" fill="transparent"
            stroke="#e8edf0" stroke-width="22"></circle>
          ${segments}
          <text x="60" y="56" text-anchor="middle" font-size="15"
            font-weight="700">${count(total)}</text>
          <text x="60" y="73" text-anchor="middle" font-size="10"
            fill="#5c6870">${escapeHtml(noun)}</text>
        </svg>
        <div class="legend">${legend}</div>`;
    }
    function renderAnomalyClasses(s) {
      const anomaly = s.anomaly_classes || {};
      const classes = anomaly.classes || [];
      const selected = Number(anomaly.selected_event_count || s.bot_events || 0);
      document.getElementById('classScope').textContent =
        anomaly.scope || definitions['anomaly class'][0];
      document.getElementById('classCards').innerHTML = classes.map(item => {
        const share = selected ? `${((Number(item.count || 0) / selected) * 100).toFixed(1)}%` : '0.0%';
        const example = (item.examples || [])[0];
        const exampleHtml = example ? `<div class="example">
          Example ${escapeHtml(example.event_id)}: ${escapeHtml(example.domain)}
          / ${escapeHtml(example.query)}; tier ${escapeHtml(example.operational_tier)};
          method ${escapeHtml(example.method_bucket)}; combined ${score(example.combined_score)}.
        </div>` : '<div class="example">No example supplied for this class.</div>';
        return `<article class="card class-card">
          <h3>${escapeHtml(item.label)}</h3>
          <div class="class-meta">
            <span class="pill">${count(item.count)} selected</span>
            <span class="pill">${share} of selected traffic</span>
          </div>
          <p>${escapeHtml(item.description)}</p>
          <p><strong>Suggested handling:</strong> ${escapeHtml(item.review_action)}</p>
          ${exampleHtml}
        </article>`;
      }).join('');
    }
    function renderActions(s) {
      const tiers = s.operational_tiers || {};
      const actions = [
        ['suppress', tiers.suppress || definitions.suppress],
        ['quarantine', tiers.quarantine || definitions.quarantine],
        ['monitor', tiers.monitor || definitions.monitor]
      ];
      document.getElementById('actionGuidance').innerHTML = actions.map(([tier, text]) => `
        <div class="card action-card">
          <h3>${escapeHtml(tier)}</h3>
          <p>${escapeHtml(text)}</p>
        </div>`).join('');
      const options = ((s.anomaly_classes || {}).filtering_options || []);
      document.getElementById('filteringOptions').innerHTML = options.map(item => `
        <tr>
          <td><strong>${escapeHtml(item.name)}</strong><br>
          <span class="label">${escapeHtml(item.filter)}</span></td>
          <td>${escapeHtml(item.use)}</td>
        </tr>`).join('');
    }
    function attachNavigation() {
      document.querySelectorAll('button.nav').forEach(button => {
        button.onclick = () => showPage(button.dataset.page);
      });
      document.addEventListener('keydown', event => {
        const modal = document.getElementById('helpModal');
        if (!modal.classList.contains('open')) return;
        if (event.key === 'Escape') {
          closeDefinition();
        } else if (event.key === 'Tab') {
          event.preventDefault();
          document.querySelector('#helpModal button').focus();
        }
      });
    }
    function showPage(page) {
      document.querySelectorAll('.page').forEach(item => item.classList.remove('active'));
      document.getElementById(`page-${page}`).classList.add('active');
      document.querySelectorAll('button.nav').forEach(button => {
        button.setAttribute('aria-current', button.dataset.page === page ? 'page' : 'false');
      });
    }
    function openDefinition(term) {
      const entry = definitions[term];
      if (!entry) return;
      lastHelpButton = document.activeElement;
      document.getElementById('modalTitle').textContent = term;
      document.getElementById('modalBody').textContent = entry[0];
      document.getElementById('modalExample').textContent = entry[1];
      document.getElementById('helpModal').classList.add('open');
      document.querySelector('#helpModal button').focus();
    }
    function closeDefinition() {
      document.getElementById('helpModal').classList.remove('open');
      if (lastHelpButton) lastHelpButton.focus();
    }
    function methodBucket(event) {
      const h = Number(event.heuristic_score || 0);
      const ml = Number(event.ml_score || 0);
      const thresholds = summaryData.tier_thresholds || {};
      const hCut = Number(thresholds.suppress_agreement_heuristic_score ?? 0.62);
      const mlCut = Number(thresholds.ml_agreement_score ?? 0.975);
      if (h >= hCut && ml >= mlCut) return 'Heuristic + ML';
      if (h >= hCut) return 'Heuristic only';
      if (ml >= mlCut) return 'ML only';
      return event.is_bot ? 'Combined tail' : 'Neither strong';
    }
    function deviceLabel(event) {
      return `${event.region || 'unknown'} / ${event.browser || 'unknown'} / ${event.os || 'unknown'}`;
    }
    function uniqueRows(rows, getter) {
      return [...new Set(rows.map(getter).filter(Boolean))].sort();
    }
    function renderFilters(events) {
      const methods = uniqueRows(events, methodBucket);
      const regions = uniqueRows(events, e => e.region);
      const devices = uniqueRows(events, deviceLabel);
      const domains = uniqueRows(events, e => e.domain);
      document.getElementById('filters').innerHTML = `
        ${selectHtml('method', 'Method bucket', methods)}
        <label>Country / ct<select disabled><option>Not available in sample_events.json</option></select><span class="label">Raw country/ct is not available in the row sample.</span></label>
        ${selectHtml('region', 'Region', regions)}
        ${selectHtml('device', 'Device cluster (region/browser/OS)', devices)}
        ${selectHtml('domain', 'Domain', domains)}
        <label>Query text<input id="filter-query" placeholder="Search query text"></label>
        <label>Anomaly focus<select id="filter-focus"><option value="anomaly">Detected anomaly sample</option><option value="all" disabled>All traffic rows unavailable</option></select></label>`;
      ['method', 'region', 'device', 'domain'].forEach(name => {
        document.getElementById(`filter-${name}`).onchange = event => {
          filters[name] = event.target.value;
          renderExplorer();
        };
      });
      document.getElementById('filter-query').oninput = event => {
        filters.query = event.target.value.toLowerCase();
        renderExplorer();
      };
    }
    function selectHtml(name, label, options) {
      return `<label>${escapeHtml(label)}<select id="filter-${name}">
        <option value="">Any</option>${options.map(item => `<option>${escapeHtml(item)}</option>`).join('')}
      </select></label>`;
    }
    function filteredEvents() {
      return sampleEvents.filter(event => {
        if (filters.method && methodBucket(event) !== filters.method) return false;
        if (filters.region && event.region !== filters.region) return false;
        if (filters.device && deviceLabel(event) !== filters.device) return false;
        if (filters.domain && event.domain !== filters.domain) return false;
        if (filters.query && !String(event.query || '').toLowerCase().includes(filters.query)) return false;
        return true;
      });
    }
    function renderExplorer() {
      const rows = filteredEvents();
      const chips = [
        'Focus: detected anomaly sample',
        filters.method && `Method: ${filters.method}`,
        filters.region && `Region: ${filters.region}`,
        filters.device && `Device cluster: ${filters.device}`,
        filters.domain && `Domain: ${filters.domain}`,
        filters.query && `Query contains: ${filters.query}`
      ].filter(Boolean);
      document.getElementById('activeFilters').innerHTML = chips.map(item => `<span class="pill">${escapeHtml(item)}</span>`).join('');
      document.getElementById('filteredEvents').innerHTML = rows.map(e => `<tr>
        <td>${escapeHtml(e.event_id)}</td><td>${escapeHtml(methodBucket(e))}</td>
        <td>${escapeHtml(deviceLabel(e))}</td><td class="wrap">${escapeHtml(e.domain)}</td>
        <td class="wrap">${escapeHtml(e.query)}</td>
        <td class="score">combined ${score(e.combined_score)}<br>rules ${score(e.heuristic_score)}<br>ML ${score(e.ml_score)}</td>
        <td>${escapeHtml(e.operational_tier)}</td>
      </tr>`).join('');
    }
    function renderQueries(events, summary) {
      renderCountBars('sampleQueries', countBy(events, e => e.query), events.length);
      renderCountBars('queryDomainPairs', countBy(events, e => `${e.query} / ${e.domain}`), events.length);
      renderBars('summaryQueries', summary.top_queries || []);
    }
    function countBy(rows, getter) {
      const counts = new Map();
      rows.forEach(row => {
        const key = getter(row) || 'unknown';
        counts.set(key, (counts.get(key) || 0) + 1);
      });
      return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
    }
    function renderCountBars(id, rows, total) {
      const max = Math.max(...rows.map(row => row[1]), 1);
      document.getElementById(id).innerHTML = rows.map(([label, value]) => {
        const share = total ? `${((100 * value) / total).toFixed(1)}%` : '0.0%';
        return `<div class="label">${escapeHtml(label)} (${count(value)}, ${share})</div><div class="bar"><span style="width:${(100 * value) / max}%"></span></div>`;
      }).join('');
    }
    function renderHeuristicThresholds(thresholds) {
      const rows = Object.values(thresholds).sort((a, b) => String(a.label).localeCompare(String(b.label)));
      document.getElementById('heuristicThresholds').innerHTML = rows.map(item => {
        const rate = item.rate_floor === null || item.rate_floor === undefined ? '' : `, rate guardrail ${escapeHtml(item.rate_floor)}`;
        const percentile = `${Math.round(Number(item.percentile || 0) * 100)}th-percentile`;
        const basis = `${percentile} threshold, floor ${escapeHtml(item.absolute_floor)}${rate}`;
        return `<tr><td>${escapeHtml(item.label)}<br><span class="label">${escapeHtml(item.rule_id)}</span></td><td class="score">${escapeHtml(item.threshold)}</td><td>${basis}</td></tr>`;
      }).join('');
    }
    function renderRuleStrengths(settings) {
      const cap = settings.supporting_cap;
      document.getElementById('ruleStrengths').textContent = cap === undefined
        ? ''
        : `Supporting rule score is capped at ${Number(cap).toFixed(2)}; strong rule evidence is not capped.`;
    }
    function renderRuleEvidence(event) {
      const contributions = event.rule_contributions || [];
      if (!contributions.length) {
        return (event.reasons || []).map(escapeHtml).join('<br>');
      }
      return contributions.map(item => {
        const strength = item.strength || 'supporting';
        const family = item.family || item.rule_family || 'general';
        const raw = item.weight === undefined ? '' : Number(item.weight).toFixed(3);
        const applied = item.applied_weight === undefined
          ? (item.uncapped_weight === undefined ? raw : Number(item.weight).toFixed(3))
          : Number(item.applied_weight).toFixed(3);
        const score = raw && applied && raw !== applied
          ? `score +${applied} of ${raw}`
          : (applied ? `score +${applied}` : '');
        const meta = `${escapeHtml(strength)} / ${escapeHtml(family)}`;
        return `${meta} - ${escapeHtml(item.label || item.rule_id)}: ${escapeHtml(item.observed)} vs threshold ${escapeHtml(item.threshold)}${score ? ` (${score})` : ''}`;
      }).join('<br>');
    }
    function renderEvents(events) {
      document.getElementById('events').innerHTML = events.slice(0, 80).map(e => `<tr>
        <td>${escapeHtml(e.event_id)}</td><td>${escapeHtml(e.event_time)}</td><td>${escapeHtml(e.region)}<br>${escapeHtml(e.browser)} / ${escapeHtml(e.os)}</td>
        <td class="wrap">${escapeHtml(e.domain)}</td><td class="wrap">${escapeHtml(e.query)}</td>
        <td class="score bot">combined ${escapeHtml(e.combined_score)}<br>rules ${escapeHtml(e.heuristic_score)}<br>ml ${escapeHtml(e.ml_score)}</td>
        <td>${escapeHtml(e.operational_tier)}</td>
        <td class="wrap">${renderRuleEvidence(e)}</td>
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
