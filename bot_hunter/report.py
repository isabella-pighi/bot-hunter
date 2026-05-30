from __future__ import annotations

import html
import re
from pathlib import Path
from textwrap import wrap


def write_reports(summary: dict[str, object], output_dir: str | Path = "docs") -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    markdown = _markdown(summary)
    (output / "analysis_report.md").write_text(markdown, encoding="utf-8")
    html_text = _html(markdown)
    (output / "analysis_report.html").write_text(html_text, encoding="utf-8")
    _write_pdf(output / "analysis_report.pdf", markdown, html_text)


def _markdown(summary: dict[str, object]) -> str:
    bot_rate = float(summary["bot_rate"])
    precision = float(summary["estimated_precision"])
    ml_backend = str(summary.get("ml_backend", "eif"))
    _model_name, model_detail, backend_label = _model_copy(ml_backend)
    top_reasons = summary.get("top_reasons", [])
    feature_count = len(summary.get("feature_names", []))
    ml_feature_names = summary.get("ml_feature_names", summary.get("feature_names", []))
    ml_feature_count = len(ml_feature_names)
    ml_feature_weights = summary.get("ml_feature_weights", {})
    reason_lines = "\n".join(
        f"- {reason}: {count:,} events" for reason, count in top_reasons
    )
    if not reason_lines:
        reason_lines = "- No dominant heuristic reason was found."
    tier_counts = summary.get("tier_counts", {})
    tier_lines = "\n".join(
        f"- {tier}: {int(tier_counts.get(tier, 0)):,} events"
        for tier in ("suppress", "quarantine", "monitor")
    )
    suppress_count = int(tier_counts.get("suppress", 0))
    quarantine_count = int(tier_counts.get("quarantine", 0))
    monitor_count = int(tier_counts.get("monitor", 0))
    thresholds = summary.get("tier_thresholds", {})
    rule_strength_lines = _rule_strength_lines(summary.get("rule_strengths", {}))
    heuristic_threshold_lines = _heuristic_threshold_lines(
        summary.get("heuristic_thresholds", {})
    )
    if not heuristic_threshold_lines:
        heuristic_threshold_lines = (
            "| Rule | Computed threshold | Basis |\n|---|---:|---|"
        )
    heuristic_agreement = float(
        thresholds.get("suppress_agreement_heuristic_score", 0.62)
    )
    ml_agreement_score = float(thresholds.get("ml_agreement_score", 0.975))
    disagreement_rows = summary.get("method_disagreement", [])
    disagreement_lines = _disagreement_lines(disagreement_rows)
    if not disagreement_lines:
        disagreement_lines = "- No method disagreement data was reported."
    agreement_both_count = _disagreement_count(disagreement_rows, "Heuristic + ML")
    ml_only_count = _disagreement_count(disagreement_rows, "ML only")
    threshold = float(summary.get("threshold", 0.0))
    heuristic_flag_rate = float(summary.get("heuristic_flag_rate", 0.0))
    ml_tail_rate = float(summary.get("ml_tail_rate", 0.0))
    total_events = f'{int(summary["total_events"]):,}'
    bot_events = f'{int(summary["bot_events"]):,}'
    domain_weight = float(ml_feature_weights.get("log_domain_count", 1.0))
    country_weight = float(ml_feature_weights.get("log_country_count", 1.0))
    kp_weight = float(ml_feature_weights.get("log_kp_count", 1.0))
    sld_weight = float(ml_feature_weights.get("log_sld_count", 1.0))
    anomaly_class_lines = _anomaly_class_lines(summary.get("anomaly_classes", {}))
    filter_lines = _filtering_option_lines(
        _filtering_options(summary.get("anomaly_classes", {}))
    )
    statistical_findings = _statistical_findings_lines(summary)
    reason_table = _reason_table(top_reasons)
    disagreement_table = _method_agreement_table(disagreement_rows)
    feature_definition_lines = _feature_definition_lines(
        summary.get("feature_names", [])
    )

    return f"""# Bot Hunter Analysis Report

## 1. Executive Summary & Problem Statement

Bot Hunter analyses fictitious ad-click traffic to identify events that look
more like automated bot activity than legitimate user behaviour. The business
challenge is a familiar one for advertising platforms: invalid clicks can
inflate campaign metrics, distort billing, reduce trust in performance
reporting, and consume operational time that should be spent on genuine
customer outcomes.

This run read `{summary["input_path"]}` and analysed {total_events} click
events. Each row contains an event identifier, timestamp, region, browser,
operating system, and click URL. The URL query string carries behaviour signals
such as clicked domain (`d`), search query (`q`), time to click (`ttc`), and
country-like context (`ct`).

Bot Hunter selected {bot_events} events, or {bot_rate:.2%} of the batch, as
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
{backend_label} catches unusual combinations across engineered features that
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
| ML classifier | {backend_label} | Works without labels and can detect unusual combinations across engineered features. |
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

{rule_strength_lines}

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
{domain_weight:.2f} and {country_weight:.2f}, respectively. The low-cardinality
`kp` and `sld` frequency features are down-weighted to {kp_weight:.2f} and
{sld_weight:.2f}. {model_detail}

## 3. Core Statistical Findings

The current run shows a concentrated anomaly population rather than a broad
quality problem across the whole dataset. Bot Hunter selected {bot_events} of
{total_events} events as likely bot traffic. That is {bot_rate:.2%} of the
run, leaving the large majority of traffic in the monitor population.

| Metric | Current value | Plain-English meaning |
|---|---:|---|
{statistical_findings}

Top explainable rule patterns from the current run:

| Pattern | Events | How to explain it |
|---|---:|---|
{reason_table}

Method agreement from the current run:

| Bucket | Events | Interpretation |
|---|---:|---|
{disagreement_table}

`Combined tail` is the borderline evidence bucket. It means the event was
selected because the blended `combined_score` crossed the run threshold, while
neither strong rules nor the strongest ML-only evidence was enough on its own.
Treat these events as combined evidence for review or quarantine, not as
automatic suppression candidates.

Operational anomaly classes from the current run:

{_anomaly_class_summary_table(summary.get("anomaly_classes", {}))}

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

{anomaly_class_lines}

## 5. Recommended Business Actions

Separate prediction from action. `is_bot` is the compatibility prediction;
`operational_tier` is the safer business-control layer.

| Tier | Recommended action | Business assumption |
|---|---|---|
| `suppress` | Exclude from billing or downstream metrics after policy approval. | The organisation accepts limited review risk for high-confidence traffic. |
| `quarantine` | Hold, delay, sample, or manually review before suppression. | Ambiguous traffic should not be automatically removed. |
| `monitor` | Keep for trend monitoring and future labels. | Non-selected traffic can still help detect drift later. |

Operational split in this run:

{tier_lines}

Use `suppress` for the strongest operational candidates after policy approval.
Use `quarantine` as the default action for ambiguous or ML-only traffic. Do not
automatically block traffic solely because it is in the ML tail.

These tiers are the recommended operating model because they keep action
proportionate to the strength of evidence. Teams that need to go beyond the
three-tier view can also use the more targeted filters below. Treat them as
review controls for similar unlabelled datasets, not as ground-truth fraud
rules.

Practical filtering options for similar unlabelled datasets:

| Filter | Use | Caveat |
|---|---|---|
{filter_lines}

## 6. Probability Perspective & Risk Assessment

The current operational confidence estimate is {precision:.2%}. This is not
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

The roadmap should improve the system in three directions: make the current
signals easier to explain, make the thresholds more stable across batches, and
replace estimated confidence with measured performance once trusted labels
exist.

Near-term work should focus on improvements that do not require external
credentials or labelled data:

1. Add feature-deviation explanations for ML-tail events. A reviewer should
   see why an ML-only event was unusual, for example that its query/domain
   repetition or same-second density sits in the top 1% of the batch.
2. Add optional local domain reputation signals. A versioned local reputation
   file can add useful context without making live network calls or turning a
   broad reputation match into an automatic bot decision.
3. Compare robust scaling or quantile transforms for heavy-tailed features.
   This would test whether the model is too sensitive to very large domain,
   query, or device-cluster counts.

Medium-term work should make the approach safer across changing traffic mixes:

4. Normalise high-volume signals by available context such as region, browser,
   operating system, country-like `ct`, hour, and future campaign or inventory
   metadata. High volume is more suspicious when it is concentrated in a narrow
   footprint than when it is broad and expected.
5. Add rolling burst features over 1-second, 10-second, and 60-second windows.
   This would catch automation that avoids exact same-second bursts by spacing
   clicks just far enough apart.
6. Store compact run history for drift monitoring, including flagged rate,
   score quantiles, tier counts, top reasons, and top domains. A sudden move
   from a 2.5% selected rate to a much higher rate should be visible before the
   output is treated as normal.

Longer-term work needs more operational context:

7. Add cached live reputation providers only when credentials, usage terms, and
   data-handling requirements are clear. Live lookups should be optional,
   cached by unique domain, and disabled by default.
8. Collect labelled validation from manual review, invalid-traffic feedback,
   chargebacks, confirmed abuse reports, or trusted campaign investigations.
   Labels are required before reporting measured precision, recall,
   calibration, or optimised decision thresholds.
9. Build a feedback loop from reviewed `suppress` and `quarantine` decisions.
   Once label quality is good enough, the team can evaluate supervised models
   while keeping the current rules plus Extended Isolation Forest path as the
   production baseline.

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
| `Combined tail` | Borderline method bucket selected by the blended `combined_score`; neither strong rules nor strongest ML-only evidence was enough alone, so use it for review or quarantine rather than automatic suppression. |
| Anomaly class | Human-readable grouping of selected events by dominant evidence pattern. |

## Appendix B: Feature Definitions

| Feature | Meaning |
|---|---|
{feature_definition_lines}

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
combined_score > {threshold:.6f}
or heuristic_score >= 0.62
```

The combined-score threshold is the run-specific 97.5th-percentile cutoff. It
keeps the selected volume stable for an unlabelled dataset while letting the ML
model influence borderline cases.

The heuristic override protects high-confidence, explainable rule hits. For
example, a strongly repeated query/domain pattern with mechanical timing should
not be missed only because the anomaly ranking moved after a feature change.

Adaptive heuristic thresholds used in this run:

{heuristic_threshold_lines}

In this run:

- heuristic-only flag rate: {heuristic_flag_rate:.2%}
- ML agreement-tail reference rate: {ml_tail_rate:.2%}
- operational confidence estimate: {precision:.2%}
"""


