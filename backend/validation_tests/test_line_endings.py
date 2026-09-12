"""Regression: shell scripts must reach Synology with LF line endings.

The runbook exports the code with `git archive HEAD`, which applies the same
line-ending conversion as checkout: with `core.autocrlf=true` (Windows PC) and
no `.gitattributes`, LF blobs are exported as CRLF and bash fails on Synology
("invalid option name") before the run starts. `.gitattributes` (`*.sh text
eol=lf`) pins LF for commit, checkout and archive.

Read-only: uses `git ls-files` / `git cat-file` / `git archive` only. Skips
outside a Git checkout (e.g. inside the Synology snapshot container, where the
snapshot checker enforces the same rule on the exported files)."""
import io
import subprocess
import tarfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "backend" / "scripts" / "w0_02_validate_synology.sh"


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, check=True, timeout=60).stdout


def _tracked_sh():
    return [p for p in _git("ls-files", "-z", "--", "*.sh").decode().split("\0") if p]


class LineEndingTests(unittest.TestCase):
    def setUp(self):
        if not (REPO / ".git").exists():
            self.skipTest("not a git checkout (snapshot container)")

    def test_gitattributes_forces_lf_for_shell_scripts(self):
        attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
        rules = [line.split() for line in attrs.splitlines()
                 if line.split() and line.split()[0] == "*.sh"]
        self.assertTrue(rules, "missing '*.sh' rule in .gitattributes")
        self.assertIn("text", rules[0])
        self.assertIn("eol=lf", rules[0])

    def test_committed_shell_blobs_have_no_cr(self):
        paths = _tracked_sh()
        self.assertTrue(paths, "no tracked *.sh files found")
        bad = [p for p in paths if b"\r" in _git("cat-file", "blob", "HEAD:" + p)]
        self.assertEqual(bad, [], "CRLF in committed shell scripts: " + ", ".join(bad))

    def test_git_archive_exports_shell_scripts_with_lf(self):
        # Same command family as runbook section A (`git archive HEAD`), so this
        # reproduces the exact defect regardless of the PC's core.autocrlf.
        paths = _tracked_sh()
        self.assertTrue(paths, "no tracked *.sh files found")
        tar = _git("archive", "--format=tar", "HEAD", "--", *paths)
        bad = []
        with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
            for m in tf:
                if m.isfile() and b"\r" in tf.extractfile(m).read():
                    bad.append(m.name)
        self.assertEqual(bad, [], "CRLF in `git archive HEAD` output: " + ", ".join(bad))

    def test_working_tree_validation_wrapper_has_no_cr(self):
        self.assertNotIn(b"\r", WRAPPER.read_bytes(), "CRLF in working-tree wrapper")
