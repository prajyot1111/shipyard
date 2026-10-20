"""Harbor knows Bosun (c-523, BO-5): the voice hold on Bosun, "put me through to Bosun",
Bosun in the digest, and an answer to an ask recorded by voice through the page.

Nothing here starts a Claude session. The hold's order (stop, a headless turn, a flagless
wake keeping the id and the app link) was probed on 2.1.283 by hand:
`state/cards/c-523/probe/README.md`.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import (actions, bosuntalk, config as config_module, console, consoletaps, deckdigest,
                  drain, housetier, requests)
from keel.board import Board, Refused
from tests.helpers import give_bosun_key
from tests.test_console import SESSION, console_toml
from tests.test_requests import RequestKbCase
from tests.test_voice_connect import ask_harbormsg, ask_verbs


class BoardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Board(Path(self.tmp.name) / "board.db")
        self.addCleanup(self.board.close)


class HoldTest(BoardCase):
    def test_taken_refreshed_and_released_like_a_card_s(self):
        first = self.board.hold_bosun("voice", 300, stopped=True)
        again = self.board.hold_bosun("voice", 300, stopped=False, turns=2)
        self.assertEqual(again["at"], first["at"], "`at` names the hold and is set once")
        self.assertIs(again["stopped"], True, "`stopped` is what the first open recorded")
        self.assertEqual(self.board.bosun_hold()["turns"], 2)
        self.assertEqual(self.board.release_bosun("voice")["stopped"], True)
        self.assertIsNone(self.board.bosun_hold())

    def test_one_that_ran_out_is_no_hold_but_is_there_to_clear(self):
        self.board.hold_bosun("voice", -5, stopped=True)
        self.assertIsNone(self.board.bosun_hold())
        self.assertEqual(self.board.bosun_hold_expired()["stopped"], True)

    def test_a_house_and_bosun_may_not_hold_it(self):
        for actor in ("house", "bosun", "cli"):
            with self.assertRaises(Refused):
                self.board.hold_bosun(actor, 300)
        self.assertIsNone(self.board.bosun_hold())


class HoldKbTest(RequestKbCase):
    def test_the_verbs_read_take_and_release_it(self):
        self.assertEqual(self.kb_json("console", "held"), {"hold": None, "expired": None})
        held = self.kb_json("--actor", "voice", "console", "hold", "--seconds", "60",
                            "--stopped", "yes")["hold"]
        self.assertIs(held["stopped"], True)
        self.assertIs(self.kb_json("console", "held")["hold"]["stopped"], True)
        self.kb_json("--actor", "voice", "console", "hold", "--release")
        self.assertIsNone(self.kb_json("console", "held")["hold"])

    def test_bosun_may_not_hold_itself(self):
        code, _, err = self.as_bosun("console", "hold")
        self.assertEqual(code, 1)
        self.assertIn("not bosun's", err)

    def test_the_wire_carries_the_hold(self):
        self.assertEqual(requests.argv({"sub": "hold", "seconds": 60, "stopped": "no",
                                        "release": True}),
                         ["console", "hold", "--seconds=60", "--stopped=no", "--release"])
        self.assertIn("held", actions.CONSOLE_READS)


def bosun_cfg(tmp: Path):
    cfg = config_module.load(console_toml(tmp), ensure=False)
    give_bosun_key(Path(os.environ.get("HOME", tmp)))
    return cfg


class BoxHalfTest(BoardCase):
    """`keel converse bosun` where the board is: the hold, then the open."""

    def setUp(self):
        super().setUp()
        self.cfg = config_module.load(console_toml(Path(self.tmp.name)), ensure=False)

    def open_as(self, opened):
        return mock.patch.object(housetier, "open_session", return_value=opened)

    def test_a_connect_holds_bosun_and_records_what_the_open_stopped(self):
        with self.open_as(housetier.Opened(True, stopped=True)) as opened:
            said = bosuntalk.connect(self.cfg, self.board)
        self.assertEqual((said["ok"], said["card"], said["space"]), (True, "bosun", "console"))
        self.assertEqual(opened.call_args[0][1]["id"], "bosun", "the pseudo card names Bosun")
        self.assertIs(self.board.bosun_hold()["stopped"], True)

    def test_each_refusal_gives_the_hold_back_and_is_a_sentence(self):
        cases = {housetier.BUSY: bosuntalk.BUSY, bosuntalk.TYPING: bosuntalk.SAID_TYPING,
                 housetier.UNREACHED: "This machine is away, so I cannot reach Bosun."}
        for code, sentence in cases.items():
            with self.open_as(housetier.Opened(False, refused=code)):
                said = bosuntalk.connect(self.cfg, self.board)
            self.assertEqual((said["ok"], said["say"]), (False, sentence))
            self.assertIsNone(self.board.bosun_hold())
        with self.open_as(housetier.Opened(False, refused=bosuntalk.DOWN, why="stuck")):
            self.assertEqual(bosuntalk.connect(self.cfg, self.board)["say"], bosuntalk.STUCK)
        with self.open_as(housetier.Opened(False, refused=bosuntalk.DOWN, why="never")):
            self.assertEqual(bosuntalk.connect(self.cfg, self.board)["say"], bosuntalk.NEVER)
        with self.open_as(housetier.Opened(False, refused=bosuntalk.DOWN, why="stopped")):
            self.assertEqual(bosuntalk.connect(self.cfg, self.board)["say"], bosuntalk.STOPPED)

    def test_an_open_that_stopped_bosun_and_then_failed_wakes_it_again(self):
        with self.open_as(housetier.Opened(False, stopped=True, refused=housetier.REFUSED,
                                           why="the conversation would not start")), \
                mock.patch.object(housetier, "close_session") as close:
            said = bosuntalk.connect(self.cfg, self.board)
        self.assertFalse(said["ok"])
        self.assertIs(close.call_args.kwargs["wake"], True)
        self.assertIsNone(self.board.bosun_hold())

    def test_a_sentence_the_mac_refused_drops_the_pin_and_the_hold(self):
        self.board.hold_bosun("voice", 300, stopped=True)
        with mock.patch.object(housetier, "say", side_effect=housetier.Away("409")), \
                mock.patch.object(housetier, "close_session",
                                  return_value=housetier.Shut(housetier.NONE)):
            said = bosuntalk.answer(self.cfg, self.board, "hello", 60, pinned=True)
        self.assertEqual((said["say"], said["unpin"]), (bosuntalk.UNPINNED, True))
        self.assertIsNone(self.board.bosun_hold())

    def test_a_tap_that_ended_the_hold_mid_open_is_undone_there(self):
        def opened(*_args, **_kw):
            self.board.release_bosun("human")        # his Start, while the open was out
            return housetier.Opened(True, stopped=True)
        with mock.patch.object(housetier, "open_session", side_effect=opened), \
                mock.patch.object(housetier, "close_session") as close:
            said = bosuntalk.connect(self.cfg, self.board)
        self.assertEqual(said["say"], bosuntalk.UNPINNED)
        self.assertIs(close.call_args.kwargs["wake"], True)
        self.assertIsNone(self.board.bosun_hold())

    def test_a_pinned_turn_whose_hold_went_is_told_to_unpin(self):
        said = bosuntalk.answer(self.cfg, self.board, "hello", 60, pinned=True)
        self.assertEqual((said["ok"], said.get("unpin")), (False, True))

    def test_a_turn_counts_itself_on_the_hold(self):
        self.board.hold_bosun("voice", 300, stopped=True)
        with mock.patch.object(housetier, "say", return_value={"result": "The drain is fine."}):
            said = bosuntalk.answer(self.cfg, self.board, "how is the drain", 60, pinned=True)
        self.assertEqual((said["say"], said["turns"]), ("The drain is fine.", 1))
        self.assertEqual(self.board.bosun_hold()["turns"], 1)

    def test_back_to_harbor_wakes_bosun_only_when_voice_stopped_it(self):
        for stopped in (True, False):
            self.board.hold_bosun("voice", 300, stopped=stopped)
            with mock.patch.object(housetier, "close_session",
                                   return_value=housetier.Shut(housetier.CLOSED, stopped)) as close:
                bosuntalk.release(self.cfg, self.board)
            self.assertIs(close.call_args.kwargs["wake"], stopped)
            self.assertIsNone(self.board.bosun_hold())

    def test_a_machine_that_is_away_keeps_the_hold_for_its_drain(self):
        self.board.hold_bosun("voice", 300, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.AWAY)):
            said = bosuntalk.release(self.cfg, self.board)
        self.assertEqual((said["say"], said["away"]), ("Back to Harbor.", True))
        self.assertIsNotNone(self.board.bosun_hold_expired(), "kept, run out, for its drain")

    def test_the_verb_routes_bosun_to_it(self):
        from keel import converse
        args = converse.build_parser().parse_args(["bosun", "--connect"])
        with mock.patch.object(bosuntalk, "connect", return_value={"ok": True}) as connect:
            converse.run(self.cfg, self.board, args)
        connect.assert_called_once()


class MacHalfCase(BoardCase):
    """Bosun's session and key on a scratch home; no tests of its own."""

    def setUp(self):
        super().setUp()
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = config_module.load(console_toml(Path(self.tmp.name)), ensure=False)
        self.key = give_bosun_key(home)
        console.write_state(self.cfg, {"session_id": SESSION, "bg_id": SESSION[:8]})


