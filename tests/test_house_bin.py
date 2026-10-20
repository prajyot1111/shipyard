"""`etc/house-bin/open`: the command that makes "a house never opens a browser" a mechanism.

A plan is read from the deck, on a phone as often as at the desk, so a house that opens a
Chrome tab is a house piling up tabs on a machine nobody may be sitting at. Two things stop
it, and this file tests the one that survives a lavish upgrade:

- `LAVISH_AXI_NO_OPEN=1` in the house's environment. Probed 2026-09-17 and recorded in
  `tests/fixtures/harness/README.md`: lavish honours it (and `--no-open`), neither being in
  its `--help`.
- This shim, first on a house's PATH. lavish reaches the browser through the npm `open`
  package, which on macOS spawns the BARE name `open`, so PATH decides which one runs. The
  shim opens nothing, leaves the URL on the card, and exits 0 so the caller carries on.

Only a house gets this directory on its PATH (`config.house_path`), so the human's own
`open` is the real one. `kb` is faked here: the test proves the shim CALLS the note, not
what the board does with it.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIM = ROOT / "etc" / "house-bin" / "open"
URL = "http://127.0.0.1:4387/session/ad9f1a5132e669b3"

FAKE_KB = """#!/bin/sh
printf '%s\\n' "$*" >> "$KB_LOG"
"""


class OpenShimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.kb_log = self.dir / "kb.log"
        kb = self.bin / "kb"
        kb.write_text(FAKE_KB)
        kb.chmod(kb.stat().st_mode | stat.S_IEXEC)
        (self.dir / "state" / "cards" / "c-1").mkdir(parents=True)

    def run_shim(self, *args, card="c-1", path=None) -> subprocess.CompletedProcess:
        env = dict(os.environ, KEEL_HOME=str(self.dir), KB_LOG=str(self.kb_log),
                   PATH=f"{self.bin}:/usr/bin:/bin" if path is None else path)
        if card:
            env["KEEL_CARD"] = card
        else:
            env.pop("KEEL_CARD", None)
        return subprocess.run([str(SHIM), *args], capture_output=True, text=True, env=env)

    def opens_log(self) -> str:
        path = self.dir / "state" / "cards" / "c-1" / "opens.log"
        return path.read_text() if path.exists() else ""


    def test_a_url_is_recorded_on_the_card_and_nothing_is_opened(self):
        result = self.run_shim(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", "the shim prints nothing at a house's terminal")
        self.assertIn(URL, self.opens_log())
        self.assertEqual(self.kb_log.read_text().strip(), f'note c-1 surface: {URL}')

    def test_every_open_is_appended_rather_than_replacing_the_last(self):
        self.run_shim(URL)
        self.run_shim(URL + "2")
        self.assertEqual(len(self.opens_log().strip().splitlines()), 2)


    def test_an_application_argument_is_not_a_target(self):
        """`open -a "Google Chrome" <url>` names an application, which is not a URL to put
        on the card. Everything after `--args` belongs to the application."""
        self.run_shim("-a", "Google Chrome", URL, "--args", "--incognito")
        self.assertEqual(self.opens_log().strip().splitlines()[0].split("\t")[1], URL)
        self.assertEqual(len(self.opens_log().strip().splitlines()), 1)

    def test_without_kb_it_still_records_the_url_and_exits_0(self):
        result = self.run_shim(URL, path="/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(URL, self.opens_log())
        self.assertFalse(self.kb_log.exists())

    def test_outside_a_house_it_does_nothing_at_all(self):
        """No `KEEL_CARD` means this is not a house, and the shim has nowhere to write. It
        still exits 0 rather than failing whatever called it."""
        result = self.run_shim(URL, card=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.opens_log(), "")


if __name__ == "__main__":
    unittest.main()
