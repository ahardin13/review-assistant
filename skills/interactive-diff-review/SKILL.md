---
name: interactive-diff-review
description: Use when walking a user through code changes file-by-file during a PR review. Not for automated or silent reviews.
---

# Interactive Diff Review

Walk the user through PR changes: present an overview, step through files one at a time, collect decisions on findings, show a summary, and post to GitHub when ready.

**File I/O:** Use `Bash` with heredocs or `>>` for session/temp files — not Write, Read, or Edit tools.

## Inputs

- `pr_number`: the PR number
- `session_file`: path to the session file (contains Why, Findings, etc.)
- `repo`: owner/repo

Read the session file to extract:
- **Why**: summary from `## Why`
- **threshold**: the `threshold: <N>` line at the top
- **files**: non-skipped files from `## Findings` (ordered: modified first, then new, then deleted)
- **findings**: map of `file -> [{ line, severity, confidence, source, description, code, in_diff }]` from entries where `skip: false` under `## Findings`. The `code` and `in_diff` fields are the line-text anchor used by `classify-and-verify.py` at post time; `interactive-diff-review` surfaces them in Phase 3 to flag uncertain anchors before the user queues a comment.
- **below_threshold**: findings from `## Below Threshold` — not shown during the walkthrough, but the orchestrator may reference them in reporting
- **skipped**: files with `skip: true`

## Phase 1: Overview

Show:

1. **Why:** The summary from the session file
2. **Changes:** A markdown table:

```
| File | What changed |
|------|--------------|
| src/resolvers/foo.ts | Simplified resolver to delegate to shared method |
| packages/lib/client.ts | New static method with extracted logic |
```

3. **Skipped files:** List with reasons. If none: "None — all files contain meaningful changes."
4. **Findings summary:** Count and severity breakdown ONLY: "Found N issues across M files (X high, Y medium, Z low)."

**Do NOT list individual findings here.** They are presented one at a time during the walkthrough.

Then ask: "Does this match your understanding of the PR? Any corrections before we dive into the file-by-file review?"

If corrections: append to `## User Context` in session file. Re-evaluate findings that the correction might invalidate.

## Phase 2: Pre-split diffs

Fetch the full diff once and split by file:

```bash
gh pr diff <PR_NUMBER> --repo <REPO> > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diff.txt
mkdir -p $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diffs
awk -v dir="$HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diffs" '
/^diff --git / {
  if (file != "") close(file)
  f = $0; sub(/.* b\//, "", f); gsub(/\//, "__", f)
  file = dir "/" f
}
file != "" { print >> file }
END { if (file != "") close(file) }
' $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diff.txt
```

Mention once: "Press ESC at any prompt to ask questions or discuss code."

## Phase 3: File-by-file walkthrough

For each file:

### 1. Read the pre-split diff

```bash
cat "$HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diffs/$(echo '<filepath>' | tr '/' '__')"
```

### 2. File header

```
File X/Y: src/resolvers/foo.ts

This file has N finding(s).
```

If no findings: "No findings for this file." Show only diff summary, then auto-advance.

### 3. Diff summary

**Do NOT dump the full unified diff.** Present:

1. **Diff summary** — prose (1-3 sentences) of what changed
2. **Condensed diff snippet** — key changes only, collapse unchanged regions:
   - Collapse removed blocks: `// ~70 lines of business logic removed...`
   - Show lines referenced by findings in full
   - 2-3 lines surrounding context
   - Small diffs (<20 lines): show as-is
   - New files: first ~30 lines + structure summary

If condensed diff exceeds 60 lines, break at logical boundaries with "Continue" / "Skip rest of file" prompt.

### 4. Present findings one at a time

Before presenting, sanity-check the line anchor against the diff:

- The finding carries `code: \`<text>\`` (and `in_diff: true|false`) from `reading-pr-context`.
- Confirm the diff snippet you just showed contains that exact text at the claimed line. Mark it explicitly, e.g. `> 42: const id = user.id;`.
- If `in_diff: false`, or the `code` text isn't present at (or within ±3 of) the claimed line, **flag it in the question**: "⚠ Line anchor is uncertain — the analyzer said line 42 but the diff shows a different line at that number." The user may dismiss or re-target.

**Put the full finding inside the `question` field of `AskUserQuestion`** (text above the prompt can get cut off):

```
question: "Finding 1 (confidence: 70): The error detection uses `error.message.startsWith(...)` — a string coupling across a package boundary. If the message changes, BAD_USER_INPUT wrapping silently breaks.\n\nTarget: src/foo.ts:42 — `if (error.message.startsWith('Bad'))`\n\nWhat would you like to do?"
options:
  - label: "Comment"
    description: "<specific action, e.g. 'Queue a comment suggesting a typed error class'>"
  - label: "Dismiss"
    description: "<specific reason, e.g. 'Low risk — string unlikely to change'>"
```

Make descriptions **specific to the finding**. Always include the `Target: <file>:<line> — <code snippet>` line so the user can confirm where the comment will land.

