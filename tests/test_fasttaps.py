"""Fast taps (c-598): the kick, a tap told to the house in its own session, and a tap for a
working house held on the board until its turn ends. The harness facts behind each are in
`keel/tellhouse.py` and `keel/kick.py` (probed on 2.1.285)."""

import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, drain, ending, house, kick, planask, prompts, tellhouse
from keel.board import Board
from tests.helpers import SESSION, FakeHarness, FakeMachine, background_row, make_config
from tests.test_cli import KbCase


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.host = "mac"


# ----- the kick -----

class KickTest(TmpCase):
    def inbox(self):
        inbox = kick.Inbox.open(self.cfg)
        self.assertIsNotNone(inbox)
        self.addCleanup(inbox.close)
        return inbox

    def test_a_kick_wakes_the_inbox_and_every_queued_kick_is_taken_at_once(self):
        inbox = self.inbox()
        self.assertFalse(inbox.wait(0))
        self.assertTrue(kick.local(self.cfg))
        self.assertTrue(kick.local(self.cfg))
        self.assertTrue(inbox.wait(1))
        self.assertFalse(inbox.wait(0), "both kicks were one wake")

    def test_no_drain_listening_is_a_quiet_false_and_a_stale_socket_is_replaced(self):
        self.assertFalse(kick.local(self.cfg))
        kick.socket_path(self.cfg).write_text("stale")
        inbox = self.inbox()
        self.assertTrue(kick.local(self.cfg))
        self.assertTrue(inbox.wait(1))

    def test_host_kicks_this_machine_s_drain_and_never_raises(self):
        self.assertEqual(kick.host(self.cfg, "mac"), "no drain listening")
        self.inbox()
        self.assertEqual(kick.host(self.cfg, "mac"), "kicked")
        self.assertEqual(kick.host(self.cfg, None), "no host")

    def test_only_a_verb_that_wrote_a_relay_kicks(self):
        ns = types.SimpleNamespace
        self.assertEqual(kick.relayed_to(ns(verb="relay", to="mac")), "mac")
        self.assertEqual(kick.relayed_to(ns(verb="approve", relay="go", to="mac")), "mac")
        self.assertEqual(kick.relayed_to(ns(verb="stage", relay="go", to="mac")), "mac")
        self.assertIsNone(kick.relayed_to(ns(verb="stage", relay=None, to=None)))
        self.assertIsNone(kick.relayed_to(ns(verb="note")))

    def test_the_stop_kicks_only_for_a_pending_relay(self):
        inbox = self.inbox()
        here = {"derived": {"relays": [{"id": 1, "to": "box"}]}}     # an old name is this machine
        self.assertFalse(kick.after_stop(self.cfg, {"derived": {"relays": []}}))
        self.assertFalse(inbox.wait(0))
        self.assertTrue(kick.after_stop(self.cfg, here))
        self.assertTrue(inbox.wait(1))

class KbKickTest(KbCase):
    def test_kb_relay_kicks_the_host_it_names_and_a_plain_verb_does_not(self):
        card = self.create()
        with mock.patch.object(kick, "host", return_value="kicked") as kicked:
            code, _, err = self.kb("relay", card, "resume", "--to", "mac", "--prompt", "go",
                                   env={"KEEL_TOKEN": self.token})
            self.assertEqual(code, 0, err)
            self.kb("note", card, "hello", env={"KEEL_TOKEN": self.token})
        self.assertEqual([c.args[1] for c in kicked.call_args_list], ["mac"])

    def test_a_refused_relay_kicks_nobody(self):
        card = self.create()
        with mock.patch.object(kick, "host") as kicked:
            code, _, _ = self.kb("relay", card, "resume", "--to", "mac")     # no token
        self.assertEqual(code, 1)
        kicked.assert_not_called()


