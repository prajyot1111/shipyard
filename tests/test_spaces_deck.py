"""The deck's spaces are the config's (c-629): the switch lists what `/api/state` carries, a
stored or asked space the config does not have becomes its first, and a lone space shows no
switch. One node run over the functions themselves, as the other deck tests do: a stdlib
suite cannot run the page."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_deck_css import js_function

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
FUNCTIONS = ("palette", "spaceNames", "settleSpace", "spaceLabel", "nextSpace")

PROBE = """
var App = { space: '', data: null }, stored = [], chrome = 0;
function store(key, value) { stored.push([key, value]); }
function applyChrome() { chrome += 1; }
%s
function settle(names, space) {
  App.space = space;
  App.data = names === null ? null : { spaces: names.reduce(function (o, n) { o[n] = {}; return o; }, {}) };
  settleSpace();
  return App.space;
}
var out = {
  fresh: settle(['personal'], 'work'),
  kept: settle(['work', 'personal'], 'personal'),
  none: settle(['personal', 'research'], ''),
  before: settle(null, 'work'),
  lone: (settle(['personal'], 'personal'), spaceNames().length),
  cycle: (function () { settle(['work', 'personal', 'research'], 'personal');
                        var seen = []; for (var i = 0; i < 3; i++) { App.space = nextSpace(); seen.push(App.space); }
                        return seen; })(),
  label: spaceLabel('research'),
  palettes: ['work', 'personal', 'research'].map(palette),
  stored: stored
};
process.stdout.write(JSON.stringify(out));
"""


def whole(name: str) -> str:
    """`function <name>(<params>) {<body>}` from ui.core.js, its signature as written."""
    text = (APP / "ui.core.js").read_text(encoding="utf-8")
    params = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(([^)]*)\)", text).group(1)
    return f"function {name}({params}) {{{js_function('ui.core.js', name)}}}"


class SpacesFromConfigTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_switch_follows_the_config(self):
        body = "\n".join(whole(name) for name in FUNCTIONS)
        result = subprocess.run(["node", "-e", PROBE % body], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["fresh"], "personal")          # a fresh install never lands on work
        self.assertEqual(out["kept"], "personal")           # a space the config has is kept
        self.assertEqual(out["none"], "personal")           # nothing stored: the config's first
        self.assertEqual(out["before"], "work")             # before any state, nothing is decided
        self.assertEqual(out["lone"], 1)
        self.assertEqual(out["cycle"], ["research", "work", "personal"])
        self.assertEqual(out["label"], "Research")
        self.assertEqual(out["palettes"], ["work", "personal", "personal"])
        self.assertEqual(out["stored"], [["space", "personal"], ["space", "personal"]])

    def test_no_space_name_is_hard_wired_in_the_switch(self):
        text = (APP / "ui.core.js").read_text(encoding="utf-8")
        self.assertNotIn("['work', 'personal']", text)
        self.assertNotIn("App.space === 'work' ? 'Work' : 'Personal'", text)
        self.assertIn("spaceNames().length < 2 ? null", text)


if __name__ == "__main__":
    unittest.main()
