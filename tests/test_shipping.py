"""Lane SHIP, the engine's half (c-600): the watcher on the machine that holds the house, the
batch it tells the card's OWN living house, the house's verdicts and his Ship.

The work adapter is a stand-in here, small scripts in the test's own adapters directory:
`ship` answers `poll` with the sight the test wrote (what the code host stand-in in
`packs/work/tests/test_shipping.py` makes the real adapter print), `method` with a fixed
method, and records `reap`; `publish` records its argv and stdin and answers what the real
one would. The harness is the suite's `FakeHarness`, so no session is ever started and a
tell goes through its armed relay. Every pull request is invented.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import adapters, afresh, deckstate, drain, house, idleclose, rotate, shipidle, shipping, shipreoffer, shipreplies
from keel.board import SHIPPING_OPTION, Board, Refused
from tests.helpers import SESSION, FakeHarness, FakeMachine, aged, background_row, make_config

MON_10 = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
RECORD = """---
kind: outcome
card: {id}
title: Tidy the loader
---
# {id} Tidy the loader

## Where it stands

The loader is tidied and the pull request is open. THE-BUILD-RECORD-MARK

## Evidence

The suite, green.
"""
DIFF = "diff --git a/app/loader.py b/app/loader.py\n+CAP = 40\n"
FRESH = "f00dcafe-0000-4000-8000-000000000009"
THIRD = "abadcafe-0000-4000-8000-00000000000a"


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def sight(comments=(), reviews=(), state="open", ci=None):
    return {"state": state, "url": "https://example.invalid/pr/4150", "head": "abc", "behind": 0,
            "approvals": 0, "comments": list(comments), "reviews": list(reviews),
            "ci": ci or {"state": "none"}}


def comment(number: int, at: datetime, text="Why is the cap 40?"):
    return {"id": number, "author": "Ana Example", "at": at.isoformat(), "text": text,
            "path": "app/loader.py", "line": 40, "parent": None}


class ShippingCase(unittest.TestCase):
    AUTO = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = self.config()
        self.cfg.host = "mac"
        self.cfg.work_hours, self.cfg.work_days = "00:00-24:00", "mon-sun"
        # these suites are of AUTOMATIC handling; off, the default, is tests/test_shipauto.py's,
        # which leaves the switches as the config gave them
        if self.AUTO:
            self.cfg.spaces["work"].ship_auto_comments = self.cfg.spaces["work"].ship_auto_checks = True
        self.board = self.opened()
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        self.fake.stops = []
        for module in (house, shipping, drain, rotate):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        for patch in (mock.patch.object(drain, "machine", FakeMachine()),
                      mock.patch.object(house, "APP_LINK_PAUSE", 0),
                      mock.patch.dict(shipping.LAST_POLLED, {}, clear=True)):
            patch.start()
            self.addCleanup(patch.stop)
        self.work_adapter()
        self.card = self.shipped_card()

    def config(self):
        return make_config(self.dir)

    def opened(self) -> Board:
        return Board(self.cfg.db_path)

    # ----- the stand-in adapter -----

    def work_adapter(self):
        work = self.cfg.adapters_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        self.tree = self.dir / "tree"
        self.tree.mkdir()
        self.sight_file = self.dir / "sight.json"
        self.log = self.dir / "adapter.log"
        self.answers = self.dir / "answers.log"
        self.see(sight())
        script(work / "ship", f'echo "ship $*" >> {self.log}\n'
                              f'case "$2" in\n'
                              f'  poll) cat {self.sight_file} ;;\n'
                              f"  method) echo 'THE-ADAPTER-METHOD' ;;\n"
                              f'  reap) echo \'{{"removed": ["{self.tree}"], "kept": []}}\' ;;\n'
                              f'esac\n')
        script(work / "worktree", f'echo "{self.tree}"\n')
        script(work / "brief", 'echo "THE WORK BRIEF"\n')
        # the answer the real adapter gives a Ship: every reply it was handed is now on the host
        (self.dir / "answer.py").write_text(
            "import json, sys\n"
            "a = json.load(sys.stdin)\n"
            "open(sys.argv[1], 'a').write(json.dumps(a) + '\\n')\n"
            "r = a.get('replies') or []\n"
            "print(json.dumps({'shipping': True, 'shipped': True, 'pushed': {'api': 'abc123'},\n"
            "                  'ready': [], 'posted': [x['handle'] for x in r], 'sent': r}))\n")
        script(work / "publish", f'echo "publish $*" >> {self.log}\n'
                                 f'if [ "$2" = "--answer" ]; then python3 {self.dir / "answer.py"} {self.answers}\n'
                                 f'else echo \'{{"shipping": true}}\'; fi\n')

    def see(self, seen: dict) -> None:
        self.sight_file.write_text(json.dumps(seen))

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def shipped_card(self) -> str:
        card_id = self.board.create("work", "Tidy the loader", repo="api", actor="human",
                                    options={"pr": 4150, "branch": "feature/st-41001/tidy"})
        self.board.stage(card_id, "assigned", "human")
        self.board.claim(card_id, "mac", "drain")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="https://example.invalid/pr/4150")
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"shipping": True})
        (self.cfg.card_dir(card_id)).mkdir(parents=True, exist_ok=True)
        (self.cfg.card_dir(card_id) / "context.md").write_text(RECORD.format(id=card_id))
        return card_id

    def upkeep(self, at: datetime, slots: int = 1) -> dict:
        return shipping.upkeep(self.cfg, self.board, {"work"}, slots=slots, at=at)

    def shipped(self) -> dict:
        return self.board.get(self.card)["options"][SHIPPING_OPTION]

    def with_a_comment(self, at=MON_10, number=11, text="Why is the cap 40?"):
        """The baseline look, then a comment someone left, seen on the next look."""
        self.upkeep(at - timedelta(minutes=30))
        self.see(sight(comments=[comment(number, at, text)]))
        shipping.LAST_POLLED.clear()
        self.upkeep(at)

    def live(self, status="idle"):
        """The card's build house, still listed: it lives on at shipping (c-600)."""
        self.fake.rows = [background_row(self.card, SESSION, status=status)]
        self.fake.relay_answer = "sent"

    def told_prompt(self) -> str:
        """The words the last tell pointed the house at (`state/cards/<id>/told/`)."""
        told = sorted((self.cfg.card_dir(self.card) / "told").iterdir())
        return told[-1].read_text()

    def told(self, at=MON_10 + timedelta(minutes=5)):
        """A comment, then the batch told to the live house once 5 quiet minutes passed."""
        self.live()
        self.with_a_comment()
        shipping.LAST_POLLED.clear()
        self.upkeep(at)

    def verdict(self, handle, verdict="valid", **fields):
        data = dict({"handle": handle, "verdict": verdict, "why": "checked against the code"}, **fields)
        return self.board.verdict(self.card, data, "house", self.card)


class WatchTest(ShippingCase):
    def test_a_shipping_card_is_looked_at_and_its_first_look_is_a_baseline(self):
        self.see(sight(comments=[comment(1, MON_10 - timedelta(days=1))]))
        result = self.upkeep(MON_10)
        self.assertEqual(result["polled"], 1)
        self.assertEqual(self.calls(), [f"ship {self.card} poll"])
        shipped = self.shipped()
        self.assertEqual(shipped["seen"]["comments"], [1])
        self.assertEqual(shipped["pending"], [])
        self.assertEqual(shipped["facts"]["state"], "open")

    def test_the_cadence_decides_when_it_looks_again(self):
        # the approve is activity: every 3 minutes for its first hour, then 10 in work hours
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: {"since": MON_10.isoformat(), "round": 0}}}, "drain")
        self.upkeep(MON_10)
        self.upkeep(MON_10 + timedelta(minutes=2))
        self.assertEqual(len(self.calls()), 1)
        self.upkeep(MON_10 + timedelta(minutes=3))
        self.assertEqual(len(self.calls()), 2)
        self.upkeep(MON_10 + timedelta(hours=2))
        self.upkeep(MON_10 + timedelta(hours=2, minutes=9))
        self.assertEqual(len(self.calls()), 3, "quiet for an hour: every 10 minutes")
        self.upkeep(MON_10 + timedelta(hours=2, minutes=10))
        self.assertEqual(len(self.calls()), 4)

    def test_waiting_items_are_looked_at_every_two_minutes(self):
        self.with_a_comment()
        before = len(self.calls())
        self.upkeep(MON_10 + timedelta(minutes=1))
        self.assertEqual(len(self.calls()), before)
        self.upkeep(MON_10 + timedelta(minutes=2))
        self.assertEqual(len(self.calls()), before + 1)

    def test_a_look_that_finds_nothing_new_writes_nothing(self):
        self.upkeep(MON_10)
        before = len(self.board.events(self.card))
        self.upkeep(MON_10 + timedelta(minutes=20))
        self.assertEqual(len(self.board.events(self.card)), before)

    def test_only_shipping_cards_of_the_spaces_served_here_are_looked_at(self):
        self.upkeep(MON_10)
        other = self.board.create("work", "not shipped", repo="api", options={"pr": 9})
        self.assertEqual(shipping.upkeep(self.cfg, self.board, {"personal"}, slots=1, at=MON_10 + timedelta(hours=2))["polled"], 0)
        self.assertNotIn(other, "\n".join(self.calls()))