class MacHalfTest(MacHalfCase):
    """In the `keel serve` of Bosun's machine: the plan, the guards, the wake."""

    def test_no_plan_without_the_hold(self):
        with self.assertRaises(Refused):
            bosuntalk.door_plan(self.cfg, self.board)

    def test_the_plan_is_bosun_s_own_session_with_its_key_and_no_card(self):
        self.board.hold_bosun("voice", 300)
        made = bosuntalk.door_plan(self.cfg, self.board)
        self.assertEqual((made["card"], made["session_id"], made["bosun"]), ("bosun", SESSION, True))
        # c-553: the key rides in its settings (read by a `-p` turn as by a `--bg` session)
        self.assertNotIn(console.BOSUN_ENV, made["env"])
        self.assertNotIn("KEEL_CARD", made["env"])
        self.assertTrue(made["settings_path"].endswith("credentials/bosun-settings.json"))
        settings = json.loads(Path(made["settings_path"]).read_text())
        self.assertEqual(settings["env"][console.BOSUN_ENV], self.key)

    def guard(self, row=None, last_turn=None, released=None):
        data = dict(console.read_state(self.cfg), voice_released_at=released)
        console.write_state(self.cfg, data)
        made = {"session_id": SESSION}
        with mock.patch.object(console, "running_row", return_value=row), \
                mock.patch.object(console, "transcript_of", return_value=Path("t")), \
                mock.patch.object(console, "tail_records",
                                  return_value=[{"timestamp": last_turn}] if last_turn else []):
            return bosuntalk.ready(self.cfg, made)

    def test_the_guards_only_bosun_has(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(seconds=30)).isoformat()
        old = (now - timedelta(minutes=10)).isoformat()
        idle = {"status": "idle", "pid": 1, "sessionId": SESSION}
        self.assertEqual(bosuntalk.ready(self.cfg, {"session_id": ""}), (bosuntalk.DOWN, "never"))
        self.assertEqual(self.guard({"sessionId": SESSION}), (bosuntalk.DOWN, "stuck"))
        self.assertEqual(self.guard(dict(idle, status="busy")), (housetier.BUSY, ""))
        self.assertEqual(self.guard(idle, recent), (bosuntalk.TYPING, ""))
        self.assertIsNone(self.guard(idle, old))
        self.assertIsNone(self.guard(idle, recent, released=now.isoformat()),
                          "a turn voice itself took is not him typing in the app")
        self.assertEqual(self.guard(None, recent), (bosuntalk.DOWN, "stopped"),
                         "voice only ever holds a Bosun it stopped itself")

    def test_the_wake_is_flagless_under_its_own_environment_and_follows_a_new_id(self):
        with mock.patch.object(bosuntalk.harness, "wake",
                               return_value={"bg_id": "e40ffe2f", "session_id": SESSION}) as wake:
            bosuntalk.wake(self.cfg)
        # a flagless resume keeps the session's own --settings, which carry the key (c-553)
        self.assertNotIn(console.BOSUN_ENV, wake.call_args.kwargs["env"])
        self.assertEqual(console.read_state(self.cfg)["session_id"], SESSION)
        other = "f50ffe2f-60a6-4141-b3ef-62abdd02aadc"
        with mock.patch.object(bosuntalk.harness, "wake",
                               return_value={"bg_id": "f50ffe2f", "session_id": other}):
            bosuntalk.wake(self.cfg)
        data = console.read_state(self.cfg)
        self.assertEqual((data["session_id"], data["app_link"]), (other, None))

    def test_the_journal_says_voice_came_and_went(self):
        bosuntalk.opened(self.cfg, True)
        bosuntalk.closed(self.cfg, True)
        data = console.read_state(self.cfg)
        self.assertEqual([row["what"] for row in data["history"]][-2:],
                         ["voice connected", "voice released; Bosun is awake again"])
        self.assertTrue(data["voice_released_at"])

    def test_a_hold_that_ran_out_is_closed_cleared_and_woken(self):
        self.board.hold_bosun("voice", -5, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.CLOSED, True)) as close:
            self.assertTrue(bosuntalk.release_expired(self.cfg, self.board))
        self.assertIs(close.call_args.kwargs["wake"], True)
        self.assertIsNone(self.board.bosun_hold_expired())

    def test_with_nobody_serving_the_drain_wakes_it_itself(self):
        self.board.hold_bosun("voice", -5, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.AWAY)), \
                mock.patch.object(bosuntalk, "wake") as wake:
            bosuntalk.release_expired(self.cfg, self.board)
        wake.assert_called_once()

    def test_the_drain_step_runs_it(self):
        with mock.patch.object(bosuntalk, "release_expired", return_value=False) as step:
            drain.bosun_hold_upkeep(self.cfg, self.board)
        step.assert_called_once()
        with mock.patch.object(bosuntalk, "release_expired", side_effect=RuntimeError("x")), \
                mock.patch.object(drain, "failed_step") as failed:
            drain.bosun_hold_upkeep(self.cfg, self.board)
        self.assertEqual(failed.call_args[0][2], "bosun voice hold", "one step, never the pass")

    def test_his_tap_ends_the_conversation_first(self):
        self.board.hold_bosun("voice", 300, stopped=True)
        with mock.patch("keel.board.open_board", return_value=self.board), \
                mock.patch.object(self.board, "close"), \
                mock.patch.object(housetier, "close_session") as close, \
                mock.patch.object(console, "running_row", return_value=None):
            self.assertTrue(bosuntalk.voice_ended(self.cfg, "stop", "human"))
        self.assertIs(close.call_args.kwargs["wake"], False)
        self.assertIsNone(self.board.bosun_hold())
        self.assertIn("voice had already stopped it", console.read_state(self.cfg)["history"][-1]["what"])

    def test_the_tap_calls_it(self):
        with mock.patch.object(bosuntalk, "voice_ended", return_value=True) as ended, \
                mock.patch.object(console, "status", return_value={"state": "stopped"}):
            consoletaps.tap(self.cfg, "stop")
        ended.assert_called_once_with(self.cfg, "stop", "human")


