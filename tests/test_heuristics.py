from collections import Counter
from datetime import datetime, timedelta

from bot_hunter.data import ClickEvent, build_features
from bot_hunter.heuristics import apply_heuristics


def _event(
    idx: int,
    event_time: datetime,
    *,
    region: str = "Mars",
    browser: str = "Chrome",
    os_name: str = "Android",
    query: str = "human search",
    domain: str = "example.com",
) -> ClickEvent:
    return ClickEvent(
        event_id=f"evt_{idx}",
        event_time=event_time,
        region=region,
        browser=browser,
        os=os_name,
        url=f"/ad_click?d={domain}&ttc={1000 + idx}&q={query.replace(' ', '%20')}",
        params={"d": domain, "ttc": str(1000 + idx), "q": query},
    )


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


def test_regular_interarrival_rule_triggers_for_regular_pseudo_session() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [_event(idx, start.replace(minute=idx * 2)) for idx in range(8)]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    contribution = events[0].rule_contributions[-1]
    assert contribution.rule_id == "regular_interarrival"
    assert contribution.label == "Regular inter-arrival timing"
    assert contribution.reason == "regular inter-arrival timing (8 clicks, mean 120.0s, cv 0.000)"
    assert contribution.weight == 0.10
    assert contribution.observed == 0.0
    assert contribution.threshold == 0.50
    assert contribution.condition == "events >= 8 and mean_delta_seconds <= 300 and cv <= 0.50"
    assert all("regular inter-arrival timing" in event.reasons[-1] for event in events)


def test_regular_interarrival_rule_ignores_irregular_timing() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    offsets = [0, 30, 360, 390, 900, 930, 1500, 1530]
    events = [_event(idx, start.replace(second=0) + timedelta(seconds=offset)) for idx, offset in enumerate(offsets)]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    assert "regular_interarrival" not in {
        contribution.rule_id for event in events for contribution in event.rule_contributions
    }


def test_regular_interarrival_rule_requires_at_least_eight_events() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [_event(idx, start.replace(minute=idx * 2)) for idx in range(7)]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    assert "regular_interarrival" not in {
        contribution.rule_id for event in events for contribution in event.rule_contributions
    }


def test_regular_interarrival_rule_does_not_cross_split_groups() -> None:
    start = datetime(2019, 12, 2, 8, 0, 0)
    events = [
        *[_event(idx, start.replace(minute=idx * 2), query="human search") for idx in range(4)],
        *[_event(idx + 4, start.replace(minute=idx * 2), query="other search") for idx in range(4)],
    ]
    _, counters = build_features(events)

    apply_heuristics(events, counters)

    assert "regular_interarrival" not in {
        contribution.rule_id for event in events for contribution in event.rule_contributions
    }
