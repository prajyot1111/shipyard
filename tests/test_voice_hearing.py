"""The gateway's mishearings from every pack root (voice/harbor_voice/hearing.py, c-725 r1.F12):
an install's own pack is in the install, not the checkout, and the gateway finds its
`hearing.json` through the `KEEL_CONFIG` its service file carries. Read in a child, because
`harbor_voice.config` reads its environment once, at import."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READ = ("import json, sys; sys.path.insert(0, sys.argv[1]); from harbor_voice import hearing; "
        "print(json.dumps(sorted(hearing.ALL_WORDS)))")


def table(path: Path, word: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"words": {word: {"said": word.title(), "heard": "a test"}}}))


class PackRootsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.checkout = self.dir / "checkout"
        table(self.checkout / "packs" / "shipped" / "hearing.json", "zorblax")
        (self.checkout / "adapters").mkdir()
        self.install = self.dir / "install"
        table(self.install / "packs" / "work" / "hearing.json", "quuxly")
        (self.install / "config.toml").write_text("[keel]\n")

    def words(self, **extra) -> list[str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith("KEEL_")}
        env.update(KEEL_HOME=str(self.checkout), KEEL_ADAPTERS_DIR=str(self.checkout / "adapters"), **extra)
        done = subprocess.run([sys.executable, "-c", READ, str(ROOT / "voice")], capture_output=True,
                              text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_with_keel_config_the_installs_pack_is_heard_too(self):
        words = self.words(KEEL_CONFIG=str(self.install / "config.toml"))
        self.assertIn("quuxly", words)
        self.assertIn("zorblax", words)

    def test_without_it_only_the_checkouts_packs_are(self):
        words = self.words()
        self.assertIn("zorblax", words)
        self.assertNotIn("quuxly", words)


if __name__ == "__main__":
    unittest.main()
