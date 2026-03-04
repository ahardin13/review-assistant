---
name: review-assistant
description: Use when the user invokes /review-assistant to interactively review a pull request. Do not use for automated/silent reviews.
---

# Review Assistant

You are a dispatcher. You call two skills in sequence. You do NOT review code, analyze diffs, present findings, or interact with the user about review content yourself.

**Do NOT:** fetch diffs, read source files, analyze code, present findings, or ask the user about findings. The skills do all of this.

**File I/O:** Use `Bash` with heredocs or `>>` for session/temp files — not Write, Read, or Edit tools.

## Sequence

### 1. Parse inputs

- `pr_number`: required
- `repo`: optional (default: parse from `git remote get-url origin`)
- `threshold`: optional confidence threshold (default: 50)

If no repo can be determined, exit: "Run from within the repo, or pass --repo owner/repo."

### 2. Gather context and run analysis

**Call:** `Skill("review-assistant:reading-pr-context", args: "pr_number=<N> repo=<owner/repo> threshold=<T>")`

This skill handles everything: PR metadata, diff, eligibility checks, session file creation, REVIEW.md loading, code-review analysis, and writing findings to the session file. Wait for it to complete. It returns the session file path.

### 3. Interactive walkthrough, summary, and posting

**Call:** `Skill("review-assistant:interactive-diff-review", args: "pr_number=<N> repo=<owner/repo> session_file=<path>")`

This skill handles everything: overview presentation, file-by-file walkthrough, finding decisions, summary, re-review, and GitHub posting. When it completes, the review is done.
