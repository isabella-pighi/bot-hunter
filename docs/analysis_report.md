# Bot Hunter: Analysis Report

---

## 1. Project Context

Bot Hunter is a bot detection pipeline built for operational review rather than automated suppression. Every flagged event can be explained in plain terms to a business user, not just a data scientist.

The pipeline has no ground-truth labels, so it cannot report a traditionally measured precision score. Instead it reports an **operational confidence estimate** based on how strongly, and how independently, different signals agree on a given event. Where this report uses the word "precision", it refers to that estimate, not a calibrated metric.

---

## 2. How the Pipeline Works

Bot Hunter scores every event twice using two independent methods, then combines the results into a single decision.

**Rules-based classifier:** Hand-built rules that each add weight to a `heuristic_score` (capped at 1.0) when a suspicious behavioural pattern is detected. Every rule that fires attaches a plain-English reason to the event, making the decision fully auditable.

**Anomaly scorer (Isolation Forest):** A statistical model that scores each event by how unusual it looks across all 15 behavioural features simultaneously. Rather than matching specific rules, it asks: *how different is this event from the majority of traffic?* Events that stand out across multiple dimensions receive a higher `ml_score`.

> **Why two methods?** Rules are transparent and easy to convert into policy, but can only catch patterns anticipated at design time. The anomaly scorer catches multivariate oddities, meaning events suspicious across several dimensions at once, even if no single rule fires. Using both reduces the chance of missing either type.

**Final decision formula:**

```
combined_score = (0.58 × heuristic_score) + (0.42 × ml_score)
```

The rules layer carries slightly more weight because it is directly auditable. The anomaly scorer still has enough weight (42%) to move borderline cases.

**An event is flagged as bot (`is_bot = 1`) if either condition is true:**

```
combined_score  >=  97.5th-percentile threshold
OR
heuristic_score  >=  0.62
```

**Threshold rationale:** The 97.5th percentile is not an arbitrary cut-off. It corresponds to the upper tail of the canonical two-tailed significance test at α = 0.05, the same boundary that places a z-score of +1.96 on a standard normal distribution and the most widely recognised decision threshold in applied statistics. Choosing it here carries a specific practical meaning: the pipeline tolerates a false-positive rate of approximately 2.5% in exchange for flagging everything in the extreme anomalous tail. In the absence of ground-truth labels this is a principled default. It is statistically legible, externally defensible, and consistent with the cost assumption that false positives and false negatives are roughly equal in severity. It should be treated as a calibrated starting point rather than a permanent setting: once even a small labelled sample is available, the threshold can be re-evaluated empirically against a measured precision-recall curve and adjusted to reflect the actual cost ratio between suppressing a legitimate click and missing a fraudulent one.

---

## 3. Methods Evaluated but Not Included

Before settling on Isolation Forest, three alternatives were benchmarked on the same dataset:

- **HDBSCAN:** a clustering algorithm that labels events fitting no cluster as noise. It produced broadly similar results but ran ~60x slower (138 s vs 2.3 s) with no meaningful improvement in flagged event quality.
- **Autoencoder:** a neural network trained to reconstruct each event's features; poor reconstruction flags an anomaly. It was ~6x slower, used more memory, and produced harder-to-explain flags.
- **Variational Autoencoder (VAE):** a probabilistic variant with 62% flag overlap vs Isolation Forest, but the highest memory usage and no improvement in explanation quality.

All three remain available as optional evaluation tools. The production path is Isolation Forest when `scikit-learn` is installed, with K-Means as the fallback.

---

## 4. Results

| | |
|---|---|
| Events analysed | 149,239 |
| Flagged as bot | 3,732 (2.50% of total) |
| Confidence estimate | 77% (signal agreement) |
| Backend | Isolation Forest + rules |

### 4.1 Rules Fired

Events can trigger multiple rules simultaneously, so totals exceed 3,732. The dominant pattern, repeated query, accounts for 89% of all flagged events, pointing to a small number of coordinated click patterns rather than broadly distributed suspicious behaviour.

| Rule | Events |
|---|---|
| Repeated query | 3,325 |
| Repeated query / domain pair | 2,065 |
| High-volume clicked domain | 1,902 |
| Same-second click burst | 1,893 |
| Very short query | 1,862 |
| Heavy region / browser / OS cluster | 1,732 |
| Extreme time-to-click | 277 |
| Implausibly fast click | 27 |
| Regular inter-arrival timing | 11 |
| Reused exact time-to-click | 2 |

