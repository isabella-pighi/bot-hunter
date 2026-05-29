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
    ml_agreement_score = float(thresholds.get("ml_agreement_score", 0.975))
    disagreement_rows = summary.get("method_disagreement", [])
    disagreement_lines = _disagreement_lines(disagreement_rows)
    if not disagreement_lines:
        disagreement_lines = "- No method disagreement data was reported."
    agreement_both_count = _disagreement_count(disagreement_rows, "Heuristic + ML")
    ml_only_count = _disagreement_count(disagreement_rows, "ML only")
    threshold = float(summary.get("threshold", 0.0))
    heuristic_flag_rate = float(summary.get("heuristic_flag_rate", 0.0))
    ml_tail_rate = float(summary.get("ml_tail_rate", 0.0))
    domain_weight = float(ml_feature_weights.get("log_domain_count", 1.0))
    country_weight = float(ml_feature_weights.get("log_country_count", 1.0))

    return f"""# Bot Hunter Analysis Report

## 1. Executive Summary

Bot Hunter analysed {int(summary["total_events"]):,} click events and selected {int(summary["bot_events"]):,} as likely bot traffic. That is {bot_rate:.2%} of the run.

This report should be read as evidence for review, not as proof of fraud for
every individual event. The dataset does not include ground-truth labels, so the
probability figures are operational confidence estimates rather than measured
precision or recall.

The submitted output is `submission.tsv`. It keeps the required binary
`is_bot` decision and adds an operational tier so the same prediction can be
used more carefully in business workflows.

## 2. What The System Does

Bot Hunter combines two complementary classifiers.

- Rules-based classifier: transparent rules that identify repeated,
  mechanically timed, or tightly clustered click patterns.
- Machine-learning classifier: {model_name} over {ml_feature_count} engineered behavioural features.

The final score is a weighted blend:

```text
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

The rules layer is weighted slightly higher because it is easier to explain and
audit. The anomaly model still matters because it can identify unusual
combinations that a small rule set may not capture.

## 3. Main Results

The strongest explainable patterns in this run were:

{reason_lines}

Example interpretation: a single repeated query is not enough to prove bot
traffic. It becomes more concerning when it appears with a repeated clicked
domain, dense same-second activity, reused time-to-click values, or a narrow
region/browser/OS footprint.

The new concentrated `ct` rule is deliberately cautious. It adds low-weight
support only when country-like concentration appears with repeated query
behaviour and either a heavy device cluster or a same-second burst. Country-like
concentration alone is not treated as bot evidence because legitimate campaigns
can be country-specific.

## 4. Classifier Details

The rules layer currently scores:

- repeated query/domain pairs
- repeated queries
- confirmed query repetition
- high-volume clicked domains
- dense region/browser/OS clusters
- exact time-to-click reuse
- same-second bursts
- dense burst repetition clusters
- concentrated `ct` context paired with repetition and clustering
- implausibly fast clicks
- moderately long or extreme time-to-click values
- regular pseudo-session inter-arrival timing

The exact time-to-click reuse rule uses a 99th-percentile reuse-count threshold
with an absolute floor. This lets the rule adapt to the observed timer reuse in
the batch while avoiding weak duplicate counts.

The `ct` rule, confirmed query repetition, and dense burst repetition rules are
conjunctive. In practical terms, they require multiple signals to be present
before adding score. This is safer than treating broad context, such as
country-like concentration, as a standalone bot indicator.

The anomaly classifier uses the engineered feature matrix. The main feature
families are:

- region/browser/OS frequency
- global `ct` country frequency
- sub-200 ms click flags
- local burst density
- query entropy
- query, domain, and query/domain repetition counts
- same-second and exact time-to-click reuse counts
- timing magnitude after log transformation

High-volume domain frequency and global country frequency are down-weighted to {domain_weight:.2f} and {country_weight:.2f}, respectively. {model_detail}

## 5. Thresholds And Decision Logic

An event is selected as a bot when either condition is true:

```text
combined_score > {threshold:.6f}
or heuristic_score >= 0.62
```

The combined-score threshold is the run-specific 97.5th-percentile cutoff. It
keeps the selected volume stable for an unlabelled dataset while letting the ML
model influence borderline cases.

The heuristic override protects high-confidence, explainable rule hits. For
example, a strongly repeated query/domain pattern with mechanical timing should
not be missed only because the anomaly ranking moved after a feature change.

In this run:

- heuristic-only flag rate: {heuristic_flag_rate:.2%}
- ML agreement-tail reference rate: {ml_tail_rate:.2%}
- operational confidence estimate: {precision:.0%}

## 6. Method Agreement And Disagreement

Agreement between the rules layer and the anomaly model is useful review
evidence. It is not statistical validation, because there are no labels.

At the ML agreement threshold, this run has {agreement_both_count:,} `Heuristic + ML` events and {ml_only_count:,} `ML only` events.

Method disagreement (`ml_score >= {ml_agreement_score:.3f}`):

{disagreement_lines}

Example interpretation:

- `Heuristic + ML` events are usually the strongest review candidates.
- `Heuristic only` events may be explainable rule hits that are not unusual in
  the wider feature space.
- `ML only` events may contain multivariate anomalies, but they need careful
  review because unusual legitimate behaviour can also be anomalous.

## 7. Operational Actions

Bot Hunter separates prediction from action by assigning operational tiers:

{tier_lines}

Recommended use:

- `suppress`: high-confidence traffic that can be excluded from billing or
  downstream metrics after policy approval.
- `quarantine`: suspicious traffic that should be reviewed, sampled, or delayed
  before suppression.
- `monitor`: traffic not selected for bot action, retained for trend analysis
  and future labels.

The binary `is_bot` field is the compatibility output. The tier is the safer
business-control layer.

## 8. Probability Perspective

The estimated probability that a flagged event is fraudulent is {precision:.0%}. This is an operational estimate based on signal agreement, not a calibrated probability.

The estimate is stronger when independent signals agree. For example, a click
with repeated query/domain replay, same-second burst evidence, and an upper-tail
ML score is more likely to be fraudulent than a click selected only because one
feature is unusual.

The estimate is weaker for isolated ML-only events, because unsupervised anomaly
detection can also surface legitimate edge cases such as unusual campaigns,
regional spikes, testing traffic, or rare but valid user behaviour.

## 9. Generalisation And Trade-Offs

The approach should generalise when bot traffic is repetitive, mechanically
timed, or concentrated in narrow device and query patterns. It may miss bots
that deliberately randomise timing, distribute across many query/domain pairs,
or imitate human behaviour closely.

The main trade-off is explainability versus coverage. Rules are easier to
defend but can miss novel patterns. The anomaly model broadens coverage but
needs careful interpretation because it finds unusual events, not necessarily
fraudulent events.

Material changes in geography, campaign volume, inventory, browser mix, or
feature extraction should trigger fresh threshold review.

## 10. Known Limitations

- There are no ground-truth labels, so measured precision, recall, and
  calibration cannot be reported.
- Legitimate campaigns can create high repetition, dense clusters, or regional
  concentration.
- The `ct` rule is supporting evidence only; it should not be used as a
  country-level blocking rule.
- The regular inter-arrival rule uses pseudo-session groups because there is no
  explicit user or session identifier.
- The anomaly score is relative to the current batch and should be monitored
  for drift across future runs.

## 11. Future Work

The next useful improvements are:

- labelled validation from manual review, chargebacks, or confirmed invalid
  traffic feedback
- campaign-level or inventory-level normalisation
- stronger browser or user-agent fingerprinting if those fields become
  available
- historical drift monitoring for score distributions and flagged rates
- calibrated probabilities once trusted labels exist
- a feedback loop from reviewed `suppress` and `quarantine` decisions

## 12. Submission Summary

The repository includes `submission.tsv` with `event_id`, `is_bot`, and
`operational_tier`.

This run selected {int(summary["bot_events"]):,} of {int(summary["total_events"]):,} events as likely bots ({bot_rate:.2%}).

Operational split:

- suppress: {suppress_count:,}
- quarantine: {quarantine_count:,}
- monitor: {monitor_count:,}

Use the report and dashboard as review aids. They explain why traffic was
selected and where the evidence is strongest, but they do not replace labelled
validation or policy approval.
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
