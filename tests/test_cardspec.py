"""The card defaults: one resolver every new card goes through (`keel/cardspec.py`).

c-434: a card with no model ran on the account's own default (Fable), because nothing
filled the field and the harness was handed no `--model`. c-303: whatever is assumed is
said back, and a correction of it is on the record. These tests hold both: every card
leaves `Board.create` with a model, every tracked field carries where its value came
from, the readback is built by code, and a `kb set` of an assumed field is an event.
"""

import json
import tempfile
import unittest
from pathlib import Path

from keel import cardspec
from keel.board import HIS_AT_CREATE, RESERVED_OPTIONS, Board, Refused
from tests.helpers import ROOT, BoardCase, make_config
from tests.test_cli import KbCase


def defaults(personal="opus", work="sonnet") -> cardspec.Defaults:
    return cardspec.Defaults({
        "personal": cardspec.SpaceDefaults(model=personal, confirm=("repo", "model")),
        "work": cardspec.SpaceDefaults(model=work, confirm=("repo", "autonomy", "design_doc",
                                                           "base", "tracker_mode"),
                                       sheet=[{"key": "base", "label": "Base branch",
                                               "stored": "options", "default": "develop"},
                                              {"key": "tracker_mode", "label": "Story mode",
                                               "stored": "options", "default": "create at task start"},
                                              {"key": "kind", "label": "Kind", "stored": "options",
                                               "default": "feature"},
                                              {"key": "design_doc", "label": "Design doc",
                                               "stored": "options",
                                               "default_if": "tracker_mode != none and kind != research"}]),
    })


class DefaultsCase(BoardCase):
    def setUp(self):
        super().setUp()
        self.board.defaults = defaults()


class ModelIsNeverLeftEmptyTest(DefaultsCase):
    """B1: a card leaves create with a model, from the space when nobody said one."""

    def test_a_card_with_no_model_gets_its_space_default(self):
        personal = self.board.get(self.card())
        work = self.board.get(self.card(space="work"))
        self.assertEqual((personal["model"], work["model"]), ("opus", "sonnet"))
        self.assertEqual(personal["options"]["provenance"]["model"], "space_default")

    def test_a_board_with_no_defaults_still_fills_keel_s_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = Board(Path(tmp) / "board.db")
            try:
                card = board.get(board.create("personal", "t"))
            finally:
                board.close()
        self.assertEqual(card["model"], cardspec.KEEL_MODEL)
        self.assertEqual(card["options"]["provenance"]["model"], "keel_default")

    def test_a_stated_model_wins_and_is_marked_stated(self):
        card = self.board.get(self.card(model="haiku"))
        self.assertEqual(card["model"], "haiku")
        self.assertEqual(card["options"]["provenance"]["model"], "stated")

    def test_an_unknown_model_is_refused_at_create(self):
        with self.assertRaisesRegex(Refused, "opsu"):
            self.card(model="opsu")

    def test_the_defaults_are_read_from_the_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            cfg.spaces["work"].model = "haiku"
            found = cardspec.defaults_from(cfg)
        self.assertEqual(found.for_space("work").model, "haiku")
        # A space that names no model leaves it to Keel's own default, and says so.
        self.assertIsNone(found.for_space("personal").model)
        self.assertIsNone(found.for_space("nowhere").model)


class SetModelTest(DefaultsCase):
    """B3: `kb set model=` takes a known name only, and never an empty one."""

    def test_a_typo_is_refused(self):
        card_id = self.card()
        with self.assertRaisesRegex(Refused, "not a model"):
            self.board.set_fields(card_id, {"model": "opsu"}, "human")

    def test_an_empty_model_is_refused_rather_than_reopening_the_hole(self):
        card_id = self.card()
        for empty in ("", None):
            with self.assertRaisesRegex(Refused, "model"):
                self.board.set_fields(card_id, {"model": empty}, "human")

    def test_the_known_names_and_their_long_context_forms_pass(self):
        card_id = self.card()
        for name in ("sonnet", "fable", "opus[1m]", "claude-opus-4-1"):
            self.assertEqual(self.board.set_fields(card_id, {"model": name}, "human")["model"], name)


