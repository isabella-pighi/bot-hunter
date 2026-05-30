# Bot Hunter Report Template

Use this template whenever the team generates or updates the Bot Hunter
analysis report. It is written for a wide technical audience: engineers,
product reviewers, analysts, and business stakeholders who need to understand
the outcome without being fluent in data science.

The report should be narrative first and statistical second. Explain what the
numbers mean, why the method was chosen, and how the results should be used.
Do not present anomaly scores as proof of fraud. The current dataset is
unlabelled, so probability statements are operational confidence estimates.

## Required Report Structure

### 1. Executive Summary & Problem Statement

State the business problem before the method. The opening must be suitable for
senior stakeholders: context first, business impact second, and analytical
caveat third.

Suggested wording:

> Bot Hunter analyses fictitious ad-click traffic to identify events that look
> more like automated bot activity than legitimate user behaviour. Invalid
> clicks can inflate campaign metrics, distort billing, reduce trust in
> performance reporting, and consume operational time that should be spent on
> genuine customer outcomes.

Include:

- the input data shape and source file
- the required output file, `submission.tsv`
- the fact that labels are unavailable
- the implication: no measured precision, recall, or calibrated fraud
  probability can be claimed
- the expected business impact: cost, revenue assurance, reputation,
  operational efficiency, and campaign optimisation

### 2. Methodology & Rationale

Explain the approach in plain English before giving formulas.

Required narrative:

- Bot Hunter uses two classifiers because each covers a different risk.
- The rules classifier catches patterns that are easy to explain and audit.
- The anomaly model catches unusual combinations that fixed rules may miss.
- The final score blends both views, but rules are weighted slightly higher
  because they are more directly explainable.
- The combined design is stronger than a single rule because adversarial
  traffic can avoid one obvious threshold while still leaving a broader
  footprint across timing, repetition, domains, and device-like context.

Current method summary:

| Component | Current choice | Why this choice was made |
|---|---|---|
| Rules classifier | Weighted heuristic rules | Transparent, auditable, and suitable for explaining repeated or mechanical click patterns. |
| ML classifier | Extended Isolation Forest | Works without labels and can detect unusual combinations across engineered features. |
| Score blend | `0.58 * heuristic_score + 0.42 * ml_score` | Keeps explainable rule evidence dominant while still using the anomaly model. |
| Main cutoff | 97.5th percentile combined-score threshold | Keeps the selected population stable for an unlabelled batch. |
| Override | `heuristic_score >= 0.62` | Protects high-confidence rule evidence from being missed by model ranking shifts. |

Include the reasons behind feature choices:

- Raw URLs are not model-ready; the query string is converted into behavioural
  features.
- Count features are log-transformed because click-log counts are heavy-tailed.
- `kp` and `sld` are treated as categorical identifiers, not ordered numeric
  measurements. The model uses `log_kp_count` and `log_sld_count` so it learns
  concentration without inventing false numeric distance between categories.
- Raw `kp` and `sld` values remain available in `artifacts/features.tsv` for
  audit, but they are excluded from `ml_feature_names`.

### 3. Core Statistical Findings

This section must be refreshed from `artifacts/summary.json` whenever the
pipeline is rerun. The current baseline findings are:

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
| Repeated query | 3,403 | The same search term appears unusually often. |
| Repeated query/domain pair | 2,086 | The same search term repeatedly clicks the same domain. |
| Confirmed query repetition | 2,023 | Query repetition is backed by additional context. |
| Very short query | 1,798 | Short terms can be legitimate, but are useful supporting evidence. |
| High-volume clicked domain | 1,732 | A domain receives unusually concentrated clicks. |
| Heavy region/browser/OS cluster | 1,168 | Traffic is concentrated in a narrow device/server footprint. |
| Concentrated `ct` context | 904 | Country-like context is concentrated with repetition and clustering. |
| Same-second click burst | 677 | Multiple clicks happen in the same second. |
| Moderately long time-to-click | 431 | Timing is unusual enough to support other evidence. |
| Dense burst repetition cluster | 236 | Burstiness and repeated behaviour appear together. |

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
| Repetition with supporting context | 1,877 | Review as replay-like traffic; suppress only in the suppress tier. |
| Compound burst/replay | 562 | Treat suppress-tier cases as strong candidates; quarantine the rest. |
| ML-tail multivariate anomaly | 509 | Quarantine or sample; do not suppress without feature-deviation review. |
| Repetition with timing anomaly | 355 | Prioritise suppress-tier and strong timing evidence. |
| Repetition dominated | 350 | Use as explainable replay evidence; sample lower-score cases. |
| Supporting context plus combined tail | 77 | Monitor or quarantine; not standalone suppression evidence. |
| Other combined-tail anomaly | 1 | Sample manually. |

