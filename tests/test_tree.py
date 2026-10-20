"""The card tree (`keel/tree.py`): several afters, the outline, assigning a tree, the queue."""

import os
import tempfile
from pathlib import Path

from keel import actions, config as config_module, tree
from keel.board import Board, Refused
from tests.helpers import BoardCase, make_config, write_toml
from tests.test_cli import KbCase


def multi_after_toml(directory: Path, on: bool = True) -> Path:
    """The scratch keel.toml with `[keel] multi_after` set."""
    path = write_toml(directory)
    path.write_text(path.read_text().replace("[keel]\n", f"[keel]\nmulti_after = {'true' if on else 'false'}\n", 1))
    return path


class TreeCase(BoardCase):
    def setUp(self):
        super().setUp()
        self.board.close()
        # Several afters are written only with `[keel] multi_after` on (review item 2).
        self.board = Board(self.dir / "board.db", switches={"multi_after"})

    def blog(self) -> tuple[str, list[str]]:
        """Move my blog: export and host first, import after both, images and domain after it."""
        parent = self.card(title="Move my blog")
        ids = self.board.split(parent, [
            {"title": "export"}, {"title": "host"},
            {"title": "import", "after": ["export", "host"]},
            {"title": "images", "after": "import"}, {"title": "domain", "after": ["import"]}],
            "human")
        return parent, ids

    def review(self, card_id: str) -> None:
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="branch")


class SeveralAftersTest(TreeCase):
    def test_a_split_slice_waits_for_every_sibling_it_names(self):
        _, (export, host, imp, _, _) = self.blog()
        card = self.board.get(imp)
        self.assertEqual(card["after"], f"{export},{host}")
        self.assertEqual(card["derived"]["after"], [export, host])
        self.assertFalse(card["derived"]["startable"])

    def test_startable_only_when_all_are_at_review_or_done(self):
        _, (export, host, imp, _, _) = self.blog()
        self.review(export)
        self.assertEqual(self.board.get(imp)["derived"]["waiting_for"], [host])
        self.assertFalse(self.board.get(imp)["derived"]["startable"])
        self.review(host)
        self.assertEqual(self.board.get(imp)["derived"]["waiting_for"], [])
        self.assertTrue(self.board.get(imp)["derived"]["startable"])

    def test_a_single_after_written_before_is_a_list_of_one(self):
        first = self.card(title="first")
        second = self.card(title="second", after=first)
        self.assertEqual(self.board.get(second)["derived"]["after"], [first])

    def test_create_and_set_take_several(self):
        a, b = self.card(title="a"), self.card(title="b")
        c = self.card(title="c", after=[a, b])
        self.assertEqual(self.board.get(c)["after"], f"{a},{b}")
        d = self.card(title="d")
        self.board.set_fields(d, {"after": f"{a}, {b}, {a}"}, "human")
        self.assertEqual(self.board.get(d)["after"], f"{a},{b}")
        self.board.set_fields(d, {"after": ""}, "human")
        self.assertIsNone(self.board.get(d)["after"])

    def test_a_cycle_and_a_self_wait_are_refused(self):
        _, (export, _, imp, images, _) = self.blog()
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(export, {"after": images}, "human")
        with self.assertRaisesRegex(Refused, "itself"):
            self.board.set_fields(imp, {"after": imp}, "human")
        with self.assertRaises(Refused):
            self.board.set_fields(imp, {"after": "c-999"}, "human")

    def test_split_refuses_a_later_or_unknown_sibling(self):
        with self.assertRaisesRegex(Refused, "unknown sibling"):
            self.board.split(self.card(), [{"title": "A", "after": ["B"]}, {"title": "B"}], "human")


