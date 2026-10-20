"""The Gitea pack held to the kit's conformance suite (`keel/packkit/conformance.py`): its
real layer against a world its stand-in serves as Gitea's API on 127.0.0.1
(`giteaworld.py`), with git's own credential helper handing over the sign-in, its guard,
and its executables over a card's and a review card's whole life.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import suitefence

import giteaworld
import gt_fence
import gt_layer
from keel.packkit.conformance import GuardContract, HostContract, ReviewsContract, VerbsContract
from keel.packkit.layer import Repo
from keel.packkit.world import World

PACK = suitefence.PACK


def git_env(pairs: list[tuple[str, str]]) -> dict:
    env = {"GIT_CONFIG_COUNT": str(len(pairs))}
    for index, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"] = key, value
    return env


class WorldServed:
    """The stand-in Gitea, for one test, and the world it serves."""

    def stand_in(self) -> giteaworld.Served:
        made = tempfile.TemporaryDirectory(prefix="keel-gitea-world-")
        self.addCleanup(made.cleanup)
        self.served = giteaworld.Served(made.name)
        self.addCleanup(self.served.stop)
        gt_layer.API.forget()
        self.addCleanup(gt_layer.API.forget)
        return self.served

    def host_serve(self, world: World) -> None:
        world.save(self.served.world_file)

    def host_seen(self, world: World) -> World:
        return World.load(self.served.world_file)


class GiteaHost(WorldServed, HostContract, unittest.TestCase):
    def setUp(self):
        served = self.stand_in()
        patcher = mock.patch.dict(os.environ, git_env(served.git_config()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def host_layer(self):
        return gt_layer

    def host_repo(self, name: str):
        return Repo(name, self.served.base, None)

    def host_secret(self, marker: str) -> None:
        self.served.secret(marker)


class GiteaGuard(GuardContract, unittest.TestCase):
    def guard_pack(self) -> Path:
        return PACK

    def guard_policy(self):
        return gt_fence.POLICY


class GiteaLife(WorldServed):
    """The hooks both lives run on: the pack, its address, git's sign-in for the stand-in."""

    def setUp(self):
        self.stand_in()

    def verbs_pack(self) -> Path:
        return PACK

    def host_remote(self, name: str) -> str:
        return f"{self.served.base}/{name}.git"

    def host_git_config(self) -> list[tuple[str, str]]:
        return self.served.git_config()


class GiteaVerbs(GiteaLife, VerbsContract, unittest.TestCase):
    """A card's whole life."""


class GiteaReviews(GiteaLife, ReviewsContract, unittest.TestCase):
    """A review card's whole life (the pack claims `reviews`)."""


if __name__ == "__main__":
    unittest.main()