class TurnEndKickTest(TmpCase):
    def run_main(self, decision):
        board = mock.Mock()
        board.get.return_value = {"id": "c-1", "derived": {"relays": [{"id": 1, "to": "mac"}]}}
        with mock.patch.object(ending.config_module, "load", return_value=self.cfg), \
                mock.patch.object(ending, "open_board", return_value=board), \
                mock.patch.object(ending, "check", return_value=decision), \
                mock.patch.object(ending, "read_payload", return_value={}), \
                mock.patch.object(kick, "local", return_value=True) as local, \
                mock.patch("sys.stdout"):
            self.assertEqual(ending.main(["c-1"]), 0)
        return local

    def test_a_turn_that_ends_kicks_this_machines_drain_for_its_held_tap(self):
        self.run_main(None).assert_called_once_with(self.cfg)

    def test_a_turn_the_hook_sends_back_does_not_kick(self):
        self.run_main({"decision": "block", "reason": "record"}).assert_not_called()


# ----- the drain: tell, fall back, hold -----

class CarryCase(TmpCase):
    def setUp(self):
        super().setUp()
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        self.fake.stops = []
        for module in (drain, house):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(drain, "machine", FakeMachine())
        patch.start()
        self.addCleanup(patch.stop)

    def once(self):
        return drain.once(self.cfg, board=self.board)

    def approved(self) -> str:
        """A card whose plan the box approved, with its house idle at the gate on the Mac."""
        card = self.board.create("personal", "an errand", autonomy="attended")
        self.board.stage(card, "assigned", "human")
        self.board.claim(card, "mac", "drain")
        self.board.stage(card, "planning", "drain", plan_ref="plan.md")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8], app_link="https://app/1")
        self.board.approve(card, "plan", "human", relay={"prompt": prompts.approve("plan.md"), "to": "mac"})
        return card

    def pending(self, card):
        return self.board.get(card)["derived"]["relays"]

    def carried(self, card):
        return [e for e in self.board.events(card) if e["kind"] == "carried"]


class TellTest(CarryCase):
    def test_an_idle_house_is_told_in_its_own_session_with_a_pointer_to_his_words(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="idle")]
        self.fake.relay_answer = "sent"
        summary = self.once()
        self.assertEqual(summary["carried"], 1)
        self.assertEqual((self.fake.resumes, self.fake.stops), ([], []), "no copy, no stop")
        [sent] = self.fake.relays
        self.assertIn(f"to: {card}\nmessage:\n", sent["argv"][-1])
        told = next(Path(self.cfg.card_dir(card), "told").glob("*.md"))
        self.assertIn(str(told), sent["argv"][-1])
        self.assertNotIn(prompts.approve("plan.md"), sent["argv"][-1], "his words never ride the relay")
        self.assertEqual(told.read_text().strip(), prompts.approve("plan.md").strip())
        after = self.board.get(card)
        self.assertEqual((after["session_id"], after["options"].get("app_link")), (SESSION, "https://app/1"))
        kinds = [e["kind"] for e in self.board.events(card)]
        self.assertLess(kinds.index("carried"), kinds.index("resume"), "marked before it acts")
        self.assertEqual(self.pending(card), [])
        self.once()
        self.assertEqual(len(self.fake.relays), 1, "carried at most once")

    def test_a_tell_that_certainly_failed_falls_back_to_the_resume(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="idle")]
        self.fake.relay_answer = "failed"
        self.once()
        self.assertEqual(len(self.fake.relays), 1)
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.fake.resumes[0]["prompt"], prompts.approve("plan.md"))
        self.assertTrue(any("resumed instead" in (e["text"] or "") for e in self.board.events(card)))

    def test_an_exited_house_is_resumed_and_no_message_is_sent(self):
        card = self.approved()
        self.fake.rows = []
        self.fake.relay_answer = "sent"
        self.once()
        self.assertEqual(getattr(self.fake, "relays", []), [])
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.pending(card), [])

    def test_a_tell_that_may_have_arrived_is_noted_and_never_sent_again(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="idle")]
        self.fake.relay_answer = "unclear"
        self.once()
        self.once()
        self.assertEqual((len(self.fake.relays), self.fake.resumes), (1, []))
        self.assertIn("may not have arrived", [e for e in self.board.events(card) if e["kind"] == "note"][-1]["text"])
        self.assertEqual(self.pending(card), [])


