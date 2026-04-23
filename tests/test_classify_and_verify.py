#!/usr/bin/env python3
"""Tests for scripts/classify-and-verify.py.

Covers the line-verification behavior strengthened in the --auto + walkthrough
flows. Run: `python3 tests/test_classify_and_verify.py` from repo root.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "classify-and-verify.py"


DIFF = """\
diff --git a/src/foo.ts b/src/foo.ts
index 1111111..2222222 100644
--- a/src/foo.ts
+++ b/src/foo.ts
@@ -10,5 +10,6 @@ export function foo() {
   const user = getUser();
-  return user.id;
+  const id = user.id;
+  return id;
 }
"""


def classify(findings_block: str, section: str = "findings") -> dict:
    session = (
        "# Review Session: PR #1\n"
        "review_sha: abc\n"
        "threshold: 50\n\n"
        "## Why\nTest\n\n"
        f"## {section.capitalize() if section == 'findings' else 'Below Threshold'}\n"
        f"{findings_block}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "diff").write_text(DIFF)
        (d / "session.md").write_text(session)
        out = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--diff",
                str(d / "diff"),
                "--session",
                str(d / "session.md"),
                "--section",
                section,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(out.stdout)


class TestClassifyAndVerify(unittest.TestCase):
    def test_exact_match_stays_inline_at_reported_line(self) -> None:
        # `const id = user.id;` sits at RIGHT-side line 11 in the hunk above.
        block = (
            "- file: src/foo.ts, line: 11, severity: high, confidence: 80, "
            "source: bug-scan, skip: false, in_diff: true\n"
            "  code: `const id = user.id;`\n"
            "  Missing null check\n"
        )
        result = classify(block)
        self.assertEqual(result["stats"]["inline"], 1)
        self.assertEqual(result["stats"]["fallback"], 0)
        self.assertEqual(result["stats"]["suspect"], 0)
        self.assertEqual(result["inline"][0]["line"], 11)
        self.assertEqual(result["inline"][0]["side"], "RIGHT")

    def test_near_miss_gets_re_anchored_by_text(self) -> None:
        # Analyzer said line 13, but `const id = user.id;` is actually at line 11.
        block = (
            "- file: src/foo.ts, line: 13, severity: medium, confidence: 70, "
            "source: bug-scan, skip: false, in_diff: true\n"
            "  code: `const id = user.id;`\n"
            "  Near-miss anchor should re-target\n"
        )
        result = classify(block)
        self.assertEqual(result["stats"]["inline"], 1)
        self.assertEqual(result["inline"][0]["line"], 11)
        self.assertIn("re-anchored", result["inline"][0]["reason"])

    def test_anchor_with_no_match_becomes_suspect(self) -> None:
        block = (
            "- file: src/foo.ts, line: 13, severity: low, confidence: 60, "
            "source: code-comments, skip: false, in_diff: true\n"
            "  code: `return nothing;`\n"
            "  Anchor never appears in diff\n"
        )
        result = classify(block)
        self.assertEqual(result["stats"]["inline"], 0)
        self.assertEqual(result["stats"]["suspect"], 1)
        self.assertIn("did not match", result["suspect"][0]["reason"])

    def test_line_outside_any_hunk_becomes_fallback(self) -> None:
        block = (
            "- file: src/foo.ts, line: 99, severity: info, confidence: 55, "
            "source: claude-md, skip: false, in_diff: true\n"
            "  code: `whatever`\n"
            "  Outside every hunk\n"
        )
        result = classify(block)
        self.assertEqual(result["stats"]["inline"], 0)
        self.assertEqual(result["stats"]["fallback"], 1)
        self.assertEqual(result["fallback"][0]["line"], 99)

    def test_in_diff_false_never_posts_inline(self) -> None:
        # Even though line 11 is in the diff, in_diff:false forces fallback.
        block = (
            "- file: src/foo.ts, line: 11, severity: high, confidence: 80, "
            "source: bug-scan, skip: false, in_diff: false\n"
            "  code: `const id = user.id;`\n"
            "  Analyzer flagged as outside diff\n"
        )
        result = classify(block)
        self.assertEqual(result["stats"]["inline"], 0)
        self.assertEqual(result["stats"]["fallback"], 1)
        self.assertIn("outside diff", result["fallback"][0]["reason"])

    def test_skipped_file_finding_is_fallback(self) -> None:
        block = (
            "- file: generated/types.ts, line: 1, severity: info, confidence: 100, "
            "source: claude-md, skip: true, in_diff: true\n"
            "  code: `export type X = ...`\n"
            "  Skipped generated file\n"
        )
        result = classify(block)
        self.assertEqual(result["stats"]["inline"], 0)
        self.assertEqual(result["stats"]["fallback"], 1)

    def test_left_side_anchors_to_deleted_line(self) -> None:
        # "return user.id;" is on the LEFT side (deleted); analyzer reports line 11.
        block = (
            "- file: src/foo.ts, line: 11, severity: medium, confidence: 65, "
            "source: git-history, skip: false, in_diff: true\n"
            "  code: `return user.id;`\n"
            "  Comment on deleted line\n"
        )
        result = classify(block)
        self.assertEqual(result["stats"]["inline"], 1)
        self.assertEqual(result["inline"][0]["side"], "LEFT")


if __name__ == "__main__":
    unittest.main()
