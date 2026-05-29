from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .data import (
    ClickEvent,
    build_features,
    iter_event_dicts,
    parse_clicks,
    select_ml_feature_names,
    select_ml_feature_weights,
)
from .heuristics import STRONG, SUPPORTING, SUPPORTING_RULE_CAP, apply_heuristics
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
ML_AGREEMENT_THRESHOLD = 0.975


def run_pipeline(
    input_path: str | Path, output_dir: str | Path = "."
) -> dict[str, object]:
    root = Path(output_dir)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    events = parse_clicks(input_path)
    feature_names, counters = build_features(events)
    ml_feature_names = select_ml_feature_names(feature_names)
    ml_feature_weights = select_ml_feature_weights(feature_names)
    heuristic_thresholds = apply_heuristics(events, counters)
    ml_backend_used = score_anomalies(events)

    combined = []
    for event in events:
        event.combined_score = (COMBINED_HEURISTIC_WEIGHT * event.heuristic_score) + (
            COMBINED_ML_WEIGHT * event.ml_score
        )
        combined.append(event.combined_score)

    cutoff = _quantile(combined, 0.975) if combined else 0.0
    for event in events:
        event.is_bot = (
            1 if event.combined_score > cutoff or event.heuristic_score >= 0.62 else 0
        )
        event.operational_tier = _assign_operational_tier(event)

    bot_events = [event for event in events if event.is_bot]
    both_count = sum(
        1
        for event in bot_events
        if event.heuristic_score >= 0.45 and event.ml_score >= ML_AGREEMENT_THRESHOLD
    )
    estimated_precision = min(
        0.95, max(0.55, 0.58 + 0.35 * (both_count / max(len(bot_events), 1)))
    )

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
        "heuristic_flag_rate": sum(
            1 for event in events if event.heuristic_score >= 0.62
        )
        / max(len(events), 1),
        "ml_tail_rate": sum(
            1 for event in events if event.ml_score >= ML_AGREEMENT_THRESHOLD
        )
        / max(len(events), 1),
        "estimated_precision": estimated_precision,
        "ml_backend": ml_backend_used,
        "feature_artifact": "artifacts/features.tsv",
        "feature_names": feature_names,
        "ml_feature_names": ml_feature_names,
        "ml_feature_weights": dict(zip(ml_feature_names, ml_feature_weights)),
        "operational_tiers": {
            "suppress": (
                "High-confidence bot traffic suitable for automatic suppression "
                "after policy approval."
            ),
            "quarantine": "Bot traffic that should be held for review before suppression.",
            "monitor": (
                "Traffic not selected for bot action; keep for trend monitoring "
                "and future labels."
            ),
        },
        "method_disagreement": _method_disagreement(events),
        "anomaly_classes": _anomaly_classes(events),
        "tier_thresholds": {
            "suppress_combined_score": SUPPRESS_COMBINED_THRESHOLD,
            "suppress_heuristic_score": SUPPRESS_HEURISTIC_THRESHOLD,
            "suppress_agreement_heuristic_score": SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD,
            "ml_agreement_score": ML_AGREEMENT_THRESHOLD,
            "quarantine": "is_bot == 1 and suppress conditions are not met",
            "monitor": "is_bot == 0",
        },
        "heuristic_thresholds": heuristic_thresholds,
        "rule_strengths": {
            STRONG: "Direct mechanical or replay evidence; applied at full weight.",
            SUPPORTING: (
                "Contextual or weaker evidence; combined applied weight is capped."
            ),
            "supporting_cap": SUPPORTING_RULE_CAP,
        },
        "tier_counts": {
            tier: tier_counts.get(tier, 0)
            for tier in ("suppress", "quarantine", "monitor")
        },
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
            and event.ml_score >= ML_AGREEMENT_THRESHOLD
        )
    ):
        return "suppress"
    return "quarantine"


def _method_disagreement(
    events,
    ml_threshold: float = ML_AGREEMENT_THRESHOLD,
) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for event in events:
        heuristic_high = event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
        ml_high = event.ml_score >= ml_threshold
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


