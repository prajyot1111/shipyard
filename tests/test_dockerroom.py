"""c-532: `keel doctor` says when Docker Desktop leaves macOS 6 GB or less.

The settings file is written under a temporary home and the machine's memory is handed in,
so nothing here reads this machine's Docker or its `sysctl`.
"""

import json
import tempfile
import unittest
from pathlib import Path

from keel import dockerroom, doctor

GIB = 1024


class Cfg:
    def __init__(self, spaces=("work",)):
        self.spaces = list(spaces)

    def served_spaces(self):
        return self.spaces


class DockerRoomTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)

    def settings(self, name: str, body: dict) -> None:
        path = self.home / "Library/Group Containers/group.com.docker" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))

    def gather(self, machine=16 * GIB, spaces=("work",), platform="darwin"):
        return dockerroom.gather(Cfg(spaces), home=self.home, platform=platform,
                                 memsize=lambda: machine)

    def test_eight_of_sixteen_leaves_room(self):
        self.settings("settings-store.json", {"MemoryMiB": 8 * GIB})
        found = self.gather()
        self.assertEqual(found["left_mib"], 8 * GIB)
        self.assertIsNone(dockerroom.problem(found))
        self.assertIn("macOS keeps 8.0 GB", dockerroom.line(found))

    def test_ten_of_sixteen_is_the_incident_and_a_problem(self):
        self.settings("settings-store.json", {"MemoryMiB": 10 * GIB})
        found = self.gather()
        said = dockerroom.problem(found)
        self.assertIn("10.0 GB of 16.0 GB", said)
        self.assertIn("leaving macOS 6.0 GB", said)
        self.assertIsNone(dockerroom.problem(self.gather(machine=17 * GIB)), "7 GB left is enough")
        self.assertIn("LOW", dockerroom.line(found))
        self.assertIn(said, doctor.problems(minimal_report(found)))

    def test_the_older_settings_file_is_read_too(self):
        self.settings("settings.json", {"memoryMiB": 12 * GIB})
        self.assertEqual(self.gather()["docker_mib"], 12 * GIB)

    def test_not_a_mac_or_no_houses_is_not_applicable(self):
        self.settings("settings-store.json", {"MemoryMiB": 15 * GIB})
        for found in (self.gather(platform="linux"), self.gather(spaces=())):
            self.assertFalse(found["applicable"])
            self.assertIsNone(dockerroom.problem(found))
            self.assertIn("not applicable", dockerroom.line(found))

    def test_no_settings_file_is_unknown_not_a_problem(self):
        found = self.gather()
        self.assertIsNone(dockerroom.problem(found))
        self.assertIn("unknown", dockerroom.line(found))


def minimal_report(docker: dict) -> dict:
    """The least of a report `doctor.problems` reads past its early return."""
    return {"config": {"ok": True, "path": "keel.toml"}, "claude": {"ok": True},
            "keel": {"state_dir": {"ok": True, "path": "state"}}, "spaces": {},
            "board": {"ok": True}, "voice": {"ok": True, "parked": True, "port": 0},
            "idle": {}, "docker": docker}


if __name__ == "__main__":
    unittest.main()
