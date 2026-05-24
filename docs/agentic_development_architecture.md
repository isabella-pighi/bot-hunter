# Agentic Development Architecture

This project can be developed with a multi-agent workflow where one coding agent implements changes and a second agent reviews the work before it is accepted. The recommended local setup uses Claude Code and Codex CLI as separate command-line agents connected through HCOM.

HCOM is used as the coordination layer: each agent runs in its own terminal, but HCOM gives them a shared message bus, activity log, file-edit awareness, transcript access, and the ability to notify or wake each other when work changes state.

## Goals

- Use different model families for independent implementation and review judgement.
- Keep engineering work traceable through explicit handoff messages.
- Reduce self-review bias by ensuring the reviewer is not the same agent that wrote the code.
- Preserve human control over scope, merges, pushes, and final product decisions.
- Make the workflow reproducible for future Bot Hunter changes.

## Fit for Bot Hunter

This approach is a strong fit for Bot Hunter because the project combines implementation work with judgement-heavy analysis. The code needs to parse data, run classifiers, generate `submission.tsv`, and serve a local dashboard, but the deliverable also depends on methodology, probability claims, business recommendations, and a written explanation. Those are exactly the places where an independent reviewer can catch weak assumptions.

Using different model families is valuable here. A single agent can overfit to its own explanation of why a classifier, threshold, or probability estimate is reasonable. Having one agent implement and another review creates a second pass on questions such as:

- Are the anomaly signals actually supported by the data?
- Does the report overstate confidence in the absence of labels?
- Does `submission.tsv` match the current classifier logic?
- Are generated artifacts reproducible from the source code?
- Are threshold choices and false-positive tradeoffs clearly stated?
- Does the dashboard communicate results to a business user without requiring data science context?

The recommended default is Codex CLI as the coder and Claude Code as the reviewer. Codex is well suited to terminal-driven implementation, local edits, test runs, and commits. Claude is well suited to broad critique of methodology, report clarity, probability reasoning, and business-facing recommendations. This pairing can be reversed when the task is mainly architecture or long-context design exploration.

HCOM is appropriate because the goal is not a large autonomous platform. The useful property is lightweight local coordination: tagged agents, explicit messages, activity awareness, and review handoffs inside the same repository. The value comes from disciplined communication, not from having more agents for its own sake.

The main risk is process overhead. A full orchestrator, coder, and reviewer loop is worthwhile for changes that affect predictions, probability estimates, report conclusions, or generated deliverables. It is probably unnecessary for small copy edits or low-risk documentation changes.

The second risk is false confidence. Agreement between two agents is not statistical validation. For this project, the reviewer should explicitly challenge any claim that sounds measured but is not label-calibrated. In particular, fraud probability estimates should be treated as operational confidence estimates unless future work adds ground truth labels, chargeback evidence, or manual review outcomes.

The practical recommendation is to keep this workflow lightweight and gated. Use HCOM for communication and state, but require concrete evidence at every review point: the diff, commands run, artifact changes, reviewer findings, and either resolution or explicit human waiver. The human owner remains responsible for the final product decision.

## Roles

### Human Owner

The human owner defines the task, accepts or rejects tradeoffs, approves external actions, and decides when work is complete. The human also chooses which agent is the coder and which agent is the reviewer for a given task.

### Orchestrator

The orchestrator is the process owner. It may be a human, a lightweight script, or a dedicated agent session. Its responsibilities are:

- Convert the user request into a compact task brief.
- Select the coder and reviewer model pairing.
- Create or identify the working branch.
- Start agents under HCOM with stable tags.
- Track task state: planned, coding, review, revision, verification, ready.
- Ensure review findings are resolved or explicitly waived.
- Run final verification commands before merge or push.

The orchestrator should not silently overwrite either agent's work. It coordinates and records decisions.

### Coder Agent

The coder agent owns implementation. For this repo, Codex is a strong default coder because it is optimized for terminal-driven implementation, edits, tests, and commits.

Coder responsibilities:

- Inspect the repo before changing files.
- Make focused edits on the assigned task.
- Run targeted tests or smoke checks.
- Publish a handoff message containing changed files, commands run, known risks, and review request.
- Wait for reviewer feedback before declaring the task complete.

### Reviewer Agent

The reviewer agent owns critique. Claude Code is a strong default reviewer because it is useful for broad reasoning, architectural critique, and bug-risk analysis.

Reviewer responsibilities:

- Review the diff, not only the coder's summary.
- Prioritize correctness, security, maintainability, test coverage, and brief alignment.
- Return actionable findings with file and line references where possible.
- Distinguish blocking issues from optional improvements.
- Re-review revisions until no blocking issues remain.

