#!/usr/bin/env python3
"""Tests for the pure helpers inside scripts/post-pending-review.py.

The gh-touching parts (whoami, find_pending_review, fetch_review_comments,
delete_review, post_review) aren't unit-tested — they're exercised by the
real plugin against real PRs. The merge/normalize/extract logic, on the
other hand, is where format mistakes silently corrupt the recreated review,
so it's worth covering.

Run: `python3 tests/test_post_pending_review.py` from repo root.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO / "scripts" / "post-pending-review.py"


def _load_module():
    """Import the helper as a module despite the hyphenated filename."""
    spec = importlib.util.spec_from_file_location("post_pending_review", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PPR = _load_module()


class TestNormalizeComment(unittest.TestCase):
    def test_modern_form_uses_line_and_side(self) -> None:
        out = PPR.normalize_comment(
            {"path": "src/foo.ts", "line": 42, "side": "RIGHT", "body": "x"}
        )
        self.assertEqual(out, {"path": "src/foo.ts", "line": 42, "side": "RIGHT", "body": "x"})

    def test_modern_form_defaults_side_to_right(self) -> None:
        # If line is set but side is missing, default to RIGHT (the post-change
        # side, which is what you almost always want).
        out = PPR.normalize_comment({"path": "src/foo.ts", "line": 42, "body": "x"})
        self.assertEqual(out["side"], "RIGHT")

    def test_legacy_form_uses_position(self) -> None:
        out = PPR.normalize_comment({"path": "src/foo.ts", "position": 7, "body": "x"})
        self.assertEqual(out, {"path": "src/foo.ts", "position": 7, "body": "x"})

    def test_strips_extra_keys(self) -> None:
        # Inputs from the classifier carry source_finding etc. — the API will
        # reject those, so we drop them.
        out = PPR.normalize_comment(
            {
                "path": "src/foo.ts",
                "line": 42,
                "side": "RIGHT",
                "body": "x",
                "source_finding": {"severity": "high"},
                "reason": "verified on RIGHT",
            }
        )
        self.assertNotIn("source_finding", out)
        self.assertNotIn("reason", out)

    def test_missing_line_or_position_raises(self) -> None:
        with self.assertRaises(ValueError):
            PPR.normalize_comment({"path": "src/foo.ts", "body": "x"})

    def test_missing_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            PPR.normalize_comment({"line": 42, "side": "RIGHT", "body": "x"})

    def test_modern_form_wins_when_both_set(self) -> None:
        # If a caller passes both line/side and position, prefer the modern
        # form — GitHub does the same, so matching its behavior is least
        # surprising.
        out = PPR.normalize_comment(
            {"path": "src/foo.ts", "line": 42, "side": "RIGHT", "position": 7, "body": "x"}
        )
        self.assertEqual(out.get("line"), 42)
        self.assertNotIn("position", out)


class TestExtractPendingComment(unittest.TestCase):
    def test_pending_comment_falls_back_to_original_position(self) -> None:
        # Pending-review comments come back with line/side null and only
        # original_position to work with.
        api_comment = {
            "path": "src/foo.ts",
            "line": None,
            "side": None,
            "position": 1,
            "original_position": 509,
            "body": "the comment",
        }
        out = PPR.extract_pending_comment(api_comment)
        self.assertEqual(out, {"path": "src/foo.ts", "position": 509, "body": "the comment"})

    def test_uses_line_side_when_present(self) -> None:
        # On a submitted review (or after a re-anchor), line/side may be set —
        # use them.
        api_comment = {
            "path": "src/foo.ts",
            "line": 42,
            "side": "RIGHT",
            "position": 9,
            "original_position": 7,
            "body": "the comment",
        }
        out = PPR.extract_pending_comment(api_comment)
        self.assertEqual(out, {"path": "src/foo.ts", "line": 42, "side": "RIGHT", "body": "the comment"})

    def test_falls_through_to_position_when_no_original(self) -> None:
        api_comment = {
            "path": "src/foo.ts",
            "line": None,
            "side": None,
            "original_position": None,
            "position": 4,
            "body": "x",
        }
        out = PPR.extract_pending_comment(api_comment)
        self.assertEqual(out["position"], 4)

    def test_raises_when_no_anchor_at_all(self) -> None:
        api_comment = {
            "path": "src/foo.ts",
            "line": None,
            "side": None,
            "original_position": None,
            "position": None,
            "body": "x",
        }
        with self.assertRaises(ValueError):
            PPR.extract_pending_comment(api_comment)


class TestMergeComments(unittest.TestCase):
    def test_existing_first_then_new(self) -> None:
        existing = [
            {"path": "src/a.ts", "position": 5, "body": "edited by user"},
        ]
        new = [
            {"path": "src/b.ts", "line": 12, "side": "RIGHT", "body": "freshly queued"},
        ]
        out = PPR.merge_comments(existing, new)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["body"], "edited by user")
        self.assertEqual(out[1]["body"], "freshly queued")

    def test_each_entry_normalized(self) -> None:
        existing = [{"path": "src/a.ts", "position": 5, "body": "x", "id": 999}]
        new = [{"path": "src/b.ts", "line": 12, "side": "RIGHT", "body": "y", "extra": "drop"}]
        out = PPR.merge_comments(existing, new)
        self.assertNotIn("id", out[0])
        self.assertNotIn("extra", out[1])

    def test_empty_existing_returns_just_new(self) -> None:
        new = [{"path": "src/b.ts", "line": 12, "side": "RIGHT", "body": "y"}]
        out = PPR.merge_comments([], new)
        self.assertEqual(len(out), 1)

    def test_empty_new_returns_just_existing(self) -> None:
        # Edit-only flow: caller hands in the (possibly modified) existing
        # comments and an empty `new` — used for "edit pending bodies and
        # recreate".
        existing = [{"path": "src/a.ts", "position": 5, "body": "edited"}]
        out = PPR.merge_comments(existing, [])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["body"], "edited")

    def test_dedup_modern_anchor_keeps_existing(self) -> None:
        # Re-running --auto regenerates analyzer findings at the same anchors.
        # Existing must win so any user edits survive the recreate.
        existing = [
            {"path": "src/a.ts", "line": 42, "side": "RIGHT", "body": "edited by user"},
        ]
        new = [
            {"path": "src/a.ts", "line": 42, "side": "RIGHT", "body": "fresh analyzer body"},
        ]
        out = PPR.merge_comments(existing, new)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["body"], "edited by user")

    def test_dedup_legacy_anchor_keeps_existing(self) -> None:
        existing = [{"path": "src/a.ts", "position": 7, "body": "edited"}]
        new = [{"path": "src/a.ts", "position": 7, "body": "regenerated"}]
        out = PPR.merge_comments(existing, new)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["body"], "edited")

    def test_dedup_different_sides_are_distinct(self) -> None:
        # Same path+line on RIGHT and LEFT are different anchors (one is the
        # added line, the other the deleted line).
        existing = [
            {"path": "src/a.ts", "line": 42, "side": "RIGHT", "body": "right"},
        ]
        new = [
            {"path": "src/a.ts", "line": 42, "side": "LEFT", "body": "left"},
        ]
        out = PPR.merge_comments(existing, new)
        self.assertEqual(len(out), 2)

    def test_dedup_within_existing(self) -> None:
        # Defensive: if the existing pending somehow contains duplicates
        # (e.g. corrupt prior recreate), collapse them.
        existing = [
            {"path": "src/a.ts", "position": 5, "body": "first"},
            {"path": "src/a.ts", "position": 5, "body": "second"},
        ]
        out = PPR.merge_comments(existing, [])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["body"], "first")


class TestBuildPostPayload(unittest.TestCase):
    def test_omits_event_field(self) -> None:
        # No `event` is what makes the resulting review pending — submitted
        # reviews have event=APPROVE/REQUEST_CHANGES/COMMENT.
        payload = PPR.build_post_payload("abc123", "summary", [{"path": "x", "line": 1, "side": "RIGHT", "body": "y"}])
        self.assertNotIn("event", payload)

    def test_includes_required_fields(self) -> None:
        payload = PPR.build_post_payload("abc123", "summary", [])
        self.assertEqual(payload["commit_id"], "abc123")
        self.assertEqual(payload["body"], "summary")
        self.assertEqual(payload["comments"], [])


if __name__ == "__main__":
    unittest.main()
