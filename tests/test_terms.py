"""What a space calls a ticket and a change (keel/terms.py, c-630): the core's neutral words,
a pack's `[terms]` laid over them, `packs.load` refusing a bad table, and the plan page's
ticket and change refs built from the card's space."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from keel import packs, planformat, planinline, terms
from keel.board import Board, Refused

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "packs"
MANIFEST = 'name = "demo"\nversion = "1"\ndescription = "a pack for the test"\n'
# A pack that says story and pull request, as a work integration may (c-722: the suite needs
# no pack of anyone's own, so it writes this one).
STORY_TERMS = ('[terms]\nticket = "story"\ntickets = "stories"\nticket_ref = "tk-<n>"\n'
               'change = "pull request"\nchanges = "pull requests"\nchange_short = "PR"\n'
               'changes_short = "PRs"\ntracker_name = "Trackr"\n')
_STORY = tempfile.TemporaryDirectory()
STORY = Path(_STORY.name) / "work"
STORY.mkdir()
(STORY / packs.PACK_FILE).write_text(MANIFEST.replace('"demo"', '"work"') + STORY_TERMS)


def space(name: str, adapter_dir: Path | None) -> SimpleNamespace:
    return SimpleNamespace(name=name, adapter=adapter_dir.name if adapter_dir else None,
                           adapter_dir=adapter_dir)


def config(**dirs) -> SimpleNamespace:
    return SimpleNamespace(spaces={name: space(name, path) for name, path in dirs.items()})


class TermsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        legacy = self.tmp / "legacy"
        legacy.mkdir()
        self.cfg = config(personal=None, work=STORY, sandbox=PACKS / "sandbox", legacy=legacy)

    def test_a_space_with_no_pack_reads_the_neutral_defaults(self):
        t = terms.of(self.cfg, "personal")
        self.assertEqual((t["ticket"], t["change"], t["change_short"]), ("ticket", "pull request", "PR"))
        self.assertIsNone(t["ticket_ref"])
        self.assertEqual(terms.of(self.cfg, "no such space"), terms.BASE)

    def test_the_work_pack_says_its_own_words(self):
        t = terms.of(self.cfg, "work")
        self.assertEqual((t["ticket"], t["tickets"], t["ticket_ref"]), ("story", "stories", "tk-<n>"))
        self.assertEqual((t["change"], t["change_short"], t["changes_short"]), ("pull request", "PR", "PRs"))
        # the vendor names are the pack's to say, never this file's
        self.assertEqual(t["tracker_name"], packs.load(STORY).terms["tracker_name"])

    def test_the_sandbox_says_words_that_differ_from_both(self):
        t, work = terms.of(self.cfg, "sandbox"), terms.of(self.cfg, "work")
        for key in ("ticket", "tickets", "ticket_ref", "change", "changes", "change_short", "changes_short"):
            self.assertNotEqual(t[key], terms.BASE[key], key)
            self.assertNotEqual(t[key], work[key], key)
        self.assertEqual((t["ticket"], t["change_short"], t["ticket_ref"]), ("issue", "MR", "st-<n>"))

    def test_an_older_adapter_with_no_pack_toml_reads_the_defaults(self):
        self.assertEqual(terms.public(terms.of(self.cfg, "legacy")), terms.public(terms.BASE))

    def test_a_pack_that_does_not_load_reads_the_defaults(self):
        broken = self.tmp / "broken"
        broken.mkdir()
        (broken / packs.PACK_FILE).write_text("name = 'broken'\n")
        self.assertEqual(terms.of(config(x=broken), "x"), terms.BASE)

    def test_say_fills_and_capitalises_and_leaves_other_fields(self):
        t = terms.of(self.cfg, "work")
        self.assertEqual(terms.say(t, "{Ticket} {ticket}: the {change} of {repo}"),
                         "Story story: the pull request of {repo}")
        self.assertEqual(terms.say(None, "Open {change_short}"), "Open PR")
        self.assertEqual(t["Change_short"], "PR")

    def test_public_carries_every_key_the_deck_reads(self):
        self.assertEqual(set(terms.public(terms.of(self.cfg, "work"))), set(packs.TERM_KEYS))
        self.assertEqual(set(terms.table(self.cfg)), {"personal", "work", "sandbox", "legacy"})

    def test_ref_pattern_is_the_prefix_and_a_number(self):
        self.assertEqual(terms.ref_pattern({"ticket_ref": "tk-<n>"}), r"tk\-\d+")
        self.assertIsNone(terms.ref_pattern(terms.BASE))
        refs = terms.refs(terms.of(self.cfg, "work"))
        found = [m.lastgroup for m in refs.finditer("see tk-12345, xtk-1 and PR #7")]
        self.assertEqual(found, ["ticket", "change"])

    def test_options_json_normalises_a_ticket_to_the_packs_own_ref(self):
        """A pack whose New card form has a ticket field shapes it as its `ticket_ref` says,
        so the form and the plan page link the same thing."""
        for pack in packs.available(ROOT):
            path = pack.path / "options.json"
            fields = json.loads(path.read_text()) if path.is_file() else []
            for field in fields:
                if field.get("type") == "story" and field.get("normalise"):
                    self.assertEqual(field["normalise"], pack.terms.get("ticket_ref"), pack.name)


class TermsTableLoadTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "demo"
        self.path.mkdir()

    def refused(self, table: str, pattern: str) -> None:
        (self.path / packs.PACK_FILE).write_text(MANIFEST + "[terms]\n" + table)
        with self.assertRaisesRegex(packs.PackError, pattern):
            packs.load(self.path)

    def test_a_known_table_loads(self):
        (self.path / packs.PACK_FILE).write_text(MANIFEST + '[terms]\nticket = "issue"\nticket_ref = "gl_x-<n>"\n')
        self.assertEqual(packs.load(self.path).terms, {"ticket": "issue", "ticket_ref": "gl_x-<n>"})

    def test_an_unknown_key_is_refused(self):
        self.refused('bug = "defect"\n', r"\[terms\] has no key bug")

    def test_a_value_that_is_not_a_string_is_refused(self):
        self.refused("ticket = 3\n", r"\[terms\] ticket must be a non-empty string")

    def test_a_bad_ticket_ref_is_refused(self):
        for bad in ("sc-\\\\d+", "<n>", "tk-<n>-<n>", "s c-<n>", "tk-<n>x"):
            with self.subTest(bad=bad):
                self.refused(f'ticket_ref = "{bad}"\n', "ticket_ref .* must be a prefix")


class PlanRefsTest(unittest.TestCase):
    TEXT = "see c-287, tk-36530, st-4, PR #12 and MR #3 and keel/serve.py:40"

    def kinds(self, refs) -> list[tuple[str, str]]:
        return [(s["kind"], s["v"]) for s in planinline.spans(self.TEXT, refs) if s["t"] == "ref"]

    def test_the_work_space_links_its_story_and_pr(self):
        refs = terms.refs(terms.Terms(packs.load(STORY).terms))
        self.assertEqual(self.kinds(refs), [("card", "c-287"), ("ticket", "tk-36530"), ("change", "PR #12"),
                                            ("path", "keel/serve.py:40")])

    def test_the_sandbox_links_the_reverse(self):
        refs = terms.refs(terms.Terms(packs.load(PACKS / "sandbox").terms))
        self.assertEqual(self.kinds(refs), [("card", "c-287"), ("ticket", "st-4"), ("change", "MR #3"),
                                            ("path", "keel/serve.py:40")])

    def test_with_no_refs_only_cards_and_paths_link(self):
        self.assertEqual(self.kinds(None), [("card", "c-287"), ("path", "keel/serve.py:40")])

    def test_parse_hands_its_refs_to_every_span(self):
        refs = terms.refs(terms.Terms(packs.load(STORY).terms))
        doc = planformat.parse("# T\n\nA **bold tk-36530** line.\n", "plan.md", refs)
        found = list(planinline.walk_refs(doc["blocks"][-1]["text"]))
        self.assertEqual([(s["kind"], s["v"]) for s in found], [("ticket", "tk-36530")])
        # and the refs end with the parse: a later parse with none links no ticket
        plain = planformat.parse("# T\n\nA tk-36530 line.\n", "plan.md")
        self.assertEqual(list(planinline.walk_refs(plain["blocks"][-1]["text"])), [])


class BoardWordsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "board.db"

    def declined(self, board: Board) -> str:
        self.addCleanup(board.close)
        card = board.create("work", "x", actor="human")
        card_id = card["id"] if isinstance(card, dict) else card
        board.conn.execute("UPDATE cards SET stage='shipping', options=? WHERE id=?",
                           (json.dumps({"shipping": {"state": "declined"}}), card_id))
        with self.assertRaises(Refused) as caught:
            board._refuse_ship(board._row(card_id))
        return str(caught.exception)

    def test_a_refusal_says_the_spaces_word(self):
        sandbox = terms.Terms(packs.load(PACKS / "sandbox").terms)
        board = Board(self.db, terms=lambda name: sandbox if name == "work" else None)
        self.assertIn("'s merge request was declined", self.declined(board))

    def test_a_board_built_without_terms_says_the_defaults(self):
        self.assertIn("'s pull request was declined", self.declined(Board(self.db)))


if __name__ == "__main__":
    unittest.main()