def _model_copy(ml_backend: str) -> tuple[str, str, str]:
    if ml_backend == "eif":
        return (
            "an Extended Isolation Forest anomaly model",
            "Events isolated quickly by random hyperplane splits receive higher "
            "anomaly scores. EIF is the only production anomaly model; alternate "
            "ML backends and supervised pilots have been removed.",
            "Extended Isolation Forest model",
        )
    return (
        "the production Extended Isolation Forest anomaly model",
        "Events with stronger statistical anomaly evidence receive higher anomaly scores.",
        "Extended Isolation Forest model",
    )


def _statistical_findings_lines(summary: dict[str, object]) -> str:
    tier_counts = summary.get("tier_counts", {})
    if not isinstance(tier_counts, dict):
        tier_counts = {}
    rows = [
        (
            "Total events analysed",
            f"{int(summary.get('total_events', 0)):,}",
            "Number of click events in the batch.",
        ),
        (
            "Selected bot events",
            f"{int(summary.get('bot_events', 0)):,}",
            "Events marked `is_bot = 1`.",
        ),
        (
            "Selected bot rate",
            f"{float(summary.get('bot_rate', 0.0)):.2%}",
            "Share of the batch selected as likely bot traffic.",
        ),
        (
            "Suppress tier",
            f"{int(tier_counts.get('suppress', 0)):,}",
            "Strongest operational candidates, subject to policy approval.",
        ),
        (
            "Quarantine tier",
            f"{int(tier_counts.get('quarantine', 0)):,}",
            "Suspicious events that should be reviewed or sampled.",
        ),
        (
            "Monitor tier",
            f"{int(tier_counts.get('monitor', 0)):,}",
            "Events not selected for bot action.",
        ),
        (
            "Combined-score cutoff",
            f"{float(summary.get('threshold', 0.0)):.6f}",
            "Run-specific anomaly threshold.",
        ),
        (
            "Heuristic-only flag rate",
            f"{float(summary.get('heuristic_flag_rate', 0.0)):.2%}",
            "Share flagged by rules before model blending.",
        ),
        (
            "ML agreement-tail rate",
            f"{float(summary.get('ml_tail_rate', 0.0)):.2%}",
            "Reference tail used to compare ML agreement.",
        ),
        (
            "Operational confidence estimate",
            f"{float(summary.get('estimated_precision', 0.0)):.2%}",
            "Signal-based estimate, not measured precision.",
        ),
    ]
    return "\n".join(
        f"| {name} | {value} | {meaning} |" for name, value, meaning in rows
    )