class OutlineTest(TreeCase):
    def test_steps_next_and_unblocks(self):
        parent, (export, host, imp, images, domain) = self.blog()
        outline = self.board.get(parent)["derived"]["tree"]
        steps = [[n["id"] for n in group["cards"]] for group in outline["steps"]]
        self.assertEqual(steps, [[export, host], [imp], [images, domain]])
        by_id = {n["id"]: n for group in outline["steps"] for n in group["cards"]}
        self.assertEqual(outline["next"], [export, host])
        self.assertEqual((by_id[export]["unblocks"], by_id[imp]["unblocks"], by_id[domain]["unblocks"]),
                         (3, 2, 0))

    def test_a_wait_outside_the_tree_is_shown_and_counts_no_step(self):
        outside = self.card(title="outside")
        parent = self.card(title="tree")
        (only,) = self.board.split(parent, [{"title": "only"}], "human")
        self.board.set_fields(only, {"after": outside}, "human")
        node = self.board.get(parent)["derived"]["tree"]["steps"][0]["cards"][0]
        self.assertEqual((node["step"], node["waiting_for"], node["next"]), (1, [outside], False))

    def test_finished_slices_stop_counting_as_unblocked(self):
        parent, (export, host, imp, images, domain) = self.blog()
        self.review(export)
        self.review(host)
        self.board.stage(imp, "building", "drain")
        self.review(imp)
        by_id = {n["id"]: n for g in self.board.get(parent)["derived"]["tree"]["steps"] for n in g["cards"]}
        self.assertEqual(by_id[export]["unblocks"], 2)


    def test_follow_ups_are_listed_apart(self):
        parent, _ = self.blog()
        follow = self.card(title="later", from_card=parent)
        card = self.board.get(parent)
        self.assertEqual(card["derived"]["tree"]["follow_ups"], [follow])
        self.assertTrue(tree.render(card).endswith(f"follow-ups: {follow}"))

    def test_no_tree_on_a_plain_card(self):
        self.assertIsNone(self.board.get(self.card())["derived"]["tree"])


class AssignTest(TreeCase):
    def later_tree(self) -> tuple[str, list[str]]:
        parent = self.card(title="tree")
        a = self.card(title="a", parent=parent)
        b = self.card(title="b", parent=parent, after=a, autonomy="attended")
        return parent, [a, b]

    def test_assign_the_tree_moves_every_inbox_slice_and_says_what_starts(self):
        parent, (a, b) = self.later_tree()
        result = tree.assign(self.board, parent, "human")
        self.assertEqual((result["start_now"], [w["id"] for w in result["wait"]], result["plan_gate"]),
                         ([a], [b], [b]))
        self.assertEqual({self.board.get(c)["stage"] for c in (a, b)}, {"assigned"})
        self.assertEqual(tree.assign_line(result), "2 assigned: 1 starts now, 1 waits; 1 stops at a plan gate first")

    def test_a_dry_run_writes_nothing(self):
        parent, (a, _) = self.later_tree()
        result = tree.assign(self.board, parent, "human", dry_run=True)
        self.assertEqual(len(result["assigned"]), 2)
        self.assertEqual(self.board.get(a)["stage"], "inbox")

    def test_a_plain_card_is_assigned_once(self):
        card = self.card()
        tree.assign(self.board, card, "human")
        self.assertEqual(self.board.get(card)["stage"], "assigned")
        with self.assertRaisesRegex(Refused, "not inbox"):
            tree.assign(self.board, card, "human")

    def test_already_assigned_slices_are_left_alone(self):
        parent, _ = self.blog()
        self.assertEqual(tree.assign(self.board, parent, "human")["assigned"], [])


class QueueTest(TreeCase):
    def assigned(self, title: str, **kwargs) -> str:
        card = self.card(title=title, **kwargs)
        self.board.stage(card, "assigned", "human")
        return card

    def test_filing_order_then_next_moves_a_card_to_the_front(self):
        first, second, third = (self.assigned(t) for t in ("one", "two", "three"))
        self.assertEqual(tree.queue(self.board.list_cards()), [first, second, third])
        tree.to_front(self.board, third, "human")
        self.assertEqual(tree.queue(self.board.list_cards()), [third, first, second])
        tree.to_front(self.board, second, "human")
        self.assertEqual(tree.queue(self.board.list_cards()), [second, third, first])
        tree.to_front(self.board, second, "human", clear=True)
        self.assertEqual(tree.queue(self.board.list_cards()), [third, first, second])

    def test_a_tree_holds_one_place_and_next_on_a_slice_moves_it_inside(self):
        parent, (export, host, imp, images, domain) = self.blog()
        loose = self.assigned("loose")
        self.assertEqual(tree.queue(self.board.list_cards())[-1], loose)
        tree.to_front(self.board, loose, "human")
        self.assertEqual(tree.queue(self.board.list_cards()),
                         [loose, export, host, imp, images, domain])
        tree.to_front(self.board, host, "human")
        self.assertEqual(tree.queue(self.board.list_cards())[:3], [loose, host, export])

    def test_a_second_next_changes_nothing(self):
        card = self.assigned("one")
        self.assigned("two")
        tree.to_front(self.board, card, "human")
        events = len(self.board.events(card))
        tree.to_front(self.board, card, "human")
        self.assertEqual(len(self.board.events(card)), events)

    def test_the_queue_names_why_a_card_is_not_starting(self):
        _, (export, host, imp, _, _) = self.blog()
        rows = {row["id"]: row for row in tree.queue_rows(self.board.list_cards())}
        self.assertTrue(rows[export]["startable"])
        self.assertIn(f"waits for {export}, {host}", tree.queue_line(rows[imp]))


