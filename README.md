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

The default run stays dependency-light and uses the built-in k-means anomaly backend. If scikit-learn is installed, you can opt into Isolation Forest scoring:

```bash
python3 -m bot_hunter.cli run --input ~/Downloads/bot-hunter-dataset.tsv --ml-backend sklearn
```

Use `--ml-backend auto` to prefer scikit-learn when available and fall back to the built-in k-means backend otherwise.

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

### Unsupervised anomaly classifier

The statistical classifier in `bot_hunter/ml.py` builds numeric features for each event in `bot_hunter/data.py`, standardizes them, then runs a dependency-light k-means implementation by default. Events farther from their nearest cluster center are treated as more anomalous.

The anomaly distance is converted into `ml_score` by ranking each event against all other distances. A high `ml_score` means the event is in the unusual tail of behavior, even if no single rule caught it.

An optional scikit-learn backend uses `IsolationForest` for anomaly scoring. It is not a default runtime dependency; install it with the `sklearn` extra or provide scikit-learn in your environment, then pass `--ml-backend sklearn` or `--ml-backend auto`.

#### Features used for anomaly scoring

Both anomaly backends use the same 15-feature vector:

- `log_domain_count`: frequency of the clicked domain.
- `log_query_count`: frequency of the search query.
- `log_query_domain_count`: frequency of that query/domain pair.
- `log_device_count`: frequency of the region/browser/OS combination.
- `log_same_second_count`: number of events at the exact same timestamp.
- `log_ttc_count`: frequency of the exact same time-to-click value.
- `ttc_seconds`: time-to-click in seconds.
- `query_terms`: number of terms in the query.
- `query_chars`: query length in characters.
- `has_bkl`: whether URL parameter `bkl` exists.
- `has_om`: whether URL parameter `om` exists.
- `kp`: numeric `kp` URL parameter.
- `sld`: numeric `sld` URL parameter.
- `hour`: hour of day from the event timestamp.
- `is_mobile_search`: whether `st=mobile_search_intl`.

Before k-means distance is calculated, each feature column is standardized as `(value - mean) / standard_deviation`, then Euclidean distance is measured from each event to its nearest cluster center. The feature values are also materialized in `artifacts/features.tsv` and exposed through the dashboard's Features page.

#### How the anomaly methods differ

The k-means backend groups standardized click behavior into a small number of clusters. For each click, Bot Hunter measures the distance to the nearest cluster center and ranks that distance against all other clicks. This works well as a dependency-light baseline: unusual clicks are often far from the common traffic clusters. The tradeoff is that k-means is a clustering method, not a dedicated anomaly detector. It can be sensitive to the number of clusters, and it assumes normal traffic can be represented by roughly center-shaped groups.

Isolation Forest is generally better suited to anomaly detection because it is designed to isolate rare observations. Instead of asking how close a click is to a cluster center, it builds random decision trees and scores clicks that can be separated quickly as more anomalous. That tends to fit bot-hunting better when suspicious events are sparse, unevenly distributed, or unusual because of a mix of signals rather than one large distance from a cluster. Bot Hunter keeps this backend optional so the default installation remains lightweight.

#### Current artifact examples

The checked-in `artifacts/summary.json` was produced from the default backend and analyzed 149,239 events. It flagged 3,781 events as bots, a 2.53% bot rate. Treat the `estimated_precision` value in the summary as an operational confidence estimate, not measured ground truth, because the dataset does not include labels.

Two high-risk examples in `artifacts/sample_events.json` show how the model and rules support the same business explanation:

- `evt_046784` clicked `www.amazon.co.uk` for query `nomnem`. It has `heuristic_score` 0.84, `ml_score` 0.9979, and `combined_score` 0.9063. The recorded reasons are concrete: the query/domain pair repeated 85 times, the query repeated 1,226 times, the Amazon UK domain appeared 4,623 times, the region/browser/OS cluster appeared 23,756 times, 6 clicks landed in the same second, and the query is very short.
- `evt_105119` clicked `www.amazon.de` for the same query, `nomnem`. It has `heuristic_score` 0.92, `ml_score` 0.8846, and `combined_score` 0.9051. Its reasons include 66 repeats of the query/domain pair, 1,226 repeats of the query, 5,543 clicks to the Amazon Germany domain, a 43,674-event device cluster, 4 clicks in the same second, an extreme time-to-click, and a very short query.

At the summary level, the same pattern is visible: Amazon domains are among the highest-volume clicked domains (`www.amazon.de`, `www.amazon.co.uk`, and `www.amazon.ca` are the top three), and `nomnem` is the top repeated query with 1,226 occurrences. Those facts do not prove fraud by themselves, but they make the flagged events easy to review: high repetition, dense device clusters, synchronized timing, and anomalous statistical scores are all pointing in the same direction.

The final pipeline in `bot_hunter/pipeline.py` combines both scores:

```python
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

An event is flagged as a bot if it is above the combined-score threshold or if the heuristic score is high enough on its own.
