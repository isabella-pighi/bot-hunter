# Bot Hunter Roadmap

This roadmap captures the remaining work for Bot Hunter. It is written for a
wide technical audience: engineers, data scientists, product reviewers, and
stakeholders who need to understand why a change matters before deciding
whether to prioritise it.

Bot Hunter already has a working production path: it parses raw click logs,
builds behavioural features, combines rules with an Extended Isolation Forest
anomaly score, writes `submission.tsv`, and serves a local review dashboard.
The next improvements should make the system more stable across datasets, more
explainable to reviewers, and safer to use operationally.

## How To Read This Roadmap

| Priority | Meaning |
|---|---|
| P1 | Highest-value follow-up. Improves correctness, explainability, or operational safety. |
| P2 | Important but less urgent. Usually improves robustness, stability, or monitoring. |
| P3 | Optional or future-facing. Useful when more data, labels, credentials, or production context exist. |
| Done | Completed work kept here to preserve project history and design intent. |

The project uses unlabelled data. That means items involving probability,
precision, recall, or supervised learning should be treated carefully. Until
trusted labels exist, the system can estimate operational confidence, but it
cannot honestly claim measured fraud accuracy.

## P1: Make Existing Detection More Stable And Explainable

### 1. Make Heuristic Thresholds Adaptive

Current heuristic rules use fixed count cutoffs in several places. Fixed
thresholds are easy to understand, but they can be brittle when the dataset size
or traffic mix changes.

For example, a query/domain pair repeated 80 times may be unusual in a 10,000
row batch but ordinary in a 10 million row batch. A percentile-based threshold
would compare behaviour against the current population rather than treating the
same raw count as equally suspicious everywhere.

**Proposed work:**

- Convert selected fixed count thresholds to percentile-based thresholds.
- Keep the current constants as fallback guardrails.
- Record the computed thresholds in `artifacts/summary.json`.
- Show the thresholds in the report so reviewers can see why an event was
  flagged.

**Acceptance examples:**

- A small input file still runs without unstable thresholds.
- A large input file does not automatically over-flag popular queries only
  because traffic volume increased.
- The report says both the rule name and the computed threshold used in the
  run.

### 2. Separate Strong Rules From Supporting Rules

Not every suspicious signal has the same evidential strength. A sub-200 ms
click is a strong mechanical signal. A popular domain is a weaker supporting
signal because legitimate campaigns can also create high volume.

At the moment, weak signals can accumulate into a score that looks similar to a
single strong bot signal. That makes the output harder to explain and can
increase false positives.

**Proposed work:**

- Split rule contributions into high-confidence and supporting families.
- Limit how much any weak rule family can contribute on its own.
- Make rule strength visible in `sample_events.json`, the dashboard, and the
  report.

**Acceptance examples:**

- An event with only weak popularity signals is less likely to be treated like
  a high-confidence bot.
- An event with repeated query/domain replay plus impossible timing remains
  high risk.
- Reviewers can see whether a score came from one strong rule or many weak
  supporting rules.

### 3. Add Local Domain Reputation Signals

Behavioural detection is the core of Bot Hunter, but domain reputation can add
useful context. The safest first step is a local, versioned blocklist rather
than live provider lookups.

For example, if a clicked domain appears on a known malware or botnet command
and control list, that should increase risk. It should not automatically decide
`is_bot`, because reputation data can be stale or broad.

**Proposed work:**

- Add an optional local domain reputation file.
- Include fields such as domain, provider, category, severity, and notes.
- Add a heuristic score contribution when a clicked domain matches.
- Preserve the reputation reason in explanations.
- Keep the pipeline fully runnable offline.

**Acceptance examples:**

- A test blocklist can flag `example-bad-domain.test` without network access.
- The event explanation says which reputation source and category matched.
- A reputation match boosts risk but does not bypass the combined scoring logic.

### 4. Explain ML Tail Events With Feature Deviations

The Extended Isolation Forest can identify unusual events, but an anomaly score
alone is not enough for a reviewer. The system should say which features made
an ML-only event stand out.

For example, an event may be in the ML tail because it combines high
query/domain repetition, high same-second density, and unusual time-to-click
reuse. Showing those feature deviations makes the ML decision easier to audit.

**Proposed work:**

- For high-anomaly events, store the top feature deviations from the batch
  baseline.
- Keep the explanation model-agnostic: explain unusual feature values rather
  than internal tree paths.
- Add the deviations to `sample_events.json`, the dashboard, and the report.

**Acceptance examples:**

- An ML-only flagged event includes a short explanation such as "query/domain
  pair frequency is in the top 1% of the batch".
- The explanation does not depend on private internals of the `isotree` model.
- The dashboard can compare heuristic reasons with ML feature deviations.

### 5. Use Robust Scaling For Heavy-Tailed Features

Click-log features are often heavy-tailed. A few domains or queries may appear
thousands of times while most appear once. Standard scaling can still leave
extreme values dominating the model.

**Proposed work:**

- Compare the current standardisation with robust scaling or quantile
  transforms.
- Measure how much the top flagged population changes.
- Keep the existing approach unless the new transform improves explanation or
  stability.

**Acceptance examples:**

- The comparison shows overlap and disagreement between current and candidate
  scaling.
- The report explains whether the change reduces over-reliance on raw volume.
- The production setting remains deterministic and reproducible.

