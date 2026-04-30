---
allowed-tools: Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr comment:*), Bash(gh pr review:*), Bash(gh pr list:*), Bash(gh issue view:*), Bash(gh api:*), Bash(git remote:*), Bash(git log:*), Bash(git blame:*), Bash(cat $HOME/.local/state/review-assistant/:*), Bash(cat ~/.claude/REVIEW.md), Bash(cat REVIEW.md), Bash(cat <<'EOF' > $HOME/.local/state/review-assistant/:*), Bash(cat <<'EOF' >> $HOME/.local/state/review-assistant/:*), Bash(mkdir -p $HOME/.local/state/review-assistant:*), Bash(find $HOME/.local/state/review-assistant/:*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/classify-and-verify.py:*), Bash(awk:*), Bash(wc:*), Read($HOME/.local/state/review-assistant/**), Read(~/.local/state/review-assistant/**), Read(~/.claude/REVIEW.md), Read(REVIEW.md), Read(/tmp/pr*.diff), Read(/tmp/pr*.patch), Edit($HOME/.local/state/review-assistant/**), Edit(~/.local/state/review-assistant/**), Write($HOME/.local/state/review-assistant/**), Write(~/.local/state/review-assistant/**)
description: Interactively review a pull request with the review-assistant
---

Review a pull request interactively.

**Usage:**

- `/review-assistant <PR_NUMBER>` — review PR in current repo
- `/review-assistant <PR_NUMBER> --repo owner/repo` — review PR in specified repo
- `/review-assistant <PR_NUMBER> --threshold N` — set minimum confidence score (default: 50)
- `/review-assistant <PR_NUMBER> --auto` — skip the interactive walkthrough and post all findings as a pending GitHub review for the user to finalize on github.com

If no PR number is provided, show usage and exit.

## You are a dispatcher. Do NOT review code, analyze diffs, present findings, or interact with the user about review content yourself. Do NOT pause, summarize, or wait for user input between steps — proceed immediately through all steps.

### 1. Parse inputs

- `pr_number`: required
- `repo`: optional (default: parse from `git remote get-url origin`)
- `threshold`: optional confidence threshold (default: 50)
- `auto`: boolean, true if `--auto` present (default: false)

If no repo can be determined, exit: "Run from within the repo, or pass --repo owner/repo."

### 2. Announce mode

**This must be your first user-facing line.** Exactly one of:

- If `auto` is true: `"Running auto review — findings will be posted as a pending review on PR #<N> for you to finalize on GitHub."`
- Otherwise: `"Starting interactive walkthrough — I'll step through PR #<N> with you file by file."`

### 3. Gather context and run analysis

**Call:** `Skill("review-assistant:reading-pr-context", args: "pr_number=<N> repo=<owner/repo> threshold=<T>")`

This skill handles PR metadata, diff, eligibility checks, session file creation, REVIEW.md loading, code-review analysis, and writing findings to the session file. The session file path will be the most recent file matching `$HOME/.local/state/review-assistant/sessions/pr-<N>-*.md`.

**Do not stop here.** This step ends in the middle of the dispatch flow — Step 4 has not yet run. Do not print "session file ready", "returning to orchestrator", or any other closing text. Your next tool call MUST be the Skill dispatch in Step 4.

### 4. Dispatch to the walkthrough skill — MANDATORY NEXT ACTION

This step always runs. There is no condition under which Step 3 is the last step. Pick exactly one based on the `auto` flag and invoke it now:

- If `auto` is true: `Skill("review-assistant:auto-draft-review", args: "pr_number=<N> repo=<owner/repo> session_file=<path>")`
- Otherwise: `Skill("review-assistant:interactive-diff-review", args: "pr_number=<N> repo=<owner/repo> session_file=<path>")`

The review is only complete after this dispatched skill finishes — not after Step 3.
