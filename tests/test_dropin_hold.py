"""U3: Drop in on an EXITED house, and the race it opened (2026-09-24).

Probed that day on Claude Code 2.1.281 with throwaway config dirs
(`tests/fixtures/harness/README.md`, "Drop in on an exited house"):

- `claude --resume <uuid>` typed in a terminal keeps the SAME session id, and
  `claude agents --json` lists it as `kind: interactive`, `status: idle` between turns, with
  no `id`. The house's own `--settings` (Keel's hooks) are NOT carried into it: no hook
  fires for his turns, and none when he leaves.
- Keel's own resume on that session while he is in it (`claude --resume <uuid> --bg
  <prompt> --settings ...`) answered "session <id> is open in another Claude Code process,
  so this started a copy as <new id>": two copies of one conversation in one directory, and
  the card then follows the copy. The supersede's `claude stop <short id>` said "stopped"
  and left his terminal running.

So his Resume house tap (and a gate answer, a relayed resume, the drain's quiet rule and
`retire_tracking`) could fork the conversation he is typing into, and reconcile could
resume an unblocked exited house in the seconds between the handed command and his paste.
Closed the way voice is: Drop in on an exited house takes a hold with an expiry
(`options.dropin_hold`), every resume refuses a held card or an interactive row, the drain
leaves a held card alone, and the hold ends when it runs out unjoined or when his terminal
session leaves the listing.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import actions, drain, dropin, house, login, views
from keel.board import Board, Refused
from tests.helpers import SESSION, FakeHarness, FakeMachine, aged, background_row, make_config, signed_in


FRESH = "f00dcafe-0000-4000-8000-000000000009"


def interactive_row(name: str, session_id: str = SESSION, status: str = "idle") -> dict:
    """The row `claude agents --json` gave for a terminal `claude --resume` (probed)."""
    return {"pid": 2, "cwd": "/x", "kind": "interactive", "startedAt": 0,
            "sessionId": session_id, "name": name, "status": status}


def stamp(delta: timedelta) -> str:
    return (datetime.now().astimezone() + delta).isoformat(timespec="seconds")


class HoldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = signed_in(make_config(self.dir))
        self.cfg.drain_paused = True
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        for module in (dropin, actions, house, drain, login):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(drain, "machine", FakeMachine())
        patch.start()
        self.addCleanup(patch.stop)
        self.kb = []
        patch = mock.patch.object(actions.subprocess, "run", side_effect=self.fake_kb)
        patch.start()
        self.addCleanup(patch.stop)

    def fake_kb(self, argv, **kwargs):
        """The deck's `kb` writes, carried out on this board as his so the hold is real."""
        self.kb.append(list(argv))
        args = [a for a in argv[1:] if a != "--json"]
        if args and args[0] == "set":
            key, _, value = args[2].partition("=")
            name = key.split(".", 1)[1]
            self.board.set_fields(args[1], {"options": {name: json.loads(value)}}, "human")
        elif args and args[0] == "unblock":
            self.board.unblock(args[1], "human")
        return mock.Mock(returncode=0, stdout="null", stderr="")

    def exited(self, stage="building", blocked=True) -> str:
        """A house that exited and is blocked for it: the card he wants to drop into."""
        card_id = self.board.create("personal", "an errand", actor="human")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, stage, "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        if blocked:
            self.board.block(card_id, "exited twice", "drain")
        return card_id

    def hold(self, card_id: str, until: timedelta = timedelta(minutes=10), seen=False) -> None:
        self.board.set_fields(card_id, {"options": {views.DROPIN_HOLD_OPTION: {
            "at": stamp(timedelta()), "until": stamp(until), "session": SESSION,
            "seen": seen}}}, "human")

    def held(self, card_id: str) -> dict | None:
        return self.board.get(card_id)["options"].get(views.DROPIN_HOLD_OPTION)

    def notes(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]

    def once(self) -> dict:
        return drain.once(self.cfg, board=self.board)