class DigestTest(unittest.TestCase):
    STATE = {"console": {"state": "idle", "voice": False, "last_turn": "2026-09-26T10:00:00Z",
                         "counts": {"asks": 1, "requests": 3},
                         "asks": [{"id": "a-31", "kind": "approval", "card": "c-540", "state": "open",
                                   "question": "Deploy next to main?",
                                   "options": [{"letter": "A", "label": "Yes, deploy", "does": "x"},
                                               {"letter": "B", "label": "Not yet", "does": "y"}]},
                                  {"id": "a-30", "state": "answered", "question": "old", "options": []}]}}

    def test_the_digest_carries_bosun_s_state_open_asks_and_counts(self):
        digest = deckdigest.build(deckdigest.fold(self.STATE))["bosun"]
        self.assertEqual((digest["state"], digest["asksOpen"], digest["requestsOpen"]), ("idle", 1, 3))
        self.assertEqual(digest["asks"],
                         ["a-31 approval on c-540: Deploy next to main? A Yes, deploy / B Not yet"])
        self.assertNotIn("x", json.dumps(digest["asks"]).replace("next", ""),
                         "an option's `does` is a body and never rides the digest")

    def test_on_voice_is_the_state_word_while_voice_holds_it(self):
        state = {"console": dict(self.STATE["console"], voice=True)}
        self.assertEqual(deckdigest.build(deckdigest.fold(state))["bosun"]["state"], "on voice")

    def test_keel_deck_bosun_and_the_overview(self):
        doc = deckdigest.fold(self.STATE)
        table = deckdigest.render_section(doc, "bosun")
        self.assertTrue(table.startswith("bosun: idle, 1 open asks, 3 open requests"))
        self.assertIn("a-31", table)
        self.assertIn("bosun: idle", deckdigest.overview(doc))
        self.assertIn("bosun", deckdigest.SECTIONS)

    def test_a_deck_with_no_console_says_so(self):
        doc = deckdigest.fold({})
        self.assertIsNone(deckdigest.build(doc)["bosun"])
        self.assertEqual(deckdigest.render_section(doc, "bosun"), "bosun: no console on this deck")


