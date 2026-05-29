import sys
from datetime import datetime
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

import pytest

from bot_hunter.data import ClickEvent, RuleContribution
from bot_hunter.ml import _assign_rank_scores
from bot_hunter.pipeline import (
    _anomaly_classes,
    _assign_operational_tier,
    _method_disagreement,
    _normalize_reason,
    run_pipeline,
)


class FakeEIF:
    last_instance: "FakeEIF | None" = None

    def __init__(
        self,
        sample_size: int,
        ntrees: int,
        ndim: int,
        missing_action: str,
        standardize_data: bool,
        random_seed: int,
        nthreads: int,
    ) -> None:
        self.sample_size = sample_size
        self.ntrees = ntrees
        self.ndim = ndim
        self.missing_action = missing_action
        self.standardize_data = standardize_data
        self.random_seed = random_seed
        self.nthreads = nthreads
        self.fit_column_count = 0
        FakeEIF.last_instance = self

    def fit(self, rows) -> "FakeEIF":
        self.fit_column_count = rows.shape[1] if len(rows) else 0
        return self

    def decision_function(self, rows) -> list[float]:
        return [0.1, 0.5, 1.0][: len(rows)]


def install_fake_isotree(monkeypatch) -> None:
    FakeEIF.last_instance = None
    isotree = ModuleType("isotree")
    isotree.__spec__ = ModuleSpec("isotree", loader=None)
    isotree.IsolationForest = FakeEIF
    monkeypatch.setitem(sys.modules, "isotree", isotree)


def hide_isotree(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "isotree", None)


def _classified_event(
    event_id: str,
    *,
    heuristic_score: float,
    ml_score: float,
    combined_score: float,
    is_bot: int,
    tier: str,
    rule_ids: list[str],
) -> ClickEvent:
    event = ClickEvent(
        event_id=event_id,
        event_time=datetime(2019, 12, 2, 0, 0, 0),
        region="Mars",
        browser="Chrome",
        os="iOS",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
        heuristic_score=heuristic_score,
        ml_score=ml_score,
        combined_score=combined_score,
        is_bot=is_bot,
        operational_tier=tier,
    )
    event.rule_contributions = [
        RuleContribution(
            rule_id=rule_id,
            label=rule_id.replace("_", " ").title(),
            reason=rule_id,
            weight=0.10,
            applied_weight=0.10,
            observed=1,
        )
        for rule_id in rule_ids
    ]
    return event


