"""The setup page follows the board (c-734 B, points 4, 5 and 9; keel/firstrun.py `watch`,
keel/packdraft.py `connection_cards`).

The second stranger run (2026-10-10): the drafted connection was approved and landed, and the
setup page still drew it as planning until a reload, since the Setup report is read only on
the page's own actions; and Where finished work goes did not offer the landed pack. Now the
state carries `firstrun.watch`, a stamp of every card the setup page draws from the report,
which moves on any move of one of them, from anywhere; the report names the pack a landed
draft added; and an open draft says which gate waits on the user and whether Bosun has heard.
On a real scratch install from `shipyard init`; no session is started."""

import subprocess
import unittest

from keel import firstrun, packdraft, pausewake
from keel.board import open_board
from tests.test_bosuntell import TellCase


def git(repo, *argv):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *argv],
                          capture_output=True, text=True, check=True).stdout.strip()


class WatchTest(TellCase):
    def stamp(self):
        with open_board(self.cfg) as board:
            return firstrun.report(self.cfg, board)["watch"]

    def test_the_stamp_moves_with_every_move_of_a_setup_card_and_no_other(self):
        first = self.stamp()
        card = self.connection()
        seen = [first, self.stamp()]
        with open_board(self.cfg) as board:
            other = board.create("personal", "an errand", brief="", actor="human")
        self.assertEqual(self.stamp(), seen[-1], "a card the page does not draw moves nothing")
        with open_board(self.cfg) as board:
            board.stage(card, "planning", "bosun")
            seen.append(None)
        seen[-1] = self.stamp()
        with open_board(self.cfg) as board:
            board.conn.execute("UPDATE cards SET stage = 'done', updated_at = 'later' WHERE id = ?", (card,))
            board.conn.commit()
        seen.append(self.stamp())
        self.assertEqual(len(set(seen)), len(seen), f"each move is a new stamp: {seen}")
        self.assertTrue(other)


class WatchMoreTest(TellCase):
    def stamp(self, steps=True):
        with open_board(self.cfg) as board:
            return firstrun.report(self.cfg, board, steps=steps)["watch"]

    def test_a_wake_moves_the_stamp(self):
        """r1.F5: "Bosun has been told" follows the wake with no reload."""
        card = self.connection()
        before = self.stamp()
        with open_board(self.cfg) as board:
            row = [r for r in pausewake.wakes(board) if r["card"] == card][0]
            pausewake.woke(board, [f"{card}@{row['event']}"], "drain")
        self.assertNotEqual(self.stamp(), before)

    def test_a_finished_install_s_light_state_carries_it_too(self):
        """r1.F8: the Setup view reads the light state once the first run is finished."""
        firstrun.change(self.cfg, lambda data: data.update(finished="2026-10-10T10:00:00+05:30"))
        self.assertIsNotNone(self.stamp(steps=False))

    def test_a_card_done_long_ago_is_not_read(self):
        """r1.F10: only open cards and ones that moved lately are read."""
        card = self.connection()
        with open_board(self.cfg) as board:
            board.conn.execute("UPDATE cards SET stage = 'done', updated_at = '2026-01-01T00:00:00+05:30' WHERE id = ?", (card,))
            board.conn.commit()
        empty = self.stamp()
        with open_board(self.cfg) as board:
            board.conn.execute("UPDATE cards SET updated_at = '2026-01-02T00:00:00+05:30' WHERE id = ?", (card,))
            board.conn.commit()
        self.assertEqual(self.stamp(), empty)


class ConnectionTest(TellCase):
    def test_an_open_draft_says_its_gate_and_whether_bosun_has_heard(self):
        card = self.connection()
        with open_board(self.cfg) as board:
            found = packdraft.connection_cards(board, self.cfg)["open"]
            self.assertEqual((found["card"], found["gate"], found["told"]), (card, None, False))
            woke = [row for row in pausewake.wakes(board) if row["card"] == card]
            pausewake.woke(board, [f"{card}@{woke[0]['event']}"], "drain")
            board.stage(card, "planning", "bosun")
            plan = self.cfg.card_dir(card) / "plan.md"
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text("# the plan\n")
            board.set_fields(card, {"plan_ref": str(plan)}, "bosun")
            found = packdraft.connection_cards(board, self.cfg)["open"]
        self.assertEqual((found["gate"], found["told"]), ("plan", True))

    def test_a_landed_draft_names_the_pack_it_added(self):
        card = self.connection()
        repo = self.cfg.spaces["personal"].repos["packs"]
        git(repo, "checkout", "-q", "-b", f"bosun/{card}-connection")
        (repo / "forge").mkdir()
        (repo / "forge" / "pack.toml").write_text('name = "forge"\n')
        git(repo, "add", "forge")
        git(repo, "commit", "-qm", "the forge pack")
        git(repo, "checkout", "-q", "-")
        git(repo, "merge", "-q", "--no-ff", f"bosun/{card}-connection", "-m", "land it")
        merge = git(repo, "rev-parse", "HEAD")
        with open_board(self.cfg) as board:
            board.set_fields(card, {"options": {"landing": {"state": "landed", "merge": merge}}}, "drain")
            board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
            board.conn.commit()
            found = packdraft.connection_cards(board, self.cfg)
        self.assertEqual((found["done"], found["pack"]), (card, "forge"))


if __name__ == "__main__":
    unittest.main()
