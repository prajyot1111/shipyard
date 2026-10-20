"""A tracking card whose slices are all done is closed by the drain (lane X, c-649).

c-277 on the box, "Voice, the next level", was split into nine slices. All nine reached done
on 2026-09-20, its house's last session ended that day, and the card sat at `building` from
then on with needs-you false, so the deck showed it nowhere. Lane X brought such a card to
his outcome gate; c-628 then sat there with no outcome. Now the drain closes it to done with
a rollup as its outcome; one already at review (from before, or by his Back to your gate) is
closed on the next pass, and his Approve there still closes it (nothing merged, landed or
published, on every path the tap can take); Send back puts it back to tracking; and a slice
that leaves done while the parent waits at review takes the parent back to building.
"""

import unittest
from pathlib import Path
from unittest import mock

from keel import actions, landing, merging, planlint, trackclose
from keel.board import Board, Refused
from tests.helpers import SESSION, BoardCase, background_row
from tests.test_drain import DrainCase
from tests.test_landing import LandingCase, sh


def finish(board: Board, card_id: str, published=None) -> None:
    """A slice through its own gates to done: built, at review, approved by him."""
    board.stage(card_id, "building", "drain")
    board.stage(card_id, "review", "house", plan_ref="plan.md", output_ref="out.md")
    board.approve(card_id, "outcome", "human",
                  publish=(lambda card: published) if published else None)


def closes(board: Board, card_id: str) -> list[dict]:
    """The drain's closes: its moves to done, each saying why."""
    return [e for e in board.events(card_id) if e["kind"] == "stage" and e["actor"] == "drain"
            and (e["data"] or {}).get("to") == "done" and trackclose.CLOSED in (e["text"] or "")]


def moves_to(board: Board, card_id: str, stage: str) -> list[dict]:
    return [e for e in board.events(card_id)
            if e["kind"] == "stage" and (e["data"] or {}).get("to") == stage]


# ----- c-649: the drain closes it, with a rollup as its outcome -----

class LastSliceLandsTest(DrainCase):
    """The reproduction: c-628's last slice landed and the card sat at his outcome gate with
    no output_ref. Now the drain closes it to done itself, and the rollup is its outcome."""

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True        # nothing here is about starting slices

    def landed(self, kid: str, sha: str) -> None:
        """A slice through its own gate and landed on next, with its own outcome written."""
        own = self.cfg.cards_dir / kid
        own.mkdir(parents=True, exist_ok=True)
        (own / "context.md").write_text(f"---\nkind: outcome\n---\n# {kid}\n\n"
                                        f"Built {kid} as planned. Second line.\n\n## Where it stands\n\nDone.\n")
        finish(self.board, kid)
        self.board.set_fields(kid, {"options": {"landing": {
            "state": "landed", "sha": sha, "merge": "f" * 40,
            "published": "fffffff merged into next"}}}, "drain")

    def test_the_last_slice_landing_closes_it_with_the_rollup_linked(self):
        parent = self.tracking(slices=2)
        a, b = [row["id"] for row in self.board.children(parent)]
        self.landed(a, "a" * 40)
        self.once()
        self.assertEqual(self.board.get(parent)["stage"], "building", "a slice still going")
        self.landed(b, "b" * 40)
        self.once()
        card = self.board.get(parent)
        self.assertEqual(card["stage"], "done")
        self.assertFalse(card["derived"]["needs_you"])
        self.assertTrue(card["output_ref"], "the rollup is its outcome")
        rollup = Path(card["output_ref"])
        self.assertEqual(rollup, self.cfg.cards_dir / parent / "outcome.md")
        text = rollup.read_text()
        for kid, sha in ((a, "aaaaaaa"), (b, "bbbbbbb")):
            self.assertIn(kid, text)
            self.assertIn(self.board.get(kid)["title"], text)
            self.assertIn(sha, text)
            self.assertIn(f"Built {kid} as planned", text)
            self.assertIn(str(self.cfg.cards_dir / kid / "context.md"), text)
        self.assertTrue(planlint.lint_text(text, "outcome.md", ships=True)["ok"])
        self.assertEqual(len(closes(self.board, parent)), 1, "one move, saying why")

    def test_one_already_waiting_at_his_gate_closes_on_the_next_pass(self):
        parent = self.tracking(slices=1)
        kid = self.board.children(parent)[0]["id"]
        self.landed(kid, "c" * 40)
        self.board.stage(parent, "review", "drain")        # c-628: brought there before c-649
        self.once()
        card = self.board.get(parent)
        self.assertEqual(card["stage"], "done")
        self.assertTrue(Path(card["output_ref"]).is_file())
        with self.assertRaisesRegex(Refused, "done"):
            self.board.approve(parent, "outcome", "human")    # his late tap finds it closed


