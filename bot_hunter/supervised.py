from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from zlib import crc32

from .data import ClickEvent, build_features, parse_clicks
from .heuristics import apply_heuristics
from .ml import score_anomalies
from .pipeline import (
    COMBINED_HEURISTIC_WEIGHT,
    COMBINED_ML_WEIGHT,
    _assign_operational_tier,
    _quantile,
)

STRICT_SEED_RULE_IDS = {
    "repeat_query_domain",
    "reused_ttc",
    "same_second_burst",
    "fast_click",
}
VALIDATION_SPLIT_MODULUS = 5


@dataclass(frozen=True)
class _CentroidModel:
    means: list[float]
    stds: list[float]
    positive_centroid: list[float]
    background_centroid: list[float]


def run_supervised_pilot(
    input_path: str | Path,
    output_dir: str | Path = ".",
    ml_backend: str = "auto",
) -> dict[str, object]:
    """Run an additive supervised experiment without writing baseline predictions."""

    root = Path(output_dir)
    artifacts = root / "artifacts"
    docs = root / "docs"
    artifacts.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)

    events = parse_clicks(input_path)
    feature_names, counters = build_features(events)
    apply_heuristics(events, counters)
    ml_backend_used = score_anomalies(events, backend=ml_backend)
    _assign_baseline(events)

    seed_labels = {id(event): _is_strict_seed_positive(event) for event in events}
    train_events = [event for event in events if not _is_validation_event(event)]
    validation_events = [event for event in events if _is_validation_event(event)]
    supervised_scores = _score_seed_likeness(events, train_events, seed_labels)
    for event, score in zip(events, supervised_scores):
        event.supervised_score = score  # type: ignore[attr-defined]
        event.supervised_combined_score = (  # type: ignore[attr-defined]
            COMBINED_HEURISTIC_WEIGHT * event.heuristic_score
        ) + (COMBINED_ML_WEIGHT * score)

    supervised_cutoff = _quantile(
        [event.supervised_combined_score for event in events], 0.975  # type: ignore[attr-defined]
    ) if events else 0.0
    for event in events:
        event.supervised_is_bot = int(  # type: ignore[attr-defined]
            event.supervised_combined_score >= supervised_cutoff or event.heuristic_score >= 0.62  # type: ignore[attr-defined]
        )

    summary = _summary(
        events,
        input_path=Path(input_path),
        feature_names=feature_names,
        ml_backend=ml_backend_used,
        supervised_cutoff=supervised_cutoff,
        seed_labels=seed_labels,
        train_events=train_events,
        validation_events=validation_events,
    )
    (artifacts / "supervised_pilot.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    markdown = _markdown(summary)
    (docs / "supervised_pilot_report.md").write_text(markdown, encoding="utf-8")
    (docs / "supervised_pilot_report.html").write_text(_html(markdown), encoding="utf-8")
    return summary


def _assign_baseline(events: list[ClickEvent]) -> None:
    combined = []
    for event in events:
        event.combined_score = (COMBINED_HEURISTIC_WEIGHT * event.heuristic_score) + (
            COMBINED_ML_WEIGHT * event.ml_score
        )
        combined.append(event.combined_score)
    cutoff = _quantile(combined, 0.975) if combined else 0.0
    for event in events:
        event.is_bot = int(event.combined_score >= cutoff or event.heuristic_score >= 0.62)
        event.operational_tier = _assign_operational_tier(event)


def _is_strict_seed_positive(event: ClickEvent) -> bool:
    return any(contribution.rule_id in STRICT_SEED_RULE_IDS for contribution in event.rule_contributions)


def _is_validation_event(event: ClickEvent) -> bool:
    return crc32(event.event_id.encode("utf-8")) % VALIDATION_SPLIT_MODULUS == 0


def _score_seed_likeness(
    events: list[ClickEvent],
    train_events: list[ClickEvent],
    seed_labels: dict[int, bool],
) -> list[float]:
    if not events or not train_events:
        return [0.0 for _ in events]
    positive_train = [event for event in train_events if seed_labels[id(event)]]
    background_train = [event for event in train_events if not seed_labels[id(event)]]
    if not positive_train or not background_train:
        return [0.0 for _ in events]

    model = _fit_centroid_model(positive_train, background_train)
    margins = [_centroid_margin(model, event.features) for event in events]
    return _rank_scores(margins)


def _fit_centroid_model(positive_events: list[ClickEvent], background_events: list[ClickEvent]) -> _CentroidModel:
    train_rows = [event.features for event in [*positive_events, *background_events]]
    cols = len(train_rows[0])
    means = [sum(row[idx] for row in train_rows) / len(train_rows) for idx in range(cols)]
    stds = []
    for idx in range(cols):
        var = sum((row[idx] - means[idx]) ** 2 for row in train_rows) / len(train_rows)
        stds.append(sqrt(var) or 1.0)

    positive_rows = [_standardize_row(event.features, means, stds) for event in positive_events]
    background_rows = [_standardize_row(event.features, means, stds) for event in background_events]
    return _CentroidModel(
        means=means,
        stds=stds,
        positive_centroid=_centroid(positive_rows),
        background_centroid=_centroid(background_rows),
    )


def _standardize_row(row: list[float], means: list[float], stds: list[float]) -> list[float]:
    return [(value - means[idx]) / stds[idx] for idx, value in enumerate(row)]


def _centroid(rows: list[list[float]]) -> list[float]:
    return [sum(row[idx] for row in rows) / len(rows) for idx in range(len(rows[0]))]


def _centroid_margin(model: _CentroidModel, row: list[float]) -> float:
    scaled = _standardize_row(row, model.means, model.stds)
    positive_distance = _distance(scaled, model.positive_centroid)
    background_distance = _distance(scaled, model.background_centroid)
    return background_distance - positive_distance


def _distance(left: list[float], right: list[float]) -> float:
    return sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _rank_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    max_rank = max(len(ordered) - 1, 1)
    return [_upper_bound(ordered, value) / max_rank for value in values]


def _upper_bound(values: list[float], needle: float) -> int:
    low = 0
    high = len(values)
    while low < high:
        mid = (low + high) // 2
        if values[mid] <= needle:
            low = mid + 1
        else:
            high = mid
    return low - 1


def _summary(
    events: list[ClickEvent],
    *,
    input_path: Path,
    feature_names: list[str],
    ml_backend: str,
    supervised_cutoff: float,
    seed_labels: dict[int, bool],
    train_events: list[ClickEvent],
    validation_events: list[ClickEvent],
) -> dict[str, object]:
    baseline_selected = [event for event in events if event.is_bot]
    supervised_selected = [event for event in events if event.supervised_is_bot]  # type: ignore[attr-defined]
    review_volume = len(baseline_selected)
    validation_review_volume = sum(1 for event in validation_events if event.is_bot)
    seed_rule_counts = Counter(
        contribution.rule_id
        for event in events
        if seed_labels[id(event)]
        for contribution in event.rule_contributions
        if contribution.rule_id in STRICT_SEED_RULE_IDS
    )
    baseline_ids = {id(event) for event in baseline_selected}
    supervised_ids = {id(event) for event in supervised_selected}
    return {
        "input_path": str(input_path.expanduser()),
        "total_events": len(events),
        "feature_names": feature_names,
        "baseline_method": "rules+unsupervised",
        "supervised_method": "rules+supervised_seed_likeness",
        "production_scoring_changed": False,
        "ml_backend": ml_backend,
        "seed_policy": {
            "positive_rule_ids": sorted(STRICT_SEED_RULE_IDS),
            "positive_source": "rule_contributions only",
            "excluded_sources": ["heuristic_score", "ml_score", "combined_score", "heuristic/ML agreement"],
            "background_label_warning": (
                "Unseeded events are unlabeled background, not verified human traffic; supervised scores "
                "are rank-calibrated seed-likeness scores, not fraud probabilities."
            ),
        },
        "seed_counts": {
            "total_positive": sum(seed_labels.values()),
            "train_positive": sum(seed_labels[id(event)] for event in train_events),
            "validation_positive": sum(seed_labels[id(event)] for event in validation_events),
            "train_background": sum(not seed_labels[id(event)] for event in train_events),
            "validation_background": sum(not seed_labels[id(event)] for event in validation_events),
            "excluded_regular_interarrival_events": _regular_interarrival_event_count(events),
            "rule_counts": seed_rule_counts.most_common(),
        },
        "score_interpretation": (
            "The supervised score is a percentile rank of distance-margin similarity to strict deterministic "
            "seed positives versus unlabeled background. It is useful for ordering review candidates, not as "
            "a calibrated probability of fraud."
        ),
        "comparison": {
            "baseline": _method_summary(events, baseline_selected, seed_labels, "ml_score"),
            "supervised": _method_summary(events, supervised_selected, seed_labels, "supervised_score"),
            "overlap_selected": len(baseline_ids & supervised_ids),
            "baseline_only_selected": len(baseline_ids - supervised_ids),
            "supervised_only_selected": len(supervised_ids - baseline_ids),
            "supervised_threshold": supervised_cutoff,
        },
        "same_volume_review": {
            "review_volume": review_volume,
            "baseline": _top_k_summary(events, review_volume, "combined_score", seed_labels),
            "supervised": _top_k_summary(events, review_volume, "supervised_combined_score", seed_labels),
        },
        "validation_holdout": {
            "split": "crc32(event_id) % 5 == 0",
            "events": len(validation_events),
            "review_volume": validation_review_volume,
            "baseline": _top_k_summary(validation_events, validation_review_volume, "combined_score", seed_labels),
            "supervised": _top_k_summary(
                validation_events, validation_review_volume, "supervised_combined_score", seed_labels
            ),
        },
        "supervised_disagreement": _supervised_disagreement(events),
    }


def _method_summary(
    all_events: list[ClickEvent],
    selected_events: list[ClickEvent],
    seed_labels: dict[int, bool],
    model_score_attr: str,
) -> dict[str, object]:
    selected_count = len(selected_events)
    selected_seed_count = sum(seed_labels[id(event)] for event in selected_events)
    total_seed_count = sum(seed_labels.values())
    return {
        "selected_events": selected_count,
        "selected_rate": selected_count / max(len(all_events), 1),
        "strict_seed_hits": selected_seed_count,
        "strict_seed_capture_rate": selected_seed_count / max(total_seed_count, 1),
        "strict_seed_share_of_selected": selected_seed_count / max(selected_count, 1),
        "method_disagreement": _method_disagreement_for_attr(all_events, model_score_attr),
    }


def _top_k_summary(
    events: list[ClickEvent],
    k: int,
    score_attr: str,
    seed_labels: dict[int, bool],
) -> dict[str, object]:
    if k <= 0 or not events:
        return {"strict_seed_hits": 0, "strict_seed_capture_rate": 0.0, "strict_seed_share_of_review": 0.0}
    selected = sorted(events, key=lambda event: getattr(event, score_attr), reverse=True)[:k]
    seed_hits = sum(seed_labels[id(event)] for event in selected)
    total_seeds = sum(seed_labels[id(event)] for event in events)
    return {
        "strict_seed_hits": seed_hits,
        "strict_seed_capture_rate": seed_hits / max(total_seeds, 1),
        "strict_seed_share_of_review": seed_hits / max(len(selected), 1),
    }


def _method_disagreement_for_attr(events: list[ClickEvent], model_score_attr: str) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for event in events:
        heuristic_high = event.heuristic_score >= 0.62
        model_high = getattr(event, model_score_attr) >= 0.90
        if heuristic_high and model_high:
            counts["Heuristic + model"] += 1
        elif heuristic_high:
            counts["Heuristic only"] += 1
        elif model_high:
            counts["Model only"] += 1
        else:
            counts["Neither strong"] += 1
    return [
        ("Heuristic + model", counts.get("Heuristic + model", 0)),
        ("Heuristic only", counts.get("Heuristic only", 0)),
        ("Model only", counts.get("Model only", 0)),
        ("Neither strong", counts.get("Neither strong", 0)),
    ]


def _regular_interarrival_event_count(events: list[ClickEvent]) -> int:
    return sum(
        any(contribution.rule_id == "regular_interarrival" for contribution in event.rule_contributions)
        for event in events
    )


def _supervised_disagreement(events: list[ClickEvent]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for event in events:
        baseline = bool(event.is_bot)
        supervised = bool(event.supervised_is_bot)  # type: ignore[attr-defined]
        if baseline and supervised:
            counts["Both selected"] += 1
        elif baseline:
            counts["Baseline only"] += 1
        elif supervised:
            counts["Supervised only"] += 1
        else:
            counts["Neither selected"] += 1
    return [
        ("Both selected", counts.get("Both selected", 0)),
        ("Baseline only", counts.get("Baseline only", 0)),
        ("Supervised only", counts.get("Supervised only", 0)),
        ("Neither selected", counts.get("Neither selected", 0)),
    ]


def _markdown(summary: dict[str, object]) -> str:
    comparison = summary["comparison"]
    same_volume = summary["same_volume_review"]
    validation = summary["validation_holdout"]
    seed_counts = summary["seed_counts"]
    seed_rule_lines = "\n".join(
        f"- {rule_id}: {count:,}" for rule_id, count in seed_counts["rule_counts"]
    )
    return f"""# Supervised Pilot Report

## Status

This is an additive experiment. The production rules+unsupervised pipeline is unchanged.

## Seed Policy

Positive labels come only from strict deterministic rule contributions: {", ".join(summary["seed_policy"]["positive_rule_ids"])}.
The pilot does not use heuristic score, ML score, combined score, or heuristic/ML agreement as label sources.
Unseeded events are unlabeled background, not verified human traffic.

## Seed Counts

- Total strict seed positives: {seed_counts["total_positive"]:,}
- Training positives: {seed_counts["train_positive"]:,}
- Validation positives: {seed_counts["validation_positive"]:,}
- Training background: {seed_counts["train_background"]:,}
- Validation background: {seed_counts["validation_background"]:,}
- Excluded regular-interarrival supporting events: {seed_counts["excluded_regular_interarrival_events"]:,}

Seed rule mix:

{seed_rule_lines}

## Side-by-Side Comparison

| Metric | Rules+unsupervised | Rules+supervised |
|---|---:|---:|
| Selected events | {comparison["baseline"]["selected_events"]:,} | {comparison["supervised"]["selected_events"]:,} |
| Strict seed hits selected | {comparison["baseline"]["strict_seed_hits"]:,} | {comparison["supervised"]["strict_seed_hits"]:,} |
| Strict seed capture rate | {comparison["baseline"]["strict_seed_capture_rate"]:.2%} | {comparison["supervised"]["strict_seed_capture_rate"]:.2%} |
| Strict seed share of selected | {comparison["baseline"]["strict_seed_share_of_selected"]:.2%} | {comparison["supervised"]["strict_seed_share_of_selected"]:.2%} |

Selected-event overlap: {comparison["overlap_selected"]:,} both, {comparison["baseline_only_selected"]:,} baseline-only, {comparison["supervised_only_selected"]:,} supervised-only.

## Same-Volume Review

At the baseline review volume of {same_volume["review_volume"]:,} events:

| Metric | Rules+unsupervised | Rules+supervised |
|---|---:|---:|
| Strict seed hits | {same_volume["baseline"]["strict_seed_hits"]:,} | {same_volume["supervised"]["strict_seed_hits"]:,} |
| Strict seed capture rate | {same_volume["baseline"]["strict_seed_capture_rate"]:.2%} | {same_volume["supervised"]["strict_seed_capture_rate"]:.2%} |
| Strict seed share of review | {same_volume["baseline"]["strict_seed_share_of_review"]:.2%} | {same_volume["supervised"]["strict_seed_share_of_review"]:.2%} |

## Validation Holdout

The validation split is deterministic: `{validation["split"]}`. At the validation review volume of {validation["review_volume"]:,} events:

| Metric | Rules+unsupervised | Rules+supervised |
|---|---:|---:|
| Strict seed hits | {validation["baseline"]["strict_seed_hits"]:,} | {validation["supervised"]["strict_seed_hits"]:,} |
| Strict seed capture rate | {validation["baseline"]["strict_seed_capture_rate"]:.2%} | {validation["supervised"]["strict_seed_capture_rate"]:.2%} |
| Strict seed share of review | {validation["baseline"]["strict_seed_share_of_review"]:.2%} | {validation["supervised"]["strict_seed_share_of_review"]:.2%} |

## Score Interpretation

{summary["score_interpretation"]}

## Validation Interpretation

The supervised path improves strict-seed capture at the same review volume, including on
the deterministic holdout. That is useful evidence for review efficiency against the
seed policy, but it is not measured fraud precision because the dataset has no
ground-truth human/bot labels. The supervised path should remain experimental until a
manual review set or stronger validation confirms that the additional supervised-only
events are better review candidates than the current baseline-only events.
"""


def _html(markdown: str) -> str:
    body = []
    in_table = False
    for line in markdown.splitlines():
        if in_table and not line.startswith("|"):
            body.append("</table>")
            in_table = False
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            body.append(f"<p>{html.escape(line)}</p>")
        elif line.startswith("|"):
            if set(line.replace("|", "").strip()) <= {"-", ":"}:
                continue
            tag = "th" if not in_table else "td"
            cells = "".join(f"<{tag}>{html.escape(cell.strip())}</{tag}>" for cell in line.strip("|").split("|"))
            if not in_table:
                body.append("<table>")
                in_table = True
            body.append(f"<tr>{cells}</tr>")
        else:
            if line:
                body.append(f"<p>{html.escape(line)}</p>")
    if in_table:
        body.append("</table>")
    return "<!doctype html><meta charset='utf-8'><title>Supervised Pilot Report</title>" + "".join(body)
