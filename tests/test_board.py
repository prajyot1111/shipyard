"""Board store: schema, stage refusals, approve, split and derived views, hooks."""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from keel import flowmoves, views
from keel.board import FILED_NOTE, STAGES, Board, Refused
from tests.helpers import BoardCase, own_options


class SchemaTest(BoardCase):
    def test_five_tables_in_wal_mode(self):
        names = {row[0] for row in self.board.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(names, {"cards", "events", "requests", "asks", "holds"})
        self.assertEqual(self.board.conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_card_columns_match_the_layout(self):
        columns = [row[1] for row in self.board.conn.execute("PRAGMA table_info(cards)")]
        self.assertEqual(columns, [
            "id", "space", "title", "brief", "autonomy", "repo", "model", "stage",
            "blocked_reason", "session_id", "plan_ref", "output_ref", "parent", "after",
            "from", "topic", "options", "created_at", "updated_at", "rank"])

    def test_ids_continue_after_the_highest(self):
        self.assertEqual(self.card(), "c-001")
        self.board.insert_card({"space": "work", "title": "old", "id": "c-250",
                               "stage": "done", "autonomy": "autonomous"}, "import")
        self.assertEqual(self.card(), "c-251")

    def test_returned_card_is_a_plain_dict_with_options_and_derived(self):
        card = self.board.get(self.card(options={"plan_style": "light"}))
        self.assertIsInstance(card, dict)
        self.assertEqual(own_options(card), {"plan_style": "light"})
        self.assertEqual(set(card["derived"]), {
            "plan_gate", "outcome_gate", "needs_you", "kind", "startable", "parent_stage",
            "tracking", "tracking_tally", "follow_ups", "archived", "backlog",
            "backlog_override", "backlog_since", "relays", "voice_hold", "after", "waiting_for",
            "tree", "notice", "gate_since", "review", "review_severity", "review_wait", "ask",
            "landing", "regate", "bosun", "worker", "worker_eligible", "held_by_stop", "closed_idle", "ship_idle",
            "ship_auto", "ship_handover", "ship_sendback", "ship_prepared", "stack"})
        self.assertEqual(card["derived"]["kind"], "errand")


class SetFieldsTest(BoardCase):
    def test_space_is_immutable(self):
        with self.assertRaisesRegex(Refused, "immutable"):
            self.board.set_fields(self.card(), {"space": "work"}, "cli")

    def test_stage_is_refused_here(self):
        with self.assertRaisesRegex(Refused, "stage"):
            self.board.set_fields(self.card(), {"stage": "done"}, "cli")

    def test_unknown_field_is_refused(self):
        with self.assertRaisesRegex(Refused, "not a card field"):
            self.board.set_fields(self.card(), {"kind": "bug"}, "cli")

    def test_options_merge(self):
        card_id = self.card(options={"a": 1})
        card = self.board.set_fields(card_id, {"options": {"b": 2}}, "cli")
        self.assertEqual(own_options(card), {"a": 1, "b": 2})

    def test_a_null_option_drops_its_key_rather_than_storing_a_null(self):
        """`set options.k=null` must leave what `kb backlog <id> auto` leaves: no key."""
        card_id = self.card(options={"backlog": "backlog", "archived": True})
        card = self.board.set_fields(card_id, {"options": {"backlog": None}}, "human")
        self.assertEqual(own_options(card), {"archived": True})
        card = self.board.set_fields(card_id, {"options": {"archived": None}}, "human")
        self.assertEqual(own_options(card), {})
        self.assertFalse(card["derived"]["archived"])
        # The event still records what was asked for, nulls and all.
        self.assertEqual(self.board.events(card_id)[-1]["data"], {"options": {"archived": None}})

    def test_a_set_that_changes_nothing_records_nothing(self):
        """c-440: the backup's hourly job re-stated an open notice with the same title and
        brief, and every run put a `set` event on the card and bumped `updated_at`."""
        card_id = self.card(options={"notice_key": "k"})
        self.board.set_fields(card_id, {"title": "same", "brief": "words"}, "cli")
        before = self.board.get(card_id)
        count = len(self.board.events(card_id))
        card = self.board.set_fields(card_id, {"title": "same", "brief": "words",
                                               "options": {"notice_key": "k", "gone": None}}, "cli")
        self.assertEqual(len(self.board.events(card_id)), count)
        self.assertEqual(card["updated_at"], before["updated_at"])
        self.board.set_fields(card_id, {"brief": "other words"}, "cli")
        self.assertEqual(len(self.board.events(card_id)), count + 1)

    def test_dropping_an_option_that_was_never_there_is_not_an_error(self):
        card_id = self.card(options={"a": 1})
        card = self.board.set_fields(card_id, {"options": {"nothing": None}}, "cli")
        self.assertEqual(own_options(card), {"a": 1})


class StageTest(BoardCase):
    def test_every_stage_name_is_accepted_and_others_refused(self):
        card_id = self.card()
        for stage in ("inbox", "assigned", "building"):
            self.assertEqual(self.board.stage(card_id, stage, "cli")["stage"], stage)
        with self.assertRaisesRegex(Refused, "unknown stage"):
            self.board.stage(card_id, "checking", "cli")
        self.assertEqual(STAGES, ("inbox", "assigned", "planning", "building", "review",
                                  "shipping", "done"))

    def test_attended_card_may_not_leave_planning_without_approve(self):
        card_id = self.card(autonomy="attended")
        self.board.stage(card_id, "planning", "drain", plan_ref="plan.md")
        for stage in ("building", "assigned", "inbox", "review"):
            with self.assertRaisesRegex(Refused, "approve plan"):
                self.board.stage(card_id, stage, "house", output_ref="x")

    def test_he_may_put_an_attended_card_back_in_the_queue(self):
        card_id = self.card(autonomy="attended")
        self.board.stage(card_id, "planning", "drain", plan_ref="plan.md")
        self.assertEqual(self.board.stage(card_id, "assigned", "human")["stage"], "assigned")
        self.board.stage(card_id, "planning", "drain")
        self.assertEqual(self.board.stage(card_id, "inbox", "human")["stage"], "inbox")
        self.board.stage(card_id, "planning", "drain")
        with self.assertRaisesRegex(Refused, "approve plan"):
            self.board.stage(card_id, "building", "human")

    def test_autonomous_card_leaves_planning_freely(self):
        card_id = self.card()
        self.board.stage(card_id, "planning", "drain")
        self.assertEqual(self.board.stage(card_id, "building", "house")["stage"], "building")

    def test_review_needs_plan_ref(self):
        card_id = self.at_building()
        with self.assertRaisesRegex(Refused, "plan_ref"):
            self.board.stage(card_id, "review", "house", output_ref="out")


    def test_review_accepts_refs_passed_or_already_set(self):
        card_id = self.at_building()
        self.board.set_fields(card_id, {"plan_ref": "plan"}, "house")
        card = self.board.stage(card_id, "review", "house", output_ref="out")
        self.assertEqual((card["plan_ref"], card["output_ref"]), ("plan", "out"))

    def test_done_only_from_review(self):
        card_id = self.at_building()
        with self.assertRaisesRegex(Refused, "only from review"):
            self.board.stage(card_id, "done", "human")
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.assertEqual(self.board.stage(card_id, "done", "human")["stage"], "done")

    def test_blocked_flag_survives_a_stage_move(self):
        card_id = self.at_building()
        self.board.block(card_id, "waiting on a key", "house")
        card = self.board.stage(card_id, "review", "human", plan_ref="p", output_ref="o")
        self.assertEqual(card["blocked_reason"], "waiting on a key")
        self.assertIsNone(self.board.unblock(card_id, "human")["blocked_reason"])

    def test_stage_move_is_an_event_with_from_and_to(self):
        card_id = self.card()
        self.board.stage(card_id, "assigned", "human", note="go")
        event = self.board.events(card_id)[-1]
        self.assertEqual((event["kind"], event["text"], event["data"]),
                         ("stage", "go", {"from": "inbox", "to": "assigned"}))


class ApproveTest(BoardCase):
    def test_only_the_human_approves(self):
        card_id = self.card(autonomy="attended")
        self.board.stage(card_id, "planning", "drain", plan_ref="plan")
        for actor in ("cli", "house", "drain", "serve"):
            with self.assertRaisesRegex(Refused, "human"):
                self.board.approve(card_id, "plan", actor)
        self.assertEqual(self.board.approve(card_id, "plan", "human")["stage"], "building")

    def test_plan_requires_planning_and_outcome_requires_review(self):
        card_id = self.at_building()
        with self.assertRaisesRegex(Refused, "not planning"):
            self.board.approve(card_id, "plan", "human")
        with self.assertRaisesRegex(Refused, "not review"):
            self.board.approve(card_id, "outcome", "human")

    def test_outcome_runs_publish_then_moves_to_done(self):
        card_id = self.at_review()
        seen = []
        card = self.board.approve(card_id, "outcome", "human",
                                  publish=lambda c: seen.append(c["id"]) or {"pr": "ready"})
        self.assertEqual(seen, [card_id])
        self.assertEqual(card["stage"], "done")
        event = self.board.events(card_id)[-1]
        self.assertEqual(event["kind"], "approve")
        self.assertEqual(event["data"]["published"], {"pr": "ready"})

    def test_publish_failure_leaves_the_card_at_review(self):
        card_id = self.at_review()

        def boom(card):
            raise RuntimeError("no network")

        with self.assertRaises(RuntimeError):
            self.board.approve(card_id, "outcome", "human", publish=boom)
        self.assertEqual(self.board.get(card_id)["stage"], "review")


class SplitTest(BoardCase):
    def slices(self):
        return [{"title": "A", "brief": "do a"},
                {"title": "B", "brief": "do b", "after": "A"},
                {"title": "C", "brief": "do c"}]

    def test_children_carry_parent_and_after(self):
        parent = self.card(space="work", repo="alpha", autonomy="attended")
        a, b, c = self.board.split(parent, self.slices(), "human")
        child_b = self.board.get(b)
        self.assertEqual((child_b["parent"], child_b["after"], child_b["space"], child_b["repo"]),
                         (parent, a, "work", "alpha"))
        self.assertEqual(self.board.get(c)["after"], None)
        self.assertEqual(self.board.events(parent)[-1]["data"], {"children": [a, b, c]})

    def test_unknown_after_title_is_refused(self):
        with self.assertRaisesRegex(Refused, "unknown sibling"):
            self.board.split(self.card(), [{"title": "B", "after": "A"}], "human")

    def test_a_slice_that_states_its_repos_gets_exactly_those(self):
        """c-771: the parent names two repos and the split means one of them for a slice. The
        slice that states none takes the parent's, as before."""
        parent = self.card(space="work", repo="api,web")
        a, b, c = [self.board.get(one) for one in self.board.split(parent, [
            {"title": "A", "repo": "api"}, {"title": "B"}, {"title": "C", "repo": ["web", "api"]}], "house")]
        self.assertEqual((a["repo"], a["options"]["provenance"]["repo"]), ("api", "stated"))
        self.assertEqual((b["repo"], b["options"]["provenance"]["repo"]), ("api,web", "inherited"))
        # c-772: kept in the parent's order, so a slice's first repo is its parent's first kept
        self.assertEqual((c["repo"], c["options"]["provenance"]["repo"]), ("api,web", "stated"))

    def test_a_repo_the_parent_does_not_name_refuses_the_whole_split(self):
        parent = self.card(space="work", repo="api,web")
        for stated, said in (("api,docs", f"slice 'B': docs is not a repo of {parent} \\(api, web\\)"),
                             ("", "slice 'B': repo= names no repo"), (" , ", "names no repo")):
            with self.subTest(stated=stated), self.assertRaisesRegex(Refused, said):
                self.board.split(parent, [{"title": "A", "repo": "api"}, {"title": "B", "repo": stated}], "house")
        self.assertEqual(self.board.children(parent), [])      # atomic: A was not filed either
        errand = self.card(space="work")
        with self.assertRaisesRegex(Refused, f"api is not a repo of {errand} \\(it names none\\)"):
            self.board.split(errand, [{"title": "A", "repo": "api"}], "house")

    def test_parent_stage_is_derived_from_children(self):
        parent = self.card()
        a, b, c = self.board.split(parent, self.slices(), "human")
        self.assertEqual(self.board.get(parent)["derived"]["parent_stage"], "building")
        self.board.stage(a, "review", "house", plan_ref="p", output_ref="o")
        self.assertEqual(self.board.get(parent)["derived"]["parent_stage"], "review")
        for child in (a, b, c):
            if self.board.get(child)["stage"] != "review":
                self.board.stage(child, "review", "house", plan_ref="p", output_ref="o")
            self.board.stage(child, "done", "human")
        # Every slice done is his outcome gate, not done: a tracking card is done only once
        # Approve outcome has closed it (lane X; c-277 read `done` for four days unclosed).
        self.assertEqual(self.board.get(parent)["derived"]["parent_stage"], "review")

    def test_tracking_card_refuses_stage_moves_and_has_no_gates(self):
        parent = self.card(autonomy="attended")
        self.board.stage(parent, "planning", "drain", plan_ref="plan")
        self.board.split(parent, self.slices(), "human")
        with self.assertRaisesRegex(Refused, "tracking"):
            self.board.stage(parent, "building", "human")
        derived = self.board.get(parent)["derived"]
        self.assertFalse(derived["plan_gate"] or derived["needs_you"] or derived["startable"])

    def test_tracking_is_a_derived_flag_of_its_own_and_kind_still_says_errand_or_house(self):
        """`kind` answers errand or house (a repo or none), which a split never changes, so
        c-277 still read `house` after it was cut into eight. `tracking` is the flag."""
        parent = self.card(repo="alpha")
        self.assertEqual(self.board.get(parent)["derived"]["tracking"], False)
        self.board.split(parent, self.slices(), "human")
        derived = self.board.get(parent)["derived"]
        self.assertEqual((derived["tracking"], derived["kind"]), (True, "house"))
        self.assertEqual(self.board.get(self.board.children(parent)[0]["id"])["derived"]["tracking"],
                         False)

    def test_the_tally_says_how_the_slices_stand_in_a_few_words(self):
        parent = self.card()
        a, b, c = self.board.split(parent, self.slices(), "human")
        self.assertEqual(self.board.get(parent)["derived"]["tracking_tally"], "3 of 3 waiting")
        self.board.stage(a, "building", "drain")
        self.assertEqual(self.board.get(parent)["derived"]["tracking_tally"],
                         "1 of 3 building, 2 waiting")
        self.board.stage(a, "review", "house", plan_ref="p", output_ref="o")
        self.assertEqual(self.board.get(parent)["derived"]["tracking_tally"],
                         "1 of 3 at review, 2 waiting")
        self.board.stage(a, "done", "human")
        self.assertEqual(self.board.get(parent)["derived"]["tracking_tally"],
                         "1 of 3 done, 2 waiting")
        self.assertIsNone(self.board.get(b)["derived"]["tracking_tally"])
        self.assertIsNone(self.board.get(c)["derived"]["tracking_tally"])


class StartableTest(BoardCase):
    def test_startable_waits_for_after(self):
        parent = self.card()
        a, b = self.board.split(parent, [{"title": "A"}, {"title": "B", "after": "A"}], "human")
        self.assertTrue(self.board.get(a)["derived"]["startable"])
        self.assertFalse(self.board.get(b)["derived"]["startable"])
        self.board.stage(a, "review", "house", plan_ref="p", output_ref="o")
        self.assertTrue(self.board.get(b)["derived"]["startable"])

    def test_blocked_or_unassigned_is_not_startable(self):
        card_id = self.card()
        self.assertFalse(self.board.get(card_id)["derived"]["startable"])
        self.board.stage(card_id, "assigned", "human")
        self.assertTrue(self.board.get(card_id)["derived"]["startable"])
        self.board.block(card_id, "hold", "human")
        self.assertFalse(self.board.get(card_id)["derived"]["startable"])


class NeedsYouTest(BoardCase):
    def notice(self, **kwargs) -> str:
        """A segment's notice as `bin/keel-backup` files one: attended, topic `notice`,
        `options.notice_key`, open until it is staged done."""
        return self.card(autonomy="attended", topic="notice",
                         options={"notice_key": "backup-pull-stale"}, **kwargs)

    def test_an_open_notice_needs_you(self):
        """Q8 counts segment notices, and views.derived counted only gates and blocked
        cards, so c-440 (the stale backup) sat in the inbox among his ideas (F6)."""
        notice = self.notice()
        card = self.board.get(notice)
        self.assertTrue(card["derived"]["notice"])
        self.assertTrue(card["derived"]["needs_you"])
        self.assertIn(notice, [c["id"] for c in self.board.needs_you()])

    def test_an_archived_notice_and_an_ordinary_inbox_card_do_not(self):
        archived = self.notice()
        self.board.set_fields(archived, {"options": {"archived": True}}, "human")
        self.assertFalse(self.board.get(archived)["derived"]["needs_you"])
        plain = self.card(topic="notice")      # the topic alone is a grouping word, not a notice
        self.assertFalse(self.board.get(plain)["derived"]["notice"])
        self.assertFalse(self.board.get(plain)["derived"]["needs_you"])

    def test_a_notice_staged_done_is_closed(self):
        notice = self.notice()
        self.board.stage(notice, "assigned", "human")
        self.board.stage(notice, "building", "drain")
        self.board.stage(notice, "review", "house", plan_ref="p", output_ref="o")
        self.board.approve(notice, "outcome", "human")
        card = self.board.get(notice)
        self.assertEqual(card["stage"], "done")
        self.assertFalse(card["derived"]["notice"])
        self.assertFalse(card["derived"]["needs_you"])

    def test_plan_gate_outcome_gate_and_blocked(self):
        planning = self.card(autonomy="attended")
        self.board.stage(planning, "planning", "drain", plan_ref="plan")
        no_plan_yet = self.card(autonomy="attended")
        self.board.stage(no_plan_yet, "planning", "drain")
        review = self.at_review()
        blocked = self.card(space="work")
        self.board.block(blocked, "needs a key", "house")
        quiet = self.card()
        ids = [c["id"] for c in self.board.needs_you()]
        self.assertEqual(sorted(ids), sorted([planning, review, blocked]))
        self.assertEqual([c["id"] for c in self.board.needs_you(space="work")], [blocked])
        self.assertNotIn(quiet, ids)
        self.assertTrue(self.board.get(planning)["derived"]["plan_gate"])
        self.assertTrue(self.board.get(review)["derived"]["outcome_gate"])


class StopCheckTest(BoardCase):
    def test_two_blocks_then_the_card_is_blocked(self):
        card_id = self.at_building()
        first = self.board.stop_check(card_id, {"hook_event_name": "Stop"})
        self.assertEqual(first["decision"], "block")
        self.assertIn(card_id, first["reason"])
        second = self.board.stop_check(card_id, {})
        self.assertEqual(second["decision"], "block")
        self.assertIsNone(self.board.stop_check(card_id, None))
        self.assertEqual(self.board.stop_blocks(card_id), 2)
        self.assertIn("2 nudges", self.board.get(card_id)["blocked_reason"])
        hooks = [e for e in self.board.events(card_id) if e["kind"] == "hook"]
        self.assertEqual([e["data"].get("stop_blocked") for e in hooks], [True, True, None])

    def test_the_stop_block_goes_with_the_houses_own_move_to_review(self):
        """It rode `kb stage review` into Approve and shipping, where Attention called a
        shipping card "stopped at building" (c-601, e2e bug 5)."""
        card_id = self.at_building()
        for _ in range(3):
            self.board.stop_check(card_id, {})
        self.assertIn("stopped at building", self.board.get(card_id)["blocked_reason"])
        self.board.stage(card_id, "review", "house", plan_ref="plan.md", output_ref="out.md")
        card = self.board.get(card_id)
        self.assertIsNone(card["blocked_reason"])
        self.assertEqual(self.board.events(card_id)[-1]["kind"], "unblock")

    def test_another_block_is_not_lifted_by_a_move(self):
        card_id = self.at_building()
        self.board.block(card_id, "needs a key", "house")
        self.board.stage(card_id, "review", "house", plan_ref="plan.md", output_ref="out.md")
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "needs a key")

    def test_no_block_outside_building(self):
        card_id = self.at_review()
        self.assertIsNone(self.board.stop_check(card_id, {}))
        self.assertEqual(self.board.stop_blocks(card_id), 0)

    def test_a_voice_turn_is_never_nudged_and_spends_none_of_the_budget(self):
        """Guard 3. A connected turn fires this hook like any other (probed 2026-09-20), and
        a `block` decision would not merely cost a nudge: it would send the house back to
        WORK in the middle of a sentence he is waiting on."""
        card_id = self.at_building()
        self.board.hold_voice(card_id, 300, stopped=True)
        for _ in range(3):
            self.assertIsNone(self.board.stop_check(card_id, {"hook_event_name": "Stop"}))
        self.assertEqual(self.board.stop_blocks(card_id), 0)
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        hooks = [e for e in self.board.events(card_id) if e["kind"] == "hook"]
        self.assertEqual([e["data"].get("voice_hold") for e in hooks], [True, True, True])

    def test_the_nudge_comes_back_once_the_hold_is_released(self):
        card_id = self.at_building()
        self.board.hold_voice(card_id, 300, stopped=True)
        self.assertIsNone(self.board.stop_check(card_id, {}))
        self.board.release_voice(card_id)
        self.assertEqual(self.board.stop_check(card_id, {})["decision"], "block")

    def test_an_expired_hold_is_no_hold(self):
        card_id = self.at_building()
        self.board.hold_voice(card_id, -1, stopped=True)
        self.assertIsNone(self.board.voice_hold_of(card_id))
        self.assertEqual(self.board.stop_check(card_id, {})["decision"], "block")


class VoiceHoldTest(BoardCase):
    """`options.voice_hold`: one key on the card, because Keel has one store."""

    def test_the_hold_carries_when_it_runs_out_and_whether_voice_stopped_the_house(self):
        card_id = self.at_building()
        self.board.hold_voice(card_id, 300, stopped=True, turns=0)
        held = self.board.voice_hold_of(card_id)
        self.assertTrue(held["stopped"])
        self.assertEqual(held["turns"], 0)
        self.assertIn("until", held)

    def test_refreshing_keeps_what_the_first_turn_recorded(self):
        """`stopped` is the first turn's answer and never changes: it decides whether the
        release wakes the house or leaves it as it found it."""
        card_id = self.at_building()
        self.board.hold_voice(card_id, 300, stopped=False, turns=0)
        self.board.hold_voice(card_id, 300, stopped=True, turns=2)
        held = self.board.voice_hold_of(card_id)
        self.assertFalse(held["stopped"])
        self.assertEqual(held["turns"], 2)

    def test_a_house_cannot_hold_its_own_card(self):
        """A held card is skipped by the drain and by the nudge, so a house that could set
        this key would be making itself undrainable in one line, and `kb` is on its PATH."""
        card_id = self.at_building()
        with self.assertRaises(Refused) as caught:
            self.board.set_fields(card_id, {"options": {"voice_hold": {"until": "2099-01-01"}}},
                                  "house")
        self.assertIn("voice_hold", str(caught.exception))
        self.assertIsNone(self.board.voice_hold_of(card_id))
        # And it cannot take one away either, which would end a conversation from under him.
        self.board.hold_voice(card_id, 300, stopped=True)
        with self.assertRaises(Refused):
            self.board.set_fields(card_id, {"options": {"voice_hold": None}}, "house")
        self.assertIsNotNone(self.board.voice_hold_of(card_id))

    def test_the_actors_the_connected_turn_runs_under_may_set_it(self):
        card_id = self.at_building()
        for actor in ("voice", "drain", "human"):
            self.board.set_fields(card_id, {"options": {"voice_hold": {"until": "2099-01-01"}}},
                                  actor)
            self.assertIsNotNone(self.board.voice_hold_of(card_id))
            self.board.set_fields(card_id, {"options": {"voice_hold": None}}, actor)
            self.assertIsNone(self.board.voice_hold_of(card_id))

    def test_another_option_is_still_a_house_s_to_set(self):
        card_id = self.at_building()
        self.board.set_fields(card_id, {"options": {"peak_mb": 512}}, "house")
        self.assertEqual(self.board.get(card_id)["options"]["peak_mb"], 512)

    def test_releasing_removes_the_key_rather_than_nulling_it(self):
        card_id = self.at_building()
        self.board.hold_voice(card_id, 300, stopped=True)
        self.board.release_voice(card_id)
        self.assertNotIn("voice_hold", self.board.get(card_id)["options"])
        self.assertIsNone(self.board.get(card_id)["derived"]["voice_hold"])


class DropFilingTest(BoardCase):
    """An ask card finishes by writing a file, so the Stop hook files the card for it."""

    def ask_card(self, drop: Path) -> str:
        card_id = self.card(options={"drop": str(drop), "segment": "daybook"})
        self.board.stage(card_id, "assigned", "human")
        self.board.set_fields(card_id, {"plan_ref": "worker.md"}, "fetch")
        self.board.stage(card_id, "building", "drain")
        return card_id

    def test_a_written_drop_files_the_card_at_review_with_no_nudge(self):
        drop = self.dir / "worker-2026.json"
        drop.write_text('{"entries": [{"k": "story:a", "v": {}, "t": "2026-09-18T06:00:00Z"}]}')
        card_id = self.ask_card(drop)
        self.assertIsNone(self.board.stop_check(card_id, {"hook_event_name": "Stop"}))
        card = self.board.get(card_id)
        self.assertEqual((card["stage"], card["output_ref"]), ("review", str(drop)))
        self.assertEqual(self.board.stop_blocks(card_id), 0)
        self.assertIsNone(card["blocked_reason"])
        filed = [e for e in self.board.events(card_id) if (e.get("data") or {}).get("filed_drop")]
        self.assertEqual([e["data"]["filed_drop"] for e in filed], [str(drop)])
        moves = [e for e in self.board.events(card_id) if e["kind"] == "stage" and e["actor"] == "hook"]
        self.assertEqual(moves[-1]["text"], FILED_NOTE)

    def test_a_missing_or_unreadable_drop_nudges_with_the_path_and_no_command(self):
        drop = self.dir / "worker-2026.json"
        card_id = self.ask_card(drop)
        first = self.board.stop_check(card_id, {})
        self.assertIn(str(drop), first["reason"])
        self.assertIn("not written yet", first["reason"])
        self.assertNotIn("kb ", first["reason"])
        drop.write_text("half a file")
        second = self.board.stop_check(card_id, {})
        self.assertIn("not valid JSON", second["reason"])
        self.assertNotIn("kb ", second["reason"])
        self.assertEqual(self.board.get(card_id)["stage"], "building")

    def test_a_drop_the_board_refuses_to_file_leaves_the_card_at_building_and_says_why(self):
        drop = self.dir / "worker-2026.json"
        drop.write_text("{}")
        card_id = self.card(options={"drop": str(drop)})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")      # no plan_ref: review is refused
        decision = self.board.stop_check(card_id, {})
        self.assertEqual(self.board.get(card_id)["stage"], "building")
        self.assertIn("could not be filed", decision["reason"])
        notes = [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]
        self.assertIn("plan_ref", notes[-1])

    def test_an_errand_without_a_drop_is_nudged_as_before(self):
        card_id = self.at_building()
        decision = self.board.stop_check(card_id, {})
        self.assertIn(f"kb stage {card_id} review --output <ref>", decision["reason"])


class SessionAndHookTest(BoardCase):
    def test_session_is_stored_and_recorded(self):
        card_id = self.card()
        card = self.board.set_session(card_id, "abc-123", "drain",
                                      transcript_path="/t/x.jsonl", bg_id="083b13ff")
        self.assertEqual(card["session_id"], "abc-123")
        event = self.board.events(card_id)[-1]
        self.assertEqual(event["kind"], "session")
        self.assertEqual(event["data"], {"session_id": "abc-123", "transcript_path": "/t/x.jsonl",
                                         "bg_id": "083b13ff"})

    def test_hook_event_keeps_transcript_and_session(self):
        card_id = self.card()
        payload = {"session_id": "s-1", "transcript_path": "/t/s-1.jsonl", "reason": "prompt_input_exit"}
        self.board.record_hook(card_id, "SessionEnd", payload)
        event = self.board.events(card_id)[-1]
        self.assertEqual((event["kind"], event["actor"], event["text"]), ("hook", "hook", "prompt_input_exit"))
        self.assertEqual((event["data"]["session_id"], event["data"]["transcript_path"]),
                         ("s-1", "/t/s-1.jsonl"))
        self.assertEqual(json.loads(json.dumps(event["data"]["payload"])), payload)


class StopWithBackgroundWorkTests(BoardCase):
    """A Stop while the house's own subagent is still running is a wait, not a stop."""

    def test_running_background_task_is_not_nudged_and_spends_no_budget(self):
        cid = self.at_building()
        payload = {"background_tasks": [{"id": "x", "type": "subagent", "status": "running"}]}
        for _ in range(3):
            self.assertIsNone(self.board.stop_check(cid, payload))
        self.assertIsNone(self.board.get(cid)["blocked_reason"])
        self.assertEqual(self.board.stop_blocks(cid), 0)
        waits = [e for e in self.board.events(cid) if (e.get("data") or {}).get("waiting_on_background")]
        self.assertEqual(len(waits), 3)
        self.assertEqual(self.board.stop_check(cid, {"background_tasks": []})["decision"], "block")


class TopicTest(BoardCase):
    def test_topic_is_settable_filterable_and_inherited_by_slices(self):
        card_id = self.card(topic="deck")
        other = self.card()
        self.assertEqual(self.board.get(card_id)["topic"], "deck")
        self.assertIsNone(self.board.get(other)["topic"])
        self.board.set_fields(other, {"topic": "deck"}, "human")
        self.assertEqual([c["id"] for c in self.board.list_cards(topic="deck")], [card_id, other])
        children = self.board.split(card_id, [{"title": "a"}], "human")
        self.assertEqual(self.board.get(children[0])["topic"], "deck")

    def test_an_older_board_gains_the_topic_column_on_open(self):
        import sqlite3
        from keel import board as board_module
        path = self.dir / "old.db"
        old_schema = board_module.SCHEMA.replace("  topic TEXT,\n", "")
        self.assertNotIn("topic", old_schema)
        conn = sqlite3.connect(path)
        conn.executescript(old_schema)
        conn.execute("INSERT INTO cards (id, space, title, created_at, updated_at) VALUES "
                     "('c-001', 'personal', 'old', 'now', 'now')")
        conn.commit()
        conn.close()
        opened = Board(path)
        self.assertIn("topic", opened.columns())
        self.assertIsNone(opened.get("c-001")["topic"])
        opened.set_fields("c-001", {"topic": "t"}, "human")
        self.assertEqual(opened.get("c-001")["topic"], "t")
        self.assertEqual(opened.migrate(), [])
        opened.close()


class BacklogTest(BoardCase):
    """A card backlogs once it has sat at its outcome gate longer than `backlog_days`.

    Date alone, plus the manual override, nothing else. The board's clock is one method,
    so a test can move the board back in time and stage a card there.
    """

    def setUp(self):
        super().setUp()
        self.at = datetime.now().astimezone()

    @contextmanager
    def clock(self, days_ago: float):
        """Run the board's writes at a stamp `days_ago` in the past."""
        stamp = (self.at - timedelta(days=days_ago)).isoformat(timespec="seconds")
        self.board.now = lambda: stamp
        try:
            yield stamp
        finally:
            self.board.__dict__.pop("now", None)

    def old_review(self, days: float = 30) -> str:
        with self.clock(days):
            return self.at_review()

    def derived(self, card_id: str) -> dict:
        return self.board.get(card_id)["derived"]

    def test_a_review_card_backlogs_once_it_is_older_than_backlog_days(self):
        fresh, old = self.at_review(), self.old_review(30)
        self.assertFalse(self.derived(fresh)["backlog"])
        self.assertTrue(self.derived(fresh)["needs_you"])
        self.assertTrue(self.derived(old)["backlog"])
        self.assertFalse(self.derived(old)["needs_you"])
        self.assertIsNone(self.derived(old)["backlog_override"])
        self.assertTrue(self.derived(old)["outcome_gate"])
        self.assertEqual(self.board.get(old)["stage"], "review")

    def test_the_boundary_is_backlog_days_and_the_board_carries_it(self):
        with Board(self.dir / "default.db") as default:
            self.assertEqual(default.backlog_days, 7)
        self.assertFalse(self.derived(self.old_review(6))["backlog"])
        eight = self.old_review(8)
        self.assertTrue(self.derived(eight)["backlog"])
        self.board.backlog_days = 60
        self.assertFalse(self.derived(eight)["backlog"])

    def test_the_manual_override_decides_in_either_direction(self):
        old, fresh = self.old_review(30), self.at_review()
        self.board.set_backlog(old, "active", "human")
        self.assertFalse(self.derived(old)["backlog"])
        self.assertTrue(self.derived(old)["needs_you"])
        self.assertEqual(self.derived(old)["backlog_override"], "active")
        self.board.set_backlog(fresh, "backlog", "human")
        self.assertTrue(self.derived(fresh)["backlog"])
        self.assertFalse(self.derived(fresh)["needs_you"])
        self.assertEqual(self.derived(fresh)["backlog_override"], "backlog")

    def test_auto_clears_the_override_back_to_the_date_rule(self):
        old = self.old_review(30)
        self.board.set_backlog(old, "active", "human")
        card = self.board.set_backlog(old, "auto", "human")
        self.assertNotIn("backlog", card["options"])
        self.assertIsNone(card["derived"]["backlog_override"])
        self.assertTrue(card["derived"]["backlog"])
        kinds = [e["kind"] for e in self.board.events(old)][-2:]
        self.assertEqual(kinds, ["set", "set"])
        self.assertEqual(self.board.events(old)[-1]["data"], {"options": {"backlog": None}})

    def test_an_unknown_value_is_refused(self):
        with self.assertRaisesRegex(Refused, "backlog takes one of"):
            self.board.set_backlog(self.at_review(), "later", "human")

    def test_a_plan_gate_never_backlogs_whatever_the_override(self):
        with self.clock(30):
            card_id = self.card(autonomy="attended", repo="keel")
            self.board.stage(card_id, "assigned", "human")
            self.board.stage(card_id, "planning", "drain", plan_ref="plan.md")
        self.board.set_backlog(card_id, "backlog", "human")
        derived = self.derived(card_id)
        self.assertTrue(derived["plan_gate"])
        self.assertFalse(derived["backlog"])
        self.assertTrue(derived["needs_you"])

    def test_a_card_short_of_review_never_backlogs(self):
        with self.clock(30):
            building = self.at_building()
        self.board.set_backlog(building, "backlog", "human")
        self.assertFalse(self.derived(building)["backlog"])

    def test_an_imported_card_with_no_stage_event_falls_back_to_created_at(self):
        """The fold stamped every imported card's `updated_at` with the ledger's last bulk
        write, so the date that means anything for those ten cards is `created_at`."""
        old = (self.at - timedelta(days=40)).isoformat(timespec="seconds")
        touched = (self.at - timedelta(days=2)).isoformat(timespec="seconds")
        self.board.insert_card({"id": "c-250", "space": "work", "title": "imported",
                                "stage": "review", "autonomy": "autonomous",
                                "plan_ref": "p", "output_ref": "o",
                                "created_at": old, "updated_at": touched}, "import")
        self.assertTrue(self.derived("c-250")["backlog"])
        self.board.set_backlog("c-250", "active", "human")
        self.assertFalse(self.derived("c-250")["backlog"])

    def test_the_stage_event_wins_over_an_older_created_at(self):
        with self.clock(30):
            card_id = self.at_building()
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.assertFalse(self.derived(card_id)["backlog"])

    def test_list_and_needs_you_filter_on_backlog(self):
        old, fresh = self.old_review(30), self.at_review()
        self.assertEqual([c["id"] for c in self.board.list_cards(backlog=True)], [old])
        self.assertEqual([c["id"] for c in self.board.list_cards(backlog=False)], [fresh])
        self.assertEqual(len(self.board.list_cards()), 2)
        self.assertEqual([c["id"] for c in self.board.needs_you()], [fresh])
        self.assertEqual([c["id"] for c in self.board.needs_you(backlog=True)], [old, fresh])

    def test_an_archived_backlog_card_is_still_not_needed(self):
        old = self.old_review(30)
        self.board.set_fields(old, {"options": {"archived": True}}, "human")
        self.assertEqual(self.board.needs_you(backlog=True), [])

    def test_backlog_since_is_when_the_card_entered_its_outcome_gate(self):
        """The deck says how long a card has sat, so the stamp the rule measures from is
        on the card too. It is the stage event's, not the card's `updated_at`, which a
        write that is not his moves too (his own is BacklogClockTest's, c-673)."""
        with self.clock(30) as stamp:
            old = self.at_review()
        self.board.set_fields(old, {"topic": "deck"}, "drain")   # touched today, not by him
        since = self.derived(old)["backlog_since"]
        self.assertEqual(since, stamp)
        moved = [e for e in self.board.events(old)
                 if e["kind"] == "stage" and (e["data"] or {}).get("to") == "review"]
        self.assertEqual(since, moved[-1]["at"])
        self.assertGreater(self.board.get(old)["updated_at"], since)

    def test_backlog_since_is_set_before_the_card_has_backlogged(self):
        fresh = self.at_review()
        derived = self.derived(fresh)
        self.assertFalse(derived["backlog"])
        self.assertIsNotNone(derived["backlog_since"])
        self.assertEqual(derived["backlog_since"], self.board.get(fresh)["updated_at"])

    def test_a_card_away_from_its_outcome_gate_has_no_backlog_since(self):
        self.assertIsNone(self.derived(self.card())["backlog_since"])
        self.assertIsNone(self.derived(self.at_building())["backlog_since"])
        old = self.old_review(30)
        self.board.approve(old, "outcome", "human")
        self.assertIsNone(self.derived(old)["backlog_since"])

    def test_an_imported_card_falls_back_to_created_at_for_backlog_since(self):
        old = (self.at - timedelta(days=40)).isoformat(timespec="seconds")
        touched = (self.at - timedelta(days=2)).isoformat(timespec="seconds")
        self.board.insert_card({"id": "c-250", "space": "work", "title": "imported",
                                "stage": "review", "autonomy": "autonomous",
                                "plan_ref": "p", "output_ref": "o",
                                "created_at": old, "updated_at": touched}, "import")
        self.assertEqual(self.derived("c-250")["backlog_since"], old)

    def test_the_override_moves_the_card_and_leaves_the_stamp_alone(self):
        """`backlog_since` is a fact about the gate, not about the override."""
        old = self.old_review(30)
        since = self.derived(old)["backlog_since"]
        self.board.set_backlog(old, "active", "human")
        self.assertEqual(self.derived(old)["backlog_since"], since)


class BacklogClockTest(BoardCase):
    """The backlog clock counts from the newest of the card reaching review and his newest
    own action on it since (c-673, seen live 2026-10-06: his flow move tap on a card at
    review since 29 Sep sent it to the backlog the same day). The board's clock is pinned:
    nothing here reads the wall clock."""

    NOW = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)

    def setUp(self):
        super().setUp()
        self.days_ago(0)

    def days_ago(self, days: float) -> str:
        """Pin the board's clock `days` before NOW; every write and read after it is there."""
        stamp = (self.NOW - timedelta(days=days)).isoformat(timespec="seconds")
        self.board.now = lambda: stamp
        return stamp

    def review_at(self, days: float) -> str:
        self.days_ago(days)
        card_id = self.at_review()
        self.days_ago(0)
        return card_id

    def derived(self, card_id: str) -> dict:
        return self.board.get(card_id)["derived"]

    def assert_active_since(self, card_id: str, stamp: str):
        derived = self.derived(card_id)
        self.assertFalse(derived["backlog"])
        self.assertTrue(derived["needs_you"])
        self.assertEqual(derived["backlog_since"], stamp)

    def assert_backlog_since(self, card_id: str, stamp: str):
        derived = self.derived(card_id)
        self.assertTrue(derived["backlog"])
        self.assertFalse(derived["needs_you"])
        self.assertEqual(derived["backlog_since"], stamp)

    def test_his_flow_move_tap_on_an_old_review_card_keeps_it_out_of_the_backlog(self):
        """What happened: at review 8 days, he taps a flow move, the house does it within a
        minute, and the card must still be his to see."""
        card_id = self.review_at(8)
        self.assertTrue(self.derived(card_id)["backlog"])
        today = self.days_ago(0)
        self.board.set_fields(card_id, {"options": {flowmoves.OPTION: {"id": "dev-review"}}}, "human")
        flowmoves.asked(self.board, {"id": card_id}, SimpleNamespace(label="Merge to dev review", id="dev-review"))
        self.board.note(card_id, "merged into dev review", "house")
        self.assertEqual(self.board.events(card_id)[-2]["text"], "flow move asked: Merge to dev review (dev-review)")
        self.assert_active_since(card_id, today)

    def test_his_note_resets_the_clock_and_eight_days_on_it_is_backlog_again(self):
        card_id = self.review_at(10)
        noted = self.days_ago(2)
        self.board.note(card_id, "looked, back to this on Friday", "human")
        self.days_ago(0)
        self.assert_active_since(card_id, noted)
        self.days_ago(-5)                # 7 days after his note: the boundary, not past it
        self.assertFalse(self.derived(card_id)["backlog"])
        self.days_ago(-6)                # 8 days after it
        self.assert_backlog_since(card_id, noted)

    def test_voice_acting_for_him_counts_as_his(self):
        card_id = self.review_at(8)
        self.board.note(card_id, "he said: keep this one for Monday", "voice")
        self.assert_active_since(card_id, self.board.now())

    def test_his_set_his_unblock_and_his_mark_each_count(self):
        today = self.days_ago(0)
        ways = {"set": lambda c: self.board.set_fields(c, {"topic": "deck"}, "human"),
                "unblock": lambda c: (self.board.block(c, "the house is stuck", "house"),
                                      self.board.unblock(c, "human")),
                "mark": lambda c: self.board.mark(c, {"what": "comment", "doc": "outcome", "text": "why?"}, "human")}
        for name, act in ways.items():
            with self.subTest(name):
                card_id = self.review_at(8)
                act(card_id)
                self.assertIn((name, "human"), [(e["kind"], e["actor"]) for e in self.board.events(card_id)][-2:])
                self.assert_active_since(card_id, today)

    def test_nobody_elses_event_keeps_a_card_out_however_recent(self):
        card_id = self.review_at(8)
        reached = self.derived(card_id)["backlog_since"]
        self.board.note(card_id, "still here, nothing to add", "house")
        self.board.set_fields(card_id, {"topic": "tidied"}, "drain")
        self.board.record_hook(card_id, "Stop", {})
        for actor in ("cli", "bosun", "talker"):
            self.board.record_event(card_id, "note", actor, text=f"{actor} wrote this")
        actors = [e["actor"] for e in self.board.events(card_id)][-7:]
        self.assertEqual(actors, ["house", "drain", "drain", "hook", "cli", "bosun", "talker"])
        self.assert_backlog_since(card_id, reached)

    def test_his_action_before_it_reached_review_does_not_count(self):
        """A send-back and a new review: the clock is the new review's, not his older tap."""
        self.days_ago(20)
        card_id = self.at_review()
        self.days_ago(12)
        self.board.note(card_id, "try it the other way", "human")
        self.board.stage(card_id, "building", "human")
        reached = self.days_ago(9)
        self.board.stage(card_id, "review", "house", plan_ref="plan.md", output_ref="out.md")
        self.days_ago(0)
        self.assert_backlog_since(card_id, reached)

    def test_the_backlog_switch_itself_never_resets_the_clock(self):
        """`auto` hands the card back to the date it had, not to today."""
        card_id = self.review_at(8)
        reached = self.derived(card_id)["backlog_since"]
        self.board.set_backlog(card_id, "active", "human")
        self.board.set_fields(card_id, {"options": {"backlog": None}}, "human")   # the deck's way
        self.assert_backlog_since(card_id, reached)

    def test_a_set_that_also_changes_something_of_his_is_his(self):
        """The passes themselves run in tests/test_backlogclock.py, each through its own
        writer. This shape is written by hand because no writer makes it: it is the edge of
        the rule, a pass's option beside a field or an option only he sets."""
        card_id = self.review_at(8)
        reached = self.derived(card_id)["backlog_since"]
        self.board.set_fields(card_id, {"options": {"shipping": {"pending": []}}}, "human")
        self.assert_backlog_since(card_id, reached)
        for fields in ({"topic": "deck", "options": {"shipping": {"pending": [1]}}},
                       {"options": {"shipping": {"pending": [2]}, "archived": False, "kind": "bug"}}):
            with self.subTest(fields=fields):
                self.assertTrue(views.his_action("set", fields))
        self.board.set_fields(card_id, {"topic": "deck", "options": {"shipping": {"pending": [1]}}}, "human")
        self.assertFalse(self.derived(card_id)["backlog"])

    def test_the_two_stamps_are_compared_as_instants_whatever_their_offsets(self):
        """A stamp is ISO text with the offset of the machine that wrote it, so the later
        instant can be the one that sorts first as text."""
        east, utc = "2026-09-28T10:00:00+05:30", "2026-09-28T06:00:00+00:00"   # 04:30Z, then 06:00Z
        self.assertEqual(views.later(east, utc), utc)
        self.assertEqual(views.later(utc, east), utc, "an action stamped before the review never moves it")
        self.assertEqual((views.later(east, None), views.later(east, "not a stamp")), (east, east))
        self.board.now = lambda: east
        card_id = self.at_review()
        self.board.now = lambda: utc
        self.board.note(card_id, "looked", "human")
        self.days_ago(0)                                     # 8 days and 3 hours after his note
        self.assert_backlog_since(card_id, utc)
        self.board.now = lambda: "2026-10-05T05:00:00+00:00"   # 7 days past the review, not past his note
        self.assertFalse(self.derived(card_id)["backlog"])
        self.board.now = lambda: utc
        other = self.at_review()
        self.board.now = lambda: east                        # a clock behind: recorded after, stamped before
        self.board.note(other, "looked", "human")
        self.days_ago(0)
        self.assertEqual(self.derived(other)["backlog_since"], utc)

    def test_the_override_still_wins_both_ways(self):
        old, quiet = self.review_at(8), self.review_at(30)
        self.board.note(old, "looked", "human")
        self.board.set_backlog(old, "backlog", "human")
        self.assertTrue(self.derived(old)["backlog"], "his note today does not undo his own move")
        self.assertFalse(self.derived(old)["needs_you"])
        self.board.set_backlog(quiet, "active", "human")
        self.assertFalse(self.derived(quiet)["backlog"])
        self.assertTrue(self.derived(quiet)["needs_you"])

    def test_the_decks_stamp_is_the_instant_the_rule_measured_from(self):
        card_id = self.review_at(10)
        reached = self.derived(card_id)["backlog_since"]
        noted = self.days_ago(3)
        self.board.note(card_id, "looked", "human")
        self.days_ago(0)
        row = self.board._row(card_id)
        self.assertEqual(self.board.backlog_clock(row), noted)
        self.assertEqual(self.derived(card_id)["backlog_since"], noted)
        self.assertEqual(self.derived(card_id)["gate_since"], reached,
                         "when the gate opened is still when it reached review")

    def test_a_card_not_at_its_outcome_gate_is_unaffected(self):
        self.days_ago(30)
        building = self.at_building()
        planned = self.card(autonomy="attended", repo="keel")
        self.board.stage(planned, "assigned", "human")
        self.board.stage(planned, "planning", "drain", plan_ref="plan.md")
        self.days_ago(0)
        for card_id in (building, planned):
            self.board.note(card_id, "looked", "human")
            self.assertFalse(self.derived(card_id)["backlog"])
            self.assertIsNone(self.derived(card_id)["backlog_since"])
        self.assertTrue(self.derived(planned)["needs_you"])

    def test_the_clock_is_read_once_per_card_and_only_at_an_outcome_gate(self):
        """Derived fields are computed for every card on every deck read: one answer serves
        the rule and the stamp, and a card that is not at its outcome gate asks nothing."""
        at_gate, building = self.review_at(8), self.at_building()
        self.board.note(at_gate, "looked", "human")
        with mock.patch.object(self.board, "backlog_clock", wraps=self.board.backlog_clock) as clock:
            self.board.get(at_gate)
            self.assertEqual(clock.call_count, 1)
            self.board.set_backlog(at_gate, "active", "human")
            self.assertEqual(clock.call_count, 2, "the override still shows the stamp, read once")
            clock.reset_mock()
            self.board.get(building)
            self.board.get(self.card())
            clock.assert_not_called()