class VoiceAnswerTest(unittest.TestCase):
    """The page records his answer: his token stays in the deck, the actor is voice."""

    PAGE = {"verb": "console", "sub": "answer", "target": "a-31", "choice": "A",
            "words": "yes, A", "voice": True}

    def test_only_the_page_s_answer_to_an_ask_may_be_voice(self):
        self.assertTrue(actions.voice_answer(self.PAGE))
        self.assertFalse(actions.voice_answer(dict(self.PAGE, voice=False)))
        for body in (dict(self.PAGE, sub="raise"), dict(self.PAGE, verb="note"),
                     dict(self.PAGE, caller={"actor": "voice"}), dict(self.PAGE, sub="deploy")):
            with self.assertRaises(actions.ActionError):
                actions.voice_answer(body)

    def test_the_deck_runs_kb_as_voice_with_its_own_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_module.load(console_toml(Path(tmp)), ensure=False)
            done = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(actions.subprocess, "run", return_value=done) as run, \
                    mock.patch.object(actions, "kb_env", return_value={"KEEL_TOKEN": "his"}):
                actions.run_kb(cfg, ["console", "answer"], voice=True)
        argv, env = run.call_args[0][0], run.call_args.kwargs["env"]
        self.assertEqual(argv[1:3], ["--actor", "voice"])
        self.assertEqual(env["KEEL_TOKEN"], "his")


