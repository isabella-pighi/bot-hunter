# TODO

## Detection Method Improvements

### Rules-Based Heuristic Classifier

- Make thresholds adaptive by percentile instead of fixed count cutoffs.
- Normalize high-volume signals by domain, region, campaign, inventory source, or hour when those fields are available.
- Add rolling burst features such as query/domain clicks in 1-second, 10-second, and 60-second windows.
- Separate high-confidence rules from weak supporting rules instead of only accumulating all signals linearly.
- Add allowlist or suppression handling for known legitimate high-volume domains or campaigns.
- Store rule contributions as structured data alongside text reasons so dashboard grouping and audits are more reliable.

### Domain Reputation Signals

- Add optional domain reputation checks as a heuristic risk signal, not as an automatic final bot decision.
- Start with a local domain blocklist file so the pipeline remains reproducible, testable, and usable offline.
- Support cached provider lookups for reputable sources such as Google Safe Browsing or Web Risk, Spamhaus DBL, and SURBL when credentials and usage terms allow.
- Query unique domains once per run instead of checking every click event individually.
- Cache lookup results with a configurable TTL to avoid rate-limit pressure and repeated network calls.
- Weight reputation categories differently, with phishing, malware, and botnet C&C as stronger signals than general spam or poor reputation.
- Record the provider and category in structured rule output and dashboard reasons, such as `domain listed by Spamhaus DBL as malware`.
- Add allowlist handling for known legitimate domains that may appear in reputation datasets because of compromise, redirects, or historical abuse.

### Unsupervised Anomaly Classifier

- Done: add an optional sklearn backend while keeping the current standard-library k-means fallback.
- Done: add `IsolationForest` as the first optional sklearn anomaly model for tabular behavioral features.
- Evaluate `LocalOutlierFactor` for density-based anomalies and small suspicious traffic pockets.
- Use robust scaling or quantile transforms for heavy-tailed features such as domain counts, query counts, and time-to-click.
- Add richer categorical encodings for region, browser, OS, country, and traffic source when using sklearn pipelines.
- Calibrate anomaly thresholds against historical batches instead of recalculating only within each run.
- Store nearest-cluster distance, cluster size, and top feature deviations to make ML flags easier to explain.

### Combined Decision Logic

- Train a simple supervised combiner, such as logistic regression or a calibrated tree model, if labels become available.
- Define confidence tiers for operations: suppress, quarantine, and monitor.
- Report disagreement buckets separately, especially high-rules/low-ML and low-rules/high-ML events.
- Track score distribution drift, flagged rate, top reasons, and top domains across runs.
