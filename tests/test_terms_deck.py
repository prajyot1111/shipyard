"""The deck says each card's space's words (c-630): `K.term` and `K.say` read the terms the
space entry carries, and the converted sites read differently per space. One node run over
the functions themselves, as the other deck tests do: personal reads ticket and PR, work
story and PR, the sandbox issue and MR."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from keel import packs, terms
from tests.test_deck_css import js_function

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
# A work space's words as a story-and-pull-request pack says them (c-722: written here, so the
# suite needs no pack of anyone's own).
STORY = {"ticket": "story", "tickets": "stories", "ticket_ref": "tk-<n>", "change": "pull request",
         "changes": "pull requests", "change_short": "PR", "changes_short": "PRs"}
SPACES = {"personal": terms.public(terms.BASE),
          "work": terms.public(terms.Terms(STORY)),
          "sandbox": terms.public(terms.Terms(packs.load(ROOT / "packs" / "sandbox").terms))}

PROBE = """
var App = { space: 'work', data: { spaces: %s } }, cardTerms = {};
var K = {};
%s
K.term = term; K.say = sayTerms;
function shippingOf(c) { return (c.options && c.options.shipping) || null; }
var TIPS = { %s };
var out = {};
['personal', 'work', 'sandbox'].forEach(function (space) {
  var one = { space: space, options: { shipping: { facts: { prs: [] } } } };
  var two = { space: space, options: { shipping: { facts: { prs: [{ state: 'open' }, { state: 'open' }] } } } };
  out[space] = {
    open: K.say(space, 'Open {ticket}'),
    openChange: K.say(space, 'Open {change_short}'),
    ship: shipWord(one).text.split(' \\u00b7 ')[0],
    ships: shipWord(two).text.split(' \\u00b7 ')[0],
    tip: K.say(space, TIPS.story),
    capital: K.term(space, 'Ticket')
  };
});
out.unknown = K.say('nowhere', 'Open {ticket}');
cardTerms.planonly = { ticket: 'card' };
App.data = null;
out.plan = K.say('planonly', 'Open {ticket}');
process.stdout.write(JSON.stringify(out));
"""


def whole(module: str, name: str) -> str:
    text = (APP / module).read_text(encoding="utf-8")
    params = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(([^)]*)\)", text).group(1)
    return f"function {name}({params}) {{{js_function(module, name)}}}"


def tip_line(key: str) -> str:
    """One static line of `TIPS` in app/ui.tips.js, as written."""
    text = (APP / "ui.tips.js").read_text(encoding="utf-8")
    return re.search(r"^\s*'" + re.escape(key) + r"': ('(?:[^'\\]|\\.)*'),$", text, re.M).group(1)


class DeckTermsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_each_space_reads_its_own_words(self):
        body = "\n".join([whole("ui.core.js", "termsOf"), whole("ui.core.js", "term"),
                          whole("ui.core.js", "sayTerms"), whole("ui.cards.js", "count"),
                          whole("ui.cards.js", "shipWord")])
        probe = PROBE % (json.dumps({name: {"terms": t} for name, t in SPACES.items()}), body, "story: " + tip_line("story"))
        result = subprocess.run(["node", "-e", probe], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["personal"], {"open": "Open ticket", "openChange": "Open PR", "ship": "PR ready",
                                           "ships": "2 PRs ready", "capital": "Ticket",
                                           "tip": "Open ticket: the card's ticket in the tracker. Nothing changes here."})
        self.assertEqual(out["work"]["open"], "Open story")
        self.assertEqual(out["work"]["ship"], "PR ready")
        self.assertEqual(out["work"]["capital"], "Story")
        self.assertEqual(out["sandbox"]["open"], "Open issue")
        self.assertEqual(out["sandbox"]["ship"], "MR ready")
        self.assertEqual(out["sandbox"]["ships"], "2 MRs ready")
        self.assertEqual(out["sandbox"]["tip"], "Open issue: the card's issue in the tracker. Nothing changes here.")
        # no copy of the defaults in the deck: a space with no terms shows the key itself
        self.assertEqual(out["unknown"], "Open ticket")
        # the plan page has no state; its card's terms answer
        self.assertEqual(out["plan"], "Open card")

    def test_the_deck_reads_terms_from_the_state_and_the_plan_payload(self):
        core = (APP / "ui.core.js").read_text(encoding="utf-8")
        self.assertIn("K.term = term; K.say = sayTerms; K.cardTerms = cardTerms;", core)
        self.assertIn("K.cardTerms[d.card.space] = d.card.terms", (APP / "ui.plan.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
