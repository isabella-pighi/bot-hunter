# Bot Hunter Analysis Report

## 1. Executive Summary

Bot Hunter analysed 149,239 click events.
It selected 3,731 as likely bot traffic, which is 2.50% of the run.

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
- Machine-learning classifier: an Extended Isolation Forest anomaly model over 14 engineered behavioural features.

The final score is a weighted blend:

```text
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

The rules layer is weighted slightly higher because it is easier to explain and
audit. The anomaly model still matters because it can identify unusual
combinations that a small rule set may not capture.

## 3. Main Results

The strongest explainable patterns in this run were:

- repeated query: 3,403 events
- repeated query/domain pair: 2,086 events
- confirmed query repetition: 2,023 events
- very short query: 1,798 events
- high-volume clicked domain: 1,732 events
- heavy region/browser/OS cluster: 1,168 events
- concentrated ct context: 904 events
- same-second click burst: 677 events
- moderately long time-to-click: 431 events
- dense burst repetition cluster: 236 events

Example interpretation: a single repeated query is not enough to prove bot
traffic. It becomes more concerning when it appears with a repeated clicked
domain, dense same-second activity, reused time-to-click values, or a narrow
region/browser/OS footprint.

The new concentrated `ct` rule is deliberately cautious. It adds low-weight
support only when country-like concentration appears with repeated query
behaviour and either a heavy device cluster or a same-second burst. Country-like
concentration alone is not treated as bot evidence because legitimate campaigns
can be country-specific.

## 4. Operational Anomaly Classes

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

## 5. Classifier Details

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

`kp` and `sld` are treated as categorical-style assumptions rather than true
continuous measurements because their observed cardinality is very low. Raw
`kp` and `sld` values remain in the feature artefact for audit, but the anomaly
model uses `log_kp_count` and `log_sld_count` instead of raw numeric distances.
The raw values are excluded from `ml_feature_names`.

Threshold-change validation used the regenerated `submission.tsv`,
`artifacts/summary.json`, `artifacts/features.tsv`,
`artifacts/sample_events.json`, and report files under `docs`. Targeted
heuristic, pipeline, and dashboard tests passed (`uv run pytest
tests/test_heuristics.py tests/test_pipeline.py tests/test_web.py`, 42 passed),
the full test suite passed (`uv run pytest`, 49 passed), and Black passed for
the touched Python files with the existing Python 3.12 target-version warning.
Each generated report reflects the current run's artefacts; fixed before/after
comparison metrics are kept in the static README task history rather than
repeated in this template.

## 6. Thresholds And Decision Logic

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
- operational confidence estimate: 74%

## 7. Method Agreement And Disagreement

Agreement between the rules layer and the anomaly model is useful review
evidence. It is not statistical validation, because there are no labels.

At the ML agreement threshold, this run has 1,726 `Heuristic + ML` events and 2,005 `ML only` events.

Method disagreement (`ml_score >= 0.975`):

- Heuristic + ML: 1,726 events
- Heuristic only: 311 events
- ML only: 2,005 events
- Neither strong: 145,197 events

Example interpretation:

- `Heuristic + ML` events are usually the strongest review candidates.
- `Heuristic only` events may be explainable rule hits that are not unusual in
  the wider feature space.
- `ML only` events may contain multivariate anomalies, but they need careful
  review because unusual legitimate behaviour can also be anomalous.

## 8. Operational Actions

Bot Hunter separates prediction from action by assigning operational tiers:

- suppress: 1,863 events
- quarantine: 1,868 events
- monitor: 145,508 events

Recommended use:

- `suppress`: high-confidence traffic that can be excluded from billing or
  downstream metrics after policy approval.
- `quarantine`: suspicious traffic that should be reviewed, sampled, or delayed
  before suppression.
- `monitor`: traffic not selected for bot action, retained for trend analysis
  and future labels.

The binary `is_bot` field is the compatibility output. The tier is the safer
business-control layer.

## 9. Probability Perspective

The estimated probability that a flagged event is fraudulent is 74%. This is an operational estimate based on signal agreement, not a calibrated probability.

The estimate is stronger when independent signals agree. For example, a click
with repeated query/domain replay, same-second burst evidence, and an upper-tail
ML score is more likely to be fraudulent than a click selected only because one
feature is unusual.

The estimate is weaker for isolated ML-only events, because unsupervised anomaly
detection can also surface legitimate edge cases such as unusual campaigns,
regional spikes, testing traffic, or rare but valid user behaviour.

## 10. Generalisation And Trade-Offs

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

## 11. Known Limitations

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

## 12. Future Work

The next useful improvements are:

- labelled validation from manual review, chargebacks, or confirmed invalid
  traffic feedback
- campaign-level or inventory-level normalisation
- stronger browser or user-agent fingerprinting if those fields become
  available
- historical drift monitoring for score distributions and flagged rates
- calibrated probabilities once trusted labels exist
- a feedback loop from reviewed `suppress` and `quarantine` decisions

## 13. Submission Summary

The repository includes `submission.tsv` with `event_id`, `is_bot`, and
`operational_tier`.

This run selected 3,731 of 149,239 events as likely bots.
That is 2.50% of the run.

Operational split:

- suppress: 1,863
- quarantine: 1,868
- monitor: 145,508

Use the report and dashboard as review aids. They explain why traffic was
selected and where the evidence is strongest, but they do not replace labelled
validation or policy approval.