def test_pipeline_writes_submission(monkeypatch, tmp_path: Path) -> None:
    install_fake_isotree(monkeypatch)
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
    assert summary["ml_backend"] == "eif"
    assert summary["feature_artifact"] == "artifacts/features.tsv"
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 3}
    submission = (tmp_path / "submission.tsv").read_text(encoding="utf-8")
    assert submission.startswith("event_id\tis_bot\toperational_tier\n")
    assert "evt_1" in submission
    sample_events = (tmp_path / "artifacts" / "sample_events.json").read_text(
        encoding="utf-8"
    )
    assert '"operational_tier"' in sample_events
    assert '"rule_contributions"' in sample_events
    assert '"threshold_mode": "absolute"' in sample_events
    assert '"rule_id": "fast_click"' in sample_events
    assert '"strength": "strong"' in sample_events
    assert '"family": "timing"' in sample_events
    assert '"applied_weight":' in sample_events
    assert '"capped":' in sample_events
    assert "method_disagreement" in summary
    assert sum(count for _, count in summary["method_disagreement"]) == 3
    assert "_".join(["method", "disagreement", "extreme"]) not in summary
    assert "_".join(["method", "disagreement", "support"]) not in summary
    assert summary["tier_thresholds"]["ml_agreement_score"] == 0.975
    assert summary["heuristic_thresholds"]["repeat_query_domain"]["threshold"] == 4
    assert (
        summary["heuristic_thresholds"]["repeat_query_domain"]["threshold_mode"]
        == "adaptive_percentile"
    )
    assert summary["heuristic_thresholds"]["repeat_query_domain"]["absolute_floor"] == 4
    assert "rule_strengths" in summary
    assert summary["rule_strengths"]["supporting_cap"] == 0.24
    assert "anomaly_classes" in summary
    assert summary["anomaly_classes"]["selected_event_count"] == 0
    assert summary["anomaly_classes"]["classified_selected_event_count"] == 0
    assert summary["anomaly_classes"]["ml_only_population_count"] == 1
    assert summary["anomaly_classes"]["classes"][0]["class_id"] == (
        "repetition_with_supporting_context"
    )
    assert summary["anomaly_classes"]["filtering_options"][0]["name"] == (
        "Conservative suppression review"
    )
    assert "_".join(["ml", "support", "score"]) not in summary["tier_thresholds"]
    assert (
        "_".join(["suppress", "agreement", "ml", "score"])
        not in summary["tier_thresholds"]
    )
    report = (tmp_path / "docs" / "analysis_report.md").read_text(encoding="utf-8")
    assert "Extended Isolation Forest model catches" in report
    assert "## 1. Problem Statement" in report
    assert "## 2. Methodology And Rationale" in report
    assert "## 3. Current Statistical Findings" in report
    assert "## 4. Explanation Of Anomalies Found" in report
    assert "## 5. Recommended Business Actions" in report
    assert "## 6. Probability Perspective" in report
    assert "## 7. Generalisation, Trade-Offs, And Limitations" in report
    assert "## 8. Future Work" in report
    assert "## Appendix A: Metric Definitions" in report
    assert "## Appendix B: Feature Definitions" in report
    assert "## Appendix C: Model Definition" in report
    assert "these are not proven fraud labels" in report
    assert "Practical filtering options for similar unlabelled datasets" in report
    assert "Conservative suppression review" in report
    assert "ML-tail sampling" in report
    assert "This is not measured precision" in report
    assert "calibrated fraud probability" in report
    assert "Adaptive heuristic thresholds used in this run" in report
    assert (
        "Rule contributions are separated into strong and supporting evidence" in report
    )
    assert "Capped together at 0.24" in report
    assert "Repeated query/domain pair (`repeat_query_domain`)" in report
    assert "99th-percentile threshold" in report
    assert "% percentile" not in report
    assert "alternate ML backends and supervised pilots have been removed" in report
    assert "Methods evaluated but not included" not in report
    html_report = (tmp_path / "docs" / "analysis_report.html").read_text(
        encoding="utf-8"
    )
    assert "<table><thead><tr>" in html_report
    assert "</thead><tbody>" in html_report
    assert "<th>Rule</th>" in html_report
    assert "<h2>4. Explanation Of Anomalies Found</h2>" in html_report
    assert "<h2>Appendix A: Metric Definitions</h2>" in html_report
    assert "<th>Class</th>" in html_report
    assert "Repeated query/domain pair" in html_report
    features = (
        (tmp_path / "artifacts" / "features.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert features[0].split("\t") == ["event_id", *summary["feature_names"]]
    assert "is_mobile_search" not in summary["feature_names"]
    assert "log_ttc_seconds" in summary["feature_names"]
    assert "is_sub_200ms_click" in summary["feature_names"]
    assert "log_pseudo_session_10s_click_count" in summary["feature_names"]
    assert "query_entropy" in summary["feature_names"]
    assert "log_country_count" in summary["feature_names"]
    assert "log_kp_count" in summary["feature_names"]
    assert "log_sld_count" in summary["feature_names"]
    assert "query_terms" not in summary["feature_names"]
    assert "query_chars" not in summary["feature_names"]
    assert "has_bkl" not in summary["feature_names"]
    assert "has_om" not in summary["feature_names"]
    assert "log_device_count" in summary["ml_feature_names"]
    assert "log_kp_count" in summary["ml_feature_names"]
    assert "log_sld_count" in summary["ml_feature_names"]
    assert "kp" not in summary["ml_feature_names"]
    assert "sld" not in summary["ml_feature_names"]
    assert summary["ml_feature_weights"]["log_domain_count"] == 0.5
    assert summary["ml_feature_weights"]["log_country_count"] == 0.5
    assert summary["ml_feature_weights"]["log_query_domain_count"] == 0.5
    assert summary["ml_feature_weights"]["log_query_count"] == 0.5
    assert summary["ml_feature_weights"]["log_kp_count"] == 0.5
    assert summary["ml_feature_weights"]["log_sld_count"] == 0.25
    assert summary["ml_feature_weights"]["log_ttc_seconds"] == 0.5
    assert summary["ml_feature_weights"]["is_sub_200ms_click"] == 0.5
    assert summary["ml_feature_weights"]["query_entropy"] == 0.5
    assert summary["ml_feature_weights"]["log_device_count"] == 1.0
    assert len(summary["feature_names"]) == 16
    assert len(summary["ml_feature_names"]) == 14
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
        "1.098612",
        "1.386294",
        "1.098612",
        "-1.000000",
        "1.000000",
        "0.000000",
        "0.009950",
        "1.000000",
        "1.098612",
        "2.521641",
    ]


def test_anomaly_classes_use_selected_counts_and_ml_only_population() -> None:
    events = [
        _classified_event(
            "evt_replay_context",
            heuristic_score=0.86,
            ml_score=0.99,
            combined_score=0.91,
            is_bot=1,
            tier="suppress",
            rule_ids=[
                "repeat_query_domain",
                "repeat_query",
                "confirmed_query_repetition",
                "high_volume_domain",
            ],
        ),
        _classified_event(
            "evt_ml_selected",
            heuristic_score=0.40,
            ml_score=0.99,
            combined_score=0.65,
            is_bot=1,
            tier="quarantine",
            rule_ids=["fast_click"],
        ),
        _classified_event(
            "evt_ml_monitor",
            heuristic_score=0.10,
            ml_score=0.98,
            combined_score=0.47,
            is_bot=0,
            tier="monitor",
            rule_ids=[],
        ),
    ]

    classes = _anomaly_classes(events)
    by_id = {item["class_id"]: item for item in classes["classes"]}

    assert classes["selected_event_count"] == 2
    assert classes["classified_selected_event_count"] == 2
    assert classes["ml_only_population_count"] == 2
    assert by_id["repetition_with_supporting_context"]["count"] == 1
    assert by_id["repetition_with_supporting_context"]["tier_counts"] == {"suppress": 1}
    assert by_id["repetition_with_supporting_context"]["method_counts"] == {
        "Heuristic + ML": 1
    }
    assert (
        by_id["repetition_with_supporting_context"]["examples"][0]["event_id"]
        == "evt_replay_context"
    )
    assert by_id["ml_tail_multivariate"]["count"] == 1
    assert by_id["ml_tail_multivariate"]["population_count"] == 2
    assert by_id["ml_tail_multivariate"]["method_counts"] == {"ML only": 1}
    assert by_id["ml_tail_multivariate"]["dominant_rules"] == []
    assert "rule_ids" not in by_id["ml_tail_multivariate"]["examples"][0]
    assert "not proven fraud labels" in classes["scope"]


def test_single_event_pipeline_is_not_selected_by_percentile_gate(
    monkeypatch, tmp_path: Path
) -> None:
    install_fake_isotree(monkeypatch)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&ttc=3000&q=human%20search&ct=US&kl=en&kp=-1&sld=1",
        encoding="utf-8",
    )

    summary = run_pipeline(raw, tmp_path)
    submission = (tmp_path / "submission.tsv").read_text(encoding="utf-8")

    assert summary["bot_events"] == 0
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 1}
    assert submission == "event_id\tis_bot\toperational_tier\nevt_1\t0\tmonitor\n"


