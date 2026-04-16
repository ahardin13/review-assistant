# Auto-mode dispatch tests

High-level tests that verify the orchestrator picks the correct walkthrough skill based on the `--auto` flag and announces the mode to the user before doing anything else.

These are agent-in-the-loop tests. Run each scenario by dispatching a subagent (Agent tool, `general-purpose`) with the orchestrator's prompt and the given invocation, then grep the subagent's first user-facing line for the expected keywords.

## Scenario 1 — Interactive mode

**Invocation:** `/review-assistant 123`

**Expected first user-facing line matches:** `/interactive|walkthrough|step through/i`

**Expected dispatch:** `Skill("review-assistant:interactive-diff-review", ...)` is called; `auto-draft-review` is NOT called.

## Scenario 2 — Auto mode

**Invocation:** `/review-assistant 123 --auto`

**Expected first user-facing line matches:** `/auto review|pending review|finalize on github/i`

**Expected dispatch:** `Skill("review-assistant:auto-draft-review", ...)` is called; `interactive-diff-review` is NOT called.

**Expected post-completion output:** includes the PR URL and a "Not posted:" section grouping any filtered/skipped findings by reason.

## Scenario 3 — Auto-mode below-threshold visibility

**Setup:** Seed a session file where the analyzer produced both above- and below-threshold findings.

**Invocation:** `/review-assistant 123 --auto --threshold 60`

**Expected:** final summary lists below-threshold findings under `Not posted → Below confidence threshold (60):`. No below-threshold finding appears as an inline comment on the posted pending review.

## Running

There is no automated harness yet; run scenarios manually against a disposable PR before merging changes to the dispatch logic, the `auto-draft-review` skill, or the session-file schema in `reading-pr-context`.
