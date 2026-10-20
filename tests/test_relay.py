"""Relays: the human's tap on a deck that is not the house's machine, recorded on the board
and carried once by that machine's drain. The board's record, `kb relay` and `kb carried`,
and the drain carrying them before reconcile."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import drain, house, idleclose, prompts
from keel.board import Board, Refused
from tests.helpers import SESSION, BoardCase, FakeHarness, FakeMachine, make_config, background_row
from tests.test_cli import KbCase

OTHER = "bbbbbbbb-0000-4000-8000-000000000009"


# ----- the board's record -----

class RelayBoardTest(BoardCase):
    def planned(self) -> str:
        card = self.card(autonomy="attended", repo="keel")
        self.board.stage(card, "assigned", "human")
        self.board.claim(card, "mac", "drain")
        self.board.stage(card, "planning", "drain", plan_ref="plan.md")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        return card

    def test_a_relay_is_the_humans_names_its_host_and_the_session_it_was_tapped_for(self):
        card = self.planned()
        with self.assertRaises(Refused):
            self.board.relay(card, "resume", "house", "mac")
        with self.assertRaises(Refused):
            self.board.relay(card, "reboot", "human", "mac")
        with self.assertRaises(Refused):
            self.board.relay(card, "stop", "human", None)
        pending = self.board.relay(card, "stop", "human", "mac")["derived"]["relays"]
        self.assertEqual([(r["what"], r["to"], r["session"]) for r in pending], [("stop", "mac", SESSION)])

    def test_approve_and_its_relay_are_one_write_and_a_refused_approve_writes_neither(self):
        card = self.planned()
        self.board.approve(card, "plan", "human", relay={"prompt": "build it", "to": "mac"})
        kinds = [e["kind"] for e in self.board.events(card)][-2:]
        self.assertEqual(kinds, ["approve", "relay"])
        self.assertEqual(self.board.get(card)["derived"]["relays"][0]["prompt"], "build it")
        with self.assertRaises(Refused):             # at building now: not at the plan gate
            self.board.approve(card, "plan", "human", relay={"prompt": "again", "to": "mac"})
        self.assertEqual(len(self.board.get(card)["derived"]["relays"]), 1)
        with self.assertRaises(Refused):
            self.board.approve(card, "outcome", "human", relay={"prompt": "x", "to": "mac"})

    def test_a_stage_move_carries_a_relay_and_a_refused_move_records_none(self):
        card = self.planned()
        self.board.approve(card, "plan", "human")
        self.board.stage(card, "review", "house", output_ref="out")
        self.board.stage(card, "building", "human", relay={"prompt": "tests are thin", "to": "mac"})
        self.assertEqual([e["kind"] for e in self.board.events(card)][-2:], ["stage", "relay"])
        with self.assertRaises(Refused):
            self.board.stage(card, "done", "human", relay={"prompt": "x", "to": "mac"})
        self.assertEqual(len(self.board.get(card)["derived"]["relays"]), 1)

    def test_carried_once_by_a_drain_and_pending_is_derived(self):
        card = self.planned()
        first = self.board.relay(card, "resume", "human", "mac", prompt="one")["derived"]["relays"][0]
        second = self.board.relay(card, "stop", "human", "mac")["derived"]["relays"][1]
        with self.assertRaises(Refused):
            self.board.carry(card, first["id"], "house")
        self.board.carry(card, first["id"], "drain")
        self.assertEqual([r["id"] for r in self.board.get(card)["derived"]["relays"]], [second["id"]])
        with self.assertRaises(Refused) as caught:
            self.board.carry(card, first["id"], "drain")
        self.assertIn("already carried", str(caught.exception))
        self.board.carry(card, second["id"], "drain", "superseded", "the house moved on")
        self.assertEqual(self.board.get(card)["derived"]["relays"], [])
        last = self.board.events(card)[-1]
        self.assertEqual((last["kind"], last["text"], last["data"]["outcome"]),
                         ("carried", "the house moved on", "superseded"))
        other = self.card()
        with self.assertRaises(Refused):
            self.board.carry(other, second["id"], "drain")        # not that card's relay


class RelayKbTest(KbCase):
    def test_kb_relay_needs_the_token_and_kb_carried_needs_a_drain(self):
        card = self.kb("create", "--space", "personal", "--title", "x")[1]
        code, _, err = self.kb("relay", card, "stop", "--to", "mac")
        self.assertEqual(code, 1)
        self.assertIn("the human's tap", err)
        self.kb("show", card)                                   # makes the token file
        code, out, err = self.kb("relay", card, "resume", "--to", "mac", "--prompt", "go",
                                 env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        relay_id = self.kb_json("show", card)["derived"]["relays"][0]["id"]
        code, _, err = self.kb("carried", card, str(relay_id), env={"KEEL_CARD": card})
        self.assertEqual(code, 1)
        self.assertIn("carried by a drain", err)
        code, _, err = self.kb("--actor", "drain", "carried", card, str(relay_id))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kb_json("show", card)["derived"]["relays"], [])

    def test_a_relay_flag_without_its_host_is_refused(self):
        card = self.kb("create", "--space", "personal", "--title", "x")[1]
        code, _, err = self.kb("stage", card, "assigned", "--to", "mac")
        self.assertEqual(code, 1)
        self.assertIn("--to names the host a --relay is for", err)


# ----- the drain carries them -----

class CarryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.host = "mac"
        self.board = Board(self.cfg.db_path)
        self.fake = FakeHarness()
        for module in (drain, house):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        self.machine = FakeMachine()
        patch = mock.patch.object(drain, "machine", self.machine)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def once(self, **kwargs):
        return drain.once(self.cfg, board=self.board, **kwargs)

    def approved(self, host="mac") -> str:
        """A card whose plan the box approved: at building, its house exited at the gate."""
        card = self.board.create("personal", "an errand", autonomy="attended")
        self.board.stage(card, "assigned", "human")
        self.board.claim(card, host, "drain")
        self.board.stage(card, "planning", "drain", plan_ref="plan.md")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        self.board.approve(card, "plan", "human", relay={"prompt": prompts.approve("plan.md"), "to": host})
        return card

    def test_the_approve_prompt_resumes_the_house_before_reconcile_could(self):
        card = self.approved()
        summary = self.once()
        self.assertEqual((summary["carried"], summary["resumed"], summary["blocked"]), (1, 0, 0))
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.fake.resumes[0]["prompt"], prompts.approve("plan.md"))
        kinds = [e["kind"] for e in self.board.events(card)]
        self.assertLess(kinds.index("carried"), kinds.index("resume"), "marked before it acts")
        self.assertIsNone(self.board.get(card)["blocked_reason"])
        self.assertIn("carried=1", drain.summary_line(summary))

    def test_a_relayed_resume_takes_a_house_off_the_memory_reading(self):
        """His tap is never refused for a shut gate, and the pass may not then start a
        house on the memory that resume has just taken."""
        self.cfg.memory_floor_mb, self.cfg.house_mb = 2048, 700
        self.machine.memory = 2600
        self.approved()
        waiting = self.board.create("personal", "waits")
        self.board.stage(waiting, "assigned", "human")
        summary = self.once()
        self.assertEqual((summary["carried"], summary["started"], summary["memory"]),
                         (1, 0, "1900MB"))
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")

    def test_a_relayed_resume_of_a_busy_house_is_held_never_blocked_or_stopped(self):
        """E1, and c-598: a tap for a WORKING house is not carried and not dropped to a note:
        it stays pending on the board until the house's turn ends. Nothing is stopped or
        blocked (`tests/test_fasttaps.py` has the rest)."""
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="busy")]
        self.fake.stops = []
        self.once()
        self.assertEqual((self.fake.resumes, self.fake.stops), ([], []))
        self.assertIsNone(self.board.get(card)["blocked_reason"])
        self.assertEqual(len(self.board.get(card)["derived"]["relays"]), 1)

    def test_a_relay_kind_this_drain_does_not_know_is_left_pending_never_read_as_stop(self):
        """Review finding 3a: a newer deck may write a kind an older drain has never heard
        of. It used to fall through to `carry_stop`. It stays pending, with one log line."""
        card = self.approved()
        relay = self.board.get(card)["derived"]["relays"][0]
        self.board.carry(card, relay["id"], "drain")
        self.board.record_event(card, "relay", "human", text="teleport",
                                data={"what": "teleport", "to": "mac", "session": SESSION})
        self.fake.rows = [background_row(card, SESSION, status="idle")]
        self.fake.stops = []
        self.once()
        self.once()
        self.assertEqual(self.fake.stops, [])
        self.assertEqual([r["what"] for r in self.board.get(card)["derived"]["relays"]], ["teleport"])
        log = (self.cfg.logs_dir / "drain.log").read_text()
        self.assertEqual(log.count("does not know"), 1)

    def test_a_relay_whose_house_moved_on_is_superseded_not_acted_on(self):
        card = self.approved()
        self.board.set_session(card, OTHER, "drain", bg_id=OTHER[:8])
        self.fake.rows = [background_row(card, OTHER)]
        self.once()
        self.assertEqual(self.fake.resumes, [])
        last = [e for e in self.board.events(card) if e["kind"] == "carried"][-1]
        self.assertEqual(last["data"]["outcome"], "superseded")
        self.assertIn("moved on", last["text"])

    def test_a_relay_a_dead_drain_already_took_is_never_acted_on_again(self):
        card = self.approved()
        relay = self.board.get(card)["derived"]["relays"][0]
        self.board.carry(card, relay["id"], "drain")       # the pass that took it died here
        self.fake.rows = [background_row(card, SESSION)]    # its house is listed, so no reconcile
        self.once()
        self.assertEqual(self.fake.resumes, [])

    def test_stop_stops_the_named_house_and_says_so(self):
        card = self.approved()
        self.board.carry(card, self.board.get(card)["derived"]["relays"][0]["id"], "drain")
        self.fake.rows = [background_row(card, SESSION)]
        self.board.relay(card, "stop", "human", "mac")
        self.assertEqual(self.once()["carried"], 1)
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertIn("stopped from the deck, carried by mac", self.board.events(card)[-1]["text"])
        self.assertEqual(self.board.events(card)[-1]["data"], {"stop": "human"})
        self.assertTrue(drain.stopped_by_him(self.board, card), "the drain leaves it down (c-605)")

    def at_review(self) -> str:
        card = self.approved()
        self.board.carry(card, self.board.get(card)["derived"]["relays"][0]["id"], "drain")
        self.board.stage(card, "review", "house", plan_ref="plan.md", output_ref="out")
        patch = mock.patch.object(idleclose, "harness", self.fake)
        patch.start()
        self.addCleanup(patch.stop)
        return card

    def test_close_idle_closes_an_idle_house_and_marks_it_closed_not_stopped(self):
        """c-607: carried on the machine that holds the house, idle checked once more there."""
        card = self.at_review()
        self.fake.rows = [background_row(card, SESSION)]
        self.board.relay(card, "close-idle", "human", "mac")
        self.assertEqual(self.once()["carried"], 1)
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        last = self.board.events(card)[-1]
        self.assertIn("closed while idle: your answer at the gate or your Resume brings it back", last["text"])
        self.assertIn("carried by mac", last["text"])
        self.assertEqual(last["data"], {"stop": "idle"})
        self.assertFalse(drain.stopped_by_him(self.board, card))
        self.assertTrue(drain.closed_while_idle(self.board, card))

    def test_close_idle_of_a_house_working_by_then_is_refused_with_a_note(self):
        card = self.at_review()
        self.fake.rows = [background_row(card, SESSION, status="busy")]
        self.board.relay(card, "close-idle", "human", "mac")
        self.fake.stops = []
        self.once()
        self.assertEqual(self.fake.stops, [])
        last = [e for e in self.board.events(card) if e["kind"] == "note"][-1]
        self.assertIn("was not carried on mac: the house is working", last["text"])
        self.assertFalse(drain.closed_while_idle(self.board, card))

    def test_a_failed_resume_blocks_the_card_with_the_reason(self):
        card = self.approved()
        with mock.patch.object(drain.house, "resume", side_effect=RuntimeError("no worktree")):
            self.once()
        self.assertIn("the resume the deck asked for failed on mac: no worktree",
                      self.board.get(card)["blocked_reason"])

    def test_start_runs_on_a_paused_drain_and_waits_while_the_pool_is_full(self):
        self.cfg.drain_paused = True
        card = self.board.create("personal", "retry me")
        self.board.stage(card, "assigned", "human")
        self.board.relay(card, "start", "human", "mac")
        self.cfg.houses_max = 0
        self.once()
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(len(self.board.get(card)["derived"]["relays"]), 1, "still pending")
        self.cfg.houses_max = 1
        self.assertEqual(self.once()["carried"], 1)
        self.assertEqual(len(self.fake.starts), 1)
        self.assertEqual(self.board.get(card)["stage"], "building")
        self.assertEqual(self.board.get(card)["derived"]["relays"], [])

    def test_a_start_the_normal_pass_already_made_is_superseded(self):
        card = self.board.create("personal", "retry me")
        self.board.stage(card, "assigned", "human")
        self.board.relay(card, "start", "human", "mac")
        self.board.claim(card, "mac", "drain")
        self.board.stage(card, "building", "drain")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        self.fake.rows = [background_row(card, SESSION)]
        self.once()
        self.assertEqual(self.fake.starts, [])
        last = [e for e in self.board.events(card) if e["kind"] == "carried"][-1]
        self.assertIn("no longer waiting to start", last["text"])


class StreamShapeTest(unittest.TestCase):
    def test_a_record_whose_message_is_text_is_read_past(self):
        from keel import relay as relay_module
        stream = '{"type": "user", "message": "Claude requested permissions to use a tool"}\n{"type": "result", "result": "no"}'
        self.assertEqual(relay_module.relay_sends(stream), ([], {}, "no"))


class CallerSessionTest(unittest.TestCase):
    """c-600: a relay never runs as the Claude Code session that started the drain."""

    def test_the_caller_s_session_identity_is_not_handed_on(self):
        from keel import relay as relay_module
        env = {"PATH": "/bin", "CLAUDE_CONFIG_DIR": "/c", "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/x.sock",
               "CLAUDE_CODE_SESSION_ID": "s", "CLAUDECODE": "1", "CLAUDE_JOB_DIR": "/j"}
        self.assertEqual(relay_module.relay_env(env), {"PATH": "/bin", "CLAUDE_CONFIG_DIR": "/c"})


if __name__ == "__main__":
    unittest.main()
