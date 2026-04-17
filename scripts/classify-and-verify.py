#!/usr/bin/env python3
"""
Classify PR-review findings into GitHub-postable buckets.

Reads a unified diff and a session-file's findings, then partitions findings
into three buckets:
  - inline:   safe to post as an inline review comment (file+line+side verified)
  - fallback: should go in the review body (line is outside any hunk OR the
              finding was recorded with in_diff: false)
  - suspect:  analyzer gave a line that is inside a hunk but the line text
              doesn't match what the diff actually shows, even after a ±3
              line scan. Also put in the review body, but flagged so the
              reviewer knows the auto-anchor was unreliable.

Usage:
  classify-and-verify.py --diff <path> --session <path> [--section findings|below|all]

Emits JSON on stdout:
  {
    "inline":   [ { path, line, side, body, source_finding } ],
    "fallback": [ { path, line, body, reason, source_finding } ],
    "suspect":  [ { path, line, body, reason, source_finding, best_guess_line } ],
    "stats":    { inline, fallback, suspect, total }
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---- diff parsing ---------------------------------------------------------

DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
HUNK_RE = re.compile(
    r"^@@ -(?P<ol>\d+)(?:,(?P<oc>\d+))? \+(?P<nl>\d+)(?:,(?P<nc>\d+))? @@"
)


@dataclass
class FileDiff:
    path: str
    # (line_number) -> exact text of that line on the right side (post-change)
    right: dict[int, str] = field(default_factory=dict)
    # (line_number) -> exact text of that line on the left side (pre-change)
    left: dict[int, str] = field(default_factory=dict)


def parse_diff(diff_text: str) -> dict[str, FileDiff]:
    """Walk every hunk body and record which lines exist on each side.

    A RIGHT-side line exists iff the diff row is '+' (added) or ' ' (context).
    A LEFT-side line exists iff the diff row is '-' (deleted) or ' ' (context).
    Tracking the hunk body (not just the @@ range) is what catches deleted-
    vs added-line mix-ups.
    """
    files: dict[str, FileDiff] = {}
    current: FileDiff | None = None
    right_line = left_line = 0
    in_hunk = False

    for raw in diff_text.splitlines():
        git_match = DIFF_GIT_RE.match(raw)
        if git_match:
            path = git_match.group("b")
            current = FileDiff(path=path)
            files[path] = current
            in_hunk = False
            continue

        if current is None:
            continue

        hunk = HUNK_RE.match(raw)
        if hunk:
            left_line = int(hunk.group("ol"))
            right_line = int(hunk.group("nl"))
            in_hunk = True
            continue

        if not in_hunk:
            continue

        if not raw:
            # Empty line inside a hunk is a context line with empty content.
            current.right[right_line] = ""
            current.left[left_line] = ""
            right_line += 1
            left_line += 1
            continue

        marker, _, body = raw[0], raw[0], raw[1:]
        if marker == "+":
            current.right[right_line] = body
            right_line += 1
        elif marker == "-":
            current.left[left_line] = body
            left_line += 1
        elif marker == " ":
            current.right[right_line] = body
            current.left[left_line] = body
            right_line += 1
            left_line += 1
        elif marker == "\\":
            # "\ No newline at end of file" — ignore
            continue
        else:
            # Hunk over; next section begins
            in_hunk = False

    return files


# ---- session parsing ------------------------------------------------------

FINDING_HEAD_RE = re.compile(r"^- file: (?P<file>[^,]+?), line: (?P<line>\d+)(?P<rest>.*)$")
KV_RE = re.compile(r"(\w+): ([^,]+)")


@dataclass
class Finding:
    file: str
    line: int
    severity: str = "unknown"
    confidence: int = 0
    source: str = "unknown"
    skip: bool = False
    in_diff: bool = True
    code: str | None = None
    description: str = ""
    section: str = "findings"  # "findings" or "below"


def parse_session(session_text: str, section_filter: str) -> list[Finding]:
    lines = session_text.splitlines()
    out: list[Finding] = []

    current_section: str | None = None
    current: Finding | None = None

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("## "):
            header = stripped[3:].strip().lower()
            if header == "findings":
                current_section = "findings"
            elif header.startswith("below threshold"):
                current_section = "below"
            else:
                current_section = None
            if current is not None:
                out.append(current)
                current = None
            continue

        if current_section is None:
            continue
        if section_filter != "all" and current_section != section_filter:
            continue

        head = FINDING_HEAD_RE.match(raw)
        if head:
            if current is not None:
                out.append(current)
            current = Finding(
                file=head.group("file").strip(),
                line=int(head.group("line")),
                section=current_section,
            )
            for k, v in KV_RE.findall(head.group("rest")):
                v = v.strip()
                if k == "severity":
                    current.severity = v
                elif k == "confidence":
                    try:
                        current.confidence = int(v)
                    except ValueError:
                        pass
                elif k == "source":
                    current.source = v
                elif k == "skip":
                    current.skip = v.lower() == "true"
                elif k == "in_diff":
                    current.in_diff = v.lower() != "false"
            continue

        if current is None:
            continue

        # Continuation lines: `  code: ...` or `  <description>` or `  <more>`
        indented = raw.lstrip()
        if indented.startswith("code: "):
            code_val = indented[6:].strip()
            if code_val.startswith("`") and code_val.endswith("`") and len(code_val) >= 2:
                code_val = code_val[1:-1]
            current.code = code_val
        elif raw.startswith("  ") and stripped:
            current.description = (
                stripped if not current.description else f"{current.description}\n{stripped}"
            )

    if current is not None:
        out.append(current)

    # Dedup by (file, line, description)
    seen: set[tuple[str, int, str]] = set()
    deduped: list[Finding] = []
    for f in out:
        key = (f.file, f.line, f.description)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped


# ---- verification ---------------------------------------------------------

def verify(finding: Finding, diff: dict[str, FileDiff]) -> tuple[str, int, str, str]:
    """Return (bucket, final_line, side, reason).

    bucket:
      - "inline"   — post as inline comment
      - "fallback" — outside any hunk for this file, or finding carries
                     in_diff: false
      - "suspect"  — inside a hunk but anchor text didn't match even after
                     scanning nearby lines
    """
    if finding.skip:
        return "fallback", finding.line, "RIGHT", "skipped file"

    if not finding.in_diff:
        return "fallback", finding.line, "RIGHT", "analyzer flagged line as outside diff"

    file_diff = diff.get(finding.file)
    if file_diff is None:
        return "fallback", finding.line, "RIGHT", "file not in PR diff"

    right = file_diff.right
    left = file_diff.left

    # Prefer RIGHT side — that's where post-change findings live. But if the
    # reported line falls in both indexes and the code matches LEFT, prefer
    # LEFT (a deleted-line comment). Always try a direct match on both sides
    # before falling back to ±3 re-anchoring on either side.
    in_right = finding.line in right
    in_left = finding.line in left

    if in_right and (finding.code is None or _matches(finding.code, right[finding.line])):
        return "inline", finding.line, "RIGHT", "verified on RIGHT"
    if in_left and (finding.code is None or _matches(finding.code, left[finding.line])):
        return "inline", finding.line, "LEFT", "verified on LEFT (deleted line)"

    if finding.code:
        nearby_right = _scan(right, finding.line, finding.code)
        if nearby_right is not None:
            return "inline", nearby_right, "RIGHT", f"re-anchored {nearby_right - finding.line:+d} lines on RIGHT"
        nearby_left = _scan(left, finding.line, finding.code)
        if nearby_left is not None:
            return "inline", nearby_left, "LEFT", f"re-anchored {nearby_left - finding.line:+d} lines on LEFT"

    if in_right or in_left:
        side = "RIGHT" if in_right else "LEFT"
        return "suspect", finding.line, side, f"code did not match {side}-side line or ±3 neighbors"

    return "fallback", finding.line, "RIGHT", "line outside every hunk in this file"


def _matches(code: str, diff_line: str) -> bool:
    return _norm(code) == _norm(diff_line)


def _norm(s: str) -> str:
    return " ".join(s.split())


def _scan(index: dict[int, str], target: int, code: str | None, radius: int = 3) -> int | None:
    if code is None:
        return None
    for delta in range(1, radius + 1):
        for cand in (target - delta, target + delta):
            if cand in index and _matches(code, index[cand]):
                return cand
    return None


# ---- glue ------------------------------------------------------------------

def format_body(f: Finding) -> str:
    return (
        f"**{f.severity}** (confidence {f.confidence}, source: {f.source})\n\n"
        f"{f.description}"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--diff", required=True, type=Path)
    p.add_argument("--session", required=True, type=Path)
    p.add_argument(
        "--section",
        choices=("findings", "below", "all"),
        default="findings",
        help="Which session section to read",
    )
    args = p.parse_args()

    diff_text = args.diff.read_text()
    session_text = args.session.read_text()

    files = parse_diff(diff_text)
    findings = parse_session(session_text, args.section)

    inline: list[dict] = []
    fallback: list[dict] = []
    suspect: list[dict] = []

    for f in findings:
        bucket, line, side, reason = verify(f, files)
        body = format_body(f)
        src = {
            "file": f.file,
            "original_line": f.line,
            "severity": f.severity,
            "confidence": f.confidence,
            "source": f.source,
            "description": f.description,
            "code": f.code,
            "section": f.section,
        }
        if bucket == "inline":
            inline.append({
                "path": f.file,
                "line": line,
                "side": side,
                "body": body,
                "source_finding": src,
                "reason": reason,
            })
        elif bucket == "fallback":
            fallback.append({
                "path": f.file,
                "line": f.line,
                "body": body,
                "reason": reason,
                "source_finding": src,
            })
        else:
            suspect.append({
                "path": f.file,
                "line": f.line,
                "body": body,
                "reason": reason,
                "best_guess_line": line,
                "source_finding": src,
            })

    out = {
        "inline": inline,
        "fallback": fallback,
        "suspect": suspect,
        "stats": {
            "inline": len(inline),
            "fallback": len(fallback),
            "suspect": len(suspect),
            "total": len(findings),
        },
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