class FollowUpTest(BoardCase):
    """`from` records that a card came out of another one, and changes nothing else.

    The board's second relation. `parent` is a slice and makes the parent a tracking card;
    `from` is a follow-up and leaves both cards exactly as they were (c-297).
    """

    def test_a_follow_up_leaves_the_origin_ordinary(self):
        origin = self.at_building()
        follow_up = self.card(title="the follow-up", from_card=origin)
        self.assertEqual(self.board.get(follow_up)["from"], origin)
        derived = self.board.get(origin)["derived"]
        self.assertIsNone(derived["parent_stage"])
        self.assertEqual(self.board.get(origin)["stage"], "building")
        self.board.stage(origin, "review", "house", plan_ref="p", output_ref="o")
        self.assertTrue(self.board.get(origin)["derived"]["outcome_gate"])
        self.assertTrue(self.board.get(origin)["derived"]["needs_you"])

    def test_the_origin_lists_its_follow_ups_oldest_first(self):
        origin = self.card()
        first = self.card(title="one", from_card=origin)
        second = self.card(title="two", from_card=origin)
        self.assertEqual(self.board.get(origin)["derived"]["follow_ups"], [first, second])
        self.assertEqual(self.board.get(first)["derived"]["follow_ups"], [])

    def test_a_follow_up_may_cross_spaces(self):
        origin = self.card(space="personal")
        follow_up = self.card(space="work", from_card=origin)
        self.assertEqual(self.board.get(follow_up)["from"], origin)

    def test_an_unknown_origin_is_refused_and_a_card_is_not_its_own(self):
        with self.assertRaisesRegex(Refused, "no card c-999"):
            self.card(from_card="c-999")
        card_id = self.card()
        with self.assertRaisesRegex(Refused, "come out of itself"):
            self.board.set_fields(card_id, {"from": card_id}, "human")

    def test_set_moves_it_and_an_empty_value_clears_it(self):
        origin, other = self.card(), self.card()
        card_id = self.card(from_card=origin)
        self.board.set_fields(card_id, {"from": other}, "human")
        self.assertEqual(self.board.get(card_id)["from"], other)
        self.board.set_fields(card_id, {"from": ""}, "human")
        self.assertIsNone(self.board.get(card_id)["from"])
        self.assertEqual(self.board.get(other)["derived"]["follow_ups"], [])

    def test_a_follow_up_is_still_startable_and_the_origin_still_approves(self):
        origin = self.at_review()
        follow_up = self.card(from_card=origin)
        self.board.stage(follow_up, "assigned", "human")
        self.assertTrue(self.board.get(follow_up)["derived"]["startable"])
        self.board.approve(origin, "outcome", "human")
        self.assertEqual(self.board.get(origin)["stage"], "done")

    def test_an_older_board_gains_the_from_column_on_open(self):
        import sqlite3
        from keel import board as board_module
        path = self.dir / "old.db"
        old_schema = board_module.SCHEMA.replace('  "from" TEXT,\n', "")
        self.assertNotIn("from", old_schema)
        conn = sqlite3.connect(path)
        conn.executescript(old_schema)
        conn.execute("INSERT INTO cards (id, space, title, created_at, updated_at) VALUES "
                     "('c-001', 'personal', 'old', 'now', 'now')")
        conn.commit()
        conn.close()
        opened = Board(path)
        self.assertIn("from", opened.columns())
        self.assertIsNone(opened.get("c-001")["from"])
        opened.insert_card({"id": "c-002", "space": "personal", "title": "new",
                            "autonomy": "autonomous", "stage": "inbox", "from": "c-001"}, "cli")
        self.assertEqual(opened.get("c-001")["derived"]["follow_ups"], ["c-002"])
        self.assertEqual(opened.migrate(), [])
        opened.close()


