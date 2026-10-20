"""The login ask (c-558, `keel/loginask.py`): one ask per red episode of a Logins row,
withdrawn by the drain when the row answers, never handed to Bosun as work; the push
handler raises the other machine's; and the deploy ask's window is not crowded by them."""

import tempfile
import unittest
from pathlib import Path

from keel import asks, deployask, loginask
from keel.board import Board, Refused
from tests.helpers import make_config


def row(state="expired", good_at=None, **extra):
    return dict({"id": "claude:harbor", "label": "Claude talker and voice", "state": state,
                 "why": "a turn said: Login expired", "where": "/k/spaces/harbor/.claude",
                 "fix": "ssh -t keel-box 'claude auth login'", "good_at": good_at}, **extra)


class SyncTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)

    def held(self, host="box"):
        return loginask.rows_for(self.board, host)

    def test_a_red_row_raises_one_ask_naming_it_and_its_fix(self):
        raised = loginask.sync(self.board, "box", [row()])["raised"]
        self.assertEqual(len(raised), 1)
        ask = asks.get(self.board, raised[0])
        self.assertEqual(ask["state"], "open")
        self.assertIn("Claude talker and voice", ask["question"])
        self.assertIn("ssh -t keel-box", ask["why"])
        self.assertEqual(loginask.facts_of(ask)["fix"], "ssh -t keel-box 'claude auth login'")
        self.assertEqual(loginask.sync(self.board, "box", [row()])["raised"], [])
        self.assertEqual(len(self.held()), 1)

    def test_it_is_withdrawn_when_the_row_answers_and_an_unknown_changes_nothing(self):
        aid = loginask.sync(self.board, "box", [row()])["raised"][0]
        loginask.sync(self.board, "box", [row(state="unknown")])
        self.assertEqual(asks.get(self.board, aid)["state"], "open")
        self.assertEqual(loginask.sync(self.board, "box", [row(state="good")])["withdrawn"], [aid])
        self.assertEqual(asks.get(self.board, aid)["state"], "withdrawn")

    def test_a_key_ask_is_withdrawn_once_the_key_reads_unset(self):
        """A key no longer set is optional, not red, so its ask goes as a working one's does."""
        key = {"id": "google-tts", "label": "Google TTS key"}
        aid = loginask.sync(self.board, "box", [row(**key)])["raised"][0]
        self.assertEqual(loginask.sync(self.board, "box", [row(state="unset", **key)])["withdrawn"],
                         [aid])

    def test_later_is_not_asked_again_until_the_row_has_worked(self):
        aid = loginask.sync(self.board, "box", [row()])["raised"][0]
        asks.answer(self.board, aid, "human", "B")
        self.assertEqual(loginask.sync(self.board, "box", [row()])["raised"], [])
        past = "2000-01-01T00:00:00+00:00"
        self.assertEqual(loginask.sync(self.board, "box", [row(good_at=past)])["raised"], [])

    def test_a_new_episode_asks_again(self):
        aid = loginask.sync(self.board, "box", [row()])["raised"][0]
        asks.answer(self.board, aid, "human", "A")
        created = asks.get(self.board, aid)["created_at"]
        later = created.replace(created[:4], str(int(created[:4]) + 1), 1)
        self.assertEqual(len(loginask.sync(self.board, "box", [row(good_at=later)])["raised"]), 1)

    def test_his_answer_is_recorded_and_never_waits_for_bosun(self):
        aid = loginask.sync(self.board, "box", [row()])["raised"][0]
        answered = asks.answer(self.board, aid, "human", "A")
        self.assertEqual(answered["delivered_by"], "login")
        self.assertIsNotNone(answered["delivered_at"])
        self.assertEqual(asks.undelivered(self.board), [])

    def test_bosun_cannot_withdraw_it(self):
        aid = loginask.sync(self.board, "box", [row()])["raised"][0]
        with self.assertRaises(Refused):
            asks.withdraw(self.board, aid, "bosun", "not needed")

    def test_each_host_keeps_its_own(self):
        loginask.sync(self.board, "box", [row()])
        loginask.sync(self.board, "mac", [row(id="claude:work", label="Claude work")])
        self.assertEqual(len(self.held("box")), 1)
        self.assertEqual(len(self.held("mac")), 1)
        loginask.sync(self.board, "mac", [])
        self.assertEqual(self.held("mac")[0]["state"], "withdrawn")
        self.assertEqual(self.held("box")[0]["state"], "open")

    def test_login_asks_do_not_crowd_the_deploy_window(self):
        rows = [row(id=f"r{n}", label=f"row {n}") for n in range(deployask.RECENT + 5)]
        loginask.sync(self.board, "box", rows)
        self.assertEqual(deployask.rows_for(self.board, "keel"), [])


if __name__ == "__main__":
    unittest.main()
