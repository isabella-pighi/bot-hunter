# Community Cheat Sheet: Local Agentic Development Team

This repo was built with a local multi-agent workflow for Bot Hunter: a Python app that detects likely bot clicks, generates `submission.tsv`, serves a local dashboard, and produces analysis reports.

The useful pattern is not "more agents". It is clear ownership, independent review, observable evidence, and human control.

## Team Shape

Use two specialist coder/reviewer pairs plus one orchestrator.

| Role | Model/tool | Owns |
| --- | --- | --- |
| Orchestrator | Codex CLI | Task routing, acceptance criteria, review gates, commits, pushes |
| Algorithm coder | Codex CLI | Data parsing, features, classifiers, tests, runtime supportability |
| Algorithm reviewer | Claude Code | Correctness, methodology, engineering quality, probability claims |
| UX/docs coder | Codex CLI | Dashboard, report, copy, README, developer docs |
| UX/docs reviewer | Claude Code | UX quality, report clarity, documentation accuracy |

The orchestrator does not code. It coordinates, checks evidence, and owns git operations after review approval or explicit human waiver.

## Tooling

- HCOM: local communication and launch layer for CLI agents.
- Codex CLI: implementation-oriented coding agent and orchestrator.
- Claude Code: independent reviewer for engineering and UX critique.
- MCP memory: `@modelcontextprotocol/server-memory` for shared local working memory.

Memory is local and ignored by git. Anything that must be durable or community-shareable should be committed as docs.

## Setup Commands

From the repo root:

```bash
./scripts/setup-memory-mcp
./scripts/check-agent-team
```

The check should confirm:

```text
ok: hcom
ok: codex
ok: claude
ok: bunx
ok: .mcp.json present
ok: Claude memory MCP connected
ok: Codex memory MCP configured
```

## Start the Team

Start both specialist pairs:

```bash
./scripts/start-agent-team
```

Start the orchestrator:

```bash
./scripts/start-orchestrator
```

Check status:

```bash
hcom list
```

Expected shape:

```text
orchestrator-<name>
algorithm-coder-<name>
algorithm-reviewer-<name>
ux-coder-<name>
ux-reviewer-<name>
```

## Stop the Team

```bash
hcom kill all
```

Stop a specific role:

```bash
hcom kill tag:algorithm-coder
hcom kill tag:algorithm-reviewer
hcom kill tag:ux-coder
hcom kill tag:ux-reviewer
hcom kill tag:orchestrator
```

## Route Work

Algorithm and engineering work:

```text
@algorithm-coder- @algorithm-reviewer- TASK bot-hunter-<id>
Goal: <one sentence>
Scope: parser/features/classifier/tests/runtime
Acceptance: <observable success criteria>
Review mode: blocking findings first, then residual risks
```

UX, report, and documentation work:

```text
@ux-coder- @ux-reviewer- TASK bot-hunter-<id>
Goal: <one sentence>
Scope: dashboard/report/copy/docs
Acceptance: <observable success criteria>
Review mode: blocking findings first, then residual risks
```

Cross-domain work should involve both pairs. The orchestrator should sequence edits to avoid conflicts and require the relevant reviewers to approve.

## Handoff Template

Coder to reviewer:

```text
@<reviewer-tag>- REVIEW_REQUEST bot-hunter-<id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

Reviewer to coder:

```text
@<coder-tag>- REVIEW_RESULT bot-hunter-<id>
Decision: changes_requested | approved
Findings:
- Severity: <blocker|major|minor>
  File: <path:line>
  Issue: <specific problem>
  Fix: <specific recommendation>
Residual risk: <remaining concern or "none">
```

Orchestrator closeout:

```text
@<assigned-team-tags> TASK_CLOSED bot-hunter-<id>
Decision: accepted | rejected | deferred
Commit: <sha>
Reason: <short rationale>
```

## Quality Bars

Algorithm and engineering pair:

- Readable Python with simple design and clear names.
- Explicit assumptions and useful errors.
- Tests proportional to risk.
- Observable runtime behavior: logs, status, metrics, summaries, or debuggable output.
- Probability and fraud claims are challenged unless supported by labels or clear evidence.

UX, report, and documentation pair:

- Business-user comprehension comes first.
- Reports and dashboards need clear hierarchy, labels, assumptions, and limitations.
- Documentation must match the actual code and commands.
- Avoid exposing internal implementation details in user-facing UI copy.

## Git Rules

- Normal flow: only the orchestrator commits and pushes.
- Coder implements; reviewer reviews; orchestrator integrates.
- Orchestrator must inspect:

```bash
git status --short --branch
git diff
git diff --cached
```

- Never include unrelated dirty files.
- Never commit rejected code unless the human owner explicitly waives the finding.
- Generated artifacts are committed only when they are deliverables.

## Bot Hunter Verification

For classifier or pipeline changes:

```bash
python3 -m py_compile bot_hunter/*.py
python3 -m bot_hunter.cli run --input /Users/isabella/Downloads/bot-hunter-dataset.tsv
```

For web/report changes:

```bash
python3 -m bot_hunter.web --port 8000
```

If port `8000` is blocked:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

## What Worked

- Separate model families reduce self-review bias.
- Specialist pairs make review sharper: methodology bugs and UX/report issues are different kinds of risk.
- HCOM tags make routing practical: `@algorithm-coder-`, `@ux-reviewer-`, etc.
- MCP memory is useful for local continuity, but repo docs remain the source of truth.
- A strict orchestrator boundary prevents the coordinator from becoming an unreviewed implementer.

## Main Risks

| Risk | Control |
| --- | --- |
| Process overhead | Use full team only for meaningful changes |
| False confidence from agent agreement | Require evidence and human judgement |
| Conflicting edits | Orchestrator sequences work by domain |
| Reviewer rubber-stamping | Require diff-based findings and residual-risk notes |
| Dirty working tree commits | Orchestrator owns staging and checks `git status` |
| Local memory becoming hidden documentation | Commit durable decisions to the repo |

## Principle

The workflow is useful when it creates better evidence and better review. It is not useful when it adds ceremony without improving the code, report, or product decision.