class ParentSetTest(BoardCase):
    """`kb set <id> parent=<id>` and `parent=`: the only way to change or clear a parent."""

    def test_clearing_the_last_child_makes_the_tracking_card_ordinary_again(self):
        parent = self.at_building()
        child, = self.board.split(parent, [{"title": "A"}], "house")
        with self.assertRaisesRegex(Refused, "tracking"):
            self.board.stage(parent, "review", "human", plan_ref="p", output_ref="o")
        self.board.set_fields(child, {"parent": ""}, "human")
        self.assertIsNone(self.board.get(child)["parent"])
        self.assertIsNone(self.board.get(parent)["derived"]["parent_stage"])
        self.board.stage(parent, "review", "human", plan_ref="p", output_ref="o")
        self.assertEqual(self.board.get(parent)["stage"], "review")

    def test_a_parent_must_exist_and_may_not_be_the_card_or_its_own_descendant(self):
        top = self.card()
        middle = self.card(parent=top)
        bottom = self.card(parent=middle)
        with self.assertRaisesRegex(Refused, "no card c-999"):
            self.board.set_fields(bottom, {"parent": "c-999"}, "human")
        with self.assertRaisesRegex(Refused, "its own parent"):
            self.board.set_fields(top, {"parent": top}, "human")
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(top, {"parent": bottom}, "human")

    def test_the_change_is_recorded_as_a_set_event(self):
        parent, other = self.card(), self.card()
        child = self.card(parent=parent)
        self.board.set_fields(child, {"parent": other}, "human")
        last = self.board.events(child)[-1]
        self.assertEqual((last["kind"], last["data"]), ("set", {"parent": other}))