class TheRaceTest(HoldCase):
    """The reproduction: he pasted the handed `claude --resume` and is in the conversation;
    the tap that used to start a second copy of it is now refused."""

    def test_resume_house_while_he_is_in_the_session_starts_no_copy(self):
        card_id = self.exited()
        self.fake.rows = [interactive_row(card_id)]
        with self.assertRaises(actions.ActionError) as refused:
            actions.act(self.cfg, self.board, {"verb": "house.resume", "id": card_id})
        self.assertEqual(self.fake.resumes, [])
        self.assertIn("terminal", str(refused.exception))
        self.assertEqual(getattr(self.fake, "stops", []), [])

    def test_an_interactive_row_is_refused_even_with_no_hold(self):
        """He ran `claude --resume` from his own shell history, not through Drop in."""
        card_id = self.exited(blocked=False)
        self.fake.rows = [interactive_row(card_id)]
        with self.assertRaises(house.InTerminal):
            house.resume(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.resumes, [])

    def test_an_idle_background_row_is_still_resumed_and_superseded_as_before(self):
        card_id = self.exited(blocked=False)
        self.fake.rows = [background_row(card_id, SESSION)]
        house.resume(self.cfg, self.board, card_id)
        self.assertEqual(len(self.fake.resumes), 1)

    def test_a_gate_answer_on_a_held_card_lands_and_says_why_the_house_was_not_resumed(self):
        card_id = self.board.create("personal", "planned", actor="human", autonomy="attended")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "planning", "drain", plan_ref=str(self.cfg.card_dir(card_id) / "p.md"))
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.fake.rows = [interactive_row(card_id)]
        answer = actions.gate_answer(self.cfg, self.board, card_id, "build it")
        self.assertIsNone(answer["resumed"])
        self.assertIn("terminal", answer["note"])
        self.assertEqual(self.fake.resumes, [])


