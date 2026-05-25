import sys
from pathlib import Path
from types import ModuleType

import pytest

from bot_hunter.pipeline import run_pipeline


def test_pipeline_writes_submission(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
                "evt_2\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
                "evt_3\t2019-12-02 00:00:01\tVenus\tSafari\tAndroid\t/ad_click?d=b.com&ttc=3000&q=human%20search&ct=GB&kl=uk&kp=-1&sld=0&st=mobile_search_intl",
            ]
        ),
        encoding="utf-8",
    )
    summary = run_pipeline(raw, tmp_path)
    assert summary["total_events"] == 3
    assert summary["ml_backend"] == "kmeans"
    submission = (tmp_path / "submission.tsv").read_text(encoding="utf-8")
    assert submission.startswith("event_id\tis_bot\n")
    assert "evt_1" in submission


def test_pipeline_handles_empty_input(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")

    summary = run_pipeline(raw, tmp_path)

    assert summary["total_events"] == 0
    assert summary["bot_events"] == 0
    assert summary["threshold"] == 0.0
    assert (tmp_path / "submission.tsv").read_text(encoding="utf-8") == "event_id\tis_bot\n"


def test_pipeline_can_select_sklearn_backend(monkeypatch, tmp_path: Path) -> None:
    class FakeIsolationForest:
        def __init__(self, random_state: int, contamination: str) -> None:
            self.random_state = random_state
            self.contamination = contamination

        def fit(self, rows) -> "FakeIsolationForest":
            return self

        def decision_function(self, rows) -> list[float]:
            # Fixed values keep the test focused on backend selection and rank normalization.
            return [1.0, 0.5, -1.0][: len(rows)]

    sklearn = ModuleType("sklearn")
    ensemble = ModuleType("sklearn.ensemble")
    ensemble.IsolationForest = FakeIsolationForest
    monkeypatch.setitem(sys.modules, "sklearn", sklearn)
    monkeypatch.setitem(sys.modules, "sklearn.ensemble", ensemble)

    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
                "evt_2\t2019-12-02 00:00:01\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=20&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
                "evt_3\t2019-12-02 00:00:02\tVenus\tSafari\tAndroid\t/ad_click?d=b.com&ttc=3000&q=human%20search&ct=GB&kl=uk&kp=-1&sld=0&st=mobile_search_intl",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_pipeline(raw, tmp_path, ml_backend="sklearn")

    assert summary["ml_backend"] == "sklearn"


def test_pipeline_auto_backend_falls_back_without_sklearn(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.setitem(sys.modules, "sklearn.ensemble", None)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
                "evt_2\t2019-12-02 00:00:01\tVenus\tSafari\tAndroid\t/ad_click?d=b.com&ttc=3000&q=human%20search&ct=GB&kl=uk&kp=-1&sld=0&st=mobile_search_intl",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_pipeline(raw, tmp_path, ml_backend="auto")

    assert summary["ml_backend"] == "kmeans"


def test_pipeline_sklearn_backend_reports_missing_dependency(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.setitem(sys.modules, "sklearn.ensemble", None)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="scikit-learn is not installed"):
        run_pipeline(raw, tmp_path, ml_backend="sklearn")