### 4.2 Method Agreement

Disagreement between methods is kept visible rather than hidden; events flagged by only one weak signal warrant more scrutiny than those where both agree.

| Agreement bucket | Events | What it means |
|---|---|---|
| Heuristic + ML agree | 966 | Strongest evidence: both methods independently flag the event |
| Heuristic only | 48 | A rule fired but the anomaly scorer did not flag it |
| ML only | 13,958 | Anomaly scorer flagged it; no individual rule fired |
| Neither strong | 134,267 | Not flagged, retained for monitoring |

The large **ML only** count (13,958) reflects the anomaly scorer's broader sensitivity. These events are assigned to the `quarantine` tier for review rather than automatic suppression.

---

## 5. Confidence Tiers

Rather than treating all flagged events identically, Bot Hunter assigns each a confidence tier to guide downstream workflow decisions. The binary `is_bot` field is unchanged; the tier adds context about how strongly the evidence supports that decision.

| Tier | Events | What it means | Suggested action |
|---|---|---|---|
| `suppress` | 981 | Both methods agree, or single method with very strong signal | Automatic suppression (after policy approval) |
| `quarantine` | 2,751 | `is_bot = 1` but weaker or single-method evidence | Hold for manual review or delayed billing decision |
| `monitor` | 145,507 | `is_bot = 0` | Retain for trend tracking and future labelling |

> **Important:** These tiers are operational confidence buckets derived from unlabelled scores. They are not statistically calibrated precision bands. Use them to prioritise reviewer time, not as a substitute for it.

---

## 6. Confidence Estimate

The estimated probability that a flagged event is genuinely fraudulent is **77%**.

This figure is not label-calibrated precision. It is a reasoned estimate based on how often the two independent methods agree on the same event. When both the rules layer and the anomaly scorer flag the same event strongly, the case is stronger than when only one method fires weakly. Treat it as an operational indicator, not a ground-truth measurement.

---

## 7. Known Limitations

- **No labels.** Without confirmed bot/human labels the pipeline cannot be formally validated. Every threshold and weight is a reasoned operational choice, not a learned or calibrated one.
- **Human-like bots will be missed.** Both methods rely on traffic being repetitive or mechanically timed. A bot mimicking varied human behaviour with diverse queries, realistic timing and plausible user agents, may not trigger any rule and may not appear anomalous statistically.
- **Legitimate campaigns can resemble bots.** High-repetition ad campaigns, retargeting traffic, or automated testing can produce the same patterns the rules flag. The `quarantine` tier exists partly to catch these before suppression.
- **Thresholds need recalibration when traffic changes.** If the traffic mix, geography, or ad inventory changes materially, current fixed thresholds may over- or under-flag. The exact time-to-click rule is the only one that recalibrates automatically; all others use fixed or rate-based cutoffs.

---

## 8. Recommended Actions

- **Suppress** events in the `suppress` tier. These have the strongest combined evidence. Apply only after policy approval for automatic suppression.
- **Review** events in the `quarantine` tier. These are flagged but with weaker or single-method evidence. Manual review or a delayed billing decision is appropriate before taking action.
- **Monitor** events in the `monitor` tier. Retain for drift detection, trend analysis, and as a future source of labels if manual review outcomes are recorded.

If false positives and false negatives are roughly equal in cost, the submitted binary prediction uses the combined score threshold across all flagged events rather than restricting to only the highest-confidence intersection.

---

## 9. Future Work

- **Labelled validation data:** even a small manually reviewed sample would allow true precision measurement and threshold calibration.
- **Campaign-level normalisation:** separating legitimate high-repetition campaigns from bot traffic before scoring would reduce quarantine false positives.
- **Browser and user-agent fingerprinting:** inconsistencies between declared and inferred device attributes are a strong bot signal if richer metadata is available.
- **Time-series burst detection:** detecting click bursts at the inventory or placement level would catch coordinated attacks spread thinly across individual events.
- **Feedback loop from manual review:** recording reviewer decisions against event IDs generates labels over time, enabling calibrated precision scores.

---

## 10. Submission

The repository includes `submission.tsv` with three fields per event:

| Field | Description |
|---|---|
| `event_id` | Original event identifier |
| `is_bot` | Binary prediction: 1 = bot, 0 = not bot |
| `operational_tier` | Confidence tier: `suppress`, `quarantine`, or `monitor` |

The binary `is_bot` field preserves full compatibility with any downstream system that expects only a bot/not-bot decision. The `operational_tier` field adds workflow context without changing that decision.
