# Bot Hunter Analysis Report

## 1. Classifiers

The application implements two classifiers. The first is a rules-based classifier that scores repeated query/domain pairs, repeated queries, high-volume domains, dense region/browser/OS clusters, exact time-to-click reuse, same-second bursts, and implausibly fast clicks. The second is an unsupervised k-means anomaly model over standardized behavioral features. Events far from their closest centroid receive higher anomaly scores.

## 2. Anomalies found

The run analyzed 149,239 events and flagged 3,781 events as bots (2.53%). The strongest explainable patterns were:

- repeated query: 3,583 events
- very short query: 2,089 events
- repeated query/domain pair: 2,015 events
- same-second click burst: 1,952 events
- heavy region/browser/os cluster: 1,889 events
- high-volume clicked domain: 1,661 events
- extreme time-to-click: 167 events
- implausibly fast click: 27 events

The dashboard exposes these same signals with sample events so a business user can inspect the likely automated behavior without reading model internals.

## 3. Filtering options

Practical filters for similar datasets include dropping or quarantining traffic from repeated query/domain pairs, repeated exact `ttc` values, dense same-second bursts, and events above the combined anomaly threshold. For ad-billing workflows, the safest starting point is to quarantine high-confidence bot traffic for review, then move to automatic suppression once performance is validated against labeled outcomes or chargeback evidence.

## 4. Rationale and generalization

The heuristic model is transparent and easy to convert into policy. The k-means model catches multivariate oddities that a small rule set may miss. Both should generalize when bot traffic is repetitive or mechanically timed, but they may miss human-like bots and may over-flag legitimate campaigns that naturally produce high repetition. The thresholds should be recalibrated when traffic mix, geography, or ad inventory changes materially.

## 5. Probability assessment

The estimated probability that a flagged event is fraudulent is 69%. This is not label-calibrated precision; it is a reasoned estimate based on agreement between independent signals. Events flagged by both the heuristic model and the upper tail of the ML anomaly score are more likely to be fraudulent than events flagged by only one weak signal. The report therefore treats probability as an operational confidence estimate, not a measured ground truth metric.

## 6. Recommended actions

Assuming false positives and false negatives are roughly equal in cost, the submitted binary prediction uses the combined score threshold rather than only the highest-confidence intersection. For business action, use three tiers: suppress the highest combined-score traffic, quarantine medium-confidence traffic for review, and monitor low-confidence anomalies until labels are available.

## 7. Future work

With more time, I would add labeled validation data, campaign-level normalization, browser/user-agent fingerprinting if available, time-series burst detection by inventory, calibrated probabilities, and a feedback loop from manual review decisions.

## 8. Submission

The repository includes `submission.tsv` with `event_id` and `is_bot`, using the final binary prediction.

```json
{
  "input_path": "data/bot-hunter-dataset.tsv",
  "total_events": 149239,
  "bot_events": 3781,
  "bot_rate": 0.02533520058429767,
  "threshold": 0.5833619587504523,
  "heuristic_flag_rate": 0.006794470614249626,
  "ml_tail_rate": 0.015002780774462439,
  "estimated_precision": 0.6924702459666754,
  "ml_backend": "kmeans",
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
  "top_reasons": [
    [
      "repeated query",
      3583
    ],
    [
      "very short query",
      2089
    ],
    [
      "repeated query/domain pair",
      2015
    ],
    [
      "same-second click burst",
      1952
    ],
    [
      "heavy region/browser/os cluster",
      1889
    ],
    [
      "high-volume clicked domain",
      1661
    ],
    [
      "extreme time-to-click",
      167
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
  "bot_regions": [
    [
      "Earth",
      1817
    ],
    [
      "Mars",
      1772
    ],
    [
      "Mercury",
      56
    ],
    [
      "Venus",
      52
    ],
    [
      "Jupiter",
      44
    ],
    [
      "Saturn",
      40
    ]
  ]
}
```
