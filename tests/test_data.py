from pathlib import Path

import pytest

from bot_hunter.data import CATEGORY_BUCKET_COUNT, build_features, parse_clicks


def test_parse_clicks_accepts_header_blank_lines_and_repeated_params(
    tmp_path: Path,
) -> None:
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


def test_build_features_drops_non_finite_kp_and_sld_categories(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t"
        "/ad_click?d=a.com&q=foo&ttc=1000&kp=nan&sld=inf\n",
        encoding="utf-8",
    )
    events = parse_clicks(raw)

    feature_names, _ = build_features(events)

    assert "kp" not in feature_names
    assert "sld" not in feature_names
    for field_name in ("kp", "sld"):
        bucket_names = [
            f"{field_name}_cat_bucket_{idx}" for idx in range(CATEGORY_BUCKET_COUNT)
        ]
        bucket_indexes = [feature_names.index(name) for name in bucket_names]
        bucket_values = [events[0].features[idx] for idx in bucket_indexes]
        assert bucket_values == [0.0] * CATEGORY_BUCKET_COUNT
