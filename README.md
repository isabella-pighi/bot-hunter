# Bot Hunter

Bot Hunter is a dependency-light Python application for detecting likely bot clicks in ad click logs. It includes:

- A rules-based heuristic classifier.
- An Isolation Forest anomaly classifier when scikit-learn is available, with a standard-library k-means fallback.
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

By default, Bot Hunter uses `--ml-backend auto`: it prefers Isolation Forest when scikit-learn is installed and falls back to the built-in k-means backend otherwise.

```bash
python3 -m bot_hunter.cli run --input ~/Downloads/bot-hunter-dataset.tsv --ml-backend kmeans
```

Use `--ml-backend kmeans` when you want the dependency-light backend explicitly, or `--ml-backend sklearn` when you want to require scikit-learn and fail fast if it is unavailable.

## Agentic development team

This repo includes a lightweight Claude Code + Codex CLI team setup using HCOM. The default team has two specialist pairs: algorithm/engineering and UX/report/documentation.

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
./scripts/start-agent-team
```

Use `./scripts/start-algorithm-coder`, `./scripts/start-algorithm-reviewer`, `./scripts/start-ux-coder`, `./scripts/start-ux-reviewer`, or `./scripts/start-orchestrator` when you want to start roles individually. The consolidated team instructions live in `development approach/team_instructions.md`.

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
- regular inter-arrival timing within narrow pseudo-session groups

Each signal adds weight to `heuristic_score`, capped at `1.0`. The classifier records human-readable reasons such as `repeated query` or `same-second click burst`, which are shown in the dashboard and generated reports.

Bot Hunter does not have an explicit user or session identifier in this dataset, so broad device-level timing patterns would be unsafe on their own. The inter-arrival rule is therefore intentionally narrow: it only compares clicks with the same region, browser, OS, query, and clicked domain, requires at least eight events, and adds only a low `0.10` heuristic weight when timing is both frequent and regular. It is supporting evidence, not a standalone proof of automation.

The same rule hits are also stored as structured `rule_contributions` in `artifacts/sample_events.json`. Each contribution has a stable `rule_id`, display `label`, compatibility `reason`, numeric `weight`, raw `observed` value, threshold where applicable, and the condition that fired. Keeping both forms matters for explainability: business users can still read concise reasons, while audits, dashboards, grouped analysis, and per-rule impact checks can rely on stable machine-readable fields instead of parsing English text.

### Unsupervised anomaly classifier

The statistical classifier in `bot_hunter/ml.py` builds numeric features for each event in `bot_hunter/data.py`, standardizes them, then uses Isolation Forest by default when scikit-learn is available. If scikit-learn is not installed, the same `auto` default falls back to the dependency-light k-means implementation. Events with stronger anomaly evidence receive higher `ml_score` values.

The anomaly signal is converted into `ml_score` by ranking each event against all other anomaly values. A high `ml_score` means the event is in the unusual tail of behavior, even if no single rule caught it.

Scikit-learn is still optional rather than a hard runtime dependency. Install it with the `sklearn` extra or provide scikit-learn in your environment to get the preferred Isolation Forest backend; otherwise Bot Hunter continues with k-means. The generated summary records the actual backend used as `ml_backend`.

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

Before anomaly scoring, each feature column is standardized as `(value - mean) / standard_deviation`. Isolation Forest uses those standardized values directly. The k-means fallback then measures Euclidean distance from each event to its nearest cluster center. The feature values are also materialized in `artifacts/features.tsv` and exposed through the dashboard's Features page.

#### How the anomaly methods differ

The k-means fallback groups standardized click behavior into a small number of clusters. For each click, Bot Hunter measures the distance to the nearest cluster center and ranks that distance against all other clicks. This works well as a dependency-light baseline: unusual clicks are often far from the common traffic clusters. The tradeoff is that k-means is a clustering method, not a dedicated anomaly detector. It can be sensitive to the number of clusters, and it assumes normal traffic can be represented by roughly center-shaped groups.

Isolation Forest is generally better suited to anomaly detection because it is designed to isolate rare observations. Instead of asking how close a click is to a cluster center, it builds random decision trees and scores clicks that can be separated quickly as more anomalous. That tends to fit bot-hunting better when suspicious events are sparse, unevenly distributed, or unusual because of a mix of signals rather than one large distance from a cluster. Bot Hunter therefore uses Isolation Forest as the primary backend when available while keeping k-means as the automatic fallback.

#### HDBSCAN benchmark decision

HDBSCAN was evaluated as a possible additional anomaly backend, but it is not part of the current implementation. The benchmark used the same 149,239-event dataset, the same 15-feature standardized matrix, and the same combined decision rule used by the existing pipeline. The comparison was between the current scikit-learn Isolation Forest backend and `sklearn.cluster.HDBSCAN` configured with `min_cluster_size=80`, `min_samples=20`, and `n_jobs=-1`.

The benchmark results were:

- Isolation Forest runtime: 2.303 seconds.
- HDBSCAN runtime: 137.953 seconds.
- Both approaches flagged 3,732 events.
- Flagged-event overlap: 3,057 events.
- Jaccard similarity: 0.6937.
- Unique flagged events outside the overlap: 675 per backend.
- HDBSCAN clusters: 17 non-noise clusters.
- HDBSCAN noise points: 4,404 events, a 2.951% noise rate.
- HDBSCAN `ml_tail_rate`: 2.951%.
- Isolation Forest `ml_tail_rate`: 1.5003%.

The suspicious themes were broadly similar across both backends. HDBSCAN found a larger anomaly tail, but the additional review set did not improve reviewability enough to justify roughly 60x runtime cost in the current dependency-light workflow.

Decision: do not add an HDBSCAN backend now. Reconsider it only with sampling, tuning, or validation evidence showing better measured precision or materially better reviewer utility.

#### Neural benchmark decision

PyTorch autoencoder and variational autoencoder models were evaluated as optional anomaly backends, but neither is part of the production `--ml-backend` options. The benchmark used `data/bot-hunter-dataset.tsv`, the same 149,239 events, the existing 15-feature matrix from `bot_hunter.data.build_features`, the same feature standardization used by `bot_hunter.ml`, unchanged heuristic scores from `apply_heuristics`, rank-normalized anomaly values for `ml_score`, and the existing combined decision rule:

```python
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

