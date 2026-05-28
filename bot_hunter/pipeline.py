from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .data import build_features, iter_event_dicts, parse_clicks, select_ml_feature_names, select_ml_feature_weights
from .heuristics import apply_heuristics
from .ml import score_anomalies
from .report import write_reports

# Heuristics stay slightly dominant because they are directly explainable and
# easier to validate in audits, while ML still has enough influence to move
# borderline cases and surface multivariate anomalies.
COMBINED_HEURISTIC_WEIGHT = 0.58
COMBINED_ML_WEIGHT = 0.42

# These are conservative operational guardrails rather than learned cutoffs.
SUPPRESS_COMBINED_THRESHOLD = 0.80
SUPPRESS_HEURISTIC_THRESHOLD = 0.80
SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD = 0.62
SUPPRESS_AGREEMENT_ML_THRESHOLD = 0.995


def run_pipeline(input_path: str | Path, output_dir: str | Path = ".") -> dict[str, object]:
    root = Path(output_dir)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    events = parse_clicks(input_path)
    feature_names, counters = build_features(events)
    ml_feature_names = select_ml_feature_names(feature_names)
    ml_feature_weights = select_ml_feature_weights(feature_names)
    apply_heuristics(events, counters)
    ml_backend_used = score_anomalies(events)

    combined = []
    for event in events:
        event.combined_score = (COMBINED_HEURISTIC_WEIGHT * event.heuristic_score) + (
            COMBINED_ML_WEIGHT * event.ml_score
        )
        combined.append(event.combined_score)

    cutoff = _quantile(combined, 0.975) if combined else 0.0
    for event in events:
        event.is_bot = 1 if event.combined_score >= cutoff or event.heuristic_score >= 0.62 else 0
        event.operational_tier = _assign_operational_tier(event)

    bot_events = [event for event in events if event.is_bot]
    both_count = sum(
        1
        for event in bot_events
        if event.heuristic_score >= 0.45 and event.ml_score >= SUPPRESS_AGREEMENT_ML_THRESHOLD
    )
    estimated_precision = min(0.95, max(0.55, 0.58 + 0.35 * (both_count / max(len(bot_events), 1))))

    reason_counter: Counter[str] = Counter()
    for event in bot_events:
        for reason in event.reasons:
            reason_counter[_normalize_reason(reason)] += 1

    top_domains = counters["domain"].most_common(12)
    top_queries = counters["query"].most_common(12)
    top_regions = Counter(event.region for event in bot_events).most_common(8)
    tier_counts = Counter(event.operational_tier for event in events)
    summary = {
        "input_path": str(Path(input_path).expanduser()),
        "total_events": len(events),
        "bot_events": len(bot_events),
        "bot_rate": len(bot_events) / max(len(events), 1),
        "threshold": cutoff,
        "heuristic_flag_rate": sum(1 for event in events if event.heuristic_score >= 0.62) / max(len(events), 1),
        "ml_tail_rate": sum(
            1 for event in events if event.ml_score >= SUPPRESS_AGREEMENT_ML_THRESHOLD
        )
        / max(len(events), 1),
        "estimated_precision": estimated_precision,
        "ml_backend": ml_backend_used,
        "feature_artifact": "artifacts/features.tsv",
        "feature_names": feature_names,
        "ml_feature_names": ml_feature_names,
        "ml_feature_weights": dict(zip(ml_feature_names, ml_feature_weights)),
        "operational_tiers": {
            "suppress": "High-confidence bot traffic suitable for automatic suppression after policy approval.",
            "quarantine": "Bot traffic that should be held for review before suppression.",
            "monitor": "Traffic not selected for bot action; keep for trend monitoring and future labels.",
        },
        "method_disagreement": _method_disagreement(events),
        "tier_thresholds": {
            "suppress_combined_score": SUPPRESS_COMBINED_THRESHOLD,
            "suppress_heuristic_score": SUPPRESS_HEURISTIC_THRESHOLD,
            "suppress_agreement_heuristic_score": SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD,
            "suppress_agreement_ml_score": SUPPRESS_AGREEMENT_ML_THRESHOLD,
            "ml_only_tuning": (
                "EIF agreement uses the extreme rank tail so the disagreement report does not "
                "treat broad unsupervised anomaly ranks as standalone bot evidence."
            ),
            "quarantine": "is_bot == 1 and suppress conditions are not met",
            "monitor": "is_bot == 0",
        },
        "tier_counts": {tier: tier_counts.get(tier, 0) for tier in ("suppress", "quarantine", "monitor")},
        "top_reasons": reason_counter.most_common(10),
        "top_domains": top_domains,
        "top_queries": top_queries,
        "bot_regions": top_regions,
    }

    _write_submission(root / "submission.tsv", events)
    _write_json(artifacts / "summary.json", summary)
    _write_features(artifacts / "features.tsv", feature_names, events)
    sample = sorted(events, key=lambda event: event.combined_score, reverse=True)[:250]
    _write_json(artifacts / "sample_events.json", list(iter_event_dicts(sample)))
    write_reports(summary, root / "docs")
    return summary


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _assign_operational_tier(event) -> str:
    if not event.is_bot:
        return "monitor"
    if (
        event.combined_score >= SUPPRESS_COMBINED_THRESHOLD
        or event.heuristic_score >= SUPPRESS_HEURISTIC_THRESHOLD
        or (
            event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
            and event.ml_score >= SUPPRESS_AGREEMENT_ML_THRESHOLD
        )
    ):
        return "suppress"
    return "quarantine"


