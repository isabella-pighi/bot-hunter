# Bot Hunter

Bot Hunter is a dependency-light Python application for detecting likely bot clicks in ad click logs. It includes:

- A rules-based heuristic classifier.
- A standard-library unsupervised k-means anomaly classifier.
- A combined binary prediction written to `submission.tsv`.
- A local HTTP dashboard for business review.
- Generated Markdown, HTML, and PDF reports.

## Input format

The expected raw file has no header and six tab-separated fields:

```text
event_id    event_time    region    browser    os    url
```

The URL field can contain query-string parameters such as `d`, `q`, `ttc`, `ct`, `kl`, and `kp`.

## Quick start

```bash
python3 -m bot_hunter.cli run --input ~/Downloads/bot-hunter-dataset.tsv
python3 -m bot_hunter.web --port 8000
```

Open `http://127.0.0.1:8000` to inspect the dashboard.

## Generated files

- `submission.tsv`: final binary predictions with `event_id` and `is_bot`.
- `artifacts/summary.json`: dashboard and report metrics.
- `artifacts/sample_events.json`: highest-risk events shown in the dashboard.
- `docs/analysis_report.md`: written response to the brief.
- `docs/analysis_report.html`: browser-printable report.
- `docs/analysis_report.pdf`: lightweight PDF report.
- `docs/agentic_development_architecture.md`: proposed Claude Code, Codex CLI, HCOM, and reviewer/coder workflow.

## Classifier rationale

The heuristic classifier focuses on business-explainable signals: repeated query/ad pairs, repeated exact click times, unusually high-volume domains or device combinations, second-level bursts, and implausibly fast clicks. These are common traits of scripted traffic and can be converted directly into operational filters.

The ML classifier uses k-means over standardized behavioral features, then treats events farthest from their closest centroid as anomalous. It is unsupervised because the brief does not include labels. K-means is intentionally simple, transparent, and fast enough for this dataset size without external dependencies.
