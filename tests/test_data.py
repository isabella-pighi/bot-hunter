from pathlib import Path

import pytest

from bot_hunter.data import build_features, parse_clicks


def test_parse_clicks_accepts_header_blank_lines_and_repeated_params(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "event_id\tevent_time\tregion\tbrowser\tos\turl",
                "",
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&q=old&q=new&ttc=10&empty=",
            ]
        ),
        encoding="utf-8",
    )

    events = parse_clicks(raw)

    assert len(events) == 1
    assert events[0].event_id == "evt_1"
    assert events[0].query == "new"
    assert events[0].ttc == 10
    assert events[0].params["empty"] == ""


def test_parse_clicks_reports_line_number_for_bad_field_count(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("evt_1\t2019-12-02 00:00:00\tMars\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Line 1 has 3 fields; expected 6"):
        parse_clicks(raw)


def test_parse_clicks_reports_line_number_for_bad_timestamp(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&q=foo&ttc=10",
                "evt_2\tbad-time\tMars\tChrome\tiOS\t/ad_click?d=a.com&q=foo&ttc=10",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Line 2 has invalid event_time 'bad-time'"):
        parse_clicks(raw)


def test_ttc_infinity_maps_to_missing_value(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&q=foo&ttc=inf\n",
        encoding="utf-8",
    )

    events = parse_clicks(raw)

    assert events[0].ttc == -1


def test_build_features_defaults_non_finite_kp_and_sld(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&q=foo&ttc=1000&kp=nan&sld=inf\n",
        encoding="utf-8",
    )
    events = parse_clicks(raw)

    feature_names, _ = build_features(events)

    assert events[0].features[feature_names.index("kp")] == -9.0
    assert events[0].features[feature_names.index("sld")] == 0.0
