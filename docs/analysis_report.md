# Bot Hunter Analysis Report

## 1. Classifiers

The application implements two classifiers. The first is a rules-based classifier that scores repeated query/domain pairs, repeated queries, high-volume domains, dense region/browser/OS clusters, exact time-to-click reuse, same-second bursts, and implausibly fast clicks. The second is an unsupervised k-means anomaly model over standardized behavioral features. Events far from their closest centroid receive higher anomaly scores.

## 2. Anomalies found

The run analyzed 149,239 events and flagged 3,732 events as bots (2.50%). The strongest explainable patterns were:

- repeated query: 3,323 events
- repeated query/domain pair: 2,065 events
- high-volume clicked domain: 1,904 events
- same-second click burst: 1,890 events
- very short query: 1,864 events
- heavy region/browser/os cluster: 1,740 events
- extreme time-to-click: 279 events
- implausibly fast click: 27 events

The dashboard exposes these same signals with sample events so a business user can inspect the likely automated behavior without reading model internals.

## 3. Filtering options

Practical filters for similar datasets include dropping or quarantining traffic from repeated query/domain pairs, repeated exact `ttc` values, dense same-second bursts, and events above the combined anomaly threshold. Bot Hunter assigns operational tiers without changing the binary `is_bot` prediction:

- suppress: 981 events
- quarantine: 2,751 events
- monitor: 145,507 events

Use `suppress` for high-confidence bot traffic after policy approval, `quarantine` for bot traffic that should be held for review, and `monitor` for traffic that is not selected for bot action but should remain available for trend analysis and future labels.

## 4. Rationale and generalization

The heuristic model is transparent and easy to convert into policy. The k-means model catches multivariate oddities that a small rule set may miss. Both should generalize when bot traffic is repetitive or mechanically timed, but they may miss human-like bots and may over-flag legitimate campaigns that naturally produce high repetition. The thresholds should be recalibrated when traffic mix, geography, or ad inventory changes materially.

## 5. Probability assessment

The estimated probability that a flagged event is fraudulent is 77%. This is not label-calibrated precision; it is a reasoned estimate based on agreement between independent signals. Events flagged by both the heuristic model and the upper tail of the ML anomaly score are more likely to be fraudulent than events flagged by only one weak signal. The report therefore treats probability as an operational confidence estimate, not a measured ground truth metric.

## 6. Recommended actions

Assuming false positives and false negatives are roughly equal in cost, the submitted binary prediction uses the combined score threshold rather than only the highest-confidence intersection. For business action, use three tiers: suppress bot events with the strongest combined, heuristic, or heuristic/ML agreement signals; quarantine the remaining bot events for review; and monitor traffic that is not selected for bot action while retaining it for drift checks and future labels.

## 7. Future work

With more time, I would add labeled validation data, campaign-level normalization, browser/user-agent fingerprinting if available, time-series burst detection by inventory, calibrated probabilities, and a feedback loop from manual review decisions.

## 8. Submission

The repository includes `submission.tsv` with `event_id`, `is_bot`, and `operational_tier`, preserving the final binary prediction while adding a workflow tier.

```json
{
  "input_path": "data/bot-hunter-dataset.tsv",
  "total_events": 149239,
  "bot_events": 3732,
  "bot_rate": 0.025006868177889156,
  "threshold": 0.5765429180235596,
  "heuristic_flag_rate": 0.006794470614249626,
  "ml_tail_rate": 0.015002780774462439,
  "estimated_precision": 0.7703804930332261,
  "ml_backend": "sklearn",
  "feature_artifact": "artifacts/features.tsv",
  "feature_names": [
    "log_domain_count",
    "log_query_count",
    "log_query_domain_count",
    "log_device_count",
    "log_same_second_count",
    "log_ttc_count",
    "ttc_seconds",
    "query_terms",
    "query_chars",
    "has_bkl",
    "has_om",
    "kp",
    "sld",
    "hour",
    "is_mobile_search"
  ],
  "operational_tiers": {
    "suppress": "High-confidence bot traffic suitable for automatic suppression after policy approval.",
    "quarantine": "Bot traffic that should be held for review before suppression.",
    "monitor": "Traffic not selected for bot action; keep for trend monitoring and future labels."
  },
  "tier_thresholds": {
    "suppress_combined_score": 0.8,
    "suppress_heuristic_score": 0.8,
    "suppress_agreement_heuristic_score": 0.62,
    "suppress_agreement_ml_score": 0.9,
    "quarantine": "is_bot == 1 and suppress conditions are not met",
    "monitor": "is_bot == 0"
  },
  "tier_counts": {
    "suppress": 981,
    "quarantine": 2751,
    "monitor": 145507
  },
  "top_reasons": [
    [
      "repeated query",
      3323
    ],
    [
      "repeated query/domain pair",
      2065
    ],
    [
      "high-volume clicked domain",
      1904
    ],
    [
      "same-second click burst",
      1890
    ],
    [
      "very short query",
      1864
    ],
    [
      "heavy region/browser/os cluster",
      1740
    ],
    [
      "extreme time-to-click",
      279
    ],
    [
      "implausibly fast click",
      27
    ]
  ],
  "top_domains": [
    [
      "www.amazon.de",
      5543
    ],
    [
      "www.amazon.co.uk",
      4623
    ],
    [
      "www.amazon.ca",
      4480
    ],
    [
      "www.booking.com",
      3640
    ],
    [
      "www.amazon.es",
      2230
    ],
    [
      "duckduckgo.com",
      1816
    ],
    [
      "www.amazon.fr",
      1573
    ],
    [
      "www.amazon.com",
      1550
    ],
    [
      "www.amazon.it",
      1321
    ],
    [
      "www.yidio.com",
      1301
    ],
    [
      "www.preis.de",
      911
    ],
    [
      "www.flicksmore.com",
      748
    ]
  ],
  "top_queries": [
    [
      "nomnem",
      1226
    ],
    [
      "splenocyte",
      531
    ],
    [
      "pluralizes",
      391
    ],
    [
      "neti biscot",
      316
    ],
    [
      "spurge",
      258
    ],
    [
      "solely",
      246
    ],
    [
      "gangdom",
      246
    ],
    [
      "valgoid kae",
      239
    ],
    [
      "censer amatorial callainite",
      216
    ],
    [
      "orlo pliny",
      213
    ],
    [
      "nana",
      212
    ],
    [
      "vaunt",
      212
    ]
  ],
  "bot_reg
```
