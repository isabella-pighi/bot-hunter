from __future__ import annotations

import html
from pathlib import Path
from textwrap import wrap


def write_reports(summary: dict[str, object], output_dir: str | Path = "docs") -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    markdown = _markdown(summary)
    (output / "analysis_report.md").write_text(markdown, encoding="utf-8")
    html_text = _html(markdown)
    (output / "analysis_report.html").write_text(html_text, encoding="utf-8")
    _write_simple_pdf(output / "analysis_report.pdf", markdown)


def _markdown(summary: dict[str, object]) -> str:
    bot_rate = float(summary["bot_rate"])
    precision = float(summary["estimated_precision"])
    ml_backend = str(summary.get("ml_backend", "eif"))
    model_name, model_detail, backend_label = _model_copy(ml_backend)
    top_reasons = summary.get("top_reasons", [])
    feature_count = len(summary.get("feature_names", []))
    ml_feature_names = summary.get("ml_feature_names", summary.get("feature_names", []))
    ml_feature_count = len(ml_feature_names)
    ml_feature_weights = summary.get("ml_feature_weights", {})
    reason_lines = "\n".join(f"- {reason}: {count:,} events" for reason, count in top_reasons)
    if not reason_lines:
        reason_lines = "- No dominant heuristic reason was found."
    tier_counts = summary.get("tier_counts", {})
    tier_lines = "\n".join(
        f"- {tier}: {int(tier_counts.get(tier, 0)):,} events" for tier in ("suppress", "quarantine", "monitor")
    )
    suppress_count = int(tier_counts.get("suppress", 0))
    quarantine_count = int(tier_counts.get("quarantine", 0))
    monitor_count = int(tier_counts.get("monitor", 0))
    thresholds = summary.get("tier_thresholds", {})
    heuristic_agreement = float(thresholds.get("suppress_agreement_heuristic_score", 0.62))
    ml_support_score = float(thresholds.get("ml_support_score", 0.975))
    ml_extreme_score = float(thresholds.get("suppress_agreement_ml_score", 0.995))
    extreme_rows = summary.get("method_disagreement_extreme", summary.get("method_disagreement", []))
    support_rows = summary.get("method_disagreement_support", [])
    support_lines = _disagreement_lines(support_rows)
    if not support_lines:
        support_lines = "- No ML support bucket data was reported."
    extreme_lines = _disagreement_lines(extreme_rows)
    if not extreme_lines:
        extreme_lines = "- No suppress-grade agreement data was reported."
    support_both_count = _disagreement_count(support_rows, "Heuristic + ML")
    extreme_both_count = _disagreement_count(extreme_rows, "Heuristic + ML")
    support_ml_only_count = _disagreement_count(support_rows, "ML only")
    extreme_ml_only_count = _disagreement_count(extreme_rows, "ML only")
    threshold = float(summary.get("threshold", 0.0))
    heuristic_flag_rate = float(summary.get("heuristic_flag_rate", 0.0))
    ml_tail_rate = float(summary.get("ml_tail_rate", 0.0))

    return f"""# Bot Hunter Analysis Report

## 1. Project context

Bot Hunter is a review-first bot detection pipeline. It keeps the rules layer readable, lets the anomaly model add statistical coverage, and treats all score outputs as unlabeled operational evidence rather than measured ground truth. That matters because the dataset does not include labels, so precision is reported as an operational confidence estimate instead of a calibrated metric.

## 2. Classifiers

The application implements two classifiers. The first is a rules-based classifier that scores repeated query/domain pairs, repeated queries, confirmed query repetition, high-volume domains, dense region/browser/OS clusters, exact time-to-click reuse, same-second bursts, dense burst repetition clusters, implausibly fast clicks, moderately long time-to-click values, extreme time-to-click values, and regular pseudo-session inter-arrival timing. Exact time-to-click reuse is selectively calibrated with a 99th-percentile reuse-count cutoff and an absolute floor so the rule can adapt to timer reuse patterns without letting low-count coincidences fire. Confirmed query repetition is intentionally conjunctive: it requires the query/domain pair to repeat and the query to be widely repeated. Dense burst repetition is also conjunctive: it requires a heavy region/browser/OS cluster, at least five same-second clicks, and a repeated query or query/domain pattern on the same event. The second classifier is {model_name} over {ml_feature_count} ML features selected from {feature_count} engineered behavioral features, including region/browser/OS frequency, global `ct` country frequency, explicit mechanical features for sub-200ms clicks, local burst density, and query entropy. Query length, query word count, and uncertain URL flags are no longer engineered features. High-volume domain frequency and global country frequency remain available but are down-weighted to {float(ml_feature_weights.get("log_domain_count", 1.0)):.2f} and {float(ml_feature_weights.get("log_country_count", 1.0)):.2f}, respectively, in the standardized ML matrix. Repetition and timing features that can dominate standalone EIF tail evidence are also down-weighted to {float(ml_feature_weights.get("log_query_count", 1.0)):.2f}: query/domain repetition, query repetition, log-scaled time-to-click magnitude, sub-200ms click flags, and query entropy. {model_detail}

## 3. Anomalies found

The run analyzed {int(summary["total_events"]):,} events and flagged {int(summary["bot_events"]):,} events as bots ({bot_rate:.2%}). The strongest explainable patterns were:

{reason_lines}

The dashboard exposes these same signals with sample events so a business user can inspect the likely automated behavior without reading model internals.

## 4. Filtering options

Practical filters for similar datasets include dropping or quarantining traffic from repeated query/domain pairs, repeated exact `ttc` values, dense same-second bursts, and events above the combined anomaly threshold. Bot Hunter assigns operational tiers without changing the binary `is_bot` prediction:

{tier_lines}

Use `suppress` for high-confidence bot traffic after policy approval, `quarantine` for bot traffic that should be held for review, and `monitor` for traffic that is not selected for bot action but should remain available for trend analysis and future labels.

## 5. Method disagreement

The combined score uses a 0.58/0.42 heuristic/ML split because the rules layer is more directly explainable and should remain slightly dominant, while ML still has enough weight to move borderline cases and catch multivariate oddities. The thresholds are conservative guardrails, not learned cutoffs. Bot Hunter now reports two EIF diagnostic buckets against the same rules threshold (`heuristic_score >= {heuristic_agreement:.2f}`). The broader support bucket (`ml_score >= {ml_support_score:.3f}`) shows where the anomaly model provides useful review evidence. The suppress-grade extreme bucket (`ml_score >= {ml_extreme_score:.3f}`) keeps the existing operational semantics used for high-confidence heuristic/ML agreement and suppression. Suppression and operational tiers still use the {ml_extreme_score:.3f} extreme threshold, not the broader support threshold.

At the broader support threshold, this run has {support_both_count:,} `Heuristic + ML` events and {support_ml_only_count:,} `ML only` events. At the suppress-grade extreme threshold, it has {extreme_both_count:,} `Heuristic + ML` events and {extreme_ml_only_count:,} `ML only` events. The comparison is diagnostic; it does not expose another production model path.

ML support bucket (`ml_score >= {ml_support_score:.3f}`):

{support_lines}

Suppress-grade extreme bucket (`ml_score >= {ml_extreme_score:.3f}`):

{extreme_lines}

## 6. Threshold rationale

The binary decision uses the stronger of two conservative gates: the event is selected when its combined score is at or above the run-specific 97.5th-percentile cutoff ({threshold:.6f} in this run), or when the rules-only heuristic score reaches 0.62 on its own. The percentile cutoff keeps the submitted bot volume stable for an unlabeled dataset while still letting the anomaly model influence which borderline events enter the review set. The heuristic override prevents high-confidence, explainable rule hits from being missed just because the anomaly ranking moved around after a feature or backend change.

The threshold is not a learned probability boundary. It is an operational cutoff for a review-first workflow where false positives and false negatives are treated as roughly comparable. In this run, the heuristic-only flag rate was {heuristic_flag_rate:.2%}, while the suppress-grade EIF extreme-tail reference rate was {ml_tail_rate:.2%}; those rates are reported separately so reviewers can see how much each method contributes before the combined decision is applied.

## 7. Rationale and generalization

The heuristic model is transparent and easy to convert into policy. Only exact time-to-click reuse uses percentile calibration because it is a global duplicate-count signal whose suspiciousness depends on the dataset's observed timer granularity and reuse distribution; the absolute floor protects against weak duplicate counts in smaller or smoother datasets. Other heuristic cutoffs remain fixed or total-rate based because they represent separate behavioral concepts. The confirmed query repetition rule reuses the repeated query/domain and repeated query thresholds and adds weight only when both fire on the same event. The dense burst repetition rule reuses those existing component thresholds and adds weight only when all three are present together, which targets many clicks from the same device cluster in the same second with repeated query patterns. The time-to-click timing bands are intentionally tiered: clicks from 0 to 250 ms are treated as implausibly fast direct evidence, clicks from 20 to 60 seconds add low-weight support for delayed or mechanical click patterns, and clicks above 120 seconds remain a separate extreme timing signal. The regular inter-arrival rule is intentionally narrow because the dataset has no explicit user or session identifier: it only compares clicks with the same region, browser, OS, query, and clicked domain, requires at least eight events, and adds low-weight supporting evidence rather than a standalone bot decision. Structured rule contributions include `threshold_mode`, with fixed rules reported as `absolute` and adaptive exact-ttc reuse reported as `adaptive_percentile` when present. The {backend_label} catches multivariate oddities that a small rule set may miss. Both should generalize when bot traffic is repetitive or mechanically timed, but they may miss human-like bots and may over-flag legitimate campaigns that naturally produce high repetition. The thresholds should be recalibrated when traffic mix, geography, or ad inventory changes materially.

## 8. Probability assessment

The estimated probability that a flagged event is fraudulent is {precision:.0%}. This is not label-calibrated precision; it is a reasoned estimate based on agreement between independent signals. Events flagged by both the heuristic model and the upper tail of the ML anomaly score are more likely to be fraudulent than events flagged by only one weak signal. The report therefore treats probability as an operational confidence estimate, not a measured ground truth metric.

## 9. Known limitations

- The dataset has no ground-truth bot labels, so Bot Hunter cannot report measured precision, recall, or calibration.
- The rules intentionally favor interpretable repetition and timing signals. Human-like automation, slow distributed bot traffic, or attacks spread across many query/domain combinations may be under-detected.
- Legitimate campaigns can create high repetition, dense device clusters, or synchronized bursts. The suppress tier should therefore be policy-approved and periodically sampled.
- The regular inter-arrival rule uses narrow pseudo-session groups because there is no user or session identifier. It is supporting evidence rather than proof of automation.
- The anomaly score is relative to the current traffic mix. Material changes in geography, inventory, campaign volume, browser mix, or feature extraction should trigger a fresh threshold and review calibration.

## 10. Recommended actions

Assuming false positives and false negatives are roughly equal in cost, the submitted binary prediction uses the combined score threshold rather than only the highest-confidence intersection. For business action, use three tiers: suppress bot events with the strongest combined, heuristic, or heuristic/ML agreement signals; quarantine the remaining bot events for review; and monitor traffic that is not selected for bot action while retaining it for drift checks and future labels.

## 11. Future work

With more time, I would add labeled validation data, campaign-level normalization, browser/user-agent fingerprinting if available, time-series burst detection by inventory beyond the current pseudo-session burst feature, calibrated probabilities, and a feedback loop from manual review decisions.

## 12. Submission and decision summary

The repository includes `submission.tsv` with `event_id`, `is_bot`, and `operational_tier`, preserving the final binary prediction while adding a workflow tier. This run selected {int(summary["bot_events"]):,} of {int(summary["total_events"]):,} events as likely bots ({bot_rate:.2%}). The operational split is {suppress_count:,} suppress, {quarantine_count:,} quarantine, and {monitor_count:,} monitor events.

Use the binary `is_bot` field as the compatibility output for downstream systems. Use `operational_tier` to decide handling: suppress high-confidence bot traffic after policy approval, quarantine lower-confidence bot traffic for review or delayed action, and monitor the remaining traffic for drift checks and future labels. The report and dashboard should be read as review aids, not as proof of fraud for every individual event.
"""


