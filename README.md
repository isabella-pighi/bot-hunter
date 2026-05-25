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

## Agentic development team

This repo includes a lightweight Claude Code + Codex CLI team setup using HCOM:

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
./scripts/start-agent-team
```

Use `./scripts/start-coder`, `./scripts/start-reviewer`, or `./scripts/start-orchestrator` when you want to start roles individually. Development team documentation and role prompts live in `development approach/`.

## Generated files

- `submission.tsv`: final binary predictions with `event_id` and `is_bot`.
- `artifacts/summary.json`: dashboard and report metrics.
- `artifacts/sample_events.json`: highest-risk events shown in the dashboard.
- `docs/analysis_report.md`: written response to the brief.
- `docs/analysis_report.html`: browser-printable report.
- `docs/analysis_report.pdf`: lightweight PDF report.
- `development approach/`: proposed Claude Code, Codex CLI, HCOM, reviewer/coder workflow, and role prompts.
- `scripts/`: helper scripts for starting the local agentic development team.

## Implemented detection methods

Bot Hunter currently uses two scoring methods, then combines them into one final bot decision.

### Rules-based heuristic classifier

The explainable classifier in `bot_hunter/heuristics.py` scores each click using hand-built behavioral signals that are suspicious for automated traffic:

- repeated query/domain pairs
- repeated search queries
- high-volume clicked domains
- dense region/browser/OS clusters
- exact time-to-click reuse
- many clicks in the same second
- implausibly fast clicks
- extremely long time-to-click values
- very short queries

Each signal adds weight to `heuristic_score`, capped at `1.0`. The classifier also records human-readable reasons such as `repeated query` or `same-second click burst`, which are shown in the dashboard and generated reports.

### Unsupervised k-means anomaly classifier

The statistical classifier in `bot_hunter/ml.py` builds numeric features for each event in `bot_hunter/data.py`, standardizes them, then runs a dependency-light k-means implementation. Events farther from their nearest cluster center are treated as more anomalous.

The anomaly distance is converted into `ml_score` by ranking each event against all other distances. A high `ml_score` means the event is in the unusual tail of behavior, even if no single rule caught it.

The final pipeline in `bot_hunter/pipeline.py` combines both scores:

```python
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

An event is flagged as a bot if it is above the combined-score threshold or if the heuristic score is high enough on its own.