class BatchToldTest(ShippingCase):
    """c-600: the batch goes to the card's OWN house, in its own session; the card stays at
    shipping; nothing is rotated, started or stopped."""

    def test_a_comment_waits_five_quiet_minutes_then_is_told_into_the_same_session(self):
        self.live()
        self.with_a_comment()
        self.upkeep(MON_10 + timedelta(minutes=4))
        self.assertEqual(getattr(self.fake, "relays", []), [], "not quiet for 5 minutes yet")
        result = self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(result["told"], [self.card])
        self.assertEqual(len(self.fake.relays), 1)
        self.assertEqual((self.fake.starts, self.fake.resumes, self.fake.stops), ([], [], []))
        card = self.board.get(self.card)
        self.assertEqual((card["stage"], card["session_id"]), ("shipping", SESSION))
        prompt = self.told_prompt()
        for words in ("c11", "Why is the cap 40?", "THE-ADAPTER-METHOD", f"kb verdict {self.card}",
                      f"keel check {self.card}", "never push"):
            self.assertIn(words, prompt)
        shipped = self.shipped()
        self.assertEqual(([i["handle"] for i in shipped["told"]], shipped["round"], shipped["pending"]), (["c11"], 1, []))
        self.assertEqual(shipped["told"][0]["batch"], 1)
        self.assertTrue(any("told in its session" in (e.get("text") or "") for e in self.board.events(self.card)))

    def test_more_comments_are_batched_together_and_capped_at_thirty_minutes(self):
        self.live()
        self.upkeep(MON_10 - timedelta(minutes=30))
        found = []
        for minute in range(0, 40, 4):
            found.append(comment(100 + minute, MON_10 + timedelta(minutes=minute), f"note {minute}"))
            self.see(sight(comments=list(found)))
            shipping.LAST_POLLED.clear()
            self.upkeep(MON_10 + timedelta(minutes=minute))
            if getattr(self.fake, "relays", []):
                break
        self.assertEqual(len(self.fake.relays), 1, "told once, at the cap")
        self.assertEqual(minute, 32, "never quiet for 5 minutes, so the 30-minute cap sends it")
        self.assertGreaterEqual(len(self.shipped()["told"]), 7)

    def test_a_failed_check_waits_five_minutes_and_a_rerun_that_passes_takes_it_back(self):
        self.live()
        self.upkeep(MON_10 - timedelta(minutes=30))
        self.see(sight(ci={"state": "failed", "name": "unit tests", "url": "https://example.invalid/ci/1"}))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10)
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["ci"])
        self.see(sight(ci={"state": "passed"}))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=3))
        self.assertEqual(self.shipped()["pending"], [])
        self.see(sight(ci={"state": "failed", "name": "unit tests"}))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=4))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=9))
        self.assertEqual([i["handle"] for i in self.shipped()["told"]], ["ci"])
        self.assertIn("unit tests failed", self.told_prompt())

    def test_changes_requested_goes_at_once(self):
        self.live()
        self.upkeep(MON_10 - timedelta(minutes=30))
        self.see(sight(reviews=[{"author": "Ana Example", "state": "changes_requested", "at": MON_10.isoformat()}]))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10)
        self.assertEqual(len(self.fake.relays), 1)
        self.assertEqual([i["handle"] for i in self.shipped()["told"]], ["review-ana-example"])

    def test_an_exited_house_is_resumed_once_with_the_batch(self):
        self.with_a_comment()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.fake.resumes[0]["session_id"], SESSION)
        self.assertIn("c11", self.fake.resumes[0]["prompt"])
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(self.board.get(self.card)["stage"], "shipping")
        self.upkeep(MON_10 + timedelta(minutes=6))
        self.assertEqual(len(self.fake.resumes), 1, "once")

    def test_a_house_he_stopped_is_not_resumed_by_a_batch(self):
        """c-605: his Stop keeps the house down; the batch waits for his Resume."""
        self.with_a_comment()
        self.board.note(self.card, "session stopped from the deck", "human", mark="human-stop")
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual((self.fake.resumes, self.fake.starts), ([], []))
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c11"], "kept, not dropped")
        self.assertTrue(self.board.get(self.card)["derived"]["held_by_stop"])
        self.upkeep(MON_10 + timedelta(minutes=5, seconds=30))
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertEqual(notes.count(shipping.HELD_BATCH_NOTE), 1, "said on the card, once")
        self.board.record_event(self.card, "resume", "human")          # his Resume
        self.assertFalse(self.board.get(self.card)["derived"]["held_by_stop"])
        self.upkeep(MON_10 + timedelta(minutes=6))
        self.assertEqual(len(self.fake.resumes), 1)

    def test_a_house_he_closed_idle_is_resumed_by_the_next_batch(self):
        """c-607: unlike his Stop, Close idle house expects the next batch to bring it back,
        with its conversation (the same session resumed), and says nothing is held."""
        self.with_a_comment()
        self.board.note(self.card, "session closed while idle", "human", mark="closed-idle")
        self.assertTrue(self.board.get(self.card)["derived"]["closed_idle"])
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.fake.resumes[0]["session_id"], SESSION, "its conversation continues")
        self.assertEqual(self.fake.starts, [])
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertNotIn(shipping.HELD_BATCH_NOTE, notes)
        self.assertFalse(self.board.get(self.card)["derived"]["closed_idle"], "the resume ends it")

    def test_every_batch_waits_for_a_slot_told_or_resumed_and_is_never_dropped(self):
        # c-600 review: a tell starts a turn as much as a resume does
        self.with_a_comment()
        self.upkeep(MON_10 + timedelta(minutes=5), slots=0)
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c11"])
        self.live()
        self.upkeep(MON_10 + timedelta(minutes=6), slots=0)
        self.assertEqual(getattr(self.fake, "relays", []), [])
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c11"], "queued, not dropped")
        self.upkeep(MON_10 + timedelta(minutes=7), slots=1)
        self.assertEqual(len(self.fake.relays), 1)
        self.assertEqual(self.shipped()["pending"], [])

    def test_a_working_house_is_not_told_and_the_batch_waits(self):
        self.live(status="busy")
        self.with_a_comment()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual((getattr(self.fake, "relays", []), self.fake.resumes), ([], []))
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c11"])
        self.live()
        self.upkeep(MON_10 + timedelta(minutes=6))
        self.assertEqual(len(self.fake.relays), 1)

    def test_a_paused_drain_holds_the_batch(self):
        self.live()
        self.with_a_comment()
        self.cfg.drain_paused = True
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(getattr(self.fake, "relays", []), [])

    def test_a_card_that_never_had_a_house_gets_one_with_its_brief_and_the_batch(self):
        self.board.set_fields(self.card, {"session_id": None}, "drain")
        self.with_a_comment()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(len(self.fake.starts), 1)
        prompt = self.fake.starts[0]["prompt"]
        self.assertIn("THE WORK BRIEF", prompt)
        self.assertIn("c11", prompt)
        self.assertEqual(self.board.get(self.card)["stage"], "shipping")

    def test_a_batch_that_cannot_reach_the_house_goes_back_and_blocks_the_card(self):
        self.board.set_fields(self.card, {"session_id": None}, "drain")
        self.with_a_comment()
        self.fake.fail = "claude would not start"
        self.upkeep(MON_10 + timedelta(minutes=5))
        card = self.board.get(self.card)
        self.assertEqual(card["stage"], "shipping")
        self.assertIn("claude would not start", card["blocked_reason"])
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c11"])


