# Bot Hunter

Bot Hunter is a Python application for detecting likely bot clicks in ad click logs. It
combines a rules-based classifier with an unsupervised anomaly scorer to produce a single
binary prediction per event, without requiring any labelled training data.

**Outputs at a glance:**

- `submission.tsv` — one row per event with `event_id` and `is_bot` (0 or 1)
- `artifacts/summary.json` — aggregate metrics and method-agreement stats
- `artifacts/sample_events.json` — highest-risk events with full scoring detail
- `docs/analysis_report.md / .html / .pdf` — written analysis
- A local HTTP dashboard for business review

---

## Quick Start

```bash
python3 -m bot_hunter.cli run --input ~/Downloads/bot-hunter-dataset.tsv
python3 -m bot_hunter.web --port 8000
```

Open `http://127.0.0.1:8000` to inspect the dashboard.

By default, Bot Hunter uses `--ml-backend auto`: it uses Isolation Forest when
`scikit-learn` is installed, and falls back to a built-in K-Means implementation
otherwise.

```bash
# Force the dependency-light fallback
python3 -m bot_hunter.cli run --input ~/Downloads/bot-hunter-dataset.tsv --ml-backend kmeans

# Require scikit-learn and fail fast if unavailable
python3 -m bot_hunter.cli run --input ~/Downloads/bot-hunter-dataset.tsv --ml-backend sklearn
```

To run the supervised scoring pilot without replacing the production method:

```bash
python3 -m bot_hunter.cli supervised-pilot --input ~/Downloads/bot-hunter-dataset.tsv --ml-backend sklearn
```

The pilot writes `artifacts/supervised_pilot.json` and
`docs/supervised_pilot_report.md/html`. Its supervised score is a rank-calibrated
seed-likeness score trained from strict deterministic rule positives only; it is not a
fraud probability and does not alter `submission.tsv`.

---

## Input Format

The expected raw file has no header and six tab-separated fields:

```
event_id    event_time    region    browser    os    url
```

The URL field can contain query-string parameters such as `d`, `q`, `ttc`, `ct`, `kl`,
and `kp`.

---

## How It Works

Bot Hunter runs two independent scoring methods and combines them into a final decision.
The sections below explain each step.

### 3.1 Feature Engineering

Before either scoring method runs, Bot Hunter extracts 15 numeric features from each
event. These are the same features used by both the anomaly scorer and the rules engine,
and they are also written to `artifacts/features.tsv` for inspection.

| Feature | What it captures |
|---|---|
| `log_domain_count` | How often this clicked domain appears across all events |
| `log_query_count` | How often this exact search query appears |
| `log_query_domain_count` | How often this query/domain pair appears together |
| `log_device_count` | How common this region/browser/OS combination is |
| `log_same_second_count` | Number of events sharing the exact same timestamp |
| `log_ttc_count` | How often this exact time-to-click value recurs |
| `ttc_seconds` | Time-to-click converted to seconds for direct timing magnitude |
| `query_terms` | Number of words in the search query |
| `query_chars` | Character length of the search query |
| `has_bkl` | Whether the URL contains the `bkl` parameter (1 or 0) |
| `has_om` | Whether the URL contains the `om` parameter (1 or 0) |
| `kp` | Numeric value of the `kp` URL parameter |
| `sld` | Numeric value of the `sld` URL parameter |
| `hour` | Hour of day extracted from the event timestamp |
| `log_ttc_seconds` | Log-scaled time-to-click magnitude, `log1p(ttc_seconds)` |

Before anomaly scoring, each feature is standardised: `(value − mean) / std_deviation`.
This puts all features on the same scale so no single large-magnitude feature dominates.

---

### 3.2 Rules-Based Classifier

The rules-based classifier in `bot_hunter/heuristics.py` scores each click by checking
for behavioural patterns that are commonly associated with automated traffic. Each
matching rule adds weight to a `heuristic_score` that is capped at 1.0.

Each rule also records a plain-English reason (for example: *"repeated query"* or
*"same-second click burst"*) that is surfaced in the dashboard and generated reports,
making the classifier's decisions auditable without any data science background.

**Rules applied:**

