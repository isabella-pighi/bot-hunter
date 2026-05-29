# Agentic Development Team Instructions

This is the canonical instruction text for the Bot Hunter local development team. It consolidates the operating model, roles, HCOM usage, MCP memory setup, handoff protocol, review policy, and git ownership rules used for this repository.

## Purpose

Bot Hunter is developed with a small multi-agent team:

- A human owner who sets direction and makes final product decisions.
- An algorithm and engineering coder/reviewer pair.
- A UX, report, and documentation coder/reviewer pair.
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
- Codex CLI as both specialist coders.
- Claude Code as both specialist reviewers.
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

Start both specialist coder/reviewer pairs:

```bash
./scripts/start-agent-team
```

Start the orchestrator:

```bash
./scripts/start-orchestrator
```

Start roles individually:

```bash
./scripts/start-algorithm-coder
./scripts/start-algorithm-reviewer
./scripts/start-ux-coder
./scripts/start-ux-reviewer
./scripts/start-orchestrator
```

Compatibility aliases:

```bash
./scripts/start-coder      # starts algorithm-coder
./scripts/start-reviewer   # starts algorithm-reviewer
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
hcom kill tag:algorithm-coder
hcom kill tag:algorithm-reviewer
hcom kill tag:ux-coder
hcom kill tag:ux-reviewer
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

All task execution must be delegated through HCOM to the specialist coder/reviewer pair(s). The orchestrator must not perform task work on its own, must not self-assign implementation, and must not advance a task until the relevant reviewer has responded to the coder's handoff. If a task touches both domains, route it to both specialist pairs and wait for both reviewer responses before committing.

The orchestrator's authority is:

- Process ownership.
- Task routing.
- Acceptance decisions.
- Git commits and pushes after required evidence is present.

The orchestrator must:

- Convert user requests into compact task briefs.
- Assign the appropriate specialist pair or both pairs.
- Keep task state explicit: planned, coding, review, revision, verification, ready.
- Require evidence before accepting work: diff, commands run, artifacts changed, and review result.
- Ensure review findings are resolved or explicitly waived by the human owner.
- Own git commits and pushes once coder work has passed review or the human owner has waived remaining findings.
- Before committing, inspect `git status`, confirm unrelated changes are not included, and summarize exactly what will be committed.
- Never commit or push code that the reviewer has rejected unless the human owner explicitly instructs it to do so.
- Never perform implementation, testing, editing, or review work yourself; only coordinate the team and manage the workflow.
- Keep the process lightweight for low-risk changes.

The orchestrator should not silently overwrite any agent's work.

### Algorithm and Engineering Coder

The algorithm and engineering coder implements changes to the detection pipeline, data parsing, feature engineering, classifier logic, runtime behavior, tests, and supportability. Codex CLI is the default agent.

This coder must:

- Inspect the relevant code before editing.
- Keep changes focused on the task brief.
- Prefer existing repo patterns and standard-library Python unless the task explicitly allows new dependencies.
- Follow the Google-style Python checklist:
  - Never use bare `except:`.
  - Never use mutable default arguments.
  - Use context managers for files, sockets, and other resources.
  - Use absolute imports only. Do not use relative imports or `from module import *`.
  - Use type hints throughout, including modern PEP 585 and PEP 604 syntax.
  - Keep line length at 80 characters unless there is a strong exception such as a URL.
  - Run linters and formatters before handoff, including `pylint` and a formatter such as `black` or `yapf`.
  - Write Google-style docstrings for public modules, classes, and functions with `Args:`, `Returns:`, and `Raises:` sections where applicable.
  - Put executable logic inside `main(argv)` and use `if __name__ == '__main__': sys.exit(main(sys.argv[1:]))`.
  - Write hermetic tests for new behavior.
  - Never use `assert` for core application validation or preconditions.
  - Prefer readability over cleverness.
  - Break large work into small, atomic changes that leave the codebase better than it was.
- Apply Google-style engineering standards: readable Python, simple design, clear names, deterministic behavior, explicit assumptions, useful errors, and maintainable tests.
- Make runtime behavior observable and supportable through clear logs, metrics, summaries, or status output when appropriate.
- Add comments where they clarify algorithmic choices, assumptions, or non-obvious tradeoffs.
- Run targeted verification before handoff.
- Treat generated artifacts as deliverables only when the task requires them.
- Not push or merge unless the human owner or orchestrator explicitly asks.
- Publish a review handoff before declaring work complete.

### Algorithm and Engineering Reviewer

The algorithm and engineering reviewer independently critiques algorithm, pipeline, parser, classifier, test, runtime, and supportability changes. Claude Code is the default agent.

This reviewer is read-only by default. It must not edit files unless the human owner or orchestrator explicitly changes its role.

This reviewer must:

- Inspect the actual git diff, not only the coder's summary.
- Apply Google-style engineering standards: readability, simplicity, maintainability, useful tests, explicit assumptions, predictable behavior, and minimal unnecessary abstraction.
- Lead with blocking bugs, correctness risks, security risks, missing verification, data-quality risks, and brief mismatches.
- Challenge unsupported probability, fraud, or model-performance claims.
- Verify generated artifacts match source-code behavior when artifacts are part of the task.
- Check that runtime behavior is observable and supportable.
- Return actionable findings with file and line references where possible.
- Distinguish blocking findings from optional improvements.
- Re-review revisions until no blocking issues remain.

### UX, Report, and Documentation Coder

The UX, report, and documentation coder implements changes to the local web interface, generated reports, user-facing copy, documentation, and developer guidance. Codex CLI is the default agent.

This coder must:

- Inspect the relevant code and docs before editing.
- Keep changes focused on the task brief.
- Follow the Google-style Python checklist when code is involved:
  - Never use bare `except:`.
  - Never use mutable default arguments.
  - Use context managers for files, sockets, and other resources.
  - Use absolute imports only. Do not use relative imports or `from module import *`.
  - Use type hints throughout, including modern PEP 585 and PEP 604 syntax.
  - Keep line length at 80 characters unless there is a strong exception such as a URL.
  - Run linters and formatters before handoff, including `pylint` and a formatter such as `black` or `yapf`.
  - Write Google-style docstrings for public modules, classes, and functions with `Args:`, `Returns:`, and `Raises:` sections where applicable.
  - Put executable logic inside `main(argv)` and use `if __name__ == '__main__': sys.exit(main(sys.argv[1:]))`.
  - Write hermetic tests for new behavior.
  - Never use `assert` for core application validation or preconditions.
  - Prefer readability over cleverness.
  - Break large work into small, atomic changes that leave the codebase better than it was.
- Apply UX industry standards: clarity, hierarchy, accessibility, responsive layout, readable tables and charts, useful labels, and business-user comprehension.
- Keep documentation accurate, concise, task-oriented, easy to scan, and aligned with the actual code and scripts.
- Ensure text fits, tables remain readable, and reports communicate assumptions and results clearly.
- Avoid visible in-app text that explains internal implementation details.
- Run targeted verification before handoff.
- Treat generated report artifacts as deliverables only when the task requires them.
- Not push or merge unless the human owner or orchestrator explicitly asks.

### UX, Report, and Documentation Reviewer

The UX, report, and documentation reviewer independently critiques changes to the local web interface, generated reports, user-facing copy, documentation, and developer guidance. Claude Code is the default agent.

This reviewer is read-only by default. It must not edit files unless the human owner or orchestrator explicitly changes its role.

This reviewer must:

- Inspect the actual git diff, not only the coder's summary.
- Apply UX industry standards: clarity, hierarchy, accessibility, responsive behavior, readable visualizations, business-user comprehension, and low-friction workflows.
- Check report and documentation accuracy against the current code, commands, artifacts, and assumptions.
- Challenge unclear copy, unsupported conclusions, confusing metrics, weak information hierarchy, and visuals that obscure rather than explain.
- Verify user-facing output is understandable without requiring data science or engineering context.
- Return actionable findings with file and line references where possible.
- Distinguish blocking findings from optional improvements.
- Re-review revisions until no blocking issues remain.

## Work Routing

The orchestrator routes work by domain:

- Algorithm/engineering pair: `bot_hunter/data.py`, `bot_hunter/heuristics.py`, `bot_hunter/ml.py`, `bot_hunter/pipeline.py`, tests, runtime observability, supportability, classifier output, probability logic, and generated `submission.tsv`.
- UX/docs pair: `bot_hunter/web.py`, `bot_hunter/report.py`, README, development approach docs, generated report copy/layout, dashboard comprehension, and business-user experience.
- Both pairs: changes that affect user-visible results and underlying methodology, such as changing classifier scores and explaining them in the dashboard/report.

When both pairs are involved, the orchestrator should sequence work to avoid edit conflicts and require both relevant reviewers to approve before committing.

## Handoff Protocol

Use short, structured HCOM messages. Keep transcripts useful and avoid relying on implicit state.

### Task Brief

Sent by the orchestrator:

```text
@algorithm-coder- @algorithm-reviewer- TASK bot-hunter-<task-id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings first, then residual risks
```

For UX/report/documentation work, target `@ux-coder- @ux-reviewer-`. For cross-domain work, seed both pairs in the task brief.

### Coder Ready for Review

Sent by the coder:

```text
@<specialist-reviewer-tag>- REVIEW_REQUEST bot-hunter-<task-id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