class InheritTest(DefaultsCase):
    """B3: a follow-up (`--from`) takes model, repo, autonomy and topic from its source."""

    def source(self) -> str:
        return self.card(model="haiku", repo="keel", autonomy="attended", topic="boards")

    def test_from_inherits_the_four_fields(self):
        card = self.board.get(self.card(from_card=self.source()))
        self.assertEqual((card["model"], card["repo"], card["autonomy"], card["topic"]),
                         ("haiku", "keel", "attended", "boards"))
        self.assertEqual(card["options"]["provenance"],
                         {"model": "inherited", "repo": "inherited", "autonomy": "inherited",
                          "topic": "inherited"})

    def test_what_the_creator_says_wins_over_the_source(self):
        card = self.board.get(self.card(from_card=self.source(), model="opus", repo="other"))
        self.assertEqual((card["model"], card["repo"]), ("opus", "other"))
        self.assertEqual(card["options"]["provenance"]["model"], "stated")
        self.assertEqual(card["options"]["provenance"]["autonomy"], "inherited")

    def test_a_slice_filed_with_parent_inherits_like_a_split_child(self):
        parent = self.card(model="haiku", repo="keel")
        card = self.board.get(self.card(parent=parent))
        self.assertEqual((card["model"], card["repo"]), ("haiku", "keel"))
        self.assertEqual(card["options"]["provenance"]["model"], "inherited")

    def test_from_wins_over_parent_as_the_source(self):
        parent, source = self.card(model="haiku"), self.card(model="sonnet")
        self.assertEqual(self.board.get(self.card(parent=parent, from_card=source))["model"],
                         "sonnet")

    def test_a_split_child_records_that_it_inherited(self):
        parent = self.source()
        child = self.board.get(self.board.split(parent, [{"title": "a"}], "house")[0])
        self.assertEqual(child["model"], "haiku")
        self.assertEqual(child["options"]["provenance"]["repo"], "inherited")

    def test_a_split_of_a_card_with_no_model_gives_the_child_the_space_default(self):
        """An imported card can still carry a null model; its slices must not."""
        parent = self.board.insert_card({"space": "personal", "title": "old", "stage": "inbox",
                                         "autonomy": "autonomous"}, "import")
        child = self.board.get(self.board.split(parent, [{"title": "a"}], "house")[0])
        self.assertEqual(child["model"], "opus")
        self.assertEqual(child["options"]["provenance"]["model"], "space_default")


def sliced(*rows: dict) -> cardspec.Defaults:
    """A space whose sheet declares a tracker mode and a base, as the house's space did
    (r-62), with a reference row, a free-text row and a row its pack marks per card. `rows`
    replace the rows of the same key, or are added."""
    sheet = [{"key": "repo", "label": "Repo", "stored": "card", "default": []},
             {"key": "kind", "label": "Kind", "stored": "options", "default": "feature"},
             {"key": "tracker_ref", "label": "Story", "type": "story", "stored": "options",
              "when": "tracker_mode == link an existing story"},
             {"key": "tracker_mode", "label": "Story mode", "type": "select", "stored": "options",
              "default": "none"},
             {"key": "base", "label": "Base branch", "type": "select", "stored": "options",
              "default": "develop"},
             {"key": "design_doc", "label": "Design doc", "type": "checkbox", "stored": "options",
              "default_if": "tracker_mode != none"},
             {"key": "include_tests", "label": "Unit tests", "type": "checkbox",
              "stored": "options", "default": True},
             {"key": "estimate", "label": "Estimate", "type": "text", "stored": "options",
              "inherit": False},
             {"key": "guidance", "label": "Guidance", "type": "textarea", "stored": "options"}]
    named = {row["key"] for row in rows}
    sheet = [row for row in sheet if row["key"] not in named] + list(rows)
    return cardspec.Defaults({"work": cardspec.SpaceDefaults(
        model="sonnet", confirm=("repo", "design_doc", "base", "tracker_mode"), sheet=sheet)})


STATED = {"tracker_mode": "create at task start", "base": "staging", "design_doc": True,
          "include_tests": False}