class KbTreeVerbsTest(KbCase):
    def setUp(self):
        super().setUp()
        os.environ["KEEL_CONFIG"] = str(multi_after_toml(self.dir))

    def test_tree_assign_next_and_queue_through_kb(self):
        parent = self.create()
        code, out, err = self.kb("split", parent, "--slice", "A|a", "--slice", "B|b",
                                 "--slice", "C|c|A|B")
        self.assertEqual(code, 0, err)
        a, b, c = out.splitlines()
        self.assertEqual(self.kb_json("show", c)["derived"]["after"], [a, b])
        code, out, _ = self.kb("tree", parent)
        self.assertEqual(code, 0)
        self.assertIn("step 2", out)
        code, out, _ = self.kb("--actor", "voice", "next", b)
        self.assertIn("front", out)
        rows = self.kb_json("queue")
        self.assertEqual([row["id"] for row in rows][:2], [b, a])
        code, out, err = self.kb("create", "--space", "personal", "--title", "w", "--after", a,
                                 "--after", b)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kb_json("show", out)["after"], f"{a},{b}")
        code, out, _ = self.kb("--actor", "voice", "assign", out, "--dry-run")
        self.assertEqual(out, "1 would be assigned: 0 start now, 1 waits")


# ----- after the fresh-context review of c-302 -----

class CyclesThroughTheTreeTest(TreeCase):
    """Item 1: a tracking card's stage follows its slices, so waiting on one's own tree, or
    on a tree that waits on you, leaves every card on the loop waiting for ever."""

    def test_a_slice_cannot_wait_for_its_own_parent(self):
        parent = self.card(title="P")
        (a,) = self.board.split(parent, [{"title": "a"}], "human")
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(a, {"after": parent}, "human")

    def test_a_slice_cannot_wait_for_a_grandparent_either(self):
        top = self.card(title="top")
        (mid,) = self.board.split(top, [{"title": "mid"}], "human")
        (leaf,) = self.board.split(mid, [{"title": "leaf"}], "human")
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(leaf, {"after": top}, "human")

    def test_a_card_cannot_wait_for_a_tree_whose_slice_waits_for_it(self):
        x = self.card(title="X")
        t = self.card(title="T")
        self.card(title="b", parent=t, after=x)
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(x, {"after": t}, "human")

    def test_create_under_a_parent_cannot_wait_for_that_parent(self):
        parent = self.card(title="P")
        with self.assertRaisesRegex(Refused, "cycle"):
            self.card(title="c", parent=parent, after=parent)
        (mid,) = self.board.split(parent, [{"title": "mid"}], "human")
        with self.assertRaisesRegex(Refused, "cycle"):
            self.card(title="d", parent=mid, after=parent)

    def test_create_under_a_parent_cannot_wait_for_a_card_that_waits_for_the_parent(self):
        parent = self.card(title="P")
        waiter = self.card(title="W", after=parent)
        with self.assertRaisesRegex(Refused, "cycle"):
            self.card(title="c", parent=parent, after=waiter)

    def test_waiting_for_another_tree_is_still_fine(self):
        other = self.card(title="other")
        self.board.split(other, [{"title": "o1"}], "human")
        card = self.card(title="c", after=other)
        self.assertEqual(self.board.get(card)["derived"]["after"], [other])


