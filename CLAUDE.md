Use conventional commit messages for all commits.

## Project

This is a Claude Code plugin with three skills:
- `review-assistant` — thin orchestrator, dispatches to the other two skills
- `reading-pr-context` — gathers PR context, runs code-review analysis, writes session file
- `interactive-diff-review` — all user-facing interaction: overview, file-by-file walkthrough, posting to GitHub

The orchestrator must stay ignorant of implementation details to prevent Claude from inlining the work instead of invoking sub-skills.

## Workflow

Use /writing-skills when creating or modifying skill files.

Commit to a working branch. Squash when merging to main.
