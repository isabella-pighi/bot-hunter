from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from math import log1p, log2
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlsplit

EXPECTED_FIELD_COUNT = 6
EVENT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
EPOCH = datetime(1970, 1, 1)
EXCLUDED_ML_FEATURE_NAMES: set[str] = set()
ML_FEATURE_WEIGHTS = {
    "log_domain_count": 0.5,
    "log_country_count": 0.5,
    "log_query_domain_count": 0.5,
    "log_query_count": 0.5,
    "log_ttc_seconds": 0.5,
    "is_sub_200ms_click": 0.5,
    "query_entropy": 0.5,
}


@dataclass
class RuleContribution:
    rule_id: str
    label: str
    reason: str
    weight: float
    observed: int | float | str
    threshold: int | float | str | None = None
    threshold_mode: str = "absolute"
    condition: str = ""


@dataclass
class ClickEvent:
    event_id: str
    event_time: datetime
    region: str
    browser: str
    os: str
    url: str
    params: dict[str, str] = field(default_factory=dict)
    features: list[float] = field(default_factory=list)
    ml_features: list[float] = field(default_factory=list)
    ml_feature_weights: list[float] = field(default_factory=list)
    heuristic_score: float = 0.0
    ml_score: float = 0.0
    combined_score: float = 0.0
    is_bot: int = 0
    operational_tier: str = "monitor"
    reasons: list[str] = field(default_factory=list)
    rule_contributions: list[RuleContribution] = field(default_factory=list)

    @property
    def domain(self) -> str:
        return self.params.get("d", "")

    @property
    def query(self) -> str:
        return self.params.get("q", "")

    @property
    def ttc(self) -> int:
        try:
            return int(float(self.params.get("ttc", "-1")))
        except ValueError:
            return -1


def parse_clicks(path: str | Path) -> list[ClickEvent]:
    events: list[ClickEvent] = []
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if line_number == 1 and parts[0].lower() == "event_id":
                continue
            if len(parts) != EXPECTED_FIELD_COUNT:
                raise ValueError(
                    f"Line {line_number} has {len(parts)} fields; expected {EXPECTED_FIELD_COUNT}"
                )
            event_id, event_time, region, browser, os_name, url = parts
            parsed_url = urlsplit(url)
            raw_params = parse_qs(parsed_url.query, keep_blank_values=True)
            params = {key: values[-1] if values else "" for key, values in raw_params.items()}
            events.append(
                ClickEvent(
                    event_id=event_id,
                    event_time=_parse_event_time(event_time, line_number),
                    region=region,
                    browser=browser,
                    os=os_name,
                    url=url,
                    params=params,
                )
            )
    return events


def _parse_event_time(value: str, line_number: int) -> datetime:
    try:
        return datetime.strptime(value, EVENT_TIME_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"Line {line_number} has invalid event_time {value!r}; expected YYYY-MM-DD HH:MM:SS"
        ) from exc


