# Development Approach

This folder contains the documentation for the local agentic development team.

- `agentic_development_architecture.md`: architecture, roles, handoff protocol, review checklist, and Bot Hunter-specific workflow.
- `prompts/coder_prompt.md`: Codex coder role prompt.
- `prompts/reviewer_prompt.md`: Claude reviewer role prompt.
- `prompts/orchestrator_prompt.md`: orchestrator role prompt.

The executable helper scripts remain in `scripts/` because they are operational project tooling, not documentation. They load these prompts from this folder when starting HCOM agents.

Claude Code also uses the project-scoped MCP config in `.mcp.json`. The `memory` MCP server is configured there with local storage under `.mcp-memory/`. The storage files are intentionally ignored by git so team memory can persist locally without leaking private notes into the repository.
