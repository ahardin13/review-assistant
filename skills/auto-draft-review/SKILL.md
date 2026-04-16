---
name: auto-draft-review
description: Use when running a PR review in --auto mode, to post analyzer findings as a pending GitHub review without an interactive walkthrough. Not user-facing — invoked by the orchestrator only.
---

# Auto Draft Review

Post all analyzer findings as a pending GitHub review so the user can finalize on github.com. No walkthrough, no per-finding prompts. The user's first line ("Running auto review — ...") was already announced by the orchestrator; do not re-announce.

**File I/O:** Use `Bash` with heredocs or `>>` for session/temp files — not Write, Read, or Edit tools.

## Inputs

- `pr_number`: the PR number
- `repo`: owner/repo
- `session_file`: path to the session file (contains Why, Findings, etc.)

## Step 1: Read session

Read the session file. Extract:

- **Why**: from `## Why`
- **review_sha**: from the `review_sha:` line near the top
- **threshold**: from the session file if recorded, else default 50
- **findings**: entries under `## Findings` where `skip: false`
- **skipped**: entries where `skip: true` (with reason if present)

## Step 2: Fetch diff and classify every finding

```bash
gh pr diff <PR_NUMBER> --repo <REPO> > ${CLAUDE_PLUGIN_DATA}/pr-<PR_NUMBER>-diff.txt
```

Parse `@@ -a,b +c,d @@` hunk markers per file. For each finding, classify into one of:

- **inline-right** — the line falls within a hunk's RIGHT-side range (`c` to `c+d-1`). Post with `side: "RIGHT"`.
- **inline-left** — the line falls within a hunk's LEFT-side range (`a` to `a+b-1`) AND the finding is explicitly on a deleted line. Post with `side: "LEFT"`.
- **fallback** — line is outside any hunk in the PR diff. Include in the review body, not in the `comments[]` array. Never drop silently.

## Step 3: Build the review payload

**Body:**

```
<Why summary>

---

This is a pending review with <N> findings pre-annotated. Open the PR on github.com, review the inline comments, edit or dismiss as needed, and submit when ready.

<If any fallback findings:>
## Findings outside the current diff

- `<file>` line <N> (<severity>, confidence <C>): <description>
...
```

**Inline comments:** one entry per `inline-*` finding. Body format:

```
**<severity>** (confidence <C>, source: <source>)

<description>
```

Use GitHub-flavored Markdown. **bold** for severity, `backticks` for code identifiers, code fences for multi-line suggestions.

## Step 4: Post as a pending review

**Critical:** omit the `event` field. This creates a pending review that only the author (the user running this) sees until they submit it on github.com.

```bash
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews \
  --method POST \
  --input - <<'EOF'
{
  "commit_id": "<review_sha>",
  "body": "<body text>",
  "comments": [
    {
      "path": "src/foo.ts",
      "line": 42,
      "side": "RIGHT",
      "body": "**high** (confidence 87, source: bug-scan)\n\nMissing null check before `.user.id` ..."
    }
  ]
}
EOF
```

If the POST fails, show the error verbatim and stop — do not retry silently.

After a successful post, append to the session file:

```
last_reviewed_sha: <review_sha>
posted_mode: auto
```

## Step 5: Final summary (user-facing)

Print exactly this shape. The "Not posted" section must list every finding the analyzer produced that did NOT end up as an inline comment on the pending review, grouped by reason. If a group is empty, omit the group entirely.

```
Pending review posted: https://github.com/<OWNER>/<REPO>/pull/<N>

Posted inline: <count>
Posted in review body (outside diff hunks): <count>

Not posted:
  Below confidence threshold (<threshold>): <count>
    - <file>:<line> — <description>
  In skipped files: <count>
    - <file> — <reason>

Open the PR on github.com to review, edit, and submit. Nothing has been submitted yet.
```

If the analyzer produced no below-threshold or skipped-file records, the "Not posted" block becomes:

```
Not posted: none — every finding made it onto the pending review.
```
