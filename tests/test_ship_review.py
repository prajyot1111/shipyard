"""c-600 review: what his Ship checks at publish time, handles told again, the lease, the tell
that fails on its own thread, the pool, the stack torn down after a shipping turn, the fence
under the guard, the smaller gaps, and the upgrade from the review-round model."""

import importlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from keel import (actions, adapters, board as board_module, cli, house, shipping, shipreplies, shipwatch,
                  teardown, tellhouse)
from keel.actions import ActionError
from keel.board import SHIPPING_OPTION, Board, Refused
from tests.helpers import SESSION, background_row
from tests.test_after_gate import load_guard
from tests.test_shipping import MON_10, ShippingCase, comment, sight

FULL = "a" * 40
LATER = "b" * 40


class ShipCase(ShippingCase):
    def with_a_verdict(self):
        self.told()
        self.verdict("c11", "not-valid", reply="The host pages at 40.")

    def ship(self, anyway=False):
        return self.board.ship(self.card, "human", adapters.publisher(self.cfg, "work", anyway=anyway))


class ShipCheckTest(ShipCase):
    """1: the worktree NOW, on the house's machine: never mid-turn, never unchecked, unless he says."""

    def test_a_ship_is_held_while_the_house_is_in_a_turn_unless_he_says_anyway(self):
        self.with_a_verdict()
        self.live(status="busy")
        with self.assertRaisesRegex(adapters.AdapterError, "Ship held: .* house is working"):
            self.ship()
        self.assertFalse(self.answers.exists(), "nothing was pushed or posted")
        self.ship(anyway=True)
        self.assertEqual(len(self.answers.read_text().splitlines()), 1)

    def test_a_held_ship_says_the_house_is_working_in_plain_words(self):
        """c-604: the confirm printed the row's uuid and pid; it says how long the turn has run."""
        from datetime import timezone
        from keel import livetail
        self.with_a_verdict()
        self.live(status="busy")
        began = (datetime.now(timezone.utc) - timedelta(minutes=7, seconds=5)).isoformat()
        with mock.patch.object(livetail, "tail", return_value={"turn_at": began}):
            with self.assertRaises(adapters.AdapterError) as caught:
                self.ship()
        said = str(caught.exception)
        self.assertIn("house is working (turn 7m)", said)
        for leak in ("pid", SESSION, "session", "state "):
            self.assertNotIn(leak, said)

    def test_commits_no_receipt_covers_hold_the_ship(self):
        self.with_a_verdict()
        facts = {"ahead": 2, "unchecked": True, "conflicts": False}
        with mock.patch.object(shipping, "local_facts", return_value=facts):
            with self.assertRaisesRegex(adapters.AdapterError, "no review receipt covers"):
                self.ship()
            self.ship(anyway=True)

    def test_the_deck_hears_held_and_asks_him_before_anything_goes(self):
        self.with_a_verdict()
        held = "kb: Ship held: c-1's house is working (turn 4m), so what it is doing is not on the branch yet; Ship anyway to send it as it is"
        with mock.patch.object(actions, "run_kb", side_effect=ActionError(held)) as run:
            answer = actions.act_ship(self.cfg, self.board, {"verb": "ship", "id": self.card})
        self.assertTrue(answer["held"].startswith("Ship held: "))
        self.assertEqual(run.call_args.args[1], ["ship", self.card])
        with mock.patch.object(actions, "run_kb", return_value=self.board.get(self.card)) as run:
            actions.act_ship(self.cfg, self.board, {"verb": "ship", "id": self.card, "anyway": True})
        self.assertEqual(run.call_args.args[1], ["ship", self.card, "--anyway"])

    def test_kb_ship_marks_the_card_while_the_adapter_runs_and_clears_it_after(self):
        self.with_a_verdict()
        seen = []

        def publish(card):
            seen.append(bool(self.board.get(self.card)["options"].get("publishing")))
            return {"shipping": True, "sent": [], "posted": []}
        args = SimpleNamespace(config=self.cfg, id=self.card, anyway=False)
        with mock.patch.object(adapters, "publisher", return_value=publish):
            cli.cmd_ship(self.board, args, "human")
        self.assertEqual(seen, [True])
        self.assertNotIn("publishing", self.board.get(self.card)["options"])

    def test_kb_ship_hands_the_adapter_the_nonce_its_marker_was_written_with(self):
        """c-738 r1.F3, r2.F5: `kb ship` runs the space's real `publish` executable with the
        tap's nonce, which matches the digest on the card while it runs. The stand-in reads
        the marker off the board as the kit's verb reads it off `kb show`."""
        self.with_a_verdict()
        said = self.dir / "nonce-check"
        (self.dir / "check.py").write_text(
            "import hashlib, json, os, sqlite3, sys\n"
            "row = sqlite3.connect(sys.argv[1]).execute('SELECT options FROM cards WHERE id = ?', (sys.argv[2],)).fetchone()\n"
            "digest = (json.loads(row[0] or '{}').get('publishing') or {}).get('digest')\n"
            "nonce = os.environ.get('KEEL_PUBLISH_NONCE', '')\n"
            "ok = bool(nonce) and digest == hashlib.sha256(nonce.encode()).hexdigest()\n"
            "open(sys.argv[3], 'w').write('matches' if ok else 'no match')\n")
        publish = self.cfg.adapters_dir / "work" / "publish"
        publish.write_text(publish.read_text().replace(
            "#!/bin/sh\n", f'#!/bin/sh\npython3 {self.dir / "check.py"} {self.cfg.db_path} "$1" {said}\n', 1))
        cli.cmd_ship(self.board, SimpleNamespace(config=self.cfg, id=self.card, anyway=False), "human")
        self.assertEqual(said.read_text(), "matches")
        self.assertNotIn("publishing", self.board.get(self.card)["options"])

    def test_an_empty_ship_is_refused_even_anyway(self):
        self.told()
        self.verdict("c11", "deferred", reply="A follow-up.")
        self.board.mark(self.card, {"what": "answer", "doc": "shipping", "block": "replies",
                                    "row": "c11", "choice": "drop"}, "human")
        with self.assertRaisesRegex(adapters.AdapterError, "nothing to ship"):
            self.ship(anyway=True)


