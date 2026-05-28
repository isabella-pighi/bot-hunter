import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bot_hunter import web


def test_web_serves_feature_page_and_api(monkeypatch, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    docs = tmp_path / "docs"
    artifacts.mkdir()
    docs.mkdir()
    (artifacts / "summary.json").write_text('{"total_events": 1}', encoding="utf-8")
    (artifacts / "sample_events.json").write_text("[]", encoding="utf-8")
    (artifacts / "features.tsv").write_text(
        "event_id\tlog_domain_count\tttc_seconds\n"
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
        assert 'id="inputPath" class="dataset-field" placeholder="/path/to/bot-hunter-dataset.tsv"' in dashboard
        assert "Choose a local .tsv file to upload and analyze." in dashboard
        assert "Use only when the TSV already exists on the machine running this dashboard." in dashboard
        assert "Only the active mode is submitted; the other input is ignored regardless of its state." in dashboard
        assert "inputMode === 'upload' ? await uploadAndRun(file) : await runPath(inputPath)" in dashboard
        assert "Choose a TSV file before running the pipeline." in dashboard
        assert "Enter a file path before running the pipeline." in dashboard
        assert 'id="mlBackend"' not in dashboard
        assert "Operational confidence" in dashboard
        assert "Method Disagreement" in dashboard
        assert "EIF tail >= ${ml}" in dashboard
        assert "0.90 ML agreement" not in dashboard

        features_page = urlopen(base_url + "/features", timeout=5).read().decode("utf-8")
        assert "Bot Hunter Features" in features_page
        assert "escapeHtml" in features_page
        assert 'id="nextButton"' in features_page
        assert "No rows found at offset" in features_page

        report = urlopen(base_url + "/report", timeout=5).read().decode("utf-8")
        assert "<h1>Report</h1>" in report

        payload = json.loads(urlopen(base_url + "/api/features?limit=1", timeout=5).read())
        assert payload["feature_names"] == ["log_domain_count", "ttc_seconds"]
        assert payload["rows"] == [{"event_id": "evt_<script>", "features": [1.386294, 0.01]}]
        assert payload["next_offset"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_web_upload_runs_pipeline_and_cleans_temp_file(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run_pipeline(input_path, output_dir):
        path = Path(input_path)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com\n"
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
            {"file": ("clicks.tsv", b"evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com\n")},
        )
        request = Request(base_url + "/upload", data=body, headers={"Content-Type": content_type}, method="POST")
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
        request = Request(base_url + "/upload", data=body, headers={"Content-Type": content_type}, method="POST")
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


def test_web_upload_reports_invalid_upload_and_cleans_temp_file(monkeypatch, tmp_path: Path) -> None:
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
        request = Request(base_url + "/upload", data=body, headers={"Content-Type": content_type}, method="POST")
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

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        payload = json.loads(urlopen(base_url + "/run?input=/tmp/clicks.tsv", timeout=5).read())
        assert payload == {"total_events": 0, "ml_backend": "eif"}
        assert calls == [("/tmp/clicks.tsv", tmp_path)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
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
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
                b"Content-Type: text/tab-separated-values\r\n\r\n",
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