def build_features(events: list[ClickEvent]) -> tuple[list[str], dict[str, Counter]]:
    counters = {
        "domain": Counter(event.domain for event in events),
        "query": Counter(event.query for event in events),
        "query_domain": Counter((event.query, event.domain) for event in events),
        "device": Counter((event.region, event.browser, event.os) for event in events),
        "second": Counter(event.event_time for event in events),
        "ttc": Counter(event.ttc for event in events),
        "country": Counter(event.params.get("ct", "") for event in events),
        "landing": Counter(event.params.get("kl", "") for event in events),
    }
    names = [
        "log_domain_count",
        "log_query_count",
        "log_query_domain_count",
        "log_device_count",
        "log_country_count",
        "log_same_second_count",
        "log_ttc_count",
        "kp",
        "sld",
        "hour",
        "log_ttc_seconds",
        "is_sub_200ms_click",
        "log_pseudo_session_10s_click_count",
        "query_entropy",
    ]
    ml_feature_weights = select_ml_feature_weights(names)
    burst_counts = _pseudo_session_burst_counts(events)
    for event in events:
        try:
            kp = float(event.params.get("kp", "-9"))
        except ValueError:
            kp = -9.0
        try:
            sld = float(event.params.get("sld", "0"))
        except ValueError:
            sld = 0.0
        click_delay_seconds = max(event.ttc, 0) / 1000.0
        event.features = [
            log1p(counters["domain"][event.domain]),
            log1p(counters["query"][event.query]),
            log1p(counters["query_domain"][(event.query, event.domain)]),
            log1p(counters["device"][(event.region, event.browser, event.os)]),
            log1p(counters["country"][event.params.get("ct", "")]),
            log1p(counters["second"][event.event_time]),
            log1p(counters["ttc"][event.ttc]),
            kp,
            sld,
            float(event.event_time.hour),
            log1p(click_delay_seconds),
            1.0 if 0 <= event.ttc < 200 else 0.0,
            log1p(burst_counts[id(event)]),
            _query_entropy(event.query),
        ]
        event.ml_features = _select_ml_features(names, event.features)
        event.ml_feature_weights = ml_feature_weights
    return names, counters


def select_ml_feature_names(feature_names: list[str]) -> list[str]:
    return [name for name in feature_names if name not in EXCLUDED_ML_FEATURE_NAMES]


def select_ml_feature_weights(feature_names: list[str]) -> list[float]:
    return [ML_FEATURE_WEIGHTS.get(name, 1.0) for name in select_ml_feature_names(feature_names)]


def _select_ml_features(feature_names: list[str], values: list[float]) -> list[float]:
    return [value for name, value in zip(feature_names, values) if name not in EXCLUDED_ML_FEATURE_NAMES]


def _pseudo_session_burst_counts(events: list[ClickEvent], window_seconds: int = 10) -> dict[int, int]:
    groups: dict[tuple[str, str, str, str, str], list[ClickEvent]] = defaultdict(list)
    for event in events:
        groups[(event.region, event.browser, event.os, event.query, event.domain)].append(event)

    counts: dict[int, int] = {}
    half_window = window_seconds / 2.0
    for group_events in groups.values():
        ordered = sorted(group_events, key=lambda event: event.event_time)
        timestamps = [(event.event_time - EPOCH).total_seconds() for event in ordered]
        left = 0
        right = 0
        for idx, timestamp in enumerate(timestamps):
            while timestamps[left] < timestamp - half_window:
                left += 1
            while right + 1 < len(timestamps) and timestamps[right + 1] <= timestamp + half_window:
                right += 1
            counts[id(ordered[idx])] = right - left + 1
    return counts


def _query_entropy(query: str) -> float:
    if not query:
        return 0.0
    total = len(query)
    counts = Counter(query)
    return -sum((count / total) * log2(count / total) for count in counts.values())


def iter_event_dicts(events: Iterable[ClickEvent]) -> Iterable[dict[str, object]]:
    for event in events:
        yield {
            "event_id": event.event_id,
            "event_time": event.event_time.isoformat(sep=" "),
            "region": event.region,
            "browser": event.browser,
            "os": event.os,
            "domain": event.domain,
            "query": event.query,
            "ttc": event.ttc,
            "heuristic_score": round(event.heuristic_score, 4),
            "ml_score": round(event.ml_score, 4),
            "combined_score": round(event.combined_score, 4),
            "is_bot": event.is_bot,
            "operational_tier": event.operational_tier,
            "reasons": event.reasons,
            "rule_contributions": [
                {
                    "rule_id": contribution.rule_id,
                    "label": contribution.label,
                    "reason": contribution.reason,
                    "weight": contribution.weight,
                    "observed": contribution.observed,
                    "threshold": contribution.threshold,
                    "threshold_mode": contribution.threshold_mode,
                    "condition": contribution.condition,
                }
                for contribution in event.rule_contributions
            ],
        }
