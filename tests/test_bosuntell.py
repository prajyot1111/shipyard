"""Bosun told of the work the page hands it (c-734 A; keel/pausewake.py, "Telling Bosun").

The second stranger run (2026-10-10): Draft a connection filed a card at assigned in Bosun's
queue and nothing told Bosun, so it sat until the user nudged it; and Approve plan on that
card (one Bosun builds, with no house) answered "no session to resume". Now a card the page
files for Bosun, and every gate tap on a card Bosun builds, records a `tell` on the card,
and the drain's existing wake (`drain.pause_upkeep`, `consolewake.wake`, its claim and its
backoff) tells an idle Bosun once, naming the card. No house is resumed for a Bosun card.
On a real scratch install from `shipyard init`; no session is started."""

import contextlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import actions, console, consoletaps, consolewake, drain, flowcards, pausewake, readiness, tiercards
from keel import config as config_module
from keel.board import Board, open_board
from tests.helpers import no_real_tools
from tests.test_asks import WakeHarness
from tests.test_console import LifecycleCase
from tests.test_installer import init

WORDS = "We use a self-hosted forge. A teammate reviews each change and merges it."


class TellCase(unittest.TestCase):
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
        self.cfg = config_module.load(self.home / "config.toml", ensure=False)

    def act(self, body):
        with open_board(self.cfg) as board:
            return actions.act(self.cfg, board, body)

    def told(self):
        """What the drain would tell Bosun now: `{card: state}`."""
        with open_board(self.cfg) as board:
            return {row["card"]: row["state"] for row in pausewake.wakes(board)}

    def upkeep(self, sent: list, answer=lambda: {"session_id": "s"}):
        """One drain pass of the wake, with an idle Bosun whose relay `answer` stands in for."""
        with open_board(self.cfg) as board, \
                mock.patch.object(drain.consolewake, "can_wake", return_value=True), \
                mock.patch.object(drain.consolewake, "wake",
                                  side_effect=lambda cfg, note, what: sent.append(note) or answer()), \
                mock.patch.object(drain, "log"):
            drain.pause_upkeep(self.cfg, board)

    def connection(self) -> str:
        return self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})["card"]


class FiledTest(TellCase):
    def test_each_card_the_page_files_for_bosun_is_told_once(self):
        """The connection draft, the flow draft and a repo's CLAUDE.md draft each queue one
        tell naming the card; the drain sends one wake for them, and the next pass none."""
        connection = self.connection()
        flow = self.act({"verb": "setup.flow.draft", "space": "personal"})["card"]
        with open_board(self.cfg) as board:
            tier = tiercards.open_draft(self.cfg, board, "personal", None, [self.home / "packs"])
        self.assertEqual(self.told(), {connection: "filed", flow: "filed", tier: "filed"})
        sent = []
        self.upkeep(sent)
        self.upkeep(sent)
        self.assertEqual(len(sent), 1, "one wake, and the second pass finds nothing new")
        for card in (connection, flow, tier):
            self.assertIn(f"{card} ({pausewake.TELLS['filed']})", sent[0])
        self.assertNotIn(WORDS, sent[0], "ids and fixed words only: the relay may obey text")
        self.assertEqual(self.told(), {})

    def test_a_busy_bosun_is_told_on_a_later_pass_and_never_twice(self):
        connection = self.connection()
        sent = []
        self.upkeep(sent, answer=lambda: None)          # busy: nothing was sent, nothing recorded
        self.assertEqual(self.told(), {connection: "filed"})
        self.upkeep(sent)
        self.upkeep(sent)
        self.assertEqual(len(sent), 2)
        self.assertEqual(self.told(), {})

    def test_the_tap_says_bosun_is_told(self):
        done = self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})
        self.assertIn(pausewake.TOLD, done["note"])
        flow = self.act({"verb": "setup.flow.draft", "space": "personal"})
        self.assertIn(pausewake.TOLD, flow["note"])
        with open_board(self.cfg) as board:
            self.assertFalse(pausewake.told(board, done["card"]), "queued, not yet told")
        self.upkeep([])
        with open_board(self.cfg) as board:
            self.assertTrue(pausewake.told(board, done["card"]))

    def test_a_proposal_a_house_works_is_not_told(self):
        """A flow proposal is a house's card (the drain starts it): Bosun has nothing to do."""
        card = self.act({"verb": "setup.flow.propose", "space": "personal", "words": "main only"})["card"]
        self.assertNotIn(card, self.told())
        with open_board(self.cfg) as board:
            self.assertIsNotNone(flowcards.proposals(board).get("personal"))


class PassTest(TellCase):
    """r1.F18, fix check: "at once" is one ordinary drain pass asked for by the tell (the
    `drain --once` Approve outcome's landing asks for), which keeps one wake a pass; a kick's
    carry runs no wake, so the relays stay fast and no second message lands."""

    def test_a_tell_asks_for_one_pass_where_a_drain_serves(self):
        from keel import kick
        with mock.patch.object(kick, "held_by_another", return_value=True), \
                mock.patch("subprocess.Popen") as started:
            self.connection()
        self.assertEqual(started.call_count, 1)
        self.assertEqual(started.call_args.args[0][1:], ["drain", "--once"])

    def test_no_drain_no_pass(self):
        with mock.patch("subprocess.Popen") as started:
            self.connection()
        started.assert_not_called()

    def test_a_kicks_carry_runs_no_wake(self):
        with mock.patch.object(drain, "wake_upkeep") as woke, mock.patch.object(drain.deploy, "kicked"), \
                mock.patch.object(drain.harness, "agents_across", return_value=[]):
            drain.carry_pass(self.cfg)
        woke.assert_not_called()


