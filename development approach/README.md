# Development Approach

This folder contains the documentation for the local agentic development team.

- `team_instructions.md`: canonical consolidated instructions for the team.
- `agentic_development_architecture.md`: architecture, roles, handoff protocol, review checklist, and Bot Hunter-specific workflow.
- `prompts/coder_prompt.md`: Codex coder role prompt.
- `prompts/reviewer_prompt.md`: Claude reviewer role prompt.
- `prompts/orchestrator_prompt.md`: orchestrator role prompt.

The executable helper scripts remain in `scripts/` because they are operational project tooling, not documentation. They load these prompts from this folder when starting HCOM agents.

Claude Code uses the project-scoped MCP config in `.mcp.json`. Codex CLI uses its user-level MCP registry, which can be configured with `./scripts/setup-memory-mcp`. Both point at the same local storage under `.mcp-memory/`. The storage files are intentionally ignored by git so team memory can persist locally without leaking private notes into the repository.