def _reason_table(top_reasons: object) -> str:
    explanations = {
        "repeated query": "The same search term appears unusually often.",
        "repeated query/domain pair": (
            "The same search term repeatedly clicks the same domain."
        ),
        "confirmed query repetition": (
            "Query repetition is backed by additional context."
        ),
        "very short query": (
            "Short terms can be legitimate, but are useful supporting evidence."
        ),
        "high-volume clicked domain": "A domain receives unusually concentrated clicks.",
        "heavy region/browser/OS cluster": (
            "Traffic is concentrated in a narrow device/server footprint."
        ),
        "concentrated ct context": (
            "Country-like context is concentrated with repetition and clustering."
        ),
        "same-second click burst": "Multiple clicks happen in the same second.",
        "moderately long time-to-click": (
            "Timing is unusual enough to support other evidence."
        ),
        "dense burst repetition cluster": (
            "Burstiness and repeated behaviour appear together."
        ),
    }
    if not isinstance(top_reasons, list):
        return "| No dominant pattern | 0 | No rule pattern was reported. |"
    rows = []
    for reason, count in top_reasons:
        explanation = explanations.get(
            str(reason), "Explainable rule evidence contributed to selection."
        )
        rows.append(f"| {reason} | {int(count):,} | {explanation} |")
    return (
        "\n".join(rows) or "| No dominant pattern | 0 | No rule pattern was reported. |"
    )