# ----- X5 and X1: the drain closes it once, and only when every slice is done -----

class StuckTrackingTest(DrainCase):
    """The reproduction: a tracking parent at building whose slices are all done."""

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True        # nothing here is about starting slices

    def all_done(self, slices=3) -> tuple[str, list[str]]:
        parent = self.tracking(slices=slices)
        kids = [row["id"] for row in self.board.children(parent)]
        for kid in kids:
            finish(self.board, kid)
        return parent, kids

    def test_one_close_never_every_pass(self):
        parent, _ = self.all_done()
        for _ in range(4):
            self.once()
        self.assertEqual(len(closes(self.board, parent)), 1)
        self.assertEqual(moves_to(self.board, parent, "review"), [], "no gate of its own")

    def test_how_each_slice_ended_is_said(self):
        parent = self.tracking(slices=3)
        a, b, c = [row["id"] for row in self.board.children(parent)]
        finish(self.board, a, published="pull request #12 ready")
        finish(self.board, b)
        # A slice closed with a stage move rather than an approve (a notice, say) reads so.
        self.board.set_fields(c, {"options": {"notice_key": "x"}}, "human")
        self.board.stage(c, "done", "drain")
        self.once()
        rollup = open(self.board.get(parent)["output_ref"]).read()
        lines = [line for line in rollup.splitlines() if line.startswith("- **")]
        self.assertIn("approved, published", lines[0])
        self.assertIn("pull request #12 ready", lines[0])
        self.assertTrue(lines[1].endswith("approved."), lines[1])
        self.assertIn("staged done by drain", lines[2])

    def test_a_card_with_no_children_is_untouched(self):
        card_id = self.housed(stage="building")
        self.fake.rows.append(dict(background_row(card_id, SESSION), status="busy"))
        self.once()
        self.assertEqual(self.board.get(card_id)["stage"], "building")
        self.assertEqual(closes(self.board, card_id), [])

    def test_a_tracking_card_with_a_slice_still_going_stays_where_it_is(self):
        parent = self.tracking(slices=2)
        a, b = [row["id"] for row in self.board.children(parent)]
        finish(self.board, a)
        self.board.stage(b, "building", "drain")
        self.once()
        self.assertEqual(self.board.get(parent)["stage"], "building")
        self.assertFalse(self.board.get(parent)["derived"]["needs_you"])

    def test_an_archived_slice_does_not_count(self):
        parent = self.tracking(slices=2)
        a, b = [row["id"] for row in self.board.children(parent)]
        finish(self.board, a)
        self.board.set_fields(b, {"options": {"archived": True}}, "human")
        self.once()
        self.assertEqual(self.board.get(parent)["stage"], "done")

    def test_an_archived_tracking_card_is_left_alone(self):
        parent, _ = self.all_done(slices=1)
        self.board.set_fields(parent, {"options": {"archived": True}}, "human")
        self.once()
        self.assertEqual(self.board.get(parent)["stage"], "building")

# ----- X3: a slice that leaves done takes the parent back -----

class SliceLeavesDoneTest(DrainCase):
    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True
        self.parent = self.tracking(slices=2)
        self.kids = [row["id"] for row in self.board.children(self.parent)]
        for kid in self.kids:
            finish(self.board, kid)
        self.board.stage(self.parent, "review", "drain")     # at his gate, as before c-649

    def test_a_reopened_slice_takes_the_parent_back_to_building_and_it_comes_back(self):
        self.board.stage(self.kids[0], "building", "human", note="one more thing")
        card = self.board.get(self.parent)
        self.assertFalse(card["derived"]["outcome_gate"], "a slice not done is no gate")
        with self.assertRaisesRegex(Refused, self.kids[0]):
            self.board.approve(self.parent, "outcome", "human")
        self.once()
        card = self.board.get(self.parent)
        self.assertEqual(card["stage"], "building")
        self.assertTrue(card["derived"]["tracking"])
        back = [e["text"] for e in self.board.events(self.parent) if e["kind"] == "note"
                and trackclose.BACK in (e["text"] or "")]
        self.assertEqual(len(back), 1)
        self.assertIn(self.kids[0], back[0])
        self.once()
        back_moves = [e for e in moves_to(self.board, self.parent, "building")
                      if e["data"].get("from") == "review"]
        self.assertEqual(len(back_moves), 1, "once")
        self.board.stage(self.kids[0], "review", "house", plan_ref="p", output_ref="o")
        self.board.approve(self.kids[0], "outcome", "human")
        self.once()
        self.assertEqual(self.board.get(self.parent)["stage"], "done")
        self.assertEqual(len(closes(self.board, self.parent)), 1)

    def test_a_new_slice_filed_under_it_takes_it_back(self):
        new = self.board.create("personal", "one more", parent=self.parent, actor="human")
        self.once()
        self.assertEqual(self.board.get(self.parent)["stage"], "building")
        self.board.stage(new, "assigned", "human")
        finish(self.board, new)
        self.once()
        self.assertEqual(self.board.get(self.parent)["stage"], "done")