- Repeated query/domain pairs
- Repeated search queries
- High-volume clicked domains
- Dense region/browser/OS clusters
- Exact time-to-click value reused across many events
- Many clicks occurring within the same second
- Implausibly fast clicks (below a human reaction-time floor)
- Moderately long time-to-click values (20 to 60 seconds, as supporting evidence)
- Extremely long time-to-click values
- Very short queries (single character or near-empty)
- Regular inter-arrival timing within narrow pseudo-session groups

**A note on the inter-arrival timing rule:** Bot Hunter has no explicit session or user
identifier in this dataset. Applying a broad inter-arrival rule across all traffic would
produce many false positives against legitimate users who happen to browse quickly. The
rule is therefore intentionally narrow: it only compares clicks that share the same
region, browser, OS, search query, and clicked domain; it requires at least eight
matching events; and it contributes only a low weight of 0.10 when both conditions fire.
It is supporting evidence, not a standalone proof of automation.

**A note on time-to-click timing bands:** Bot Hunter separates direct timing evidence
from weaker supporting evidence. Implausibly fast clicks from 0 to 250 ms carry a higher
weight because they are hard to reconcile with normal human reaction time. Moderately
long clicks from 20 to 60 seconds add only low-weight support for delayed or mechanical
click patterns, and extremely long clicks above 120 seconds remain a separate timing
signal. Exact time-to-click reuse is handled separately because identical timer values
can indicate instrumentation or scripted reuse across many events.

**A note on the exact time-to-click reuse rule:** This is the only heuristic that uses
percentile calibration — meaning its threshold is computed from the data rather than set
to a fixed number. It counts how many times each time-to-click value recurs across all
events and uses the 99th percentile of those reuse counts as the threshold, with a
minimum floor of 40. This prevents the rule from falsely firing on small datasets where
coincidental matches are expected by chance.

The rule results are also stored in machine-readable form in
`artifacts/sample_events.json` under `rule_contributions`. Each contribution includes a
stable `rule_id`, a display label, a numeric weight, the observed value, and the
threshold that was applied — enabling programmatic analysis and auditing in addition to
human review.

---

### 3.3 Anomaly Scorer

The anomaly scorer in `bot_hunter/ml.py` uses the 15-feature standardised matrix
described in section 3.1. Its job is to find events whose combination of features is
statistically unusual compared to the rest of the dataset — without knowing in advance
what "bot-like" looks like.

**How anomaly scoring works (conceptually):** Rather than looking for events that break
a specific rule, the anomaly scorer asks: *"How different is this event from the
majority of traffic?"* Events that look unusual in multiple dimensions simultaneously
receive a high anomaly score. The raw anomaly value is then converted to `ml_score` by
ranking each event against all others — so a high `ml_score` means the event sits in the
unusual tail of the distribution, even if no single rule caught it.

**Isolation Forest (default when `scikit-learn` is installed)**

Isolation Forest builds a large number of random decision trees and measures how quickly
each event can be separated from the rest of the data. The intuition: normal events
look similar to many others and require many splits to isolate, while unusual events
stand out quickly and are isolated in just a few splits. Events isolated quickly score
higher. This design makes Isolation Forest well suited to anomaly detection when
suspicious events are sparse, unevenly distributed, or suspicious because of a
combination of signals rather than one large deviation.

**K-Means (fallback when `scikit-learn` is not installed)**

K-Means groups all events into a small number of clusters based on their feature
similarity. For each event, Bot Hunter measures the distance from that event to the
centre of its nearest cluster. Events far from any cluster centre are unusual compared
to the common traffic patterns and score higher. K-Means works well as a
dependency-light baseline but is a clustering method rather than a dedicated anomaly
detector — it can be sensitive to the number of clusters chosen and works best when
normal traffic forms roughly round, well-separated groups.

The `ml_backend` field in `artifacts/summary.json` records which backend was used for
a given run.

---

### 3.4 Combining the Two Scores

The final score for each event is a weighted combination:

```
combined_score = (0.58 × heuristic_score) + (0.42 × ml_score)
```

**Why this split?** The rules layer carries slightly more weight because it is directly
explainable and easier to audit — every flagged event has a plain-English reason attached.
The anomaly scorer still has enough weight (42%) to move borderline cases and catch
multivariate patterns that no individual rule covers.

