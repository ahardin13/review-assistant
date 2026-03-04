# review-assistant

Interactive, human-in-the-loop PR review assistant for [Claude Code](https://claude.ai/code).

Unlike automated review tools that post comments silently, review-assistant guides you through pull request changes file-by-file, presents findings with confidence scores, and lets you decide what to comment on before anything is posted to GitHub.

## Prerequisites

- [Claude Code](https://claude.ai/code) installed
- [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated
- The official **code-review** plugin installed:
  ```
  claude plugin install code-review@claude-plugins-official
  ```

## Installation

```bash
claude plugin install review-assistant@ahardin13
```

For local development:

```bash
claude --plugin-dir /path/to/review-assistant
```

## Usage

```
/review-assistant <PR_NUMBER>
/review-assistant <PR_NUMBER> --repo owner/repo
/review-assistant <PR_NUMBER> --threshold 75
```

**Options:**
- `--repo owner/repo` — specify the repository (default: detected from `git remote`)
- `--threshold N` — minimum confidence score for findings, 0-100 (default: 50)

## How It Works

1. **Context gathering** — fetches PR metadata, diff, and linked GitHub issues
2. **Analysis** — invokes the code-review plugin to scan for bugs, guideline violations, historical regressions, and more
3. **Interactive walkthrough** — presents each file's diff with annotated findings; you decide per finding: Comment, Ignore, Correct, or Expand
4. **Post to GitHub** — when ready, submit your review as Approve, Request Changes, Comment Only, or exit without posting

## Review Guidelines (REVIEW.md)

Create a `REVIEW.md` file to define project-specific review guidelines. The plugin loads guidelines from two locations (both if present):

1. `~/.claude/REVIEW.md` — global defaults across all projects
2. `REVIEW.md` at the project root — project-specific rules

These guidelines are checked alongside any `CLAUDE.md` files in your repository. See [docs/REVIEW-example.md](docs/REVIEW-example.md) for an example.

### Adding Issue Tracker Context

review-assistant fetches linked GitHub issues automatically. For other issue trackers (Linear, Jira, Shortcut, etc.), add guidance to your REVIEW.md:

```markdown
## Issue Tracker

When reviewing PRs, check for Linear issue references (e.g. `ENG-123` or
`https://linear.app/.../issue/ENG-123/...`) in the PR title and body.
Use the Linear MCP tool to fetch issue context if available:

    mcp__plugin_linear_linear__get_issue(id: "ENG-123")

If the Linear MCP server is not configured, ask the reviewer for context
about the linked issue.
```

Adapt the example above for your team's issue tracker and MCP tools.

## Session Files

Review sessions are saved to `~/.review-assistant/sessions/` (as `pr-<NUMBER>-<YYYYMMDD-HHMMSS>.md`) and automatically cleaned up after 7 days. Sessions enable:

- **Incremental reviews** — re-review only new changes since your last session
- **Session continuity** — pick up where you left off if context is lost

## License

MIT