class ApproveKeepsTheHouseTest(ShippingCase):
    """c-600: Approve outcome moves a work card to shipping and ends nothing."""

    def test_kb_approve_of_a_work_card_does_not_stop_its_house(self):
        from keel import cli
        card_id = self.board.create("work", "another", repo="api", actor="human", options={"pr": 7})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.fake.rows = [background_row(card_id, SESSION)]
        args = mock.Mock(id=card_id, gate="outcome", said=None, checked=None, relay=None, to=None,
                         config=self.cfg)
        with mock.patch.object(house, "retire_finished") as retired:
            card = cli.cmd_approve(self.board, args, "human")
        self.assertEqual(card["stage"], "shipping")
        retired.assert_not_called()

class VerdictTest(ShippingCase):
    def test_the_house_records_one_verdict_per_told_item_and_the_newest_wins(self):
        self.told()
        self.verdict("c11", "not-valid", reply="The cap is the host's page size.", summary="why 40")
        self.verdict("c11", "valid", reply="Named the constant.", commits=[{"sha": "abc1234", "diff": "+PAGE = 40"}])
        rows = deckstate.detail(self.cfg, self.board, self.card)["shipping"]["rows"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["handle"], row["verdict"]["verdict"], row["choice"], row["words"]),
                         ("c11", "valid", "post", "Named the constant."))
        self.assertEqual(row["verdict"]["commits"][0]["diff"], "+PAGE = 40")
        self.assertEqual(row["item"]["text"], "Why is the cap 40?")

    def test_only_the_cards_own_house_may_record_one(self):
        self.told()
        data = {"handle": "c11", "verdict": "valid", "why": "w", "reply": "r"}
        with self.assertRaisesRegex(Refused, "own house"):
            self.board.verdict(self.card, data, "house", "c-999")
        with self.assertRaisesRegex(Refused, "own house"):
            self.board.verdict(self.card, data, "human", None)

    def test_a_verdict_is_held_to_its_shape(self):
        self.told()
        cases = [({"handle": "c99"}, "not an item you were told"),
                 ({"verdict": "maybe"}, "one of"),
                 ({"why": ""}, "says why"),
                 ({"verdict": "not-valid", "reply": ""}, "gets a reply"),
                 ({"verdict": "not-valid", "reply": "no", "commits": [{"sha": "abc1234"}]}, "only a valid"),
                 ({"reply": ""}, "code change"),
                 ({"reply": "x" * 4001}, "longer than")]
        for change, said in cases:
            data = dict({"handle": "c11", "verdict": "valid", "why": "w", "reply": "fine"}, **change)
            with self.subTest(said=said), self.assertRaisesRegex(Refused, said):
                self.board.verdict(self.card, data, "house", self.card)

    def test_no_verdict_away_from_shipping(self):
        self.told()
        self.board.stage(self.card, "done", "drain")
        with self.assertRaisesRegex(Refused, "not shipping"):
            self.verdict("c11", reply="x")


class ShipTest(ShippingCase):
    """His Ship posts only the replies he kept, each once; the card stays at shipping."""

    def at_three_rows(self):
        self.live()
        self.upkeep(MON_10 - timedelta(minutes=30))
        self.see(sight(comments=[comment(11, MON_10), comment(12, MON_10, "Nit: a blank line"),
                                 comment(13, MON_10, "Use a dict here")]))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10)
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.verdict("c11", "valid", reply="Named the constant.", commits=[{"sha": "abc1234", "diff": "+PAGE"}])
        self.verdict("c12", "valid", commits=[{"sha": "def5678", "diff": "-\n"}])
        self.verdict("c13", "not-valid", reply="A list keeps the order the host sends.")

    def ship(self):
        return self.board.ship(self.card, "human", adapters.publisher(self.cfg, "work"))

    def answers_sent(self):
        return [json.loads(line) for line in self.answers.read_text().splitlines() if line.strip()]

    def mark(self, row, choice, other=None):
        data = {"what": "answer", "doc": "shipping", "block": "replies", "row": row, "choice": choice}
        if other:
            data["other"] = other
        self.board.mark(self.card, data, "human")

    def test_ship_posts_only_kept_replies_with_his_words_and_only_once(self):
        self.at_three_rows()
        self.mark("c13", "edit", "A list keeps the host's order; a dict would lose it.")
        self.mark("c11", "drop")
        card = self.ship()
        self.assertEqual(card["stage"], "shipping")
        self.assertIn(f"publish {self.card} --answer", self.calls())
        self.assertEqual(self.answers_sent(), [{"ship": True, "lease": {}, "replies": [
            {"handle": "c13", "text": "A list keeps the host's order; a dict would lose it."}]}])
        rows = {r["handle"]: r for r in deckstate.detail(self.cfg, self.board, self.card)["shipping"]["rows"]}
        self.assertTrue(rows["c13"]["posted"])
        self.assertFalse(rows["c11"]["posted"])
        self.assertIn("shipped", self.board.events(self.card)[-1]["text"])
        with self.assertRaisesRegex(adapters.AdapterError, "nothing to ship"):
            self.ship()                    # nothing twice, and an empty Ship never runs
        self.assertEqual(len(self.answers_sent()), 1)
        self.mark("c11", "post")
        self.ship()
        self.assertEqual(self.answers_sent()[-1]["replies"], [{"handle": "c11", "text": "Named the constant."}])

    def test_ship_is_his_and_only_at_shipping(self):
        self.at_three_rows()
        with self.assertRaisesRegex(Refused, "human's alone"):
            self.board.ship(self.card, "house", adapters.publisher(self.cfg, "work"))
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: dict(self.shipped(), state="declined")}}, "drain")
        with self.assertRaisesRegex(Refused, "declined"):
            self.ship()
        self.assertFalse(self.answers.exists())

    def test_a_publish_that_fails_records_nothing(self):
        self.at_three_rows()
        def boom(card):
            raise adapters.AdapterError("git push refused")
        with self.assertRaisesRegex(adapters.AdapterError, "push refused"):
            self.board.ship(self.card, "human", boom)
        self.assertEqual(self.shipped().get("posted") or {}, {})

    def test_a_first_approve_hands_the_adapter_nothing_on_stdin(self):
        card_id = self.board.create("work", "another", repo="api", actor="human", options={"pr": 7})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        card = self.board.approve(card_id, "outcome", "human", publish=adapters.publisher(self.cfg, "work"))
        self.assertEqual(card["stage"], "shipping")
        self.assertIn(f"publish {card_id}", self.calls())
        self.assertFalse(self.answers.exists())


class MergeAndDeclineTest(ShippingCase):
    def test_a_merged_pull_request_moves_the_card_to_done_and_reaps_its_worktree(self):
        self.upkeep(MON_10)
        self.see(sight(state="merged"))
        shipping.LAST_POLLED.clear()
        result = self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(result["merged"], 1)
        self.assertEqual(self.board.get(self.card)["stage"], "done")
        self.assertIn(f"ship {self.card} reap", self.calls())
        self.assertTrue(any("reaped" in (e.get("text") or "") for e in self.board.events(self.card)))

    def test_a_declined_pull_request_is_a_note_and_the_card_stays(self):
        self.upkeep(MON_10)
        self.see(sight(state="declined"))
        for minute in (5, 10):
            shipping.LAST_POLLED.clear()
            self.upkeep(MON_10 + timedelta(minutes=minute))
        card = self.board.get(self.card)
        self.assertEqual(card["stage"], "shipping")
        self.assertEqual(self.shipped()["state"], "declined")
        notes = [e for e in self.board.events(self.card) if "declined" in (e.get("text") or "")]
        self.assertEqual(len(notes), 1, "said once")
        self.assertNotIn(f"ship {self.card} reap", self.calls(), "a card not done keeps its worktree")
        self.see(sight())
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=15))
        self.assertNotIn("state", self.shipped())
        self.assertTrue(any("open again" in (e.get("text") or "") for e in self.board.events(self.card)))


def two_prs(api=None, web=None) -> dict:
    """The sight of a card with a pull request in each of its repos (SH-10)."""
    first = dict(sight(**(api or {})), repo="api", pr=4150, primary=True)
    second = dict(sight(**(web or {})), repo="web", pr=2190,
                  url="https://example.invalid/pr/2190")
    return {"state": "open", "url": first["url"], "head": "abc", "prs": [first, second]}


