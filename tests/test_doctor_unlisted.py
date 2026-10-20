"""`keel doctor` names a clone of a space's org that the space does not list (c-509,
2026-09-25: the team's skills repo sat cloned beside api and web, unlisted, so a
card could not name it). A repo of another org beside them (his own GitHub tools) is not
one of the space's and is never named."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import doctor
from keel.config import Space


def clone(path: Path, origin: str) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    return path


class UnlistedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        clone(ws / "api", "git@codehost.example:example-org/api.git")
        clone(ws / "skills", "git@codehost.example:example-org/skills.git")
        clone(ws / "tools", "https://github.com/someone/tools.git")
        (ws / "notes").mkdir()
        self.space = Space(name="work", config_dir=ws, repos={"api": ws / "api"}, contract=None, adapter=None)
        self.ws = ws

    def test_an_unlisted_clone_of_the_org_is_named(self):
        self.assertEqual(doctor.unlisted_repos(self.space), {"skills": str((self.ws / "skills").resolve())})

    def test_it_is_a_problem_on_the_serving_host_and_not_elsewhere(self):
        [said] = doctor.unlisted_problems("work", doctor.space_report(self.space))
        self.assertIn("skills", said)
        self.assertIn("not listed", said)
        self.assertEqual(doctor.unlisted_problems("work", doctor.space_report(self.space, served=False)), [])

    def test_a_space_with_nothing_unlisted_says_nothing(self):
        self.space.repos["skills"] = self.ws / "skills"
        self.assertEqual(doctor.unlisted_repos(self.space), {})

    def test_a_clone_beside_the_code_checkout_is_not_named_on_an_install(self):
        """c-618: an install listing Keel itself did not choose the folder Keel sits in; the
        live config's scan is as before."""
        code = clone(self.ws / "keel", "git@codehost.example:example-org/keel.git")
        space = Space(name="personal", config_dir=self.ws, repos={"keel": code}, contract=None, adapter=None)
        with mock.patch.dict(os.environ, {"KEEL_HOME": str(code)}):
            self.assertEqual(doctor.unlisted_repos(space, install=True), {})
            self.assertIn("skills", doctor.unlisted_repos(space))


if __name__ == "__main__":
    unittest.main()