class AnswerKbTest(RequestKbCase):
    def test_a_voice_answer_with_his_token_records_the_channel_voice(self):
        aid = self.as_bosun("console", "raise", "Deploy?", "--kind", "approval", "--why", "w",
                            "--option", "Yes|deploy", "--option", "No|wait", "--json")[1]
        aid = json.loads(aid)["id"]
        row = self.kb_json("--actor", "voice", "console", "answer", aid, "A", "--words", "yes",
                           env={"KEEL_TOKEN": self.token})
        self.assertEqual((row["channel"], row["answer"], row["words"]), ("voice", "A", "yes"))


class VerbsTest(unittest.TestCase):
    """In the voice package's own interpreter."""

    def test_put_me_through_to_bosun_and_nothing_longer(self):
        self.assertEqual(ask_verbs(["verbs.connect_target('Put me through to Bosun.')",
                                    "verbs.connect_target('talk to the bosun')",
                                    "verbs.connect_target('talk to bosun about the drain')",
                                    "verbs.say_card('bosun')",
                                    "verbs.entering('bosun', 'the admin console')"]),
                         ["bosun", "bosun", "", "Bosun", "Entering Bosun, the admin console."])

    def test_the_model_may_name_bosun(self):
        self.assertEqual(ask_verbs(["verbs.connect_directive('Putting you through. "
                                    "<<keel-connect bosun ab12cd>>', 'ab12cd')"]),
                         [["Putting you through.", "bosun"]])

    def test_an_answer_directive_is_this_turn_s_and_ends_the_answer(self):
        got = ask_verbs(["verbs.answer_directive('Recording A. <<keel-answer a-31 A ab12cd>>', 'ab12cd')",
                         "verbs.answer_directive('Your words. <<keel-answer a-31 - ab12cd>>', 'ab12cd')",
                         "verbs.answer_directive('Recording A. <<keel-answer a-31 A ab12cd>>', '000000')",
                         "verbs.answer_directive('<<keel-answer a-31 A ab12cd>> and more', 'ab12cd')",
                         "verbs.answer_directive('<<keel-answer a-31 A ab12cd>>', '')"])
        self.assertEqual(got[0], ["Recording A.", ["a-31", "A"]])
        for spoken, picked in got[1:]:
            self.assertIsNone(picked)
            self.assertNotIn("keel-answer", spoken)

    def test_the_framing_teaches_bosun_only_with_a_key(self):
        line, plain = ask_harbormsg([
            "harbormsg.build_line('answer bosun', connect_key='ab12cd')",
            "harbormsg.build_line('answer bosun')"])
        self.assertIn("<<keel-answer a-31 A ab12cd>>", line)
        self.assertIn("<<keel-connect bosun ab12cd>>", line)
        self.assertIn("never pick for them", line)
        self.assertIn("Filed with Bosun as request 23.", line)
        self.assertNotIn("keel-answer", plain)


