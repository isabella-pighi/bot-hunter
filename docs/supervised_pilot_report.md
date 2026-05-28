# Supervised Pilot Report

## Status

This is an additive experiment. The production rules+unsupervised pipeline is unchanged.

## Outcome Summary

The supervised pilot improved strict-seed capture at the same review volume, but it did
not establish true fraud precision. At the baseline review volume of 3,732 events,
rules+unsupervised selected 3,369 strict-seed events while rules+supervised selected
3,726. On the deterministic holdout, rules+unsupervised selected 674 strict-seed events
and rules+supervised selected 759 at the same 761-event review volume.

This means the supervised path is better at recovering events that resemble the strict
seed policy. It does not prove that supervised-only events are more fraudulent than
baseline-only events, because unseeded events are unlabeled background rather than
confirmed human traffic.

## Seed Policy

Positive labels come only from strict deterministic rule contributions: fast_click, repeat_query_domain, reused_ttc, same_second_burst.
The pilot does not use heuristic score, ML score, combined score, or heuristic/ML agreement as label sources.
Unseeded events are unlabeled background, not verified human traffic.

## Seed Counts

- Total strict seed positives: 50,249
- Training positives: 40,206
- Validation positives: 10,043
- Training background: 79,050
- Validation background: 19,940
- Excluded regular-interarrival supporting events: 34

Seed rule mix:

- same_second_burst: 48,412
- repeat_query_domain: 2,101
- fast_click: 541
- reused_ttc: 40

## Side-by-Side Comparison

| Metric | Rules+unsupervised | Rules+supervised |
|---|---:|---:|
| Selected events | 3,732 | 3,746 |
| Strict seed hits selected | 3,369 | 3,740 |
| Strict seed capture rate | 6.70% | 7.44% |
| Strict seed share of selected | 90.27% | 99.84% |

Selected-event overlap: 2,752 both, 980 baseline-only, 994 supervised-only.

## Same-Volume Review

At the baseline review volume of 3,732 events:

| Metric | Rules+unsupervised | Rules+supervised |
|---|---:|---:|
| Strict seed hits | 3,369 | 3,726 |
| Strict seed capture rate | 6.70% | 7.42% |
| Strict seed share of review | 90.27% | 99.84% |

## Validation Holdout

The validation split is deterministic: `crc32(event_id) % 5 == 0`. At the validation review volume of 761 events:

| Metric | Rules+unsupervised | Rules+supervised |
|---|---:|---:|
| Strict seed hits | 674 | 759 |
| Strict seed capture rate | 6.71% | 7.56% |
| Strict seed share of review | 88.57% | 99.74% |

## Score Interpretation

The supervised score is a percentile rank of distance-margin similarity to strict deterministic seed positives versus unlabeled background. It is useful for ordering review candidates, not as a calibrated probability of fraud.

## Validation Interpretation

The supervised path improves strict-seed capture at the same review volume, including on
the deterministic holdout. That is useful evidence for review efficiency against the
seed policy, but it is not measured fraud precision because the dataset has no
ground-truth human/bot labels. The supervised path should remain experimental until a
manual review set or stronger validation confirms that the additional supervised-only
events are better review candidates than the current baseline-only events.