def _model_copy(ml_backend: str) -> tuple[str, str, str]:
    if ml_backend == "eif":
        return (
            "an Extended Isolation Forest anomaly model",
            "Events isolated quickly by random hyperplane splits receive higher anomaly scores. "
            "EIF is the only production anomaly model; alternate ML backends and supervised pilots have been removed.",
            "Extended Isolation Forest model",
        )
    return (
        "the production Extended Isolation Forest anomaly model",
        "Events with stronger statistical anomaly evidence receive higher anomaly scores.",
        "Extended Isolation Forest model",
    )


def _disagreement_lines(rows: object) -> str:
    if not isinstance(rows, list):
        return ""
    return "\n".join(
        f"- {label}: {int(count):,} events"
        for label, count in rows
        if isinstance(label, str)
    )


def _disagreement_count(rows: object, label: str) -> int:
    if not isinstance(rows, list):
        return 0
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) == 2 and row[0] == label:
            return int(row[1])
    return 0


def _html(markdown: str) -> str:
    body = []
    in_list = False
    in_code = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            body.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            body.append(html.escape(line))
            continue
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip():
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        body.append("</ul>")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Bot Hunter Analysis Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.5; margin: 48px auto; max-width: 920px; color: #172026; }}
    h1, h2 {{ line-height: 1.2; }}
    h1 {{ font-size: 34px; }}
    h2 {{ margin-top: 32px; border-top: 1px solid #d8dee4; padding-top: 20px; }}
    pre {{ background: #f6f8fa; padding: 16px; overflow: auto; border-radius: 6px; }}
  </style>
</head>
<body>{''.join(body)}</body>
</html>"""


def _write_simple_pdf(path: Path, text: str) -> None:
    lines: list[str] = []
    for raw in text.replace("#", "").replace("`", "").splitlines():
        if not raw.strip():
            lines.append("")
        else:
            lines.extend(wrap(raw, width=88) or [""])

    pages = [lines[i : i + 42] for i in range(0, len(lines), 42)] or [[]]
    objects: list[bytes] = [b"", b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids: list[int] = []
    for page_lines in pages:
        content = ["BT", "/F1 10 Tf", "50 780 Td", "14 TL"]
        for line in page_lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.append(f"({escaped}) Tj")
            content.append("T*")
        content.append("ET")
        stream = "\n".join(content).encode("latin-1", errors="replace")
        content_id = len(objects)
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_id = len(objects)
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects[1:], start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_at = len(pdf)
    pdf.extend(f"xref\n0 {len(objects)}\n0000000000 65535 f\n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n\n".encode())
    pdf.extend(f"trailer << /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    path.write_bytes(bytes(pdf))