class ReusedHandleTest(ShipCase):
    """2: a handle told again (`ci`, `review-<who>`) never carries the old verdict or mark."""

    def test_a_check_that_fails_again_starts_its_row_afresh(self):
        self.told()
        shipped = self.shipped()
        shipped["pending"] = [{"kind": "ci", "handle": "ci", "state": "failed", "name": "unit tests"}]
        _, shipped = shipwatch.take_batch(shipped, datetime.now().astimezone() - timedelta(hours=1))
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        self.verdict("ci", "not-valid", reply="Flaky: the suite passes here.")
        self.board.mark(self.card, {"what": "answer", "doc": "shipping", "block": "replies", "row": "ci",
                                    "choice": "edit", "other": "Flaky, rerun it please."}, "human")
        self.ship(anyway=True)
        self.assertIn("ci", self.shipped()["posted"])
        again = dict(self.shipped(), pending=[{"kind": "ci", "handle": "ci", "state": "failed"}])
        _, again = shipwatch.take_batch(again, datetime.now().astimezone() + timedelta(minutes=5))
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: again}}, "drain")
        rows = {r["handle"]: r for r in shipreplies.rows(self.board.get(self.card), self.board.events(self.card))}
        self.assertIsNone(rows["ci"]["verdict"])
        self.assertEqual((rows["ci"]["choice"], rows["ci"]["edited"], rows["ci"]["words"]), (None, "", ""))
        self.assertNotIn("ci", [k["handle"] for k in shipreplies.kept(self.board.get(self.card),
                                                                        self.board.events(self.card))])

    def test_stamps_from_two_clocks_compare_as_instants(self):
        events = [{"at": "2026-09-21T15:31:00+05:30", "kind": "mark"}]
        self.assertEqual(shipreplies.since(events, "2026-09-21T10:00:00+00:00"), events)
        self.assertEqual(shipreplies.since(events, "2026-09-21T10:02:00+00:00"), [])


