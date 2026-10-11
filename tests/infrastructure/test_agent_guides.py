"""AGENTS.md and CLAUDE.md are one guide kept as two identical files (ARA-114)."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AgentGuideTests(unittest.TestCase):
    def test_given_both_guides_when_compared_then_claude_md_is_an_identical_copy(self):
        agents, claude = ROOT / "AGENTS.md", ROOT / "CLAUDE.md"
        # A plain file, not a symlink: a symlink checks out as a one-line file on Windows.
        self.assertFalse(claude.is_symlink(), "CLAUDE.md must be a copy, not a symlink")
        self.assertEqual(
            claude.read_bytes(),
            agents.read_bytes(),
            "CLAUDE.md differs from AGENTS.md; apply the same change to both",
        )


if __name__ == "__main__":
    unittest.main()
