from __future__ import annotations

from collections import Counter, defaultdict
from math import ceil, sqrt

from .data import ClickEvent, RuleContribution

REGULAR_INTERARRIVAL_MIN_EVENTS = 8
REGULAR_INTERARRIVAL_MAX_MEAN_SECONDS = 300.0
REGULAR_INTERARRIVAL_MAX_CV = 0.50
REGULAR_INTERARRIVAL_WEIGHT = 0.10
MODERATE_LONG_TTC_MIN_MS = 20_000
MODERATE_LONG_TTC_MAX_MS = 60_000
MODERATE_LONG_TTC_WEIGHT = 0.06
TTC_REUSE_COUNT_FLOOR = 40
TTC_REUSE_COUNT_PERCENTILE = 0.99


def apply_heuristics(events: list[ClickEvent], counters: dict[str, Counter]) -> None:
    total = max(len(events), 1)
    domain_hi = max(200, int(total * 0.015))
    query_hi = max(12, int(total * 0.001))
    query_domain_hi = max(4, int(total * 0.00025))
    device_hi = max(600, int(total * 0.035))
    ttc_hi = _adaptive_ttc_reuse_threshold(counters["ttc"])
    regular_interarrival = _regular_interarrival_contributions(events)

    for event in events:
        score = 0.0
        reasons: list[str] = []
        contributions: list[RuleContribution] = []

        qd_count = counters["query_domain"][(event.query, event.domain)]
        if qd_count >= query_domain_hi:
            score += 0.32
            reason = f"query/domain repeated {qd_count} times"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "repeat_query_domain",
                    "Repeated query/domain pair",
                    reason,
                    0.32,
                    qd_count,
                    query_domain_hi,
                    "query_domain_count >= threshold",
                )
            )

        q_count = counters["query"][event.query]
        if q_count >= query_hi:
            score += 0.18
            reason = f"query repeated {q_count} times"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "repeat_query",
                    "Repeated query",
                    reason,
                    0.18,
                    q_count,
                    query_hi,
                    "query_count >= threshold",
                )
            )

        d_count = counters["domain"][event.domain]
        if d_count >= domain_hi:
            score += 0.10
            reason = f"high-volume clicked domain ({d_count})"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "high_volume_domain",
                    "High-volume clicked domain",
                    reason,
                    0.10,
                    d_count,
                    domain_hi,
                    "domain_count >= threshold",
                )
            )

        device_count = counters["device"][(event.region, event.browser, event.os)]
        if device_count >= device_hi:
            score += 0.08
            reason = f"heavy region/browser/os cluster ({device_count})"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "heavy_device_cluster",
                    "Heavy region/browser/os cluster",
                    reason,
                    0.08,
                    device_count,
                    device_hi,
                    "device_count >= threshold",
                )
            )

        ttc_count = counters["ttc"][event.ttc]
        if event.ttc >= 0 and ttc_count >= ttc_hi:
            score += 0.16
            reason = f"exact time-to-click reused {ttc_count} times"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "reused_ttc",
                    "Reused exact time-to-click",
                    reason,
                    0.16,
                    ttc_count,
                    ttc_hi,
                    (
                        "ttc >= 0 and ttc_count >= adaptive 99th percentile "
                        "threshold with absolute floor 40"
                    ),
                    "adaptive_percentile",
                )
            )

        same_second = counters["second"][event.event_time]
        if same_second >= 4:
            score += 0.12
            reason = f"{same_second} clicks in the same second"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "same_second_burst",
                    "Same-second click burst",
                    reason,
                    0.12,
                    same_second,
                    4,
                    "same_second_count >= threshold",
                )
            )

        if 0 <= event.ttc <= 250:
            score += 0.18
            reason = "implausibly fast click"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "fast_click",
                    "Implausibly fast click",
                    reason,
                    0.18,
                    event.ttc,
                    250,
                    "0 <= ttc <= threshold",
                )
            )
        elif MODERATE_LONG_TTC_MIN_MS <= event.ttc <= MODERATE_LONG_TTC_MAX_MS:
            score += MODERATE_LONG_TTC_WEIGHT
            reason = "moderately long time-to-click"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "moderate_long_ttc",
                    "Moderately long time-to-click",
                    reason,
                    MODERATE_LONG_TTC_WEIGHT,
                    event.ttc,
                    f"{MODERATE_LONG_TTC_MIN_MS}-{MODERATE_LONG_TTC_MAX_MS}",
                    "20000 <= ttc <= 60000",
                )
            )
        elif event.ttc > 120000:
            score += 0.08
            reason = "extreme time-to-click"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "extreme_ttc",
                    "Extreme time-to-click",
                    reason,
                    0.08,
                    event.ttc,
                    120000,
                    "ttc > threshold",
                )
            )

        query_terms = len(event.query.split())
        if query_terms <= 1:
            score += 0.04
            reason = "very short query"
            reasons.append(reason)
            contributions.append(
                _contribution(
                    "short_query",
                    "Very short query",
                    reason,
                    0.04,
                    query_terms,
                    1,
                    "query_terms <= threshold",
                )
            )

        interarrival_contribution = regular_interarrival.get(id(event))
        if interarrival_contribution:
            score += interarrival_contribution.weight
            reasons.append(interarrival_contribution.reason)
            contributions.append(interarrival_contribution)

        event.heuristic_score = min(score, 1.0)
        event.reasons = reasons
        event.rule_contributions = contributions


