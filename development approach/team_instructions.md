# Agentic Development Team Instructions

This is the canonical instruction text for the Bot Hunter local development team. It consolidates the operating model, roles, HCOM usage, MCP memory setup, handoff protocol, review policy, and git ownership rules used for this repository.

## Purpose

Bot Hunter is developed with a small multi-agent team:

- A human owner who sets direction and makes final product decisions.
- A coder agent that implements changes.
- A reviewer agent that independently reviews the coder's work.
- An orchestrator agent that coordinates the workflow and owns git commits and pushes.

The goal is not to maximize autonomy. The goal is disciplined local collaboration with clear evidence, independent review, and human control.

## Why This Fits Bot Hunter

This project mixes implementation with judgement-heavy analysis. The code parses click data, runs bot classifiers, generates `submission.tsv`, and serves a local dashboard. The deliverable also depends on methodology, probability claims, business recommendations, and written explanation.

Independent review is valuable because a single agent can overfit to its own explanation of why a classifier, threshold, or probability estimate is reasonable. The reviewer must challenge weak assumptions, especially around:

- Whether anomaly signals are supported by the data.
- Whether the report overstates confidence in the absence of labels.
- Whether `submission.tsv` matches the current classifier logic.
- Whether generated artifacts are reproducible from source.
- Whether threshold choices and false-positive tradeoffs are explicit.
- Whether the dashboard is understandable to a business user.

Use the full orchestrator/coder/reviewer loop for changes that affect predictions, probability estimates, report conclusions, generated deliverables, or the local development workflow. For small copy edits, keep the process lightweight.

Agreement between two agents is not statistical validation. Fraud probability estimates remain operational confidence estimates unless future work adds labels, chargeback evidence, or manual review outcomes.

## Tools

The local team uses:

- HCOM as the communication and launch layer.
- Codex CLI as the default coder.
- Claude Code as the default reviewer.
- Codex CLI as the default orchestrator.
- MCP memory through `@modelcontextprotocol/server-memory`.

Claude Code reads the project-scoped MCP config in `.mcp.json`. Codex CLI has a separate MCP registry, so run `./scripts/setup-memory-mcp` once on a development machine to configure Codex to use the same memory server. Both should use `.mcp-memory/claude-memory.jsonl` as local memory storage.

The memory store is ignored by git. Use MCP memory for working context, not for durable project documentation. Anything that must be shared should be committed to the repository.

## Setup

From the repository root:

```bash
cd /Users/isabella/bot-hunter
./scripts/setup-memory-mcp
./scripts/check-agent-team
```

`./scripts/check-agent-team` should confirm:

- HCOM is installed.
- Codex CLI is installed.
- Claude Code is installed.
- `bunx` is installed for the MCP memory server.
- `.mcp.json` exists.
- Claude memory MCP is connected.
- Codex memory MCP is configured.

## Starting and Stopping

Start the default coder and reviewer:

```bash
./scripts/start-agent-team
```

Start the orchestrator:

```bash
./scripts/start-orchestrator
```

Start roles individually:

```bash
./scripts/start-coder
./scripts/start-reviewer
./scripts/start-orchestrator
```

Check active agents:

```bash
hcom list
```

Stop the whole team:

```bash
hcom kill all
```

Stop one role by tag:

```bash
hcom kill tag:coder
hcom kill tag:reviewer
hcom kill tag:orchestrator
```

If a local server blocks the orchestrator from using port `8000`, identify and kill only that process:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

## Role Rules

### Human Owner

The human owner defines task goals, accepts or rejects tradeoffs, approves external actions, and decides when work is complete. The human owner may waive reviewer findings, but waivers must be explicit.

### Orchestrator

The orchestrator coordinates the team. It must not implement code, edit application files, write tests, refactor, or directly fix reviewer findings. Implementation belongs to the coder. Review belongs to the reviewer.

The orchestrator's authority is:

- Process ownership.
- Task routing.
- Acceptance decisions.
- Git commits and pushes after required evidence is present.

The orchestrator must:

- Convert user requests into compact task briefs.
- Assign coder and reviewer.
- Keep task state explicit: planned, coding, review, revision, verification, ready.
- Require evidence before accepting work: diff, commands run, artifacts changed, and review result.
- Ensure review findings are resolved or explicitly waived by the human owner.
- Own git commits and pushes once coder work has passed review or the human owner has waived remaining findings.
- Before committing, inspect `git status`, confirm unrelated changes are not included, and summarize exactly what will be committed.
- Never commit or push code that the reviewer has rejected unless the human owner explicitly instructs it to do so.
- Keep the process lightweight for low-risk changes.

The orchestrator should not silently overwrite any agent's work.

### Coder

The coder implements assigned tasks. Codex CLI is the default coder.

The coder must:

- Inspect the relevant code before editing.
- Keep changes focused on the task brief.
- Prefer existing repo patterns and standard-library Python unless the task explicitly allows new dependencies.
- Run targeted verification before handoff.
- Treat generated artifacts as deliverables only when the task requires them.
- Not push or merge unless the human owner or orchestrator explicitly asks.
- Publish a review handoff before declaring work complete.

### Reviewer

The reviewer independently critiques the coder's work. Claude Code is the default reviewer.

The reviewer is read-only by default. It must not edit files unless the human owner or orchestrator explicitly changes its role.

The reviewer must:

- Inspect the actual git diff, not only the coder's summary.
- Lead with blocking bugs, correctness risks, security risks, missing verification, and brief mismatches.
- Challenge unsupported probability, fraud, or model-performance claims.
- Verify generated artifacts match source-code behavior when artifacts are part of the task.
- Return actionable findings with file and line references where possible.
- Distinguish blocking findings from optional improvements.
- Re-review revisions until no blocking issues remain.

## Handoff Protocol

Use short, structured HCOM messages. Keep transcripts useful and avoid relying on implicit state.

### Task Brief

Sent by the orchestrator:

```text
@coder @reviewer TASK bot-hunter-<task-id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

### Coder Ready for Review

Sent by the coder:

```text
@reviewer REVIEW_REQUEST bot-hunter-<task-id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

### Reviewer Result

Sent by the reviewer:

```text
@coder REVIEW_RESULT bot-hunter-<task-id>
Decision: changes_requested | approved
Findings:
- Severity: <blocker|major|minor>
  File: <path:line>
  Issue: <specific problem>
  Fix: <specific recommendation>
Residual risk: <remaining concern or "none">
```

If there are no blocking findings, the reviewer must say that directly and note residual risk.

### Revision Ready

Sent by the coder:

```text
@reviewer REVISION_READY bot-hunter-<task-id>
Resolved:
- <finding and fix>
Verification: <commands run>
Open: <anything intentionally not fixed>
```

### Task Closed

Sent by the orchestrator:

```text
@coder @reviewer TASK_CLOSED bot-hunter-<task-id>
Decision: accepted | rejected | deferred
Commit: <sha>
Reason: <short rationale>
```

## Git and Branch Policy

For larger changes, use a task branch:

```bash
git switch -c agent/<task-id>
```

For small tasks, direct work on `main` is acceptable only if the human owner approves.

Only the orchestrator should own commits and pushes in the normal team flow. The orchestrator must stage only intentional changes and must not include unrelated dirty files.

Before commit:

- Check `git status --short --branch`.
- Review `git diff`.
- Review `git diff --cached`.
- Confirm tests or smoke checks were run.
- Confirm reviewer approval or explicit human waiver.
- Confirm generated artifacts are included only when they are required deliverables.

Never revert user or agent changes casually. Work with existing changes. Ask the human owner if unrelated changes make the task impossible to isolate.

## Bot Hunter Verification

For classifier, report, dashboard, or submission changes, the coder should run:

```bash
python3 -m py_compile bot_hunter/*.py
python3 -m bot_hunter.cli run --input /Users/isabella/Downloads/bot-hunter-dataset.tsv
```

The reviewer should inspect:

```bash
git diff --stat
git diff
```

The reviewer should verify that `submission.tsv`, `artifacts/summary.json`, and report files are consistent with the changed logic when those artifacts are affected.

## Review Checklist

The reviewer should check:

- Does the implementation satisfy the stated task?
- Are data assumptions explicit?
- Are false positives, false negatives, or probability claims justified?
- Is the HTTP interface still runnable locally?
- Are generated outputs reproducible from source?
- Are dependency choices minimal and documented?
- Are tests or smoke checks proportional to the change?
- Are secrets, credentials, raw private data, and local-only files excluded?

## Failure Modes and Controls

| Risk | Control |
| --- | --- |
| Agents edit the same file at the same time | Use HCOM event awareness and require coder ownership of edits. |
| Reviewer rubber-stamps coder work | Require diff-based findings and explicit residual risk. |
| Agents optimize for passing tests while missing the brief | Keep acceptance criteria in every task handoff. |
| Generated artifacts drift from source logic | Re-run the pipeline before commit. |
| Credentials or raw data leak into git | Review `git diff --cached` and `.gitignore` before commit. |
| Infinite review loops | Orchestrator limits review cycles, then asks the human owner to decide. |
| Orchestrator starts implementing | Stop and restate role boundary: orchestrator coordinates only. |

## Default Pairing

Use Codex CLI as coder and Claude Code as reviewer for implementation-heavy work. Reverse the pairing only when the task is mainly architecture or long-context design exploration, with Claude drafting the approach and Codex reviewing operational feasibility.

The important property is independence. The reviewer should not defend the coder's reasoning. It should inspect the repository state and produce its own judgement.

