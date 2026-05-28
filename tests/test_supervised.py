from pathlib import Path

from bot_hunter.data import ClickEvent
from bot_hunter.heuristics import _contribution
from bot_hunter.supervised import STRICT_SEED_RULE_IDS, _is_strict_seed_positive, run_supervised_pilot


def test_strict_seed_positive_uses_only_approved_rule_ids() -> None:
    event = ClickEvent("evt", None, "Mars", "Chrome", "Android", "")  # type: ignore[arg-type]
    event.heuristic_score = 1.0
    event.ml_score = 1.0
    event.combined_score = 1.0
    event.rule_contributions = [
        _contribution("short_query", "Very short query", "very short query", 0.04, 1, 1, "query_terms <= threshold")
    ]

    assert not _is_strict_seed_positive(event)

    event.rule_contributions = [
        _contribution(
            "regular_interarrival",
            "Regular inter-arrival timing",
            "regular inter-arrival timing",
            0.10,
            "1.0s",
            "low variance",
            "regular_interarrival == true",
        )
    ]

    assert not _is_strict_seed_positive(event)

    event.heuristic_score = 0.0
    event.ml_score = 0.0
    event.combined_score = 0.0
    event.rule_contributions = [
        _contribution(
            "same_second_burst",
            "Same-second click burst",
            "12 clicks in the same second",
            0.12,
            12,
            4,
            "same_second_count >= threshold",
        )
    ]

    assert _is_strict_seed_positive(event)


def test_supervised_pilot_writes_additive_comparison(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    rows = []
    for index in range(12):
        rows.append(
            f"seed_{index}\t2019-12-02 00:00:{index:02d}\tMars\tChrome\tAndroid\t"
            "/ad_click?d=seed.example&q=repeat&ttc=10&ct=US&kp=-1&sld=1"
        )
    for index in range(12):
        rows.append(
            f"background_{index}\t2019-12-02 00:01:{index:02d}\tEarth\tSafari\tiOS\t"
            f"/ad_click?d=site{index}.example&q=query{index}&ttc=3000&ct=GB&kp=-1&sld=0"
        )
    raw.write_text("\n".join(rows), encoding="utf-8")

    summary = run_supervised_pilot(raw, tmp_path, ml_backend="kmeans")

    assert summary["production_scoring_changed"] is False
    assert summary["baseline_method"] == "rules+unsupervised"
    assert summary["supervised_method"] == "rules+supervised_seed_likeness"
    assert summary["seed_policy"]["positive_rule_ids"] == sorted(STRICT_SEED_RULE_IDS)
    assert "regular_interarrival" not in summary["seed_policy"]["positive_rule_ids"]
    assert "heuristic_score" in summary["seed_policy"]["excluded_sources"]
    assert summary["seed_counts"]["total_positive"] == 12
    assert summary["comparison"]["baseline"]["selected_events"] >= 1
    assert summary["comparison"]["supervised"]["selected_events"] >= 1
    assert "log_country_domain_count" not in summary["feature_names"]
    assert (tmp_path / "artifacts" / "supervised_pilot.json").exists()
    assert (tmp_path / "docs" / "supervised_pilot_report.md").exists()
    assert (tmp_path / "docs" / "supervised_pilot_report.html").exists()
    assert not (tmp_path / "submission.tsv").exists()
    assert not (tmp_path / "artifacts" / "summary.json").exists()
