# Bot Hunter

Bot Hunter detects likely bot clicks in ad click logs without labelled training data. The
production pipeline is intentionally narrow: an auditable rules classifier plus an
Extended Isolation Forest (EIF) anomaly scorer.

**Outputs:**

- `submission.tsv` with `event_id`, `is_bot`, and `operational_tier`
- `artifacts/summary.json` with aggregate metrics, thresholds, and method disagreement
- `artifacts/features.tsv` with engineered feature values
- `artifacts/sample_events.json` with high-risk examples and rule contributions
- `docs/analysis_report.md`, `.html`, and `.pdf`
- A local HTTP dashboard for review

## Quick Start

Install with the EIF extra, then run the single production classifier:

```bash
uv run --extra eif python -m bot_hunter.cli run --input data/bot-hunter-dataset.tsv
uv run --extra eif python -m bot_hunter.web --port 8000
```

Open `http://127.0.0.1:8000` to inspect the dashboard.

The CLI no longer exposes alternate ML backends or supervised pilot commands. If `isotree`
is unavailable, the run fails fast with an installation hint instead of silently switching
models.

## Input Format

The raw file has six tab-separated fields and may include a header:

```text
event_id    event_time    region    browser    os    url
```

`event_time` must use `YYYY-MM-DD HH:MM:SS`. The URL query string can include `d`, `q`,
`ttc`, `ct`, `kl`, `kp`, and `sld`.

## Scoring

Bot Hunter builds 15 numeric features for each event:

| Feature | Meaning |
|---|---|
| `log_domain_count` | Clicked-domain frequency |
| `log_query_count` | Exact query frequency |
| `log_query_domain_count` | Query/domain pair frequency |
| `log_device_count` | Region/browser/OS cluster frequency |
| `log_country_count` | `ct` country frequency |
| `log_same_second_count` | Events with the same timestamp |
| `log_ttc_count` | Exact time-to-click reuse |
| `ttc_seconds` | Time-to-click in seconds |
| `kp` | Numeric `kp` parameter |
| `sld` | Numeric `sld` parameter |
| `hour` | Event hour |
| `log_ttc_seconds` | Log-scaled time-to-click |
| `is_sub_200ms_click` | Mechanical sub-200 ms click indicator |
| `log_pseudo_session_10s_click_count` | Local 10-second burst density |
| `query_entropy` | Shannon entropy of query text |

The rules layer scores repeated query/domain pairs, repeated queries, confirmed query
repetition, high-volume domains, dense device clusters, exact `ttc` reuse, same-second
bursts, dense burst repetition clusters, timing bands, very short queries, and narrow
pseudo-session regularity. Each rule emits a structured `rule_contribution` so reports
can show why a click was suspicious.

The EIF layer standardizes the ML feature matrix, applies feature weights, fits `isotree`
with deterministic settings, and converts anomaly values to percentile-like ranks. The
production decision combines both scores:

```text
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

An event is flagged when either condition is true:

```text
combined_score >= run-specific 97.5th-percentile cutoff
or heuristic_score >= 0.62
```

Operational tiers are separate from the binary output:

- `suppress`: high-confidence bot traffic after policy approval
- `quarantine`: selected bot traffic that needs review before action
- `monitor`: traffic not selected for bot action

## Method Disagreement

`artifacts/summary.json` reports four disagreement buckets:

- `Heuristic + ML`
- `Heuristic only`
- `ML only`
- `Neither strong`

The rules agreement threshold is `heuristic_score >= 0.62`. The EIF agreement threshold
is `ml_score >= 0.995`, tuned to reserve standalone ML-only evidence for the extreme
anomaly tail. The previous broad top-decile agreement threshold produced many `ML only`
entries without enough explainable support. On `data/bot-hunter-dataset.tsv`, the EIF
tail setting reports 590 `ML only` events; the obsolete 0.90 cutoff reported 12,855.

## Dashboard

The dashboard can run the production pipeline from either an uploaded TSV or a server-side
path. It does not expose model selection. It reads the generated artifacts from the
repository root and serves:

- `/` dashboard
- `/features` feature table
- `/report` HTML report
- `/api/summary`, `/api/events`, `/api/features`

## Development

Run tests:

```bash
uv run pytest
```

Run a full artifact refresh:

```bash
uv run --extra eif python -m bot_hunter.cli run --input data/bot-hunter-dataset.tsv
```

The project intentionally omits supervised pilots, sklearn Isolation Forest, k-means, and
obsolete benchmark report surfaces. Reintroduce alternate models only with labelled
validation or a clear operational requirement.