class TwoPullRequestsTest(ShippingCase):
    """SH-10: a card with a pull request in each repo is watched as one: both in one batch,
    and done only when both have merged."""

    def test_comments_on_both_pull_requests_go_in_one_batch(self):
        self.live()
        self.see(two_prs())
        self.upkeep(MON_10 - timedelta(minutes=30))
        self.see(two_prs(api={"comments": [comment(11, MON_10)]},
                         web={"comments": [comment(21, MON_10, text="Rename the prop")]}))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10)
        result = self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(result["told"], [self.card])
        self.assertEqual([i["handle"] for i in self.shipped()["told"]], ["c11", "web.c21"])
        self.assertIn("Rename the prop", self.told_prompt())

    def test_the_card_is_done_only_when_both_have_merged(self):
        self.see(two_prs())
        self.upkeep(MON_10)
        self.see(two_prs(api={"state": "merged"}))
        shipping.LAST_POLLED.clear()
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=5))["merged"], 0)
        self.assertEqual(self.board.get(self.card)["stage"], "shipping")
        facts = self.shipped()["facts"]
        self.assertEqual([p["state"] for p in facts["prs"]], ["merged", "open"])
        self.see(two_prs(api={"state": "merged"}, web={"state": "merged"}))
        shipping.LAST_POLLED.clear()
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=10))["merged"], 1)
        self.assertEqual(self.board.get(self.card)["stage"], "done")


class WholeCommentTest(ShippingCase):
    """c-580: every comment's whole text is kept in the card's `comments/`, once."""

    def test_a_look_keeps_each_comment_whole_and_rewrites_only_what_changed(self):
        long = "a very long remark " * 200
        self.see(two_prs(api={"comments": [comment(11, MON_10)]},
                         web={"comments": [comment(21, MON_10, text=long)]}))
        self.upkeep(MON_10)
        folder = self.cfg.card_dir(self.card) / "comments"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["c11.md", "web.c21.md"])
        self.assertIn(long, (folder / "web.c21.md").read_text())
        kept = folder / "c11.md"
        os.utime(kept, (1, 1))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(kept.stat().st_mtime, 1, "an unchanged comment is not written again")


class GoneConversationTest(ShippingCase):
    """c-654 (c-015, c-017, c-037): the harness keeps a transcript for its retention period
    only. A resume of a session whose conversation is gone launches normally and then fails
    with no turn, so the house is started afresh from the card's own record instead."""

    def gone(self, days=40):
        """The house was last used `days` days ago, and the harness holds its conversation no
        more; a comment waits for it."""
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        aged(self.board, self.card, days)
        self.with_a_comment()
        self.fake.gone = {SESSION}
        self.fake.started_as = FRESH

    def blocked(self) -> str:
        return self.board.get(self.card)["blocked_reason"] or ""

    def test_a_house_whose_conversation_is_gone_is_started_afresh_with_the_batch(self):
        self.gone()
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=5))["resumed"], [self.card])
        self.assertEqual(self.fake.failed, [], "the resume that could only fail was never launched")
        self.assertEqual(len(self.fake.starts), 1)
        prompt = self.fake.starts[0]["prompt"]
        for known in ("THE WORK BRIEF", "context.md", "feature/st-41001/tidy",
                      "https://example.invalid/pr/4150", "c11"):
            self.assertIn(known, prompt)
        self.assertLess(prompt.index("context.md"), prompt.index("c11"), "the record, then the batch")
        card = self.board.get(self.card)
        self.assertEqual((card["session_id"], card["stage"], card["blocked_reason"]), (FRESH, "shipping", None))
        self.assertEqual([i["handle"] for i in self.shipped()["told"]], ["c11"])
        notes = [e["text"] or "" for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertTrue(any(SESSION in note and FRESH[:8] in note for note in notes),
                        "the old session's whole id is kept, so he can look for it by hand")
        self.assertEqual(self.fake.gone_asked, [(SESSION, str(self.tree), str(self.cfg.spaces["work"].config_dir))],
                         "asked once, where the resume itself would have run")

    def test_a_conversation_reported_gone_that_the_card_shows_used_last_week_blocks_and_starts_nothing(self):
        """c-654 review: one answer of the harness never replaces a session. A transcript is
        kept 30 days, so "gone" five days after a turn is two facts that disagree: his."""
        self.gone(days=5)
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual((self.fake.starts, self.fake.resumes), ([], []), "nothing started, nothing resumed")
        self.assertEqual(self.board.get(self.card)["session_id"], SESSION, "the card keeps its session")
        self.assertIn(SESSION, self.blocked())
        self.assertIn("5 days ago", self.blocked())
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c11"], "the batch waits")

    def test_a_doomed_resume_and_its_session_end_are_not_use(self):
        """c-015, c-017, c-037: the last Stop 40 days ago, then the resume of 2026-10-05 that
        launched and ended with no turn. A resume and a SessionEnd are not a turn: afresh."""
        self.gone()
        self.board.record_resume(self.card, "drain", "the batch", {"session_id": SESSION, "bg_id": SESSION[:8]})
        self.board.record_hook(self.card, "SessionEnd", {"session_id": SESSION, "reason": "other"})
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=5))["resumed"], [self.card])
        self.assertEqual((len(self.fake.starts), self.fake.resumes), (1, []))
        self.assertEqual((self.board.get(self.card)["session_id"], self.blocked()), (FRESH, ""))

    def test_his_unblock_of_the_withheld_block_is_his_answer_and_nobody_else_s(self):
        """The way out of "gone, but used 5 days ago" is his unblock: the next resume then
        starts afresh. With no unblock, or the drain's, it is withheld again."""
        self.gone(days=5)
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertIn("unblock the card yourself", self.blocked())
        with self.assertRaises(afresh.Withheld):
            house.resume(self.cfg, self.board, self.card)
        self.board.unblock(self.card, "drain")
        with self.assertRaises(afresh.Withheld):
            house.resume(self.cfg, self.board, self.card)
        self.assertEqual(self.fake.starts, [])
        self.board.unblock(self.card, "human")
        shipping.LAST_POLLED.clear()
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=10))["resumed"], [self.card])
        self.assertEqual((len(self.fake.starts), self.fake.resumes), (1, []))
        self.assertEqual((self.board.get(self.card)["session_id"], self.blocked()), (FRESH, ""))

    def test_a_listed_session_is_resumed_as_ever_and_never_asked_about(self):
        """c-654 review: a session the harness lists with a process has a conversation by
        being alive. A fresh house beside it would be a twin nothing owns, so it is never
        asked about: the tell that failed falls back to the plain resume."""
        self.gone()
        self.fake.rows = [background_row(self.card, SESSION)]
        self.fake.relay_answer = "failed"
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(getattr(self.fake, "gone_asked", []), [])
        self.assertEqual((len(self.fake.starts), len(self.fake.resumes)), (0, 1))

    def test_a_fresh_house_whose_conversation_is_gone_too_is_not_started_again(self):
        """c-654 review: the fresh house died in its first seconds (no turn ever ended), the
        class this card is about. A second fresh start is refused and both sessions named."""
        self.gone()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(self.board.get(self.card)["session_id"], FRESH)
        self.fake.gone = {SESSION, FRESH}
        self.see(sight(comments=[comment(11, MON_10), comment(12, MON_10 + timedelta(minutes=6))]))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=7))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=13))
        self.assertEqual(len(self.fake.starts), 1, "exactly one fresh start")
        self.assertIn(SESSION, self.blocked())
        self.assertIn(FRESH, self.blocked())
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c12"])
        # his way out (c-654 review): his own unblock allows exactly one more fresh start
        self.assertIn("unblock the card yourself", self.blocked())
        self.board.unblock(self.card, "human")
        self.fake.started_as = THIRD
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=20))
        self.assertEqual((len(self.fake.starts), self.board.get(self.card)["session_id"]), (2, THIRD))
        self.fake.gone = {SESSION, FRESH, THIRD}
        with self.assertRaises(afresh.Withheld):
            house.resume(self.cfg, self.board, self.card)
        self.assertEqual(len(self.fake.starts), 2, "one more, not as many as he likes")

    def test_a_turn_under_the_session_before_this_one_is_use_too(self):
        """c-654 review: a resume mints a new id. A session minted yesterday that died before
        its first Stop has no turn of its own, but the card shows the conversation in use the
        day before under the id it had then: withheld, with both ids named."""
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.board.record_resume(self.card, "drain", "carry on", {"session_id": THIRD, "bg_id": THIRD[:8]})
        aged(self.board, self.card, 1)
        self.with_a_comment()
        self.fake.gone, self.fake.started_as = {THIRD}, FRESH
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual((self.fake.starts, self.fake.resumes), ([], []))
        self.assertIn("1 day ago", self.blocked())
        self.assertIn(THIRD, self.blocked())
        self.assertIn(SESSION, self.blocked())

    def test_his_answer_outlives_a_block_that_restates_the_refusal_and_no_other(self):
        """c-654 review: a caller that caught the refusal blocked again on top of it (Bosun's
        resume repair, a carried tap), and his unblock was then never read as his answer."""
        self.gone(days=5)
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.board.block(self.card, "the reviewer asked which cap is meant", "house")
        self.board.unblock(self.card, "human")
        with self.assertRaises(afresh.Withheld):
            house.resume(self.cfg, self.board, self.card)       # that unblock answered the question
        self.board.block(self.card, f"Bosun's resume failed: {self.blocked()}", "drain", mark="failed-resume")
        self.board.unblock(self.card, "human")
        shipping.LAST_POLLED.clear()
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=10))["resumed"], [self.card])
        self.assertEqual((len(self.fake.starts), self.board.get(self.card)["session_id"]), (1, FRESH))

    def test_a_listing_that_failed_is_never_read_as_no_process(self):
        """c-654 review: `claude agents` failing answers an empty listing. Where a session is
        about to be replaced the harness is asked again, strictly: resumed as before."""
        self.gone()
        self.fake.listing_fails = True
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(getattr(self.fake, "gone_asked", []), [])
        self.assertEqual((len(self.fake.starts), len(self.fake.resumes)), (0, 1))

    def test_a_fresh_start_that_fails_puts_the_batch_back_and_blocks_the_card(self):
        self.gone()
        self.fake.fail = "claude would not start"
        self.upkeep(MON_10 + timedelta(minutes=5))
        card = self.board.get(self.card)
        self.assertIn("claude would not start", card["blocked_reason"])
        self.assertIn(SESSION[:8], card["blocked_reason"], "and why a start was tried at all")
        self.assertTrue(card["derived"]["needs_you"])
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c11"])
        self.assertEqual(self.fake.failed, [])


