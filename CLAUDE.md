Use conventional commit messages for all commits.

## Project

This is a Claude Code plugin with three skills:
- `review-assistant` — thin orchestrator, dispatches to the other two skills
- `reading-pr-context` — gathers PR context, runs code-review analysis, writes session file
- `interactive-diff-review` — all user-facing interaction: overview, file-by-file walkthrough, posting to GitHub

The orchestrator must stay ignorant of implementation details to prevent Claude from inlining the work instead of invoking sub-skills.

## Workflow

Work on `dev` branch locally. When ready to push, squash-merge to main:
```
git checkout main && git merge --squash dev && git commit && git push && git branch -d dev
```
