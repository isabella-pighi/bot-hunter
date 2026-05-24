from pathlib import Path

from bot_hunter.pipeline import run_pipeline


def test_pipeline_writes_submission(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text(
        "\n".join(
            [
                "evt_1\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
                "evt_2\t2019-12-02 00:00:00\tMars\tChrome\tiOS\t/ad_click?d=a.com&ttc=10&q=foo%20bar&ct=US&kl=en&kp=-1&sld=1&st=mobile_search_intl",
                "evt_3\t2019-12-02 00:00:01\tVenus\tSafari\tAndroid\t/ad_click?d=b.com&ttc=3000&q=human%20search&ct=GB&kl=uk&kp=-1&sld=0&st=mobile_search_intl",
            ]
        ),
        encoding="utf-8",
    )
    summary = run_pipeline(raw, tmp_path)
    assert summary["total_events"] == 3
    submission = (tmp_path / "submission.tsv").read_text(encoding="utf-8")
    assert submission.startswith("event_id\tis_bot\n")
    assert "evt_1" in submission


def test_pipeline_handles_empty_input(tmp_path: Path) -> None:
    raw = tmp_path / "clicks.tsv"
    raw.write_text("", encoding="utf-8")

    summary = run_pipeline(raw, tmp_path)

    assert summary["total_events"] == 0
    assert summary["bot_events"] == 0
    assert summary["threshold"] == 0.0
    assert (tmp_path / "submission.tsv").read_text(encoding="utf-8") == "event_id\tis_bot\n"