class LeaseTest(ShipCase):
    """3: the push leases against the heads Keel recorded, never against a fresh fetch."""

    def test_the_publish_and_each_ship_record_the_heads_the_next_ship_leases_against(self):
        card_id = self.board.create("work", "another", repo="api", actor="human", options={"pr": 7})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.board.approve(card_id, "outcome", "human",
                           publish=lambda c: json.dumps({"shipping": True, "heads": {"api": FULL, "x": "short"}}))
        self.assertEqual(self.board.get(card_id)["options"][SHIPPING_OPTION]["heads"], {"api": FULL})
        card = self.board.get(card_id)
        self.assertEqual(shipreplies.ship_answer(card, [])["lease"], {"api": FULL})
        self.board.ship(card_id, "human", lambda c: {"shipping": True, "pushed": {"api": LATER}, "sent": []})
        self.assertEqual(self.board.get(card_id)["options"][SHIPPING_OPTION]["heads"], {"api": LATER})

    def test_a_ship_that_moved_no_head_says_nothing_new_to_push(self):
        """c-605: the sandbox's second Ship "pushed web 01282a6", the head its first had
        pushed, and the toast said so after the confirm had said "nothing new"."""
        card_id = self.board.create("work", "another", repo="api", actor="human", options={"pr": 7})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.board.approve(card_id, "outcome", "human",
                           publish=lambda c: json.dumps({"shipping": True, "heads": {"api": FULL}}))
        said = lambda: [e["text"] for e in self.board.events(card_id) if e["kind"] == "ship"][-1]  # noqa: E731
        self.board.ship(card_id, "human", lambda c: {"shipping": True, "pushed": {"api": FULL}, "sent": []})
        self.assertEqual(said(), "shipped: nothing new to push, posted 0 replies")
        self.board.ship(card_id, "human", lambda c: {"shipping": True, "pushed": {"api": LATER}, "sent": []})
        self.assertEqual(said(), "shipped: pushed api bbbbbbbbbb, posted 0 replies")

    def test_heads_of_takes_only_full_shas(self):
        self.assertEqual(board_module.heads_of('{"pushed": {"a": "abc", "b": "%s"}}' % FULL), {"b": FULL})
        self.assertEqual(board_module.heads_of("not json"), {})