class DropinTakesTheHoldTest(HoldCase):
    def test_drop_in_on_an_exited_house_takes_a_hold_with_an_expiry(self):
        card_id = self.exited()
        answer = actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertEqual(answer["how"], dropin.RESUME)
        held = self.held(card_id)
        self.assertEqual(held["session"], SESSION)
        self.assertFalse(held["seen"])
        until = views.parse_at(held["until"])
        self.assertGreater(until, datetime.now().astimezone() + timedelta(seconds=dropin.HOLD_SECONDS - 60))

    def test_drop_in_on_a_house_whose_conversation_is_gone_starts_one_afresh_and_joins_it(self):
        """c-654 (c-020): `claude --resume <id>` fails at his terminal once the harness no
        longer holds the conversation, so a new house is started from the card's record and
        the command joins THAT session."""
        card_id = self.gone()
        self.fake.on_start = lambda name: setattr(self.fake, "rows", [background_row(name, FRESH)])
        answer = actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertEqual(answer["how"], dropin.ATTACH)
        self.assertIn(f"attach {FRESH[:8]}", answer["command"])
        self.assertNotIn(SESSION, answer["command"])
        self.assertEqual(self.board.get(card_id)["session_id"], FRESH)
        self.assertIsNone(self.held(card_id), "attach joins the one session: nothing to hold")
        self.assertIn("context.md", self.fake.starts[0]["prompt"])
        self.assertTrue(any(SESSION in note and FRESH[:8] in note for note in self.notes(card_id)))
        self.assertEqual(self.fake.gone_asked[0][1], str(self.cfg.card_dir(card_id)),
                         "asked where the handed command would have run")

    def gone(self, **kwargs) -> str:
        """An exited house last used 40 days ago, whose conversation the harness holds no more."""
        card_id = self.exited(**kwargs)
        aged(self.board, card_id, 40)
        self.fake.gone, self.fake.started_as = {SESSION}, FRESH
        return card_id

    def refused(self, card_id: str) -> str:
        """Drop in refused: its words, and neither a command nor a hold was handed out."""
        with self.assertRaises(actions.ActionError) as refusal:
            actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertIsNone(self.held(card_id))
        self.assertFalse(any("drop-in command handed out" in (note or "") for note in self.notes(card_id)))
        return str(refusal.exception)

    def test_a_fresh_house_the_harness_does_not_list_yet_is_never_handed_out_as_a_resume(self):
        """c-654 review: the new house may be in its first turn, and `claude --resume` of it
        would start a copy (N10). It is joined by its own id once listed, or not at all."""
        card_id = self.gone()
        said = self.refused(card_id)
        self.assertIn(FRESH[:8], said)
        self.assertIn("again", said)
        self.assertEqual(self.board.get(card_id)["session_id"], FRESH)
        # the second tap he was told to make: still not listed, so still nothing handed out,
        # and the house that may be starting is not asked about or blocked for it
        self.fake.gone = {SESSION, FRESH}
        self.assertIn(FRESH[:8], self.refused(card_id))
        self.assertEqual(len(self.fake.gone_asked), 1)
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "exited twice")

    def test_his_unblock_of_the_second_refusal_lets_drop_in_start_the_one_more_house(self):
        """The fresh house died before it ran a turn and a second start was refused; he
        unblocked that. Drop in then starts the one more house and joins it, and no longer
        answers "tap again in a moment" for the dead one."""
        card_id = self.gone(blocked=False)
        self.refused(card_id)                              # FRESH started, never listed
        self.fake.gone = {SESSION, FRESH}
        with self.assertRaises(house.harness.HarnessError):
            house.resume(self.cfg, self.board, card_id)    # the second fresh start, refused
        self.assertIn("a second time", self.board.get(card_id)["blocked_reason"])
        self.board.unblock(card_id, "human")
        third = "abadcafe-0000-4000-8000-00000000000a"
        self.fake.started_as = third
        self.fake.on_start = lambda name: setattr(self.fake, "rows", [background_row(name, third)])
        answer = actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertEqual((answer["how"], len(self.fake.starts)), (dropin.ATTACH, 2))
        self.assertIn(f"attach {third[:8]}", answer["command"])

    def test_an_answered_second_refusal_never_hands_the_dead_house_out_as_a_resume(self):
        """He unblocked the second refusal, but the harness cannot be asked now (its listing
        fails), so no house is started: the unlisted fresh session is still not handed out."""
        card_id = self.gone(blocked=False)
        self.refused(card_id)
        self.fake.gone = {SESSION, FRESH}
        with self.assertRaises(house.harness.HarnessError):
            house.resume(self.cfg, self.board, card_id)
        self.board.unblock(card_id, "human")
        self.fake.listing_fails = True
        self.assertIn(FRESH[:8], self.refused(card_id))
        self.assertEqual(len(self.fake.starts), 1)

    def test_a_withheld_fresh_start_refuses_drop_in_until_his_own_unblock(self):
        card_id = self.exited(blocked=False)
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION})
        aged(self.board, card_id, 5)
        self.fake.gone, self.fake.started_as = {SESSION}, FRESH
        self.assertIn("unblock the card yourself", self.refused(card_id))
        self.assertEqual(self.fake.starts, [])
        self.board.unblock(card_id, "human")
        self.fake.on_start = lambda name: setattr(self.fake, "rows", [background_row(name, FRESH)])
        answer = actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertEqual((answer["how"], len(self.fake.starts)), (dropin.ATTACH, 1))

    def test_a_done_card_whose_conversation_is_gone_opens_a_session_on_its_record(self):
        """c-787: a done card's house is never started again (c-654 review), so its gone
        conversation is handed out as a fresh session in the card's record, his terminal's:
        no house started, no hold, nothing recorded as the card's session."""
        card_id = self.gone(blocked=False)
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="out.md")
        self.board.approve(card_id, "outcome", "human")
        self.assertEqual(self.board.get(card_id)["stage"], "done")
        answer = actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertEqual(answer["how"], dropin.RECORD)
        self.assertIn(f"cd {self.cfg.card_dir(card_id)}", answer["command"])
        self.assertIn("context.md", answer["command"])
        self.assertNotIn("--resume", answer["command"])
        self.assertEqual(self.fake.starts, [])
        self.assertIsNone(self.held(card_id))
        self.assertEqual(self.board.get(card_id)["session_id"], SESSION)

    def test_a_fresh_start_that_fails_leaves_the_card_blocked_and_hands_out_nothing(self):
        card_id = self.gone(blocked=False)
        self.fake.fail = "claude would not start"
        said = self.refused(card_id)
        self.assertIn("claude would not start", said)
        self.assertIn("claude would not start", self.board.get(card_id)["blocked_reason"])

    def test_drop_in_on_a_live_house_takes_none(self):
        """Attach JOINS the running session (N10); there is no second copy to prevent."""
        card_id = self.exited(blocked=False)
        self.fake.rows = [background_row(card_id, SESSION)]
        actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertIsNone(self.held(card_id))

    def test_drop_in_with_no_session_takes_none(self):
        card_id = self.board.create("personal", "fresh", actor="human")
        actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertIsNone(self.held(card_id))

    def test_his_resume_house_is_refused_during_the_paste_window(self):
        card_id = self.exited()
        actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        events = len(self.board.events(card_id))
        with self.assertRaises(actions.ActionError) as refused:
            actions.act(self.cfg, self.board, {"verb": "house.resume", "id": card_id})
        self.assertEqual(self.fake.resumes, [])
        # the hold's own sentence, pinned (c-673 review 3), and nothing written for the tap
        self.assertEqual(str(refused.exception),
                         f"Drop in handed you {card_id}'s conversation to resume in a terminal, so it is "
                         f"not resumed here as well. Quit that session, or wait for the hold to run out "
                         f"if you never opened it")
        self.assertEqual(len(self.board.events(card_id)), events)


