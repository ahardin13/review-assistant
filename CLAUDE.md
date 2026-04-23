Use conventional commit messages for all commits.

## Project

This is a Claude Code plugin with four skills:
- `review-assistant` — thin orchestrator, dispatches to one of the walkthrough skills
- `reading-pr-context` — gathers PR context, runs code-review analysis, writes session file
- `interactive-diff-review` — user-facing walkthrough: overview, file-by-file review, posting to GitHub
- `auto-draft-review` — non-interactive path for `--auto` mode: posts every analyzer finding as a pending GitHub review for the user to finalize on github.com

The orchestrator must stay ignorant of implementation details to prevent Claude from inlining the work instead of invoking sub-skills.

## Workflow

Use /writing-skills when creating or modifying skill files.

Commit to a working branch. Squash when merging to main.
