"""NOTICE names every third-party work the tree carries (c-699, review F5).

A work somebody else made is found by where it sits and what it is, never by a list kept
here: every tracked file under a `vendor/` directory, every minified script, every font and
every sound. Each must sit at, or under, a path NOTICE names. NOTICE may not say a work is
unmodified when the tree's own credits say it was changed, and every path it names exists.
"""

import re
import subprocess
import unittest
from pathlib import Path

from tests.helpers import left_out

ROOT = Path(__file__).resolve().parent.parent
NOTICE = ROOT / "NOTICE"
MEDIA = {".mp3", ".ogg", ".wav", ".m4a", ".flac", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".wasm"}
OURS = {"README.md"}                      # a vendor directory's own note on how it was filled
PATH = re.compile(r"^\s+((?:[\w.-]+/)+[\w.-]*)\s*$", re.M)


def tracked() -> list[str]:
    done = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in done.stdout.splitlines() if line]


def third_party(files: list[str]) -> list[str]:
    """The tracked files that are somebody else's work, by place and by kind."""
    found = []
    for rel in files:
        path = Path(rel)
        if path.name in OURS:
            continue
        if "vendor" in path.parts[:-1] or path.name.endswith((".min.js", ".min.css")) or path.suffix.lower() in MEDIA:
            found.append(rel)
    return found


def elsewhere(path: str) -> bool:
    """A path in a segment this tree does not carry: one install's own, which moves to that
    install with the segment (c-722). Its NOTICE entry leaves the tree with it."""
    parts = Path(path).parts
    return len(parts) > 2 and parts[0] == "segments" and not (ROOT / parts[0] / parts[1]).is_dir()


def named(text: str) -> list[str]:
    """The paths NOTICE gives a work, each on a line of its own under the work's name."""
    return PATH.findall(text)


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.text = NOTICE.read_text(encoding="utf-8")

    def test_every_third_party_file_in_the_tree_is_under_a_path_notice_names(self):
        paths = named(self.text)
        self.assertTrue(paths)
        missing = [rel for rel in third_party(tracked())
                   if not any(rel == path or (path.endswith("/") and rel.startswith(path)) for path in paths)]
        self.assertEqual(missing, [], "third-party files NOTICE does not name:\n" + "\n".join(missing))

    def test_every_path_notice_names_is_in_the_tree(self):
        gone = [path for path in named(self.text) if not (ROOT / path).exists() and not elsewhere(path)
                and not left_out(path)]
        self.assertEqual(gone, [], "NOTICE names a path the tree does not hold")

    def test_every_licence_file_notice_points_at_exists(self):
        told = re.findall(r"license text is (\S+?)\.?\s", self.text)
        self.assertTrue(told)
        self.assertEqual([path for path in told if not (ROOT / path).is_file() and not elsewhere(path)
                          and not left_out(path)], [])

    def test_it_does_not_call_a_changed_work_unmodified(self):
        """The demo's music was re-encoded with its tags and cover removed
        (`demo/music/CREDITS.md`), so no blanket "each unmodified" may stand."""
        self.assertNotIn("each unmodified", self.text)
        credits = ROOT / "demo" / "music" / "CREDITS.md"
        if not left_out("demo/music/CREDITS.md"):
            self.assertIn("re-encoded", credits.read_text(encoding="utf-8"))
        self.assertIn("re-encoded", self.text)

    def test_the_finder_knows_a_vendored_file_a_minified_one_and_a_sound(self):
        files = ["app/vendor/README.md", "app/vendor/x.js", "segments/a/app/vendor/y.LICENSE",
                 "app/z.min.js", "demo/music/t.mp3", "app/ui.core.js", "docs/vendor.md"]
        self.assertEqual(third_party(files), ["app/vendor/x.js", "segments/a/app/vendor/y.LICENSE",
                                              "app/z.min.js", "demo/music/t.mp3"])


if __name__ == "__main__":
    unittest.main()