The reviewer should be read-only by default. If the reviewer proposes code, the coder should apply it unless the orchestrator explicitly changes the workflow.

## HCOM Runtime Pattern

Run each agent from the project root so they share the same repository context:

```bash
cd /Users/isabella/bot-hunter
```

Check local prerequisites:

```bash
./scripts/check-agent-team
```

Start the coder:

```bash
./scripts/start-coder
```

Start the reviewer:

```bash
./scripts/start-reviewer
```

Start both default agents:

```bash
./scripts/start-agent-team
```

Optional orchestrator:

```bash
./scripts/start-orchestrator
```

For headless review, the reviewer can be started with a standing instruction:

```bash
HCOM_TAG=reviewer hcom claude -p "Act as read-only reviewer. Watch for coder handoffs, inspect the git diff, and reply with blocking findings first."
```

Exact command flags may vary by local HCOM, Claude Code, and Codex CLI versions. The stable requirements are the tags, shared working directory, and explicit handoff messages.

The repository also includes role prompts in `agents/`. The helper scripts pass these prompts to HCOM with `--hcom-system-prompt`, so each agent starts with the expected role and handoff discipline.

## Handoff Protocol

Each handoff message should be short and structured. This keeps transcripts useful and avoids forcing the reviewer to infer state.

### Task Brief

Sent by the orchestrator to the coder and reviewer:

```text
@coder @reviewer TASK bot-hunter-<id>
Goal: <one sentence>
Scope: <files or feature area>
Acceptance: <observable success criteria>
Constraints: <runtime, dependencies, style, data assumptions>
Review mode: blocking findings only, then residual risks
```

### Coder Ready for Review

Sent by the coder:

```text
@reviewer REVIEW_REQUEST bot-hunter-<id>
Summary: <what changed>
Files: <main files>
Verification: <commands run and results>
Known risks: <risks or "none known">
Diff base: <branch or commit>
```

### Reviewer Findings

Sent by the reviewer:

```text
@coder REVIEW_RESULT bot-hunter-<id>
Decision: changes_requested | approved
Findings:
- Severity: <blocker|major|minor>
  File: <path:line>
  Issue: <specific problem>
  Fix: <specific recommendation>
Residual risk: <remaining concern or "none">
```

### Revision Handoff

Sent by the coder after fixes:

```text
@reviewer REVISION_READY bot-hunter-<id>
Resolved:
- <finding and fix>
Verification: <commands run>
Open: <anything intentionally not fixed>
```

### Final Decision

Sent by the orchestrator:

```text
@coder @reviewer TASK_CLOSED bot-hunter-<id>
Decision: accepted | rejected | deferred
Commit: <sha>
Reason: <short rationale>
```

## Branch and Commit Policy

For small tasks, the orchestrator can allow work directly on `main` if the repo owner approves. For larger changes, use a task branch:

```bash
git switch -c agent/<task-id>
```

Commit only after:

- The working tree contains only intentional changes.
- The pipeline or targeted tests have run.
- The reviewer has approved or the human owner has waived open findings.
- Generated artifacts are included only when they are part of the requested deliverable.

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

## Bot Hunter Specific Workflow

For classifier or dashboard changes:

1. Orchestrator defines the expected behavior and artifact changes.
2. Coder updates parser, classifier, report, dashboard, or docs.
3. Coder runs:

```bash
python3 -m py_compile bot_hunter/*.py
python3 -m bot_hunter.cli run --input /Users/isabella/Downloads/bot-hunter-dataset.tsv
```

4. Reviewer inspects:

```bash
git diff --stat
git diff
```

5. Reviewer verifies that `submission.tsv`, `artifacts/summary.json`, and report files are consistent with the changed logic.
6. Orchestrator approves commit and push.

## Failure Modes and Controls

| Risk | Control |
| --- | --- |
| Agents edit the same file at the same time | Use HCOM event awareness and require coder ownership of edits. |
| Reviewer rubber-stamps coder work | Require diff-based findings and explicit residual risk. |
| Agents optimize for passing tests while missing the brief | Keep acceptance criteria in every task handoff. |
| Generated artifacts drift from source logic | Re-run the pipeline before commit. |
| Credentials or raw data leak into git | Review `git diff --cached` and `.gitignore` before commit. |
| Infinite review loops | Orchestrator limits review cycles, then asks the human owner to decide. |

## Recommended Default Pairing

Use Codex CLI as coder and Claude Code as reviewer for implementation-heavy work. Reverse the pairing when the task is mostly design exploration or long-context architecture analysis, with Claude drafting the approach and Codex reviewing operational feasibility.

The important property is independence: the reviewer should not be asked to defend the coder's earlier reasoning. It should inspect the repository state and produce its own judgement.
