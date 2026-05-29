# Bot Hunter

Bot Hunter is a local Python application for finding likely automated bot
clicks in advertising click logs. It reads raw TSV click data, engineers
behavioural features, combines an explainable rules model with an unsupervised
anomaly model, writes the required `submission.tsv`, and serves a local HTTP
dashboard for review.

The project is designed for an evaluation setting where the data are
unlabelled. That matters: without ground truth, the goal is not to claim
measured fraud accuracy. The goal is to build a defensible detection workflow,
show the evidence behind each decision, and make the trade-offs clear enough
for both technical and business review.

## Technical Setup

### Requirements

Use Python `3.10` or newer. The project is managed with `uv` and keeps the
runtime deliberately small:

- core package: `bot_hunter`
- test dependency: `pytest`
- optional anomaly-model dependency: `isotree`, installed through the `eif`
  extra
- local dashboard: Python standard-library HTTP server

Install the reusable local environment from the repository root:

```bash
uv sync --extra eif
```

For one-off commands, keep the `uv run --extra eif ...` prefix so the Extended
Isolation Forest dependency is available without a separate activation step.

### Input Data

The raw click file is a tab-separated file with six fields. It may include a
header:

```text
event_id    event_time    region    browser    os    url
```

`event_time` must use `YYYY-MM-DD HH:MM:SS`. The URL query string may contain
fields such as:

| Parameter | Meaning |
|---|---|
| `d` | clicked advert or domain-like target |
| `q` | original search query |
| `ttc` | time to click |
| `ct` | country-like location signal |
| `kl` | language or locale-like signal |
| `kp` | numeric parameter used as a model feature |
| `sld` | numeric parameter used as a model feature |

Example, wrapped across fields for readability:

```text
evt_123    2024-01-01 10:15:03    eu-west    chrome    android
/click?d=example&q=cheap+shoes&ttc=0.132&ct=uk
```

### Running The Pipeline

Run the production classifier and generate all deliverables:

```bash
uv run --extra eif python -m bot_hunter.cli run --input data/bot-hunter-dataset.tsv
```

This writes the following artefacts. The directory name is `artifacts/` on disk
to match the existing project structure:

| Output | Purpose |
|---|---|
| `submission.tsv` | Required event-level output |
| `artifacts/summary.json` | Metrics, thresholds, settings, and disagreement counts |
| `artifacts/features.tsv` | Engineered feature matrix for audit and debugging |
| `artifacts/sample_events.json` | High-risk examples and rule contributions |
| `docs/analysis_report.md` | Markdown report |
| `docs/analysis_report.html` | HTML report |
| `docs/analysis_report.pdf` | PDF report |

Use `--output-dir <path>` to write outputs somewhere other than the repository
root:

```bash
uv run --extra eif python -m bot_hunter.cli run \
  --input data/bot-hunter-dataset.tsv \
  --output-dir /tmp/bot-hunter-run
```

### Running The Dashboard

Start the local HTTP dashboard:

```bash
uv run --extra eif python -m bot_hunter.web --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

The dashboard serves:

| Route | Purpose |
|---|---|
| `/` | Business-facing dashboard |
| `/features` | Feature table |
| `/report` | HTML report |
| `/api/summary` | Summary metrics as JSON |
| `/api/events` | Sample high-risk events as JSON |
| `/api/features` | Engineered features as JSON |
| `POST /upload` | Upload a TSV and run the pipeline |
| `GET /run?input=<path>` | Run a server-side TSV path under the dashboard root |

By default the server binds to `127.0.0.1`. Use `--host 0.0.0.0` only when the
dashboard should be reachable from another machine on the network.

### Development Commands

Run the tests:

```bash
uv run pytest
```

Run a full artifact refresh:

```bash
uv run --extra eif python -m bot_hunter.cli run --input data/bot-hunter-dataset.tsv
```

If a previous dashboard is occupying a local port:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

## Problem Statement And Proposed Solution

### The Problem

The input data contain fictitious advertising click traffic. Some clicks come
from legitimate users and some come from automated bots. The project brief asks
for:

- a rules-based classifier
- a machine-learning classifier
- explanations of the anomalies found
- visualisations for a non-data-scientist audience
- probability reasoning and action recommendations
- a generated `submission.tsv` containing the best binary bot prediction

The difficult part is that the data are unlabelled. There is no trusted column
that says "this click was fraud" or "this click was human". That means the
solution must be evidence-led rather than accuracy-led. We can describe why
traffic looks automated, compare independent signals, and estimate operational
confidence, but we cannot honestly report measured precision or recall without
labels.

### Definitions

| Term | Definition |
|---|---|
| Bot click | A click that appears to be generated by automation rather than a human user |
| Heuristic | A transparent rule based on domain knowledge, such as implausibly fast clicking |
| Feature | A numeric signal used by a classifier, such as query repetition or time-to-click |
| Anomaly score | A model score describing how unusual an event looks compared with the population |
| False positive | A legitimate human click incorrectly flagged as bot traffic |
| False negative | A bot click missed by the classifier |
| Operational tier | A practical action category: suppress, quarantine, or monitor |
| Pseudo-label | A label inferred from strong rules or high-confidence model behaviour |

### Strategy

Bot Hunter combines two classifiers:

1. A rules-based classifier that looks for explainable bot-like behaviour.
2. An Extended Isolation Forest anomaly model that looks for unusual
   combinations of engineered features.

The final score is a weighted blend:

```text
combined_score = (0.58 * heuristic_score) + (0.42 * ml_score)
```

An event is flagged when either:

```text
combined_score >= run-specific 97.5th-percentile cutoff
or heuristic_score >= 0.62
```

The rules are deliberately weighted slightly higher because they are easier to
explain, audit, and challenge. The anomaly model remains important because it
can detect multivariate patterns that a single rule may miss.

### Why This Strategy Was Chosen

Bot traffic usually leaves behavioural and structural footprints. A single
click might not prove much, but repeated patterns across thousands of events can
be informative.

For example, a human user may click quickly once. A bot is more likely to
produce many clicks with repeated query/domain pairs, exact time-to-click reuse,
dense same-second bursts, and narrow device or environment clusters. These are
not independent proof of fraud, but together they form a stronger argument.

The rules layer captures patterns that are easy to explain:

| Example signal | Why it matters |
|---|---|
| `ttc < 200 ms` | Many humans cannot physically search, inspect, and click that quickly |
| repeated query/domain pair | Scripts often replay the same search and click pattern |
| many events in the same second | Automation can create dense timing bursts |
| exact time-to-click reuse | Programmatic systems often reuse deterministic delays |
| heavy region/browser/OS cluster | Bots often share an environment footprint |

The anomaly layer captures combinations. A single feature value may look
ordinary, but the combination can still be suspicious. For example, a click may
not have an impossible `ttc`, but it may belong to a rare mix of high query
repetition, high domain repetition, high same-second density, and narrow device
clustering.

### Engineered Features

The current production feature set includes:

| Feature | Meaning |
|---|---|
| `log_domain_count` | Clicked-domain frequency |
| `log_query_count` | Exact query frequency |
| `log_query_domain_count` | Query/domain pair frequency |
| `log_device_count` | Region/browser/OS cluster frequency |
| `log_country_count` | `ct` country frequency |
| `log_same_second_count` | Events with the same timestamp |
| `log_ttc_count` | Exact time-to-click reuse |
| `kp` | Numeric `kp` parameter |
| `sld` | Numeric `sld` parameter |
| `hour` | Event hour |
| `log_ttc_seconds` | Log-scaled time-to-click |
| `is_sub_200ms_click` | Mechanical sub-200 ms click indicator |
| `log_pseudo_session_10s_click_count` | Local 10-second burst density |
| `query_entropy` | Shannon entropy of query text |

Several features use logarithmic transforms because click-log data are usually
heavy-tailed. A small number of queries, domains, or device clusters may appear
many times. Log transforms reduce the influence of extreme values so the model
does not treat scale alone as the whole story.

### Probability Perspective

Because the dataset is unlabelled, Bot Hunter reports an estimated operational
precision rather than measured fraud probability. The estimate is based on
agreement between independent signals:

- high heuristic score
- high anomaly score
- repeated rule contributions
- concentration in suspicious timing, query, and device patterns

The strongest cases are where rules and ML agree. Cases flagged only by the ML
model are still useful, but they are less certain because unsupervised anomaly
detection can also find unusual legitimate behaviour. For example, a legitimate
power user, test campaign, or unusual regional spike may look anomalous without
being fraudulent.

The dashboard and report therefore separate binary prediction from operational
action:

| Tier | Meaning | Recommended action |
|---|---|---|
| `suppress` | High-confidence bot traffic | Exclude after policy approval |
| `quarantine` | Suspicious traffic needing review | Hold for manual or sampled review |
| `monitor` | Not selected for action | Keep for trend tracking and future labelling |

This avoids treating every flagged event as equally certain.

### Trade-Offs

| Choice | Benefit | Trade-off |
|---|---|---|
| Rules plus anomaly model | Balances explanation with pattern detection | More moving parts |
| Conservative cutoff | Reduces false positives | May miss subtle bots |
| Heuristics weighted higher than ML | Easier to defend in review | May underweight novel bots |
| Unsupervised learning | Works without labels | Cannot measure precision or recall directly |
| Local dashboard and artefacts | Easy to run and audit locally | Not production monitoring |

The current approach should generalise to similar click-log datasets when bots
reuse timing, query, domain, or environment patterns. It will generalise less
well if future bots deliberately randomise those signals, if the traffic mix
changes sharply, or if business rules around acceptable traffic differ.

### Future Work

The next step is to move from unlabelled anomaly detection towards labelled or
weakly supervised validation. Useful additions would include:

- manual review labels for a stratified sample of suppress, quarantine, and
  monitor events
- downstream fraud, chargeback, or invalid-traffic feedback
- calibrated probability modelling once labels exist
- time-windowed monitoring for drift and new bot families
- model cards for each production classifier version
- stronger observability around runtime, input quality, and artifact freshness

## Team Setup And HCOM

### Development Model

This repository is also used to document and exercise a local agentic
development workflow. The aim is disciplined collaboration, not uncontrolled
autonomy.

The team has five roles:

| Role | Default tool | Responsibility |
|---|---|---|
| Human owner | Human | Sets goals, approves trade-offs, owns final judgement |
| Orchestrator | Codex CLI | Routes work, waits for review, owns commits and pushes |
| Algorithm coder | Codex CLI | Pipeline, features, classifiers, tests, runtime supportability |
| Algorithm reviewer | Claude Code | Independent engineering and data-science review |
| UX coder | Codex CLI | Dashboard, report, documentation, user-facing explanations |
| UX reviewer | Claude Code | Independent UX, report, accessibility, and documentation review |

The orchestrator must not implement code, write tests, edit documentation, or
perform review work itself. It sends tasks to the relevant specialist pair over
HCOM, waits for the reviewer response, checks the evidence, and only then
commits and pushes accepted work.

### Why HCOM Is Used

HCOM gives the local team a lightweight communication layer for CLI agents. It
provides:

- agent launch and tagging
- direct messages by role tag
- conversation transcripts
- event awareness
- a practical way to separate implementation, review, and orchestration

This matters because Bot Hunter mixes code, data-science judgement, reports,
and business-facing explanation. Separate specialist pairs reduce the chance
that one agent both creates and uncritically accepts its own assumptions.

### Team Setup

Install and configure memory support:

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
```

