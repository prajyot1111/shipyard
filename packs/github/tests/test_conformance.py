"""The GitHub pack held to the kit's conformance suite (`keel/packkit/conformance.py`): its
real layer against a world its stand-in `gh` serves (`ghworld.py`), its guard, and its
executables over a card's and a review card's whole life.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import suitefence

import gh_fence
import gh_layer
import ghworld
from keel.packkit.conformance import GuardContract, HostContract, ReviewsContract, VerbsContract
from keel.packkit.layer import Repo
from keel.packkit.world import World

PACK = suitefence.PACK


class WorldOnPath:
    """A PATH holding only `sh`, `python3`, git and the stand-in `gh`, and the world it reads."""

    def stand_in(self, folder: Path | None = None) -> Path:
        made = tempfile.TemporaryDirectory(prefix="keel-github-world-")
        self.addCleanup(made.cleanup)
        self.world_file = Path(made.name) / "world.json"
        if folder is None:
            folder = Path(made.name) / "bin"
            folder.mkdir()
            for name, found in (("sh", shutil.which("sh")), ("python3", sys.executable), ("git", shutil.which("git"))):
                os.symlink(found, folder / name)
            patcher = mock.patch.dict(os.environ, {"PATH": str(folder), "GH_WORLD": str(self.world_file)})
            patcher.start()
            self.addCleanup(patcher.stop)
        ghworld.install(folder)
        return folder

    def host_serve(self, world: World) -> None:
        world.save(self.world_file)

    def host_seen(self, world: World) -> World:
        return World.load(self.world_file)


class GitHubHost(WorldOnPath, HostContract, unittest.TestCase):
    def setUp(self):
        self.stand_in()

    def host_layer(self):
        return gh_layer

    def host_repo(self, name: str):
        return Repo(name, gh_layer.BASE, None)

    def host_secret(self, marker: str) -> None:
        patcher = mock.patch.dict(os.environ, {"GH_TOKEN": marker, "GITHUB_TOKEN": marker})
        patcher.start()
        self.addCleanup(patcher.stop)


class GitHubGuard(GuardContract, unittest.TestCase):
    def guard_pack(self) -> Path:
        return PACK

    def guard_policy(self):
        return gh_fence.POLICY


class GitHubLife(WorldOnPath):
    """The hooks both lives run on: the pack, its address, the stand-in `gh` on PATH."""

    def verbs_pack(self) -> Path:
        return PACK

    def host_remote(self, name: str) -> str:
        return f"https://github.com/{name}.git"

    def host_bin(self, folder: Path) -> None:
        self.stand_in(folder)

    def host_env(self) -> dict:
        return {"GH_WORLD": str(self.world_file)}


class GitHubVerbs(GitHubLife, VerbsContract, unittest.TestCase):
    """A card's whole life."""


class GitHubReviews(GitHubLife, ReviewsContract, unittest.TestCase):
    """A review card's whole life (the pack claims `reviews`)."""


if __name__ == "__main__":
    unittest.main()
