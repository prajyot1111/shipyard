"""The Settings view (c-633, `app/ui.settings.js`): every field of the schema is drawn with its
help as the label's tooltip and an info button for the phone, an edit marks its field, Save
posts ONE `setup.settings.save` with every change, the form S4 embeds draws only the groups
it is given, and Now and More reach it. One node run over the module itself, fed a real
`settings.report`, as the other deck tests do: a stdlib suite cannot run the page."""

import dataclasses
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import settings, terms
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
FIXTURE = ROOT / "tests" / "fixtures" / "settings-deck.js"
LEAVE = ROOT / "tests" / "fixtures" / "settings-leave.js"


class SettingsViewTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_every_field_is_drawn_with_its_help_and_save_posts_one_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            report = settings.report(cfg)
            report["install"] = tmp                   # drawn as an install's: editable, with Save
            data = Path(tmp) / "report.json"
            data.write_text(json.dumps(report))
            done = subprocess.run(["node", str(FIXTURE), str(APP), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        said = lambda s: terms.say(None, s.help)        # noqa: E731 - neither space has a pack's words
        wanted = [(s.label, said(s)) for s in settings.SETTINGS if s.scope == "install"]
        wanted += [(s.label, said(s)) for _ in cfg.spaces for s in settings.SETTINGS if s.scope == "space"]
        drawn = [(row["label"], row["title"]) for row in out["labels"]]
        self.assertEqual(sorted(drawn), sorted(wanted), "a field without its help, or one drawn twice")
        self.assertEqual(out["infos"], len(wanted))                  # the help, shown under each field
        self.assertEqual(out["changed"], 2)
        self.assertEqual(out["saveText"], "Save 2 changes to this install")
        named = {s.key: s.label for s in settings.of("keel")}
        self.assertEqual(out["what"], f"{named['drain_paused']}, {named['houses_max']}"
                         " · a save takes effect at once (a voice change restarts the deck)")
        self.assertEqual(out["acted"], [{"verb": "setup.settings.save", "changes": [
            {"table": "keel", "key": "drain_paused", "value": True},
            {"table": "keel", "key": "houses_max", "value": 5}]}])
        self.assertEqual(out["form"], len([s for s in settings.of("keel") if s.group == "Drain"]))
        self.assertTrue(out["formSave"], "the embedded form has its own Save over its own fields")
        self.assertEqual(out["nowWarnings"], 1)
        self.assertTrue(out["moreHasSettings"])

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_a_spaces_flow_is_drawn_as_a_board_and_propose_posts_his_words(self):
        """c-640: the Flow panel draws the board's lines (a node per branch, an edge per move,
        his target marked), lists each move, and Propose sends his words for that space."""
        from keel import flows
        from tests.test_flows import MINE
        public = flows.public(flows.parse_text(MINE, "f.toml", "space", None))
        # a space with no code host that has one of the two shipping settings turned on
        out = self.flow_panel(dict(public, proposal=None,
                                   handling={"shipping": False, "comments": True, "checks": False}))
        nodes = [line for line in out["lines"] if line.startswith("node ")]
        edges = [line for line in out["lines"] if line.startswith("edge ")]
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(edges), 1)
        self.assertIn("card -> dev", edges[0])
        self.assertIn("mark dev accent", out["lines"])
        self.assertEqual((out["moves"], out["graph"], out["nav"]), (["flow-move-to-dev"], 1, True))
        self.assertEqual(out["proposed"], [{"verb": "setup.flow.propose", "space": "personal",
                                            "words": "dev review on my word"}])
        # c-664: the panel says what a flow is, and that a shipping setting does nothing here
        self.assertIn("Only the moves you make are buttons", out["honest"])
        self.assertEqual(out["who"], ["you · a button"])
        self.assertIn("Handle review comments automatically is turned on here and does nothing", out["handling"])
        # and, before the tap, what Propose starts, that nothing changes until Adopt, and
        # that it is a conversation; the example is not anyone's own flow
        for said in ("a house", "Nothing changes until you Adopt", "Drop in", "Send back"):
            self.assertIn(said, out["before"])
        self.assertNotIn("staging", out["example"])

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_keels_own_flow_is_said_to_be_a_picture_and_an_open_proposal_says_where_it_went(self):
        """c-664: a flow with no move of yours adds no button and says so, `{base}` is drawn in
        words, the space's two shipping settings are said with their state, and an open
        proposal is its card as a link, its state in words, and Adopt once the draft is ready."""
        from keel import flows
        public = flows.public(flows.load(flows.GENERAL))
        out = self.flow_panel(dict(public, proposal={"card": "c-7", "stage": "review", "waiting": False},
                                   handling={"shipping": True, "comments": False, "checks": True}))
        self.assertIn("adds no button to a card: Approve and Ship are the card's own buttons", out["honest"])
        # c-758 r1.F6: the same words as the first run's drawing for whose button Ship is and who merges
        self.assertEqual(out["who"], ["the house · drawn only", "you · the card's own button",
                                      "you · the card's own button", "you or a teammate · drawn only"])
        self.assertTrue(any('"Ship · you"' in line for line in out["lines"]), out["lines"])
        self.assertTrue(any("the card's base" in line for line in out["lines"]))
        self.assertFalse(any("{base}" in line for line in out["lines"]))
        self.assertIn("comments are kept on the card", out["handling"])
        self.assertIn("failing checks are handed to its house", out["handling"])
        self.assertEqual(out["link"], "/?card=c-7")
        self.assertIn("draft ready", out["after"])
        self.assertIn("Send back", out["after"])
        self.assertIsNone(out["before"], "the box gives way to the open proposal")
        self.assertEqual(out["proposed"], [{"verb": "setup.flow.adopt", "card": "c-7"}])
        # c-667: Adopt says the adoption's own answer, an error when the card was not moved
        self.assertEqual(out["adoptSaid"], [{"text": "adopted, but not moved", "err": True, "id": "c-7"}])

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_a_space_where_nothing_can_land_says_so_with_the_way_to_set_it_up(self):
        """c-664 review: a held space. The panel prints the state's own sentence for its case
        as it is, in a line of its own with the first run's Where finished work goes step."""
        from keel import flows
        held = dataclasses.replace(flows.load(flows.LOCAL), moves=(), description=flows.HELD)
        said = "A card can be approved and published in this space, but Shipyard cannot watch it at shipping: the x adapter has no ship verb."
        out = self.flow_panel(dict(flows.public(held), proposal=None, held=said,
                                   handling={"shipping": False, "comments": False, "checks": False}))
        self.assertEqual(out["held"], said + " Set it up", "the sentence as the state gives it, and the link")
        self.assertNotIn("cannot be approved", out["held"], "no wrapper that is untrue of this case")
        self.assertNotIn("adapter", out["about"], "said once")
        # the shipping note claims nothing of its own: a card here does reach shipping
        self.assertIn("says nothing of shipping", out["handling"])
        self.assertNotIn("reaches shipping", out["handling"])
        self.assertNotIn("no code host", out["handling"])
        self.assertEqual(out["setup"], "?view=start&step=integrations&space=personal")
        self.assertEqual(out["moves"], [])
        # a held space whose flow is its own file says the same line, with the same link
        from tests.test_flows import MINE
        own = self.flow_panel(dict(flows.public(flows.parse_text(MINE, "f.toml", "space", None)), proposal=None,
                                   held=said,
                                   handling={"shipping": False, "comments": False, "checks": False}))
        self.assertIn(said, own["held"])
        self.assertEqual(own["setup"], "?view=start&step=integrations&space=personal")
        plain = self.flow_panel(dict(flows.public(flows.load(flows.LOCAL)), proposal=None, held=None,
                                     handling={"shipping": False, "comments": False, "checks": False}))
        self.assertEqual((plain["setup"], plain["held"]), (None, None))
        self.assertIn("(it has no code host)", plain["handling"], "true of a space with no pack")

    def flow_panel(self, flow: dict) -> dict:
        """The personal space's Flow panel drawn from `flow`, as the node fixture reads it."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            report = settings.report(cfg)
            report["install"] = tmp
            data, drawn = Path(tmp) / "report.json", Path(tmp) / "flow.json"
            data.write_text(json.dumps(report))
            drawn.write_text(json.dumps(flow))
            done = subprocess.run(["node", str(FIXTURE), str(APP), str(data), str(drawn)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["flow"]

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_a_space_setting_names_its_space_and_an_unsaved_change_is_not_left_silently(self):
        """c-661 (2026-10-06): he saved two switches onto the wrong space, after once leaving
        them unsaved. The page opens at the deck's space, every space row carries its space,
        an unsaved row is marked, Save says where it writes, and leaving asks first."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            report = settings.report(cfg)
            report["install"] = tmp
            data = Path(tmp) / "report.json"
            data.write_text(json.dumps(report))
            done = subprocess.run(["node", str(FIXTURE), str(APP), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)["spaces"]
        names = list(cfg.spaces)
        self.assertEqual(out["here"], names[-1], "the fixture's deck is in the config's last space")
        self.assertEqual(out["order"][0], "set-space-" + names[-1], "the deck's space is the first section")
        self.assertEqual(sorted(out["order"]), sorted(["set-install", "set-voice"] + ["set-space-" + n for n in names]))
        self.assertEqual((out["unnamed"], out["installNamed"]), (0, 0), "a space row without its space")
        self.assertEqual((out["leaveClean"], out["askedClean"]), (True, 0), "nothing pending: nothing asked")
        self.assertEqual(out["unsaved"], out["turned"], "each changed row is marked, and only those")
        self.assertEqual(out["saveText"], f"Save 2 changes to {names[0]} and {names[1]}",
                         "Save says which spaces it writes")
        label = next(s.label for s in settings.SETTINGS if f"set-{names[0]}|{s.id}" in out["turned"])
        self.assertEqual(out["what"], f"{label} ({names[0]}), {label} ({names[1]})"
                         " · a save takes effect at once (a voice change restarts the deck)")
        self.assertTrue(out["barLastInColumn"], "the Save bar is the last child of the column it sticks within")
        self.assertEqual((out["leavePending"], out["askedPending"], out["unloadAsks"]), (False, 1, True))
        self.assertEqual((out["unsavedAfter"], out["leaveAfter"]), (0, True), "turned back is not a change")

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_typing_marks_at_once_and_a_yes_or_a_value_typed_back_leaves_nothing_pending(self):
        """c-661 review (F2, F3, F5): a number typed with no blur marks its row and shows the
        bar at the first keystroke, redrawing only as the key joins or leaves the pending
        set; typed back to what is stored it is no change; a yes to the leave question drops
        every change; and the stepper's asked choice keeps the default as an answer."""
        out = self.run_fixture(FIXTURE)
        clean, marked = {"unsaved": 0, "bar": 0, "unload": False}, {"unsaved": 1, "bar": 1, "unload": True}
        typing = out["typing"]
        self.assertEqual(typing["afterFirstKey"], [1, marked], "the first keystroke marks the row and draws the bar")
        self.assertEqual(typing["afterSecondKey"], 1, "a keystroke that changes no membership does not redraw")
        self.assertEqual(typing["typedBack"], [2, clean], "typed back to the stored value: not a change")
        self.assertEqual((typing["leaveYes"], typing["askedYes"], typing["afterYes"]), (True, 1, clean))
        stepper = out["stepper"]
        self.assertEqual((stepper["untouched"]["chooseOne"], stepper["untouched"]["save"]), (True, "Nothing to save"))
        self.assertEqual((stepper["other"]["chooseOne"], stepper["other"]["save"]), (False, "Save 1 change to this install"))
        self.assertEqual(stepper["backToDefault"], {"chooseOne": False, "selected": [stepper["default"]],
                                                    "save": "Save 1 change to this install"})

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_decks_routing_asks_before_it_leaves_settings(self):
        """c-661 review: `go`, Back and Forward through app/ui.core.js and app/ui.leave.js with
        the real `K.beforeLeave`. A refused move changes nothing (the view, the URL, the
        entries), over two steps and with a render pass or a late popstate in between; an
        accepted one drops the changes; and a landing on an entry with no stamp does exactly
        what the Atlas admits."""
        self.assertEqual(self.run_fixture(LEAVE), {"ok": True})

    def run_fixture(self, fixture):
        with tempfile.TemporaryDirectory() as tmp:
            report = settings.report(make_config(Path(tmp)))
            report["install"] = tmp
            data = Path(tmp) / "report.json"
            data.write_text(json.dumps(report))
            done = subprocess.run(["node", str(fixture), str(APP), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_route_is_registered_everywhere_the_deck_looks(self):
        """The manifest's row, and what the server draws from it (app/views.json, c-634)."""
        from keel import deckviews, serve
        row = next(v for v in deckviews.load(APP)["views"] if v["key"] == "settings")
        self.assertEqual((row["name"], row["render"], row["script"]), ("Settings", "viewSettings", "ui.settings.js"))
        self.assertEqual(serve.APP_FILES.get("/ui.settings.js"), "ui.settings.js")
        self.assertIn('"/ui.settings.js"', deckviews.rendered(APP, "sw.js"))
        self.assertIn('<script src="/ui.settings.js">', deckviews.rendered(APP, "index.html"))
        self.assertIn("K.configWarnings ? K.configWarnings() : null", (APP / "ui.views.js").read_text())


if __name__ == "__main__":
    unittest.main()