class TrackingParentRefusalTest(BoardCase):
    """`kb create --parent X` refuses a card a house is working or has worked (c-297).

    A house that files one follow-up under its own card used to turn that card into a
    tracking card and lose its gate; the refusal names `--from` and `kb split` instead.
    """

    def test_a_card_with_a_session_refuses_a_new_child(self):
        origin = self.at_building()
        self.board.set_session(origin, "0abc1234-0000-4000-8000-000000000009", "drain")
        with self.assertRaisesRegex(Refused, "--from"):
            self.card(parent=origin)

    def test_a_claimed_card_refuses_a_new_child(self):
        origin = self.card()
        self.board.stage(origin, "assigned", "human")
        self.board.claim(origin, "mac", "drain")
        with self.assertRaisesRegex(Refused, "kb split"):
            self.card(parent=origin)

    def test_a_card_at_a_worked_stage_refuses_a_new_child(self):
        for stage in ("planning", "building", "review", "done"):
            with self.subTest(stage=stage):
                origin = self.at_review()
                if stage != "review":
                    self.board.set_fields(origin, {"session_id": None}, "human")
                    self.board.conn.execute("UPDATE cards SET stage = ? WHERE id = ?",
                                            (stage, origin))
                with self.assertRaisesRegex(Refused, "tracking card"):
                    self.card(parent=origin)

    def test_an_inbox_or_assigned_card_with_no_session_takes_children(self):
        for stage in ("inbox", "assigned"):
            with self.subTest(stage=stage):
                parent = self.card()
                if stage == "assigned":
                    self.board.stage(parent, "assigned", "human")
                child = self.card(parent=parent)
                self.assertEqual(self.board.get(child)["parent"], parent)

    def test_a_card_that_is_already_tracking_takes_another_child(self):
        parent = self.card()
        first = self.card(parent=parent)
        self.board.stage(first, "assigned", "human")
        self.board.stage(first, "building", "drain")
        self.assertEqual(self.board.get(parent)["derived"]["parent_stage"], "building")
        second = self.card(parent=parent)
        self.assertEqual(self.board.get(parent)["derived"]["parent_stage"], "building")
        self.assertEqual(self.board.get(second)["parent"], parent)

    def test_split_still_turns_a_worked_card_into_a_tracking_card(self):
        origin = self.at_building()
        self.board.set_session(origin, "0abc1234-0000-4000-8000-000000000009", "drain")
        children = self.board.split(origin, [{"title": "A"}, {"title": "B"}], "house")
        self.assertEqual(len(children), 2)
        self.assertEqual(self.board.get(origin)["derived"]["parent_stage"], "building")