def _anomaly_classes(events: list[ClickEvent]) -> dict[str, object]:
    selected_events = [event for event in events if event.is_bot]
    class_groups: dict[str, list[ClickEvent]] = {
        class_id: [] for class_id in _anomaly_class_definitions()
    }
    for event in selected_events:
        class_groups[_event_anomaly_class(event)].append(event)

    ml_only_population = [
        event for event in events if _event_method_bucket(event) == "ML only"
    ]
    class_rows = []
    for class_id, metadata in _anomaly_class_definitions().items():
        class_events = class_groups[class_id]
        row = {
            "class_id": class_id,
            **metadata,
            "count": len(class_events),
            "tier_counts": _ordered_counter(
                Counter(event.operational_tier for event in class_events),
                ("suppress", "quarantine", "monitor"),
            ),
            "method_counts": _ordered_counter(
                Counter(_event_method_bucket(event) for event in class_events),
                ("Heuristic + ML", "Heuristic only", "ML only", "Combined tail"),
            ),
            "dominant_rules": _dominant_rule_counts(class_events),
            "examples": _anomaly_examples(class_events),
        }
        if class_id == "ml_tail_multivariate":
            row["dominant_rules"] = []
            row["examples"] = _anomaly_examples(class_events, include_rules=False)
            row["population_count"] = len(ml_only_population)
            row["population_scope"] = (
                "All events where ml_score >= 0.975 and heuristic_score < 0.62."
            )
            row["rule_evidence_note"] = (
                "This class is grouped by anomaly-model agreement, not by "
                "rule explanations. Low-weight rules may be present, but they "
                "do not cross the heuristic override threshold."
            )
        class_rows.append(row)

    return {
        "scope": (
            "Operational anomaly classes derived from the current unlabelled "
            "run; these are not proven fraud labels."
        ),
        "selected_event_count": len(selected_events),
        "classified_selected_event_count": sum(
            len(group) for group in class_groups.values()
        ),
        "ml_only_population_count": len(ml_only_population),
        "classes": class_rows,
        "filtering_options": _anomaly_filtering_options(),
    }


def _anomaly_class_definitions() -> dict[str, dict[str, str]]:
    return {
        "repetition_with_supporting_context": {
            "label": "Repetition with supporting context",
            "description": (
                "Repeated query or query/domain behaviour with contextual "
                "evidence such as high-volume domains, device clusters, "
                "country-like concentration, or very short queries."
            ),
            "filter": (
                "is_bot == 1, heuristic_score >= 0.62 or combined_score above "
                "the run cutoff, repeated query evidence present, no stronger "
                "burst or timing class matched first."
            ),
            "review_action": (
                "Review as replay-like traffic. Suppress only when the event "
                "is already in the suppress tier; otherwise quarantine or sample."
            ),
        },
        "compound_burst_replay": {
            "label": "Compound burst/replay",
            "description": (
                "Repeated query evidence paired with same-second bursts or the "
                "dense burst repetition rule."
            ),
            "filter": (
                "is_bot == 1 with repeated query evidence and same_second_burst "
                "or dense_burst_repetition_cluster."
            ),
            "review_action": (
                "Treat suppress-tier events as strong operational candidates; "
                "quarantine the rest for timing-pattern review."
            ),
        },
        "ml_tail_multivariate": {
            "label": "ML-tail multivariate anomaly",
            "description": (
                "Events in the anomaly-model tail without enough heuristic "
                "evidence to cross the rule override threshold."
            ),
            "filter": (
                "ml_score >= 0.975 and heuristic_score < 0.62. Some events are "
                "selected when combined_score exceeds the run cutoff."
            ),
            "review_action": (
                "Quarantine or sample. Do not suppress automatically without "
                "feature-deviation review or labels."
            ),
        },
        "repetition_with_timing": {
            "label": "Repetition with timing anomaly",
            "description": (
                "Repeated query evidence paired with timing evidence such as "
                "moderately long, extreme, fast, exact-reuse, or regular "
                "inter-arrival timing."
            ),
            "filter": (
                "is_bot == 1 with repeated query evidence and timing-family "
                "rules, no compound burst/replay class matched first."
            ),
            "review_action": (
                "Prioritise when suppress-tier or when timing evidence is "
                "strong; otherwise quarantine for sampling."
            ),
        },
        "repetition_dominated": {
            "label": "Repetition dominated",
            "description": (
                "Events selected mainly by repeated query/domain and confirmed "
                "query repetition without additional burst, timing, or broad "
                "supporting context."
            ),
            "filter": (
                "is_bot == 1 with repeated query evidence and no stronger "
                "context, burst, or timing class matched first."
            ),
            "review_action": (
                "Use as an explainable replay candidate. Quarantine lower-score "
                "cases when ML agreement is absent."
            ),
        },
        "supporting_context_combined_tail": {
            "label": "Supporting context plus combined tail",
            "description": (
                "Events with supporting rule context and enough anomaly-model "
                "score to pass the combined cutoff, but without the ML-only "
                "agreement threshold."
            ),
            "filter": (
                "is_bot == 1, heuristic_score < 0.62, ml_score < 0.975, and "
                "supporting rule context present."
            ),
            "review_action": (
                "Monitor or quarantine. These are useful for trend review, not "
                "standalone suppression."
            ),
        },
        "other_combined_tail": {
            "label": "Other combined-tail anomaly",
            "description": (
                "Selected events that do not fit the main operational classes."
            ),
            "filter": (
                "is_bot == 1 and no primary repetition, ML-only, or supporting "
                "context class matched."
            ),
            "review_action": "Sample manually before taking action.",
        },
    }


