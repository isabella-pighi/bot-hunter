from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite, log1p, log2
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlsplit

EXPECTED_FIELD_COUNT = 6
EVENT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
EPOCH = datetime(1970, 1, 1)
EXCLUDED_ML_FEATURE_NAMES: set[str] = set()
CATEGORY_BUCKET_COUNT = 4
SOURCE_PARAM_NAMES = ("st", "source", "src", "utm_source", "campaign_source")
ML_FEATURE_WEIGHTS = {
    "log_domain_count": 0.5,
    "log_country_count": 0.5,
    "log_query_domain_count": 0.5,
    "log_query_count": 0.5,
    "log_ttc_seconds": 0.5,
    "is_sub_200ms_click": 0.5,
    "query_entropy": 0.5,
}
CATEGORICAL_ML_FEATURE_WEIGHTS = {
    "region_cat": 0.5,
    "browser_cat": 0.5,
    "os_cat": 0.5,
    "country_cat": 0.5,
    "source_cat": 0.5,
    "kp_cat": 0.5,
    "sld_cat": 0.25,
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
        return _parse_int_param(self.params.get("ttc"), default=-1)


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
            params = {
                key: values[-1] if values else "" for key, values in raw_params.items()
            }
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
        *_categorical_feature_names("region_cat"),
        *_categorical_feature_names("browser_cat"),
        *_categorical_feature_names("os_cat"),
        *_categorical_feature_names("country_cat"),
        *_categorical_feature_names("source_cat"),
        *_categorical_feature_names("kp_cat"),
        *_categorical_feature_names("sld_cat"),
        "hour",
        "log_ttc_seconds",
        "is_sub_200ms_click",
        "log_pseudo_session_10s_click_count",
        "query_entropy",
    ]
    ml_feature_weights = select_ml_feature_weights(names)
    burst_counts = _pseudo_session_burst_counts(events)
    for event in events:
        kp = _category_param(event.params.get("kp"))
        sld = _category_param(event.params.get("sld"))
        click_delay_seconds = max(event.ttc, 0) / 1000.0
        event.features = [
            log1p(counters["domain"][event.domain]),
            log1p(counters["query"][event.query]),
            log1p(counters["query_domain"][(event.query, event.domain)]),
            log1p(counters["device"][(event.region, event.browser, event.os)]),
            log1p(counters["country"][event.params.get("ct", "")]),
            log1p(counters["second"][event.event_time]),
            log1p(counters["ttc"][event.ttc]),
            *_categorical_indicators("region", event.region),
            *_categorical_indicators("browser", event.browser),
            *_categorical_indicators("os", event.os),
            *_categorical_indicators("country", event.params.get("ct", "")),
            *_categorical_indicators("source", _source_category(event.params)),
            *_categorical_indicators("kp", kp),
            *_categorical_indicators("sld", sld),
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
    return [_ml_feature_weight(name) for name in select_ml_feature_names(feature_names)]


def _select_ml_features(feature_names: list[str], values: list[float]) -> list[float]:
    return [
        value
        for name, value in zip(feature_names, values)
        if name not in EXCLUDED_ML_FEATURE_NAMES
    ]


def _ml_feature_weight(name: str) -> float:
    if name in ML_FEATURE_WEIGHTS:
        return ML_FEATURE_WEIGHTS[name]
    for prefix, weight in CATEGORICAL_ML_FEATURE_WEIGHTS.items():
        if name.startswith(f"{prefix}_bucket_"):
            return weight
    return 1.0


def _categorical_feature_names(prefix: str) -> list[str]:
    return [f"{prefix}_bucket_{idx}" for idx in range(CATEGORY_BUCKET_COUNT)]


def _categorical_indicators(namespace: str, value: str) -> list[float]:
    indicators = [0.0] * CATEGORY_BUCKET_COUNT
    normalized = value.strip().lower()
    if not normalized:
        return indicators
    bucket = _stable_bucket(namespace, normalized)
    indicators[bucket] = 1.0
    return indicators


def _stable_bucket(namespace: str, value: str) -> int:
    key = f"{namespace}\0{value}".encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=2).digest()
    return int.from_bytes(digest, byteorder="big") % CATEGORY_BUCKET_COUNT


def _source_category(params: dict[str, str]) -> str:
    for param_name in SOURCE_PARAM_NAMES:
        value = params.get(param_name, "").strip()
        if value:
            return value
    return ""


def _category_param(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.strip()
    if normalized.lower() in {"nan", "inf", "+inf", "-inf", "infinity"}:
        return ""
    return normalized


def _pseudo_session_burst_counts(
    events: list[ClickEvent], window_seconds: int = 10
) -> dict[int, int]:
    groups: dict[tuple[str, str, str, str, str], list[ClickEvent]] = defaultdict(list)
    for event in events:
        groups[
            (event.region, event.browser, event.os, event.query, event.domain)
        ].append(event)

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
            while (
                right + 1 < len(timestamps)
                and timestamps[right + 1] <= timestamp + half_window
            ):
                right += 1
            counts[id(ordered[idx])] = right - left + 1
    return counts


def _query_entropy(query: str) -> float:
    if not query:
        return 0.0
    total = len(query)
    counts = Counter(query)
    return -sum((count / total) * log2(count / total) for count in counts.values())


def _parse_int_param(value: str | None, default: int) -> int:
    try:
        parsed = float(value if value is not None else str(default))
        if not isfinite(parsed):
            return default
        return int(parsed)
    except (OverflowError, ValueError):
        return default


def _parse_float_param(value: str | None, default: float) -> float:
    try:
        parsed = float(value if value is not None else str(default))
    except (OverflowError, ValueError):
        return default
    return parsed if isfinite(parsed) else default


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
