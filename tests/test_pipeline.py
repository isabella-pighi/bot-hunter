import sys
from datetime import datetime
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

import pytest

from bot_hunter.data import ClickEvent
from bot_hunter.pipeline import _assign_operational_tier, _method_disagreement, _normalize_reason, run_pipeline


class FakeIsolationForest:
    last_instance: "FakeIsolationForest | None" = None

    def __init__(self, random_state: int, contamination: str, max_samples: int, max_features: float) -> None:
        self.random_state = random_state
        self.contamination = contamination
        self.max_samples = max_samples
        self.max_features = max_features
        FakeIsolationForest.last_instance = self

    def fit(self, rows) -> "FakeIsolationForest":
        return self

    def decision_function(self, rows) -> list[float]:
        # Fixed values keep the test focused on backend selection and rank normalization.
        return [1.0, 0.5, -1.0][: len(rows)]


def install_fake_sklearn(monkeypatch) -> None:
    FakeIsolationForest.last_instance = None
    sklearn = ModuleType("sklearn")
    sklearn.__spec__ = ModuleSpec("sklearn", loader=None, is_package=True)
    ensemble = ModuleType("sklearn.ensemble")
    ensemble.__spec__ = ModuleSpec("sklearn.ensemble", loader=None)
    ensemble.IsolationForest = FakeIsolationForest
    monkeypatch.setitem(sys.modules, "sklearn", sklearn)
    monkeypatch.setitem(sys.modules, "sklearn.ensemble", ensemble)


def hide_sklearn(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.setitem(sys.modules, "sklearn.ensemble", None)


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
    summary = run_pipeline(raw, tmp_path, ml_backend="kmeans")
    assert summary["total_events"] == 3
    assert summary["ml_backend"] == "kmeans"
    assert summary["feature_artifact"] == "artifacts/features.tsv"
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 2, "monitor": 1}
    submission = (tmp_path / "submission.tsv").read_text(encoding="utf-8")
    assert submission.startswith("event_id\tis_bot\toperational_tier\n")
    assert "evt_1" in submission
    sample_events = (tmp_path / "artifacts" / "sample_events.json").read_text(encoding="utf-8")
    assert '"operational_tier"' in sample_events
    assert '"rule_contributions"' in sample_events
    assert '"threshold_mode": "absolute"' in sample_events
    assert '"rule_id": "fast_click"' in sample_events
    assert "method_disagreement" in summary
    assert sum(count for _, count in summary["method_disagreement"]) == 3
    report = (tmp_path / "docs" / "analysis_report.md").read_text(encoding="utf-8")
    assert "Methods evaluated but not included" in report
    assert "HDBSCAN" in report
    assert "an unsupervised k-means anomaly model" in report
    features = (tmp_path / "artifacts" / "features.tsv").read_text(encoding="utf-8").splitlines()
    assert features[0].split("\t") == ["event_id", *summary["feature_names"]]
    assert "is_mobile_search" not in summary["feature_names"]
    assert "log_ttc_seconds" in summary["feature_names"]
    assert "is_sub_200ms_click" in summary["feature_names"]
    assert "log_pseudo_session_10s_click_count" in summary["feature_names"]
    assert "query_entropy" in summary["feature_names"]
    assert len(features) == 4
    first_feature_row = features[1].split("\t")
    assert first_feature_row == [
        "evt_1",
        "1.098612",
        "1.098612",
        "1.098612",
        "1.098612",
        "1.098612",
        "1.098612",
        "0.010000",
        "2.000000",
        "7.000000",
        "0.000000",
        "0.000000",
        "-1.000000",
        "1.000000",
        "0.000000",
        "0.009950",
        "1.000000",
        "1.098612",
        "2.521641",
    ]


def test_pipeline_handles_empty_input(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")

    summary = run_pipeline(raw, tmp_path)

    assert summary["total_events"] == 0
    assert summary["bot_events"] == 0
    assert summary["threshold"] == 0.0
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 0}
    assert (tmp_path / "submission.tsv").read_text(encoding="utf-8") == "event_id\tis_bot\toperational_tier\n"
    assert (tmp_path / "artifacts" / "features.tsv").read_text(encoding="utf-8") == (
        "event_id\t" + "\t".join(summary["feature_names"]) + "\n"
    )


def test_pipeline_can_select_sklearn_backend(monkeypatch, tmp_path: Path) -> None:
    install_fake_sklearn(monkeypatch)
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
    assert FakeIsolationForest.last_instance is not None
    assert FakeIsolationForest.last_instance.max_samples == 3
    assert FakeIsolationForest.last_instance.max_features == 0.85
    report = (tmp_path / "docs" / "analysis_report.md").read_text(encoding="utf-8")
    assert "an Isolation Forest anomaly model" in report


def test_pipeline_default_prefers_sklearn_when_available(monkeypatch, tmp_path: Path) -> None:
    install_fake_sklearn(monkeypatch)
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

    summary = run_pipeline(raw, tmp_path)

    assert summary["ml_backend"] == "sklearn"


def test_pipeline_default_falls_back_without_sklearn(monkeypatch, tmp_path: Path) -> None:
    hide_sklearn(monkeypatch)
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

    summary = run_pipeline(raw, tmp_path)

    assert summary["ml_backend"] == "kmeans"


def test_pipeline_sklearn_backend_reports_missing_dependency(monkeypatch, tmp_path: Path) -> None:
    hide_sklearn(monkeypatch)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="scikit-learn is not installed"):
        run_pipeline(raw, tmp_path, ml_backend="sklearn")


def test_normalize_reason_handles_regular_interarrival() -> None:
    assert (
        _normalize_reason("regular inter-arrival timing (8 clicks, mean 214.7s, cv 0.224)")
        == "regular inter-arrival timing"
    )


def test_method_disagreement_buckets_partition_events_by_agreement_thresholds() -> None:
    events = [
        ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_2", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_3", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_4", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
    ]
    events[0].heuristic_score = 0.62
    events[0].ml_score = 0.90
    events[1].heuristic_score = 0.70
    events[1].ml_score = 0.10
    events[2].heuristic_score = 0.10
    events[2].ml_score = 0.95
    events[3].heuristic_score = 0.10
    events[3].ml_score = 0.10

    assert _method_disagreement(events) == [
        ("Heuristic + ML", 1),
        ("Heuristic only", 1),
        ("ML only", 1),
        ("Neither strong", 1),
    ]


def test_operational_tier_boundaries() -> None:
    event = ClickEvent("evt", datetime(2019, 12, 2), "Mars", "Chrome", "Android", "")

    event.is_bot = 0
    event.combined_score = 0.99
    event.heuristic_score = 1.0
    event.ml_score = 1.0
    assert _assign_operational_tier(event) == "monitor"

    event.is_bot = 1
    event.combined_score = 0.7999
    event.heuristic_score = 0.6199
    event.ml_score = 0.8999
    assert _assign_operational_tier(event) == "quarantine"

    event.combined_score = 0.80
    assert _assign_operational_tier(event) == "suppress"

    event.combined_score = 0.50
    event.heuristic_score = 0.80
    assert _assign_operational_tier(event) == "suppress"

    event.heuristic_score = 0.62
    event.ml_score = 0.90
    assert _assign_operational_tier(event) == "suppress"
