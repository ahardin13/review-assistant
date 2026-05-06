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

- **inline** — safe to post as an inline review comment. `line` and `side` have been verified (or re-anchored within ±3 lines) against the finding's recorded `code` text. Use these verbatim. Each entry's `body` is the finding's description as written by the analyzer (paragraph breaks preserved). Severity, confidence, and source live on `source_finding` for the review-body summary, **not** in the inline body — keep it that way; meta-prefixes like `**high** (confidence 87, source: bug-scan)` add noise to anyone reading the PR on github.com.
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

Call the shared helper. It detects an existing pending review by the current user, **silently merges** with it (preserving any user-edited bodies the user already touched on github.com), backs up the pre-DELETE state, and POSTs the combined review. Omitting the `event` field — which the helper does — is what keeps the new review pending so the user finalizes on github.com.

Write the body to a scratch file first, then assemble the JSON spec with `jq -n` so multi-paragraph content (which contains literal newlines) is JSON-encoded reliably. Do **not** try to interpolate `$(jq -Rs . <<<"$BODY")` inside an outer heredoc — bash's here-string handling chokes on multi-line content and you'll get `Invalid control character` from the helper.

```bash
cat > $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-body.txt <<'EOF'
<body text — Why summary, separator, "pending review with N findings..." line, then any "Findings outside the diff" / "uncertain anchor" sections>
EOF

INLINE_COMMENTS=$(jq '.inline | map({path, line, side, body})' \
  $HOME/.local/state/review-assistant/pr-<PR_NUMBER>-classified.json)

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

The helper exits non-zero with `gh ... failed: <reason>` on any GitHub error — surface that verbatim to the user and stop. Do not retry silently. The helper output (stdout) is JSON: `{ review_id, review_url, comment_count, replaced_existing, merged_comments, backup_path }`. Keep the `review_url` for the final summary; if `replaced_existing` is true, mention it ("Merged with previous pending review (N comments)") so the user isn't surprised.

After a successful post, append to the session file:

```
last_reviewed_sha: <review_sha>
posted_mode: auto
```

## Step 5: Final summary (user-facing)

Print exactly this shape. "Not posted" lists every finding that did NOT end up as an inline comment, grouped by reason. Omit groups with zero entries. If the helper reported `replaced_existing: true`, prepend the merge line below the URL.

```
Pending review posted: https://github.com/<OWNER>/<REPO>/pull/<N>
[Merged with previous pending review (<merged_comments> comments).]

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
