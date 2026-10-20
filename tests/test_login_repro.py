"""The reproduction of 2026-09-24 (c-452's daybook on the box), kept as the regression test.

The personal space's OAuth could not refresh. Every house turn ended at once with
"Login expired · Please run /login" and no Stop hook, so each house sat listed and idle
at `building`: the quiet-house shape. The drain read it as "most likely the account's rate
limit" and spent its resumes on a login that could not work, and nothing said "login".

Nothing here is a Python fake of the harness. A stand-in `claude` sits first on PATH
(`tests/fixtures/fake_claude_login.py`), and the drain pass runs through the real
`keel.harness`, the real `house.resume` and the real board: the only fakes are that binary,
the machine's memory reading and the drain's clock.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import drain, house
from keel.board import Board
from tests.helpers import FakeMachine, make_config, signed_in

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake_claude_login.py"
FIRST = "11111111-0000-4000-8000-000000000001"
HIS = "22222222-0000-4000-8000-000000000002"


class LoginExpiredReproTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.fake_dir = self.dir / "fake"
        self.fake_dir.mkdir()
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        claude = bin_dir / "claude"
        claude.write_text(f"#!{sys.executable}\nimport runpy, sys\n"
                          f"sys.argv[0] = {str(FIXTURE)!r}\n"
                          f"runpy.run_path({str(FIXTURE)!r}, run_name='__main__')\n")
        claude.chmod(0o755)
        env = mock.patch.dict(os.environ, {"FAKE_CLAUDE_DIR": str(self.fake_dir),
                                           "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        env.start()
        self.addCleanup(env.stop)
        for name, value in (("APP_LINK_TRIES", 1),):
            patch = mock.patch.object(house, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(drain, "machine", FakeMachine())
        patch.start()
        self.addCleanup(patch.stop)
        # The Logins list's own checks (`keel/logins.py`) probe every due dir too, and record
        # a dir with no login as expired (c-560); here only the hold's probes are counted.
        patch = mock.patch.object(drain, "logins_upkeep", return_value=0)
        patch.start()
        self.addCleanup(patch.stop)
        self.cfg = signed_in(make_config(self.dir))   # it was logged in, then expired
        self.cfg.drain_paused = True
        self.board = Board(self.cfg.db_path)
        self.start = datetime.now().astimezone()

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    # ----- the live shape -----

    def quiet_house(self, session: str) -> str:
        """A personal card at building whose turn ended on the login error with no Stop:
        its session listed idle, the idle-prompt Notification, and a transcript whose last
        assistant record is the harness's own auth error."""
        card_id = self.board.create("personal", "daybook", autonomy="autonomous")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, session, "drain", bg_id=session[:8])
        transcript = self.dir / f"{session}.jsonl"
        transcript.write_text(json.dumps({
            "type": "assistant", "isApiErrorMessage": True, "error": "authentication_failed",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Login expired · Please run /login"}]}}) + "\n")
        self.board.record_hook(card_id, "Notification", {
            "hook_event_name": "Notification", "message": "Claude is waiting for your input",
            "notification_type": "idle_prompt", "session_id": session,
            "transcript_path": str(transcript)})
        self.list_rows([(card_id, session)])
        return card_id

    def list_rows(self, pairs) -> None:
        path = self.fake_dir / "rows.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        rows += [{"pid": 7, "id": s[:8], "cwd": "/x", "kind": "background", "sessionId": s,
                  "name": card, "status": "idle"} for card, s in pairs]
        path.write_text(json.dumps(rows))

    def calls(self) -> list[list[str]]:
        path = self.fake_dir / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line)["argv"] for line in path.read_text().splitlines()]

    def resumes(self) -> list[list[str]]:
        return [argv for argv in self.calls() if "--resume" in argv and "--bg" in argv]

    def probes(self) -> list[list[str]]:
        # a promptless `-p --resume <id>` asks whether the conversation is there (c-654)
        return [argv for argv in self.calls() if "-p" in argv and "--resume" not in argv]

    def pass_at(self, minutes: int) -> dict:
        """One pass `minutes` after the house went quiet, on one clock: the drain's and the
        board's, so what the pass itself records is stamped at the same instant."""
        at = self.start + timedelta(minutes=minutes)
        with mock.patch.object(drain, "now", return_value=at), \
                mock.patch.object(self.board, "now", return_value=at.isoformat(timespec="seconds")):
            return drain.once(self.cfg, board=self.board)

    def notes(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]

    # ----- the reproduction -----

    def test_an_expired_login_blocks_its_houses_and_they_come_back_once_it_works(self):
        card_id = self.quiet_house(FIRST)
        mine = self.quiet_house(HIS)
        self.board.block(mine, "leave this one, I am looking at it", "human")

        self.pass_at(11)
        self.assertEqual(self.resumes(), [], "no resume is spent on a login that cannot work")
        card = self.board.get(card_id)
        self.assertIn("the personal login expired", card["blocked_reason"] or "")
        self.assertIn(f"CLAUDE_CONFIG_DIR={self.cfg.spaces['personal'].config_dir} claude",
                      card["blocked_reason"])
        self.assertTrue(card["derived"]["needs_you"])
        self.assertFalse(any("rate limit" in text for text in self.notes(card_id)))
        self.assertEqual(len(self.probes()), 1, "one probe, of the personal space")
        self.assertEqual(self.board.get(mine)["blocked_reason"],
                         "leave this one, I am looking at it")

        self.pass_at(15)
        self.assertEqual(len(self.probes()), 1, "not probed again inside ten minutes")
        self.assertEqual(self.resumes(), [])

        (self.fake_dir / "login-ok").touch()
        self.pass_at(22)
        self.assertEqual(len(self.probes()), 2, "an expired space is probed again after ten")
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.assertEqual(len(self.resumes()), 1, "resumed once, through house.resume")
        self.assertIn(FIRST, self.resumes()[0])
        self.assertTrue(any("login works again" in text for text in self.notes(card_id)))
        self.assertEqual(self.board.get(mine)["blocked_reason"],
                         "leave this one, I am looking at it", "his block is never touched")

        self.pass_at(24)
        self.assertEqual(len(self.resumes()), 1, "and only once")


if __name__ == "__main__":
    unittest.main()
