# Bot Hunter Analysis Report

## 1. Project context

Bot Hunter is a review-first bot detection pipeline. It keeps the rules layer readable, lets the anomaly model add statistical coverage, and treats all score outputs as unlabeled operational evidence rather than measured ground truth. That matters because the dataset does not include labels, so precision is reported as an operational confidence estimate instead of a calibrated metric.

## 2. Classifiers

The application implements two classifiers. The first is a rules-based classifier that scores repeated query/domain pairs, repeated queries, confirmed query repetition, high-volume domains, dense region/browser/OS clusters, exact time-to-click reuse, same-second bursts, dense burst repetition clusters, implausibly fast clicks, moderately long time-to-click values, extreme time-to-click values, and regular pseudo-session inter-arrival timing. Exact time-to-click reuse is selectively calibrated with a 99th-percentile reuse-count cutoff and an absolute floor so the rule can adapt to timer reuse patterns without letting low-count coincidences fire. Confirmed query repetition is intentionally conjunctive: it requires the query/domain pair to repeat and the query to be widely repeated. Dense burst repetition is also conjunctive: it requires a heavy region/browser/OS cluster, at least five same-second clicks, and a repeated query or query/domain pattern on the same event. The second classifier is an Extended Isolation Forest anomaly model over 15 ML features selected from 15 engineered behavioral features, including region/browser/OS frequency, global `ct` country frequency, explicit mechanical features for sub-200ms clicks, local burst density, and query entropy. Query length, query word count, and uncertain URL flags are no longer engineered features. High-volume domain frequency and global country frequency remain available but are down-weighted to 0.50 and 0.50, respectively, in the standardized ML matrix. Repetition and timing features that can dominate standalone EIF tail evidence are also down-weighted to 0.50: query/domain repetition, query repetition, log-scaled time-to-click magnitude, sub-200ms click flags, and query entropy. Events isolated quickly by random hyperplane splits receive higher anomaly scores. EIF is the only production anomaly model; alternate ML backends and supervised pilots have been removed.

## 3. Anomalies found

The run analyzed 149,239 events and flagged 3,732 events as bots (2.50%). The strongest explainable patterns were:

- repeated query: 3,427 events
- repeated query/domain pair: 2,099 events
- confirmed query repetition: 2,023 events
- same-second click burst: 1,994 events
- very short query: 1,828 events
- heavy region/browser/os cluster: 1,784 events
- high-volume clicked domain: 1,773 events
- dense burst repetition cluster: 517 events
- moderately long time-to-click: 461 events
- extreme time-to-click: 176 events

The dashboard exposes these same signals with sample events so a business user can inspect the likely automated behavior without reading model internals.

## 4. Filtering options

Practical filters for similar datasets include dropping or quarantining traffic from repeated query/domain pairs, repeated exact `ttc` values, dense same-second bursts, and events above the combined anomaly threshold. Bot Hunter assigns operational tiers without changing the binary `is_bot` prediction:

- suppress: 1,728 events
- quarantine: 2,004 events
- monitor: 145,507 events

Use `suppress` for high-confidence bot traffic after policy approval, `quarantine` for bot traffic that should be held for review, and `monitor` for traffic that is not selected for bot action but should remain available for trend analysis and future labels.

## 5. Method disagreement

The combined score uses a 0.58/0.42 heuristic/ML split because the rules layer is more directly explainable and should remain slightly dominant, while ML still has enough weight to move borderline cases and catch multivariate oddities. The thresholds are conservative guardrails, not learned cutoffs. The same 0.62 heuristic and 0.995 EIF rank-tail agreement thresholds used in suppression are also reported separately so blind spots are visible. The EIF agreement threshold is intentionally narrow: this run reports 590 `ML only` events in the extreme anomaly tail, while broad top-decile anomaly ranks previously created too many standalone ML entries without enough explainable support. The method-disagreement table is diagnostic; it does not expose another production model path.

- Heuristic + ML: 157 events
- Heuristic only: 1,913 events
- ML only: 590 events
- Neither strong: 146,579 events

## 6. Threshold rationale

The binary decision uses the stronger of two conservative gates: the event is selected when its combined score is at or above the run-specific 97.5th-percentile cutoff (0.598913 in this run), or when the rules-only heuristic score reaches 0.62 on its own. The percentile cutoff keeps the submitted bot volume stable for an unlabeled dataset while still letting the anomaly model influence which borderline events enter the review set. The heuristic override prevents high-confidence, explainable rule hits from being missed just because the anomaly ranking moved around after a feature or backend change.

