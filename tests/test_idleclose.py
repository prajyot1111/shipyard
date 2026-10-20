"""Idle houses (c-607): the memory a live house holds, read from the process table on Linux
and on macOS, never guessed; which houses are idle; and the rule every Close idle house tap
is checked against, where the tap lands and on the machine that carries it."""

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from keel import deckstate, housemem, idleclose, livestrip, shipidle, views
from tests.helpers import SESSION, background_row

# `ps -A -o pid=,ppid=,rss=` as a Mac prints it: right-aligned, RSS in KiB.
MAC_PS = """\
    1     0  12016
  501     1 614400
  502   501 204800
  503   502  51200
  504     1  90000
  junk line
"""


class PsTest(unittest.TestCase):
    def test_the_mac_table_parses_and_the_tree_is_summed(self):
        procs = housemem.parse_ps(MAC_PS)
        self.assertEqual(procs[502], (501, 204800))
        self.assertEqual(len(procs), 5)
        self.assertEqual(housemem.tree_kib(501, procs), 614400 + 204800 + 51200)
        self.assertEqual(housemem.mem_mb(501, procs), 850, "850 MiB, rounded to 50")
        self.assertEqual(housemem.mem_mb("504", procs), 100, "rounded; a string pid is read too")

    def test_no_pid_or_an_unknown_pid_is_no_reading(self):
        procs = housemem.parse_ps(MAC_PS)
        for pid in (None, "", "abc", 9999):
            self.assertIsNone(housemem.mem_mb(pid, procs))


    def test_ps_is_run_once_as_one_table(self):
        seen = []

        def run(argv, **kwargs):
            seen.append(argv)
            return mock.Mock(stdout=MAC_PS)
        self.assertEqual(len(housemem.ps_table(run)), 5)
        self.assertEqual(seen, [["ps", "-A", "-o", "pid=,ppid=,rss="]])


class ProcTest(unittest.TestCase):
    def proc(self, root: Path, pid: int, command: str, ppid: int, pages: int) -> None:
        (root / str(pid)).mkdir()
        (root / str(pid) / "stat").write_text(f"{pid} ({command}) S {ppid} {pid} {pid} 0 -1 4194560 0\n")
        (root / str(pid) / "statm").write_text(f"999999 {pages} 300 20 0 900 0\n")

    def test_the_linux_table_reads_stat_and_statm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.proc(root, 700, "claude", 1, 100000)
            self.proc(root, 701, "node (mcp) x", 700, 25000)     # a command with ") " in it
            self.proc(root, 702, "bash", 701, 1000)
            (root / "self").mkdir()
            (root / "703").mkdir()                                 # ended while read: left out
            with mock.patch.object(housemem.os, "sysconf", return_value=4096):
                procs = housemem.proc_table(root)
        self.assertEqual(sorted(procs), [700, 701, 702])
        self.assertEqual(procs[701], (700, 100000))
        self.assertEqual(housemem.tree_kib(700, procs), (100000 + 25000 + 1000) * 4)
        self.assertEqual(housemem.mem_mb(700, procs), 500)


class FactsTest(unittest.TestCase):
    def test_the_strip_carries_the_reading_and_none_without_a_pid(self):
        procs = {77: (1, 2 * 1024 * 1024)}
        row = dict(background_row("c-1", SESSION), pid=77)
        card = {"id": "c-1", "space": "personal", "session_id": SESSION}
        cfg = mock.Mock(host="box")
        cfg.spaces = {"personal": mock.Mock(config_dir=Path("/nowhere"))}
        facts = livestrip.card_facts(cfg, card, [row], procs=procs)
        self.assertEqual(facts["mem_mb"], 2050, "2 GiB, in steps of 50 MB")
        facts = livestrip.card_facts(cfg, card, [dict(row, pid=None)], procs=procs)
        self.assertIsNone(facts["mem_mb"], "never a guess")


class NotIdleTest(unittest.TestCase):
    CARD = {"id": "c-1", "options": {}}

    def test_only_a_listed_idle_background_house_may_be_closed(self):
        idle = background_row("c-1", SESSION)
        self.assertIsNone(idleclose.not_idle(self.CARD, idle))
        self.assertIn("working", idleclose.not_idle(self.CARD, background_row("c-1", SESSION, "busy")))
        self.assertIn("lists no live session", idleclose.not_idle(self.CARD, None))
        self.assertIn("lists no live session", idleclose.not_idle(self.CARD, dict(idle, pid=None)))
        self.assertIn("terminal", idleclose.not_idle(self.CARD, dict(idle, kind="interactive")))
        held = {"id": "c-1", "options": {views.VOICE_HOLD_OPTION: {"until": "2999-01-01T00:00:00+00:00"}}}
        self.assertIn("voice", idleclose.not_idle(held, idle))

    def test_an_idle_house_with_a_job_of_its_own_running_is_refused(self):
        with mock.patch.object(idleclose.housejobs, "of_row", return_value=[{"label": "poll"}]):
            self.assertIn("background job", idleclose.not_idle(self.CARD, background_row("c-1", SESSION), "/cfg"))


