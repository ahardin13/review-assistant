#!/usr/bin/env python3
"""
Post a pending GitHub PR review, optionally merging with any existing pending
review by the current user.

REST PATCH on `/pulls/comments/{id}` returns 404 for comments inside a pending
review, and POST on `/pulls/{pr}/reviews` rejects a second pending review with
"user_id can only have one pending review per PR." Both situations require
re-creating the review: fetch existing comments, build a combined payload,
DELETE the pending review, POST a new one. This script codifies that flow so
the skill files don't have to re-derive it.

Reads JSON from stdin:
  {
    "repo": "owner/repo",
    "pr": 12345,
    "commit_id": "<sha>",
    "body": "<review body markdown>",
    "comments": [
      { "path": "src/foo.ts", "line": 42, "side": "RIGHT", "body": "..." },
      { "path": "src/bar.ts", "position": 7, "body": "..." }
    ],
    "if_pending": "merge" | "replace" | "fail"
  }

Behavior:
  1. Identify the current user via `gh api user`.
  2. Find the user's pending review on this PR (if any).
  3. If none exists: just POST the supplied comments as a new pending review.
  4. If one exists and `if_pending == "fail"`: exit 2 with a structured error.
  5. If one exists and `if_pending == "merge"`: fetch its comments, prepend
     them (preserving any user edits) to the supplied `comments`.
  6. Save a backup of the pre-DELETE state to
     `$HOME/.local/state/review-assistant/pr-<PR>-recreate-<TS>.json`.
  7. DELETE the existing pending review.
  8. POST a new pending review with the combined payload.

Output (stdout):
  {
    "review_id": <int>,
    "review_url": "<html_url>",
    "comment_count": <int>,
    "replaced_existing": <bool>,
    "merged_comments": <int>,
    "backup_path": "<path>" | null
  }

Exit codes:
  0  posted
  2  pending review exists and `if_pending == "fail"`
  1  any other error (gh failure, malformed input, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# ---- pure helpers (unit-tested) -------------------------------------------


def normalize_comment(comment: dict) -> dict:
    """Return a comment dict with only the keys GitHub's create-review API
    accepts.

    Caller may pass either the modern `{path, line, side, body}` form or the
    legacy `{path, position, body}` form. Each comment in the resulting array
    uses whichever form it was given. GitHub accepts both per-entry; if a
    comment has both, the modern form wins (its docs say "if both are
    specified, line and side will take precedence"), but we don't pass both
    when we can avoid it.
    """
    if "path" not in comment:
        raise ValueError(f"comment missing 'path': {comment!r}")
    if "body" not in comment:
        raise ValueError(f"comment missing 'body': {comment!r}")

    out: dict = {"path": comment["path"], "body": comment["body"]}

    # Modern form: line + side. side defaults to RIGHT if line is set.
    if comment.get("line") is not None:
        out["line"] = int(comment["line"])
        out["side"] = comment.get("side") or "RIGHT"
        if "start_line" in comment and comment["start_line"] is not None:
            out["start_line"] = int(comment["start_line"])
            out["start_side"] = comment.get("start_side") or out["side"]
        return out

    # Legacy form: position.
    if comment.get("position") is not None:
        out["position"] = int(comment["position"])
        return out

    raise ValueError(
        f"comment must specify either 'line' or 'position': {comment!r}"
    )


def extract_pending_comment(api_comment: dict) -> dict:
    """Convert a `/reviews/{id}/comments` response item into a comment shape
    suitable for re-POSTing.

    Pending-review comments come back with `line` and `side` set to null —
    only `original_position` is reliable. Fall through to `position` (which
    may also be set to null on outdated comments) if `original_position` is
    somehow absent.
    """
    path = api_comment.get("path")
    body = api_comment.get("body")
    if path is None or body is None:
        raise ValueError(f"existing comment missing path/body: {api_comment!r}")

    # Prefer original_position — stable across diff updates and present on
    # pending comments where `line`/`side` are null.
    position = api_comment.get("original_position")
    if position is None:
        position = api_comment.get("position")

    line = api_comment.get("line")
    side = api_comment.get("side")
    if line is not None and side is not None:
        return {"path": path, "line": int(line), "side": side, "body": body}

    if position is None:
        raise ValueError(
            f"existing comment has neither line/side nor position: {api_comment!r}"
        )
    return {"path": path, "position": int(position), "body": body}


def _anchor_key(c: dict) -> tuple:
    """Stable identity for dedup. Modern entries key on (path, line, side);
    legacy entries key on (path, position). Forms are never collapsed across
    each other — if a caller mixes modern and legacy for the same logical
    spot, both survive (rare in practice; we use one form per call).
    """
    if c.get("line") is not None:
        return ("modern", c["path"], int(c["line"]), c.get("side") or "RIGHT")
    return ("legacy", c["path"], int(c["position"]))


def merge_comments(existing: list[dict], new: list[dict]) -> list[dict]:
    """Combine existing pending-review comments with newly queued ones, deduped
    by anchor. Existing wins on collision so any user edits made on github.com
    survive the recreate.

    Existing-first ordering preserves the user's reading order if they've
    already started editing the pending review — their edits stay where they
    were, and any genuinely-new comments tail the list.
    """
    out: list[dict] = []
    seen: set[tuple] = set()
    for c in existing:
        norm = normalize_comment(c)
        key = _anchor_key(norm)
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    for c in new:
        norm = normalize_comment(c)
        key = _anchor_key(norm)
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


def build_post_payload(commit_id: str, body: str, comments: list[dict]) -> dict:
    """Assemble the JSON body for POST /pulls/{pr}/reviews.

    Omits the `event` field — that's what makes the new review "pending"
    instead of submitted.
    """
    return {
        "commit_id": commit_id,
        "body": body,
        "comments": comments,
    }


# ---- gh-touching helpers ---------------------------------------------------


def _gh(args: list[str], *, input_data: str | None = None) -> str:
    """Invoke `gh` with the given args. Return stdout. Raise on non-zero."""
    proc = subprocess.run(
        ["gh", *args],
        input=input_data,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or f"gh exited {proc.returncode}"
        raise RuntimeError(f"gh {' '.join(args)} failed: {msg}")
    return proc.stdout


def whoami() -> str:
    return _gh(["api", "user", "--jq", ".login"]).strip()


def find_pending_review(repo: str, pr: int, login: str) -> dict | None:
    out = _gh([
        "api",
        f"repos/{repo}/pulls/{pr}/reviews",
        "--paginate",
        "--jq",
        f'.[] | select(.state == "PENDING" and .user.login == "{login}")',
    ])
    out = out.strip()
    if not out:
        return None
    # `--jq` with the filter above emits one JSON object per match. There can
    # only be one pending review per (user, PR), so take the first.
    first_line = out.splitlines()[0]
    return json.loads(first_line)


def fetch_review_comments(repo: str, pr: int, review_id: int) -> list[dict]:
    out = _gh([
        "api",
        f"repos/{repo}/pulls/{pr}/reviews/{review_id}/comments",
        "--paginate",
        "--slurp",
    ])
    out = out.strip()
    if not out:
        return []
    # `--slurp` wraps every page in an outer array: `[[page1...], [page2...]]`.
    # Flatten one level so the caller sees a flat list of comment dicts.
    pages = json.loads(out)
    return [c for page in pages for c in page]


def delete_review(repo: str, pr: int, review_id: int) -> None:
    _gh([
        "api",
        "--method",
        "DELETE",
        f"repos/{repo}/pulls/{pr}/reviews/{review_id}",
    ])


def post_review(repo: str, pr: int, payload: dict) -> dict:
    out = _gh(
        [
            "api",
            "--method",
            "POST",
            f"repos/{repo}/pulls/{pr}/reviews",
            "--input",
            "-",
        ],
        input_data=json.dumps(payload),
    )
    return json.loads(out)


# ---- backup ---------------------------------------------------------------


def backup_dir() -> Path:
    base = os.environ.get("REVIEW_ASSISTANT_STATE") or os.path.join(
        os.environ["HOME"], ".local", "state", "review-assistant"
    )
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_backup(pr: int, payload: dict, existing_review: dict | None) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = backup_dir() / f"pr-{pr}-recreate-{ts}.json"
    contents = {
        "pr": pr,
        "timestamp": ts,
        "would_post": payload,
        "deleted_review": existing_review,
    }
    path.write_text(json.dumps(contents, indent=2))
    return path


# ---- main -----------------------------------------------------------------


def run(spec: dict) -> dict:
    required = ["repo", "pr", "commit_id", "body", "comments"]
    for key in required:
        if key not in spec:
            raise ValueError(f"input missing required field: {key!r}")

    repo: str = spec["repo"]
    pr: int = int(spec["pr"])
    commit_id: str = spec["commit_id"]
    body: str = spec["body"]
    new_comments: list[dict] = spec["comments"] or []
    if_pending: str = spec.get("if_pending", "merge")
    if if_pending not in ("merge", "replace", "fail"):
        raise ValueError(
            f"if_pending must be merge|replace|fail, got {if_pending!r}"
        )

    login = whoami()
    existing = find_pending_review(repo, pr, login)
    merged_count = 0

    if existing is not None and if_pending == "fail":
        return {
            "error": "pending_review_exists",
            "existing_review_id": existing["id"],
            "existing_comment_count": existing.get("comments_count")
            or existing.get("comment_count")
            or None,
        }

    if existing is not None and if_pending == "merge":
        api_comments = fetch_review_comments(repo, pr, existing["id"])
        merged = [extract_pending_comment(c) for c in api_comments]
        merged_count = len(merged)
        comments_for_post = merge_comments(merged, new_comments)
    else:
        comments_for_post = [normalize_comment(c) for c in new_comments]

    payload = build_post_payload(commit_id, body, comments_for_post)

    backup_path: Path | None = None
    if existing is not None:
        backup_path = write_backup(pr, payload, existing)
        delete_review(repo, pr, existing["id"])

    posted = post_review(repo, pr, payload)
    return {
        "review_id": posted["id"],
        "review_url": posted.get("html_url"),
        "comment_count": len(comments_for_post),
        "replaced_existing": existing is not None,
        "merged_comments": merged_count,
        "backup_path": str(backup_path) if backup_path else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Read JSON spec from this file instead of stdin.",
    )
    args = parser.parse_args()

    try:
        if args.input:
            spec = json.loads(args.input.read_text())
        else:
            spec = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"input is not valid JSON: {e}", file=sys.stderr)
        return 1

    try:
        result = run(spec)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    if result.get("error") == "pending_review_exists":
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