# ----- X2: Approve outcome closes it; Send back puts it back to tracking -----

class CloseOnTheBoardTest(BoardCase):
    def tracking_at_review(self) -> str:
        parent = self.at_building()
        for kid in self.board.split(parent, [{"title": "a"}, {"title": "b"}], "house"):
            finish(self.board, kid)
        self.board.stage(parent, "review", "drain")
        return parent

    def test_approve_outcome_closes_it_and_publishes_nothing(self):
        parent = self.tracking_at_review()
        publish = mock.Mock(side_effect=AssertionError("a tracking card publishes nothing"))
        card = self.board.approve(parent, "outcome", "human", publish=publish)
        publish.assert_not_called()
        self.assertEqual(card["stage"], "done")
        self.assertEqual(card["derived"]["parent_stage"], "done")
        self.assertFalse(card["derived"]["needs_you"])
        approve = [e for e in self.board.events(parent) if e["kind"] == "approve"][-1]
        self.assertEqual(approve["data"]["tracking"], True)
        self.assertNotIn("published", approve["data"])

    def test_the_stage_moves_are_the_close_path_and_nothing_else(self):
        parent = self.at_building()
        a, b = self.board.split(parent, [{"title": "a"}, {"title": "b"}], "house")
        with self.assertRaisesRegex(Refused, "tracking"):
            self.board.stage(parent, "review", "drain")        # slices not done yet
        finish(self.board, a)
        finish(self.board, b)
        with self.assertRaisesRegex(Refused, "tracking"):
            self.board.stage(parent, "done", "human")          # the close is the drain's, or his Approve
        with self.assertRaisesRegex(Refused, "tracking"):
            self.board.stage(parent, "review", "house")        # the drain's move, or his
        self.board.stage(parent, "review", "drain")
        with self.assertRaisesRegex(Refused, "tracking"):
            self.board.stage(parent, "planning", "human")
        self.board.stage(parent, "building", "human", note="sent back")
        self.assertEqual(self.board.get(parent)["stage"], "building")

    def test_before_the_drain_moves_it_the_deck_already_reads_review_not_done(self):
        parent = self.at_building()
        for kid in self.board.split(parent, [{"title": "a"}], "house"):
            finish(self.board, kid)
        derived = self.board.get(parent)["derived"]
        self.assertEqual(derived["parent_stage"], "review")
        self.assertFalse(derived["outcome_gate"])

    def test_no_land_relay_for_a_tracking_card(self):
        parent = self.tracking_at_review()
        switched = Board(self.dir / "board.db", switches={"merge_queue"})
        self.addCleanup(switched.close)
        with self.assertRaisesRegex(Refused, "lands nothing"):
            switched.relay(parent, "land", "human", "box", sha="abc")


class SendBackTest(DrainCase):
    def test_send_back_is_a_note_and_a_move_and_resumes_nothing(self):
        self.cfg.drain_paused = True
        parent = self.tracking(slices=1)
        finish(self.board, self.board.children(parent)[0]["id"])
        self.board.stage(parent, "review", "drain")     # at his gate, as before c-649
        calls = []

        def fake_kb(cfg, argv, **kwargs):
            calls.append(argv)
            if argv[0] == "note":
                self.board.note(argv[1], argv[2], "human")
            elif argv[0] == "stage":
                self.board.stage(argv[1], argv[2], "human", note=argv[argv.index("--note") + 1])
            return self.board.get(argv[1])

        with mock.patch.object(actions, "run_kb", side_effect=fake_kb), \
                mock.patch.object(actions, "resume_with") as resume:
            answer = actions.act(self.cfg, self.board, {"verb": "sendback", "id": parent,
                                                        "reason": "one slice missed the docs"})
        resume.assert_not_called()
        self.assertEqual([argv[0] for argv in calls], ["note", "stage"])
        self.assertNotIn("--relay", calls[1])
        self.assertIsNone(answer["resumed"])
        card = self.board.get(parent)
        self.assertEqual(card["stage"], "building")
        self.assertIn("one slice missed the docs",
                      [e["text"] for e in self.board.events(parent) if e["kind"] == "note"])
        for _ in range(2):
            self.once()
        self.assertEqual(self.board.get(parent)["stage"], "building",
                         "sent back stays back until a slice changes")