class HoldTest(CarryCase):
    def test_a_tap_for_a_working_house_is_held_on_the_board_then_told_once_when_idle(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="busy")]
        self.fake.relay_answer = "sent"
        notes = len([e for e in self.board.events(card) if e["kind"] == "note"])
        summary = self.once()
        self.assertEqual((summary.get("carried"), summary["held"]), (None, 1))
        self.assertEqual(len(self.pending(card)), 1, "held: still pending, not carried")
        self.assertEqual(self.carried(card), [])
        self.assertEqual(len([e for e in self.board.events(card) if e["kind"] == "note"]), notes,
                         "never dropped to a note")
        self.assertEqual((getattr(self.fake, "relays", []), self.fake.resumes, self.fake.stops), ([], [], []))
        self.once()
        self.assertEqual(len(self.pending(card)), 1, "held as long as it works")
        self.fake.rows = [background_row(card, SESSION, status="idle")]    # its turn ended
        self.assertEqual(self.once()["carried"], 1)
        self.assertEqual(len(self.fake.relays), 1)
        self.assertEqual([e["data"]["outcome"] for e in self.carried(card)], ["taken"])
        self.once()
        self.assertEqual(len(self.fake.relays), 1, "at most once")

    def test_a_held_card_is_not_hidden_from_the_rest_of_the_pass(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="busy")]
        gate = drain.MemoryGate(self.cfg)
        done = drain.carry_relays(self.cfg, self.board, self.fake.rows, {"personal"}, gate)
        self.assertEqual(done["ids"], set())
        self.assertEqual(len(done["held"]), 1)

    def test_a_second_tap_in_the_same_pass_waits_for_the_turn_the_first_started(self):
        card = self.approved()
        self.board.relay(card, "resume", "human", "mac", prompt="and another thing")
        self.fake.rows = [background_row(card, SESSION, status="idle")]
        self.fake.relay_answer = "sent"
        summary = self.once()
        self.assertEqual((summary["carried"], summary["held"]), (1, 1))
        self.assertEqual([r["prompt"] for r in self.pending(card)], ["and another thing"])

    def test_two_drains_carry_one_tap_once(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="idle")]
        self.fake.relay_answer = "sent"
        relay = self.pending(card)[0]
        self.board.carry(card, relay["id"], "drain")          # the other drain took it first
        self.once()
        self.assertEqual((getattr(self.fake, "relays", []), self.fake.resumes), ([], []))

    def test_a_house_in_his_terminal_is_noted_as_before(self):
        card = self.approved()
        self.fake.rows = [dict(background_row(card, SESSION, status="idle"), kind="interactive")]
        self.fake.relay_answer = "sent"
        self.once()
        self.assertEqual(getattr(self.fake, "relays", []), [])
        self.assertIn("open in a terminal", self.board.events(card)[-1]["text"])


class KickPassTest(CarryCase):
    def test_a_kick_pass_carries_the_relays_and_says_how_many_are_held(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="busy")]
        with mock.patch.object(drain, "open_board", return_value=self.board), \
                mock.patch.object(self.board, "close"):
            self.assertEqual(drain.carry_pass(self.cfg), 1)
            self.fake.rows = [background_row(card, SESSION, status="idle")]
            self.fake.relay_answer = "sent"
            self.assertEqual(drain.carry_pass(self.cfg), 0)
        self.assertEqual(len(self.fake.relays), 1)
        self.assertIn("kick: carried=1", (self.cfg.logs_dir / "drain.log").read_text())


