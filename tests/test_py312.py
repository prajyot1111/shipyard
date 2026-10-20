"""The Python 3.12 import check (`tests/py312.py`), the `py312` job of `make test`.

The box runs Keel on its own /usr/bin/python3, which is 3.12, while the Mac runs 3.14. 3.14
evaluates annotations lazily, so a module that names a class in an annotation before
defining it imports on the Mac and fails on the box at import. These cases build a small
package in a temporary directory and run the real check over it under the real
`python3.12`, skipping when the machine has none (the check itself then says so).
"""

import re
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests import py312

ROOT = Path(__file__).resolve().parent.parent
PY312 = shutil.which("python3.12")

FINE = "import json\n\ndef load(text: str) -> dict:\n    return json.loads(text)\n"
# Fine under 3.14 (annotations are evaluated only when read), a NameError under 3.12.
LATE_NAME = textwrap.dedent("""
    def make() -> Later:
        return Later()

    class Later:
        pass
""")
SCRIPT = textwrap.dedent("""\
    #!/usr/bin/env python3
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from keel.{module} import {name}  # noqa: E402

    sys.exit({name}())
""")


class Tree:
    """A scratch root with keel/ and bin/, shaped like the repo."""

    def __init__(self, test: unittest.TestCase):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "keel").mkdir()
        (self.root / "keel" / "__init__.py").write_text("")
        (self.root / "bin").mkdir()

    def module(self, name: str, text: str) -> None:
        (self.root / "keel" / f"{name}.py").write_text(text)

    def script(self, name: str, text: str) -> None:
        (self.root / "bin" / name).write_text(text)


@unittest.skipUnless(PY312, "no python3.12 on this machine")
class CheckTest(unittest.TestCase):
    def test_a_module_that_imports_only_under_314_fails_the_check(self):
        tree = Tree(self)
        tree.module("fine", FINE)
        tree.module("late", LATE_NAME)
        code, lines = py312.check(tree.root, PY312)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any("keel.late" in line and "NameError" in line for line in lines), lines)
        self.assertFalse(any("keel.fine" in line for line in lines[:-1]), lines)
        self.assertRegex(lines[-1], r"^py312: FAILED")

    def test_a_script_naming_a_keel_function_that_is_not_there_fails(self):
        tree = Tree(self)
        tree.module("fine", FINE)
        tree.script("kb", SCRIPT.format(module="fine", name="main"))
        code, lines = py312.check(tree.root, PY312)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any("bin/kb" in line and "main" in line for line in lines), lines)

    def test_a_clean_tree_passes_with_its_completion_line(self):
        tree = Tree(self)
        tree.module("fine", FINE)
        tree.script("kb", SCRIPT.format(module="fine", name="load"))
        tree.script("other", "#!/bin/sh\necho not python\n")
        code, lines = py312.check(tree.root, PY312)
        self.assertEqual(code, 0, lines)
        self.assertRegex(lines[-1], py312.DONE)
        self.assertIn("1 module and 1 script", lines[-1])

    def test_the_repo_itself_imports_under_312(self):
        code, lines = py312.check(ROOT, PY312)
        self.assertEqual(code, 0, "\n".join(lines))


class SkipTest(unittest.TestCase):
    def test_no_interpreter_is_a_skip_that_still_says_it_finished(self):
        code, lines = py312.check(ROOT, None)
        self.assertEqual(code, 0)
        self.assertRegex(lines[-1], r"^py312: skipped")
        self.assertRegex(lines[-1], py312.DONE)


class WiredTest(unittest.TestCase):
    def test_make_test_runs_it_as_a_job_with_its_completion_line(self):
        recipe = (ROOT / "Makefile").read_text()
        self.assertIn("--job 'py312=$(PY312_CHECK)'", recipe)
        self.assertIn("--done '$(PY312_DONE)'", recipe)
        done = re.search(r"^PY312_DONE = py312=(.*)$", recipe, re.M).group(1).replace("$$", "$")
        self.assertEqual(done, py312.DONE)


if __name__ == "__main__":
    unittest.main()
