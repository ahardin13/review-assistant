---
allowed-tools: Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr comment:*), Bash(gh pr review:*), Bash(gh pr list:*), Bash(gh issue view:*), Bash(gh api:*), Bash(git remote:*), Bash(git log:*), Bash(git blame:*), Bash(cat ${CLAUDE_PLUGIN_DATA}/sessions:*), Bash(cat ~/.claude/REVIEW.md), Bash(cat REVIEW.md), Bash(cat ${CLAUDE_PLUGIN_DATA}/pr-:*), Bash(cat <<'EOF' > ${CLAUDE_PLUGIN_DATA}/sessions/:*), Bash(cat <<'EOF' >> ${CLAUDE_PLUGIN_DATA}/sessions/:*), Bash(mkdir -p ${CLAUDE_PLUGIN_DATA}/sessions), Bash(find ${CLAUDE_PLUGIN_DATA}/sessions:*), Bash(awk:*), Bash(wc:*)
description: Interactively review a pull request with the review-assistant
---

Review a pull request interactively.

**Usage:**

- `/review-assistant <PR_NUMBER>` — review PR in current repo
- `/review-assistant <PR_NUMBER> --repo owner/repo` — review PR in specified repo
- `/review-assistant <PR_NUMBER> --threshold N` — set minimum confidence score (default: 50)

If no PR number is provided, show usage and exit.

## You are a dispatcher. Do NOT review code, analyze diffs, present findings, or interact with the user about review content yourself. Do NOT pause, summarize, or wait for user input between steps — proceed immediately from step 2 to step 3.

### 1. Parse inputs

- `pr_number`: required
- `repo`: optional (default: parse from `git remote get-url origin`)
- `threshold`: optional confidence threshold (default: 50)

If no repo can be determined, exit: "Run from within the repo, or pass --repo owner/repo."

### 2. Gather context and run analysis

**Call:** `Skill("review-assistant:reading-pr-context", args: "pr_number=<N> repo=<owner/repo> threshold=<T>")`

This skill handles everything: PR metadata, diff, eligibility checks, session file creation, REVIEW.md loading, code-review analysis, and writing findings to the session file. It returns the session file path. **Immediately proceed to step 3 — do not pause or present any output to the user.**

### 3. Interactive walkthrough, summary, and posting

**Call:** `Skill("review-assistant:interactive-diff-review", args: "pr_number=<N> repo=<owner/repo> session_file=<path>")`

This skill handles everything: overview presentation, file-by-file walkthrough, finding decisions, summary, re-review, and GitHub posting. When it completes, the review is done.