class SliceOptionsTest(BoardCase):
    """c-760: a slice starts as its parent would. It takes the parent's stated values for
    the option keys the space's sheet declares, and nothing of the parent's own."""

    def setUp(self):
        super().setUp()
        self.board.defaults = sliced()

    def parent(self, **options) -> str:
        return self.card(space="work", repo="api", options=dict(STATED, **options))

    def slices(self, parent: str, *pieces: dict) -> list[dict]:
        made = self.board.split(parent, list(pieces) or [{"title": "one"}, {"title": "two"}], "house")
        return [self.board.get(one) for one in made]

    def test_a_slice_starts_with_the_mode_and_base_its_parent_stated(self):
        """As the house hit it: the slices came up with the space default, so the first one
        started with no story."""
        for child in self.slices(self.parent()):
            self.assertEqual({key: child["options"].get(key) for key in STATED}, STATED)
            tags = child["options"]["provenance"]
            self.assertEqual((tags["tracker_mode"], tags["base"], tags["design_doc"]),
                             ("inherited", "inherited", "inherited"))

    def test_the_readback_says_what_the_slice_inherited(self):
        parent = self.parent()
        text = cardspec.readback(self.slices(parent)[0], self.board.defaults)
        self.assertIn("base branch staging, story mode create at task start", text)
        # r2.F2: a row off the confirm list is named too, by its label (include_tests here)
        self.assertIn(f"repo, model, design doc, base branch, story mode and unit tests "
                      f"inherited from {parent}", text)

    def test_every_inherited_row_is_tagged_and_a_later_change_of_one_is_a_correction(self):
        """r2.F2: an inherited row off the confirm list can be told from a stated one, and
        `kb set` of it is recorded as a correction, as for any value that was not stated."""
        child = self.slices(self.parent())[0]
        self.assertEqual(child["options"]["provenance"]["include_tests"], "inherited")
        self.board.set_fields(child["id"], {"options": {"include_tests": True}}, "human")
        found = [e["data"] for e in self.board.events(child["id"]) if e["kind"] == "correct"]
        self.assertEqual(found, [{"field": "include_tests", "from": False, "to": True,
                                  "provenance": "inherited"}])

    def test_a_slice_takes_its_parent_s_kind_unless_that_is_research_or_review(self):
        """r2.F1: a bug card's slices are bug slices (the branch type), and nothing at the
        split could have said so. A research or review parent's slices are ordinary cards."""
        for kind, taken in (("bug", "bug"), ("research", None), ("Review", None)):
            child = self.slices(self.parent(kind=kind), {"title": "one"})[0]
            self.assertEqual(child["options"].get("kind"), taken, kind)

    def test_a_split_that_is_refused_keeps_nothing_of_an_earlier_held_slice(self):
        """r2.F4: the first slice was filed and blocked before the second refused the split."""
        parent = self.linked()
        before = self.board.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        with self.assertRaisesRegex(Refused, "waits for unknown sibling"):
            self.board.split(parent, [{"title": "one"}, {"title": "two", "after": "nobody"}], "house")
        self.assertEqual(self.board.get(parent).get("children") or [], [])
        self.assertEqual(self.board.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 1)
        self.assertEqual(self.board.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], before)

    def test_what_a_slice_states_wins_over_its_parent(self):
        child = self.slices(self.parent(), {"title": "one", "options": {"base": "hotfix"}})[0]
        self.assertEqual((child["options"]["base"], child["options"]["provenance"]["base"]),
                         ("hotfix", "stated"))
        self.assertEqual(child["options"]["tracker_mode"], "create at task start")

    def test_a_row_whose_when_fails_on_the_slice_stays_behind(self):
        """r1.F11: the row's own `when` is asked on the slice, through a chain of rows."""
        self.board.defaults = sliced(
            {"key": "rich_story", "label": "Rich story", "type": "checkbox", "stored": "options",
             "when": "tracker_mode != none"},
            {"key": "link_doc", "label": "Link doc", "type": "checkbox", "stored": "options",
             "when": "rich_story == true"})
        parent = self.parent(rich_story=True, link_doc=True)
        kept, dropped = self.slices(parent, {"title": "one"},
                                    {"title": "two", "options": {"tracker_mode": "none"}})
        self.assertEqual((kept["options"].get("rich_story"), kept["options"].get("link_doc")), (True, True))
        self.assertEqual(sorted({"rich_story", "link_doc"} & set(dropped["options"])), [])
        self.assertEqual(dropped["options"]["base"], "staging")

    def test_an_empty_value_a_slice_states_wins_too(self):
        """r1.F11: "no base" is a statement, not a gap for the parent's to fill."""
        child = self.slices(self.parent(), {"title": "one", "options": {"base": ""}})[0]
        self.assertEqual(child["options"]["base"], "")

    def test_a_value_the_parent_never_stated_stays_the_sheet_s(self):
        parent = self.card(space="work", repo="api", options={"base": "staging"})
        child = self.slices(parent)[0]
        self.assertNotIn("tracker_mode", child["options"])
        self.assertNotIn("include_tests", child["options"])
        self.assertEqual(child["options"]["provenance"]["tracker_mode"], "space_default")

    def test_nothing_of_the_parent_s_own_travels(self):
        """Its story, branch and worktrees, its free text, its kind, and a row the pack
        marks as per card (`inherit: false`)."""
        own = {"tracker_ref": "T-9", "branch": "feature/t-9/x", "worktree": "/w/x",
               "worktrees": ["/w/x"], "pr": 4, "app_link": "http://x", "peak_mb": 900,
               "guidance": "backend only", "kind": "research", "estimate": "3 days",
               "not_on_the_sheet": "x"}
        child = self.slices(self.parent(**own))[0]
        self.assertEqual(sorted(set(own) & set(child["options"])), [])

    def test_no_option_the_board_keeps_for_the_owner_or_itself_travels(self):
        """r1.F6, r1.F12: a sheet that declares every held key as a plain row, and a parent
        that holds a value for each. The list is the board's own, whoever runs the split:
        what no creator could state at create (r2.F1, so `kind` is not on it)."""
        held = sorted({*cardspec.OWN, *HIS_AT_CREATE, "worker", *RESERVED_OPTIONS} - {"provenance"})
        self.assertNotIn("kind", held)
        self.assertIn("ship_auto_checks", held)
        self.board.defaults = sliced(*({"key": key, "label": key, "stored": "options"} for key in held))
        parent = self.parent()
        options = dict(self.board.get(parent)["options"], **{key: "x" for key in held})
        self.board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(options), parent))
        for actor in ("house", "human"):
            child = self.board.get(self.board.split(parent, [{"title": actor}], actor)[0])
            self.assertEqual(sorted(set(held) & set(child["options"])), [], actor)
            self.assertEqual(child["options"]["base"], "staging")

    def linked(self) -> str:
        return self.parent(tracker_mode="link an existing story", tracker_ref="T-9")

    def held_for(self, child: dict, parent: str) -> str:
        return (f"story was {parent}'s own and was not inherited, and this card's inherited "
                f"tracker_mode=link an existing story shows that row. Give this card its own "
                f"(`kb set {child['id']} options.tracker_ref=<value>`) or state a different "
                f"tracker_mode (`kb set {child['id']} options.tracker_mode=<value>`), then unblock it")

    def test_only_the_parent_s_own_row_picked_by_an_inherited_value_holds_a_slice(self):
        """D1: a `when` is the form's show-this-field rule, not a requirement. A row a pack
        marks `inherit: false` never holds a slice, a row the board holds back for the owner
        (`ship_auto_checks`) never does, even where the `when` picks it for an inherited
        value, and the parent's own row does not when its `when` only rules a value out."""
        picked = "tracker_mode == create at task start"
        self.board.defaults = sliced(
            {"key": "estimate", "label": "Estimate", "type": "text", "stored": "options",
             "inherit": False, "when": picked},
            {"key": "ship_auto_checks", "label": "Fix checks", "type": "checkbox", "stored": "options",
             "when": picked},
            {"key": "tracker_ref", "label": "Story", "type": "story", "stored": "options",
             "when": "tracker_mode != none"})
        self.assertIn("ship_auto_checks", HIS_AT_CREATE)
        parent = self.parent(estimate="3 days", tracker_ref="T-9")
        self.put(parent, ship_auto_checks=True)
        child = self.slices(parent)[0]
        self.assertEqual(child["options"]["tracker_mode"], "create at task start")
        self.assertEqual(sorted({"estimate", "ship_auto_checks", "tracker_ref"} & set(child["options"])), [])
        self.assertIsNone(child["blocked_reason"])

    def test_a_compound_when_never_raises_and_holds_only_as_the_rule_says(self):
        """r1.D4: several `==` joined by `and`, a part with `!=`, and an `or` (which the
        sheet's language does not have, so the clause is simply false). The parent's own row
        holds when an `==` part names a value the slice inherited, whatever the pack marks it."""
        link = "tracker_mode == link an existing story"
        cases = ((f"{link} and kind == feature", {}, True),
                 (f"{link} and base != develop", {}, True),
                 ("tracker_mode != none and base == staging", {}, True),
                 (link, {"inherit": False}, True),
                 ("tracker_mode != none and base != develop", {}, False),
                 (f"{link} and base == develop", {}, False),
                 (f"{link} or tracker_mode == none", {}, False))
        for when, more, held in cases:
            self.board.defaults = sliced({"key": "tracker_ref", "label": "Story", "type": "story",
                                          "stored": "options", "when": when, **more})
            child = self.slices(self.linked())[0]
            with self.subTest(when=when, more=more):
                self.assertEqual(child["blocked_reason"] is not None, held)

    def test_a_slice_of_a_card_linked_to_one_story_is_held_until_it_has_its_own(self):
        """r1.F7: the mode travels and the reference does not, so the split goes through and
        each such slice is blocked with the two ways on. A note would hold nothing."""
        parent = self.linked()
        for child in self.slices(parent):
            self.assertEqual(child["options"]["tracker_mode"], "link an existing story")
            self.assertNotIn("tracker_ref", child["options"])
            self.assertEqual(child["blocked_reason"], self.held_for(child, parent))

    def test_a_slice_filed_with_parent_is_held_the_same_way(self):
        parent = self.linked()
        child = self.board.get(self.card(space="work", parent=parent))
        self.assertEqual(child["blocked_reason"], self.held_for(child, parent))

    def test_a_slice_that_states_its_mode_or_its_reference_is_not_held(self):
        parent = self.linked()
        for own in ({"tracker_mode": "none"}, {"tracker_ref": "T-10"},
                    {"tracker_mode": "link an existing story"}):
            child = self.slices(parent, {"title": "one", "options": own})[0]
            self.assertIsNone(child["blocked_reason"], own)
            parent = self.linked()

    def test_a_when_the_board_cannot_read_refuses_and_names_its_row(self):
        """r1.F4, r1.F5: on a row that travels and on one that stays behind, a refusal that
        names the row and the space, never a traceback and never a silent skip."""
        bad = {"base": {"key": "base", "label": "Base branch", "stored": "options",
                        "default": "develop", "when": "repo is api"},
               "tracker_ref": {"key": "tracker_ref", "label": "Story", "type": "story",
                               "stored": "options", "when": "tracker_mode equals link"}}
        for key, row in bad.items():
            self.board.defaults = sliced(row)
            parent = self.parent(tracker_ref="T-9")
            with self.subTest(key), self.assertRaisesRegex(
                    Refused, f"the work sheet's row {key} has a `when` the board cannot read"):
                self.board.split(parent, [{"title": "one"}], "house")

    def test_a_slice_filed_with_parent_inherits_them_too(self):
        child = self.board.get(self.card(space="work", parent=self.parent()))
        self.assertEqual((child["options"]["base"], child["options"]["provenance"]["base"]),
                         ("staging", "inherited"))

    def test_a_follow_up_keeps_the_sheet_s_defaults(self):
        """`--from` is a different relation: new work that came out of a card."""
        card = self.board.get(self.card(space="work", from_card=self.parent()))
        self.assertNotIn("base", card["options"])
        self.assertEqual(card["options"]["provenance"]["base"], "space_default")

    def notes(self, card_id: str) -> list[str]:
        return [event["text"] for event in self.board.events(card_id) if event["kind"] == "note"]

    def put(self, card_id: str, **options) -> None:
        """Options no creator may state (the owner's, or a value create refuses), as stored."""
        merged = dict(self.board.get(card_id)["options"], **options)
        self.board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(merged), card_id))

    def test_an_inherited_base_yields_to_the_slice_s_stack(self):
        """A stacked card merges into the base of the card it is stacked on, and the slice
        and the split both say the parent's base was not taken (r1.F8)."""
        self.board.stacks = frozenset({"work"})
        parent = self.parent()
        made = self.board.split(parent, [
            {"title": "one", "options": {"base": "hotfix"}},
            {"title": "two", "after": "one", "options": {"stack": "stacked"}}], "human")
        stacked = self.board.get(made[1])["options"]
        self.assertEqual((stacked["stack"], stacked.get("base"), stacked["provenance"]["base"]),
                         ("stacked", None, "space_default"))
        said = (f"base staging was {parent}'s and was not taken: this card is stacked on {made[0]}, "
                f"which merges into hotfix")
        self.assertEqual(self.notes(made[1]), [said])
        self.assertIn(f"'two': {said}", self.notes(parent)[-1])

    def test_a_slice_filed_with_parent_yields_its_base_to_its_stack_too(self):
        """r1.F1: `kb create --parent --after` with stack=stacked, as the split does it."""
        self.board.stacks = frozenset({"work"})
        parent = self.parent()
        first = self.card(space="work", parent=parent, options={"base": "hotfix"})
        second = self.board.get(self.card(space="work", parent=parent, after=first,
                                          options={"stack": "stacked"}, actor="human"))
        self.assertEqual((second["options"]["stack"], second["options"].get("base")), ("stacked", None))
        self.assertEqual(len(self.notes(second["id"])), 1)

    def test_a_stated_stack_is_checked_on_the_repo_the_card_resolved_to(self):
        """D2: a card that is no slice too. One that takes its repo from `--from` and is
        stacked on a card in another repo is refused at create, as `kb set` refuses it."""
        self.board.stacks = frozenset({"work"})
        on = self.card(space="work", repo="api")
        source = self.card(space="work", repo="web")
        with self.assertRaisesRegex(Refused, f"{on} works in api, not in web"):
            self.card(space="work", from_card=source, after=on, options={"stack": "stacked"},
                      actor="human")

    def test_a_slice_left_without_its_stack_keeps_the_base_it_inherited(self):
        """r1.F3: an approved answer that cannot stand (a space that does not stack, a
        research sibling) leaves the slice unstacked, on its parent's base."""
        for stacks, kind in ((frozenset(), "feature"), (frozenset({"work"}), "research")):
            self.board.stacks = stacks
            parent = self.parent()
            self.put(parent, split_stack={"two": {"choice": "stacked", "on": "one"}})
            made = self.board.split(parent, [
                {"title": "one", "options": {"base": "hotfix", "kind": kind}},
                {"title": "two", "after": "one"}], "house")
            second = self.board.get(made[1])["options"]
            self.assertEqual((second.get("stack"), second.get("base")), (None, "staging"), kind)
            self.assertEqual(self.notes(made[1]), [], kind)

    def test_an_inherited_base_yields_on_a_repo_that_takes_none(self):
        """A card on a repo that lands on an integration branch names no base (c-732), and
        the slice says the parent's was not taken (r1.F8)."""
        self.board.integrated = frozenset({("work", "web")})
        parent = self.parent()
        child = self.board.get(self.card(space="work", repo="web", parent=parent))
        self.assertNotIn("base", child["options"])
        self.assertEqual(child["options"]["provenance"]["base"], "space_default")
        self.assertEqual(self.notes(child["id"]), [
            f"base staging was {parent}'s and was not taken: web lands on its integration branch, "
            f"so a card on it names no base of its own"])

    def test_an_inherited_base_that_is_no_branch_name_still_refuses(self):
        """r1.F8: only the rule about where a repo lands gives a base up."""
        parent = self.parent()
        self.put(parent, base="not a branch")
        with self.assertRaisesRegex(Refused, "options.base: 'not a branch' is not a branch name"):
            self.board.split(parent, [{"title": "one"}], "house")

    def test_an_inherited_browser_yields_on_a_repo_that_cannot_run_the_app(self):
        """r1.F10: an inherited value a create-time rule refuses does not travel, by one
        list of rules asked at create and at the split alike."""
        self.board.defaults = sliced({"key": "browser", "label": "Browser", "type": "checkbox",
                                      "stored": "options", "default": False})
        parent = self.parent(browser=True)
        self.board.run_rule = lambda space, key: key != "web"
        why = "web's CLAUDE.md does not say how to run the app yet, so a card on it cannot take the browser"
        child = self.board.get(self.card(space="work", repo="web", parent=parent))
        self.assertNotIn("browser", child["options"])
        self.assertEqual(self.notes(child["id"]), [f"browser on was {parent}'s and was not taken: {why}"])
        self.board.run_rule = lambda space, key: False
        sliced_off = self.slices(parent, {"title": "one"})[0]
        self.assertNotIn("browser", sliced_off["options"])
        self.assertEqual(len(self.notes(sliced_off["id"])), 1)