class StopCheckTrackingTest(BoardCase):
    """A tracking card's house has nothing left to stage, so it may stop (c-292)."""

    def test_a_tracking_card_is_not_nudged(self):
        origin = self.at_building()
        self.board.split(origin, [{"title": "A"}], "house")
        self.assertIsNone(self.board.stop_check(origin, {"hook_event_name": "Stop"}))
        self.assertEqual(self.board.stop_blocks(origin), 0)
        self.assertIsNone(self.board.get(origin)["blocked_reason"])
        hooks = [e for e in self.board.events(origin) if e["kind"] == "hook"]
        self.assertEqual(hooks[-1]["data"].get("tracking"), True)


class ArchivedParentTest(BoardCase):
    """B4, c-427: an archived card never becomes, or stays, a tracking card.

    c-014 was archived in July, a new card was filed under it with `--parent`, and it came
    back on the board as a tracking card. Archived is history: a slice under it is refused
    at create and at `kb set parent=`, and the derivation ignores an archived parent and
    archived children."""

    def archived(self, **kwargs) -> str:
        card_id = self.card(**kwargs)
        self.board.set_fields(card_id, {"options": {"archived": True}}, "human")
        return card_id

    def test_create_under_an_archived_parent_is_refused(self):
        parent = self.archived()
        with self.assertRaisesRegex(Refused, f"{parent} is archived"):
            self.card(parent=parent)

    def test_the_refusal_holds_when_the_archived_parent_already_has_a_child(self):
        parent = self.card()
        self.card(parent=parent)
        self.board.set_fields(parent, {"options": {"archived": True}}, "human")
        with self.assertRaisesRegex(Refused, "archived"):
            self.card(parent=parent)

    def test_set_parent_goes_through_the_same_check(self):
        parent, child = self.archived(), self.card()
        with self.assertRaisesRegex(Refused, "archived"):
            self.board.set_fields(child, {"parent": parent}, "human")
        worked = self.at_building()
        with self.assertRaisesRegex(Refused, "cannot become a tracking card"):
            self.board.set_fields(child, {"parent": worked}, "human")
        self.assertIsNone(self.board.get(child)["parent"])

    def test_set_parent_under_a_tracking_card_and_clearing_it_still_work(self):
        parent = self.card()
        self.card(parent=parent)
        child = self.card()
        self.assertEqual(self.board.set_fields(child, {"parent": parent}, "human")["parent"], parent)
        self.assertIsNone(self.board.set_fields(child, {"parent": ""}, "human")["parent"])

    def test_an_archived_parent_with_a_live_child_is_not_tracking(self):
        parent = self.card()
        self.card(parent=parent)
        self.board.set_fields(parent, {"options": {"archived": True}}, "human")
        derived = self.board.get(parent)["derived"]
        self.assertFalse(derived["tracking"])
        self.assertIsNone(derived["parent_stage"])
        self.assertIsNone(derived["tracking_tally"])

    def test_a_parent_whose_only_child_is_archived_is_an_ordinary_card_again(self):
        parent = self.card()
        child = self.card(parent=parent)
        self.board.set_fields(child, {"options": {"archived": True}}, "human")
        self.assertFalse(self.board.get(parent)["derived"]["tracking"])
        # And the board agrees with the derivation: its own stage moves work again.
        self.board.stage(parent, "assigned", "human")
        self.assertTrue(self.board.get(parent)["derived"]["startable"])

    def test_a_live_child_beside_an_archived_one_is_what_the_tally_counts(self):
        parent = self.card()
        self.card(parent=parent)
        gone = self.card(parent=parent)
        self.board.set_fields(gone, {"options": {"archived": True}}, "human")
        self.assertEqual(self.board.get(parent)["derived"]["tracking_tally"], "1 of 1 waiting")