class DrainWiringTest(ShippingCase):
    def test_the_drain_pass_tells_a_live_house_only_with_room_in_the_pool(self):
        self.live()
        self.with_a_comment()
        self.cfg.houses_max = 0
        with mock.patch.object(shipping, "now", return_value=MON_10 + timedelta(minutes=5)):
            drain.once(self.cfg, board=self.board)
        self.assertEqual(getattr(self.fake, "relays", []), [])
        self.cfg.houses_max = 2
        with mock.patch.object(shipping, "now", return_value=MON_10 + timedelta(minutes=6)):
            summary = drain.once(self.cfg, board=self.board)
        self.assertEqual(summary.get("ship_resumed"), 1, "a tell takes a slot")
        self.assertEqual(len(self.fake.relays), 1)
        self.assertEqual(self.board.get(self.card)["stage"], "shipping")

    def test_a_resume_counts_in_the_house_pool_and_a_full_pool_holds_it(self):
        self.with_a_comment()
        self.cfg.houses_max = 0
        with mock.patch.object(shipping, "now", return_value=MON_10 + timedelta(minutes=5)):
            drain.once(self.cfg, board=self.board)
        self.assertEqual(self.fake.resumes, [])
        self.cfg.houses_max = 2
        with mock.patch.object(shipping, "now", return_value=MON_10 + timedelta(minutes=6)):
            summary = drain.once(self.cfg, board=self.board)
        self.assertEqual(summary.get("ship_resumed"), 1)
        self.assertEqual(len(self.fake.resumes), 1)

    def test_a_shipping_house_holds_a_slot_only_while_it_works(self):
        card = self.board.get(self.card)
        self.assertFalse(drain.holds_slot(self.board, card, [background_row(self.card, SESSION)]))
        self.assertTrue(drain.holds_slot(self.board, card, [background_row(self.card, SESSION, status="busy")]))

    def test_a_done_card_keeps_its_listed_house_for_his_stop_and_holds_no_slot(self):
        # the merge made it done: nothing automatic ends the session, so the deck must draw it
        card = dict(self.board.get(self.card), stage="done")
        idle = [background_row(self.card, SESSION)]
        self.assertIsNotNone(deckstate.live_house(card, idle))
        self.assertIsNone(deckstate.live_house(card, []))
        self.assertFalse(drain.holds_slot(self.board, card, idle))
        view = dict(card, house={"status": "idle"}, derived={"archived": False, "backlog": False, "tracking": False})
        self.assertEqual(deckstate.houses_of([view]), [])
        self.assertEqual(deckstate.houses_of([dict(view, house={"status": "busy"})]), [self.card])