Events were flagged when the combined score was at or above the 97.5th percentile cutoff or when `heuristic_score >= 0.62`, matching the current pipeline. The benchmark was run CPU-only with fixed seed `7`, 8 capped training epochs, batch size `2048`, and this command:

```bash
uv run --extra neural scripts/neural-benchmark --input data/bot-hunter-dataset.tsv --output /tmp/bot-hunter-neural-benchmark.json
```

The optional evaluation dependency group is `neural = ["scikit-learn>=1.4", "torch>=2.3"]`. This extra is for benchmark tooling only; production behavior is unchanged. `--ml-backend auto` still prefers Isolation Forest when scikit-learn is available, and k-means remains the fallback.

Model settings:

- Isolation Forest baseline: `sklearn.ensemble.IsolationForest(random_state=7, contamination="auto")`.
- Autoencoder: `15->32->8->32->15`, ReLU hidden layers, Adam with `lr=0.001`, scored by mean squared reconstruction error.
- VAE: encoder `15->32->mu/logvar(8)`, decoder `8->32->15`, Adam with `lr=0.001`, scored by reconstruction MSE plus `0.001 * KL divergence`, with deterministic scoring from the latent mean after training.

Benchmark metrics:

| Backend | Runtime | Approx. peak memory | Flagged events | `ml_tail_rate` | IF overlap | Jaccard vs IF | Unique vs IF | IF unique vs backend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Isolation Forest | 2.022s | 716.9 MB | 3,732 | 1.5003% | 3,732 | 1.0000 | 0 | 0 |
| Autoencoder | 12.366s | 992.6 MB | 3,838 | 1.5003% | 2,689 | 0.5509 | 1,149 | 1,043 |
| VAE | 3.403s | 1,027.8 MB | 3,789 | 1.5003% | 2,877 | 0.6195 | 912 | 855 |

The review slices were similar, but not better for the neural models:

