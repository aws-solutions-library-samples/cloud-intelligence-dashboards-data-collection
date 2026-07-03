# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Steering lives in `.ai/specs`

This project keeps its AI steering in the `.ai/specs` folder so it can be shared
across tools (Kiro reads it via thin redirects in `.kiro/steering/`; Claude
imports it here). Treat these as the source of truth and follow them:

- Overall coding standards: @.ai/specs/coding-standards.md
- Implementation guide (architecture, flows): @.ai/specs/implementation.md

Module- or aspect-specific steering lives in subfolders of `.ai/specs`
(for example, @.ai/specs/data-exports/data-exports-aggregation.md). When working
on a specific module, check for and follow any matching subfolder steering.

## How to use `.ai/specs`

- **Overall guidance** → `coding-standards.md` and `implementation.md` apply to
  all or nearly all assets.
- **Module or aspect-specific guidance** → add or read an appropriately named
  subfolder under `.ai/specs/`.
- **Local or experimental guidance** → put it under `.ai/local/`, which is
  gitignored (not committed or shared).

When you establish a new convention during a task (e.g. a testing pattern or a
security rule), record it in the appropriate `.ai/specs` file rather than only
in a commit message, so both Kiro and Claude pick it up next time.