def _regular_interarrival_contributions(events: list[ClickEvent]) -> dict[int, RuleContribution]:
    groups: dict[tuple[str, str, str, str, str], list[ClickEvent]] = defaultdict(list)
    for event in events:
        groups[(event.region, event.browser, event.os, event.query, event.domain)].append(event)

    contributions: dict[int, RuleContribution] = {}
    for group_events in groups.values():
        if len(group_events) < REGULAR_INTERARRIVAL_MIN_EVENTS:
            continue
        ordered = sorted(group_events, key=lambda event: event.event_time)
        deltas = [
            (current.event_time - previous.event_time).total_seconds()
            for previous, current in zip(ordered, ordered[1:])
        ]
        if not deltas:
            continue
        mean_delta = sum(deltas) / len(deltas)
        if mean_delta <= 0 or mean_delta > REGULAR_INTERARRIVAL_MAX_MEAN_SECONDS:
            continue
        variance = sum((delta - mean_delta) ** 2 for delta in deltas) / len(deltas)
        cv = sqrt(variance) / mean_delta
        if cv > REGULAR_INTERARRIVAL_MAX_CV:
            continue

        reason = (
            f"regular inter-arrival timing ({len(group_events)} clicks, "
            f"mean {mean_delta:.1f}s, cv {cv:.3f})"
        )
        contribution = _contribution(
            "regular_interarrival",
            "Regular inter-arrival timing",
            reason,
            REGULAR_INTERARRIVAL_WEIGHT,
            round(cv, 3),
            REGULAR_INTERARRIVAL_MAX_CV,
            "events >= 8 and mean_delta_seconds <= 300 and cv <= 0.50",
        )
        for event in group_events:
            contributions[id(event)] = contribution
    return contributions


def _adaptive_ttc_reuse_threshold(ttc_counts: Counter) -> int:
    counts = sorted(count for ttc, count in ttc_counts.items() if ttc >= 0 and count > 0)
    if not counts:
        return TTC_REUSE_COUNT_FLOOR
    percentile_idx = max(0, ceil(len(counts) * TTC_REUSE_COUNT_PERCENTILE) - 1)
    return max(TTC_REUSE_COUNT_FLOOR, counts[percentile_idx])


def _contribution(
    rule_id: str,
    label: str,
    reason: str,
    weight: float,
    observed: int | float | str,
    threshold: int | float | str | None,
    condition: str,
    threshold_mode: str = "absolute",
) -> RuleContribution:
    return RuleContribution(
        rule_id=rule_id,
        label=label,
        reason=reason,
        weight=weight,
        observed=observed,
        threshold=threshold,
        threshold_mode=threshold_mode,
        condition=condition,
    )