class ParentSetChecksTest(TreeCase):
    """J-2: `kb set <id> parent=` answers to the checks `create --parent` does, since a new
    parent makes a tracking edge exactly as a filing under it does."""

    def test_a_card_cannot_move_under_a_card_it_waits_for(self):
        parent = self.card(title="P")
        card = self.card(title="c", after=parent)
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(card, {"parent": parent}, "human")
        self.assertIsNone(self.board.get(card)["parent"])

    def test_a_card_cannot_move_under_the_tree_it_waits_for(self):
        top = self.card(title="top")
        (mid,) = self.board.split(top, [{"title": "mid"}], "human")
        card = self.card(title="c", after=top)
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(card, {"parent": mid}, "human")

    def test_a_card_cannot_move_under_a_card_its_own_slice_waits_for(self):
        target = self.card(title="T")
        card = self.card(title="c")
        (piece,) = self.board.split(card, [{"title": "s"}], "human")
        self.board.set_fields(piece, {"after": target}, "human")
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(card, {"parent": target}, "human")

    def test_a_card_cannot_move_under_a_card_whose_waiter_it_waits_for(self):
        parent = self.card(title="P")
        waiter = self.card(title="W", after=parent)
        card = self.card(title="c", after=waiter)
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(card, {"parent": parent}, "human")

    def test_a_parent_and_an_after_given_together_are_checked_together(self):
        parent = self.card(title="P")
        card = self.card(title="c")
        with self.assertRaisesRegex(Refused, "cycle"):
            self.board.set_fields(card, {"parent": parent, "after": parent}, "human")

    def test_a_parent_in_another_space_is_refused(self):
        parent = self.card(title="P", space="work")
        card = self.card(title="c")
        with self.assertRaisesRegex(Refused, "work space"):
            self.board.set_fields(card, {"parent": parent}, "human")

    def test_moving_under_an_unrelated_card_still_works(self):
        parent, other = self.card(title="P"), self.card(title="O")
        card = self.card(title="c", after=other)
        self.assertEqual(self.board.set_fields(card, {"parent": parent}, "human")["parent"],
                         parent)


class MultiAfterSwitchTest(BoardCase):
    """Item 2: an older drain or deck reading this board fails on a comma list, so writing
    one is refused until `[keel] multi_after` is on; reading one always works."""

    def test_several_afters_are_refused_with_the_switch_off(self):
        a, b = self.card(title="a"), self.card(title="b")
        with self.assertRaisesRegex(Refused, "multi_after"):
            self.card(title="c", after=[a, b])
        d = self.card(title="d")
        with self.assertRaisesRegex(Refused, "multi_after"):
            self.board.set_fields(d, {"after": f"{a},{b}"}, "human")
        with self.assertRaisesRegex(Refused, "multi_after"):
            self.board.split(self.card(title="p"), [{"title": "A"}, {"title": "B"},
                                                    {"title": "C", "after": ["A", "B"]}], "human")

    def test_one_after_still_works_with_the_switch_off(self):
        a = self.card(title="a")
        c = self.card(title="c", after=[a])
        self.board.set_fields(self.card(title="d"), {"after": a}, "human")
        self.board.split(self.card(title="p"), [{"title": "A"}, {"title": "B", "after": ["A"]}], "human")
        self.assertEqual(self.board.get(c)["after"], a)

    def test_a_row_already_holding_several_is_read(self):
        a, b, c = self.card(title="a"), self.card(title="b"), self.card(title="c")
        self.board.conn.execute("UPDATE cards SET after = ? WHERE id = ?", (f"{a},{b}", c))
        self.assertEqual(self.board.get(c)["derived"]["waiting_for"], [a, b])

    def test_the_switch_is_off_by_default_and_on_in_the_shipped_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            off = config_module.load(write_toml(Path(tmp)))
            self.assertNotIn("multi_after", off.switches)
            on = config_module.load(multi_after_toml(Path(tmp)))
            self.assertIn("multi_after", on.switches)
        shipped = (Path(__file__).resolve().parent.parent / "etc" / "shipyard.example.toml").read_text()
        # Turned on 2026-09-24, once the box and the Mac both ran the code that reads a list.
        self.assertIn("\nmulti_after = true", shipped)

    def test_a_place_is_read_from_a_card_with_no_rank(self):
        old = {"id": "c-1", "created_at": "2026-09-01T00:00:00Z"}
        self.assertEqual(tree.place(old), (True, 0.0, "2026-09-01T00:00:00Z", "c-1"))


