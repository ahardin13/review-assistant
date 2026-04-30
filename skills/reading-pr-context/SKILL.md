---
name: reading-pr-context
description: Use when starting a PR review and the session file needs to be created or refreshed. Not user-facing — invoked by the orchestrator only.
---

# Reading PR Context

Gather all context for a PR review: metadata, diff, linked issues, REVIEW.md guidelines, and code-review analysis. Write everything to a session file. Do not present anything to the user — the calling skill handles that.

**File I/O:** Use `Bash` with heredocs or `>>` for session/temp files — not Write, Read, or Edit tools.

## Inputs

- `pr_number`: required
- `repo`: owner/repo
- `threshold`: confidence threshold (default: 50)

## Step 1: Clean up old sessions

Data dir: `$HOME/.local/state/review-assistant` (kept OUT of `~/.claude/` so "always allow" permission rules persist — paths under `~/.claude/` are treated as sensitive by Claude Code and re-prompt every session).

```bash
mkdir -p $HOME/.local/state/review-assistant/sessions && find $HOME/.local/state/review-assistant/sessions -name "*.md" -mtime +7 -delete
```

## Step 2: Check PR eligibility

```bash
gh pr view <PR_NUMBER> --repo <REPO> --json state,isDraft,title
```

- **Closed/merged:** Use `AskUserQuestion`: "PR #N is closed. Proceed anyway?" with options "Yes, review it anyway" / "No, exit". Stop if no.
- **Draft:** Proceed normally, note "This is a draft PR."
- **Already reviewed:** Check for existing session file(s) matching `pr-<NUMBER>-*.md` in `$HOME/.local/state/review-assistant/sessions/`. If found, use the most recent one (by filename timestamp). Use `AskUserQuestion`:
  > "You've reviewed this PR before (session: <date>). How would you like to proceed?"
  - "Full re-review" — start fresh, delete old session file
  - "Incremental" — review only changes since last review (reads `last_reviewed_sha` from session file, uses `git diff <last_reviewed_sha>..HEAD`)
  - "Update session" — re-analyze full diff, keep `## User Context` from previous session

## Step 3: Fetch PR metadata and diff

```bash
gh pr view <PR_NUMBER> --repo <REPO> --json title,body,commits,labels,milestone,closingIssuesReferences,headRefOid
```

Record `headRefOid` as `review_sha`.

Fetch linked GitHub issues from `closingIssuesReferences`:

```bash
gh issue view <ISSUE_NUMBER> --repo <REPO> --json title,body
```

Fetch the full diff and cache it for reuse by downstream skills and the analyzer subagent. Writing to our data dir (rather than `/tmp/`) keeps the path inside the pre-approved allowlist so subagents don't get a per-session permission prompt:

```bash
mkdir -p $HOME/.local/state/review-assistant
gh pr diff <PR_NUMBER> --repo <REPO> > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diff.txt
```

Refer to this path as `<DIFF_PATH>` in later steps.

## Step 4: Produce the "why" summary

From the PR title, body, commit messages, and linked issues, write a 2-3 sentence summary of what changed and why.

**If the why is unclear** (empty body, unhelpful commits, no linked issues): ask the user ONE question:

> "I couldn't determine why this change was made. Can you give me a brief summary of the intent?"

## Step 5: Load REVIEW.md

Load in order (both if present):

1. `~/.claude/REVIEW.md`
2. `REVIEW.md` at the project root

If neither exists: note "No REVIEW.md found — proceeding without review guidelines."

Concatenate contents (per-repo appends to/overrides global).

## Step 6: Write initial session file

```bash
cat <<'EOF' > $HOME/.local/state/review-assistant/sessions/pr-<NUMBER>-<YYYYMMDD-HHMMSS>.md
# Review Session: PR #<NUMBER> — <title>
review_sha: <headRefOid>

## Why
<2-3 sentence summary>

## Findings
_Populated by analysis_

## Queued Comments
_Populated during interactive review_

## User Context
_Populated if user provides corrections_
EOF
```

## Step 7: Run code-review analysis

### 7a: Check code-review plugin availability

Attempt to invoke the `code-review:code-review` skill. If not available, stop:

> "The `code-review` plugin is required but not installed. Install with:
> ```
> claude plugin install code-review@claude-plugins-official
> ```
> Then re-run `/review-assistant`."