# ----- X2 on the merge-queue path: no relay, no pre-run, nothing merged -----

class QueueTest(LandingCase):
    def tracking_here(self) -> str:
        parent = self.board.create("personal", "big", repo="keel", actor="human")
        self.board.stage(parent, "assigned", "human")
        self.board.claim(parent, "box", "drain")
        self.board.stage(parent, "building", "drain")
        self.board.set_session(parent, SESSION, "drain", bg_id=SESSION[:8])
        for kid in self.board.split(parent, [{"title": "a"}, {"title": "b"}], "house"):
            finish(self.board, kid)
        self.board.stage(parent, "review", "drain")
        return parent

    def test_a_tracking_card_is_not_mergeable_and_is_never_pre_run(self):
        parent = self.tracking_here()
        card = self.board.get(parent)
        self.assertFalse(landing.mergeable(self.cfg, card))
        self.assertIsNone(landing.route(self.cfg, card))
        self.board.stage(self.card, "building", "human")    # only the tracking card at review
        self.assertFalse(landing.pre_run_one(self.cfg, self.board))
        self.assertEqual(self.spawned, [])

    def test_the_deck_tap_closes_it_with_no_relay_and_nothing_merged(self):
        parent = self.tracking_here()
        kb = []

        def fake_kb(cfg, argv, **kwargs):
            kb.append(argv)
            if argv[0] == "approve":
                from keel import adapters
                publish = adapters.publisher(cfg, "personal")
                return self.board.approve(argv[1], argv[2], "human", publish=publish)
            return self.board.get(argv[1])

        before = sh(self.repo, "git", "rev-parse", "main")
        with mock.patch.object(actions, "run_kb", side_effect=fake_kb), \
                mock.patch.object(actions, "run_keel", return_value=""), \
                mock.patch.object(merging, "publish") as publish:
            actions.act(self.cfg, self.board, {"verb": "approve", "id": parent, "gate": "outcome"})
        publish.assert_not_called()
        self.assertEqual([argv[0] for argv in kb], ["approve"])
        self.assertEqual(self.board.get(parent)["stage"], "done")
        self.assertEqual(self.board.get(parent)["derived"]["relays"], [])
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), before)

    def test_the_tap_for_a_work_card_is_kb_approve(self):
        parent = self.board.create("work", "big work", actor="human")
        self.board.stage(parent, "assigned", "human")
        self.board.stage(parent, "building", "drain")
        self.board.set_fields(parent, {"options": {"host": "mac"}}, "human")
        for kid in self.board.split(parent, [{"title": "a"}], "house"):
            finish(self.board, kid)
        self.board.stage(parent, "review", "drain")
        with mock.patch.object(actions, "run_kb", return_value={}) as run_kb:
            actions.act(self.cfg, self.board, {"verb": "approve", "id": parent, "gate": "outcome"})
        self.assertEqual(run_kb.call_args[0][1][:3], ["approve", parent, "outcome"])


# ----- c-649 review: one close, a closed card reopens, a held card waits, the rollup lints -----

EM = "\u2014"                # spelled as its code point: no em-dash in the source itself