class StopKindTest(unittest.TestCase):
    def events(self, *kinds):
        out = []
        for kind in kinds:
            if kind in ("human", "idle"):
                out.append({"kind": "note", "data": {"stop": kind}})
            else:
                out.append({"kind": kind, "data": {}})
        return list(reversed(out))

    def test_the_newest_mark_since_the_last_turn_decides(self):
        self.assertEqual(views.stop_kind(self.events("resume", "idle")), "idle")
        self.assertEqual(views.stop_kind(self.events("human", "resume", "idle")), "idle")
        self.assertEqual(views.stop_kind(self.events("idle", "human")), "human", "his Stop after a close holds it")
        self.assertIsNone(views.stop_kind(self.events("idle", "resume")), "a batch or his tap resumed it")
        self.assertFalse(views.stop_holds(self.events("idle")))
        self.assertTrue(views.closed_idle(self.events("idle")))


class IdleHousesTest(unittest.TestCase):
    def card(self, card_id, stage, house, archived=False):
        return {"id": card_id, "stage": stage, "house": house, "derived": {"archived": archived}}

    def test_listed_and_out_of_a_turn_at_a_live_stage(self):
        idle = {"working": False, "kind": "background"}
        cards = [self.card("c-1", "review", idle), self.card("c-2", "shipping", idle),
                 self.card("c-3", "building", {"working": True, "kind": "background"}),
                 self.card("c-4", "done", idle), self.card("c-5", "review", None),
                 self.card("c-6", "review", idle, archived=True),
                 self.card("c-7", "building", {"working": False, "kind": "interactive"})]
        self.assertEqual(deckstate.idle_houses(cards), ["c-1", "c-2"])


if __name__ == "__main__":
    unittest.main()


class ShipIdleCase(unittest.TestCase):

    def setUp(self):
        from keel.board import Board
        from tests.helpers import FakeHarness, make_config
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(Path(self.tmp.name))
        self.board = Board(self.cfg.db_path)
        self.fake = FakeHarness()
        self.fake.stops = []
        for module in (shipidle, idleclose):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def shipping_card(self, merged=False) -> str:
        card = self.board.create("personal", "shipped", autonomy="autonomous")
        self.board.stage(card, "assigned", "human")
        self.board.stage(card, "building", "drain")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card, "review", "house", plan_ref="p.md", output_ref="o")
        self.board.approve(card, "outcome", "human", publish=lambda c: {"shipping": True})
        self.board.record_hook(card, "Stop", {"session_id": SESSION})
        if merged:
            self.board.set_fields(card, {"options": {"shipping": {"facts": {"state": "merged"}}}}, "drain")
            self.board.stage(card, "done", "drain", note="merged")
        return card

    def upkeep(self, hours: float, status: str = "idle"):
        self.fake.rows = [background_row("c", SESSION, status=status)]
        at = shipidle.now() + timedelta(hours=hours)
        return shipidle.upkeep(self.cfg, self.board, self.fake.rows, {"personal"}, at=at)



class ShipIdleTest(ShipIdleCase):
    """a-72: the drain ends a merged card's idle house, and closes a shipping house idle over
    two hours by its own Stop; never a working one, checked again right before the stop."""

    def test_a_merged_cards_idle_house_is_ended_final(self):
        card = self.shipping_card(merged=True)
        self.assertEqual(self.upkeep(0)["ended"], [card])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        last = self.board.events(card)[-1]
        self.assertEqual(last["data"], {"stop": "merged"})
        self.assertIn("a done card is not resumed", last["text"])
        self.assertFalse(self.board.get(card)["derived"]["closed_idle"])

    def test_a_merged_cards_working_house_is_left_until_a_later_pass_finds_it_idle(self):
        card = self.shipping_card(merged=True)
        self.assertEqual(self.upkeep(0, status="busy")["ended"], [])
        self.assertEqual(self.fake.stops, [])
        self.assertEqual(self.upkeep(0)["ended"], [card])

    def test_a_shipping_house_idle_over_two_hours_is_closed_until_its_next_batch(self):
        card = self.shipping_card()
        self.assertEqual(self.upkeep(1.9)["closed"], [], "not yet")
        idle = self.board.get(card)["derived"]["ship_idle"]
        self.assertEqual(idle["hours"], 2)
        self.assertEqual(self.upkeep(2.1)["closed"], [card])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        last = self.board.events(card)[-1]
        self.assertEqual((last["actor"], last["data"]), ("drain", {"stop": "idle"}))
        self.assertIn("idle at shipping for 2h06m", last["text"])
        self.assertIn("the next review or your tap resumes it", last["text"])
        derived = self.board.get(card)["derived"]
        self.assertEqual((derived["closed_idle"], derived["held_by_stop"]), (True, False))

    def test_never_a_working_house_and_never_without_a_stop_on_record(self):
        card = self.shipping_card()
        self.assertEqual(self.upkeep(5, status="busy")["closed"], [])
        self.board.record_event(card, "resume", "drain")      # a batch told: a turn began
        self.assertIsNone(self.board.get(card)["derived"]["ship_idle"])
        self.assertEqual(self.upkeep(5)["closed"], [], "quiet time is not evidence")
        self.assertEqual(self.fake.stops, [])

    def test_the_house_is_checked_again_right_before_the_stop(self):
        card = self.shipping_card()
        rows = [background_row("c", SESSION, status="idle")]
        self.fake.rows = [background_row("c", SESSION, status="busy")]    # the fresh listing
        at = shipidle.now() + timedelta(hours=3)
        self.assertEqual(shipidle.upkeep(self.cfg, self.board, rows, {"personal"}, at=at)["closed"], [])
        self.assertEqual(self.fake.stops, [])
        self.assertFalse(self.board.get(card)["derived"]["closed_idle"])