class ReofferTest(ShippingCase):
    """c-651: `kb ship <id> reoffer` offers the house the review the baseline hid (c-239: nine
    comments, told none), the drain tells or resumes it at once, and once the house's turn on
    that batch ends it is stopped (his word); a normal batch keeps the two-hour close."""

    def setUp(self):
        super().setUp()
        for module in (shipidle, idleclose):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)

    def baselined(self):
        """Three comments and a changes-requested review from before the card shipped, all
        baselined as seen; c2 was told since and his Ship posted a reply to c3."""
        old = MON_10 - timedelta(days=1)
        self.see(sight(comments=[comment(1, old), comment(2, old, "Rename it"), comment(3, old, "Typo")],
                       reviews=[{"author": "Bo Example", "state": "changes_requested", "at": old.isoformat()}]))
        self.upkeep(MON_10 - timedelta(minutes=30))
        shipped = self.shipped()
        self.assertEqual((shipped["pending"], shipped.get("told")), ([], None), "the baseline told nothing")
        shipped.update(told=[{"kind": "comment", "handle": "c2", "batch": 1, "told_at": old.isoformat()}],
                       posted={"c3": "digest"}, round=1)
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        self.judged("c2")

    def judged(self, *handles):
        """The house's verdict on each: an item told and judged is never offered again (c-654)."""
        for handle in handles:
            self.verdict(handle, "not-valid", reply="No: it is the documented cap.")

    def reoffered(self, at=MON_10):
        """A live house, its baseline, his re-offer, and the batch told into its session."""
        self.live()
        self.baselined()
        self.board.reoffer(self.card, "human")
        self.upkeep(at)
        self.assertEqual(self.shipped()["reoffer"]["batch"], 2)

    def close_pass(self, at=MON_10 + timedelta(minutes=1)) -> list[str]:
        return shipidle.upkeep(self.cfg, self.board, list(self.fake.rows), {"work"}, at=at)["closed"]

    def options(self) -> dict:
        return self.board.get(self.card)["options"]

    def notes(self) -> list[str]:
        return [e["text"] or "" for e in self.board.events(self.card) if e["kind"] == "note"]

    def test_reoffer_puts_the_untold_human_review_in_the_batch_and_the_next_pass_tells_it(self):
        self.live()
        self.baselined()
        for actor in ("house", "bosun"):
            with self.assertRaises(Refused, msg="the ask is his alone"):
                self.board.reoffer(self.card, actor)
        self.board.reoffer(self.card, "human")
        self.upkeep(MON_10, slots=0)            # the ask looks at once; no room to tell yet
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c1", "review-bo-example"],
                         "c2 was told and c3 posted; only what the house never had")
        self.assertNotIn("reoffer", self.options(), "the ask is answered")
        self.assertEqual(self.upkeep(MON_10 + timedelta(seconds=30))["told"], [self.card], "due at once")
        prompt = self.told_prompt()
        self.assertIn("Why is the cap 40?", prompt)
        self.assertNotIn("Typo", prompt)
        self.assertEqual(self.shipped()["reoffer"]["batch"], 2)

    def test_rebase_adds_one_merge_item_and_an_exited_house_is_resumed_with_it(self):
        self.baselined()
        self.board.set_fields(self.card, {"options": {"base": "main"}}, "human")
        shipped = self.shipped()
        shipped["told"] += [{"kind": "comment", "handle": h, "batch": 1} for h in ("c1", "review-bo-example")]
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        self.judged("c1", "review-bo-example")
        with self.assertRaises(Refused, msg="nothing to offer, not behind, no --rebase"):
            self.board.reoffer(self.card, "human")
        self.board.reoffer(self.card, "human", rebase=True)
        self.upkeep(MON_10)
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual([i["handle"] for i in self.shipped()["told"] if i.get("batch") == 2], ["rebase"])
        prompt = self.fake.resumes[0]["prompt"]
        # his Ship's push is a plain fast-forward: the house merges the base in, never rewrites
        self.assertIn("git merge origin/main", prompt)
        self.assertNotIn("rebase onto", prompt)
        self.assertIn("never `git push --force`", " ".join(prompt.split()),
                      "a force push is named only to forbid it")

    def test_the_rebase_takes_the_pull_request_s_own_base_and_is_refused_without_one(self):
        self.baselined()
        self.see(dict(sight(), base="develop"))      # the destination the sight names
        self.board.reoffer(self.card, "human", rebase=True)
        self.upkeep(MON_10)
        self.assertIn("git merge origin/develop", self.fake.resumes[0]["prompt"])
        self.assertEqual(self.shipped()["base"], "develop", "kept for the conflict check")
        # a card whose base nothing names: no guess, the --rebase is refused on the card
        shipped = self.shipped()
        shipped.pop("base")
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        self.see(sight())
        self.board.reoffer(self.card, "human", rebase=True)
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertNotIn("rebase", [i["handle"] for i in self.shipped()["pending"]])
        self.assertTrue(any("--rebase refused" in note for note in self.notes()), self.notes())

    def test_a_plain_reoffer_behind_with_no_base_says_so_and_never_claims_up_to_date(self):
        """No --rebase, nothing left to offer, the branch behind its base, and no base named
        by options.base or the pull request: no rebase item (never a guess), and the note
        says it is behind with no base to ask against, not that it is up to date."""
        self.baselined()
        shipped = self.shipped()
        shipped.pop("base", None)
        shipped["told"] += [{"kind": "comment", "handle": h, "batch": 1} for h in ("c1", "review-bo-example")]
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        self.judged("c1", "review-bo-example")
        self.see(dict(sight(), behind=4))
        self.upkeep(MON_10 - timedelta(minutes=10))
        self.assertEqual(self.shipped()["facts"]["behind"], 4)
        self.board.reoffer(self.card, "human")
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10)
        self.assertEqual(self.shipped()["pending"], [], "no base: no rebase item")
        self.assertNotIn("reoffer", self.options(), "the ask is answered")
        said = self.notes()[-1]
        self.assertNotIn("up to date", said)
        self.assertIn("behind its base", said)
        self.assertIn("set options.base", said)

    def test_the_house_is_stopped_once_its_turn_on_the_reoffered_batch_ends(self):
        self.reoffered()
        self.assertEqual(self.close_pass(), [], "its turn on the batch has not ended")
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.assertEqual(self.close_pass(), [self.card])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertTrue(self.board.get(self.card)["derived"]["closed_idle"], "its next batch resumes it")
        self.live()
        self.assertEqual(self.close_pass(), [], "closed once: listed again, it is not closed again")
        self.assertEqual(self.fake.stops, [SESSION[:8]])

    def test_the_close_follows_the_board_s_order_not_the_drain_s_clock(self):
        # the drain's clock an hour ahead of the board's (two machines): its Stop still counts
        self.reoffered(at=datetime.now(timezone.utc) + timedelta(hours=1))
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.assertEqual(self.close_pass(), [self.card])

    def test_a_later_turn_is_never_closed_by_the_re_offer(self):
        self.reoffered()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.fake.rows = [background_row(self.card, SESSION, status="busy")]
        self.assertEqual(self.close_pass(), [], "working again: left")
        # his Talk, a turn of its own in the same session, and its end
        self.board.record_resume(self.card, "human", "How is it going?", {"session_id": SESSION, "told": True})
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.live()
        self.assertEqual(self.close_pass(), [])
        self.assertEqual(self.fake.stops, [])
        self.assertTrue(self.shipped()["reoffer"].get("done_at"), "the re-offer is over")

    def test_a_resume_that_mints_a_new_session_closes_the_new_one(self):
        self.baselined()
        self.fake.resumed_as = FRESH              # the exited house comes back as a new session
        self.board.reoffer(self.card, "human")
        self.upkeep(MON_10)
        self.assertEqual(self.board.get(self.card)["session_id"], FRESH)
        self.fake.rows = [background_row(self.card, FRESH)]
        self.assertEqual(self.close_pass(), [], "its turn has not ended")
        self.board.record_hook(self.card, "Stop", {"session_id": FRESH})
        self.assertEqual(self.close_pass(), [self.card])
        self.assertEqual(self.fake.stops, [FRESH[:8]])

    def held_and_let_go(self, hold, release):
        """The batch's turn ended, then he talked to the house (a hold taken and let go)."""
        self.reoffered()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        hold()
        release()
        self.live()
        self.assertEqual(self.close_pass(), [], "the house he talked to is not closed")
        self.assertEqual(self.fake.stops, [])
        self.assertTrue(self.shipped()["reoffer"].get("done_at"))

    def test_his_voice_after_the_batch_ends_the_re_offer(self):
        self.held_and_let_go(lambda: self.board.hold_voice(self.card, 60),
                             lambda: self.board.release_voice(self.card))

    def test_his_drop_in_after_the_batch_ends_the_re_offer(self):
        held = {"at": MON_10.isoformat(), "session": SESSION, "seen": False}
        self.held_and_let_go(
            lambda: self.board.set_fields(self.card, {"options": {"dropin_hold": held}}, "human"),
            lambda: self.board.set_fields(self.card, {"options": {"dropin_hold": None}}, "drain"))

    def test_the_deck_says_a_re_offered_house_closes_now(self):
        self.reoffered()
        self.assertIsNone(self.board.get(self.card)["derived"]["ship_idle"])
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        idle = self.board.get(self.card)["derived"]["ship_idle"]
        self.assertTrue(idle["reoffer"])
        self.assertEqual(idle["close_at"], idle["since"], "closed on the drain's next pass, not at 2h")

    def test_a_superseded_re_offer_is_not_closed(self):
        self.reoffered()
        shipped = self.shipped()
        shipped["round"] = 3                     # a newer batch was told since
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.assertEqual(self.close_pass(), [])

    def test_a_ship_during_the_close_keeps_what_it_posted(self):
        self.reoffered()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        stop = self.fake.stop

        def shipped_meanwhile(bg_id, config_dir=None):
            shipped = self.shipped()
            shipped.update(posted=dict(shipped.get("posted") or {}, c1="d"), heads={"api": "beef"})
            self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "human")
            return stop(bg_id, config_dir)
        with mock.patch.object(self.fake, "stop", side_effect=shipped_meanwhile):
            self.assertEqual(self.close_pass(), [self.card])
        shipped = self.shipped()
        self.assertEqual((shipped["posted"].get("c1"), shipped.get("heads")), ("d", {"api": "beef"}))
        self.assertTrue(shipped["reoffer"].get("closed_at"))

    def test_a_failed_look_keeps_the_ask_at_the_cadence_and_the_third_clears_it_with_why(self):
        self.live()
        self.baselined()
        self.board.reoffer(self.card, "human")
        self.sight_file.write_text("not a sight")
        self.upkeep(MON_10)
        self.assertIn("reoffer", self.options(), "kept on a failed look")
        looks = len(self.calls())
        self.upkeep(MON_10 + timedelta(seconds=30))
        self.assertEqual(len(self.calls()), looks, "the next look waits for the cadence")
        for minutes in (30, 60):
            shipping.LAST_POLLED.clear()
            self.upkeep(MON_10 + timedelta(minutes=minutes))
        self.assertNotIn("reoffer", self.options())
        self.assertTrue(any("Expecting value" in note for note in self.notes()), "the note names the failure")

    def test_a_failed_look_never_brings_back_an_ask_cleared_meanwhile(self):
        self.baselined()
        self.board.reoffer(self.card, "human")
        card = self.board.get(self.card)
        self.board.block(self.card, "his hold", "human")      # cleared while the look ran
        shipping.look_failed(self.board, card, card["options"]["reoffer"], "timed out")
        self.assertNotIn("reoffer", self.options())

    def test_a_block_or_an_archive_clears_the_ask_with_a_note(self):
        self.baselined()
        self.board.reoffer(self.card, "human", rebase=True)
        self.board.block(self.card, "his hold", "human")
        self.assertNotIn("reoffer", self.options())
        self.board.unblock(self.card, "human")
        self.board.reoffer(self.card, "human", rebase=True)
        self.board.set_fields(self.card, {"options": {"archived": True}}, "human")
        self.assertNotIn("reoffer", self.options())
        self.assertEqual(sum("re-offer cleared" in note for note in self.notes()), 2, self.notes())

    def test_a_declined_look_answers_the_ask(self):
        self.baselined()
        self.board.reoffer(self.card, "human", rebase=True)
        self.see(sight(state="declined"))
        self.upkeep(MON_10)
        self.assertNotIn("reoffer", self.options())
        self.assertNotIn("reoffer", self.shipped(), "nothing is offered on a declined one")

    def test_a_merged_look_answers_the_ask_and_no_ask_outlives_shipping(self):
        self.baselined()
        self.board.reoffer(self.card, "human", rebase=True)
        self.see(sight(state="merged"))
        self.upkeep(MON_10)
        card = self.board.get(self.card)
        self.assertEqual((card["stage"], card["options"].get("reoffer")), ("done", None))

    def test_the_ask_is_refused_on_a_blocked_or_archived_card_and_cleared_off_shipping(self):
        self.baselined()
        self.board.block(self.card, "his hold", "human")
        with self.assertRaisesRegex(Refused, "blocked"):
            self.board.reoffer(self.card, "human", rebase=True)
        self.board.unblock(self.card, "human")
        self.board.set_fields(self.card, {"options": {"archived": True}}, "human")
        with self.assertRaisesRegex(Refused, "archived"):
            self.board.reoffer(self.card, "human", rebase=True)
        self.board.set_fields(self.card, {"options": {"archived": None}}, "human")
        self.board.reoffer(self.card, "human", rebase=True)
        for actor in ("human", "bosun"):
            with self.assertRaises(Refused, msg="the ask is written only by the verb"):
                self.board.set_fields(self.card, {"options": {"reoffer": {"by": actor}}}, actor)
        self.board.stage(self.card, "done", "human", note="merged by hand")
        self.assertNotIn("reoffer", self.options())

    def told_rebase(self):
        self.baselined()
        shipped = self.shipped()
        shipped["told"] += [{"kind": "rebase", "handle": "rebase", "batch": 2, "base": "main"}]
        shipped["round"] = 2
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")

    def test_a_rebase_item_is_answered_by_its_commit_or_deferred_and_never_posts(self):
        self.told_rebase()
        for verdict, fields in (("not-valid", {"reply": "No."}), ("deferred", {"reply": "Later."}),
                                ("valid", {"reply": "Done.", "commits": [{"sha": "abc1234", "diff": "d"}]})):
            with self.assertRaises(Refused, msg=f"{verdict} with a reply"):
                self.verdict("rebase", verdict, **fields)
        self.verdict("rebase", "deferred", why="the conflict needs his call on the schema")
        self.verdict("rebase", "valid", commits=[{"sha": "abc1234", "diff": "d"}])
        for choice, extra in (("post", {}), ("edit", {"other": "Merged main in."})):
            with self.assertRaises(Refused, msg=f"his {choice} on the rebase row"):
                self.board.mark(self.card, dict({"what": "answer", "doc": "shipping", "block": "replies",
                                                 "row": "rebase", "choice": choice}, **extra), "human")
        # an edit mark from before the refusal existed is still never posted
        self.board.record_event(self.card, "mark", "human", data={
            "what": "answer", "doc": "shipping", "block": "replies", "row": "rebase",
            "choice": "edit", "other": "Merged main in."})
        card = self.board.get(self.card)
        self.assertNotIn("rebase", [k["handle"] for k in shipreplies.kept(card, self.board.events(self.card))])

    def test_a_turn_that_ends_with_items_unjudged_is_handed_to_him_and_never_called_answered(self):
        """c-654 (c-151): the house's turn on a re-offered batch ended with a verdict on one
        item of two. The idle house is still closed, the card needs him with the item named,
        and nothing tells that batch again by itself."""
        self.reoffered()
        self.judged("c1")
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.assertEqual(self.close_pass(), [self.card], "an idle house holds no memory either way")
        card = self.board.get(self.card)
        self.assertEqual(self.shipped()["reoffer"]["unjudged"], ["review-bo-example"])
        self.assertTrue(card["derived"]["needs_you"])
        self.assertIn("review-bo-example", card["blocked_reason"])
        self.assertNotIn("c1,", card["blocked_reason"])
        told = len(self.fake.relays)
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=10))
        self.assertEqual((len(self.fake.relays), self.fake.resumes), (told, []), "never told again unasked")

    def test_a_house_that_exits_on_its_re_offered_batch_is_handed_to_him(self):
        """c-654: the harness said the session ended (SessionEnd) with no Stop and nothing
        judged, and it is listed no more: there is nothing to close, and the card needs him."""
        self.reoffered()
        self.board.record_hook(self.card, "SessionEnd", {"session_id": SESSION})
        self.fake.rows = []
        self.assertEqual(self.close_pass(), [])
        card = self.board.get(self.card)
        self.assertEqual(self.fake.stops, [])
        self.assertEqual(self.shipped()["reoffer"]["unjudged"], ["c1", "review-bo-example"])
        self.assertTrue(card["derived"]["needs_you"])

    def test_a_re_offer_includes_what_the_house_was_told_and_never_judged(self):
        """c-654 (c-151's second ask): told is not judged. An item with no verdict since it
        was told is offered again and its row starts afresh; a judged one is not."""
        self.reoffered()
        self.judged("c1")
        first = {i["handle"]: i["told_at"] for i in self.shipped()["told"]}
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.close_pass()
        self.board.unblock(self.card, "human")
        self.board.reoffer(self.card, "human")
        self.live()
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=10))
        again = [i for i in self.shipped()["told"] if i.get("batch") == 3]
        self.assertEqual([i["handle"] for i in again], ["review-bo-example"])
        self.assertNotEqual(again[0]["told_at"], first["review-bo-example"], "told afresh")
        rows = {r["handle"]: r for r in shipreplies.rows(self.board.get(self.card), self.board.events(self.card))}
        self.assertIsNone(rows["review-bo-example"]["verdict"])
        self.assertEqual(rows["c1"]["verdict"]["verdict"], "not-valid", "its verdict stands")

    def test_a_re_offer_asked_mid_turn_leaves_alone_what_the_house_is_still_on(self):
        """c-654 review: re-queued mid-turn, the items it was judging were told again and
        the verdicts it was writing thrown away. A batch whose own turn has not ended is the
        house's: the ask with nothing else to offer is refused, and one that does go through
        (a rebase) offers none of them."""
        self.board.set_fields(self.card, {"options": {"base": "main"}}, "human")
        self.reoffered()
        with self.assertRaises(Refused) as refused:
            self.board.reoffer(self.card, "human")
        self.assertIn("still on batch 2", str(refused.exception))
        self.board.reoffer(self.card, "human", rebase=True)
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=1))
        self.assertEqual([i["handle"] for i in self.shipped()["told"] if i.get("batch") == 3], ["rebase"])
        self.assertEqual({i["handle"]: i["batch"] for i in self.shipped()["told"] if i["handle"] != "rebase"},
                         {"c2": 1, "c1": 2, "review-bo-example": 2}, "told once, in the batch it is on")

    def test_an_item_judged_between_the_re_offer_and_the_tell_is_not_told_again(self):
        """c-654 review: the batch waited for a slot, and the house's verdict landed
        meanwhile. Told again, the item's row would start afresh and that verdict be lost."""
        self.reoffered()
        self.judged("c1")
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.close_pass()
        self.board.unblock(self.card, "human")
        self.board.reoffer(self.card, "human")
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=10), slots=0)
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["review-bo-example"])
        self.judged("review-bo-example")
        self.upkeep(MON_10 + timedelta(minutes=11))
        shipped = self.shipped()
        self.assertEqual((shipped["round"], shipped["pending"]), (2, []), "no batch 3 was told")
        rows = {r["handle"]: r for r in shipreplies.rows(self.board.get(self.card), self.board.events(self.card))}
        self.assertEqual(rows["review-bo-example"]["verdict"]["verdict"], "not-valid", "its verdict stands")

    def test_a_turn_that_ended_and_a_session_listed_no_more_is_handed_to_him_too(self):
        """c-654 review: the turn ended by its Stop, then the session left the listing with no
        SessionEnd on the board (a reboot, a killed process). Nothing is left to close, and
        the unjudged items are his; a listing that FAILED is never read as that."""
        self.reoffered()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.fake.rows, self.fake.listing_fails = [], True
        self.assertEqual(self.close_pass(), [])
        self.assertIsNone(self.board.get(self.card)["blocked_reason"], "a failed listing settles nothing")
        self.fake.listing_fails = False
        self.assertEqual(self.close_pass(), [])
        self.assertEqual(self.fake.stops, [])
        self.assertEqual(self.shipped()["reoffer"]["unjudged"], ["c1", "review-bo-example"])
        self.assertTrue(self.board.get(self.card)["derived"]["needs_you"])

    def test_a_house_the_drain_stopped_is_noted_even_when_the_batch_moved_on_meanwhile(self):
        """c-654 review: the record moved to another batch while the house was being stopped,
        so the re-offer's mark is not written. The stop is still said on the card."""
        self.reoffered()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        stop = self.fake.stop

        def a_newer_batch_meanwhile(bg_id, config_dir=None):
            shipped = self.shipped()
            shipped.update(round=3, reoffer=dict(shipped["reoffer"], batch=3))
            self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
            return stop(bg_id, config_dir)
        with mock.patch.object(self.fake, "stop", side_effect=a_newer_batch_meanwhile):
            self.assertEqual(self.close_pass(), [self.card])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertIsNone(self.shipped()["reoffer"].get("closed_at"), "the newer batch's mark is untouched")
        self.assertTrue(self.board.get(self.card)["derived"]["closed_idle"])
        self.assertIsNone(self.board.get(self.card)["blocked_reason"], "the block goes with the mark")

    def test_a_card_blocked_for_unjudged_items_is_still_closed_by_its_merge(self):
        """c-654 review: a blocked card is not watched, so this block would have left a merged
        pull request unseen and the card at shipping for good. It is still looked at; new
        review waits for his unblock."""
        self.reoffered()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.close_pass()
        self.assertTrue(self.board.get(self.card)["blocked_reason"])
        old = MON_10 - timedelta(days=1)
        self.see(sight(comments=[comment(1, old), comment(2, old, "Rename it"), comment(3, old, "Typo"),
                                 comment(4, MON_10)]))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=10))
        shipping.LAST_POLLED.clear()
        told = len(self.fake.relays)
        self.upkeep(MON_10 + timedelta(minutes=20))
        self.assertEqual([i["handle"] for i in self.shipped()["pending"]], ["c4"], "seen, and it waits")
        self.assertEqual((len(self.fake.relays), self.fake.resumes), (told, []), "nothing told while blocked")
        self.see(sight(state="merged"))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=30))
        card = self.board.get(self.card)
        self.assertEqual((card["stage"], card["blocked_reason"], card["derived"]["needs_you"]),
                         ("done", None, False), "the unjudged items are moot once merged")

    def test_a_merge_whose_move_to_done_is_refused_lifts_no_block(self):
        """The block is lifted by the move to done itself, so it can never be lifted while
        the card stays at shipping."""
        self.reoffered()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.close_pass()
        blocked = self.board.get(self.card)["blocked_reason"]
        with self.assertRaises(Refused):
            self.board.stage(self.card, "done", "house")     # the board's own rule: not a house's move
        card = self.board.get(self.card)
        self.assertEqual((card["stage"], card["blocked_reason"]), ("shipping", blocked))
        self.assertEqual([e for e in self.board.events(self.card) if e["kind"] == "unblock"], [])

    def test_a_normal_batch_keeps_the_two_hour_idle_close(self):
        """And its turn ending with nothing judged blocks nothing (c-654 review): its house
        is kept those two hours so a later turn can finish the judging."""
        self.told()
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        rows = self.fake.rows
        self.assertEqual(shipidle.upkeep(self.cfg, self.board, rows, {"work"},
                                         at=MON_10 + timedelta(minutes=10))["closed"], [])
        self.assertEqual(self.fake.stops, [])
        self.assertIsNone(self.board.get(self.card)["blocked_reason"])