## P2: Improve Context, Drift Awareness, And Batch Robustness

### 6. Normalise High-Volume Signals By Available Context

High-volume traffic is not always fraudulent. A legitimate campaign, region, or
inventory source can create concentrated traffic. The heuristic rules should
use available context where possible.

**Proposed work:**

- Normalise high-volume signals by fields such as domain, region, browser, OS,
  country, hour, or any future campaign/inventory metadata.
- Avoid assuming metadata exists when it is not present in the current dataset.

**Example:**

If a domain is globally popular across many devices and regions, that is less
suspicious than the same volume concentrated in one narrow
region/browser/OS/query cluster.

### 7. Add Rolling Burst Features

The current system includes same-second and pseudo-session burst signals. It
should also capture rolling windows over multiple time spans.

**Proposed work:**

- Add 1-second, 10-second, and 60-second rolling windows.
- Start with query/domain and device-cluster groups.
- Keep the implementation deterministic and testable.

**Example:**

A bot may avoid exact same-second bursts by spreading clicks every two seconds.
A 60-second rolling window can still reveal the regular automated pattern.

### 8. Cache Domain Reputation Lookups

If live reputation providers are added later, the pipeline must not call a
provider once per event. That would be slow, expensive, and likely to hit rate
limits.

**Proposed work:**

- Query unique domains once per run.
- Cache results with a configurable time-to-live.
- Store provider, category, severity, and lookup timestamp.
- Keep live lookups disabled by default.

### 9. Weight Reputation Categories Differently

Not all reputation matches should carry the same weight. Malware, phishing, or
botnet command and control categories should usually matter more than a broad
"low reputation" category.

**Proposed work:**

- Map reputation categories to score weights.
- Preserve the provider category in explanations.
- Add an allowlist stage so legitimate domains can be protected from stale or
  overly broad reputation signals.

### 10. Add Richer Categorical Encodings

The current model uses aggregate count features for categorical fields such as
region, browser, OS, and country. More direct encodings may help the anomaly
model understand population shape.

**Proposed work:**

- Add deterministic bounded encodings for region, browser, OS, country, and
  future traffic-source fields.
- Avoid high-cardinality encodings that make artefacts difficult to inspect.
- Compare results before making the change production default.

### 11. Calibrate Thresholds Against Historical Batches

Current thresholds are batch-relative. That is appropriate for a self-contained
dataset, but production use would benefit from historical stability.

**Proposed work:**

- Save compact run history: flagged rate, score quantiles, top reasons, top
  domains, and tier counts.
- Compare each new run with previous baselines.
- Warn when traffic or score distributions drift sharply.

**Example:**

If the bot rate jumps from 2.5% to 12% between runs, the dashboard should make
that visible before anyone treats the new output as normal.

## P3: Future Work That Needs More Evidence Or External Context

### 12. Add Optional Live Reputation Providers

Live providers such as Google Safe Browsing, Google Web Risk, Spamhaus DBL, or
SURBL could add stronger threat intelligence when credentials and usage terms
allow it.

**Constraints:**

- Keep live lookups optional and disabled by default.
- Never require credentials to run the local project.
- Use cached unique-domain lookups, not per-event calls.
- Document provider terms and data handling before enabling the feature.

### 13. Add Labelled Validation

The most important future improvement is labelled validation. Labels could come
from manual review, invalid-traffic feedback, chargebacks, confirmed abuse
reports, or trusted campaign investigations.

With labels, Bot Hunter could move from operational confidence estimates to
measured precision, recall, calibration, and threshold optimisation.

**Proposed work:**

- Sample events across `suppress`, `quarantine`, and `monitor` tiers.
- Collect reviewer labels and reasons.
- Train or evaluate supervised models only when label quality is good enough.
- Keep the current rules plus EIF path as the production baseline until labels
  justify a replacement.

## Completed Work

These items are done and retained here because they explain why the current
pipeline looks the way it does.

| Area | Completed item | Why it mattered |
|---|---|---|
| Anomaly classifier | Added `is_sub_200ms_click` | Makes sub-human reaction timing explicit for ML, not only the rules layer. |
| Anomaly classifier | Added 10-second pseudo-session burst density | Captures coordinated click patterns that exact same-second counts can miss. |
| Anomaly classifier | Added query entropy | Helps distinguish natural-looking query text from synthetic or random strings. |
| Anomaly classifier | Consolidated production scoring on Extended Isolation Forest | Removes alternate backend drift and keeps output semantics consistent. |
| Explainability | Added structured rule contributions | Gives stable rule IDs, labels, weights, observed values, and thresholds for audits. |
| Rules classifier | Added concentrated `ct` context as supporting evidence | Lets the rules layer use country-like concentration only when paired with repeated query behaviour and clustering. |
| Decision logic | Added `suppress`, `quarantine`, and `monitor` tiers | Turns scores into practical actions without pretending unlabelled data has measured precision. |
| Decision logic | Added method disagreement buckets | Makes rules/ML agreement and disagreement visible for review. |

## Suggested Next Slice

The best next implementation slice is:

1. adaptive heuristic thresholds
2. strong-versus-supporting rule families
3. feature-deviation explanations for ML tail events

Those three items improve the current system without requiring external
credentials, live services, or labels. They also make the dashboard and report
more defensible because reviewers can see not just that an event was flagged,
but why the system considered the evidence strong.