def _method_agreement_table(rows: object) -> str:
    explanations = {
        "Heuristic + ML": "Strongest review candidates because both methods agree.",
        "Heuristic only": (
            "Explainable rule hits that are not extreme in the ML feature space."
        ),
        "ML only": "Multivariate anomalies that need careful sampling or review.",
        "Neither strong": "Traffic not strongly indicated by either method.",
    }
    if not isinstance(rows, list):
        return "| Not available | 0 | No method agreement data was reported. |"
    rendered = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            label = str(row[0])
            rendered.append(
                f"| {label} | {int(row[1]):,} | "
                f"{explanations.get(label, 'Agreement bucket reported by the run.')} |"
            )
    return (
        "\n".join(rendered)
        or "| Not available | 0 | No method agreement data was reported. |"
    )


def _anomaly_class_summary_table(anomaly_classes: object) -> str:
    if not isinstance(anomaly_classes, dict):
        return "| Class | Selected events | Recommended handling |\n|---|---:|---|\n| Not available | 0 | Review manually. |"
    classes = anomaly_classes.get("classes", [])
    if not isinstance(classes, list):
        return "| Class | Selected events | Recommended handling |\n|---|---:|---|\n| Not available | 0 | Review manually. |"
    rows = ["| Class | Selected events | Recommended handling |", "|---|---:|---|"]
    for item in classes:
        if not isinstance(item, dict):
            continue
        rows.append(
            "| "
            f"{_cell(str(item.get('label', item.get('class_id', 'Unknown'))))} | "
            f"{int(item.get('count', 0)):,} | "
            f"{_cell(str(item.get('review_action', 'Review manually.')))} |"
        )
    return "\n".join(rows)


def _feature_definition_lines(feature_names: object) -> str:
    definitions = {
        "log_domain_count": "Log-scaled frequency of the clicked domain.",
        "log_query_count": "Log-scaled frequency of the search query.",
        "log_query_domain_count": "Log-scaled frequency of the query/domain pair.",
        "log_device_count": "Log-scaled frequency of the region/browser/OS cluster.",
        "log_country_count": (
            "Log-scaled frequency of `ct`, the country-like URL parameter."
        ),
        "log_same_second_count": "Log-scaled number of clicks sharing the same second.",
        "log_ttc_count": "Log-scaled reuse count for exact time-to-click values.",
        "log_kp_count": "Log-scaled frequency of the `kp` URL parameter value.",
        "log_sld_count": "Log-scaled frequency of the `sld` URL parameter value.",
        "kp": "Raw `kp` URL parameter retained for audit; excluded from ML features.",
        "sld": "Raw `sld` URL parameter retained for audit; excluded from ML features.",
        "hour": "Event hour extracted from the timestamp.",
        "log_ttc_seconds": "Log-scaled time-to-click duration.",
        "is_sub_200ms_click": (
            "Flag for click timing below a plausible human reaction threshold."
        ),
        "log_pseudo_session_10s_click_count": (
            "Log-scaled burst density within pseudo-session-style groups."
        ),
        "query_entropy": "Text randomness measure for the search query.",
    }
    if not isinstance(feature_names, list):
        feature_names = list(definitions)
    rows = []
    for feature_name in feature_names:
        if feature_name in definitions:
            rows.append(f"| `{feature_name}` | {definitions[feature_name]} |")
    return "\n".join(rows)


def _disagreement_lines(rows: object) -> str:
    if not isinstance(rows, list):
        return ""
    return "\n".join(
        f"- {label}: {int(count):,} events"
        for label, count in rows
        if isinstance(label, str)
    )


def _heuristic_threshold_lines(thresholds: object) -> str:
    if not isinstance(thresholds, dict) or not thresholds:
        return ""
    rows = ["| Rule | Computed threshold | Basis |", "|---|---:|---|"]
    for rule_id in sorted(thresholds):
        details = thresholds[rule_id]
        if not isinstance(details, dict):
            continue
        label = str(details.get("label", rule_id))
        threshold = details.get("threshold", "")
        percentile = float(details.get("percentile", 0.0))
        absolute_floor = details.get("absolute_floor", "")
        rate_floor = details.get("rate_floor")
        percentile_label = f"{round(percentile * 100)}th-percentile"
        basis = f"{percentile_label} threshold, floor {absolute_floor}"
        if rate_floor is not None:
            basis = f"{basis}, rate guardrail {rate_floor}"
        rows.append(f"| {label} (`{rule_id}`) | {threshold} | {basis} |")
    return "\n".join(rows)


