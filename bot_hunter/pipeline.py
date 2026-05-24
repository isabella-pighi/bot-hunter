from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .data import build_features, iter_event_dicts, parse_clicks
from .heuristics import apply_heuristics
from .ml import score_with_kmeans
from .report import write_reports


def run_pipeline(input_path: str | Path, output_dir: str | Path = ".") -> dict[str, object]:
    root = Path(output_dir)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    events = parse_clicks(input_path)
    feature_names, counters = build_features(events)
    apply_heuristics(events, counters)
    score_with_kmeans(events)

    combined = []
    for event in events:
        event.combined_score = (0.58 * event.heuristic_score) + (0.42 * event.ml_score)
        combined.append(event.combined_score)

    cutoff = _quantile(combined, 0.975)
    for event in events:
        event.is_bot = 1 if event.combined_score >= cutoff or event.heuristic_score >= 0.62 else 0

    bot_events = [event for event in events if event.is_bot]
    both_count = sum(1 for event in bot_events if event.heuristic_score >= 0.45 and event.ml_score >= 0.90)
    estimated_precision = min(0.95, max(0.55, 0.58 + 0.35 * (both_count / max(len(bot_events), 1))))

    reason_counter: Counter[str] = Counter()
    for event in bot_events:
        for reason in event.reasons:
            reason_counter[_normalize_reason(reason)] += 1

    top_domains = counters["domain"].most_common(12)
    top_queries = counters["query"].most_common(12)
    top_regions = Counter(event.region for event in bot_events).most_common(8)
    summary = {
        "input_path": str(Path(input_path).expanduser()),
        "total_events": len(events),
        "bot_events": len(bot_events),
        "bot_rate": len(bot_events) / max(len(events), 1),
        "threshold": cutoff,
        "heuristic_flag_rate": sum(1 for event in events if event.heuristic_score >= 0.62) / max(len(events), 1),
        "ml_tail_rate": sum(1 for event in events if event.ml_score >= 0.985) / max(len(events), 1),
        "estimated_precision": estimated_precision,
        "feature_names": feature_names,
        "top_reasons": reason_counter.most_common(10),
        "top_domains": top_domains,
        "top_queries": top_queries,
        "bot_regions": top_regions,
    }

    _write_submission(root / "submission.tsv", events)
    _write_json(artifacts / "summary.json", summary)
    sample = sorted(events, key=lambda event: event.combined_score, reverse=True)[:250]
    _write_json(artifacts / "sample_events.json", list(iter_event_dicts(sample)))
    write_reports(summary, root / "docs")
    return summary


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _write_submission(path: Path, events) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("event_id\tis_bot\n")
        for event in events:
            handle.write(f"{event.event_id}\t{event.is_bot}\n")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _normalize_reason(reason: str) -> str:
    reason = re.sub(r"\d+ clicks in the same second", "same-second click burst", reason)
    reason = re.sub(r"query/domain repeated \d+ times", "repeated query/domain pair", reason)
    reason = re.sub(r"query repeated \d+ times", "repeated query", reason)
    reason = re.sub(r"exact time-to-click reused \d+ times", "reused exact time-to-click", reason)
    reason = re.sub(r"high-volume clicked domain \(\d+\)", "high-volume clicked domain", reason)
    reason = re.sub(r"heavy region/browser/os cluster \(\d+\)", "heavy region/browser/os cluster", reason)
    return reason