class ReviewFixesTest(ShipIdleCase):
    """c-607 review: the close and a tell serialize; a merged card's house is judged by the
    same rule; a blocked Stop does not end the turn; the table counts a job's own pid."""

    def test_a_merged_cards_house_with_a_job_or_a_tap_or_a_drop_in_is_left(self):
        card = self.shipping_card(merged=True)
        with mock.patch.object(idleclose.housejobs, "of_row", return_value=[{"label": "poll"}]):
            self.assertEqual(self.upkeep(0)["ended"], [])
        held = {**self.board.get(card), "options": {views.DROPIN_HOLD_OPTION: {"until": "2999-01-01T00:00:00+00:00"}}}
        self.assertIsNotNone(views.dropin_hold(held["options"]))
        self.assertIn("Drop in", idleclose.not_idle(held, background_row("c", SESSION)))
        self.board.relay(card, "resume", "human", "mac")
        self.assertEqual(self.upkeep(0)["ended"], [])
        self.assertEqual(self.fake.stops, [])

    def test_the_close_waits_for_the_card_lock_a_tell_holds(self):
        import threading
        from keel import house
        card = self.shipping_card()
        self.fake.rows = [background_row("c", SESSION)]
        done = []
        with house.card_lock(self.cfg, card):
            def close():
                from keel.board import Board
                with Board(self.cfg.db_path) as own:
                    done.append(idleclose.close_here(self.cfg, own, card))
            worker = threading.Thread(target=close)
            worker.start()
            worker.join(0.5)
            self.assertEqual((done, self.fake.stops), ([], []), "held while the tell decides")
        worker.join(5)
        self.assertEqual(self.fake.stops, [SESSION[:8]])

    def test_a_tell_marks_itself_in_flight_until_its_send_ends(self):
        from keel import tellhouse
        card = self.shipping_card()
        self.fake.rows = [background_row(card, SESSION)]
        seen = []
        plan = {"card": self.board.get(card), "result": {}}
        with mock.patch.object(tellhouse.house, "harness", self.fake), \
                mock.patch.object(tellhouse, "prepare", return_value=plan), \
                mock.patch.object(tellhouse, "send", lambda cfg, board, p: seen.append(
                    idleclose.not_idle(self.board.get(card), self.fake.rows[0], None, self.cfg)) or {}):
            tellhouse.deliver(self.cfg, self.board, card, "a batch")
        self.assertEqual(seen, ["a message is being sent to it right now"])
        self.assertFalse(tellhouse.telling(self.cfg, card), "cleared once the send is over")

    def test_a_stop_the_hook_blocked_did_not_end_the_turn(self):
        card = self.shipping_card()
        self.board.record_hook(card, "Stop", {"session_id": SESSION}, {"stop_blocked": True})
        events = list(reversed(self.board.events(card)))
        ended = views.turn_ended(events, SESSION)
        first = next(e for e in self.board.events(card) if e["kind"] == "hook")
        self.assertEqual(ended.isoformat(timespec="seconds"), first["at"], "the earlier, real one")


class JobPidTest(unittest.TestCase):
    def test_a_job_reparented_to_pid_1_is_still_counted_once(self):
        procs = {10: (1, 1024), 11: (10, 1024), 20: (1, 2048), 21: (20, 1024)}
        self.assertEqual(housemem.tree_kib(10, procs), 2048)
        self.assertEqual(housemem.tree_kib(10, procs, extra=[20, 11, 1, None]), 2048 + 3072)

    def test_the_table_is_read_once_per_tick(self):
        reads = []
        now = [100.0]
        with mock.patch.object(housemem, "read_table", lambda: reads.append(1) or {1: (0, 1)}), \
                mock.patch.dict(housemem._cache, {"at": float("-inf"), "table": {}}):
            housemem.table(lambda: now[0])
            housemem.table(lambda: now[0] + 1)
            housemem.table(lambda: now[0] + 3)
        self.assertEqual(len(reads), 2)