class WhoMayOrderTheQueueTest(TreeCase):
    """Item 3: the queue and a tree's assignment are his, by hand or by voice."""

    def test_next_and_assign_refuse_a_house_and_a_plain_cli(self):
        parent, (a, b) = AssignTest.later_tree(self)
        for actor in ("house", "cli", "drain"):
            with self.assertRaisesRegex(Refused, "human or voice"):
                tree.to_front(self.board, a, actor)
            with self.assertRaisesRegex(Refused, "human or voice"):
                tree.assign(self.board, parent, actor)
        tree.to_front(self.board, a, "voice")
        tree.assign(self.board, parent, "voice")

    def test_next_refuses_a_done_or_archived_card(self):
        done = self.at_review()
        self.board.stage(done, "done", "human")
        with self.assertRaisesRegex(Refused, "done"):
            tree.to_front(self.board, done, "human")
        archived = self.card(title="old")
        self.board.set_fields(archived, {"options": {"archived": True}}, "human")
        with self.assertRaisesRegex(Refused, "archived"):
            tree.to_front(self.board, archived, "human")


class KbTreeActorsTest(KbCase):
    def test_a_house_cannot_run_next_or_assign(self):
        card = self.create()
        code, _, err = self.kb("next", card, env={"KEEL_CARD": card})
        self.assertNotEqual(code, 0)
        self.assertIn("human or voice", err)
        code, _, err = self.kb("assign", card, env={"KEEL_CARD": card})
        self.assertNotEqual(code, 0)
        self.assertIn("human or voice", err)


class AssignPinsThePreviewTest(TreeCase):
    """Item 4: the confirm assigns what the preview showed, or refuses."""

    def test_assign_refuses_when_the_set_changed_since_the_preview(self):
        parent, (a, b) = AssignTest.later_tree(self)
        preview = tree.assign(self.board, parent, "human", dry_run=True)["assigned"]
        self.card(title="late", parent=parent)
        with self.assertRaisesRegex(Refused, "changed since"):
            tree.assign(self.board, parent, "human", expected=preview)
        self.assertEqual(self.board.get(a)["stage"], "inbox")

    def test_assign_with_the_same_set_goes_ahead(self):
        parent, (a, b) = AssignTest.later_tree(self)
        preview = tree.assign(self.board, parent, "human", dry_run=True)["assigned"]
        tree.assign(self.board, parent, "human", expected=list(reversed(preview)))
        self.assertEqual(self.board.get(a)["stage"], "assigned")

    def test_the_outline_counts_what_assign_would_assign_in_a_nested_tree(self):
        top = self.card(title="top")
        mid = self.card(title="mid", parent=top)
        self.card(title="leaf1", parent=mid)
        self.card(title="leaf2", parent=mid)
        self.card(title="loose", parent=top)
        outline = self.board.get(top)["derived"]["tree"]
        self.assertEqual(outline["unassigned"], 3)
        self.assertEqual(len(tree.assign(self.board, top, "human", dry_run=True)["assigned"]), 3)

    def test_the_action_and_kb_carry_the_previewed_ids(self):
        argv = actions.ARGV_BUILDERS["assign"]({"id": "c-1", "ids": ["c-2", "c-3"]})
        self.assertEqual(argv, ["assign", "c-1", "--ids", "c-2,c-3"])

    def test_create_refuses_a_parent_in_another_space(self):
        parent = self.card(space="personal", title="P")
        with self.assertRaisesRegex(Refused, "space"):
            self.card(space="work", title="c", parent=parent)


class KbAssignIdsTest(KbCase):
    def test_kb_assign_ids_refuses_a_changed_set(self):
        parent = self.create()
        code, out, err = self.kb("create", "--space", "personal", "--title", "s", "--parent", parent)
        self.assertEqual(code, 0, err)
        code, _, err = self.kb("--actor", "voice", "assign", parent, "--ids", "c-999")
        self.assertNotEqual(code, 0)
        self.assertIn("changed since", err)
        code, out, err = self.kb("--actor", "voice", "assign", parent, "--ids", out)
        self.assertEqual(code, 0, err)