- Isolation Forest top reasons: repeated query 3,323; repeated query/domain pair 2,065; high-volume clicked domain 1,904; same-second click burst 1,890; very short query 1,864; heavy region/browser/os cluster 1,740; extreme time-to-click 279; implausibly fast click 27.
- Autoencoder top reasons: repeated query 3,638; very short query 2,165; heavy region/browser/os cluster 2,160; same-second click burst 2,048; repeated query/domain pair 1,882; high-volume clicked domain 1,405; extreme time-to-click 161; implausibly fast click 36.
- VAE top reasons: repeated query 3,405; heavy region/browser/os cluster 2,080; same-second click burst 2,001; very short query 1,954; repeated query/domain pair 1,876; high-volume clicked domain 1,657; extreme time-to-click 202; implausibly fast click 48.
- Isolation Forest top domains: `www.amazon.de` 818; `www.booking.com` 392; `www.amazon.ca` 372; `www.amazon.co.uk` 322; `duckduckgo.com` 248; `www.amazon.it` 232; `www.overstock.com` 186; `sofatutor.com` 183.
- Autoencoder top domains: `www.amazon.de` 655; `www.booking.com` 302; `www.amazon.ca` 278; `duckduckgo.com` 228; `www.amazon.it` 216; `www.amazon.co.uk` 170; `sofatutor.com` 145; `www.overstock.com` 137.
- VAE top domains: `www.amazon.de` 707; `www.booking.com` 353; `www.amazon.ca` 340; `www.amazon.co.uk` 257; `www.amazon.it` 234; `duckduckgo.com` 230; `sofatutor.com` 172; `www.overstock.com` 160.
- Isolation Forest top queries: `nomnem` 587; `neti biscot` 204; `nana` 191; `fuzz sulphid` 188; `censer amatorial callainite` 186; `vaunt` 185; `orlo pliny` 185; `shamefast ui` 185.
- Autoencoder top queries: `nomnem` 916; `splenocyte` 265; `vaunt` 191; `nana` 185; `shamefast ui` 182; `orlo pliny` 180; `neti biscot` 178; `pluralizes` 177.
- VAE top queries: `nomnem` 747; `splenocyte` 223; `censer amatorial callainite` 195; `nana` 192; `vaunt` 187; `starn noonmeat` 177; `vielle motoneuron` 174; `fuzz sulphid` 169.
- Isolation Forest top regions: Earth 1,809; Mars 1,762; Mercury 53; Venus 43; Saturn 36; Jupiter 29.
- Autoencoder top regions: Mars 1,927; Earth 1,719; Venus 51; Saturn 51; Mercury 46; Jupiter 44.
- VAE top regions: Mars 1,936; Earth 1,702; Mercury 40; Venus 40; Jupiter 39; Saturn 32.
- Isolation Forest top event IDs: `evt_105119`, `evt_046784`, `evt_128656`, `evt_068755`, `evt_038503`, `evt_005176`, `evt_063596`, `evt_043433`, `evt_111917`, `evt_126217`.
- Autoencoder top event IDs: `evt_105119`, `evt_068755`, `evt_046784`, `evt_128656`, `evt_126217`, `evt_133713`, `evt_126676`, `evt_132706`, `evt_120121`, `evt_114075`.
- VAE top event IDs: `evt_105119`, `evt_068755`, `evt_046784`, `evt_073286`, `evt_063103`, `evt_063596`, `evt_007787`, `evt_128656`, `evt_005176`, `evt_126217`.

Qualitatively, Isolation Forest remains the best production fit: it was fastest, used the lowest observed peak memory, is already integrated, and its flags align with the existing heuristic explanations. The autoencoder added reconstruction-error ranking but no direct business explanation beyond the same heuristic overlays; it was about 6.1x slower than Isolation Forest, used more memory, and had only 0.5509 Jaccard similarity with Isolation Forest. The VAE was closer to Isolation Forest than the autoencoder, but it used the most memory, adds stochastic training and model complexity, and did not improve reviewability or explanation quality.

Decision: do not promote the autoencoder or VAE into production `--ml-backend` choices. Keep neural benchmarking as optional evaluation tooling only, and reconsider neural backends only with labels or manual-review evidence showing materially better precision or reviewer utility.

#### Current artifact examples