### 4. Anomaly Explanations & Practical Guidance

Describe the patterns as behaviours, not just model outputs.

Required narrative points:

- Repetition is suspicious when the same query, clicked domain, and device-like
  context appear together.
- Timing matters because some click patterns are difficult for humans to
  produce consistently.
- Country-like `ct` concentration is only supporting evidence. It should not be
  treated as a country-blocking rule.
- ML-only events are unusual, but unusual does not automatically mean
  fraudulent.

Include at least one concrete example from `artifacts/sample_events.json` for
each major anomaly class. Each example should include:

- `event_id`
- domain and query
- operational tier
- method bucket
- combined, heuristic, and ML scores
- short explanation of the rule or feature evidence

### 5. Recommended Business Actions

Separate prediction from action.

| Tier | Recommended action | Business assumption |
|---|---|---|
| `suppress` | Exclude from billing or downstream metrics after policy approval. | The organisation accepts limited review risk for high-confidence traffic. |
| `quarantine` | Hold, delay, sample, or manually review before suppression. | Ambiguous traffic should not be automatically removed. |
| `monitor` | Keep for trend monitoring and future labels. | Non-selected traffic can still help detect drift later. |

State the recommendation:

> Use `suppress` for the strongest operational candidates after policy approval.
> Use `quarantine` as the default action for ambiguous or ML-only traffic. Do
> not automatically block traffic solely because it is in the ML tail.

### 6. Probability Perspective & Risk Assessment

Required narrative:

- The current operational confidence estimate is 74.49%.
- This is not measured precision because the dataset has no ground-truth labels.
- Confidence is higher when independent signals agree.
- Confidence is lower for ML-only events because anomaly detection can surface
  legitimate edge cases.

Explain the basis:

- rule/model agreement
- strength of rule evidence
- score tier
- selected class
- known absence of labels

Include a business risk table with:

- risk area
- likelihood
- impact
- plain-English business interpretation
- likely exposure if no action is taken

### 7. Generalisation, Trade-Offs, And Limitations

Include:

- where the approach should generalise well
- where it may fail
- what assumptions could break
- why labels are still needed

Suggested wording:

> The approach should generalise to bot traffic that is repetitive,
> mechanically timed, or concentrated in narrow device and query patterns. It
> may miss bots that deliberately randomise timing, distribute activity across
> many query/domain pairs, or closely imitate human behaviour.

Required limitations:

- no ground-truth labels
- no measured precision or recall
- batch-relative anomaly scores
- legitimate campaigns can produce repetition and regional concentration
- pseudo-session logic is an approximation because explicit session IDs are
  unavailable

### 8. Future Work

Keep this section specific and prioritised.

Recommended future work:

1. Labelled validation from manual review or confirmed invalid-traffic data.
2. Feature-deviation explanations for ML-tail events.
3. Historical drift monitoring for flagged rates and score distributions.
4. Campaign or inventory normalisation if metadata becomes available.
5. Calibrated probabilities once trusted labels exist.

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
| Estimated precision | Operational confidence estimate based on signal agreement; not measured precision. |
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
| `hour` | Event hour extracted from the timestamp. |
| `log_ttc_seconds` | Log-scaled time-to-click duration. |
| `is_sub_200ms_click` | Flag for click timing below a plausible human reaction threshold. |
| `log_pseudo_session_10s_click_count` | Log-scaled burst density within pseudo-session-style groups. |
| `query_entropy` | Text randomness measure for the search query. |

## Appendix C: Model Definition

Extended Isolation Forest is an unsupervised anomaly-detection model. It does
not learn from known bot labels. Instead, it asks which events are easier to
isolate from the rest of the batch using random feature-space splits.

Plain-English explanation:

> If an event has an unusual combination of feature values, the model can
> separate it from ordinary traffic quickly. That event receives a higher
> anomaly score. A high anomaly score means "unusual compared with this batch",
> not "proven fraudulent".

Why it was chosen:

- it works without labelled examples
- it handles several behavioural features at once
- it is suitable for local batch processing
- it complements explainable rules by finding unusual combinations

Main shortcoming:

- without labels, it cannot prove fraud or produce calibrated fraud
  probabilities on its own

## Appendix D: Report Quality Checklist

Before handoff, the UX coder and reviewer must confirm:

- the report starts with the executive summary and problem statement
- methodology and rationale appear before detailed results
- all statistical findings match the latest `artifacts/summary.json`
- examples come from current artefacts, not stale notes
- probability wording says "operational confidence estimate" unless labels
  exist
- appendices define metrics, features, and model terminology
- language is clear British English for a wide technical audience
- tables or visual aids clarify the story rather than adding decoration
- recommendations separate `is_bot` prediction from business action
