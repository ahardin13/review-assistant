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
- **files**: non-skipped files from `## Findings` (ordered: modified first, then new, then deleted)
- **findings**: map of `file -> [{ line, severity, confidence, description }]` from entries where `skip: false`
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
gh pr diff <PR_NUMBER> --repo <REPO> > ${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diff.txt
mkdir -p ${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diffs
awk -v dir="${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diffs" '
/^diff --git / {
  if (file != "") close(file)
  f = $0; sub(/.* b\//, "", f); gsub(/\//, "__", f)
  file = dir "/" f
}
file != "" { print >> file }
END { if (file != "") close(file) }
' ${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diff.txt
```

Mention once: "Press ESC at any prompt to ask questions or discuss code."

## Phase 3: File-by-file walkthrough

For each file:

### 1. Read the pre-split diff

```bash
cat "${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diffs/$(echo '<filepath>' | tr '/' '__')"
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

**Comment:** Append to `## Queued Comments` in session file:

```markdown
- `<filepath>` line <N>: <finding description>
```

Format with GitHub-flavored Markdown: **bold** for key terms, `backticks` for code, code blocks for suggestions, bullet lists for multiple points.

Confirm: "Queued."

**Dismiss:** Note internally. Do not write to session file.

**Free-text (ESC):** Handle their message. If context invalidates finding, drop it. If it changes the finding, re-present. If they want investigation, launch a sub-agent. Then re-present Comment/Dismiss.

### 6. After all findings for a file

Prompt: "Next file" / "Skip remaining files" (auto-advance if previously chosen).

## Phase 4: Summary and re-review

Read `## Queued Comments` from session file and display:

```
─── Queued Comments ──────────────────────────
1. src/foo.ts line 42: Missing null check before accessing `.user.id`
2. src/bar.ts line 15: Magic number 86400 should be a named constant
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

Build a temp session fragment containing only the queued comments (one per line, same row format as `## Findings`, including the `code:` anchor carried through from the original finding). Write it to a scratch file, then run:

```bash
gh pr diff <PR_NUMBER> --repo <REPO> > ${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diff.txt
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/classify-and-verify.py" \
  --diff "${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diff.txt" \
  --session "${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-queued.md" \
  --section findings \
  > ${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-queued-classified.json
```

Use the classifier's buckets:

- **inline** — post as `comments[]` entries with the verified `path`, `line`, and `side` from the bucket (not the original values — the verifier may have re-anchored by ±3 lines).
- **fallback** — include in the review body.
- **suspect** — include in the review body under an "uncertain line anchor" header, so the reader knows the number may be stale.

Do NOT hand-roll hunk classification. Do NOT post a comment whose `line` or `side` came from anywhere other than the classifier's `inline` bucket.

**Post review:**

````bash
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews \
  --method POST \
  --input - << 'EOF'
{
  "commit_id": "<review_sha>",
  "body": "<overall note + fallback comments + suspect comments>",
  "event": "<APPROVE|REQUEST_CHANGES|COMMENT>",
  "comments": [
    {
      "path": "src/foo.ts",
      "line": 42,
      "side": "RIGHT",
      "body": "**Possible null dereference** — ..."
    }
  ]
}
EOF
````

- Format all bodies with GitHub-flavored Markdown.
- Fallback and suspect comments in `body` are never dropped.

After posting, update session file: `last_reviewed_sha: <current SHA>`

## Conversational escape (ESC)

At any prompt, the user can press ESC to type freely. Answer their question using current context, then **re-present the same prompt** so the walkthrough continues.
