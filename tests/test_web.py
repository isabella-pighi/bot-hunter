import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bot_hunter import web

SIDEBAR_LABELS = [
    "Overview",
    "Method/Tier Breakdown",
    "Traffic Explorer",
    "Technical Evidence",
    "Query Terms",
    "Help",
]

OVERVIEW_HEADINGS = [
    "<h2>Run at a glance</h2>",
    "<h2>What this run says</h2>",
    "<h2>Recommended actions</h2>",
]


def _sidebar_nav_markup(dashboard: str) -> str:
    nav_start = dashboard.index('<nav class="sidebar-nav">')
    nav_end = dashboard.index("</nav>", nav_start)
    return dashboard[nav_start:nav_end]


def _overview_markup(dashboard: str) -> str:
    overview_start = dashboard.index('<section class="page active" id="page-overview">')
    overview_end = dashboard.index('<section class="page" id="page-classes">')
    return dashboard[overview_start:overview_end]


def _labels_are_ordered(markup: str, labels: list[str]) -> bool:
    positions = [markup.index(label) for label in labels]
    return positions == sorted(positions)


def test_web_serves_feature_page_and_api(monkeypatch, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    docs = tmp_path / "docs"
    artifacts.mkdir()
    docs.mkdir()
    (artifacts / "summary.json").write_text('{"total_events": 1}', encoding="utf-8")
    (artifacts / "selected_events.json").write_text(
        (
            '[{"event_id":"evt_selected","method_bucket":"Heuristic + ML",'
            '"anomaly_class":"compound_burst_replay",'
            '"operational_tier":"suppress"}]'
        ),
        encoding="utf-8",
    )
    (artifacts / "sample_events.json").write_text("[]", encoding="utf-8")
    (artifacts / "features.tsv").write_text(
        "event_id\tlog_domain_count\tlog_ttc_seconds\n"
        "evt_<script>\t1.386294\t0.010000\n"
        "evt_2\t0.693147\t3.000000\n",
        encoding="utf-8",
    )
    (docs / "analysis_report.html").write_text("<h1>Report</h1>", encoding="utf-8")
    monkeypatch.setattr(web, "ROOT", tmp_path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        dashboard = urlopen(base_url + "/", timeout=5).read().decode("utf-8")
        assert 'href="/features"' in dashboard
        assert 'id="uploadModeButton"' in dashboard
        assert 'aria-pressed="true" onclick="setInputMode(\'upload\')"' in dashboard
        assert 'id="pathModeButton"' in dashboard
        assert 'aria-pressed="false" onclick="setInputMode(\'path\')"' in dashboard
        assert 'id="inputFile"' in dashboard
        assert 'id="uploadInputPanel" class="input-panel"' in dashboard
        assert 'id="pathInputPanel" class="input-panel is-hidden"' in dashboard
        assert ".input-panel.is-hidden { display:none; }" in dashboard
        assert (
            'id="inputPath" class="dataset-field" placeholder="/path/to/bot-hunter-dataset.tsv"'
            in dashboard
        )
        assert "Choose a local .tsv file to upload and analyse." in dashboard
        assert (
            "Use only when the TSV already exists on the machine running this dashboard."
            in dashboard
        )
        assert (
            "Only the active mode is submitted; the other input is ignored regardless of its state."
            in dashboard
        )
        assert (
            "inputMode === 'upload' ? await uploadAndRun(file) : await runPath(inputPath)"
            in dashboard
        )
        assert "Choose a TSV file before running the pipeline." in dashboard
        assert "Enter a file path before running the pipeline." in dashboard
        assert 'id="mlBackend"' not in dashboard
        assert "Bot Hunter Business Dashboard" in dashboard
        assert "html { overflow-x:hidden; }" in dashboard
        assert "overflow-x:hidden" in dashboard
        assert ".table-wrap { overflow:auto; contain:inline-size; }" in dashboard
        assert "What this run says" in dashboard
        assert "Business problem" in dashboard
        assert "What was analysed" in dashboard
        assert "How to act" in dashboard
        assert "Run at a glance" in dashboard
        overview_markup = _overview_markup(dashboard)
        assert _labels_are_ordered(overview_markup, OVERVIEW_HEADINGS)
        assert 'aria-label="Current result proportions"' not in overview_markup
        assert 'id="tierChart"' not in overview_markup
        assert 'id="methodChart"' not in overview_markup
        assert 'id="classChart"' not in overview_markup
        assert "Traffic Explorer" in dashboard
        assert "Query Terms" in dashboard
        assert "Method/Tier Breakdown" in dashboard
        assert "Help" in dashboard
        nav_markup = _sidebar_nav_markup(dashboard)
        assert _labels_are_ordered(
            nav_markup, [f">{label}</button>" for label in SIDEBAR_LABELS]
        )
        assert 'data-page="classes"' not in nav_markup
        assert (
            '<button type="button" class="nav" data-page="overview" '
            'aria-current="page" onclick="showPage(\'overview\')">Overview' in dashboard
        )
        assert (
            '<button type="button" class="nav" data-page="breakdown" '
            "onclick=\"showPage('breakdown')\">Method/Tier Breakdown" in dashboard
        )
        assert (
            '<button type="button" class="nav" data-page="explorer" '
            "onclick=\"showPage('explorer')\">Traffic Explorer" in dashboard
        )
        assert "let navigationAttached = false;" in dashboard
        assert "if (navigationAttached) return;" in dashboard
        assert "navigationAttached = true;" in dashboard
        assert dashboard.index("attachNavigation();") < dashboard.index(
            "async function load()"
        )
        assert "button.onclick = () => showPage(button.dataset.page);" in dashboard
        assert 'class="app-shell"' in dashboard
        assert '<aside class="sidebar" aria-label="Dashboard sections">' in dashboard
        assert '<nav class="sidebar-nav">' in dashboard
        assert (
            '<nav class="sidebar-nav" aria-label="Dashboard sections">' not in dashboard
        )
        assert "header { position:sticky; top:0; z-index:20;" in dashboard
        assert (
            ".app-shell { display:grid; grid-template-columns:240px minmax(0,1fr);"
            in dashboard
        )
        assert ".sidebar { position:sticky; top:0;" in dashboard
        assert ".workspace { min-width:0; width:100%;" in dashboard
        assert (
            ".global-filters { position:relative; z-index:1; padding:12px; }"
            in dashboard
        )
        assert "top:122px" not in dashboard
        assert ".control-head { display:flex;" in dashboard
        assert (
            ".filter-grid { grid-template-columns:repeat(4,minmax(140px,1fr)); gap:8px; }"
            in dashboard
        )
        assert (
            ".filter-grid select[multiple] { height:34px; min-height:34px; width:100%; }"
            in dashboard
        )
        assert (
            ".sidebar-nav { grid-template-columns:repeat(2,minmax(0,1fr)); }"
            in dashboard
        )
        assert (
            ".sidebar-nav button.nav { text-align:center; min-width:0; }" in dashboard
        )
        assert "table { table-layout:fixed; font-size:11px; }" in dashboard
        assert "header { align-items:start; }" in dashboard
        assert "Operational tiers" in dashboard
        assert "Method buckets" in dashboard
        assert "Anomaly classes" in dashboard
        assert "Anomaly classes and handling" in dashboard
        assert "Recommended actions" in dashboard
        assert "Technical evidence" in dashboard
        assert "Adaptive rule thresholds" in dashboard
        assert 'id="ruleStrengths"' in dashboard
        assert 'id="heuristicThresholds"' in dashboard
        assert 'id="tierChart"' not in dashboard
        assert 'id="methodChart"' not in dashboard
        assert 'id="classChart"' not in dashboard
        assert 'id="tierChartBreakdown"' in dashboard
        assert 'id="methodChartBreakdown"' in dashboard
        assert 'id="classChartBreakdown"' in dashboard
        assert 'id="classCards"' in dashboard
        assert 'id="filteringOptions"' in dashboard
        assert 'id="definitionButtons"' in dashboard
        assert 'id="helpModal" role="dialog" aria-modal="true"' in dashboard
        assert 'onclick="if(event.target===this)closeDefinition()"' in dashboard
        assert "openDefinition" in dashboard
        assert "closeDefinition" in dashboard
        assert "Escape" in dashboard
        assert "event.key === 'Tab'" in dashboard
        assert "event.preventDefault()" in dashboard
        assert "Country / ct" not in dashboard
        assert "Not available in sample_events.json" not in dashboard
        assert "Raw country/ct is not available in the row sample." not in dashboard
        assert "Country/ct: unavailable in row sample" not in dashboard
        assert "Detected anomaly sample" not in dashboard
        assert "All traffic rows unavailable" not in dashboard
        assert "Device cluster (region/browser/OS sample)" not in dashboard
        assert "Explore detected anomalies" in dashboard
        assert "Clear filters" in dashboard
        assert (
            "Compact row-level controls for the full selected anomaly set." in dashboard
        )
        assert "View data" not in dashboard
        assert "Export CSV" in dashboard
        assert 'id="sampleKpis"' not in dashboard
        assert "renderSampleKpis" not in dashboard
        assert "Filtered anomalies" not in dashboard
        assert "Suppress rows" not in dashboard
        assert "Unique domains" not in dashboard
        assert 'id="sampleTierChart"' in dashboard
        assert 'id="sampleMethodChart"' in dashboard
        assert 'id="sampleDomainChart"' in dashboard
        assert 'select id="filter-${name}" multiple size="1"' in dashboard
        assert 'id="classSelectionNote"' in dashboard
        assert "Viewing:" in dashboard
        assert "row-level filtering is not available for this class" in dashboard
        assert "class-card clickable selected" in dashboard
        assert (
            "Use the legend buttons below to apply filters with a keyboard."
            in dashboard
        )
        assert "clearFilters()" in dashboard
        assert "exportSelection()" in dashboard
        assert "export_scope" in dashboard
        assert "))).join('\\n');" in dashboard
        assert "))).join('\n');" not in dashboard
        assert "Filtered top-250 highest-risk suppress sample" not in dashboard
        assert "Filtered detected anomaly set" in dashboard
        assert "full-run aggregate; not affected by explorer filters" in dashboard
        assert (
            "Full-run aggregate. Explorer filters do not change these KPI cards."
            in dashboard
        )
        assert "sample filters do not change them" not in dashboard
        assert "Overview charts use full-run aggregates" not in dashboard
        assert "Filtered anomaly domains" in dashboard
        assert "Rows below come from `artifacts/selected_events.json`" in dashboard
        assert "full selected detected-anomaly set" in dashboard
        assert "not the full all-traffic population" in dashboard
        assert "Top query terms in detected anomalies" in dashboard
        assert "Top query/domain combinations" in dashboard
        assert "Summary top queries" in dashboard
        assert 'id="activeFilters"' in dashboard
        assert 'id="filteredEvents"' in dashboard
        assert 'id="sampleQueries"' in dashboard
        assert 'id="queryDomainPairs"' in dashboard
        assert 'id="summaryQueries"' in dashboard
        assert 'role="img"' in dashboard
        assert 'aria-label="${escapeHtml(label)} donut chart"' in dashboard
        assert "tierChart donut chart" not in dashboard
        assert "classChart donut chart" not in dashboard
        assert "The required yes/no output" in dashboard
        assert "The suggested business handling" in dashboard
        assert "A high-confidence candidate" in dashboard
        assert "Traffic to hold, delay, sample" in dashboard
        assert "Traffic not selected for action" in dashboard
        assert "Evidence from transparent rules" in dashboard
        assert "How unusual the event looks" in dashboard
        assert "0.58 rule evidence plus 0.42 anomaly-model evidence" in dashboard
        assert "A review group that explains the main pattern" in dashboard
        assert "not measured precision" in dashboard
        assert "The run-specific cutoff" in dashboard
        assert "Data without known right answers" in dashboard
        assert "not proven fraud labels" in dashboard
        assert "ML-only traffic should be sampled or quarantined" in dashboard
        assert "not ground-truth fraud rules" in dashboard
        assert '<p class="label">${escapeHtml(definitions[tier])}</p>' not in dashboard
        assert '<section class="panel">' in dashboard
        assert 'style="margin-bottom' not in dashboard
        assert "renderRuleStrengths(s.rule_strengths || {})" in dashboard
        assert "renderHeuristicThresholds(s.heuristic_thresholds || {})" in dashboard
        assert "Supporting rule score is capped at" in dashboard
        assert "strong rule evidence is not capped" in dashboard
        assert "th-percentile" in dashboard
        assert "threshold, floor" in dashboard
        assert "% percentile" not in dashboard
        assert "Rule evidence" in dashboard
        assert "item.family || item.rule_family || 'general'" in dashboard
        assert "score +${applied} of ${raw}" in dashboard
        assert "method_disagreement || []" in dashboard
        assert (
            "renderMethodChart(s.method_disagreement || [], 'methodChart', "
            not in dashboard
        )
        assert (
            "renderMethodChart(s.method_disagreement || [], 'methodChartBreakdown', "
            "'full-run aggregate, not affected by explorer filters')" in dashboard
        )
        assert "function renderExplorer(rows)" in dashboard
        assert "arguments.length" not in dashboard
        assert "renderQueries(sampleEvents, summary)" not in dashboard
        assert "fetch('/api/anomalies')" in dashboard
        assert "fetch('/api/events')" not in dashboard
        assert "updateFilteredViews()" in dashboard
        assert "methodBucket(event)" in dashboard
        assert "deviceLabel(event)" in dashboard
        assert "renderCountBars('sampleDomainChart'" in dashboard
        assert "rows.length, 'domain')" in dashboard
        assert "applyBarFilter" in dashboard
        assert "toggleFilterValue(name, value)" in dashboard
        assert "Anomaly class aggregate only:" not in dashboard
        assert "filter-query" not in dashboard
        assert "filter-device" not in dashboard
        assert "filter-focus" not in dashboard
        assert 'class="method-bars" role="img"' in dashboard
        assert "Method buckets bar chart for review-relevant events" in dashboard
        assert "label !== 'Neither strong'" in dashboard
        assert "excluded from this review-bucket chart" in dashboard
        assert "renderDonut('tierChart', 'Operational tiers', " not in dashboard
        assert "renderDonut('classChart', 'Anomaly classes', " not in dashboard
        assert "(s.anomaly_classes || {}).classes || []" in dashboard
        assert "0.90 ML agreement" not in dashboard

        features_page = (
            urlopen(base_url + "/features", timeout=5).read().decode("utf-8")
        )
        assert "Bot Hunter Features" in features_page
        assert "escapeHtml" in features_page
        assert 'id="nextButton"' in features_page
        assert "No rows found at offset" in features_page

        report = urlopen(base_url + "/report", timeout=5).read().decode("utf-8")
        assert "<h1>Report</h1>" in report

        payload = json.loads(
            urlopen(base_url + "/api/features?limit=1", timeout=5).read()
        )
        assert payload["feature_names"] == ["log_domain_count", "log_ttc_seconds"]
        assert payload["rows"] == [
            {"event_id": "evt_<script>", "features": [1.386294, 0.01]}
        ]
        assert payload["next_offset"] == 1

        anomalies = json.loads(urlopen(base_url + "/api/anomalies", timeout=5).read())
        assert anomalies == [
            {
                "event_id": "evt_selected",
                "method_bucket": "Heuristic + ML",
                "anomaly_class": "compound_burst_replay",
                "operational_tier": "suppress",
            }
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_runs_pipeline_and_cleans_temp_file(
    monkeypatch, tmp_path: Path
) -> None:
    calls = []

    def fake_run_pipeline(input_path, output_dir):
        path = Path(input_path)
        assert path.exists()
        assert (
            path.read_text(encoding="utf-8")
            == "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com\n"
        )
        calls.append((path, output_dir))
        return {"total_events": 1, "ml_backend": "eif"}

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart(
            {},
            {
                "file": (
                    "clicks.tsv",
                    b"evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com\n",
                )
            },
        )
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        payload = json.loads(urlopen(request, timeout=5).read())
        assert payload == {"total_events": 1, "ml_backend": "eif"}
        assert len(calls) == 1
        assert calls[0][1] == tmp_path
        assert not calls[0][0].exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_reports_missing_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "ROOT", tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart({}, {})
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            urlopen(request, timeout=5)
        except HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
            assert payload["error"] == "Upload a TSV file before running the pipeline"
        else:
            raise AssertionError("missing file should return HTTP 400")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_rejects_oversized_body(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "MAX_UPLOAD_BYTES", 1)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart({}, {"file": ("clicks.tsv", b"too large")})
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            urlopen(request, timeout=5)
        except HTTPError as exc:
            assert exc.code == 413
            payload = json.loads(exc.read().decode("utf-8"))
            assert "Upload exceeds" in payload["error"]
        else:
            raise AssertionError("oversized upload should return HTTP 413")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_reports_invalid_upload_and_cleans_temp_file(
    monkeypatch, tmp_path: Path
) -> None:
    temp_paths = []

    def fake_run_pipeline(input_path, output_dir):
        path = Path(input_path)
        assert path.exists()
        temp_paths.append(path)
        raise ValueError("Line 1 has 1 fields; expected 6")

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        body, content_type = _multipart({}, {"file": ("bad.tsv", b"bad row\n")})
        request = Request(
            base_url + "/upload",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            urlopen(request, timeout=5)
        except HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
            assert payload["error"] == "Line 1 has 1 fields; expected 6"
        else:
            raise AssertionError("invalid upload should return HTTP 400")
        assert len(temp_paths) == 1
        assert not temp_paths[0].exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_run_uses_production_pipeline(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run_pipeline(input_path, output_dir):
        calls.append((str(input_path), output_dir))
        return {"total_events": 0, "ml_backend": "eif"}

    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        payload = json.loads(urlopen(base_url + f"/run?input={raw}", timeout=5).read())
        assert payload == {"total_events": 0, "ml_backend": "eif"}
        assert calls == [(str(raw), tmp_path)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_run_rejects_server_path_outside_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "ROOT", tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            urlopen(base_url + "/run?input=/etc/passwd", timeout=5)
        except HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
            assert "Server-side input path must be under" in payload["error"]
        else:
            raise AssertionError("server path outside root should return HTTP 400")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes]]
) -> tuple[bytes, str]:
    boundary = "----bot-hunter-test-boundary"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    for name, (filename, content) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    "Content-Disposition: form-data; "
                    f'name="{name}"; filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: text/tab-separated-values\r\n\r\n",
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