class ProvenanceTest(DefaultsCase):
    """B6: stated, assumed, inherited, space, keel, recorded per field in the options."""

    def test_every_tracked_field_has_a_provenance(self):
        card = self.board.get(self.card(repo="keel", assumed={"repo"}))
        self.assertEqual(card["options"]["provenance"],
                         {"repo": "assumed", "model": "space_default", "autonomy": "keel_default",
                          "topic": "keel_default"})

    def test_a_stated_option_on_the_confirm_list_is_stated_and_a_missing_one_is_the_space_s(self):
        card = self.board.get(self.card(space="work", repo="api", options={"base": "master"}))
        tags = card["options"]["provenance"]
        self.assertEqual((tags["base"], tags["tracker_mode"], tags["design_doc"]),
                         ("stated", "space_default", "space_default"))
        # A default is recorded as a provenance, never written into the options.
        self.assertNotIn("tracker_mode", card["options"])

    def test_assumed_must_name_a_field_that_was_given(self):
        with self.assertRaisesRegex(Refused, "assumed"):
            self.card(assumed={"repo"})


class ReadbackTest(DefaultsCase):
    """B6: the one-line readback is code's, so every creator says the same thing."""

    def test_the_brief_s_own_example(self):
        card = self.board.get(self.card(repo="keel", model="opus", topic="boards",
                                        assumed={"repo", "topic"}))
        self.assertEqual(cardspec.readback(card, self.board.defaults),
                         f"Filed {card['id']} in keel, opus, topic boards (repo and topic assumed)")

    def test_an_errand_on_defaults_says_so(self):
        card = self.board.get(self.card())
        self.assertEqual(cardspec.readback(card, self.board.defaults),
                         f"Filed {card['id']} in personal as an errand, opus "
                         f"(model the space default; repo Shipyard's default)")

    def test_a_work_card_names_every_field_that_may_not_pass_silently(self):
        card = self.board.get(self.card(space="work", repo="api", model="opus"))
        text = cardspec.readback(card, self.board.defaults)
        self.assertEqual(text, f"Filed {card['id']} in api, opus, autonomous, design doc on, "
                               f"base branch develop, story mode create at task start "
                               f"(design doc, base branch and story mode the space default; "
                               f"autonomy Shipyard's default)")

    def test_an_inherited_field_names_its_source(self):
        source = self.card(model="haiku", repo="keel")
        card = self.board.get(self.card(from_card=source))
        self.assertIn(f"repo and model inherited from {source}",
                      cardspec.readback(card, self.board.defaults))

    def test_a_card_with_no_provenance_reads_back_without_a_parenthesis(self):
        card_id = self.board.insert_card({"space": "personal", "title": "old", "stage": "inbox",
                                          "autonomy": "autonomous", "model": "opus"}, "import")
        self.assertEqual(cardspec.readback(self.board.get(card_id), self.board.defaults),
                         f"Filed {card_id} in personal as an errand, opus")