def event(number: int, kind: str, **data) -> dict:
    return {"id": number, "kind": kind, "data": data, "at": None}


def stop(number: int, session: str, **extra) -> dict:
    return event(number, "hook", hook="Stop", session_id=session, **extra)


class BatchTurnTest(unittest.TestCase):
    """c-651: where a re-offered batch's own turn stands, by the board's order of events
    after it was told (`after`), never by a clock."""

    MARK = {"after": 5}

    def turn(self, *events) -> str:
        older = [event(4, "resume", session_id="S1"), stop(5, "S1")]
        return shipreoffer.batch_turn(self.MARK, older + list(events))[0]

    def test_a_resume_minting_a_session_and_its_stop_end_its_turn(self):
        self.assertEqual(self.turn(event(6, "resume", session_id="S2"), event(7, "session", session_id="S2"),
                                   stop(8, "S2")), shipreoffer.ENDED)

    def test_a_fresh_launch_and_its_stop_end_its_turn(self):
        self.assertEqual(self.turn(event(6, "session", session_id="S"), stop(7, "S")), shipreoffer.ENDED)

    def test_a_blocked_stop_or_another_session_s_stop_leaves_it_waiting(self):
        self.assertEqual(self.turn(event(6, "resume", session_id="S"), stop(7, "S", stop_blocked=True)),
                         shipreoffer.WAITING)
        self.assertEqual(self.turn(event(6, "resume", session_id="S"), stop(7, "other")), shipreoffer.WAITING)

    def test_a_session_that_ended_with_no_stop_has_exited(self):
        end = event(7, "hook", hook="SessionEnd", session_id="S")
        self.assertEqual(self.turn(event(6, "resume", session_id="S"), end), shipreoffer.EXITED)
        self.assertEqual(self.turn(event(6, "resume", session_id="S"),
                                   event(7, "hook", hook="SessionEnd", session_id="superseded")),
                         shipreoffer.WAITING)

    def test_a_later_turn_ends_it(self):
        self.assertEqual(self.turn(event(6, "resume", session_id="S"), stop(7, "S"),
                                   event(8, "resume", session_id="S")), shipreoffer.OVER)

    def test_his_voice_or_drop_in_hold_is_a_later_turn_and_its_release_is_not(self):
        for key in ("voice_hold", "dropin_hold"):
            self.assertEqual(self.turn(event(6, "resume", session_id="S"), stop(7, "S"),
                                       event(8, "set", options={key: {"at": "now"}})), shipreoffer.OVER)
        self.assertEqual(self.turn(event(6, "resume", session_id="S"), stop(7, "S"),
                                   event(8, "set", options={"dropin_hold": None})), shipreoffer.ENDED)


