"""The ask box: a question typed under the stage (K11).

What is held here:

1. **The answer is polled, never waited for.** The POST comes back with a turn id while the
   turn is still running, and the turn always settles, including when it raised.
2. **One question per board at a time.** A second Send while one is in flight is refused
   with a sentence rather than queued behind it.
3. **A refusal IS the answer.** A card whose house has no session answers with the spoken
   sentence `keel converse` would have said, because that sentence is what he needs to read.
4. **The talker's board is a handoff**, and the reply says so rather than pretending Harbor
   answered through this request.
"""

import json
import secrets
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from keel import boardask, boards
from tests import test_serve as deck_tests


class AskCase(deck_tests.ServerCase):
    def setUp(self):
        super().setUp()
        boardask._turns.clear()
        self.addCleanup(boardask._turns.clear)
        # `self.inbox` has no house session, so a real turn is refused before anything on
        # this machine is touched: no `claude` is ever started by these tests.
        boards.push(self.cfg, 'frame note "n"\ntext "what this card is about"', card=self.inbox)
        self.record = boards.read_record(self.cfg, "b-001")

    def post(self, path, payload, origin=True):
        request = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(),
                                         method="POST")
        request.add_header("Content-Type", "application/json")
        if not origin:
            request.add_header("Origin", "http://evil.test")
        else:
            for name, value in self.page_headers().items():
                request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def settled(self, turn: str, timeout: float = 20.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, body = self.fetch_json(f"/api/board/b-001/ask/{turn}")
            self.assertEqual(status, 200, body)
            if body["state"] == "done":
                return body
            time.sleep(0.05)
        self.fail(f"turn {turn} never settled")

    def fetch_json(self, path):
        status, _, raw = self.fetch(path)
        return status, json.loads(raw)


class AskRouteTest(AskCase):
    def test_a_question_answers_with_a_turn_id_and_the_page_polls_for_the_answer(self):
        status, body = self.post("/api/board/b-001/ask", {"text": "what does this card do?"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["state"], "running")
        self.assertTrue(body["turn"])
        answer = self.settled(body["turn"])
        self.assertFalse(answer["answered"])
        self.assertIn("no house session yet", answer["say"])
        self.assertIsNotNone(answer["seconds"])

    def test_the_requests_ok_and_the_turns_verdict_are_two_different_words(self):
        """One `ok` carrying both is how a refused turn reads as a broken page: the poll
        succeeded, and what it carries is a house saying no."""
        turn = self.post("/api/board/b-001/ask", {"text": "explain it"})[1]["turn"]
        answer = self.settled(turn)
        self.assertTrue(answer["ok"], "the poll itself was understood")
        self.assertFalse(answer["answered"], "and the turn was refused")

    def test_the_spoken_refusal_is_what_shows_under_the_box(self):
        """`keel converse`'s refusals are sentences written to be said to him, and they are
        the right thing to read here too."""
        turn = self.post("/api/board/b-001/ask", {"text": "explain it"})[1]["turn"]
        self.assertIn(self.inbox, self.settled(turn)["say"])

    def test_an_empty_question_is_refused_before_a_turn_starts(self):
        status, body = self.post("/api/board/b-001/ask", {"text": "   "})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], boardask.NOTHING)

    def test_a_second_send_while_one_is_running_is_refused(self):
        held = threading.Event()

        def slow(cfg, card_id, said):
            held.wait(10)
            return True, "done"

        with mock.patch.object(boardask, "ask_card", slow):
            first = self.post("/api/board/b-001/ask", {"text": "one"})[1]
            status, body = self.post("/api/board/b-001/ask", {"text": "two"})
            self.assertEqual(status, 409)
            self.assertEqual(body["error"], boardask.BUSY)
            held.set()
            self.assertEqual(self.settled(first["turn"])["say"], "done")

    def test_a_question_from_another_page_is_refused(self):
        status, body = self.post("/api/board/b-001/ask", {"text": "hello"}, origin=False)
        self.assertEqual(status, 403)

    def test_an_unknown_board_and_an_unknown_turn_are_both_404(self):
        self.assertEqual(self.post("/api/board/b-404/ask", {"text": "hi"})[0], 404)
        self.assertEqual(self.fetch("/api/board/b-001/ask/deadbeef")[0], 404)

    def test_a_turn_that_raised_still_settles_rather_than_spinning_forever(self):
        def boom(cfg, card_id, said):
            raise RuntimeError("the machine half fell over")

        with mock.patch.object(boardask, "ask_card", boom):
            turn = self.post("/api/board/b-001/ask", {"text": "one"})[1]["turn"]
            answer = self.settled(turn)
        self.assertFalse(answer["answered"])
        self.assertIn("fell over", answer["say"])


