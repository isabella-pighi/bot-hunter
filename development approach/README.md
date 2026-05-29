# Development Approach

This folder contains the documentation for the local agentic development team.

- `team_instructions.md`: canonical consolidated instructions for the team.
- `community_cheat_sheet.md`: shareable summary of the local agentic development team pattern.
- `agentic_development_architecture.md`: architecture, roles, handoff protocol, review checklist, and Bot Hunter-specific workflow.
- `prompts/algorithm_coder_prompt.md`: Codex algorithm and engineering coder role prompt.
- `prompts/algorithm_reviewer_prompt.md`: Claude algorithm and engineering reviewer role prompt.
- `prompts/ux_coder_prompt.md`: Codex UX, report, and documentation coder role prompt.
- `prompts/ux_reviewer_prompt.md`: Claude UX, report, and documentation reviewer role prompt.
- `prompts/orchestrator_prompt.md`: orchestrator role prompt.

The executable helper scripts remain in `scripts/` because they are operational project tooling, not documentation. They load these prompts from this folder when starting HCOM agents.

Claude Code uses the project-scoped MCP config in `.mcp.json`. Codex CLI uses its user-level MCP registry, which can be configured with `./scripts/setup-memory-mcp`. Both point at the same local storage under `.mcp-memory/`. The storage files are intentionally ignored by git so team memory can persist locally without leaking private notes into the repository.

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