class LocalFactsTest(unittest.TestCase):
    """The drain's git read of a shipping card's worktree: what Ship's confirm warns about."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.cfg = make_config(root)
        self.origin, self.tree = root / "origin.git", root / "tree"
        run = lambda *a, cwd=root: __import__("subprocess").run(a, cwd=cwd, check=True, capture_output=True)
        self.run = run
        run("git", "init", "-q", "--bare", "-b", "main", str(self.origin))
        run("git", "clone", "-q", str(self.origin), str(self.tree))
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "T")):
            run("git", "config", key, value, cwd=self.tree)
        (self.tree / "a.txt").write_text("one\n")
        run("git", "add", "a.txt", cwd=self.tree)
        run("git", "commit", "-qm", "base", cwd=self.tree)
        run("git", "push", "-q", "origin", "HEAD:main", cwd=self.tree)
        run("git", "checkout", "-qb", "feature/x", cwd=self.tree)
        run("git", "push", "-qu", "origin", "feature/x", cwd=self.tree)
        self.card = {"id": "c-9300", "repo": "api", "options": {"worktree": str(self.tree), "base": "main"}}

    def commit(self, text):
        (self.tree / "a.txt").write_text(text)
        self.run("git", "commit", "-qam", "change", cwd=self.tree)

    def test_commits_not_pushed_are_ahead_and_unchecked(self):
        self.assertEqual(shipping.local_facts(self.cfg, self.card), {"ahead": 0, "behind": 0, "unchecked": False, "conflicts": False})
        self.commit("two\n")
        self.assertEqual(shipping.local_facts(self.cfg, self.card), {"ahead": 1, "behind": 0, "unchecked": True, "conflicts": False})

    def test_a_conflict_with_the_base_the_pull_request_names_is_seen(self):
        """No `options.base`: the base the last look saw (the record's `base`) is the one."""
        self.card["options"] = {"worktree": str(self.tree), SHIPPING_OPTION: {"base": "main"}}
        self.test_a_conflict_with_the_base_is_seen()

    def test_a_conflict_with_the_base_is_seen(self):
        self.commit("mine\n")
        other = Path(self.tmp.name) / "other"
        self.run("git", "clone", "-q", str(self.origin), str(other))
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "T")):
            self.run("git", "config", key, value, cwd=other)
        (other / "a.txt").write_text("theirs\n")
        self.run("git", "commit", "-qam", "theirs", cwd=other)
        self.run("git", "push", "-q", "origin", "HEAD:main", cwd=other)
        self.run("git", "fetch", "-q", "origin", cwd=self.tree)
        self.assertTrue(shipping.local_facts(self.cfg, self.card)["conflicts"])


if __name__ == "__main__":
    unittest.main()