def _anomaly_class_lines(anomaly_classes: object) -> str:
    if not isinstance(anomaly_classes, dict) or not anomaly_classes:
        return "Operational anomaly classes are not available for this run."

    scope = str(
        anomaly_classes.get(
            "scope",
            (
                "Operational anomaly classes derived from the current "
                "unlabelled run; these are not proven fraud labels."
            ),
        )
    )
    classified_count = int(anomaly_classes.get("classified_selected_event_count", 0))
    ml_only_population = int(anomaly_classes.get("ml_only_population_count", 0))
    class_rows = _anomaly_class_table(anomaly_classes.get("classes", []))
    example_lines = _anomaly_example_lines(anomaly_classes.get("classes", []))

    return f"""{scope}

The classes below group the {classified_count:,} selected events from this run.
The grouping is backed by full-run rule contributions, rule strength and family
fields, heuristic and ML scores, method-agreement buckets, operational tiers,
and the run-specific thresholds described later in this report.

| Class | Selected events | Data backing |
|---|---:|---|
{class_rows}

The ML-tail population contains {ml_only_population:,} events with high anomaly
scores and heuristic scores below the rule override threshold. Only the subset
that also crossed the combined-score cutoff is counted as selected traffic in
the class table. This keeps ML-only anomalies visible without describing them
as rule-derived replay evidence.

Concrete examples from the current run are summarised below. The underlying
event-level fields, scores, tiers, and rule evidence can be visualised in the
Traffic Explorer in the dashboard.

{example_lines}
"""


def _filtering_options(anomaly_classes: object) -> object:
    """Return filtering options from the anomaly class summary.

    Args:
        anomaly_classes: Summary section containing anomaly class metadata.

    Returns:
        The filtering options object, or an empty list when unavailable.
    """
    if not isinstance(anomaly_classes, dict):
        return []
    return anomaly_classes.get("filtering_options", [])


def _anomaly_class_table(classes: object) -> str:
    if not isinstance(classes, list):
        return "| Not available | 0 | No class data reported |"
    rows: list[str] = []
    for item in classes:
        if not isinstance(item, dict):
            continue
        label = _cell(str(item.get("label", item.get("class_id", "Unknown"))))
        count = int(item.get("count", 0))
        backing = _cell(_class_backing(item))
        rows.append(f"| {label} | {count:,} | {backing} |")
    return "\n".join(rows) or "| Not available | 0 | No class data reported |"


def _class_backing(item: dict[str, object]) -> str:
    tier_counts = _count_dict(item.get("tier_counts", {}), separator=" / ")
    method_counts = _count_dict(item.get("method_counts", {}), separator=" / ")
    dominant_rules = item.get("dominant_rules", [])
    rules = []
    if isinstance(dominant_rules, list):
        for rule in dominant_rules[:3]:
            if isinstance(rule, dict):
                rules.append(
                    f"{rule.get('rule_id', 'unknown')} ({int(rule.get('count', 0)):,})"
                )
    parts = []
    if tier_counts:
        parts.append(f"tiers: {tier_counts}")
    if method_counts:
        parts.append(f"methods: {method_counts}")
    if rules:
        parts.append(f"top rules: {' / '.join(rules)}")
    note = item.get("rule_evidence_note")
    if isinstance(note, str) and note:
        parts.append(f"top rules: {note}")
    return "; ".join(parts) or str(item.get("description", "No backing reported."))


def _anomaly_example_lines(classes: object) -> str:
    if not isinstance(classes, list):
        return "- No anomaly class examples were reported."
    lines: list[str] = []
    for item in classes:
        if not isinstance(item, dict):
            continue
        examples = item.get("examples", [])
        if not isinstance(examples, list) or not examples:
            continue
        example = examples[0]
        if not isinstance(example, dict):
            continue
        label = str(item.get("label", item.get("class_id", "Anomaly class")))
        population = item.get("population_count")
        population_text = ""
        if population is not None:
            population_text = f" ({int(population):,} events in the wider population)"
        class_id = str(item.get("class_id", ""))
        narrative = _example_narrative(class_id, label, example)
        lines.append(
            "- "
            f"{label}{population_text}: {narrative} The example event is "
            f"`{example.get('event_id', 'unknown')}`, which clicked "
            f"`{example.get('domain', '')}` for query "
            f"`{example.get('query', '')}`."
        )
    return "\n".join(lines) or "- No anomaly class examples were reported."


