import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

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
        assert 'placeholder="/path/to/bot-hunter-dataset.tsv"' in dashboard
        assert 'id="mlBackend"' in dashboard
        assert "Operational confidence" in dashboard
        assert "Method Disagreement" in dashboard

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


def test_web_run_passes_selected_backend(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run_pipeline(input_path, output_dir, ml_backend="auto"):
        calls.append((str(input_path), output_dir, ml_backend))
        return {"total_events": 0, "ml_backend": ml_backend}

    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "run_pipeline", fake_run_pipeline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        payload = json.loads(
            urlopen(base_url + "/run?input=/tmp/clicks.tsv&ml_backend=kmeans", timeout=5).read()
        )
        assert payload == {"total_events": 0, "ml_backend": "kmeans"}
        assert calls == [("/tmp/clicks.tsv", tmp_path, "kmeans")]

        try:
            urlopen(base_url + "/run?input=/tmp/clicks.tsv&ml_backend=bad", timeout=5)
        except HTTPError as exc:
            assert exc.code == 400
            error_payload = json.loads(exc.read().decode("utf-8"))
            assert error_payload["error"] == "ml_backend must be auto, sklearn, or kmeans"
        else:
            raise AssertionError("invalid backend should return HTTP 400")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