class OneCloseTest(BoardCase):
    """Every close of a tracking card is `Board.close_tracking`'s one move (F1, F5, F6)."""

    def split_two(self) -> tuple[str, str, str]:
        parent = self.at_building()
        a, b = self.board.split(parent, [{"title": "a"}, {"title": "b"}], "house")
        return parent, a, b

    def test_his_approve_at_review_leaves_the_rollup_as_its_outcome(self):
        parent, a, b = self.split_two()
        finish(self.board, a)
        finish(self.board, b)
        self.board.stage(parent, "review", "drain")
        card = self.board.approve(parent, "outcome", "human")
        self.assertEqual(card["stage"], "done")
        self.assertEqual(card["output_ref"], str(self.dir / "cards" / parent / trackclose.ROLLUP))
        self.assertTrue(planlint.lint_text(Path(card["output_ref"]).read_text(), "outcome.md",
                                           ships=True)["ok"])

    def test_no_stage_move_reaches_done_whoever_names_himself_the_drain(self):
        parent, a, b = self.split_two()
        finish(self.board, a)
        self.board.stage(b, "building", "drain")
        with self.assertRaisesRegex(Refused, b):
            self.board.stage(parent, "done", "drain")          # a slice still building
        finish(self.board, b)
        with self.assertRaisesRegex(Refused, "tracking"):
            self.board.stage(parent, "done", "drain")          # `kb stage --actor drain` is not the close
        self.assertEqual(self.board.close_tracking(parent, "drain", trackclose.CLOSED)["stage"], "done")


class ReopenTest(DrainCase):
    """A closed tracking card follows its slices again when one leaves done (F2)."""

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True
        self.parent = self.tracking(slices=1)
        self.kid = self.board.children(self.parent)[0]["id"]
        finish(self.board, self.kid)
        self.once()
        self.assertEqual(self.board.get(self.parent)["stage"], "done")

    def test_a_reopened_slice_reopens_it_and_it_closes_again_with_a_fresh_rollup(self):
        self.board.stage(self.kid, "building", "human", note="one more thing")
        self.once()
        self.assertEqual(self.board.get(self.parent)["stage"], "building")
        self.board.set_fields(self.kid, {"title": "A, finished twice"}, "human")
        finish(self.board, self.kid)
        self.once()
        card = self.board.get(self.parent)
        self.assertEqual(card["stage"], "done")
        self.assertEqual(len(closes(self.board, self.parent)), 2)
        self.assertIn("A, finished twice", Path(card["output_ref"]).read_text())

    def test_a_slice_filed_under_it_reopens_it(self):
        new = self.board.create("personal", "one more", parent=self.parent, actor="human")
        self.once()
        self.assertEqual(self.board.get(self.parent)["stage"], "building")
        self.board.stage(new, "assigned", "human")
        finish(self.board, new)
        self.once()
        self.assertEqual(self.board.get(self.parent)["stage"], "done")


class HeldTest(DrainCase):
    """A close waits while he is asked, holding, or blocked (F3)."""

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True
        self.parent = self.tracking(slices=1)
        finish(self.board, self.board.children(self.parent)[0]["id"])

    def assert_waits(self) -> None:
        self.once()
        self.assertNotEqual(self.board.get(self.parent)["stage"], "done")

    def test_a_block_holds_the_close(self):
        self.board.block(self.parent, "he wants to read it first", "human")
        self.assert_waits()

    def test_a_voice_hold_holds_the_close(self):
        self.board.hold_voice(self.parent, 300)
        self.assert_waits()

    def test_a_drop_in_hold_holds_the_close(self):
        self.board.set_fields(self.parent, {"options": {"dropin_hold": {"at": self.board.now()}}},
                              "human")
        self.assert_waits()

    def test_an_open_ask_holds_the_close(self):
        from keel import asks
        asks.raise_ask(self.board, "bosun", "decision", "Close it?", "why not", ["yes|close it", "no|leave it open"],
                       card=self.parent)
        self.assert_waits()


class RaceTest(DrainCase):
    """A slice reopened between the pass's read and its move (F5, F7)."""

    def test_the_card_stays_and_no_rollup_is_left(self):
        parent = self.tracking(slices=1)
        kid = self.board.children(parent)[0]["id"]
        finish(self.board, kid)
        snapshot = self.board.list_cards()
        self.board.stage(kid, "building", "human", note="one more thing")
        with mock.patch.object(self.board, "list_cards", return_value=snapshot):
            moved = trackclose.upkeep(self.board, lambda card: True)
        self.assertEqual(moved["closed"], 0)
        self.assertEqual(self.board.get(parent)["stage"], "building")
        self.assertFalse((self.cfg.cards_dir / parent / trackclose.ROLLUP).exists())

    def test_a_disk_error_on_one_card_does_not_stop_the_next(self):
        first, second = self.tracking(slices=1), self.tracking(slices=1)
        for parent in (first, second):
            finish(self.board, self.board.children(parent)[0]["id"])
        real, said = trackclose.draft_rollup, []

        def flaky(board, card, *args):
            if card["id"] == first:
                raise OSError("disk full")
            return real(board, card, *args)

        with mock.patch.object(trackclose, "draft_rollup", side_effect=flaky):
            moved = trackclose.upkeep(self.board, lambda card: True, said.append)
        self.assertEqual(moved["closed"], 1)
        self.assertEqual(self.board.get(second)["stage"], "done")
        self.assertIn(first, said[0])


