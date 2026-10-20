"""Who works a card (c-645, `views.bosun_builds`, `options.worker`): Bosun or a house, his
choice on a card Bosun may build, with no worker meaning the rule's answer as before. The
board refuses a worker it cannot honour and a move once work has started, and the one gate
(the drain, Bosun's queue, his approvals) reads it."""

import tempfile
import unittest
from pathlib import Path

from keel import actions, authority, drain, views
from keel.board import Board, Refused
from tests.helpers import SESSION, make_config


class WorkerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name in ("keel", "notes"):
            (root / name).mkdir()
        self.cfg = make_config(root, repos={"keel": root / "keel", "notes": root / "notes"})
        # the in-app builder over keel: builder mode on, Bosun builds keel and nothing else
        self.board = Board(self.cfg.db_path, switches={authority.BUILDER}, builds=["keel"])
        self.addCleanup(self.board.close)

    def card(self, repo="keel", space="personal", **options):
        return self.board.get(self.board.create(space, "a card", repo=repo, actor="human", options=options or None))

    def test_no_worker_is_the_rule_as_before(self):
        keel, notes = self.card(), self.card(repo="notes")
        self.assertEqual((keel["derived"]["bosun"], keel["derived"]["worker"], keel["derived"]["worker_eligible"]),
                         (True, "bosun", True))
        self.assertEqual((notes["derived"]["bosun"], notes["derived"]["worker"], notes["derived"]["worker_eligible"]),
                         (False, "house", False))

    def test_a_house_worker_takes_a_card_off_bosun_and_the_drain_may_start_it(self):
        cid = self.card(worker="house")["id"]
        self.board.stage(cid, "assigned", "human")
        card = self.board.get(cid)
        self.assertEqual((card["derived"]["bosun"], card["derived"]["worker"]), (False, "house"))
        self.assertTrue(card["derived"]["startable"], "a house's card is the drain's to start")
        bosun = self.card()["id"]
        self.board.stage(bosun, "assigned", "human")
        self.assertFalse(self.board.get(bosun)["derived"]["startable"], "Bosun's never is")

    def test_bosun_never_approves_a_house_card(self):
        cid = self.card(worker="house")["id"]
        with self.assertRaisesRegex(Refused, "not a card the builder builds"):
            self.board.approve(cid, "plan", authority.BOSUN, bosun={"checked": "x"})
        # the box's legacy superuser too
        su = Board(self.cfg.db_path, switches={authority.BUILDER, authority.SUPERUSER}, builds=["keel"])
        self.addCleanup(su.close)
        with self.assertRaisesRegex(Refused, "not a card the builder builds"):
            su.approve(cid, "plan", authority.BOSUN, bosun={"checked": "x"})

    def test_a_worker_it_cannot_honour_is_refused(self):
        with self.assertRaisesRegex(Refused, "Bosun builds only"):
            self.card(repo="notes", worker="bosun")
        with self.assertRaisesRegex(Refused, "Bosun builds only"):
            self.card(space="work", repo="keel", worker="bosun")
        with self.assertRaisesRegex(Refused, "one of house, bosun"):
            self.card(worker="you")
        off = Board(self.cfg.db_path, switches=(), builds=["keel"])
        self.addCleanup(off.close)
        with self.assertRaisesRegex(Refused, "Bosun builds only"):
            off.create("personal", "builder mode off", repo="keel", actor="human", options={"worker": "bosun"})

    def test_he_moves_it_only_before_anything_starts(self):
        cid = self.card()["id"]
        self.board.set_fields(cid, {"options": {"worker": "house"}}, "human")
        self.assertEqual(self.board.get(cid)["derived"]["worker"], "house")
        self.board.stage(cid, "assigned", "human")
        self.board.set_fields(cid, {"options": {"worker": "bosun"}}, "human")
        self.assertEqual(self.board.get(cid)["derived"]["worker"], "bosun")
        with self.assertRaisesRegex(Refused, r"the owner's to change after create \(with their token\)"):
            self.board.set_fields(cid, {"options": {"worker": "house"}}, authority.BOSUN)
        self.board.set_session(cid, SESSION, "drain", bg_id=SESSION[:8])
        with self.assertRaisesRegex(Refused, "stop it first"):
            self.board.set_fields(cid, {"options": {"worker": "house"}}, "human")
        events = [e for e in self.board.events(cid) if e["kind"] == "set"]
        self.assertEqual(len(events), 2, "each move is recorded on the card")

    def test_the_deck_carries_it(self):
        argv = actions.create_argv({"space": "personal", "title": "t", "repo": "keel", "worker": "house"})
        self.assertEqual(argv[argv.index("--worker") + 1], "house")

    def test_kb_create_takes_the_worker(self):
        from keel import cli
        args = type("Args", (), dict(space="personal", title="t", brief=None, autonomy=None, repo="keel",
                                     new_project=None, model=None, parent=None, after=None, from_card=None,
                                     topic=None, option=None, assumed=None, worker="house", config=self.cfg))()
        card = cli.cmd_create(self.board, args, "human")
        self.assertEqual((card["options"]["worker"], card["derived"]["worker"]), ("house", "house"))

    def test_only_he_names_a_worker_when_a_card_is_made(self):
        """r1.F1: Bosun, a house and the drain never choose who works a card; his voice may."""
        for actor in (authority.BOSUN, "house", "drain", "cli", "hook"):
            with self.assertRaisesRegex(Refused, "the owner's to choose"):
                self.board.create("personal", "t", repo="keel", actor=actor, options={"worker": "house"})
        from keel import bosuncards
        from keel.board import WORKER_SETTERS
        self.assertEqual(set(WORKER_SETTERS), set(bosuncards.HIS_ACTORS), "his actors, one list")
        cid = self.board.create("personal", "t", repo="keel", actor="voice", options={"worker": "house"})
        self.assertEqual(self.board.get(cid)["derived"]["worker"], "house")

    def test_a_slice_or_a_from_card_of_a_house_card_is_a_houses(self):
        """r1.F2: the worker is carried, and a slice's own worker is checked."""
        parent = self.card(worker="house")["id"]
        kids = self.board.split(parent, [{"title": "one"}, {"title": "two"}], "human")
        self.assertEqual([self.board.get(k)["derived"]["worker"] for k in kids], ["house", "house"])
        born = self.board.create("personal", "from it", actor="human", from_card=parent)
        self.assertEqual(self.board.get(born)["derived"]["worker"], "house")
        mine = self.card()["id"]
        with self.assertRaisesRegex(Refused, "one of house, bosun"):
            self.board.split(mine, [{"title": "x", "options": {"worker": "you"}}], "human")
        with self.assertRaisesRegex(Refused, "Bosun builds only"):
            self.board.split(self.card(repo="notes")["id"], [{"title": "x", "options": {"worker": "bosun"}}], "human")

    def test_a_claimed_card_keeps_its_worker_and_the_drain_never_houses_bosuns(self):
        """r1.F3: the drain's claim is a start under way."""
        cid = self.card(worker="house")["id"]
        self.board.stage(cid, "assigned", "human")
        self.board.claim(cid, "mac", "drain")
        with self.assertRaisesRegex(Refused, "claimed by a drain"):
            self.board.set_fields(cid, {"options": {"worker": "bosun"}}, "human")
        self.cfg.host = "mac"
        self.assertTrue(drain.claimed_unstarted(self.cfg, self.board.get(cid)), "the house's: it starts")
        # the same claimed card, read by a board on which it is Bosun's (its worker cleared,
        # as a card from before c-645 would read): the drain leaves it alone
        self.board.conn.execute("UPDATE cards SET options = json_remove(options, '$.worker') WHERE id = ?", (cid,))
        self.board.conn.commit()
        self.assertTrue(self.board.get(cid)["derived"]["bosun"])
        self.assertFalse(drain.claimed_unstarted(self.cfg, self.board.get(cid)))

    def test_bosun_never_acts_on_a_house_card_as_his_own(self):
        """r1.F5: his stage, set, split, note and unblock go through `authority.builds`."""
        cid = self.card(worker="house")["id"]
        self.assertFalse(authority.builds(self.board.get(cid), True))
        self.board.stage(cid, "assigned", "human")
        with self.assertRaisesRegex(Refused, "worker is a house: Bosun moves none of it"):
            self.board.stage(cid, "building", authority.BOSUN)
        with self.assertRaisesRegex(Refused, "worker is a house, so Bosun changes no field"):
            self.board.set_fields(cid, {"topic": "mine"}, authority.BOSUN)
        with self.assertRaisesRegex(Refused, "worker is a house: Bosun splits none of it"):
            self.board.split(cid, [{"title": "x"}], authority.BOSUN)
        with self.assertRaisesRegex(Refused, "not a card Bosun builds: Bosun writes no note"):
            self.board.note(cid, "mine", authority.BOSUN)
        self.board.block(cid, "waiting", "human")
        with self.assertRaisesRegex(Refused, "not a card Bosun builds"):
            self.board.unblock(cid, authority.BOSUN)
        # his own card he still moves
        mine = self.card()["id"]
        self.board.stage(mine, "assigned", "human")
        self.board.stage(mine, "building", authority.BOSUN)
        self.assertEqual(self.board.get(mine)["stage"], "building")

    def test_a_tracking_card_has_no_worker_of_its_own(self):
        """r1.F8: each slice has its own; r2.F3: archived slices do not count, as on the pane."""
        parent = self.card()["id"]
        kids = self.board.split(parent, [{"title": "one"}], "human")
        with self.assertRaisesRegex(Refused, "tracking card"):
            self.board.set_fields(parent, {"options": {"worker": "house"}}, "human")
        self.board.set_fields(kids[0], {"options": {"archived": True}}, "human")
        self.board.set_fields(parent, {"options": {"worker": "house"}}, "human")
        self.assertEqual(self.board.get(parent)["derived"]["worker"], "house")

    def test_a_started_card_says_it_has_started(self):
        """r2.F2: a claim stays on a card its house started; the stage is the reason given."""
        cid = self.card(worker="house")["id"]
        self.board.stage(cid, "assigned", "human")
        self.board.claim(cid, "mac", "drain")
        self.board.stage(cid, "building", "drain")
        with self.assertRaisesRegex(Refused, "has started"):
            self.board.set_fields(cid, {"options": {"worker": "bosun"}}, "human")

    def test_views_reads_a_dict_or_json_options(self):
        self.assertEqual(views.worker_of({"options": '{"worker": "house"}'}), "house")
        self.assertEqual(views.worker_of({"options": {"worker": "nobody"}}), None)


if __name__ == "__main__":
    unittest.main()
