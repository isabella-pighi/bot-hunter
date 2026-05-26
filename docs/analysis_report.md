# Bot Hunter Analysis Report

## 1. Project context

Bot Hunter is a review-first bot detection pipeline. It keeps the rules layer readable, lets the anomaly model add statistical coverage, and treats all score outputs as unlabeled operational evidence rather than measured ground truth. That matters because the dataset does not include labels, so precision is reported as an operational confidence estimate instead of a calibrated metric.

## 2. Classifiers

The application implements two classifiers. The first is a rules-based classifier that scores repeated query/domain pairs, repeated queries, high-volume domains, dense region/browser/OS clusters, exact time-to-click reuse, same-second bursts, implausibly fast clicks, and regular pseudo-session inter-arrival timing. The second is an Isolation Forest anomaly model over standardized behavioral features. Events that isolate unusually quickly in the fitted forest receive higher anomaly scores.

## 3. Methods evaluated but not included

Bot Hunter also evaluated HDBSCAN, a shallow autoencoder, and a small VAE as optional anomaly backends in prior benchmark work. They were not promoted because they did not improve reviewer utility enough to justify their runtime, memory, or complexity costs. HDBSCAN was much slower than the current anomaly path on the full dataset, while the neural models used more memory and did not produce clearer explanations than Isolation Forest. The production ML path therefore remains Isolation Forest when scikit-learn is available, with k-means as the lightweight fallback.

## 4. Anomalies found

The run analyzed 149,239 events and flagged 3,732 events as bots (2.50%). The strongest explainable patterns were:

- repeated query: 3,324 events
- repeated query/domain pair: 2,065 events
- high-volume clicked domain: 1,902 events
- same-second click burst: 1,894 events
- very short query: 1,861 events
- heavy region/browser/os cluster: 1,733 events
- extreme time-to-click: 278 events
- implausibly fast click: 27 events
- regular inter-arrival timing: 11 events

The dashboard exposes these same signals with sample events so a business user can inspect the likely automated behavior without reading model internals.

## 5. Filtering options

Practical filters for similar datasets include dropping or quarantining traffic from repeated query/domain pairs, repeated exact `ttc` values, dense same-second bursts, and events above the combined anomaly threshold. Bot Hunter assigns operational tiers without changing the binary `is_bot` prediction:

- suppress: 981 events
- quarantine: 2,751 events
- monitor: 145,507 events

Use `suppress` for high-confidence bot traffic after policy approval, `quarantine` for bot traffic that should be held for review, and `monitor` for traffic that is not selected for bot action but should remain available for trend analysis and future labels.

## 6. Method disagreement

The combined score uses a 0.58/0.42 heuristic/ML split because the rules layer is more directly explainable and should remain slightly dominant, while ML still has enough weight to move borderline cases and catch multivariate oddities. The thresholds are conservative guardrails, not learned cutoffs. The same 0.62 heuristic and 0.90 ML agreement thresholds used in suppression are also reported separately so blind spots are visible:

- Heuristic + ML: 966 events
- Heuristic only: 48 events
- ML only: 13,958 events
- Neither strong: 134,267 events

## 7. Rationale and generalization

The heuristic model is transparent and easy to convert into policy. The regular inter-arrival rule is intentionally narrow because the dataset has no explicit user or session identifier: it only compares clicks with the same region, browser, OS, query, and clicked domain, requires at least eight events, and adds low-weight supporting evidence rather than a standalone bot decision. The Isolation Forest model catches multivariate oddities that a small rule set may miss. Both should generalize when bot traffic is repetitive or mechanically timed, but they may miss human-like bots and may over-flag legitimate campaigns that naturally produce high repetition. The thresholds should be recalibrated when traffic mix, geography, or ad inventory changes materially.

## 8. Probability assessment

The estimated probability that a flagged event is fraudulent is 77%. This is not label-calibrated precision; it is a reasoned estimate based on agreement between independent signals. Events flagged by both the heuristic model and the upper tail of the ML anomaly score are more likely to be fraudulent than events flagged by only one weak signal. The report therefore treats probability as an operational confidence estimate, not a measured ground truth metric.

## 9. Recommended actions

Assuming false positives and false negatives are roughly equal in cost, the submitted binary prediction uses the combined score threshold rather than only the highest-confidence intersection. For business action, use three tiers: suppress bot events with the strongest combined, heuristic, or heuristic/ML agreement signals; quarantine the remaining bot events for review; and monitor traffic that is not selected for bot action while retaining it for drift checks and future labels.

## 10. Future work

With more time, I would add labeled validation data, campaign-level normalization, browser/user-agent fingerprinting if available, time-series burst detection by inventory, calibrated probabilities, and a feedback loop from manual review decisions.

## 11. Submission

The repository includes `submission.tsv` with `event_id`, `is_bot`, and `operational_tier`, preserving the final binary prediction while adding a workflow tier.