def _example_narrative(
    class_id: str,
    label: str,
    example: dict[str, object],
) -> str:
    """Return a stakeholder-friendly explanation for an anomaly example.

    Args:
        class_id: Stable anomaly class identifier.
        label: Human-readable anomaly class label.
        example: Example event dictionary from the summary artefact.

    Returns:
        Plain-English narrative describing what the example represents.
    """
    domain = str(example.get("domain", "the clicked domain"))
    query = str(example.get("query", "the query"))
    narratives = {
        "repetition_with_supporting_context": (
            "This is a replay-like example rather than a single odd click. "
            f"The same query/domain pattern around `{query}` and `{domain}` is "
            "reinforced by broader context such as domain volume, device-like "
            "clustering, and country-like concentration. That combination is "
            "stronger than repetition alone because several independent fields "
            "point in the same direction."
        ),
        "compound_burst_replay": (
            "This example shows repetition happening inside a burst. The key "
            "concern is not only that the query and domain repeat, but that the "
            "click pattern also appears in same-second or dense burst evidence. "
            "That is more consistent with automated replay than with ordinary "
            "human browsing."
        ),
        "ml_tail_multivariate": (
            "This is an unusual multivariate event rather than a clean rule hit. "
            "The rules did not provide enough strong evidence for automatic "
            "suppression, but the event sits far enough into the anomaly-model "
            "tail to justify quarantine or sampling. In business terms, this is "
            "a review candidate, not proof of fraud."
        ),
        "repetition_with_timing": (
            "This example combines repeated query/domain behaviour with unusual "
            "timing. Repetition explains why the event resembles replay; the "
            "timing evidence makes the case stronger because the click cadence "
            "does not look like normal human variation."
        ),
        "repetition_dominated": (
            "This is the simplest explainable replay pattern. The main evidence "
            "is repeated query/domain behaviour with confirmed query repetition, "
            "without needing burst or broader context to carry the decision."
        ),
        "supporting_context_combined_tail": (
            "This example is deliberately treated as borderline. It has "
            "supporting context and a high enough blended score to cross the run "
            "threshold, but neither the rules nor the ML evidence is strong "
            "enough on its own. That is why the right action is review or "
            "quarantine rather than automatic suppression."
        ),
        "other_combined_tail": (
            "This is a residual combined-tail example. It crosses the blended "
            "threshold, but it does not match the main operational classes. The "
            "fast-click and burst evidence make it worth sampling, while the "
            "borderline score argues against automatic suppression."
        ),
    }
    return narratives.get(
        class_id,
        (
            f"This example represents the `{label}` class. The event is included "
            "because its combined behavioural evidence is stronger than ordinary "
            "traffic in the current batch."
        ),
    )


def _filtering_option_lines(options: object) -> str:
    if not isinstance(options, list):
        return "| No filter reported | Review manually | Needs local policy approval |"
    rows: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        name = _cell(str(option.get("name", "Unnamed filter")))
        filter_text = _cell(f"`{option.get('filter', '')}`")
        use = _cell(str(option.get("use", "")))
        caveat = _filter_caveat(str(option.get("name", "")))
        rows.append(f"| {name}: {filter_text} | {use} | {caveat} |")
    return (
        "\n".join(rows)
        or "| No filter reported | Review manually | Needs local policy approval |"
    )


def _filter_caveat(name: str) -> str:
    lowered = name.lower()
    if "suppression" in lowered:
        return "Check policy, billing, and customer-impact rules before action."
    if "quarantine" in lowered:
        return "Use sampling to estimate likely false positives before suppression."
    if "ml" in lowered:
        return "Needs feature-deviation review because rule evidence is below override."
    return "Validate repeated-pattern assumptions against campaign context."


def _count_dict(value: object, separator: str = ", ") -> str:
    if not isinstance(value, dict):
        return ""
    return separator.join(f"{key} {int(count):,}" for key, count in value.items())


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _rule_strength_lines(settings: object) -> str:
    if not isinstance(settings, dict) or not settings:
        return (
            "The current run did not report rule-strength settings in the "
            "summary artefact."
        )
    supporting_cap = settings.get("supporting_cap")
    rows = [
        "| Rule strength | Meaning | Score treatment |",
        "|---|---|---|",
        (
            "| Strong | Direct mechanical or replay evidence | "
            "Contributes its full rule weight |"
        ),
    ]
    if supporting_cap is None:
        treatment = "Contributes as supporting evidence"
    else:
        treatment = f"Capped together at {float(supporting_cap):.2f}"
    rows.append(f"| Supporting | Contextual or weaker evidence | {treatment} |")
    return "\n".join(rows)


def _disagreement_count(rows: object, label: str) -> int:
    if not isinstance(rows, list):
        return 0
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) == 2 and row[0] == label:
            return int(row[1])
    return 0


