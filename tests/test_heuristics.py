from collections import Counter
from datetime import datetime

from bot_hunter.data import ClickEvent, build_features
from bot_hunter.heuristics import apply_heuristics


def test_rule_contributions_preserve_reasons_and_score() -> None:
    events = [
        ClickEvent(
            event_id=f"evt_{idx}",
            event_time=datetime(2019, 12, 2, 8, 0, 0),
            region="Mars",
            browser="Chrome",
            os="Android",
            url="/ad_click?d=a.com&ttc=10&q=foo",
            params={"d": "a.com", "ttc": "10", "q": "foo"},
        )
        for idx in range(4)
    ]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    event = events[0]
    assert event.reasons == [
        "query/domain repeated 4 times",
        "4 clicks in the same second",
        "implausibly fast click",
        "very short query",
    ]
    assert event.heuristic_score == 0.66
    assert [contribution.rule_id for contribution in event.rule_contributions] == [
        "repeat_query_domain",
        "same_second_burst",
        "fast_click",
        "short_query",
    ]
    assert sum(contribution.weight for contribution in event.rule_contributions) == event.heuristic_score
    assert event.rule_contributions[0].reason == "query/domain repeated 4 times"
    assert event.rule_contributions[0].label == "Repeated query/domain pair"
    assert event.rule_contributions[0].weight == 0.32
    assert event.rule_contributions[0].observed == 4
    assert event.rule_contributions[0].threshold == 4
    assert event.rule_contributions[0].condition == "query_domain_count >= threshold"
    assert event.rule_contributions[2].observed == 10
    assert event.rule_contributions[2].threshold == 250


def test_high_volume_rule_contribution_fields() -> None:
    event = ClickEvent(
        event_id="evt",
        event_time=datetime(2019, 12, 2, 8, 0, 0),
        region="Mars",
        browser="Chrome",
        os="Android",
        url="/ad_click?d=a.com&ttc=3000&q=human%20search",
        params={"d": "a.com", "ttc": "3000", "q": "human search"},
    )
    counters = {
        "query_domain": Counter({("human search", "a.com"): 1}),
        "query": Counter({"human search": 1}),
        "domain": Counter({"a.com": 200}),
        "device": Counter({("Mars", "Chrome", "Android"): 1}),
        "ttc": Counter({3000: 1}),
        "second": Counter({event.event_time: 1}),
    }

    apply_heuristics([event], counters)

    assert event.reasons == ["high-volume clicked domain (200)"]
    assert event.heuristic_score == 0.10
    assert len(event.rule_contributions) == 1
    contribution = event.rule_contributions[0]
    assert contribution.rule_id == "high_volume_domain"
    assert contribution.label == "High-volume clicked domain"
    assert contribution.reason == "high-volume clicked domain (200)"
    assert contribution.weight == 0.10
    assert contribution.observed == 200
    assert contribution.threshold == 200
    assert contribution.condition == "domain_count >= threshold"