def test_all_tied_combined_scores_do_not_flag_all_events(
    monkeypatch, tmp_path: Path
) -> None:
    def score_tied_anomalies(events: list[ClickEvent]) -> str:
        for event in events:
            event.ml_score = 0.5
        return "test"

    monkeypatch.setattr("bot_hunter.pipeline.score_anomalies", score_tied_anomalies)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                f"evt_{idx}\t2019-12-02 00:00:0{idx}\tMars\tChrome\tiOS\t"
                f"/ad_click?d=a-{idx}.com&ttc=3000&q=human%20search%20{idx}"
                for idx in range(3)
            ]
        ),
        encoding="utf-8",
    )

    summary = run_pipeline(raw, tmp_path)

    assert summary["bot_events"] == 0
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 3}


def test_all_tied_anomaly_scores_use_non_inflated_midrank() -> None:
    events = [
        ClickEvent(f"evt_{idx}", datetime(2019, 12, 2), "Mars", "Chrome", "Android", "")
        for idx in range(4)
    ]

    _assign_rank_scores(events, [0.5, 0.5, 0.5, 0.5])

    assert [event.ml_score for event in events] == [0.5, 0.5, 0.5, 0.5]


def test_pipeline_handles_empty_input(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")

    summary = run_pipeline(raw, tmp_path)

    assert summary["total_events"] == 0
    assert summary["bot_events"] == 0
    assert summary["threshold"] == 0.0
    assert summary["tier_counts"] == {"suppress": 0, "quarantine": 0, "monitor": 0}
    assert (tmp_path / "submission.tsv").read_text(
        encoding="utf-8"
    ) == "event_id\tis_bot\toperational_tier\n"
    assert (tmp_path / "artifacts" / "features.tsv").read_text(encoding="utf-8") == (
        "event_id\t" + "\t".join(summary["feature_names"]) + "\n"
    )


def test_pipeline_uses_eif_backend(monkeypatch, tmp_path: Path) -> None:
    install_fake_isotree(monkeypatch)
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

    assert summary["ml_backend"] == "eif"
    assert FakeEIF.last_instance is not None
    assert FakeEIF.last_instance.sample_size == 3
    assert FakeEIF.last_instance.ndim == 2
    assert FakeEIF.last_instance.standardize_data is False
    assert FakeEIF.last_instance.fit_column_count == 14
    report = (tmp_path / "docs" / "analysis_report.md").read_text(encoding="utf-8")
    assert "Extended Isolation Forest model catches" in report


def test_pipeline_eif_backend_reports_missing_dependency(
    monkeypatch, tmp_path: Path
) -> None:
    hide_isotree(monkeypatch)
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Extended Isolation Forest requires isotree"):
        run_pipeline(raw, tmp_path)


def test_normalize_reason_handles_regular_interarrival() -> None:
    assert (
        _normalize_reason(
            "regular inter-arrival timing (8 clicks, mean 214.7s, cv 0.224)"
        )
        == "regular inter-arrival timing"
    )


def test_normalize_reason_handles_dense_burst_repetition_cluster() -> None:
    assert (
        _normalize_reason(
            "dense burst repetition cluster (device 43674, same-second 5, query 1226)"
        )
        == "dense burst repetition cluster"
    )


def test_normalize_reason_handles_confirmed_query_repetition() -> None:
    assert (
        _normalize_reason("confirmed query repetition (query/domain 184, query 1226)")
        == "confirmed query repetition"
    )


def test_normalize_reason_handles_concentrated_ct_context() -> None:
    assert (
        _normalize_reason("concentrated ct context (US 1000, device 600, query 12)")
        == "concentrated ct context"
    )


def test_method_disagreement_buckets_partition_events_by_agreement_thresholds() -> None:
    events = [
        ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_2", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_3", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_4", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
    ]
    events[0].heuristic_score = 0.62
    events[0].ml_score = 0.975
    events[1].heuristic_score = 0.70
    events[1].ml_score = 0.10
    events[2].heuristic_score = 0.10
    events[2].ml_score = 1.0
    events[3].heuristic_score = 0.10
    events[3].ml_score = 0.10

    assert _method_disagreement(events) == [
        ("Heuristic + ML", 1),
        ("Heuristic only", 1),
        ("ML only", 1),
        ("Neither strong", 1),
    ]
    assert _method_disagreement(events, ml_threshold=0.975) == [
        ("Heuristic + ML", 1),
        ("Heuristic only", 1),
        ("ML only", 1),
        ("Neither strong", 1),
    ]


def test_method_disagreement_uses_single_ml_agreement_threshold() -> None:
    events = [
        ClickEvent("evt_1", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_2", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_3", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
        ClickEvent("evt_4", datetime(2019, 12, 2), "Mars", "Chrome", "Android", ""),
    ]
    events[0].heuristic_score = 0.62
    events[0].ml_score = 0.980
    events[1].heuristic_score = 0.62
    events[1].ml_score = 0.994
    events[2].heuristic_score = 0.10
    events[2].ml_score = 0.980
    events[3].heuristic_score = 0.10
    events[3].ml_score = 0.10

    assert _method_disagreement(events) == [
        ("Heuristic + ML", 2),
        ("Heuristic only", 0),
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
    event.ml_score = 0.975
    assert _assign_operational_tier(event) == "suppress"
