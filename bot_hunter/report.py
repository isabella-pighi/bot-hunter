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
    ml_backend = str(summary.get("ml_backend", "auto"))
    model_name, model_detail, backend_label = _model_copy(ml_backend)
    top_reasons = summary.get("top_reasons", [])
    reason_lines = "\n".join(f"- {reason}: {count:,} events" for reason, count in top_reasons)
    if not reason_lines:
        reason_lines = "- No dominant heuristic reason was found."
    tier_counts = summary.get("tier_counts", {})
    tier_lines = "\n".join(
        f"- {tier}: {int(tier_counts.get(tier, 0)):,} events" for tier in ("suppress", "quarantine", "monitor")
    )

    return f"""# Bot Hunter Analysis Report

## 1. Classifiers

The application implements two classifiers. The first is a rules-based classifier that scores repeated query/domain pairs, repeated queries, high-volume domains, dense region/browser/OS clusters, exact time-to-click reuse, same-second bursts, implausibly fast clicks, and regular pseudo-session inter-arrival timing. The second is {model_name} over standardized behavioral features. {model_detail}

## 2. Anomalies found

The run analyzed {int(summary["total_events"]):,} events and flagged {int(summary["bot_events"]):,} events as bots ({bot_rate:.2%}). The strongest explainable patterns were:

{reason_lines}

The dashboard exposes these same signals with sample events so a business user can inspect the likely automated behavior without reading model internals.

## 3. Filtering options

Practical filters for similar datasets include dropping or quarantining traffic from repeated query/domain pairs, repeated exact `ttc` values, dense same-second bursts, and events above the combined anomaly threshold. Bot Hunter assigns operational tiers without changing the binary `is_bot` prediction:

{tier_lines}

Use `suppress` for high-confidence bot traffic after policy approval, `quarantine` for bot traffic that should be held for review, and `monitor` for traffic that is not selected for bot action but should remain available for trend analysis and future labels.

## 4. Rationale and generalization

The heuristic model is transparent and easy to convert into policy. The regular inter-arrival rule is intentionally narrow because the dataset has no explicit user or session identifier: it only compares clicks with the same region, browser, OS, query, and clicked domain, requires at least eight events, and adds low-weight supporting evidence rather than a standalone bot decision. The {backend_label} catches multivariate oddities that a small rule set may miss. Both should generalize when bot traffic is repetitive or mechanically timed, but they may miss human-like bots and may over-flag legitimate campaigns that naturally produce high repetition. The thresholds should be recalibrated when traffic mix, geography, or ad inventory changes materially.

## 5. Probability assessment

The estimated probability that a flagged event is fraudulent is {precision:.0%}. This is not label-calibrated precision; it is a reasoned estimate based on agreement between independent signals. Events flagged by both the heuristic model and the upper tail of the ML anomaly score are more likely to be fraudulent than events flagged by only one weak signal. The report therefore treats probability as an operational confidence estimate, not a measured ground truth metric.

## 6. Recommended actions

Assuming false positives and false negatives are roughly equal in cost, the submitted binary prediction uses the combined score threshold rather than only the highest-confidence intersection. For business action, use three tiers: suppress bot events with the strongest combined, heuristic, or heuristic/ML agreement signals; quarantine the remaining bot events for review; and monitor traffic that is not selected for bot action while retaining it for drift checks and future labels.

## 7. Future work

With more time, I would add labeled validation data, campaign-level normalization, browser/user-agent fingerprinting if available, time-series burst detection by inventory, calibrated probabilities, and a feedback loop from manual review decisions.

## 8. Submission

The repository includes `submission.tsv` with `event_id`, `is_bot`, and `operational_tier`, preserving the final binary prediction while adding a workflow tier.
"""


def _model_copy(ml_backend: str) -> tuple[str, str, str]:
    if ml_backend == "sklearn":
        return (
            "an Isolation Forest anomaly model",
            "Events that isolate unusually quickly in the fitted forest receive higher anomaly scores.",
            "Isolation Forest model",
        )
    if ml_backend == "kmeans":
        return (
            "an unsupervised k-means anomaly model",
            "Events far from their closest centroid receive higher anomaly scores.",
            "k-means model",
        )
    return (
        "the configured unsupervised anomaly model",
        "Events with stronger statistical anomaly evidence receive higher anomaly scores.",
        "anomaly model",
    )


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
    pdf.extend(f"xref\n0 {len(objects)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer << /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    path.write_bytes(bytes(pdf))
