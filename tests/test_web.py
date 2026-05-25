import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
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