class GateSinceTest(BoardCase):
    """`derived.gate_since`: when the thing he is waiting on OPENED, the event that opened
    it, for every needs-you card (F5). Attention's age read `updated_at`, which any note,
    set or voice-hold release moves, so a gate open for two days read "2m"."""

    def setUp(self):
        super().setUp()
        self.base = datetime(2026, 9, 20, 9, 0).astimezone()

    @contextmanager
    def at_hour(self, hours: float):
        stamp = (self.base + timedelta(hours=hours)).isoformat(timespec="seconds")
        self.board.now = lambda: stamp
        try:
            yield stamp
        finally:
            self.board.__dict__.pop("now", None)

    def since(self, card_id: str):
        return self.board.get(card_id)["derived"]["gate_since"]

    def test_a_plan_gate_counts_from_the_stage_that_opened_it_not_a_later_note(self):
        with self.at_hour(0):
            card_id = self.card(autonomy="attended")
        with self.at_hour(1) as opened:
            self.board.stage(card_id, "planning", "drain", plan_ref="plan.md")
        with self.at_hour(30):
            self.board.note(card_id, "a later word", "human")
        self.assertEqual(self.since(card_id), opened)

    def test_a_plan_given_after_the_stage_opens_the_gate_when_it_is_given(self):
        with self.at_hour(0):
            card_id = self.card(autonomy="attended")
            self.board.stage(card_id, "planning", "drain")
        self.assertIsNone(self.since(card_id), "no plan yet, so no gate is open")
        with self.at_hour(2) as opened:
            self.board.set_fields(card_id, {"plan_ref": "plan.md"}, "house")
        with self.at_hour(9):
            self.board.note(card_id, "noted", "house")
        self.assertEqual(self.since(card_id), opened)

    def test_an_outcome_gate_counts_from_the_move_to_review(self):
        with self.at_hour(0):
            card_id = self.at_building()
        with self.at_hour(3) as opened:
            self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        with self.at_hour(20):
            self.board.note(card_id, "a note", "human")
        self.assertEqual(self.since(card_id), opened)

    def test_a_block_counts_from_the_block_and_wins_over_the_gate_behind_it(self):
        with self.at_hour(0):
            card_id = self.at_building()
        with self.at_hour(4) as opened:
            self.board.block(card_id, "needs a key", "house")
        with self.at_hour(12):
            self.board.note(card_id, "still waiting", "human")
        self.assertEqual(self.since(card_id), opened)

    def test_a_notice_counts_from_when_it_was_filed(self):
        with self.at_hour(0) as opened:
            card_id = self.card(autonomy="attended", topic="notice", options={"notice_key": "k"})
        with self.at_hour(6):
            self.board.set_fields(card_id, {"brief": "restated"}, "cli")
        self.assertEqual(self.since(card_id), opened)