class LateTapTest(DrainCase):
    def test_his_tap_after_the_drain_closed_it_returns_the_done_card(self):
        """F8: no kb call, and the rollup stays its outcome."""
        self.cfg.drain_paused = True
        parent = self.tracking(slices=1)
        finish(self.board, self.board.children(parent)[0]["id"])
        self.once()
        ref = self.board.get(parent)["output_ref"]
        with mock.patch.object(actions, "run_kb") as run_kb:
            answer = actions.act(self.cfg, self.board, {"verb": "approve", "id": parent,
                                                        "gate": "outcome"})
        run_kb.assert_not_called()
        self.assertEqual(answer["stage"], "done")
        self.assertEqual(self.board.get(parent)["output_ref"], ref)


class RollupLintTest(DrainCase):
    """The rollup passes `kb lint` whatever its slices wrote (F4, F9, F10)."""

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True

    def rollup_of(self, parent: str) -> str:
        path = self.cfg.cards_dir / parent / trackclose.ROLLUP
        text = path.read_text()
        result = planlint.lint_text(text, "outcome.md", ships=True)
        self.assertTrue(result["ok"], planlint.lines_of(result))
        return text

    def test_an_em_dash_a_relative_link_and_a_long_code_span(self):
        parent = self.tracking(slices=1)
        kid = self.board.children(parent)[0]["id"]
        self.board.set_fields(kid, {"title": f"Voice {EM} the next level"}, "human")
        own = self.cfg.cards_dir / kid
        own.mkdir(parents=True)
        span = "`" + " ".join(["word"] * 70) + "`"
        (own / "context.md").write_text(
            f"---\nkind: outcome\n---\n# t\n\nBuilt it {EM} see [the notes](notes.md). "
            f"Then {span} and more.\n\n## Where it stands\n\nDone.\n")
        finish(self.board, kid)
        self.once()
        text = self.rollup_of(parent)
        self.assertNotIn(EM, text)
        self.assertIn(f"]({own / 'notes.md'})", text)
        line = next(line for line in text.splitlines() if line.startswith(f"- **{kid}"))
        self.assertEqual(line.count("`") % 2, 0, line)

    def test_the_fallback_with_no_slice_outcome_lints(self):
        parent = self.tracking(slices=2)
        for kid in self.board.children(parent):
            finish(self.board, kid["id"])
        self.once()
        self.assertIn("```text", self.rollup_of(parent))

    def test_a_nested_tracking_slice_links_its_own_rollup(self):
        parent = self.tracking(slices=1)
        kid = self.board.children(parent)[0]["id"]
        grand = self.board.create("personal", "grand", parent=kid, actor="human")
        self.board.stage(grand, "assigned", "human")
        finish(self.board, grand)
        own = self.cfg.cards_dir / kid
        own.mkdir(parents=True)
        (own / "context.md").write_text("# before the split\n\nIts house's record.\n")
        mine = lambda card: True
        trackclose.upkeep(self.board, mine)
        trackclose.upkeep(self.board, mine)
        self.assertEqual(self.board.get(parent)["stage"], "done")
        self.assertIn(f"({self.cfg.cards_dir / kid / trackclose.ROLLUP})", self.rollup_of(parent))


    def test_an_artifact_output_is_not_quoted_as_the_slice_s_outcome(self):
        """A personal slice's output_ref may be an artifact in its folder (a board's ops):
        the rollup quotes its context.md, never that file."""
        parent = self.tracking(slices=1)
        kid = self.board.children(parent)[0]["id"]
        own = self.cfg.cards_dir / kid
        own.mkdir(parents=True)
        (own / "context.md").write_text("# Done\n\nThe record in words.\n")
        (own / "outcome-board.ops").write_text("board \"x\"\nnode a cpu \"A\"\n")
        finish(self.board, kid)
        self.board.set_fields(kid, {"output_ref": str(own / "outcome-board.ops")}, "human")
        self.once()
        text = self.rollup_of(parent)
        self.assertIn("The record in words.", text)
        self.assertNotIn("node a cpu", text)


if __name__ == "__main__":
    unittest.main()