class TalkerAskTest(AskCase):
    """A talker board hands the text to Harbor the way the phone does."""

    def setUp(self):
        super().setUp()
        boards.push(self.cfg, 'frame note "n"\ntext "Harbor drew this"', talker=True,
                    actor="talker")
        self.talker = boards.read_record(self.cfg, "b-002")

    def test_it_runs_the_gateways_own_ask_verb_and_shows_harbors_answer(self):
        """c-422: the reply is Harbor's ANSWER, waited for, never "it was sent"."""
        seen = {}

        def fake_run(argv, timeout):
            seen["argv"] = argv
            return 0, json.dumps(
                {"tier": "harbor", "ok": True, "answer": "Here is the memory system.",
                 "drew": 1}), ""

        with mock.patch.object(boardask, "run_ask", fake_run):
            ok, say = boardask.ask_talker(self.cfg, "draw me the memory system")
        self.assertTrue(ok)
        self.assertEqual(say, "Here is the memory system.")
        self.assertTrue(seen["argv"][1].endswith("bin/keel-voice"), seen["argv"])
        self.assertEqual(seen["argv"][2:], ["ask", "--wait", "--json",
                                            "draw me the memory system"])

    def test_an_answer_the_fast_tier_gave_is_shown_too(self):
        def fake_run(argv, timeout):
            return 0, json.dumps(
                {"tier": "board", "ok": True, "answer": "Two houses are up."}), ""

        with mock.patch.object(boardask, "run_ask", fake_run):
            ok, say = boardask.ask_talker(self.cfg, "what is running")
        self.assertEqual((ok, say), (True, "Two houses are up."))

    def test_a_gateway_that_cannot_be_reached_says_so_in_one_line(self):
        def fake_run(argv, timeout):
            return 1, "", "no module named harbor_voice\n"

        with mock.patch.object(boardask, "run_ask", fake_run):
            ok, say = boardask.ask_talker(self.cfg, "hello")
        self.assertFalse(ok)
        self.assertIn("Harbor could not be reached", say)
        self.assertEqual(len(say.splitlines()), 1)

    def test_a_talker_board_takes_the_talker_path(self):
        with mock.patch.object(boardask, "ask_talker", return_value=(True, "It is drawn.")) as sent:
            started = boardask.start(self.cfg, self.talker, "draw the drain")
            deadline = time.time() + 10
            while boardask.result(started["turn"])["state"] == "running" and time.time() < deadline:
                time.sleep(0.02)
        self.assertEqual(sent.call_args[0][1], "draw the drain")
        self.assertEqual(sent.call_args.kwargs["board_id"], self.talker["id"],
                         "the board rides along as the ask's context")
        self.assertEqual(boardask.result(started["turn"])["say"], "It is drawn.")


class OneAtATimeTest(AskCase):
    """The refusal is a LOCK and not a look. `start` checked `running_on` under the lock and
    then inserted under it again, so two Sends landing together both passed the check and
    both started a turn into the same house: two `claude` processes on one session, which is
    exactly what the guard exists to stop. The window is small, so the test widens it by
    holding the id mint, which the fix covers because the mint is inside the lock now."""

    def two_at_once(self) -> list:
        answers = []
        gate = threading.Barrier(2)

        def attempt():
            gate.wait(5)
            try:
                answers.append(boardask.start(self.cfg, self.record, "explain this"))
            except boardask.AskError as refusal:
                answers.append(refusal)

        def slow_mint():
            time.sleep(0.05)      # the window between the check and the insert
            return secrets.token_hex(6)

        held = threading.Event()

        def answer(*_):
            # The turn stays running until both Sends are in: a turn that settled first
            # would let the second start legitimately, and the test would flake on timing.
            held.wait(10)
            return True, "done"

        with mock.patch.object(boardask, "ask_card", answer), \
             mock.patch.object(boardask, "ask_talker", answer), \
             mock.patch.object(boardask, "new_id", slow_mint):
            threads = [threading.Thread(target=attempt) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            held.set()
        return answers

    def test_two_sends_landing_together_start_one_turn_and_refuse_the_other(self):
        answers = self.two_at_once()
        self.assertEqual(len(answers), 2)
        started = [answer for answer in answers if isinstance(answer, dict)]
        refused = [answer for answer in answers if isinstance(answer, boardask.AskError)]
        self.assertEqual(len(started), 1, f"two turns started on one board: {answers}")
        self.assertEqual(str(refused[0]), boardask.BUSY)
        self.assertEqual(len([row for row in boardask._turns.values()
                              if row["board"] == self.record["id"]]), 1)


class TurnStoreTest(unittest.TestCase):
    def setUp(self):
        boardask._turns.clear()
        self.addCleanup(boardask._turns.clear)

    def test_a_finished_turn_is_forgotten_once_nobody_came_for_it(self):
        boardask._turns["old"] = {"board": "b-001", "state": "done", "answered": True,
                                  "say": "hi", "at": time.time() - boardask.KEEP_SECONDS - 1}
        boardask._turns["live"] = {"board": "b-002", "state": "running", "answered": None,
                                   "say": "", "at": time.time() - boardask.KEEP_SECONDS - 1}
        boardask.prune()
        self.assertEqual(sorted(boardask._turns), ["live"], "a running turn is never dropped")

    def test_the_answer_a_poll_is_handed_names_its_board(self):
        boardask._turns["t"] = {"board": "b-007", "state": "done", "answered": True,
                                "say": "yes", "at": time.time(), "seconds": 1.2}
        self.assertEqual(boardask.result("t"),
                         {"turn": "t", "board": "b-007", "state": "done", "answered": True,
                          "say": "yes", "seconds": 1.2})
        self.assertIsNone(boardask.result("nobody"))

    def test_the_gateways_json_is_read_off_the_last_line_of_its_output(self):
        self.assertEqual(boardask.parsed('noise\n{"answer": "Two houses."}\n'),
                         {"answer": "Two houses."})
        self.assertIsNone(boardask.parsed("tier: Harbor\nharbor: delivered\n"))


if __name__ == "__main__":
    unittest.main()