### 7b: Identify inconsequential files

From the diff, identify files to skip (pure renames, generated files, mass reformats, bulk deletions). Mark as `skip: true`. **Exception:** If REVIEW.md guidelines call for reviewing a category of these files, include them.

### 7c: Dispatch code-review-analyzer agent

Dispatch the `code-review-analyzer` agent (Agent tool with `subagent_type="review-assistant:code-review-analyzer"`) with the following task. Substitute `{pr_number}`, `{repo}`, `{diff_path}` (the `<DIFF_PATH>` from Step 3), and `{review_md_content}`:

> Review PR #{pr_number} in {repo}.
>
> - The PR diff has already been fetched and cached at `{diff_path}`. Use that file instead of re-running `gh pr diff`. Do NOT write scratch diffs to `/tmp/` — that path triggers a user permission prompt every session. If the `code-review` skill accepts a diff path, pass `{diff_path}` to it; otherwise read from `{diff_path}` directly.
> - Use a confidence threshold of 0 — return EVERY finding the code-review skill produces, regardless of confidence. The caller filters later; do not filter here.
> - In addition to any CLAUDE.md files, also check the diff against these review guidelines:
>
> ---
> {review_md_content}
> ---
>
> If no review guidelines were provided above (the section between the --- markers is empty), skip the review guidelines compliance check.

### 7d: Parse and deduplicate findings

Parse the subagent's response. Each finding needs: `file`, `line`, `severity`, `confidence`, `source`, `description`. Skip malformed lines.

Merge findings at the same `file` + `line`. Keep the highest confidence score.

### 7e: Anchor findings to the diff

Before writing findings to the session file, attach a line-text anchor so downstream consumers can verify that comments land on the right lines.

Build an in-memory index of the fetched diff: for each file, walk the hunk bodies and record `(right_line) -> line_text` for `+` and ` ` lines, and `(left_line) -> line_text` for `-` and ` ` lines. This is a lightweight read-only index used only for anchor lookup during session-file writing — do NOT re-derive it at post time. The full classifier that enforces line anchoring (`scripts/classify-and-verify.py`, invoked by `auto-draft-review` and `interactive-diff-review` at POST time) parses the diff the same way; do not reimplement its classification logic here.

For each finding, look up `(file, line)` in the RIGHT-side index first, then LEFT-side:

- If found: set `code: \`<exact line text>\`` and `in_diff: true`.
- If the file isn't in the diff, or the line isn't in any hunk for that file: set `in_diff: false`. Do NOT drop the finding — auto mode still reports it, and the verifier may re-anchor by text match later.

### 7f: Write findings to session file

Record the active threshold for later consumers:

```
threshold: <T>
```

Partition findings by confidence. Write those with `confidence >= threshold` under `## Findings`, and those below threshold under `## Below Threshold` (same format, minus `skip`). Both sections use this shape:

```
## Findings
- file: src/foo.ts, line: 42, severity: high, confidence: 87, source: bug-scan, skip: false, in_diff: true
  code: `const id = user.id;`
  Missing null check before accessing `.user.id`
- file: generated/types.ts, line: 1, severity: info, confidence: 100, source: claude-md, skip: true, in_diff: true
  code: `export type Foo = ...`
  Generated file — skipping

## Below Threshold
- file: src/bar.ts, line: 15, severity: low, confidence: 30, source: code-comments, in_diff: true
  code: `setTimeout(fn, 86400);`
  Magic number 86400 could be a named constant
```

Interactive consumers read only `## Findings`. Auto-mode reads both so it can report what got filtered.

The `code:` line is the anchor that `classify-and-verify.py` uses to confirm the finding lands on the right diff line (with a ±3 line scan on mismatch). Keep backticks around the text literally — they're stripped by the parser.

## Step 8: Hand off silently

Do NOT print a closing summary, "session file ready" message, or "returning to the orchestrator" line — any user-facing text here reads as a turn boundary and causes the orchestrator to stop before dispatching the walkthrough skill.

Hold the session file path in working memory. The orchestrator's next step (Step 4 of `review-assistant.md`) will pass it to either `auto-draft-review` or `interactive-diff-review`. Proceed directly to that dispatch with no intervening output.