class ListenerTest(TmpCase):
    """`kick.Listener`'s rounds on a fake inbox: the held-retry rule `drain.rest` had (c-598)."""

    def rounds(self, kicks, held, count):
        waits, passes = [], []

        class Inbox:
            def wait(self, seconds):
                waits.append(seconds)
                return kicks.pop(0) if kicks else False

        def carry():
            passes.append(len(waits))
            return held.pop(0) if held else 0

        listener = kick.Listener(Inbox(), carry, lambda: None)
        for _ in range(count):
            listener.round()
        return waits, passes

    def test_no_kick_carries_nothing(self):
        self.assertEqual(self.rounds([], [], 3), ([1, 1, 1], []))

    def test_a_kick_carries_at_once_and_a_held_tap_is_tried_again_every_two_seconds(self):
        waits, passes = self.rounds([True], [1, 1, 0], 5)
        self.assertEqual(passes, [1, 2, 3])
        self.assertEqual(waits, [1, 2, 2, 1, 1], "the plain wait once nothing is held")

    def test_the_retries_stop_after_five(self):
        _, passes = self.rounds([True], [1] * 20, 20)
        self.assertEqual(len(passes), 1 + kick.HOLD_RETRIES)


class KickDuringPassTest(TmpCase):
    """c-608: a kick is carried while a slow pass runs, not after it (c-567's 75 s wait)."""

    def test_a_kick_during_a_slow_pass_is_carried_before_that_pass_ends(self):
        carried = threading.Event()
        seen = []

        def slow_pass(cfg):
            self.assertTrue(kick.local(cfg), "the drain's inbox is listening")
            seen.append(carried.wait(5))      # the pass blocks until the kick is carried
            return {"houses": 0, "reviews": 0, "resumed": 0, "blocked": 0, "started": 0,
                    "paused": False}

        def carry_pass(cfg):
            carried.set()
            return 0

        with mock.patch.object(drain, "once", side_effect=slow_pass), \
                mock.patch.object(drain, "carry_pass", side_effect=carry_pass), \
                mock.patch.object(drain, "rest", side_effect=KeyboardInterrupt), \
                mock.patch.object(drain, "announce"), \
                mock.patch.object(drain.merging, "code_head", return_value="a930320"), \
                mock.patch.object(drain, "code_moved", return_value=False):
            with self.assertRaises(KeyboardInterrupt):
                drain.run(self.cfg)
        self.assertEqual(seen, [True])
        self.assertFalse(any(t.name == "kick" for t in threading.enumerate()),
                         "the kick thread stops with the loop")
        self.assertFalse(kick.socket_path(self.cfg).exists())


# ----- the deck on the house's own machine -----

class LocalHoldTest(TmpCase):
    def card(self, board, busy_session=SESSION):
        card = board.create("personal", "here", autonomy="attended")
        board.set_session(card, busy_session, "drain", bg_id=busy_session[:8])
        return board.get(card)

    def test_hold_here_writes_a_resume_relay_for_this_very_host(self):
        with mock.patch.object(actions, "run_kb") as run_kb:
            answer = actions.hold_here(self.cfg, {"id": "c-9"}, "his words")
        run_kb.assert_called_once_with(self.cfg, ["relay", "c-9", "resume", "--to", "mac", "--held",
                                                  "--prompt", "his words"])
        with mock.patch.object(actions, "run_kb") as run_kb:
            actions.hold_here(self.cfg, {"id": "c-9"}, "approved", gate=True)
        self.assertIn("--gate", run_kb.call_args.args[1], "c-604 review: a gate's tap says so")
        self.assertTrue(answer["held"])
        self.assertIn("when its turn ends", answer["note"])

    def test_a_gate_answer_to_a_working_house_here_is_held_not_dropped(self):
        with Board(self.cfg.db_path) as board:
            card = self.card(board)
            busy = house.Busy("working right now")
            with mock.patch.object(actions, "resume_with", side_effect=busy), \
                    mock.patch.object(actions, "hold_here", return_value={"note": "held", "held": True}) as held:
                answer = actions.gate_answer(self.cfg, board, card["id"], "approved")
            held.assert_called_once()
            self.assertEqual(held.call_args.args[2], "approved")
            self.assertTrue(held.call_args.kwargs.get("gate"))
            self.assertTrue(answer["held"])

    def test_a_gate_answer_to_his_terminal_is_still_only_noted(self):
        with Board(self.cfg.db_path) as board:
            card = self.card(board)
            with mock.patch.object(actions, "resume_with", side_effect=house.InTerminal("open in a terminal")), \
                    mock.patch.object(actions, "hold_here") as held:
                answer = actions.gate_answer(self.cfg, board, card["id"], "approved")
            held.assert_not_called()
            self.assertIn("open in a terminal", answer["note"])

    def test_an_ask_to_a_working_house_with_no_open_question_is_held(self):
        with Board(self.cfg.db_path) as board:
            card = board.create("personal", "here", autonomy="attended")
            board.stage(card, "assigned", "human")
            board.stage(card, "planning", "drain", plan_ref="plan.md")
            board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
            held = mock.Mock(return_value={"relayed": "resume", "held": True, "note": "held"})
            run_kb = mock.Mock(side_effect=lambda cfg, argv: {
                "event": board.mark(card, json.loads(argv[2].removeprefix("--data=")), "human")})
            with mock.patch.object(planask, "working", return_value=planask.HOLD):
                answer = planask.ask(self.cfg, board, {"id": card, "text": "why?"}, run_kb=run_kb,
                                     gate_of=lambda c: "plan", hold=held)
            self.assertTrue(answer["held"])
            self.assertIn("why?", held.call_args.args[2])


