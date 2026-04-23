---
name: auto-draft-review
description: Use when running a PR review in --auto mode, to post analyzer findings as a pending GitHub review without an interactive walkthrough. Not user-facing — invoked by the orchestrator only.
---

# Auto Draft Review

Post analyzer findings as a pending GitHub review so the user can finalize on github.com. No walkthrough, no per-finding prompts. The user's first line ("Running auto review — ...") was already announced by the orchestrator; do not re-announce.

**File I/O:** Use `Bash` with heredocs or `>>` for session/temp files — not Write, Read, or Edit tools.

## Inputs

- `pr_number`: the PR number
- `repo`: owner/repo
- `session_file`: path to the session file (contains Why, Findings, etc.)

## Step 1: Fetch the diff

```bash
gh pr diff <PR_NUMBER> --repo <REPO> > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diff.txt
```

Read the session file separately for metadata (Why summary, `review_sha`, `threshold`, skipped files). Findings themselves flow through the classifier in the next step — do not re-parse them by hand.

## Step 2: Classify and verify findings

Run the shared classifier against the `## Findings` section:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/classify-and-verify.py" \
  --diff "$HOME/.local/state/review-assistant/pr-<PR_NUMBER>-diff.txt" \
  --session "<session_file>" \
  --section findings \
  > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-classified.json
```

The script emits `{ inline, fallback, suspect, stats }` where each bucket means:

- **inline** — safe to post as an inline review comment. `line` and `side` have been verified (or re-anchored within ±3 lines) against the finding's recorded `code` text. Use these verbatim.
- **fallback** — the line is outside every hunk for that file, or the finding was recorded with `in_diff: false`. Put these in the review body, not in `comments[]`.
- **suspect** — the line IS inside a hunk, but the finding's `code` anchor didn't match the diff line or any of its ±3 neighbors. Also goes in the review body, with an explicit "line anchor uncertain" flag so the reviewer knows not to trust the number.

**Never** invent inline comments that bypass the classifier. If the classifier says fallback or suspect, respect it.

## Step 3: Build the review payload

**Body** (heredoc into the `gh api` call):

```
<Why summary from session file>

---

This is a pending review with <inline_count> findings pre-annotated inline. Open the PR on github.com, review the inline comments, edit or dismiss as needed, and submit when ready.

<If fallback entries exist:>
## Findings outside the current diff

- `<file>` line <N> (<severity>, confidence <C>): <description>
...

<If suspect entries exist:>
## Findings with uncertain line anchors

The analyzer reported these inside the diff, but the recorded line text didn't match the diff's version — the line number may be stale. Check the file on github.com before acting.

- `<file>` line <N> (<severity>, confidence <C>): <description>
...
```

**Inline comments** come from the classifier's `inline` bucket — use each entry's `path`, `line`, `side`, and `body` directly.

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
    { "path": "...", "line": N, "side": "RIGHT", "body": "..." }
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

Print exactly this shape. "Not posted" lists every finding that did NOT end up as an inline comment, grouped by reason. Omit groups with zero entries.

```
Pending review posted: https://github.com/<OWNER>/<REPO>/pull/<N>

Posted inline: <inline_count>
Posted in review body (outside diff hunks): <fallback_count>
Posted in review body (uncertain line anchor): <suspect_count>

Not posted:
  Below confidence threshold (<threshold>): <count>
    - <file>:<line> — <description>
  In skipped files: <count>
    - <file> — <reason>

Open the PR on github.com to review, edit, and submit. Nothing has been submitted yet.
```

If `inline + fallback + suspect` equals the total non-skipped findings and there are no below-threshold or skipped records, replace the "Not posted" block with:

```
Not posted: none — every finding made it onto the pending review.
```

To list below-threshold findings, re-run the classifier with `--section below` (emits the same bucket shape; you only need the `source_finding` details for display, not the classification).