class PageTest(unittest.TestCase):
    def test_the_page_posts_only_the_answer_with_the_voice_flag(self):
        from tests.test_voice_connect import code
        source = code()
        self.assertEqual(source.count('"/api/action"'), 1)
        self.assertIn('sub: "answer"', source)
        self.assertIn("voice: true", source)

    def test_the_gateway_hands_it_to_the_page_and_records_nothing(self):
        root = Path(__file__).resolve().parent.parent
        server = (root / "voice" / "harbor_voice" / "server.py").read_text(encoding="utf-8")
        self.assertIn("answer_asked=self.answer_by_model", server)
        self.assertIn('{"type": "answer"', server)
        self.assertNotIn("\"answer\", \"--actor\"", server)
        self.assertNotIn("KEEL_TOKEN", server)


if __name__ == "__main__":
    unittest.main()


# ----- the review's findings (c-523): the hold through kb, the house tier, the deck, the dispatcher

from keel.deckstate import Deck  # noqa: E402
from tests.test_requests import LocalCase  # noqa: E402


class KbHoldTest(LocalCase):
    """His tap and the drain clear the hold voice took, on the board kb reads."""

    def local(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        return board

    def test_his_tap_clears_the_hold(self):
        self.local().hold_bosun("voice", 300, stopped=True)
        with mock.patch.object(housetier, "close_session") as close:
            held = bosuntalk.end_for_tap(self.cfg)
        self.assertIs(held["stopped"], True)
        self.assertIs(close.call_args.kwargs["wake"], False)
        self.assertIsNone(self.local().bosun_hold(), "the hold is gone, not swallowed")

    def test_the_drain_clears_one_that_ran_out(self):
        self.local().hold_bosun("voice", -5, stopped=False)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.CLOSED)):
            self.assertTrue(bosuntalk.release_expired(self.cfg, self.local()))
        self.assertIsNone(self.local().bosun_hold_expired())

    def test_the_page_s_answer_goes_through_the_deck_as_voice(self):
        aid = json.loads(self.as_bosun("console", "raise", "Deploy?", "--kind", "approval",
                                       "--why", "w", "--option", "Yes|deploy",
                                       "--option", "No|wait", "--json")[1])["id"]
        with Board(self.cfg.db_path) as board:
            actions.act(self.cfg, board, {"verb": "console", "sub": "answer", "target": aid,
                                          "choice": "B", "words": "not yet", "voice": True})
        row = self.kb_json("console", "show", aid)
        self.assertEqual((row["channel"], row["answer"], row["words"]), ("voice", "B", "not yet"))

    def test_the_voice_flag_on_a_gate_verb_is_refused(self):
        card = self.create()
        with Board(self.cfg.db_path) as board, self.assertRaises(actions.ActionError):
            actions.act(self.cfg, board, {"verb": "approve", "id": card, "gate": "plan",
                                          "voice": True})


class DoorTest(BoardCase):
    """The house tier, with a Bosun plan: the refusals only it can make."""

    def setUp(self):
        super().setUp()
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = config_module.load(console_toml(Path(self.tmp.name)), ensure=False)
        give_bosun_key(home)
        console.write_state(self.cfg, {"session_id": SESSION})
        self.replies = []
        tier = housetier.HouseTier.__new__(housetier.HouseTier)
        tier.cfg = self.cfg
        tier.reply_json = lambda code, body: self.replies.append((code, body))
        self.tier = tier
        self.made = {"card": "bosun", "bosun": True, "session_id": SESSION, "config_dir": None}

    def test_a_sentence_with_no_live_conversation_is_refused_not_reopened(self):
        with mock.patch.object(housetier, "open_board", return_value=self.board), \
                mock.patch.object(self.board, "close"):
            with self.assertRaises(Refused):
                self.tier.house_plan("bosun", fresh=False)

    def test_a_tap_in_flight_refuses_the_open(self):
        with console.held_lock(self.cfg) as held:
            self.assertTrue(held)
            self.tier.house_open(self.made, {})
        self.assertEqual(self.replies[-1][1]["error"], "a tap on Bosun is being carried out")

    def test_an_open_that_fails_after_the_stop_says_it_stopped_bosun(self):
        with mock.patch.object(self.tier, "house_ready", return_value=None), \
                mock.patch.object(housetier.housetalk, "stop_house", return_value=True), \
                mock.patch.object(housetier.SESSIONS, "open",
                                  side_effect=bosuntalk.harness.HarnessError("no")):
            self.tier.house_open(self.made, {})
        body = self.replies[-1][1]
        self.assertEqual((body["ok"], body["stopped"]), (False, True))

    def test_a_wake_that_fails_is_in_the_journal(self):
        with mock.patch.object(bosuntalk, "wake", side_effect=RuntimeError("claude exited 1")):
            self.tier.bosun_close(True, True)
        self.assertIn("waking Bosun failed", console.read_state(self.cfg)["history"][-1]["what"])
        self.assertEqual(self.replies[-1][1]["error"], "claude exited 1")