**An event is flagged as bot (`is_bot = 1`) if either condition is true:**

```
combined_score ≥ 97.5th-percentile threshold
OR
heuristic_score ≥ 0.62
```

The summary report also breaks down flags by agreement level — *Heuristic + ML*,
*Heuristic only*, *ML only*, and *Neither strong* — so that disagreement between the
two methods stays visible and can be investigated.

### 3.5 Supervised Pilot

The optional `supervised-pilot` command compares the current rules+unsupervised baseline
with an experimental rules+supervised path. Positive labels come only from strict
deterministic rule contributions: repeated query/domain pairs, reused exact
time-to-click values, same-second bursts, and implausibly fast clicks. Regular
inter-arrival timing remains a supporting rule/feature, but is excluded from positive
labels because it is sensitive to pseudo-session construction. The pilot explicitly
excludes heuristic score, ML score, combined score, and heuristic/ML agreement as label
sources.

```bash
python3 -m bot_hunter.cli supervised-pilot --input ~/Downloads/bot-hunter-dataset.tsv --ml-backend sklearn
```

Unseeded events are treated as unlabeled background, not confirmed human traffic. For
that reason, the supervised output is reported as a seed-likeness ranking and reviewed
for seed capture, agreement/disagreement, and same-volume review efficiency before any
future promotion decision.

The pilot writes `artifacts/supervised_pilot.json` and
`docs/supervised_pilot_report.md / .html`. It does not write `submission.tsv` or
`artifacts/summary.json`, and it does not change the production `is_bot` decision path.

In the current pilot run, the supervised path improved strict-seed capture at the same
review volume: at 3,732 reviewed events, rules+unsupervised selected 3,369 strict-seed
events while rules+supervised selected 3,726. The deterministic holdout showed the same
direction: 674 strict-seed hits for rules+unsupervised versus 759 for rules+supervised at
the same 761-event review volume. This is evidence of better seed recovery and review
efficiency, not measured fraud precision, because the dataset still has no ground-truth
human/bot labels.

---

## Output and Confidence Tiers

The binary `is_bot` field (0 or 1) is the primary output. Bot Hunter also assigns each
event an `operational_tier` to guide how downstream workflows should treat the result:

| Tier | Meaning | Suggested action |
|---|---|---|
| `suppress` | High-confidence bot traffic | Automatic suppression — after policy approval |
| `quarantine` | Lower-confidence bot traffic (`is_bot=1` but weaker evidence) | Hold for manual review or delayed billing decision |
| `monitor` | Not flagged (`is_bot=0`) | Keep for trend tracking and future model validation |

These tiers are derived from the same unlabelled scores and represent operational
confidence buckets, not statistically measured precision. They are intended to guide
workflow severity, not to replace human review for edge cases.

Tier counts are written to `artifacts/summary.json`, included per-event in
`submission.tsv`, and surfaced in the dashboard.

---

## Precision and Limitations

Bot Hunter does not report true precision because the dataset contains no ground-truth
labels. True precision requires knowing which events are actually bots:

```
precision = true_positives / (true_positives + false_positives)
```

The `estimated_precision` field in `artifacts/summary.json` is a **signal agreement
score**, not measured precision. It starts from a baseline confidence and increases when
an event is supported by both a meaningful heuristic score and a high anomaly score —
that is, when two independent methods agree. Treat it as an operational confidence
indicator. To obtain measured precision, the project would need one of the following:

- Ground-truth labels from manual review
- Chargeback or fraud confirmation records
- A benchmark dataset with known bot/human labels
- Trusted synthetic labels

---

## Generated Files

| File | Contents |
|---|---|
| `submission.tsv` | Final binary predictions: `event_id` and `is_bot` |
| `artifacts/summary.json` | Aggregate metrics, tier counts, backend used, signal agreement score |
| `artifacts/features.tsv` | Raw 15-feature matrix for every event |
| `artifacts/sample_events.json` | Highest-risk events with scores, tiers, and rule contributions |
| `docs/analysis_report.md` | Written analysis report (Markdown) |
| `docs/analysis_report.html` | Browser-printable version of the report |
| `docs/analysis_report.pdf` | Lightweight PDF version of the report |