def _event_anomaly_class(event: ClickEvent) -> str:
    if _event_method_bucket(event) == "ML only":
        return "ml_tail_multivariate"

    rule_ids = {contribution.rule_id for contribution in event.rule_contributions}
    has_repetition = bool(
        rule_ids & {"repeat_query_domain", "repeat_query", "confirmed_query_repetition"}
    )
    has_burst = bool(rule_ids & {"dense_burst_repetition_cluster", "same_second_burst"})
    has_timing = bool(
        rule_ids
        & {
            "fast_click",
            "reused_ttc",
            "regular_interarrival",
            "moderate_long_ttc",
            "extreme_ttc",
        }
    )
    has_supporting_context = bool(
        rule_ids
        & {
            "high_volume_domain",
            "heavy_device_cluster",
            "concentrated_ct_context",
            "short_query",
        }
    )

    if has_repetition and has_burst:
        return "compound_burst_replay"
    if has_repetition and has_timing:
        return "repetition_with_timing"
    if has_repetition and has_supporting_context:
        return "repetition_with_supporting_context"
    if has_repetition:
        return "repetition_dominated"
    if has_supporting_context:
        return "supporting_context_combined_tail"
    return "other_combined_tail"


def _event_method_bucket(event: ClickEvent) -> str:
    heuristic_high = event.heuristic_score >= SUPPRESS_AGREEMENT_HEURISTIC_THRESHOLD
    ml_high = event.ml_score >= ML_AGREEMENT_THRESHOLD
    if heuristic_high and ml_high:
        return "Heuristic + ML"
    if heuristic_high:
        return "Heuristic only"
    if ml_high:
        return "ML only"
    return "Combined tail"


def _ordered_counter(counter: Counter, keys: tuple[str, ...]) -> dict[str, int]:
    return {key: counter.get(key, 0) for key in keys if counter.get(key, 0)}


def _dominant_rule_counts(events: list[ClickEvent]) -> list[dict[str, object]]:
    counter: Counter[str] = Counter(
        contribution.rule_id
        for event in events
        for contribution in event.rule_contributions
    )
    return [
        {"rule_id": rule_id, "count": count}
        for rule_id, count in counter.most_common(8)
    ]


def _anomaly_examples(
    events: list[ClickEvent],
    *,
    include_rules: bool = True,
) -> list[dict[str, object]]:
    examples = sorted(events, key=lambda event: event.combined_score, reverse=True)[:3]
    rows = [
        {
            "event_id": event.event_id,
            "operational_tier": event.operational_tier,
            "domain": event.domain,
            "query": event.query,
            "heuristic_score": round(event.heuristic_score, 4),
            "ml_score": round(event.ml_score, 4),
            "combined_score": round(event.combined_score, 4),
            "method_bucket": _event_method_bucket(event),
        }
        for event in examples
    ]
    if include_rules:
        for row, event in zip(rows, examples):
            row["rule_ids"] = [
                contribution.rule_id for contribution in event.rule_contributions
            ]
    return rows


def _anomaly_filtering_options() -> list[dict[str, str]]:
    return [
        {
            "name": "Conservative suppression review",
            "filter": "operational_tier == 'suppress'",
            "use": (
                "Start here for the strongest operational candidates. Still "
                "requires policy approval because labels are unavailable."
            ),
        },
        {
            "name": "Quarantine for manual review",
            "filter": "operational_tier == 'quarantine'",
            "use": (
                "Hold, sample, or delay action on suspicious traffic that is "
                "not strong enough for direct suppression."
            ),
        },
        {
            "name": "Explainable replay review",
            "filter": (
                "anomaly_class in repetition_with_supporting_context, "
                "compound_burst_replay, repetition_with_timing, "
                "repetition_dominated"
            ),
            "use": (
                "Focus reviewer time on repeated query/domain behaviour with "
                "clear rule evidence."
            ),
        },
        {
            "name": "ML-tail sampling",
            "filter": "ml_score >= 0.975 and heuristic_score < 0.62",
            "use": (
                "Sample for future feature-deviation work; do not treat as "
                "proven fraud without labels."
            ),
        },
    ]


def _write_submission(path: Path, events) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("event_id\tis_bot\toperational_tier\n")
        for event in events:
            handle.write(
                f"{event.event_id}\t{event.is_bot}\t{event.operational_tier}\n"
            )


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
    reason = re.sub(
        r"query/domain repeated \d+ times", "repeated query/domain pair", reason
    )
    reason = re.sub(r"query repeated \d+ times", "repeated query", reason)
    reason = re.sub(
        r"confirmed query repetition \(query/domain \d+, query \d+\)",
        "confirmed query repetition",
        reason,
    )
    reason = re.sub(
        r"exact time-to-click reused \d+ times", "reused exact time-to-click", reason
    )
    reason = re.sub(
        r"high-volume clicked domain \(\d+\)", "high-volume clicked domain", reason
    )
    reason = re.sub(
        r"heavy region/browser/os cluster \(\d+\)",
        "heavy region/browser/OS cluster",
        reason,
    )
    reason = re.sub(
        r"dense burst repetition cluster \(device \d+, same-second \d+, (query/domain|query) \d+\)",
        "dense burst repetition cluster",
        reason,
    )
    reason = re.sub(
        r"concentrated ct context \([^)]+\)",
        "concentrated ct context",
        reason,
    )
    reason = re.sub(
        r"regular inter-arrival timing \(\d+ clicks, mean [\d.]+s, cv [\d.]+\)",
        "regular inter-arrival timing",
        reason,
    )
    return reason