def _html(markdown: str) -> str:
    body = []
    in_list = False
    in_code = False
    in_table = False
    list_tag = "ul"
    table_headers: list[str] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = " ".join(part.strip() for part in paragraph_lines if part.strip())
        if text:
            body.append(f"<p>{html.escape(text)}</p>")
        paragraph_lines.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append(f"</{list_tag}>\n")
            in_list = False

    def close_table() -> None:
        nonlocal in_table, table_headers
        if in_table:
            body.append("</tbody></table></div>\n")
            in_table = False
            table_headers = []

    for line in markdown.splitlines():
        if line.startswith("```"):
            flush_paragraph()
            close_table()
            close_list()
            body.append("</pre>\n" if in_code else "\n<pre>")
            in_code = not in_code
            continue
        if in_code:
            body.append(f"{html.escape(line)}\n")
            continue
        if line.startswith("# "):
            flush_paragraph()
            close_table()
            close_list()
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            flush_paragraph()
            close_list()
            close_table()
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            flush_paragraph()
            close_table()
            if not in_list:
                list_tag = "ul"
                body.append("\n<ul>")
                in_list = True
            body.append(f"<li>{html.escape(line[2:])}</li>")
        elif match := re.match(r"^(\d+)\. (.+)$", line):
            flush_paragraph()
            close_table()
            if not in_list or list_tag != "ol":
                close_list()
                list_tag = "ol"
                body.append("\n<ol>")
                in_list = True
            body.append(f"<li>{html.escape(match.group(2))}</li>")
        elif in_list and line.startswith("  ") and line.strip():
            if body and body[-1].endswith("</li>"):
                body[-1] = f"{body[-1][:-5]} {html.escape(line.strip())}</li>"
        elif line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            close_list()
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(cell.replace("-", "").replace(":", "") == "" for cell in cells):
                continue
            if not in_table:
                table_headers = cells
                rendered_cells = "".join(
                    f"<th>{html.escape(cell)}</th>" for cell in cells
                )
                body.append(
                    '\n<div class="table-wrap"><table><thead><tr>'
                    f"{rendered_cells}</tr></thead><tbody>"
                )
                in_table = True
            else:
                rendered_cells = "".join(
                    _render_table_data_cell(
                        cell, table_headers[index] if index < len(table_headers) else ""
                    )
                    for index, cell in enumerate(cells)
                )
                body.append(f"<tr>{rendered_cells}</tr>")
        elif line.strip():
            close_table()
            close_list()
            paragraph_lines.append(line)
        else:
            flush_paragraph()
            close_table()
            close_list()
    flush_paragraph()
    close_list()
    close_table()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bot Hunter Analysis Report</title>
  <style>
    :root {{
      color-scheme: light;
      --border: #cfd7df;
      --border-strong: #9eaab5;
      --ink: #172026;
      --muted: #52616d;
      --page: #ffffff;
      --surface: #f6f8fa;
      --thead: #eef3f7;
    }}
    * {{ box-sizing: border-box; }}
    html {{ font-size: clamp(16px, 0.72vw + 0.45rem, 22px); }}
    body {{
      background: #f4f7fa;
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.55;
      margin: 0;
    }}
    main {{
      background: var(--page);
      box-shadow: 0 16px 48px rgba(23, 32, 38, 0.08);
      margin: 0 auto;
      max-width: 1680px;
      min-height: 100vh;
      padding: clamp(24px, 4.5vw, 88px);
      width: min(100%, 1680px);
    }}
    h1, h2 {{ line-height: 1.2; overflow-wrap: anywhere; }}
    h1 {{ font-size: clamp(2.2rem, 3.2vw, 4.25rem); margin: 0 0 1.25rem; }}
    h2 {{
      border-top: 1px solid var(--border);
      font-size: clamp(1.45rem, 1.45vw, 2.35rem);
      margin-top: 2.4rem;
      padding-top: 1.25rem;
    }}
    p, ul, ol, pre, .table-wrap {{
      margin-left: 0;
      margin-right: 0;
      max-width: none;
      width: 100%;
    }}
    p {{ margin-bottom: 1.1rem; margin-top: 0; }}
    ul, ol {{ padding-left: 1.35rem; }}
    pre {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow-x: auto;
      padding: 1rem;
      white-space: pre-wrap;
    }}
    .table-wrap {{
      border: 1px solid var(--border-strong);
      border-radius: 6px;
      margin: 1.35rem 0 1.8rem;
      overflow-x: auto;
      scrollbar-gutter: stable;
      width: 100%;
    }}
    table {{
      border-collapse: collapse;
      font-size: clamp(0.86rem, 0.55vw + 0.45rem, 1rem);
      min-width: min(1040px, 100%);
      table-layout: auto;
      width: 100%;
    }}
    th, td {{
      border: 1px solid var(--border);
      padding: 0.7rem 0.8rem;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
      word-break: normal;
    }}
    th {{
      background: var(--thead);
      color: var(--muted);
      font-weight: 700;
    }}
    .cell-list {{
      margin: 0;
      padding-left: 1rem;
    }}
    .cell-list ul {{
      margin: 0.3rem 0 0.75rem;
      padding-left: 1.15rem;
      width: auto;
    }}
    .cell-list > li:last-child ul {{ margin-bottom: 0; }}
    .cell-list-label {{
      color: var(--ink);
      font-weight: 700;
    }}
    tbody tr:nth-child(even) {{ background: #fbfcfd; }}
    @page {{ size: A4; margin: 14mm; }}
    @media print {{
      html {{ font-size: 13px; }}
      body {{ background: var(--page); }}
      main {{
        box-shadow: none;
        max-width: none;
        min-height: auto;
        padding: 0;
        width: 100%;
      }}
      h1 {{ font-size: 2.35rem; }}
      h2 {{
        break-after: avoid;
        font-size: 1.45rem;
        margin-top: 1.8rem;
      }}
      p, ul, ol, pre, .table-wrap {{ break-inside: avoid; }}
      .table-wrap {{
        border-color: var(--border-strong);
        overflow: visible;
      }}
      table {{
        font-size: 0.78rem;
        min-width: 100%;
      }}
      tr {{ break-inside: avoid; }}
    }}
    @media (max-width: 720px) {{
      main {{ padding: 20px 14px 32px; }}
      .table-wrap {{ border-radius: 4px; }}
      table {{ min-width: 760px; }}
      th, td {{ padding: 0.6rem; }}
    }}
  </style>
</head>
<body><main>{''.join(body)}</main></body>
</html>"""


def _render_table_data_cell(cell: str, header: str) -> str:
    if header == "Data backing":
        return f"<td>{_render_data_backing_html(cell)}</td>"
    return f"<td>{html.escape(cell)}</td>"


def _render_data_backing_html(cell: str) -> str:
    groups = []
    for part in cell.split("; "):
        if ": " not in part:
            continue
        label, values = part.split(": ", 1)
        nested_items = [
            f"<li>{html.escape(value.strip())}</li>"
            for value in values.split(" / ")
            if value.strip()
        ]
        if nested_items:
            groups.append(
                "<li>"
                f'<span class="cell-list-label">{html.escape(label)}</span>'
                f"<ul>{''.join(nested_items)}</ul></li>"
            )
    if not groups:
        return html.escape(cell)
    return f"<ul class=\"cell-list\">{''.join(groups)}</ul>"


def _write_pdf(path: Path, markdown: str, html_text: str) -> None:
    """Write a styled PDF report, falling back to a simple PDF if needed.

    Args:
        path: Destination PDF path.
        markdown: Markdown report text used by the fallback writer.
        html_text: Styled HTML report text used for browser PDF rendering.
    """
    if _write_browser_pdf(path, html_text):
        return
    _write_simple_pdf(path, markdown)


def _write_browser_pdf(path: Path, html_text: str) -> bool:
    """Render the report PDF from the same HTML/CSS used by the web report.

    Args:
        path: Destination PDF path.
        html_text: Styled report HTML.

    Returns:
        True when browser rendering succeeded; otherwise False.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(
                viewport={"width": 1440, "height": 1800},
                device_scale_factor=1,
            )
            page.set_content(html_text, wait_until="load")
            page.pdf(
                path=str(path),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
            )
    except PlaywrightError:
        return False
    finally:
        if browser is not None:
            try:
                browser.close()
            except PlaywrightError:
                pass
    return True


def _write_simple_pdf(path: Path, text: str) -> None:
    lines: list[str] = []
    for raw in text.replace("#", "").replace("`", "").splitlines():
        if not raw.strip():
            lines.append("")
        else:
            lines.extend(wrap(raw, width=88) or [""])

    pages = [lines[i : i + 42] for i in range(0, len(lines), 42)] or [[]]
    objects: list[bytes] = [
        b"",
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    page_ids: list[int] = []
    for page_lines in pages:
        content = ["BT", "/F1 10 Tf", "50 780 Td", "14 TL"]
        for line in page_lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.append(f"({escaped}) Tj")
            content.append("T*")
        content.append("ET")
        stream = "\n".join(content).encode("latin-1", errors="replace")
        content_id = len(objects)
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        page_id = len(objects)
        page_ids.append(page_id)
        page_payload = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects.append(page_payload.encode())

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects[1:], start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_at = len(pdf)
    pdf.extend(f"xref\n0 {len(objects)}\n0000000000 65535 f\n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n\n".encode())
    pdf.extend(
        f"trailer << /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    )
    path.write_bytes(bytes(pdf))