class CorrectionTest(DefaultsCase):
    """B6: a later `kb set` of an assumed field is a `correct` event, and the field is
    then his: nothing is kept anywhere but the card and its events."""

    def test_changing_an_assumed_field_is_recorded_as_a_correction(self):
        card_id = self.card(repo="keel", assumed={"repo"})
        card = self.board.set_fields(card_id, {"repo": "other"}, "human")
        corrections = [e for e in self.board.events(card_id) if e["kind"] == "correct"]
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["data"],
                         {"field": "repo", "from": "keel", "to": "other", "provenance": "assumed"})
        self.assertEqual(corrections[0]["actor"], "human")
        self.assertEqual(card["options"]["provenance"]["repo"], "stated")

    def test_a_defaulted_option_corrected_through_options_is_recorded_too(self):
        card_id = self.card(space="work", repo="api")
        self.board.set_fields(card_id, {"options": {"base": "master"}}, "human")
        found = [e["data"] for e in self.board.events(card_id) if e["kind"] == "correct"]
        self.assertEqual(found, [{"field": "base", "from": "develop", "to": "master",
                                  "provenance": "space_default"}])

    def test_a_stated_field_changed_is_an_ordinary_set(self):
        card_id = self.card(repo="keel")
        self.board.set_fields(card_id, {"repo": "other"}, "human")
        self.assertFalse([e for e in self.board.events(card_id) if e["kind"] == "correct"])

    def test_setting_the_same_value_is_not_a_correction(self):
        card_id = self.card(repo="keel", assumed={"repo"})
        self.board.set_fields(card_id, {"repo": "keel"}, "human")
        self.assertFalse([e for e in self.board.events(card_id) if e["kind"] == "correct"])


    def test_a_set_that_changes_nothing_records_neither_a_set_nor_a_correct(self):
        """The no-op check (c-440) runs before the corrections: re-stating an assumed field
        with the value it already holds is no event at all, and its provenance stays
        `assumed`. (A space default is not stored on the card, so writing one out IS a
        change and records a `set`, though still no `correct`.)"""
        card_id = self.card(space="work", repo="api", assumed={"repo"})
        before = self.board.get(card_id)
        count = len(self.board.events(card_id))
        card = self.board.set_fields(card_id, {"repo": "api"}, "human")
        self.assertEqual(len(self.board.events(card_id)), count)
        self.assertEqual(card["updated_at"], before["updated_at"])
        self.assertEqual(card["options"]["provenance"], before["options"]["provenance"])
        self.assertEqual(card["options"]["provenance"]["repo"], "assumed")


