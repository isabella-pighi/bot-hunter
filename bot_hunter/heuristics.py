from __future__ import annotations

from collections import Counter

from .data import ClickEvent, RuleContribution


def apply_heuristics(events: list[ClickEvent], counters: dict[str, Counter]) -> None:
    total = max(len(events), 1)
    domain_hi = max(200, int(total * 0.015))
    query_hi = max(12, int(total * 0.001))
    query_domain_hi = max(4, int(total * 0.00025))
    device_hi = max(600, int(total * 0.035))
    ttc_hi = max(40, int(total * 0.0012))

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
                    "ttc >= 0 and ttc_count >= threshold",
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

        event.heuristic_score = min(score, 1.0)
        event.reasons = reasons
        event.rule_contributions = contributions


def _contribution(
    rule_id: str,
    label: str,
    reason: str,
    weight: float,
    observed: int | float | str,
    threshold: int | float | str | None,
    condition: str,
) -> RuleContribution:
    return RuleContribution(
        rule_id=rule_id,
        label=label,
        reason=reason,
        weight=weight,
        observed=observed,
        threshold=threshold,
        condition=condition,
    )
