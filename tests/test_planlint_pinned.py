"""A plan's `path:line` refs resolve at the commit it was planned against (`at:` in its
frontmatter), not at a later HEAD (2026-09-25).

A plan describes the code BEFORE the change: its Now section cites the lines the change
will replace. Once the house builds, those lines move or go, and a plan checked at HEAD
reads as broken on its own page, or worse, points at other code. Found converting the
pre-format cards (c-238's plan cites `analysis_routes.py:329-331`, which after the fix holds
different code). `at:` names the commit, one per repo for a cross-repo card, comma
separated; a commit a checkout does not have is skipped there, and with none it has, that
checkout is read at HEAD as before. An outcome is read at the card's branch tip
(tests/test_planlint_tip.py): it describes the change as built.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import planlint

GIT_ID = ("-c", "user.name=t", "-c", "user.email=t@t")


def commit(root: Path, name: str, lines: int) -> str:
    (root / name).write_text("\n".join(f"line {i}" for i in range(lines)) + "\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), *GIT_ID, "commit", "-q", "-m", "x"], check=True)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


def repo(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    return root


def doc(kind: str, ref: str, at: str | None = None) -> str:
    head = f"---\nkind: {kind}\ncard: c-901\ntitle: T\nrepo: api\n" + (f"at: {at}\n" if at else "") + "---\n"
    return head + f"# T\n\nIt reads {ref} today.\n"


def c7(text: str, resolve) -> list[str]:
    result = planlint.lint_text(text, "plan.md", repo_card=True, resolve=resolve)
    return [f["text"] for f in result["findings"] if f["rule"] == "C7"]


class PinnedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = repo(Path(tmp.name) / "api")
        self.planned = commit(self.root, "routes.py", 50)     # the plan cites line 40 here
        commit(self.root, "routes.py", 10)                    # the change: the file is short now
        self.web = repo(Path(tmp.name) / "web")
        self.web_planned = commit(self.web, "Page.js", 30)
        commit(self.web, "Page.js", 5)

    def test_a_plan_pinned_to_its_commit_resolves_there(self):
        self.assertEqual(c7(doc("plan", "routes.py:40", self.planned), planlint.GitResolver(self.root)), [])

    def test_unpinned_it_is_read_at_head_as_before(self):
        [said] = c7(doc("plan", "routes.py:40"), planlint.GitResolver(self.root))
        self.assertIn("does not resolve at HEAD", said)

    def test_a_pinned_ref_that_did_not_exist_then_is_refused_and_names_the_commit(self):
        [said] = c7(doc("plan", "routes.py:60", self.planned), planlint.GitResolver(self.root))
        self.assertIn(f"does not resolve at {self.planned[:10]}", said)

    def test_an_outcome_is_always_read_at_head(self):
        [said] = c7(doc("outcome", "routes.py:40", self.planned), planlint.GitResolver(self.root))
        self.assertIn("does not resolve at HEAD", said)

    def test_a_cross_repo_plan_names_a_commit_per_repo(self):
        both = planlint.AnyResolver([self.root, self.web])
        text = doc("plan", "routes.py:40 and Page.js:25", f"{self.planned}, {self.web_planned}")
        self.assertEqual(c7(text, both), [])

    def test_a_commit_the_checkout_does_not_have_leaves_it_at_head(self):
        [said] = c7(doc("plan", "routes.py:40", "0" * 40), planlint.GitResolver(self.root))
        self.assertIn("does not resolve at HEAD", said)


class SettledDecisionTest(unittest.TestCase):
    """An approved plan folds each answered decision in as settled (FOLD_IN) and takes the
    block out; a `> [!settled]` callout under Decisions says so truthfully, where C11 used to
    want `None:` for a plan that did decide something (2026-09-25)."""

    PLAN = "---\nkind: plan\ncard: c-901\ntitle: T\n---\n# T\n\nS.\n\n## Decisions\n\n{body}\n"

    def c11(self, body):
        result = planlint.lint_text(self.PLAN.format(body=body), "plan.md")
        return [f for f in result["findings"] if f["rule"] == "C11"]

    def test_a_settled_callout_is_a_decided_plan(self):
        self.assertEqual(self.c11("> [!settled] Fix only the reads\n> He chose it."), [])

    def test_none_still_passes_and_an_empty_section_still_does_not(self):
        self.assertEqual(self.c11("None: nothing to decide."), [])
        self.assertEqual(len(self.c11("Some words.")), 1)

    def test_another_callout_is_not_a_decision(self):
        self.assertEqual(len(self.c11("> [!info] Worth knowing\n> Words.")), 1)


class ThirdPartyTest(unittest.TestCase):
    """A ref into a dependency's code (`node_modules/`, `site-packages/`) is not the card's
    code and no worktree tracks it: C7 skips it, so a root cause in a library can be cited
    by line instead of reworded into prose (2026-09-25, the pre-format cards' conversions:
    marshmallow, pika, react-redux-toastr, jsdom)."""

    def test_dependency_refs_are_not_checked(self):
        never = lambda path, start, end: "no such file"      # noqa: E731 - a resolver that fails all
        text = doc("outcome", "node_modules/react-redux-toastr/src/utils.js:40 and "
                              "venv/lib/python3.8/site-packages/marshmallow/schema.py:610")
        self.assertEqual(c7(text, never), [])

    def test_the_card_s_own_refs_still_are(self):
        never = lambda path, start, end: "no such file"      # noqa: E731
        self.assertEqual(len(c7(doc("outcome", "src/node_modules_helper.js:4"), never)), 1)


class RefShapeTest(unittest.TestCase):
    """What reads as a `path:line` (2026-09-25, from the conversions): a build file with no
    extension (`ci/Makefile:209`, `app/Dockerfile:24`) is one, so a pipeline card's refs are
    linked and checked like any other; a ratio or a version (`4.5:1`, `3.12:40`) is not."""

    def paths(self, text):
        from keel import planinline
        return [r["v"] for r in planinline.refs_in(text) if r.get("kind") == "path"]

    def test_build_files_without_an_extension_are_refs(self):
        self.assertEqual(self.paths("see ci/Makefile:209 and app/build/server/Dockerfile:24-30"),
                         ["ci/Makefile:209", "app/build/server/Dockerfile:24-30"])

    def test_a_ratio_or_a_version_is_not(self):
        self.assertEqual(self.paths("contrast 4.5:1 on Python 3.12:40 and 12:30"), [])

    def test_a_word_ending_in_file_is_not_unless_under_a_directory(self):
        self.assertEqual(self.paths("Profile:2 items, then ci/Buildfile:7"), ["ci/Buildfile:7"])

    def test_ordinary_refs_still_are(self):
        self.assertEqual(self.paths("app/x.py:4 and src/A.test.jsx:10-12"), ["app/x.py:4", "src/A.test.jsx:10-12"])


if __name__ == "__main__":
    unittest.main()