Start the specialist pairs:

```bash
./scripts/start-agent-team
```

Start the orchestrator:

```bash
./scripts/start-orchestrator
```

Check the active team:

```bash
hcom list
```

Stop all agents:

```bash
hcom kill all
```

Role prompts and deeper operating instructions live in:

```text
development approach/
```

Key files:

| File | Purpose |
|---|---|
| `development approach/team_instructions.md` | Canonical team operating model |
| `development approach/agentic_development_architecture.md` | Architecture and rationale |
| `development approach/community_cheat_sheet.md` | Shareable summary |
| `development approach/prompts/` | Role prompts used by HCOM launch scripts |

### Working Pattern

For algorithm work, the orchestrator sends the task to `@algorithm-coder-`.
The coder inspects the code, implements a focused change, runs targeted
verification, and sends a handoff. The orchestrator then asks
`@algorithm-reviewer-` to review the diff and evidence. The task does not move
to commit until blocking findings are resolved or explicitly waived by the
human owner.

For report, dashboard, and documentation work, the same pattern uses
`@ux-coder-` and `@ux-reviewer-`.

For cross-cutting changes, both specialist pairs are used. For example, changing
the anomaly threshold and explaining it in the report requires algorithm review
for the classifier impact and UX review for whether the explanation is clear to
a technical reader who may not be fluent in data science.

### Quality Bar

The coders are expected to follow Google-style Python engineering standards:

- no bare `except:`
- no mutable default arguments
- explicit context managers for resources
- absolute imports only
- type hints throughout
- 80-character line target
- Google-style docstrings for public modules, classes, and functions
- executable scripts structured around `main(argv)`
- hermetic tests for new behaviour
- no `assert` for runtime validation
- readable code over clever code
- small, atomic changes

New packages must not be installed without approval from the human owner or
orchestrator. This keeps dependency growth intentional and reviewable.

The UX and documentation specialists are expected to write in clear British
English for a wide technical audience. They should use examples, tables,
diagrams, charts, and plain definitions where those make the result easier to
understand.