class BackgroundTellTest(ShipCase):
    """4: a tell that fails on its own thread is logged, said on the card, and handed back."""

    def test_a_failure_is_logged_noted_and_put_back(self):
        self.told()
        before = dict(self.shipped(), pending=[{"kind": "ci", "handle": "ci"}])
        plan = {"card": self.board.get(self.card), "actor": "drain"}
        undo = shipping.put_back(self.card, before)
        opened = lambda cfg: Board(self.cfg.db_path)    # noqa: E731
        with mock.patch.object(tellhouse, "send", side_effect=RuntimeError("the relay broke")), \
                mock.patch("keel.board.open_board", opened):
            tellhouse.send_alone(self.cfg, plan, undo)
        log = (self.cfg.logs_dir / "drain.log").read_text()
        self.assertIn("Traceback", log)
        self.assertIn("the relay broke", log)
        card = self.board.get(self.card)
        block = [e for e in self.board.events(self.card) if e["kind"] == "block"][-1]
        self.assertEqual(block["data"], {"mechanics": True})
        self.assertIn("could not reach the house: the relay broke", card["blocked_reason"])
        self.assertEqual(card["options"][SHIPPING_OPTION]["pending"], [{"kind": "ci", "handle": "ci"}])
        notes = [e.get("text") or "" for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertTrue(any("telling the house failed" in n for n in notes))

    def test_a_tell_rewrites_the_house_settings_for_the_stage_it_is_at(self):
        settings = self.cfg.card_dir(self.card) / "settings.json"
        settings.unlink(missing_ok=True)
        self.told()
        self.assertIn(f"keel-house-guard {self.card}", settings.read_text())


class TeardownAtShippingTest(ShippingCase):
    """6: the card's stack goes down after each turn its house takes at shipping."""

    def test_each_stop_at_shipping_is_a_spell_to_answer(self):
        card = self.board.get(self.card)
        building = teardown.spell(self.board, self.card)
        self.board.set_fields(self.card, {"options": {teardown.TEARDOWN_OPTION: building}}, "drain")
        self.assertIsNone(teardown.due(self.board, self.board.get(self.card)))
        stop = self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.assertEqual(teardown.due(self.board, self.board.get(self.card)), stop)
        self.board.set_fields(self.card, {"options": {teardown.TEARDOWN_OPTION: stop}}, "drain")
        self.assertIsNone(teardown.due(self.board, self.board.get(self.card)))
        again = self.board.record_hook(self.card, "Stop", {"session_id": SESSION})
        self.assertEqual(teardown.due(self.board, self.board.get(self.card)), again, "never cached")
        self.assertEqual(card["stage"], "shipping")


class PoolTest(ShippingCase):
    """5: every batch takes a slot; the drain counts the woken houses."""

    def test_two_cards_due_with_one_slot_wake_one_house(self):
        self.live()
        self.with_a_comment()
        second = self.shipped_card()
        self.fake.rows.append(background_row(second, "0" * 8 + SESSION[8:], status="idle"))
        self.board.set_session(second, "0" * 8 + SESSION[8:], "drain", bg_id="00000000")
        self.board.set_fields(second, {"options": {SHIPPING_OPTION: dict(self.shipped())}}, "drain")
        result = self.upkeep(MON_10 + timedelta(minutes=5), slots=1)
        self.assertEqual(len(result["told"]) + len(result["resumed"]), 1)


class FenceTest(ShipCase):
    """7 and 8: the guard's wider pattern; a posted reply is never sent twice; valid means changed."""

    def test_the_guard_sees_git_spelled_out_for_a_subprocess_and_the_host_module(self):
        guard = load_guard()
        with mock.patch.object(guard, "card_of", return_value={"stage": "shipping"}):     # `kb flowinfo`, c-641
            for command in ("""python3 -c "import subprocess; subprocess.run(['git', '-C', 'x', 'push'])" """,
                            "python3 -c 'import codehost; codehost.post_comment(1, 2, 3)'"):
                self.assertTrue(guard.problem(command, "c-1"), command)

    def test_his_edit_after_a_post_is_refused(self):
        self.with_a_verdict()
        self.ship(anyway=True)
        with self.assertRaisesRegex(Refused, "already posted"):
            self.board.mark(self.card, {"what": "answer", "doc": "shipping", "block": "replies",
                                        "row": "c11", "choice": "edit", "other": "Better words."}, "human")

    def test_a_valid_verdict_without_a_change_is_refused(self):
        self.told()
        with self.assertRaisesRegex(Refused, "deferred"):
            self.verdict("c11", "valid", reply="Agreed, but not here.")

    def test_a_comment_edited_on_the_host_is_told_again(self):
        seen = sight(comments=[dict(comment(11, MON_10), updated="2026-09-21T10:00:00+00:00")])
        first, _ = shipwatch.fold({}, seen, MON_10)
        self.assertEqual(first["pending"], [])
        edited = sight(comments=[dict(comment(11, MON_10, "Why 40, and not 50?"),
                                      updated="2026-09-21T10:20:00+00:00")])
        later, _ = shipwatch.fold(first, edited, MON_10 + timedelta(minutes=20))
        self.assertEqual([(i["handle"], i["text"], i.get("edited")) for i in later["pending"]],
                         [("c11", "Why 40, and not 50?", True)])


shipupgrade = None     # keel/shipupgrade.py, imported by UpgradeTest.setUp


class UpgradeTest(ShippingCase):
    """9: the carry from the review-round model, a dry run first, and his Approve meanwhile."""

    OLD = [{"kind": "comment", "handle": "c11", "text": "Why 40?"}, {"kind": "ci", "handle": "ci"}]

    def setUp(self):
        super().setUp()
        global shipupgrade
        shipupgrade = importlib.import_module("keel.shipupgrade")

    def test_a_shipping_card_s_answered_round_is_told_and_posted(self):
        card = {"id": "c-1", "stage": "shipping", "session_id": SESSION,
                "options": {"shipping": {"round": 2, "round_at": "2026-09-20T10:00:00+00:00",
                                         "batch": self.OLD, "rotated": True}, "ship_now": True}}
        new = shipupgrade.carried(card)
        self.assertEqual([(i["handle"], i["batch"]) for i in new["told"]], [("c11", 2), ("ci", 2)])
        self.assertEqual(new["posted"], {"c11": shipupgrade.LEGACY, "ci": shipupgrade.LEGACY})
        self.assertNotIn("batch", new)
        self.assertNotIn("rotated", new)
        self.assertEqual(shipupgrade.fields(card)["options"]["ship_now"], None)
        self.assertTrue(any("settings" in step for step in shipupgrade.plan(card)))

    def test_a_card_mid_round_goes_back_to_pending_and_its_approve_waits_for_the_upgrade(self):
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: {
            "round": 1, "round_at": "2026-09-20T10:00:00+00:00", "batch": self.OLD}}}, "drain")
        card = dict(self.board.get(self.card), stage="review")
        self.assertIn("keel-shipping-upgrade", shipupgrade.refusal(card))
        new = shipupgrade.carried(card)
        self.assertEqual([i["handle"] for i in new["pending"]], ["c11", "ci"])
        self.assertEqual(shipwatch.due(new, MON_10), "nothing new for 5 minutes")

    def test_approve_at_review_on_an_old_round_publishes_nothing(self):
        card_id = self.board.create("work", "mid-round", repo="api", actor="human", options={"pr": 9})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_fields(card_id, {"options": {SHIPPING_OPTION: {"round": 1, "batch": self.OLD}}}, "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        published = []
        with self.assertRaisesRegex(Refused, "keel-shipping-upgrade"):
            self.board.approve(card_id, "outcome", "human", publish=lambda c: published.append(c))
        self.assertEqual(published, [])

    def test_the_dry_run_prints_from_a_deck_and_writes_nothing(self):
        state = {"cards": [{"id": "c-1", "stage": "shipping", "session_id": SESSION,
                            "options": {"shipping": {"round": 1, "batch": self.OLD}}, "derived": {}}]}
        cards = shipupgrade.cards_from_deck("http://deck.invalid", fetch=lambda url: json.dumps(state))
        lines = shipupgrade.report(cards)
        self.assertEqual(lines[0], "c-1 (shipping):")
        self.assertIn("copy round 1's 2 item(s) into told", lines[1])

    def test_a_house_whose_settings_are_current_is_not_proposed_a_rewrite(self):
        """c-604: the upgrade proposed rewriting a card's settings that were already current."""
        card = self.board.get(self.card)
        current = lambda one: shipupgrade.held_current(self.cfg, one)     # noqa: E731
        self.assertTrue(any("settings" in line for line in shipupgrade.report([card], current)))
        house.settings_for(self.cfg, card)
        self.assertFalse(any("settings" in line for line in shipupgrade.report([card], current)))
        settings = self.cfg.card_dir(self.card) / "settings.json"
        settings.write_text(settings.read_text().replace("KEEL_CARD", "KEEL_OLD"))
        self.assertTrue(any("settings" in line for line in shipupgrade.report([card], current)))


class BatchWordsTest(ShippingCase):
    def test_the_batch_names_the_card_dir_by_its_path_not_a_variable(self):
        """c-604 review: probed 2026-09-30, a settings-file env rewrite does not reach a LIVE
        session's shell, and a batch is told into one; a house started before KEEL_CARD_DIR
        existed would find it empty."""
        from keel import shipround
        text = shipround.batch_prompt(self.cfg, self.board.get(self.card), [], "now", 1)
        self.assertNotIn("$KEEL_CARD_DIR", text)
        self.assertIn(f"{self.cfg.cards_dir / self.card}/replies/", text)

    def test_the_batch_changes_the_outcome_only_when_behaviour_changes(self):
        """c-643: a comment's answer reaches the outcome only when it alters how the thing
        works; the rest is the verdict's, which the comments page shows."""
        from keel import shipround
        text = " ".join(shipround.batch_prompt(self.cfg, self.board.get(self.card), [], "now", 1).split())
        self.assertIn(f"Change `{self.cfg.cards_dir / self.card}/context.md` only when your change alters how the thing works",
                      text)
        self.assertIn("recorded in its verdict alone", text)


class NoHouseAtShippingTest(ShippingCase):
    """A shipping card with no session starts one through c-601's one-house guard, which must
    be told the card is expected at shipping, or the batch is refused and the card blocked."""

    def test_the_first_batch_on_a_housed_less_card_starts_it_at_shipping(self):
        card = self.board.create("work", "Never housed", repo="api", actor="human",
                                 options={"pr": 4151, "branch": "feature/st-41002/never"})
        self.board.stage(card, "assigned", "human")
        self.board.claim(card, "mac", "drain")
        self.board.stage(card, "building", "drain")
        self.board.stage(card, "review", "house", plan_ref="p.md", output_ref="https://example.invalid/pr/4151")
        self.board.approve(card, "outcome", "human", publish=lambda c: {"shipping": True})
        self.cfg.card_dir(card).mkdir(parents=True, exist_ok=True)
        self.assertFalse(self.board.get(card).get("session_id"))
        seen = {}

        def start(cfg, board, card_id, extra=None):
            seen.update(card=card_id, extra=extra)
            return {"session_id": SESSION}

        with mock.patch.object(house, "launch", house.one_house(start)):
            row = self.board.get(card)
            shipping.deliver(self.cfg, self.board, row, {}, "comments",
                             MON_10 + timedelta(minutes=5), slots=1)
        self.assertEqual(seen.get("card"), card)
        self.assertIsNone(self.board.get(card)["blocked_reason"])