### 5. Handle response

**Comment:** Append the queued comment to `## Queued Comments` in the session file using the **same row format as `## Findings`**. This lets Phase 5 feed the section straight through `classify-and-verify.py` without re-shaping each entry.

```markdown
- file: <filepath>, line: <N>, severity: <sev>, confidence: <conf>, source: <source>, skip: false, in_diff: <true|false>
  code: `<code anchor carried from the original finding>`
  **<short lead-in>.** <what's wrong — one paragraph>

  **Why it matters.** <one paragraph; omit if the lead-in already covers it>

  **Suggestion:** <what to do — one paragraph; include a fenced code block if a fix snippet helps>
```

Rules for the body:

- **Drop the metadata prefix.** Do NOT begin the body with `**<severity>** (confidence N, source: X)` — `classify-and-verify.py` no longer adds that, and the inline comment should read like prose to whoever opens the PR. Severity/confidence/source live on the row's structured fields and are surfaced in the review-body summary, not in the comment itself.
- **Use blank lines to separate paragraphs.** The classifier's parser preserves blank-line breaks as `\n\n` in the rendered body. Consecutive non-blank lines stay one paragraph (Markdown soft-break).
- **Lead-ins.** Bold leads like `**Performance.**`, `**Possible null dereference.**`, or `**Suggestion:**` give the reader something to scan. Don't force the literal labels "What's wrong / Why it matters / Suggestion" — write what fits the finding.
- **Indented continuation.** Each continuation line MUST start with two spaces. Markdown nesting (lists, fenced code blocks) past the two-space prefix is preserved, so a fenced suggestion block at four-space indent renders correctly.

Confirm: "Queued."

**Dismiss:** Note internally. Do not write to session file.

**Free-text (ESC):** Handle their message. If context invalidates finding, drop it. If it changes the finding, re-present. If they want investigation, launch a sub-agent. Then re-present Comment/Dismiss.

### 6. After all findings for a file

Prompt: "Next file" / "Skip remaining files" (auto-advance if previously chosen).

## Phase 4: Summary and re-review

Read `## Queued Comments` from the session file. Each entry is a `## Findings`-shaped row whose continuation block holds the multi-paragraph body. For the on-screen summary, show only `file`, `line`, and the **first paragraph** of the body (truncated to ~80 chars) — the full body lives in the session file and gets posted verbatim:

```
─── Queued Comments ──────────────────────────
1. src/foo.ts line 42 — Possible null dereference. When `getUser()` returns null this throws.
2. src/bar.ts line 15 — Magic number 86400 should be a named constant…
──────────────────────────────────────────────
```

Prompt: "Submit" / "Revisit a file". If revisit, list files as options, then re-run the walkthrough for that file. Loop back here.

## Phase 5: Post to GitHub

Prompt with options:

- "Approve" — approving review with inline annotations
- "Request changes" — changes-requested review with inline annotations
- "Comment only" — inline annotations, no formal decision
- "Nothing" — exit without posting

If no queued comments + Approve: "Add an overall review note?" (Yes / No, just approve).
If no queued comments + Request changes: prompt for reason (required by GitHub).
**Nothing:** Exit.

### Posting inline comments

**Check for new commits:**

```bash
CURRENT_SHA=$(gh pr view <PR_NUMBER> --repo <REPO> --json headRefOid --jq '.headRefOid')
```

If different from `review_sha` in session file, warn user:
- "Post anyway" — use original `review_sha` as `commit_id`
- "Abandon" — exit

**Classify comments via the shared verifier:**

Phase 3 wrote queued comments using the same row format as `## Findings` (with `code:` anchors and multi-paragraph bodies). The classifier reads either header — copy the section into a scratch file as `## Findings`, then run:

```bash
gh pr diff <PR_NUMBER> --repo <REPO> > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diff.txt

# Re-header `## Queued Comments` → `## Findings` so the classifier finds it.
awk '/^## Queued Comments/{print "## Findings"; next} {print}' "<session_file>" \
  > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-queued.md

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/classify-and-verify.py" \
  --diff "$HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diff.txt" \
  --session "$HOME/.local/state/review-assistant/pr-<PR_NUMBER>-queued.md" \
  --section findings \
  > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-queued-classified.json