class StampTest(unittest.TestCase):
    def test_the_deck_s_revision_moves_when_the_hold_is_taken_and_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_module.load(console_toml(Path(tmp)), ensure=False)
            board = Board(cfg.db_path)
            deck = Deck(cfg)

            def stamp():
                deck.stamped_at = 0.0
                return deck.board_stamp()
            before = stamp()
            board.hold_bosun("voice", 300)
            taken = stamp()
            board.release_bosun("voice")
            released = stamp()
            board.close()
            if deck.stamp_conn is not None:
                deck.stamp_conn.close()
        self.assertNotEqual(before, taken)
        self.assertNotEqual(taken, released)


def ask_voice(lines: list[str]) -> list:
    """Run `lines` in the voice package's interpreter, with the dispatcher importable."""
    import subprocess
    import sys
    root = Path(__file__).resolve().parent.parent
    code = ("import json, sys; sys.path.insert(0, %r);"
            "from harbor_voice import dispatcher, server;" % str(root / "voice")
            + "\n".join(lines))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=dict(os.environ, KEEL_HOME=tempfile.mkdtemp()))
    if out.returncode:
        raise unittest.SkipTest("the voice package would not import: " + out.stderr[-400:])
    return json.loads(out.stdout)


class DispatcherTest(unittest.TestCase):
    """A pick is handed to the page only once the answer was spoken, never otherwise."""

    SETUP = [
        "calls = []",
        "d = dispatcher.Dispatcher.__new__(dispatcher.Dispatcher)",
        "d.answer_asked = lambda ask, letter, words: calls.append([ask, letter, words])",
        "d.connect_asked = lambda card: None",
        "d._log = lambda *a, **k: None",
        "d.pinned = lambda: ''",
        "t = dispatcher.Turn(1, 'yes, A')",
        "t.picked = ('a-31', 'A')",
    ]

    def test_spoken_is_taken_once_with_his_words(self):
        got = ask_voice(self.SETUP + ["d._take_connect(t)", "d._take_connect(t)",
                                      "print(json.dumps(calls))"])
        self.assertEqual(got, [["a-31", "A", "yes, A"]])

    def test_unheard_is_dropped_and_never_taken(self):
        got = ask_voice(self.SETUP + ["d._drop_connect(t, 'the answer is text, not audio')",
                                      "d._take_connect(t)", "print(json.dumps(calls))"])
        self.assertEqual(got, [])

    def test_the_gateway_hands_the_page_exactly_the_pick(self):
        got = ask_voice([
            "sent = []",
            "g = server.Gateway.__new__(server.Gateway)",
            "g.broadcast = lambda obj: sent.append(obj) or True",
            "g.answer_by_model('a-31', 'A', 'yes, A')",
            "print(json.dumps(sent))"])
        self.assertEqual(got, [{"type": "answer", "ask": "a-31", "choice": "A", "words": "yes, A"}])