The checked-in `artifacts/summary.json` was produced by an earlier k-means/default run and analyzed 149,239 events. It flagged 3,781 events as bots, a 2.53% bot rate. Treat the `estimated_precision` value in the summary as an operational confidence estimate, not measured ground truth, because the dataset does not include labels.

Two high-risk examples in `artifacts/sample_events.json` show how the model and rules support the same business explanation:

- `evt_046784` clicked `www.amazon.co.uk` for query `nomnem`. It has `heuristic_score` 0.84, `ml_score` 0.9979, and `combined_score` 0.9063. The recorded reasons are concrete: the query/domain pair repeated 85 times, the query repeated 1,226 times, the Amazon UK domain appeared 4,623 times, the region/browser/OS cluster appeared 23,756 times, 6 clicks landed in the same second, and the query is very short.
- `evt_105119` clicked `www.amazon.de` for the same query, `nomnem`. It has `heuristic_score` 0.92, `ml_score` 0.8846, and `combined_score` 0.9051. Its reasons include 66 repeats of the query/domain pair, 1,226 repeats of the query, 5,543 clicks to the Amazon Germany domain, a 43,674-event device cluster, 4 clicks in the same second, an extreme time-to-click, and a very short query.

At the summary level, the same pattern is visible: Amazon domains are among the highest-volume clicked domains (`www.amazon.de`, `www.amazon.co.uk`, and `www.amazon.ca` are the top three), and `nomnem` is the top repeated query with 1,226 occurrences. Those facts do not prove fraud by themselves, but they make the flagged events easy to review: high repetition, dense device clusters, synchronized timing, and anomalous statistical scores are all pointing in the same direction.

The final pipeline in `bot_hunter/pipeline.py` combines both scores:

```python
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

The 0.58/0.42 split is intentional rather than learned: the rule layer stays slightly dominant because it is more directly explainable and easier to audit, while ML still has enough weight to move borderline cases and catch multivariate oddities. The suppress thresholds are conservative guardrails, not fitted probabilities. The same 0.62 heuristic and 0.90 ML agreement thresholds that support suppression are also reported separately as `Heuristic + ML`, `Heuristic only`, `ML only`, and `Neither strong` buckets so method disagreement stays visible.

An event is flagged as a bot if it is above the combined-score threshold or if the heuristic score is high enough on its own.

#### Operational confidence tiers

The binary `is_bot` field remains the compatibility decision: `1` means Bot Hunter selected the event as likely bot traffic and `0` means it did not. Bot Hunter also assigns an `operational_tier` so business workflows can separate action from model output:

- `suppress`: high-confidence bot traffic. These events are flagged as bots and have a strong combined score, a strong heuristic score, or agreement between heuristic and anomaly scores. Use this tier for automatic suppression only after policy approval.
- `quarantine`: lower-confidence bot traffic. These events are still `is_bot=1`, but they do not meet the stronger suppress conditions. Hold them for review, sampling, or delayed billing decisions.
- `monitor`: traffic not selected for bot action. These events are `is_bot=0`; keep them for trends, drift checks, and future labels.

These tiers are operational confidence buckets, not measured precision. They are derived from the same unlabeled scores and are intended to guide workflow severity. The pipeline writes tier counts to `artifacts/summary.json`, includes each event's tier in `submission.tsv`, and exposes sampled tiers in `artifacts/sample_events.json` and the dashboard.

#### Precision and confidence

Bot Hunter does not currently calculate true precision for the heuristic, k-means, Isolation Forest, or combined methods because the dataset does not include ground-truth labels. True precision requires known true positives and false positives:

```text
precision = true_positives / (true_positives + false_positives)
```

The `estimated_precision` field in the generated summary is therefore not measured model precision. It is an operational confidence estimate based on agreement between independent signals. The pipeline starts with a baseline confidence and increases it when final flagged events are supported by both a meaningful heuristic score and a high anomaly score.

Measured per-method precision would require labeled data, manual review outcomes, chargeback/fraud confirmation, trusted synthetic labels, or a benchmark dataset with known bot/human labels. With labels available, the project could report separate precision values for heuristic-only flags, k-means flags, Isolation Forest flags, and the final combined decision.
