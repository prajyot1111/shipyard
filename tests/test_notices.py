"""A notice retires itself: a card carrying `options.notice_key` is staged done from any stage
(decision S4, "open until staged done"), through the same paths the segments close one by.

Before J-1 the board allowed done only from review while a notice sits at inbox, and every
closer swallowed the refusal, so no automatic close had ever worked: c-440 sat open after
three good pulls. The backup test drives the script's own `queue` function against a real
board through the real `bin/kb`, because the selftest's stub board took any stage and hid it.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel.board import Board, Refused
from tests.helpers import BoardCase, ROOT, write_toml

BACKUP = ROOT / "bin" / "keel-backup"
KEY = "backup-stale"


class NoticeStageTest(BoardCase):
    def notice(self, stage="inbox"):
        return self.board.create("personal", "the backup is stale", autonomy="attended",
                                 topic="notice", options={"notice_key": KEY}, stage=stage)


    def test_a_notice_is_staged_done_from_any_stage_and_by_any_actor(self):
        for stage, actor in (("assigned", "fetch"), ("planning", "cli"),
                              ("building", "house"), ("inbox", "human")):
            card_id = self.notice(stage)
            self.assertEqual(self.board.stage(card_id, "done", actor)["stage"], "done")

    def test_a_card_without_the_key_is_still_refused_done_from_inbox(self):
        card_id = self.board.create("personal", "an idea", topic="notice")
        with self.assertRaisesRegex(Refused, "only from review"):
            self.board.stage(card_id, "done", "cli")

    def test_the_exemption_is_done_only(self):
        card_id = self.notice()
        with self.assertRaisesRegex(Refused, "review needs a plan_ref"):
            self.board.stage(card_id, "review", "cli")


class BackupQueueCloseTest(unittest.TestCase):
    """`bin/keel-backup notice close K` is the script's own `queue close`, verbatim."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "backup-home"
        self.toml = write_toml(Path(self.tmp.name))

    def backup(self, *argv):
        env = dict(os.environ, KEEL_HOME=str(ROOT), KEEL_CONFIG=str(self.toml),
                   KEEL_BACKUP_HOME=str(self.home), KEEL_BACKUP_STORE="file:/nowhere",
                   KEEL_BACKUP_SETS="")
        env.pop("KEEL_CARD", None)
        return subprocess.run(["bash", str(BACKUP), "notice", *argv], env=env,
                              capture_output=True, text=True, timeout=60)

    def open_notices(self):
        with Board(Path(self.tmp.name) / "state" / "board.db") as board:
            return [card for card in board.list_cards(stage=None)
                    if (card["options"] or {}).get("notice_key") == KEY
                    and card["stage"] != "done"]

    def test_a_raised_notice_is_closed_through_the_scripts_queue_close(self):
        raised = self.backup("add", "Keel backup is stale", "--kind", "notice", "--key", KEY,
                             "--replace", "--why", "no run for 7h")
        self.assertEqual(raised.returncode, 0, raised.stdout + raised.stderr)
        self.assertEqual(len(self.open_notices()), 1)
        closed = self.backup("close", KEY)
        self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)
        self.assertEqual(self.open_notices(), [])

    def test_nothing_open_under_the_key_is_exit_5_and_not_a_failure(self):
        self.assertEqual(self.backup("close", KEY).returncode, 5)


class BackupCloseIsLoggedTest(unittest.TestCase):
    """Every clear_* in the script says why a close failed instead of `|| true`."""

    def test_no_closer_swallows_its_failure(self):
        text = BACKUP.read_text()
        closes = [line for line in text.splitlines() if "queue close" in line
                  and not line.lstrip().startswith("#")]
        self.assertTrue(closes)
        for line in closes:
            self.assertNotIn("|| true", line, line)
            self.assertNotIn(">/dev/null 2>&1", line, line)


def load_cloud_spend():
    spec = importlib.util.spec_from_file_location(
        "cloud_spend_fetch_notices", ROOT / "segments" / "cloud-spend" / "fetch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless((ROOT / "segments" / "cloud-spend" / "fetch.py").is_file(),
                     "the cloud-spend segment is one install's own and leaves the tree (c-722)")
class CloudSpendCloseIsLoggedTest(unittest.TestCase):
    def test_a_failed_close_says_what_the_board_said(self):
        fetch = load_cloud_spend()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name) / "cloud-spend"
        data.mkdir()
        (data / "announced.json").write_text(json.dumps({"keys": {"k1": "warn"}}))
        refused = "refused: done is reached only from review (c-9 is at inbox)"
        err = io.StringIO()
        with mock.patch.object(fetch, "DATA", data), contextlib.redirect_stderr(err):
            result = fetch.stage({}, run=lambda args: (1, refused))
        self.assertEqual(result["failed"], ["k1"])
        self.assertIn("k1", err.getvalue())
        self.assertIn(refused, err.getvalue())


if __name__ == "__main__":
    unittest.main()