class SetAssumedTest(DefaultsCase):
    """D-3: a `kb set` may say the value is a guess (`--assumed repo`), which is what the
    capture's refine does when his words did not settle the repo. The field is tagged
    `assumed`, not `stated`, and it is not recorded as his correction, so a later change
    by him still is one."""

    def test_an_assumed_set_is_tagged_assumed_and_is_no_correction(self):
        card_id = self.card()
        card = self.board.set_fields(card_id, {"repo": "keel"}, "voice", assumed={"repo"})
        self.assertEqual(card["repo"], "keel")
        self.assertEqual(card["options"]["provenance"]["repo"], "assumed")
        self.assertFalse([e for e in self.board.events(card_id) if e["kind"] == "correct"])

    def test_his_later_change_of_that_guess_is_a_correction(self):
        card_id = self.card()
        self.board.set_fields(card_id, {"repo": "keel"}, "voice", assumed={"repo"})
        card = self.board.set_fields(card_id, {"repo": "other"}, "human")
        found = [e["data"] for e in self.board.events(card_id) if e["kind"] == "correct"]
        self.assertEqual(found, [{"field": "repo", "from": "keel", "to": "other",
                                  "provenance": "assumed"}])
        self.assertEqual(card["options"]["provenance"]["repo"], "stated")

    def test_assumed_must_name_a_field_being_set(self):
        card_id = self.card()
        with self.assertRaisesRegex(Refused, "assumed"):
            self.board.set_fields(card_id, {"topic": "boards"}, "voice", assumed={"repo"})