The threshold is not a learned probability boundary. It is an operational cutoff for a review-first workflow where false positives and false negatives are treated as roughly comparable. In this run, the heuristic-only flag rate was 1.39%, while the EIF agreement-tail reference rate was 0.50%; those rates are reported separately so reviewers can see how much each method contributes before the combined decision is applied.

## 7. Rationale and generalization

The heuristic model is transparent and easy to convert into policy. Only exact time-to-click reuse uses percentile calibration because it is a global duplicate-count signal whose suspiciousness depends on the dataset's observed timer granularity and reuse distribution; the absolute floor protects against weak duplicate counts in smaller or smoother datasets. Other heuristic cutoffs remain fixed or total-rate based because they represent separate behavioral concepts. The confirmed query repetition rule reuses the repeated query/domain and repeated query thresholds and adds weight only when both fire on the same event. The dense burst repetition rule reuses those existing component thresholds and adds weight only when all three are present together, which targets many clicks from the same device cluster in the same second with repeated query patterns. The time-to-click timing bands are intentionally tiered: clicks from 0 to 250 ms are treated as implausibly fast direct evidence, clicks from 20 to 60 seconds add low-weight support for delayed or mechanical click patterns, and clicks above 120 seconds remain a separate extreme timing signal. The regular inter-arrival rule is intentionally narrow because the dataset has no explicit user or session identifier: it only compares clicks with the same region, browser, OS, query, and clicked domain, requires at least eight events, and adds low-weight supporting evidence rather than a standalone bot decision. Structured rule contributions include `threshold_mode`, with fixed rules reported as `absolute` and adaptive exact-ttc reuse reported as `adaptive_percentile` when present. The Extended Isolation Forest model catches multivariate oddities that a small rule set may miss. Both should generalize when bot traffic is repetitive or mechanically timed, but they may miss human-like bots and may over-flag legitimate campaigns that naturally produce high repetition. The thresholds should be recalibrated when traffic mix, geography, or ad inventory changes materially.

## 8. Probability assessment

The estimated probability that a flagged event is fraudulent is 60%. This is not label-calibrated precision; it is a reasoned estimate based on agreement between independent signals. Events flagged by both the heuristic model and the upper tail of the ML anomaly score are more likely to be fraudulent than events flagged by only one weak signal. The report therefore treats probability as an operational confidence estimate, not a measured ground truth metric.

## 9. Known limitations

- The dataset has no ground-truth bot labels, so Bot Hunter cannot report measured precision, recall, or calibration.
- The rules intentionally favor interpretable repetition and timing signals. Human-like automation, slow distributed bot traffic, or attacks spread across many query/domain combinations may be under-detected.
- Legitimate campaigns can create high repetition, dense device clusters, or synchronized bursts. The suppress tier should therefore be policy-approved and periodically sampled.
- The regular inter-arrival rule uses narrow pseudo-session groups because there is no user or session identifier. It is supporting evidence rather than proof of automation.
- The anomaly score is relative to the current traffic mix. Material changes in geography, inventory, campaign volume, browser mix, or feature extraction should trigger a fresh threshold and review calibration.

## 10. Recommended actions

Assuming false positives and false negatives are roughly equal in cost, the submitted binary prediction uses the combined score threshold rather than only the highest-confidence intersection. For business action, use three tiers: suppress bot events with the strongest combined, heuristic, or heuristic/ML agreement signals; quarantine the remaining bot events for review; and monitor traffic that is not selected for bot action while retaining it for drift checks and future labels.

## 11. Future work

With more time, I would add labeled validation data, campaign-level normalization, browser/user-agent fingerprinting if available, time-series burst detection by inventory beyond the current pseudo-session burst feature, calibrated probabilities, and a feedback loop from manual review decisions.

## 12. Submission and decision summary

The repository includes `submission.tsv` with `event_id`, `is_bot`, and `operational_tier`, preserving the final binary prediction while adding a workflow tier. This run selected 3,732 of 149,239 events as likely bots (2.50%). The operational split is 1,728 suppress, 2,004 quarantine, and 145,507 monitor events.

Use the binary `is_bot` field as the compatibility output for downstream systems. Use `operational_tier` to decide handling: suppress high-confidence bot traffic after policy approval, quarantine lower-confidence bot traffic for review or delayed action, and monitor the remaining traffic for drift checks and future labels. The report and dashboard should be read as review aids, not as proof of fraud for every individual event.
