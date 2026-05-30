# Bot Hunter Analysis Report

## 1. Executive Summary & Problem Statement

Bot Hunter analyses fictitious ad-click traffic to identify events that look
more like automated bot activity than legitimate user behaviour. The business
challenge is a familiar one for advertising platforms: invalid clicks can
inflate campaign metrics, distort billing, reduce trust in performance
reporting, and consume operational time that should be spent on genuine
customer outcomes.

This run read `data/bot-hunter-dataset.tsv` and analysed 149,239 click
events. Each row contains an event identifier, timestamp, region, browser,
operating system, and click URL. The URL query string carries behaviour signals
such as clicked domain (`d`), search query (`q`), time to click (`ttc`), and
country-like context (`ct`).

Bot Hunter selected 3,731 events, or 2.50% of the batch, as
likely bot traffic for review. This is a meaningful operational finding: even a
small invalid-click rate can affect revenue assurance, customer confidence,
campaign optimisation, and the credibility of downstream reporting.

This report should be read as evidence for review, not as proof of fraud for
every individual event. The dataset does not include ground-truth labels, so
the system cannot claim measured precision, measured recall, or a calibrated
fraud probability. The submitted output is `submission.tsv`. It keeps the
required binary `is_bot` decision and adds `operational_tier` so the same
prediction can be used carefully in business workflows.

## 2. Methodology & Rationale

Bot Hunter uses two classifiers because the risk has two different shapes. A
rules classifier catches patterns that are easy to explain and audit, such as
repeated query/domain pairs, mechanical timing, and dense bursts. The
Extended Isolation Forest model catches unusual combinations across engineered features that
fixed rules may miss.

This combined design was chosen over a simpler single-rule approach because a
single rule is too brittle for adversarial traffic. For example, a bot can
avoid one obvious threshold while still leaving a broader statistical footprint
across timing, repeated terms, clicked domains, and device-like context. The
rules layer gives leadership an auditable explanation; the anomaly model adds
coverage where fixed rules would otherwise be narrow.

| Component | Current choice | Why this choice was made |
|---|---|---|
| Rules classifier | Weighted heuristic rules | Transparent, auditable, and suitable for explaining repeated or mechanical click patterns. |
| ML classifier | Extended Isolation Forest model | Works without labels and can detect unusual combinations across engineered features. |
| Score blend | `0.58 * heuristic_score + 0.42 * ml_score` | Keeps explainable rule evidence dominant while still using the anomaly model. |
| Main cutoff | 97.5th percentile combined-score threshold | Keeps the selected population stable for an unlabelled batch. |
| Override | `heuristic_score >= 0.62` | Protects high-confidence rule evidence from being missed by model ranking shifts. |

The final score is a weighted blend:

```text
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

The rules layer is weighted slightly higher because it is easier to explain and
audit. The anomaly model still matters because it can identify unusual
combinations that a small rule set may not capture.

Raw URLs are not model-ready. Bot Hunter parses each query string and converts
it into behavioural features. Count features are log-transformed because
click-log counts are heavy-tailed: a few domains or queries may appear many
times while most appear once. `kp` and `sld` are treated as categorical
identifiers, not ordered numeric measurements. Their raw values remain in
`artifacts/features.tsv` for audit, but the model uses `log_kp_count` and
`log_sld_count` to learn concentration without inventing false numeric distance
between categories.

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

Rule contributions are separated into strong and supporting evidence. Strong
rules represent direct mechanical or replay-like patterns, such as impossible
timing or repeated query/domain behaviour. Supporting rules provide context,
such as volume, concentration, or broad clustering. Supporting contributions
are capped so several weak signals cannot add up to the same meaning as a
strong bot signal on their own.

| Rule strength | Meaning | Score treatment |
|---|---|---|
| Strong | Direct mechanical or replay evidence | Contributes its full rule weight |
| Supporting | Contextual or weaker evidence | Capped together at 0.24 |

The exact time-to-click reuse rule uses a 99th-percentile reuse-count threshold
with an absolute floor. The main repetition and concentration rules also use
99th-percentile batch thresholds with the previous fixed count and total-rate
cutoffs kept as guardrails. This lets the rules adapt to the observed
population while avoiding weak duplicate counts in small runs.

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
- low-cardinality `kp` and `sld` value frequencies

High-volume domain frequency and global country frequency are down-weighted to
0.50 and 0.50, respectively. The low-cardinality
`kp` and `sld` frequency features are down-weighted to 0.50 and
0.25. Events isolated quickly by random hyperplane splits receive higher anomaly scores. EIF is the only production anomaly model; alternate ML backends and supervised pilots have been removed.

## 3. Core Statistical Findings

The current run shows a concentrated anomaly population rather than a broad
quality problem across the whole dataset. Bot Hunter selected 3,731 of
149,239 events as likely bot traffic. That is 2.50% of the
run, leaving the large majority of traffic in the monitor population.

| Metric | Current value | Plain-English meaning |
|---|---:|---|
| Total events analysed | 149,239 | Number of click events in the batch. |
| Selected bot events | 3,731 | Events marked `is_bot = 1`. |
| Selected bot rate | 2.50% | Share of the batch selected as likely bot traffic. |
| Suppress tier | 1,863 | Strongest operational candidates, subject to policy approval. |
| Quarantine tier | 1,868 | Suspicious events that should be reviewed or sampled. |
| Monitor tier | 145,508 | Events not selected for bot action. |
| Combined-score cutoff | 0.568053 | Run-specific anomaly threshold. |
| Heuristic-only flag rate | 1.36% | Share flagged by rules before model blending. |
| ML agreement-tail rate | 2.50% | Reference tail used to compare ML agreement. |
| Operational confidence estimate | 74.49% | Signal-based estimate, not measured precision. |

Top explainable rule patterns from the current run:

| Pattern | Events | How to explain it |
|---|---:|---|
| repeated query | 3,403 | The same search term appears unusually often. |
| repeated query/domain pair | 2,086 | The same search term repeatedly clicks the same domain. |
| confirmed query repetition | 2,023 | Query repetition is backed by additional context. |
| very short query | 1,798 | Short terms can be legitimate, but are useful supporting evidence. |
| high-volume clicked domain | 1,732 | A domain receives unusually concentrated clicks. |
| heavy region/browser/OS cluster | 1,168 | Traffic is concentrated in a narrow device/server footprint. |
| concentrated ct context | 904 | Country-like context is concentrated with repetition and clustering. |
| same-second click burst | 677 | Multiple clicks happen in the same second. |
| moderately long time-to-click | 431 | Timing is unusual enough to support other evidence. |
| dense burst repetition cluster | 236 | Burstiness and repeated behaviour appear together. |

Method agreement from the current run:

| Bucket | Events | Interpretation |
|---|---:|---|
| Heuristic + ML | 1,726 | Strongest review candidates because both methods agree. |
| Heuristic only | 311 | Explainable rule hits that are not extreme in the ML feature space. |
| ML only | 2,005 | Multivariate anomalies that need careful sampling or review. |
| Neither strong | 145,197 | Traffic not strongly indicated by either method. |

Operational anomaly classes from the current run:

| Class | Selected events | Recommended handling |
|---|---:|---|
| Repetition with supporting context | 1,877 | Review as replay-like traffic. Suppress only when the event is already in the suppress tier; otherwise quarantine or sample. |
| Compound burst/replay | 562 | Treat suppress-tier events as strong operational candidates; quarantine the rest for timing-pattern review. |
| ML-tail multivariate anomaly | 509 | Quarantine or sample. Do not suppress automatically without feature-deviation review or labels. |
| Repetition with timing anomaly | 355 | Prioritise when suppress-tier or when timing evidence is strong; otherwise quarantine for sampling. |
| Repetition dominated | 350 | Use as an explainable replay candidate. Quarantine lower-score cases when ML agreement is absent. |
| Supporting context plus combined tail | 77 | Monitor or quarantine. These are useful for trend review, not standalone suppression. |
| Other combined-tail anomaly | 1 | Sample manually before taking action. |

The largest pattern is repetition with supporting context. In practical terms,
that means the same queries and clicked domains appear far more often than
expected and are reinforced by other signals such as device-like clustering,
country-like context, or timing behaviour. The ML-only population is also
material, but it carries a different business meaning: those events are unusual
in the feature space and should be sampled or quarantined rather than treated
as automatically fraudulent.

## 4. Anomaly Explanations & Practical Guidance

Repetition is suspicious when the same query, clicked domain, and device-like
context appear together. Timing matters because some click patterns are
difficult for humans to produce consistently. Country-like `ct` concentration
is supporting evidence only; it should not be treated as a country-blocking
rule. ML-only events are unusual, but unusual does not automatically mean
fraudulent.

Operational anomaly classes derived from the current unlabelled run; these are not proven fraud labels.

The classes below group the 3,731 selected events from this run.
The grouping is backed by full-run rule contributions, rule strength and family
fields, heuristic and ML scores, method-agreement buckets, operational tiers,
and the run-specific thresholds described later in this report.

| Class | Selected events | Data backing | Suggested handling |
|---|---:|---|---|
| Repetition with supporting context | 1,877 | tiers: suppress 1,327, quarantine 550; methods: Heuristic + ML 1,198, Heuristic only 186, Combined tail 493; top rules: repeat_query (1,877), repeat_query_domain (1,384), confirmed_query_repetition (1,384) | Review as replay-like traffic. Suppress only when the event is already in the suppress tier; otherwise quarantine or sample. |
| Compound burst/replay | 562 | tiers: suppress 154, quarantine 408; methods: Heuristic + ML 150, Heuristic only 11, Combined tail 401; top rules: repeat_query (558), same_second_burst (441), short_query (285) | Treat suppress-tier events as strong operational candidates; quarantine the rest for timing-pattern review. |
| ML-tail multivariate anomaly | 509 | tiers: quarantine 509; methods: ML only 509; This class is grouped by anomaly-model agreement, not by rule explanations. Low-weight rules may be present, but they do not cross the heuristic override threshold. | Quarantine or sample. Do not suppress automatically without feature-deviation review or labels. |
| Repetition with timing anomaly | 355 | tiers: suppress 199, quarantine 156; methods: Heuristic + ML 195, Heuristic only 4, Combined tail 156; top rules: repeat_query (355), moderate_long_ttc (283), repeat_query_domain (199) | Prioritise when suppress-tier or when timing evidence is strong; otherwise quarantine for sampling. |
| Repetition dominated | 350 | tiers: suppress 183, quarantine 167; methods: Heuristic + ML 183, Heuristic only 110, Combined tail 57; top rules: repeat_query_domain (350), repeat_query (293), confirmed_query_repetition (293) | Use as an explainable replay candidate. Quarantine lower-score cases when ML agreement is absent. |
| Supporting context plus combined tail | 77 | tiers: quarantine 77; methods: Combined tail 77; top rules: same_second_burst (74), high_volume_domain (62), heavy_device_cluster (62) | Monitor or quarantine. These are useful for trend review, not standalone suppression. |
| Other combined-tail anomaly | 1 | tiers: quarantine 1; methods: Combined tail 1; top rules: same_second_burst (1), fast_click (1) | Sample manually before taking action. |

The ML-tail population contains 2,005 events with high anomaly
scores and heuristic scores below the rule override threshold. Only the subset
that also crossed the combined-score cutoff is counted as selected traffic in
the class table. This keeps ML-only anomalies visible without describing them
as rule-derived replay evidence.

Concrete examples from the current run:

- Repetition with supporting context: `evt_147679` clicked `www.amazon.de` for query `nomnem`; combined 0.9183, rules 0.8600, ML 0.9988, tier `suppress`, method `Heuristic + ML`; rules: repeat_query_domain, repeat_query, confirmed_query_repetition, high_volume_domain, heavy_device_cluster, concentrated_ct_context, short_query.
- Compound burst/replay: `evt_097085` clicked `duckduckgo.com` for query `vielle motoneuron`; combined 0.9982, rules 1.0000, ML 0.9957, tier `suppress`, method `Heuristic + ML`; rules: repeat_query_domain, repeat_query, confirmed_query_repetition, heavy_device_cluster, same_second_burst, dense_burst_repetition_cluster, concentrated_ct_context, moderate_long_ttc.
- ML-tail multivariate anomaly (2,005 events in the wider population): `evt_082067` clicked `www.firefold.com` for query `splenocyte`; combined 0.7637, rules 0.6000, ML 0.9896, tier `quarantine`, method `ML only`.
- Repetition with timing anomaly: `evt_004943` clicked `www.amazon.ca` for query `nomnem`; combined 0.9184, rules 0.8600, ML 0.9991, tier `suppress`, method `Heuristic + ML`; rules: repeat_query_domain, repeat_query, confirmed_query_repetition, high_volume_domain, heavy_device_cluster, extreme_ttc, short_query.
- Repetition dominated: `evt_009777` clicked `www.overstock.com` for query `fuzz sulphid`; combined 0.7781, rules 0.6200, ML 0.9964, tier `suppress`, method `Heuristic + ML`; rules: repeat_query_domain, repeat_query, confirmed_query_repetition.
- Supporting context plus combined tail: `evt_089535` clicked `www.amazon.co.uk` for query `aw`; combined 0.6109, rules 0.3600, ML 0.9574, tier `quarantine`, method `Combined tail`; rules: high_volume_domain, heavy_device_cluster, same_second_burst, moderate_long_ttc, short_query.
- Other combined-tail anomaly: `evt_032590` clicked `find.gmx.com` for query `balm thyrohyal youre eight`; combined 0.5687, rules 0.3000, ML 0.9396, tier `quarantine`, method `Combined tail`; rules: same_second_burst, fast_click.

Practical filtering options for similar unlabelled datasets:

| Filter | Use | Caveat |
|---|---|---|
| Conservative suppression review: `operational_tier == 'suppress'` | Start here for the strongest operational candidates. Still requires policy approval because labels are unavailable. | Check policy, billing, and customer-impact rules before action. |
| Quarantine for manual review: `operational_tier == 'quarantine'` | Hold, sample, or delay action on suspicious traffic that is not strong enough for direct suppression. | Use sampling to estimate likely false positives before suppression. |
| Explainable replay review: `anomaly_class in repetition_with_supporting_context, compound_burst_replay, repetition_with_timing, repetition_dominated` | Focus reviewer time on repeated query/domain behaviour with clear rule evidence. | Validate repeated-pattern assumptions against campaign context. |
| ML-tail sampling: `ml_score >= 0.975 and heuristic_score < 0.62` | Sample for future feature-deviation work; do not treat as proven fraud without labels. | Needs feature-deviation review because rule evidence is below override. |

Use these filters as review controls. `suppress` is the strongest operational
tier, `quarantine` is the safer default for ambiguous or ML-only traffic, and
`monitor` keeps non-selected traffic available for drift checks and future
labels.

## 5. Recommended Business Actions

Separate prediction from action. `is_bot` is the compatibility prediction;
`operational_tier` is the safer business-control layer.

| Tier | Recommended action | Business assumption |
|---|---|---|
| `suppress` | Exclude from billing or downstream metrics after policy approval. | The organisation accepts limited review risk for high-confidence traffic. |
| `quarantine` | Hold, delay, sample, or manually review before suppression. | Ambiguous traffic should not be automatically removed. |
| `monitor` | Keep for trend monitoring and future labels. | Non-selected traffic can still help detect drift later. |

Operational split in this run:

- suppress: 1,863 events
- quarantine: 1,868 events
- monitor: 145,508 events

Use `suppress` for the strongest operational candidates after policy approval.
Use `quarantine` as the default action for ambiguous or ML-only traffic. Do not
automatically block traffic solely because it is in the ML tail.

Filtering options are in Section 4. They are review controls for similar
unlabelled datasets, not ground-truth fraud rules.

## 6. Probability Perspective & Risk Assessment

The current operational confidence estimate is 74.49%. This is not
measured precision because the dataset has no ground-truth labels.

Confidence is higher when independent signals agree: for example, when a
strong repeated query/domain rule hit also lands in the upper anomaly-model
tail. Confidence is lower for ML-only events because anomaly detection can also
surface legitimate edge cases such as unusual campaigns, regional spikes,
testing traffic, or rare but valid user behaviour.

The estimate is based on rule/model agreement, strength of rule evidence,
operational tier, selected anomaly class, and the known absence of labels. It
should guide review priority, not replace labelled validation or policy
approval.

| Risk area | Likelihood | Impact | Business interpretation |
|---|---|---|---|
| Suppress-tier bot traffic remains untreated | High | Medium to High | Strong signals would continue to distort billing, reporting, and optimisation unless policy-approved action is taken. |
| Quarantine-tier traffic is suppressed too aggressively | Medium | Medium | Ambiguous or ML-only events may include legitimate edge cases, so sampling and review should precede irreversible action. |
| Model drift in future batches | Medium | Medium | Traffic mix, campaigns, browsers, and geographies can change; thresholds should be monitored rather than assumed permanent. |
| Treating anomaly scores as proof of fraud | Low if governed | High | The current scores are evidence for review, not legal or contractual proof. Misuse would create customer and reputational risk. |

If no action is taken, the likely exposure is continued metric inflation and
avoidable investigation effort. The current evidence does not quantify direct
financial loss, but it does show a reviewable population large enough to affect
performance reporting if left unmanaged.

## 7. Generalisation, Trade-Offs, And Limitations

The approach should generalise to bot traffic that is repetitive,
mechanically timed, or concentrated in narrow device and query patterns. It may
miss bots that deliberately randomise timing, distribute activity across many
query/domain pairs, or closely imitate human behaviour.

The main trade-off is explainability versus coverage. Rules are easier to
defend but can miss novel patterns. The anomaly model broadens coverage but
needs careful interpretation because it finds unusual events, not necessarily
fraudulent events.

Known limitations:

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

Material changes in geography, campaign volume, inventory, browser mix, or
feature extraction should trigger fresh threshold review.

## 8. Future Work

The next useful improvements are:

1. Labelled validation from manual review, chargebacks, or confirmed invalid
   traffic feedback.
2. Feature-deviation explanations for ML-tail events.
3. Historical drift monitoring for flagged rates and score distributions.
4. Campaign-level or inventory-level normalisation if metadata becomes
   available.
5. Calibrated probabilities once trusted labels exist.
6. A feedback loop from reviewed `suppress` and `quarantine` decisions.

## Appendix A: Metric Definitions

| Metric | Definition |
|---|---|
| `is_bot` | Required binary prediction in `submission.tsv`; `1` means selected as likely bot traffic. |
| `heuristic_score` | Score from transparent rules such as repetition, timing, and burst checks. |
| `ml_score` | Anomaly score from the Extended Isolation Forest feature model. |
| `combined_score` | Weighted blend of rule and ML evidence. |
| Combined-score cutoff | Run-specific threshold used to select the top anomaly population. |
| Heuristic override | Rule-score threshold that selects strong explainable rule hits. |
| Operational tier | Business action layer: `suppress`, `quarantine`, or `monitor`. |
| Operational confidence estimate | Signal-based estimate from method agreement; not measured precision. |
| Method bucket | Agreement category showing whether rules, ML, both, or neither were strong. |
| Anomaly class | Human-readable grouping of selected events by dominant evidence pattern. |

## Appendix B: Feature Definitions

| Feature | Meaning |
|---|---|
| `log_domain_count` | Log-scaled frequency of the clicked domain. |
| `log_query_count` | Log-scaled frequency of the search query. |
| `log_query_domain_count` | Log-scaled frequency of the query/domain pair. |
| `log_device_count` | Log-scaled frequency of the region/browser/OS cluster. |
| `log_country_count` | Log-scaled frequency of `ct`, the country-like URL parameter. |
| `log_same_second_count` | Log-scaled number of clicks sharing the same second. |
| `log_ttc_count` | Log-scaled reuse count for exact time-to-click values. |
| `log_kp_count` | Log-scaled frequency of the `kp` URL parameter value. |
| `log_sld_count` | Log-scaled frequency of the `sld` URL parameter value. |
| `kp` | Raw `kp` URL parameter retained for audit; excluded from ML features. |
| `sld` | Raw `sld` URL parameter retained for audit; excluded from ML features. |
| `hour` | Event hour extracted from the timestamp. |
| `log_ttc_seconds` | Log-scaled time-to-click duration. |
| `is_sub_200ms_click` | Flag for click timing below a plausible human reaction threshold. |
| `log_pseudo_session_10s_click_count` | Log-scaled burst density within pseudo-session-style groups. |
| `query_entropy` | Text randomness measure for the search query. |

## Appendix C: Model Definition

Extended Isolation Forest is an unsupervised anomaly-detection model. It does
not learn from known bot labels. Instead, it asks which events are easier to
isolate from the rest of the batch using random feature-space splits.

In plain English, events that look very different from the main population tend
to be isolated more quickly and receive higher anomaly scores. This is useful
for an unlabelled dataset, but it also means the model detects unusual
behaviour rather than confirmed fraud. The model output is strongest when it
agrees with transparent rule evidence and weakest when it stands alone without
feature-deviation review.

Methods evaluated but not selected:

| Method | Why it was not preferred |
|---|---|
| K-means clustering | K-means is useful when compact, roughly spherical clusters are expected. Bot-click traffic is sparse, skewed, and heavy-tailed, so forcing every event into a cluster makes the output harder to explain and less reliable for rare anomalies. |
| Standard Isolation Forest | Standard Isolation Forest is a strong baseline, but its axis-aligned splits can be less expressive when anomalous behaviour is a combination of several weak signals. Extended Isolation Forest uses random hyperplane splits, which better matches the multivariate footprint of repeated, bursty, and concentrated traffic. |
| DBSCAN | DBSCAN can find dense groups and outliers, but it is sensitive to distance scaling and neighbourhood parameters. With mixed count, timing, entropy, and categorical-frequency features, it was less stable as a default production choice for repeatable local batch runs. |

Extended Isolation Forest was preferred because it preserves the main advantage
of unsupervised Isolation Forest-style detection while giving a more flexible
view of multivariate anomalies. It also fits the operating constraints of this
project: no labels, a local batch pipeline, explainable feature engineering,
and a need to combine model scores with transparent rules.

## Appendix D: Thresholds And Decision Logic

An event is selected as a bot when either condition is true:

```text
combined_score > 0.568053
or heuristic_score >= 0.62
```

The combined-score threshold is the run-specific 97.5th-percentile cutoff. It
keeps the selected volume stable for an unlabelled dataset while letting the ML
model influence borderline cases.

The heuristic override protects high-confidence, explainable rule hits. For
example, a strongly repeated query/domain pattern with mechanical timing should
not be missed only because the anomaly ranking moved after a feature change.

Adaptive heuristic thresholds used in this run:

| Rule | Computed threshold | Basis |
|---|---:|---|
| Concentrated ct context (`concentrated_ct_context`) | 29013 | 99th-percentile threshold, floor 1000, rate guardrail 14923 |
| Heavy region/browser/OS cluster (`heavy_device_cluster`) | 43674 | 99th-percentile threshold, floor 600, rate guardrail 5223 |
| High-volume clicked domain (`high_volume_domain`) | 2238 | 99th-percentile threshold, floor 200, rate guardrail 2238 |
| Repeated query (`repeat_query`) | 149 | 99th-percentile threshold, floor 12, rate guardrail 149 |
| Repeated query/domain pair (`repeat_query_domain`) | 37 | 99th-percentile threshold, floor 4, rate guardrail 37 |
| Reused exact time-to-click (`reused_ttc`) | 40 | 99th-percentile threshold, floor 40 |
| Same-second click burst (`same_second_burst`) | 6 | 99th-percentile threshold, floor 4 |

In this run:

- heuristic-only flag rate: 1.36%
- ML agreement-tail reference rate: 2.50%
- operational confidence estimate: 74.49%
