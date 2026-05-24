from __future__ import annotations

from collections import Counter

from .data import ClickEvent


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

        qd_count = counters["query_domain"][(event.query, event.domain)]
        if qd_count >= query_domain_hi:
            score += 0.32
            reasons.append(f"query/domain repeated {qd_count} times")

        q_count = counters["query"][event.query]
        if q_count >= query_hi:
            score += 0.18
            reasons.append(f"query repeated {q_count} times")

        d_count = counters["domain"][event.domain]
        if d_count >= domain_hi:
            score += 0.10
            reasons.append(f"high-volume clicked domain ({d_count})")

        device_count = counters["device"][(event.region, event.browser, event.os)]
        if device_count >= device_hi:
            score += 0.08
            reasons.append(f"heavy region/browser/os cluster ({device_count})")

        ttc_count = counters["ttc"][event.ttc]
        if event.ttc >= 0 and ttc_count >= ttc_hi:
            score += 0.16
            reasons.append(f"exact time-to-click reused {ttc_count} times")

        same_second = counters["second"][event.event_time]
        if same_second >= 4:
            score += 0.12
            reasons.append(f"{same_second} clicks in the same second")

        if 0 <= event.ttc <= 250:
            score += 0.18
            reasons.append("implausibly fast click")
        elif event.ttc > 120000:
            score += 0.08
            reasons.append("extreme time-to-click")

        if len(event.query.split()) <= 1:
            score += 0.04
            reasons.append("very short query")

        event.heuristic_score = min(score, 1.0)
        event.reasons = reasons

