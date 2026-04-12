# References

Agent-legible distillations of external tools, libraries, and conventions used in this project.

Read files in this directory before implementing anything that involves the tool or pattern they describe.

## Naming convention

- `<tool-name>.md` — distilled reference for a specific library or tool
- `<topic>.md` — project-specific convention (e.g. `testing-strategy.md`, `database-conventions.md`)

## What belongs here

- How this project uses a specific external library or tool (not the library's own docs — a distilled, project-scoped summary)
- Any knowledge about external tools or conventions that currently lives only in someone's head or a Slack thread

## What does not belong here

- Full library documentation (too large for agent context)
- Feature specifications (those go in `specs/features/`)
- Architectural decisions (those go in `specs/architecture/decisions/`)

## Current references

| File | Covers |
|---|---|
| `AI_operating_system_video_transcriptions.md` | Source video transcriptions — context for original architecture decisions |
| `python-ai-project-structure.md` | Python project structure conventions for AI systems |