class DropInOnASessionAlreadyInATerminalTest(HoldCase):
    """Found on the scratch deck: the listing's interactive row made Drop in say "attach",
    and `claude attach` takes a BACKGROUND session's id. The terminal already has it."""

    def test_drop_in_says_it_is_open_there_rather_than_handing_attach(self):
        card_id = self.exited(blocked=False)
        self.fake.rows = [interactive_row(card_id)]
        with self.assertRaises(actions.ActionError) as refused:
            actions.act(self.cfg, self.board, {"verb": "dropin", "id": card_id})
        self.assertIn("already open in a terminal", str(refused.exception))

    def test_the_house_row_says_what_kind_of_session_it_is(self):
        """So the deck can tell a terminal from a house, and draw neither Logs nor Stop
        (both take a background session's id) for it."""
        self.assertEqual(dropin.row_facts(interactive_row("c-1"))["kind"], "interactive")
        self.assertEqual(dropin.row_facts(background_row("c-1", SESSION))["kind"], "background")


class TheDrainLeavesItAloneTest(HoldCase):
    def test_reconcile_does_not_resume_a_held_exited_house_before_he_pastes(self):
        """An unblocked exited house is reconcile's to resume, and a resume mints a NEW
        session: his pasted `--resume <old>` would then fork the conversation."""
        card_id = self.exited(blocked=False)
        self.hold(card_id)
        counts = self.once()
        self.assertEqual((counts["resumed"], counts["blocked"]), (0, 0))
        self.assertEqual(self.fake.resumes, [])

    def test_a_held_house_is_never_read_as_quiet(self):
        card_id = self.exited(blocked=False)
        self.fake.rows = [interactive_row(card_id)]
        self.hold(card_id, seen=True)
        self.board.record_hook(card_id, "Notification", {
            "notification_type": "idle_prompt", "session_id": SESSION})
        self.assertIsNone(drain.idle_stuck(self.cfg, self.board, self.board.get(card_id),
                                           self.fake.rows,
                                           at=datetime.now().astimezone() + timedelta(hours=3)))

    def test_a_held_tracking_card_s_session_is_not_retired_under_him(self):
        card_id = self.exited(blocked=False)
        self.board.split(card_id, [{"title": "A"}, {"title": "B"}], "house")
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION}, {"tracking": True})
        self.fake.rows = [interactive_row(card_id)]
        self.hold(card_id, seen=True)
        self.once()
        self.assertEqual(getattr(self.fake, "stops", []), [])


class TheHoldEndsTest(HoldCase):
    def test_the_drain_marks_the_hold_seen_once_he_is_in(self):
        card_id = self.exited()
        self.hold(card_id)
        self.fake.rows = [interactive_row(card_id)]
        self.once()
        self.assertTrue(self.held(card_id)["seen"])

    def test_a_seen_hold_does_not_run_out_while_he_is_still_in(self):
        card_id = self.exited()
        self.hold(card_id, until=timedelta(minutes=-30), seen=True)
        self.fake.rows = [interactive_row(card_id)]
        self.once()
        self.assertIsNotNone(self.held(card_id))

    def test_it_ends_when_his_terminal_session_leaves_the_listing(self):
        card_id = self.exited(blocked=False)
        self.hold(card_id, seen=True)
        self.fake.rows = []
        counts = self.once()
        self.assertIsNone(self.held(card_id))
        self.assertTrue(any("terminal" in note for note in self.notes(card_id)))
        # the release pass leaves the card alone; the next pass treats it as any exited house
        self.assertEqual(counts["resumed"], 0)
        self.assertEqual(self.once()["resumed"], 1)

    def test_it_ends_when_nobody_joined_before_it_ran_out(self):
        card_id = self.exited()
        self.hold(card_id, until=timedelta(minutes=-1))
        self.once()
        self.assertIsNone(self.held(card_id))
        self.assertTrue(any("Drop in" in note for note in self.notes(card_id)))

    def test_an_unexpired_unjoined_hold_is_kept(self):
        card_id = self.exited()
        self.hold(card_id)
        self.once()
        self.assertIsNotNone(self.held(card_id))


class OnlyHeAndTheDrainWriteItTest(HoldCase):
    def test_a_house_cannot_grant_itself_the_hold(self):
        card_id = self.exited()
        with self.assertRaises(Refused):
            self.board.set_fields(card_id, {"options": {views.DROPIN_HOLD_OPTION: {"seen": True}}},
                                  "house")

    def test_no_card_is_filed_with_one(self):
        with self.assertRaises(Refused):
            self.board.create("personal", "x", actor="human",
                              options={views.DROPIN_HOLD_OPTION: {"seen": True}})


if __name__ == "__main__":
    unittest.main()