def _method_disagreement(events) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for event in events:
        heuristic_high = event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
        ml_high = event.ml_score >= SUPPRESS_AGREEMENT_ML_THRESHOLD
        if heuristic_high and ml_high:
            counts["Heuristic + ML"] += 1
        elif heuristic_high:
            counts["Heuristic only"] += 1
        elif ml_high:
            counts["ML only"] += 1
        else:
            counts["Neither strong"] += 1
    return [
        ("Heuristic + ML", counts.get("Heuristic + ML", 0)),
        ("Heuristic only", counts.get("Heuristic only", 0)),
        ("ML only", counts.get("ML only", 0)),
        ("Neither strong", counts.get("Neither strong", 0)),
    ]


def _write_submission(path: Path, events) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("event_id\tis_bot\toperational_tier\n")
        for event in events:
            handle.write(f"{event.event_id}\t{event.is_bot}\t{event.operational_tier}\n")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_features(path: Path, feature_names: list[str], events) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(["event_id", *feature_names]) + "\n")
        for event in events:
            values = [f"{value:.6f}" for value in event.features]
            handle.write("\t".join([event.event_id, *values]) + "\n")


def _normalize_reason(reason: str) -> str:
    reason = re.sub(r"\d+ clicks in the same second", "same-second click burst", reason)
    reason = re.sub(r"query/domain repeated \d+ times", "repeated query/domain pair", reason)
    reason = re.sub(r"query repeated \d+ times", "repeated query", reason)
    reason = re.sub(
        r"confirmed query repetition \(query/domain \d+, query \d+\)",
        "confirmed query repetition",
        reason,
    )
    reason = re.sub(r"exact time-to-click reused \d+ times", "reused exact time-to-click", reason)
    reason = re.sub(r"high-volume clicked domain \(\d+\)", "high-volume clicked domain", reason)
    reason = re.sub(r"heavy region/browser/os cluster \(\d+\)", "heavy region/browser/os cluster", reason)
    reason = re.sub(
        r"dense burst repetition cluster \(device \d+, same-second \d+, (query/domain|query) \d+\)",
        "dense burst repetition cluster",
        reason,
    )
    reason = re.sub(
        r"regular inter-arrival timing \(\d+ clicks, mean [\d.]+s, cv [\d.]+\)",
        "regular inter-arrival timing",
        reason,
    )
    return reason