class RoundTwoTest(BoardCase):
    """The second review's findings (c-523): a hold that ran out, a close that failed, the
    one-shot path, and a tap that ends the hold mid-turn."""

    def setUp(self):
        super().setUp()
        self.cfg = config_module.load(console_toml(Path(self.tmp.name)), ensure=False)

    def test_a_connect_over_a_hold_that_ran_out_wakes_bosun_first(self):
        self.board.hold_bosun("voice", -5, stopped=True, turns=4)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.CLOSED, True)) as close, \
                mock.patch.object(housetier, "open_session",
                                  return_value=housetier.Opened(True, stopped=True)):
            said = bosuntalk.connect(self.cfg, self.board)
        self.assertTrue(said["ok"])
        self.assertIs(close.call_args.kwargs["wake"], True, "the old conversation's stop is undone")
        held = self.board.bosun_hold()
        self.assertEqual(held["turns"], 0, "nothing of the old hold is carried")

    def test_with_its_machine_away_the_old_hold_waits_for_its_drain(self):
        self.board.hold_bosun("voice", -5, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.AWAY)), \
                mock.patch.object(housetier, "open_session") as opened:
            said = bosuntalk.connect(self.cfg, self.board)
        self.assertIn("has not closed the last voice conversation", said["say"])
        opened.assert_not_called()
        self.assertIsNotNone(self.board.bosun_hold_expired())

    def test_back_to_harbor_whose_close_failed_keeps_the_hold_for_the_drain(self):
        self.board.hold_bosun("voice", 300, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.FAILED)):
            said = bosuntalk.release(self.cfg, self.board)
        self.assertEqual((said["say"], said["failed"]), ("Back to Harbor.", True))
        self.assertIsNone(self.board.bosun_hold(), "run out at once, so no turn reads it as live")
        self.assertIs(self.board.bosun_hold_expired()["stopped"], True, "kept for the drain")

    def test_a_connect_over_one_whose_close_failed_waits_for_the_drain(self):
        self.board.hold_bosun("voice", -5, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.FAILED)), \
                mock.patch.object(housetier, "open_session") as opened:
            said = bosuntalk.connect(self.cfg, self.board)
        self.assertFalse(said["ok"])
        opened.assert_not_called()
        self.assertIs(self.board.bosun_hold_expired()["stopped"], True)

    def test_one_shot_connects_asks_and_lets_go(self):
        with mock.patch.object(housetier, "open_session",
                               return_value=housetier.Opened(True, stopped=True)), \
                mock.patch.object(housetier, "say", return_value={"result": "Idle."}), \
                mock.patch.object(housetier, "close_session",
                                  return_value=housetier.Shut(housetier.CLOSED, True)) as close:
            said = bosuntalk.answer(self.cfg, self.board, "are you busy", 60)
        self.assertEqual(said["say"], "Idle.")
        self.assertIs(close.call_args.kwargs["wake"], True)
        self.assertIsNone(self.board.bosun_hold())

    def test_one_shot_whose_turn_failed_still_lets_go(self):
        with mock.patch.object(housetier, "open_session",
                               return_value=housetier.Opened(True, stopped=True)), \
                mock.patch.object(housetier, "say",
                                  side_effect=bosuntalk.harness.HarnessError("boom")), \
                mock.patch.object(housetier, "close_session",
                                  return_value=housetier.Shut(housetier.CLOSED, True)):
            said = bosuntalk.answer(self.cfg, self.board, "are you busy", 60)
        self.assertFalse(said["ok"])
        self.assertIsNone(self.board.bosun_hold())

    def test_a_tap_mid_turn_is_not_undone_by_the_refresh(self):
        self.board.hold_bosun("voice", 300, stopped=True)

        def turn(*_args, **_kw):
            self.board.release_bosun("voice")          # his Stop, while Bosun answered
            return {"result": "Done."}
        with mock.patch.object(housetier, "say", side_effect=turn):
            said = bosuntalk.answer(self.cfg, self.board, "go on", 60, pinned=True)
        self.assertEqual((said["say"], said["unpin"]), ("Done.", True))
        self.assertIsNone(self.board.bosun_hold(), "the hold is not re-taken")


class DrainFailuresTest(MacHalfCase):
    def test_a_close_that_failed_is_in_the_journal(self):
        self.board.hold_bosun("voice", -5, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.FAILED)):
            bosuntalk.release_expired(self.cfg, self.board)
        self.assertIn("would not close", console.read_state(self.cfg)["history"][-1]["what"])

    def test_the_drain_s_own_wake_failing_is_in_the_journal(self):
        self.board.hold_bosun("voice", -5, stopped=True)
        with mock.patch.object(housetier, "close_session",
                               return_value=housetier.Shut(housetier.AWAY)), \
                mock.patch.object(bosuntalk, "wake", side_effect=RuntimeError("claude exited 1")):
            bosuntalk.release_expired(self.cfg, self.board)
        self.assertIn("waking Bosun failed", console.read_state(self.cfg)["history"][-1]["what"])


class DuplicateTest(RequestKbCase):
    def test_a_second_filing_about_the_same_card_is_said_not_refused(self):
        card = self.create()
        self.kb_json("--actor", "voice", "console", "ask", "one", "--card", card)
        row = self.kb_json("--actor", "voice", "console", "ask", "two", "--card", card)
        self.assertEqual((row["id"], row["filed"], row["say"]),
                         ("r-1", False, "Bosun already has that as request 1."))
        self.assertEqual(len(self.kb_json("console", "list")["requests"]), 1)