### Reviewer Result

Sent by the reviewer:

```text
@<specialist-coder-tag>- REVIEW_RESULT bot-hunter-<task-id>
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
@<specialist-reviewer-tag>- REVISION_READY bot-hunter-<task-id>
Resolved:
- <finding and fix>
Verification: <commands run>
Open: <anything intentionally not fixed>
```

### Task Closed

Sent by the orchestrator:

```text
@<assigned-team-tags> TASK_CLOSED bot-hunter-<task-id>
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

The algorithm and engineering reviewer should inspect:

```bash
git diff --stat
git diff
```

The algorithm and engineering reviewer should verify that `submission.tsv`, `artifacts/summary.json`, and report files are consistent with the changed logic when those artifacts are affected.

For dashboard, report, or documentation changes, the UX/docs coder should run targeted rendering or content checks appropriate to the change. If the HTTP interface changes, verify the local app can still serve and the page remains business-readable.

## Review Checklist

The algorithm and engineering reviewer should check:

- Does the implementation satisfy the stated task?
- Are data assumptions explicit?
- Are false positives, false negatives, or probability claims justified?
- Is the HTTP interface still runnable locally?
- Are generated outputs reproducible from source?
- Are dependency choices minimal and documented?
- Are tests or smoke checks proportional to the change?
- Are secrets, credentials, raw private data, and local-only files excluded?

The UX, report, and documentation reviewer should check:

- Is the intended business user able to understand the result without data science context?
- Is the interface or report hierarchy clear and scannable?
- Are labels, tables, and charts readable across reasonable viewport sizes?
- Are assumptions and limitations visible where they affect interpretation?
- Is documentation accurate against the current code, commands, and scripts?
- Does the page/report avoid internal implementation noise in user-facing copy?

## Failure Modes and Controls

| Risk | Control |
| --- | --- |
| Agents edit the same file at the same time | Use HCOM event awareness and require coder ownership of edits. |
| Reviewer rubber-stamps coder work | Require diff-based findings and explicit residual risk. |
| Agents optimize for passing tests while missing the brief | Keep acceptance criteria in every task handoff. |
| Specialist teams make inconsistent changes | Orchestrator sequences work and requires cross-domain review for shared behavior. |
| Generated artifacts drift from source logic | Re-run the pipeline before commit. |
| Credentials or raw data leak into git | Review `git diff --cached` and `.gitignore` before commit. |
| Infinite review loops | Orchestrator limits review cycles, then asks the human owner to decide. |
| Orchestrator starts implementing | Stop and restate role boundary: orchestrator coordinates only. |

## Specialist Pairings

- Algorithm and engineering: Codex CLI coder, Claude Code reviewer.
- UX, report, and documentation: Codex CLI coder, Claude Code reviewer.
- Orchestrator: Codex CLI, unchanged from the original role definition.

The important property is independence. The reviewer should not defend the coder's reasoning. It should inspect the repository state and produce its own judgement.