class KbCreateTest(KbCase):
    """B6 and B3 through `kb`: `--assumed`, the readback on --json and on stderr."""

    def test_the_readback_rides_on_the_json_and_is_said_on_stderr(self):
        code, out, err = self.kb("--actor", "voice", "create", "--space", "personal",
                                 "--title", "t", "--repo", "keel", "--topic", "boards",
                                 "--assumed", "repo,topic", "--json")
        self.assertEqual(code, 0, err)
        card = json.loads(out)
        self.assertEqual(card["readback"],
                         f"Filed {card['id']} in keel, opus, topic boards (repo and topic assumed; "
                         f"model Shipyard's default)")
        self.assertIn(card["readback"], err)

    def test_text_mode_still_prints_only_the_id_on_stdout(self):
        code, out, err = self.kb("create", "--space", "personal", "--title", "t")
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"^c-\d+$")
        self.assertIn(f"Filed {out} in personal as an errand", err)

    def test_from_inherits_through_kb(self):
        source = self.create("--repo", "keel", "--model", "haiku", "--topic", "voice")
        card = self.kb_json("create", "--space", "personal", "--title", "f", "--from", source)
        self.assertEqual((card["repo"], card["model"], card["topic"]), ("keel", "haiku", "voice"))

    def test_kb_split_hands_each_slice_what_its_parent_stated(self):
        """c-760, end to end: a pack's own sheet on disk, `kb create`, then `kb split`."""
        sheet = (ROOT / "packs" / "sandbox" / "options.json").read_text()
        (self.dir / "adapters" / "work").mkdir(parents=True)
        (self.dir / "adapters" / "work" / "options.json").write_text(sheet)
        parent = self.kb_json("create", "--space", "work", "--title", "p", "--repo", "api",
                              "--option", "tracker_mode=none", "--option", "kind=bug")
        code, out, err = self.kb("split", parent["id"], "--slice", "one|first", "--slice", "two|second",
                                 "--json")
        self.assertEqual(code, 0, err)
        slices = json.loads(out)
        self.assertEqual([one["options"].get("tracker_mode") for one in slices], ["none", "none"])
        self.assertEqual([one["options"].get("kind") for one in slices], ["bug", "bug"])   # r2.F1
        # r1.F2: the split says each slice's readback, as create does, on stderr and in the json
        for one in slices:
            self.assertRegex(one["readback"], f"^Filed {one['id']} in api.* inherited from {parent['id']}")
            self.assertIn(one["readback"], err)

    def test_kb_create_says_a_slice_it_filed_blocked(self):
        """D3: `kb create --parent` under a card linked to one ticket, as `kb split` says it."""
        sheet = [{"key": "tracker_ref", "label": "Ticket", "stored": "options",
                  "when": "tracker_mode == link"},
                 {"key": "tracker_mode", "label": "Ticket mode", "stored": "options", "default": "none"}]
        (self.dir / "adapters" / "work").mkdir(parents=True)
        (self.dir / "adapters" / "work" / "options.json").write_text(json.dumps(sheet))
        parent = self.kb_json("create", "--space", "work", "--title", "p", "--repo", "api",
                              "--option", "tracker_mode=link", "--option", "tracker_ref=T-9")
        code, out, err = self.kb("create", "--space", "work", "--title", "s", "--parent", parent["id"])
        self.assertEqual(code, 0, err)
        self.assertIn(f"{out} is blocked: ticket was {parent['id']}'s own and was not inherited", err)
        # r2.F4: `kb split` under the same parent says each held slice's block, and the json has it
        code, out, err = self.kb("split", parent["id"], "--slice", "one|a", "--slice", "two|b", "--json")
        self.assertEqual(code, 0, err)
        for one in json.loads(out):
            self.assertIn(f"ticket was {parent['id']}'s own", one["blocked_reason"])
            self.assertIn(f"{one['id']} is blocked: {one['blocked_reason']}", err)

    def test_a_new_project_card_s_attended_is_assumed_not_stated(self):
        card = self.kb_json("create", "--space", "personal", "--title", "p",
                            "--new-project", "smoke")
        self.assertEqual(card["autonomy"], "attended")
        self.assertEqual(card["options"]["provenance"]["autonomy"], "assumed")

    def test_kb_set_takes_assumed(self):
        card_id = self.create()
        code, _, err = self.kb("--actor", "voice", "set", card_id, "repo=keel", "--assumed", "repo")
        self.assertEqual(code, 0, err)
        card = self.kb_json("show", card_id)
        self.assertEqual(card["options"]["provenance"]["repo"], "assumed")

    def test_kb_set_model_refuses_a_typo(self):
        card_id = self.create()
        code, _, err = self.kb("set", card_id, "model=opsu")
        self.assertEqual(code, 1)
        self.assertIn("opsu", err)