class SpacedTest(LifecycleCase):
    """The pass a tell asks for, and the drain's own pass close behind it, wake Bosun once:
    the real `consolewake.can_wake` and `wake` (where the spacing lives) with a fake relay and
    the real Journal, as `tests/test_asks.py` WakeTest runs them (r2.F7)."""

    def setUp(self):
        super().setUp()
        self.fake = WakeHarness()
        for module, name in ((console, "harness"), (consoletaps, "harness"), (consolewake, "harness"),
                             (consolewake, "relay")):
            patch = mock.patch.object(module, name, self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        self.board = Board(self.dir / "spaced.db")
        self.addCleanup(self.board.close)
        consoletaps.tap(self.cfg, "start")       # an idle Bosun

    def upkeep(self):
        with mock.patch.object(drain, "log"):
            drain.pause_upkeep(self.cfg, self.board)

    def later(self, seconds):
        """The board's clock and the Journal's moved on together."""
        at = (datetime.fromisoformat(self.board.now()) + timedelta(seconds=seconds)).isoformat()
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(self.board, "now", return_value=at))
        stack.enter_context(mock.patch.object(console, "now_iso", return_value=at))
        return stack

    def test_a_second_tell_within_the_spacing_waits_and_is_told_after_it(self):
        first, second = self.board.create("personal", "one"), self.board.create("personal", "two")
        pausewake.tell(self.board, first, "filed")
        self.upkeep()
        self.assertEqual(len(self.fake.told), 1)
        self.assertIn(first, self.fake.told[0]["message"])
        pausewake.tell(self.board, second, "filed")
        self.upkeep()
        self.assertEqual(len(self.fake.told), 1, "a wake went moments ago: one message")
        self.assertFalse(pausewake.told(self.board, second), "still queued, not lost")
        with self.later(consolewake.SPACING_SECONDS + 1):
            self.upkeep()
        self.assertEqual(len(self.fake.told), 2)
        self.assertIn(second, self.fake.told[1]["message"])
        self.assertNotIn(first, self.fake.told[1]["message"], "the first was told once")


class GateTest(TellCase):
    """Every gate tap on a card Bosun builds tells Bosun and resumes no house."""

    def at(self, stage: str) -> str:
        card = self.connection()
        with open_board(self.cfg) as board:
            self.assertTrue(board.get(card)["derived"]["bosun"], "the connection draft is Bosun's to build")
            board.stage(card, "planning", "bosun")
            plan = self.cfg.card_dir(card) / "plan.md"
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text("# the plan\n")
            board.set_fields(card, {"plan_ref": str(plan)}, "bosun")
            if stage == "review":
                board.approve(card, "plan", "human")
                board.stage(card, "review", "bosun", output_ref=f"bosun/{card}-connection")
            woke = [row for row in pausewake.wakes(board) if row["card"] == card]
            pausewake.woke(board, [f"{card}@{woke[0]['event']}"], "drain")     # the filing was told
        return card

    def test_approve_plan_tells_bosun_and_resumes_nothing(self):
        card = self.at("planning")
        with mock.patch.object(actions.house, "resume") as resumed:
            done = self.act({"verb": "approve", "id": card, "gate": "plan"})
        resumed.assert_not_called()
        self.assertNotIn("no house session", done["note"])
        self.assertEqual(done["note"], pausewake.TOLD_NOTE)
        self.assertEqual((done["resumed"], done["told"]), (None, "plan"))
        self.assertEqual(self.told(), {card: "plan"})

    def test_send_back_at_the_plan_tells_bosun(self):
        card = self.at("planning")
        with mock.patch.object(actions.house, "resume") as resumed:
            done = self.act({"verb": "sendback", "id": card, "reason": "name the pack forge"})
        resumed.assert_not_called()
        self.assertEqual((done["resumed"], done["told"]), (None, "sendback"))
        self.assertEqual(self.told(), {card: "sendback"})

    def test_stay_to_discuss_is_refused_in_plain_words_and_nothing_is_written(self):
        """r1.F16: no house serves a discussion on a card Bosun builds."""
        card = self.at("planning")
        with self.assertRaises(actions.ActionError) as refused:
            self.act({"verb": "sendback", "id": card, "reason": "let us talk", "stay": True})
        self.assertIn("talk it over with Bosun in its session", str(refused.exception))
        with open_board(self.cfg) as board:
            self.assertFalse(board.get(card)["options"].get("discussion"))
            self.assertNotIn("let us talk", [e["text"] for e in board.events(card)])
        self.assertEqual(self.told(), {})

    def test_send_back_at_the_outcome_tells_bosun(self):
        card = self.at("review")
        with mock.patch.object(actions.house, "resume") as resumed:
            done = self.act({"verb": "sendback", "id": card, "reason": "the token check is missing"})
        resumed.assert_not_called()
        self.assertEqual(done["told"], "sendback")
        self.assertEqual(self.told(), {card: "sendback"})

    def test_approve_outcome_tells_bosun(self):
        card = self.at("review")
        with mock.patch.object(actions, "queue_landing", return_value={"card": {}, "relayed": "land", "note": "queued"}), \
                mock.patch.object(actions.house, "resume") as resumed:
            done = self.act({"verb": "approve", "id": card, "gate": "outcome"})
        resumed.assert_not_called()
        self.assertEqual(done["told"], "outcome")
        self.assertEqual(self.told(), {card: "outcome"})


if __name__ == "__main__":
    unittest.main()