---

## Agentic Development Team

This repository includes a lightweight Claude Code + Codex CLI team setup using HCOM.
The default team has two specialist pairs: algorithm/engineering and
UX/report/documentation.

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
./scripts/start-agent-team
```

Individual roles can be started separately:

```bash
./scripts/start-algorithm-coder
./scripts/start-algorithm-reviewer
./scripts/start-ux-coder
./scripts/start-ux-reviewer
./scripts/start-orchestrator
```

Consolidated team instructions are in `development approach/team_instructions.md`.

---

## Appendix A — HDBSCAN Benchmark

HDBSCAN (Hierarchical Density-Based Spatial Clustering of Applications with Noise) is a
clustering algorithm that — unlike K-Means — does not require specifying the number of
clusters in advance. It finds arbitrarily shaped clusters and explicitly labels points
that do not belong to any cluster as noise. In a bot-detection context, those noise
points are anomaly candidates.

HDBSCAN was evaluated as a possible additional anomaly backend. The benchmark used the
same 149,239-event dataset, the same 15-feature standardised matrix, and the same
combined decision rule as the existing pipeline. HDBSCAN was configured with
`min_cluster_size=80`, `min_samples=20`, and `n_jobs=-1`.

**Results:**

| | Isolation Forest | HDBSCAN |
|---|---|---|
| Runtime | 2.3 s | 138.0 s |
| Events flagged | 3,732 | 3,732 |
| Overlap with IF | — | 3,057 |
| Jaccard similarity† | — | 0.69 |
| Unique flags (not in overlap) | — | 675 |
| Noise / anomaly rate | 1.50% | 2.95% |

† *Jaccard similarity: the share of flagged events both methods agreed on out of all
events either method flagged. 0.69 means roughly 69% overlap.*

HDBSCAN found a larger anomaly tail and the suspicious themes were broadly similar across
both backends. However, the additional flagged events did not improve reviewability enough
to justify the roughly 60× runtime cost.

**Decision:** HDBSCAN is not included as a production backend. Reconsider only with
sampling, tuning, or validation evidence showing materially better precision or reviewer
utility.

---

## Appendix B — Neural Model Benchmark

Two neural network approaches — an autoencoder and a variational autoencoder (VAE) —
were evaluated as optional anomaly backends.

**How these models work (briefly):**

- **Autoencoder:** A neural network trained to compress an event's features down to a
  small internal representation and then reconstruct the original values. Normal events
  reconstruct accurately; unusual events do not. Reconstruction error becomes the anomaly
  score.
- **Variational Autoencoder (VAE):** The same idea, but the internal representation is
  probabilistic rather than deterministic. This gives a more calibrated anomaly score at
  the cost of added model complexity. The anomaly score is reconstruction error plus a
  regularisation term (KL divergence — a measure of how far the learned internal
  distribution is from a standard baseline).

The benchmark used the same 149,239 events, the same 15-feature matrix, the same
heuristic scores, and the same flagging rule as the main pipeline:

```
combined_score = (0.58 × heuristic_score) + (0.42 × ml_score)
Flag if: combined_score ≥ 97.5th percentile OR heuristic_score ≥ 0.62
```

Settings: CPU only, fixed random seed 7, 8 training epochs, batch size 2048.

**Results:**

| Backend | Runtime | Peak memory | Events flagged | Jaccard vs IF |
|---|---|---|---|---|
| Isolation Forest | 2.0 s | 717 MB | 3,732 | — |
| Autoencoder | 12.4 s | 993 MB | 3,838 | 0.55 |
| VAE | 3.4 s | 1,028 MB | 3,789 | 0.62 |

The flagged events' suspicious characteristics — top queries, top domains, top regions —
were qualitatively similar across all three methods. The neural models added reconstruction-error
ranking but no direct business-level explanation beyond the same heuristic overlays already
available from Isolation Forest. They also required more memory and, for the autoencoder,
were around 6× slower.

**Decision:** Neither neural model is promoted to a production `--ml-backend` option.
Neural benchmarking remains available as optional evaluation tooling only (install with
`uv run --extra neural`). Reconsider only with labels or manual-review evidence showing
materially better precision or reviewer utility.
