"""The requirement checks (`gt_ready.py`) against the stand-in Gitea: each row's specific
sentence, which address, which account, which scope."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import suitefence  # noqa: F401

import gt_ready
from keel.packkit.world import World
from test_conformance import WorldServed, git_env

REPO = "octo/api"


class ReadyTest(WorldServed, unittest.TestCase):
    def setUp(self):
        served = self.stand_in()
        self.world = World()
        self.world.repo(REPO)
        self.clone = self.made_clone(f"{served.base}/{REPO}.git")
        self.env(self.clone)

    def made_clone(self, remote: str) -> Path:
        folder = tempfile.TemporaryDirectory(prefix="keel-gitea-clone-")
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "api"
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
        return path

    def env(self, *clones: Path) -> None:
        patcher = mock.patch.dict(os.environ, {**git_env(self.served.git_config()),
                                               "KEEL_SPACE_REPOS": os.pathsep.join(map(str, clones))})
        patcher.start()
        self.addCleanup(patcher.stop)

    def checked(self) -> dict:
        self.host_serve(self.world)
        return {one["name"]: one for one in gt_ready.rows()}

    def test_every_check_passes_for_a_token_allowed_enough_on_a_repo_it_may_push(self):
        rows = self.checked()
        self.assertEqual([name for name, one in rows.items() if not one["ok"]], [])
        self.assertIn("as me on 127.0.0.1", rows["sign-in"]["why"])

    def test_a_token_without_the_scope_names_it_and_the_lines_to_swap_it(self):
        self.world.data["fail"]["scope"] = "read:issue"
        row = self.checked()["token"]
        self.assertFalse(row["ok"])
        self.assertIn("not allowed read:issue", row["why"])
        self.assertIn(f"url={self.served.base}", row["fix"])

    def test_an_account_that_may_only_read_is_named(self):
        self.world.repo(REPO)["access"] = "read"
        row = self.checked()["access"]
        self.assertEqual((row["ok"], row["why"]), (False, "You are signed in to Gitea as me, which can read "
                                                          "octo/api but cannot push to it."))

    def test_no_sign_in_kept_for_the_address_is_signed_out(self):
        self.served.helper.write_text("#!/bin/sh\nexit 0\n")
        row = self.checked()["sign-in"]
        self.assertFalse(row["ok"])
        self.assertIn("git keeps no sign-in for 127.0.0.1", row["why"])

    def test_an_ssh_address_is_not_one_this_connection_can_use(self):
        self.env(self.made_clone("git@box:octo/api.git"))
        row = self.checked()["address"]
        self.assertFalse(row["ok"])
        self.assertIn("is not an http or https address", row["why"])


if __name__ == "__main__":
    unittest.main()