if __name__ == "__main__":
    unittest.main()


class SheetTest(unittest.TestCase):
    """B1: the deck's sheets never offer "" as a model. That empty option was labelled
    "(default)" and meant the ACCOUNT's default, which is how a composer card ran on Fable."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.adapters_dir.mkdir(parents=True, exist_ok=True)
        root = Path(__file__).resolve().parent.parent
        # the space's pack is the example one, which ships with the core (c-722)
        (self.cfg.adapters_dir / "work").symlink_to(root / "adapters" / "sandbox")

    def model_entry(self, name):
        from keel import deckstate
        return next(e for e in deckstate.options_for(self.cfg.spaces[name]) if e["key"] == "model")

    def test_both_sheets_offer_only_real_models_and_default_to_the_space_s(self):
        self.cfg.spaces["work"].model = "sonnet"
        for name, expected in (("personal", cardspec.KEEL_MODEL), ("work", "sonnet")):
            entry = self.model_entry(name)
            self.assertNotIn("", entry["options"])
            self.assertEqual(entry["default"], expected)
            self.assertIn(expected, entry["options"])

    def test_a_pack_that_lists_no_repos_of_its_own_offers_the_space_s(self):
        """c-689: a pack for whatever repos a person clones cannot know their names, so its
        repo row lists none and the sheet offers the space's; a pack that lists its own
        (the example pack's two) keeps them whatever the space holds."""
        from keel.config import Space
        root = Path(__file__).resolve().parent.parent
        repos = {"core": Path("/nowhere/core"), "site": Path("/nowhere/site")}

        def repo_row(pack):
            space = Space(name="code", config_dir=Path("/nowhere"), repos=repos, contract=None,
                          adapter=pack, adapter_dir=root / "packs" / pack)
            return next(e for e in cardspec.sheet(space) if e["key"] == "repo")

        self.assertEqual(repo_row("github")["options"], ["core", "site"])
        self.assertEqual(repo_row("sandbox")["options"], ["api", "web"])
