"""Your first card and the last screen (keel/firstrun.py, keel/tierdrafts.py, c-678): the
step order's end, what counts as the user's first card, the card Bosun suggests from a file
it drafted, and what the step carries of the card as it moves. On a real scratch install
from `shipyard init`, with a local bare repo as the repo's address; no session is started."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, deckstate, firstrun, landpush, packs, readiness, tierdrafts
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

DRAFT = "# api\n\n## Prepare and test\n- Run the tests: `npm test`\n"
NOTE = "First card: Add a setup section to the README (because the README has no setup section)"


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        readiness.forget()
        self.addCleanup(readiness.forget)
        for name, value in (("keel.prereqs.gather", []), ("keel.readiness.serve_status", {"missing": True})):
            fake = mock.patch(name, return_value=value)
            fake.start()
            self.addCleanup(fake.stop)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def act(self, body):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return actions.act(cfg, board, body)

    def add(self, key="api") -> str:
        work, origin = self.home.parent / f"{key}-work", self.home.parent / f"{key}.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        (work / "README").write_text("hello\n")
        for argv in (["add", "."], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "one"],
                     ["push", "-q", str(origin), "HEAD:main"]):
            subprocess.run(["git", "-C", str(work), *argv], check=True)
        return self.act({"verb": "setup.repo.add", "space": "work", "url": str(origin), "key": key})["draft"]

    def drafted(self, card: str, note: str | None = NOTE):
        cfg = self.cfg()
        out = self.home / "builder" / "cards" / card / "claude-md.md"
        with open_board(cfg) as board:
            board.stage(card, "building", "bosun")
            if note:
                board.note(card, note, "bosun")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(DRAFT)
            board.stage(card, "review", "bosun", output_ref=str(out))

    def step(self, name="first-card"):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return next(s for s in firstrun.report(cfg, board)["steps"] if s["id"] == name)


class OrderTest(Case):
    def test_the_last_two_places_are_the_first_card_and_you_are_set_up(self):
        ids = [step.id for step in firstrun.STEPS]
        self.assertEqual(ids[-2:], ["first-card", "set-up"])
        self.assertNotIn("phone", ids, "Phone and voice is on the last screen, under More to set up later")
        self.assertEqual(len(ids), 13)
        self.assertEqual(firstrun.BY_ID["first-card"].headline, "Give Shipyard one small piece of work")
        self.assertEqual(firstrun.BY_ID["set-up"].headline, "You are set up")

    def test_the_last_screen_has_nothing_to_check_and_no_skip(self):
        step = self.step("set-up")
        self.assertEqual((step["done"], step["skip"], step["required"]), (None, False, False))

    def test_what_pointed_at_the_phone_step_points_at_the_last_screen(self):
        """c-729: voice has no step to set it up (the owner's call: no voice step), so its row
        names none and the page sends the user to Bosun instead; the phone keeps the last
        screen, where its command is."""
        self.assertEqual((readiness.STEPS["phone"], readiness.STEPS["voice"]), ("set-up", None))
        self.assertEqual(packs.SETUP_MOVED["phone"], "first-card", "a pack's step never follows the last screen")
        self.assertIn("set-up", packs.SETUP_AFTER)


class FirstCardTest(Case):
    def test_a_card_filed_from_the_users_words_gets_a_short_title_and_keeps_the_words(self):
        """c-729: the first card's form sends what the user wrote as `words`; the card's title
        is short (so its branch and its merge subject are), and the words are its brief."""
        self.add("notes-api")
        made = self.act({"verb": "create", "space": "work", "repo": "notes-api",
                         "words": "In notes-api add a way to delete a note", "brief": "It asks first."})
        cfg = self.cfg()
        with open_board(cfg) as board:
            card = board.get(made["id"])
        self.assertEqual(card["title"], "Add a way to delete a note")
        self.assertEqual(card["brief"], "In notes-api add a way to delete a note\n\nIt asks first.")
        with self.assertRaisesRegex(actions.ActionError, "create needs title"):
            self.act({"verb": "create", "space": "work", "words": "  "})

    def test_a_state_build_asks_git_nothing_about_a_landed_cards_push(self):
        """It did on every poll, finished install or not (review F11): the offer is the card
        detail's alone now."""
        self.add()
        cfg = self.cfg()
        with open_board(cfg) as board:
            card = board.create("work", "Fix a typo", repo="api", actor="human")
            board.set_fields(card, {"options": {"landing": {"state": "landed", "sha": "a" * 40, "merge": "a" * 40,
                                                            "published": "aaaaaaa merged into main locally, not pushed"}}}, "drain")
            board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
            board.conn.commit()
            with mock.patch.object(landpush, "run", side_effect=AssertionError("git was asked")) as asked, \
                    mock.patch.object(landpush, "offer", wraps=landpush.offer) as offered:
                state = deckstate.build(cfg, board, rows=[])
            self.assertEqual((asked.call_count, offered.call_count), (0, 0))
            step = next(s for s in state["firstrun"]["steps"] if s["id"] == "first-card")
            self.assertEqual(step["card"]["id"], card)

    def test_a_draft_card_is_not_the_users_first_card(self):
        self.add()
        self.act({"verb": "setup.flow.draft", "space": "work"})
        step = self.step()
        self.assertEqual((step["done"], step["why"]), (False, "no card filed yet"))
        self.assertNotIn("card", step)

    def test_the_step_follows_the_card_the_user_filed(self):
        self.add()
        cfg = self.cfg()
        with open_board(cfg) as board:
            card = board.create("work", "Fix a typo", repo="api", actor="human")
        step = self.step()
        self.assertEqual((step["card"]["id"], step["card"]["stage"], step["card"]["title"]), (card, "inbox", "Fix a typo"))
        self.assertIsNone(step["card"]["blocked"])
        self.assertNotIn("push", step["card"], "the Push comes with the card's own detail, not every state")
        self.assertFalse(step["done"])


class SuggestionTest(Case):
    def test_nothing_is_suggested_before_a_file_is_adopted(self):
        card = self.add()
        self.drafted(card)
        self.assertIsNone(self.step().get("suggestion"))

    def test_an_adopted_file_brings_the_card_bosun_noted(self):
        card = self.add()
        self.drafted(card)
        self.act({"verb": "setup.tier.adopt", "card": card})
        self.assertEqual(self.step()["suggestion"], {
            "space": "work", "repo": "api", "file": "api/CLAUDE.md",
            "title": "Add a setup section to the README", "saw": "the README has no setup section"})

    def test_a_note_with_no_reason_is_still_a_suggestion(self):
        card = self.add()
        self.drafted(card, "First card: Fix the typo in the README")
        self.act({"verb": "setup.tier.adopt", "card": card})
        found = self.step()["suggestion"]
        self.assertEqual((found["title"], found["saw"]), ("Fix the typo in the README", None))

    def test_a_draft_with_no_such_note_suggests_nothing(self):
        card = self.add()
        self.drafted(card, None)
        self.act({"verb": "setup.tier.adopt", "card": card})
        self.assertIsNone(self.step().get("suggestion"))

    def test_the_brief_tells_bosun_how_to_leave_one(self):
        card = self.add()
        cfg = self.cfg()
        with open_board(cfg) as board:
            brief = board.get(card)["brief"]
        self.assertIn(f'kb note {card} "First card: ', brief)

    def test_the_parse_is_exact(self):
        self.assertEqual(tierdrafts.first_card_of("First card: A (because b)"), ("A", "b"))
        self.assertEqual(tierdrafts.first_card_of("  first card:  A thing.  "), ("A thing.", None))
        self.assertIsNone(tierdrafts.first_card_of("the first card: no"))
        self.assertIsNone(tierdrafts.first_card_of("First card:"))


if __name__ == "__main__":
    unittest.main()
