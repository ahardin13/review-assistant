---
allowed-tools: Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr comment:*), Bash(gh pr review:*), Bash(gh pr list:*), Bash(gh issue view:*), Bash(gh api:*), Bash(git remote:*), Bash(git log:*), Bash(git blame:*), Bash(cat ~/.review-assistant/sessions:*), Bash(cat ~/.claude/REVIEW.md), Bash(cat REVIEW.md), Bash(cat /tmp/pr-:*), Bash(cat <<'EOF' > ~/.review-assistant/sessions/:*), Bash(cat <<'EOF' >> ~/.review-assistant/sessions/:*), Bash(mkdir -p ~/.review-assistant/sessions), Bash(find ~/.review-assistant/sessions:*), Bash(awk:*), Bash(wc:*)
description: Interactively review a pull request with the review-assistant
---

Review a pull request interactively.

**Usage:**

- `/review-assistant <PR_NUMBER>` — review PR in current repo
- `/review-assistant <PR_NUMBER> --repo owner/repo` — review PR in specified repo
- `/review-assistant <PR_NUMBER> --threshold N` — set minimum confidence score (default: 50)

Parse the arguments, then invoke the `review-assistant` skill with `pr_number`, (if provided) `repo`, and (if provided) `threshold`.

If no PR number is provided, show usage and exit.