class TellHouseUnitTest(CarryCase):
    def test_a_voice_held_or_exited_house_goes_the_resume_path(self):
        card = self.approved()
        self.fake.rows = []
        self.fake.relay_answer = "sent"
        result = tellhouse.deliver(self.cfg, self.board, card, "go")
        self.assertNotIn("told", result)
        self.assertEqual(len(self.fake.resumes), 1)

    def test_busy_refuses_unless_the_caller_already_took_the_relay(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="busy")]
        self.fake.relay_answer = "sent"
        with self.assertRaises(house.Busy):
            tellhouse.deliver(self.cfg, self.board, card, "go")
        result = tellhouse.deliver(self.cfg, self.board, card, "go", when_busy=tellhouse.TELL)
        self.assertTrue(result["told"])

    def test_the_relay_runs_in_the_houses_config_dir_without_a_card(self):
        card = self.approved()
        self.fake.rows = [background_row(card, SESSION, status="idle")]
        self.fake.relay_answer = "sent"
        with mock.patch.dict("os.environ", {"KEEL_CARD": "c-7"}):
            tellhouse.deliver(self.cfg, self.board, card, "go")
        env = self.fake.relays[0]["env"]
        self.assertNotIn("KEEL_CARD", env)
        self.assertEqual(env.get("CLAUDE_CONFIG_DIR"), str(self.cfg.spaces["personal"].config_dir))


# ----- the review (c-598 review) -----

