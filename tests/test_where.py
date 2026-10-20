"""Whether the drain may start a card, and the line the deck shows when it cannot
(keel/where.py): the space, and the repo on this disk."""

import tempfile
import unittest
from pathlib import Path

from keel import where
from tests.helpers import make_config, make_repo


def card(space="personal", repo=None, stage="assigned", options=None, startable=True, **extra):
    return dict({"id": "c-1", "space": space, "repo": repo, "stage": stage, "options": options or {},
                 "blocked_reason": None, "plan_ref": None,
                 "derived": {"startable": startable, "archived": False}}, **extra)


class WhereCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.keel = make_repo(self.dir / "keel")
        self.projects = self.dir / "projects"
        make_repo(self.projects / "jev-bench")
        self.cfg = make_config(self.dir, repos={"keel": self.keel, "harbor": self.dir / "no-harbor"},
                               projects_dir=self.projects)
        self.cfg.spaces["personal"].config_dir.mkdir(parents=True)


class StartableHereTest(WhereCase):
    def test_a_repo_on_this_disk_starts_and_a_missing_one_does_not(self):
        self.assertTrue(where.startable_here(self.cfg, card(repo="keel"), {"personal"}))
        self.assertTrue(where.startable_here(self.cfg, card(repo="jev-bench"), {"personal"}))
        self.assertFalse(where.startable_here(self.cfg, card(repo="harbor"), {"personal"}))
        self.assertEqual(where.missing_repos(self.cfg, card(repo="keel,harbor")), ["harbor"])

    def test_a_new_project_starts_where_the_projects_directory_is(self):
        fresh = card(repo="brand-new", options={"new_project": True})
        self.assertTrue(where.startable_here(self.cfg, fresh, {"personal"}))
        self.cfg.spaces["personal"].projects_dir = self.dir / "absent"
        self.assertFalse(where.startable_here(self.cfg, fresh, {"personal"}))

    def test_a_space_this_drain_does_not_serve_is_not_started(self):
        self.assertFalse(where.startable_here(self.cfg, card(repo="keel"), {"work"}))

    def test_an_old_pin_to_another_host_no_longer_decides(self):
        """c-622: a pin (`options.host`) placed a card between two machines. One machine
        starts every card it can, whatever a card imported from that time still says."""
        self.cfg.host = "mac"
        self.assertTrue(where.startable_here(self.cfg, card(repo="keel", options={"host": "box"}),
                                             {"personal"}))

    def test_an_adapter_space_is_not_checked_for_repos(self):
        self.assertEqual(where.missing_repos(self.cfg, card(space="work", repo="api")), [])


class WaitingTest(WhereCase):
    """The deck's line for a startable card the drain will not start."""

    def test_a_card_this_machine_can_start_says_nothing(self):
        self.assertIsNone(where.waiting_text(self.cfg, card(repo="keel")))

    def test_a_missing_repo_says_what_is_missing(self):
        self.assertEqual(where.waiting_text(self.cfg, card(repo="harbor")),
                         "Cannot start this: personal needs harbor, and this install does not have it")

    def test_a_card_not_at_assigned_or_not_startable_says_nothing(self):
        self.assertIsNone(where.waiting_text(self.cfg, card(repo="harbor", stage="building")))
        self.assertIsNone(where.waiting_text(self.cfg, card(repo="harbor", startable=False)))

    def test_blocked_and_archived_cards_are_left_alone(self):
        self.assertIsNone(where.waiting_text(self.cfg, card(repo="harbor", blocked_reason="x")))
        archived = card(repo="harbor")
        archived["derived"]["archived"] = True
        self.assertIsNone(where.waiting_text(self.cfg, archived))

    def test_the_deck_gets_one_line_per_card_that_cannot_start(self):
        cards = [card(repo="keel"), dict(card(repo="harbor"), id="c-2")]
        self.assertEqual(list(where.waiting(self.cfg, cards)), ["c-2"])


class DrainPlacementTest(WhereCase):
    """The drain's own list: a card whose repo is not on this disk is never started here."""

    def test_startable_cards_leaves_out_a_missing_repo(self):
        from keel import drain
        from keel.board import Board
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        ids = {}
        for name, repo in (("keel", "keel"), ("harbor", "harbor")):
            ids[name] = board.create("personal", name, repo=repo, actor="human")
            board.stage(ids[name], "assigned", "human")
        found = [c["id"] for c in drain.startable_cards(self.cfg, board, {"personal"})]
        self.assertEqual(found, [ids["keel"]])


if __name__ == "__main__":
    unittest.main()