```

Use the classifier's buckets:

- **inline** — post as `comments[]` entries with the verified `path`, `line`, and `side` from the bucket (not the original values — the verifier may have re-anchored by ±3 lines). The `body` is the description with paragraph breaks preserved; do not re-prefix it.
- **fallback** — include in the review body.
- **suspect** — include in the review body under an "uncertain line anchor" header, so the reader knows the number may be stale.

Do NOT hand-roll hunk classification. Do NOT post a comment whose `line` or `side` came from anywhere other than the classifier's `inline` bucket.

**Post review (silent merge with any existing pending review):**

The user may have already started a pending review on github.com — either from a prior `--auto` pass or from manual edits. Editing pending-review comments via REST is impossible (PATCH on `/pulls/comments/{id}` returns 404 for pending), and POSTing a second pending review fails with "user_id can only have one pending review per PR." Both situations are handled by the helper, which fetches existing pending comments, merges them ahead of the newly queued ones, deletes the old pending review, and POSTs a fresh one in a single call:

Write the review body to a scratch file first, then build the JSON spec with `jq -n` and `--rawfile` so multi-paragraph content survives. Do **not** try to interpolate `$(jq -Rs . <<<"$BODY")` inside an outer heredoc — bash's here-string handling drops or corrupts characters in multi-line content and the helper rejects the result with `Invalid control character`.

```bash
cat > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-body.txt <<'EOF'
<overall note + fallback comments + suspect comments>
EOF

INLINE_COMMENTS=$(jq '.inline | map({path, line, side, body})' \
  $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-queued-classified.json)

jq -n \
  --arg repo "<OWNER>/<REPO>" \
  --argjson pr <PR_NUMBER> \
  --arg commit "<review_sha>" \
  --rawfile body $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-body.txt \
  --argjson comments "$INLINE_COMMENTS" \
  --arg ip "merge" \
  '{repo: $repo, pr: $pr, commit_id: $commit, body: $body, comments: $comments, if_pending: $ip}' \
  | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post-pending-review.py"
```

The helper writes a backup of the about-to-be-deleted state to `~/.local/state/review-assistant/pr-<N>-recreate-<TS>.json` before any destructive call, so a mid-flight failure is recoverable. On success it prints `{ review_id, review_url, comment_count, replaced_existing, merged_comments, backup_path }`. Surface the URL to the user; if `replaced_existing` is true, mention "Merged with N existing comments" in the closing summary.

**About the review event (APPROVE / REQUEST_CHANGES / COMMENT):** the helper always posts a *pending* review (no `event`). This is by design — the user's "Approve" / "Request changes" / "Comment only" choice from the prompt above is held in the session file and used the next time the user submits the review on github.com. If the user picks "Approve" with zero queued comments and no overall note, skip the helper entirely and submit directly via `gh pr review --approve`; that's a one-shot action with no comments and doesn't need a pending phase.

- Format all bodies with GitHub-flavored Markdown.
- Fallback and suspect comments in `body` are never dropped.

After posting, append to the session file:

```
last_reviewed_sha: <current SHA>
last_pending_review_id: <review_id from helper output>
```

The `last_pending_review_id` lets a follow-up session find this review without scanning all reviews on the PR.

### Editing comments inside an existing pending review

REST PATCH on `/pulls/comments/{id}` returns 404 while a comment lives inside a pending review. To edit, recreate. This applies whether the user has manually edited some comments on github.com (we want to preserve those) or wants Claude to rewrite some of the bodies it wrote earlier.

```bash
# 1. Find the user's pending review on this PR (saved as last_pending_review_id
#    or looked up fresh):
ME=$(gh api user --jq '.login')
REVIEW_ID=$(gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews --paginate \
  --jq "[.[] | select(.state == \"PENDING\" and .user.login == \"$ME\")] | first | .id")

# 2. Fetch its current comments (these include any user edits):
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews/$REVIEW_ID/comments --paginate \
  > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-existing-comments.json

# 3. Build the FINAL desired set of comments. For each existing comment use
#    {path, position: original_position, body} — line/side are null on pending,
#    so original_position is the only anchor that survives. Replace bodies you
#    want to rewrite; leave the rest verbatim.
jq '
  [ .[] | {
      path,
      position: .original_position,
      body
    }
  ]
  # ...apply your edits in jq, e.g. with `map(if .path == "x" and .position == 7 then .body = "new body" else . end)`
' $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-existing-comments.json \
  > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-edited-comments.json

# 4. Hand the FINAL list to the helper with `if_pending: "replace"` — the
#    existing entries are already inside `comments`, so we don't want the
#    helper to merge them in again. Use the --rawfile + jq -n pattern (see
#    Phase 5 above) for the body so multi-paragraph review-body content
#    survives intact.
cat > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-body.txt <<'EOF'
<review body — same as before, or rewritten>
EOF

jq -n \
  --arg repo "<OWNER>/<REPO>" \
  --argjson pr <PR_NUMBER> \
  --arg commit "<review_sha>" \
  --rawfile body $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-body.txt \
  --argjson comments "$(cat $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-edited-comments.json)" \
  --arg ip "replace" \
  '{repo: $repo, pr: $pr, commit_id: $commit, body: $body, comments: $comments, if_pending: $ip}' \
  | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post-pending-review.py"
```

The helper still writes the backup payload before deleting, so if your edited bodies have a typo you can recover. The new pending review's id is in the helper's stdout; record it as `last_pending_review_id` in the session file.

## Conversational escape (ESC)

At any prompt, the user can press ESC to type freely. Answer their question using current context, then **re-present the same prompt** so the walkthrough continues.