class ReviewTest(CarryCase):
    def idle(self, card, session=SESSION):
        return background_row(card, session, status="idle")

    def test_an_unclear_tell_is_recorded_so_the_quiet_rule_catches_a_house_that_never_took_it(self):
        card = self.approved()
        self.board.carry(card, self.pending(card)[0]["id"], "drain")      # the drain took it
        self.board.record_hook(card, "Stop", {"session_id": SESSION})     # its last turn ended
        self.fake.rows = [self.idle(card)]
        self.fake.relay_answer = "unclear"
        result = tellhouse.deliver(self.cfg, self.board, card, "go")
        self.assertEqual(result["told"], tellhouse.UNCLEAR)
        self.assertIn("tap Resume", result["note"])
        self.assertIn("tap Resume", [e for e in self.board.events(card) if e["kind"] == "note"][-1]["text"])
        later = drain.now() + drain.timedelta(hours=2)
        stuck = drain.idle_stuck(self.cfg, self.board, self.board.get(card), self.fake.rows, at=later)
        self.assertIsNotNone(stuck, "a house that never took the turn is the quiet rule's")
        self.assertTrue(stuck["due"])
        self.assertEqual((len(self.fake.relays), self.fake.resumes), (1, []), "never sent twice")

    def test_a_failure_after_the_send_is_never_a_second_delivery(self):
        card = self.approved()
        self.fake.rows = [self.idle(card)]
        self.fake.relay_answer = "sent"
        with mock.patch.object(self.board, "record_resume", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                tellhouse.deliver(self.cfg, self.board, card, "go")
        self.assertEqual((len(self.fake.relays), self.fake.resumes), (1, []))

    def test_the_relay_runs_without_the_card_lock_and_his_tap_returns_at_once(self):
        import fcntl
        import threading
        card = self.approved()
        self.fake.rows = [self.idle(card)]
        self.fake.relay_answer = "sent"
        release, seen = threading.Event(), {}
        real_run = self.fake.run

        def run(argv, **kwargs):
            with open(self.cfg.state_dir / "locks" / f"card-{card}.lock", "a") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    seen["lock_free"] = True
                    fcntl.flock(handle, fcntl.LOCK_UN)
                except BlockingIOError:
                    seen["lock_free"] = False
            release.wait(10)
            return real_run(argv, **kwargs)

        with mock.patch.object(self.fake, "run", side_effect=run):
            result = tellhouse.deliver(self.cfg, self.board, card, "go", background=True)
            self.assertEqual(result["told"], tellhouse.SENDING, "answered before the relay ended")
            release.set()
            tellhouse.join(10)
        self.assertTrue(seen["lock_free"])
        self.assertEqual([e["kind"] for e in self.board.events(card)][-1], "resume")

    def test_the_drain_tells_different_cards_side_by_side(self):
        import threading
        import time
        first = self.approved()
        other = "bbbbbbbb-0000-4000-8000-000000000009"
        second = self.board.create("personal", "another", autonomy="attended")
        self.board.stage(second, "assigned", "human")
        self.board.claim(second, "mac", "drain")
        self.board.stage(second, "planning", "drain", plan_ref="plan.md")
        self.board.set_session(second, other, "drain", bg_id=other[:8])
        self.board.approve(second, "plan", "human", relay={"prompt": "go", "to": "mac"})
        self.fake.rows = [self.idle(first), self.idle(second, other)]
        self.fake.relay_answer = "sent"
        lock, now, peak = threading.Lock(), [0], [0]
        real_run = self.fake.run

        def run(argv, **kwargs):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.3)
            with lock:
                now[0] -= 1
            return real_run(argv, **kwargs)

        with mock.patch.object(self.fake, "run", side_effect=run):
            self.assertEqual(self.once()["carried"], 2)
        self.assertEqual(peak[0], 2)
        for card in (first, second):
            self.assertEqual([e["kind"] for e in self.board.events(card)][-1], "resume")

    def test_two_live_sessions_of_the_cards_name_are_said_plainly_and_nothing_is_minted(self):
        card = self.approved()
        stale = "cccccccc-0000-4000-8000-000000000003"
        self.fake.rows = [self.idle(card), dict(self.idle(card, stale), pid=2)]
        self.fake.relay_answer = "sent"
        self.once()
        self.assertEqual((getattr(self.fake, "relays", []), self.fake.resumes, self.fake.stops), ([], [], []))
        said = " ".join(e["text"] or "" for e in self.board.events(card) if e["kind"] == "note")
        self.assertIn(SESSION, said)
        self.assertIn(stale, said)
        self.assertIn("Stop the stale one", said)


class ReviewKickTest(TmpCase):
    def test_a_second_drain_never_steals_the_inbox(self):
        first = kick.Inbox.open(self.cfg)
        self.addCleanup(first.close)
        self.assertIsNone(kick.Inbox.open(self.cfg))
        self.assertTrue(kick.local(self.cfg))
        self.assertTrue(first.wait(1), "the first drain still hears its kicks")

    def test_a_card_keeps_only_its_newest_told_files(self):
        folder = Path(self.tmp.name) / "c-1"
        folder.mkdir()
        for n in range(tellhouse.TOLD_KEEP + 3):
            tellhouse.write_prompt(folder, f"prompt {n}")
        kept = sorted((folder / tellhouse.TOLD_DIR).glob("*.md"))
        self.assertEqual(len(kept), tellhouse.TOLD_KEEP)
        self.assertIn(f"prompt {tellhouse.TOLD_KEEP + 2}", " ".join(p.read_text() for p in kept))


if __name__ == "__main__":
    unittest.main()
