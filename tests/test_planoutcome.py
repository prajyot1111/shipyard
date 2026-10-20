"""C33 (c-602): an outcome that ships a change carries boards drawn at the BUILT head and a
numbered reading order, the page tags a board carried over from the plan, the brief asks for
it at Verify, and the backfill finds the outcomes already at his gate without it.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import boards, outcomeboards, planformat, plangate, planlint, planoutcome, planroute
from keel.board import Board
from tests.helpers import make_config, make_repo

APPROVED = "2026-09-20T10:00:00+00:00"
BEFORE, AFTER = "2026-09-19T10:00:00+00:00", "2026-09-21T10:00:00+00:00"

OUTCOME = """\
---
kind: outcome
card: c-9
title: t
---
# c-9 t

What it does.

## Where it stands

Built.

## What is next

Approve.

## Why this shape

One store.

{boards}
{order}
## Open questions

None.

## Evidence

`keel/planlint.py:1`

## Risk

low: small.
"""
ORDER = "### Read it in this order\n\n1. `keel/planlint.py:10` the lint\n2. `keel/planoutcome.py:5` the rule\n"


def outcome(refs=("b-001",), order=ORDER) -> dict:
    blocks = "\n".join(f"```board flow {i}\n{ref}\n```\n" for i, ref in enumerate(refs))
    return planformat.parse(OUTCOME.format(boards=blocks, order=order))


def resolver(pushed: dict):
    def board_of(ref):
        return None if ref in pushed else "no such board"
    board_of.pushed = lambda ref: pushed.get(ref)
    return board_of


def c33(doc, pushed, since=APPROVED, written=False) -> list[dict]:
    result = planlint.lint(doc, ships=True, board_of=resolver(pushed), since=since, written=written)
    return [f for f in result["findings"] if f["rule"] == "C33"]


class RuleTest(unittest.TestCase):
    def test_a_redrawn_board_and_a_reading_order_pass(self):
        self.assertEqual(c33(outcome(("b-001", "b-002")), {"b-001": AFTER, "b-002": AFTER}), [])

    def test_only_the_plans_boards_unchanged_is_refused_and_each_is_warned(self):
        found = c33(outcome(("b-001", "b-002")), {"b-001": BEFORE, "b-002": APPROVED})
        warns = [f for f in found if f["level"] == "warn"]
        self.assertEqual(len(warns), 2)
        self.assertIn(planoutcome.CARRIED, warns[0]["text"])
        self.assertEqual([f["level"] for f in found if "every board" in f["text"]], ["error"])

    def test_one_fresh_board_passes_and_the_carried_one_is_a_warning(self):
        found = c33(outcome(("b-001", "b-002")), {"b-001": BEFORE, "b-002": AFTER})
        self.assertEqual([(f["level"], f["block"]) for f in found], [("warn", "why.board1")])
        self.assertTrue(planlint.lint(outcome(("b-001", "b-002")), ships=True, since=APPROVED,
                                      board_of=resolver({"b-001": BEFORE, "b-002": AFTER}))["ok"])

    def test_no_board_and_no_reading_order_are_refused(self):
        found = c33(outcome((), order=""), {})
        self.assertEqual(len([f for f in found if f["level"] == "error"]), 2)
        self.assertTrue(any("embeds no board" in f["text"] for f in found))
        self.assertTrue(any("reading order" in f["text"] for f in found))

    def test_the_reading_order_is_numbered(self):
        bullets = ORDER.replace("1. ", "- ").replace("2. ", "- ")
        self.assertTrue(any("reading order" in f["text"]
                            for f in c33(outcome(order=bullets), {"b-001": AFTER})))

    def test_written_outcomes_are_warned_not_refused(self):
        found = c33(outcome((), order=""), {}, written=True)
        self.assertTrue(found and all(f["level"] == "warn" for f in found))

    def test_a_push_time_nobody_can_read_counts_as_fresh(self):
        self.assertEqual(c33(outcome(), {"b-001": None}), [])

    def test_no_approval_known_needs_only_a_board_and_the_order(self):
        self.assertEqual(c33(outcome(), {"b-001": BEFORE}, since=None), [])

    def test_only_an_outcome_that_ships_is_held(self):
        result = planlint.lint(outcome((), order=""), ships=False, board_of=resolver({}), since=APPROVED)
        self.assertFalse([f for f in result["findings"] if f["rule"] == "C33"])

    def test_nothing_to_land_is_exempt(self):
        doc = planformat.parse(OUTCOME.format(boards="", order="").replace("title: t\n", "title: t\nchange: none\n"))
        self.assertEqual(c33(doc, {}), [])

    def test_docs_only_needs_the_reading_order_and_no_board(self):
        docs = OUTCOME.replace("title: t\n", "title: t\nchange: docs\n")
        self.assertEqual(c33(planformat.parse(docs.format(boards="", order=ORDER)), {}), [])
        found = c33(planformat.parse(docs.format(boards="", order="")), {})
        self.assertEqual([(f["level"], "reading order" in f["text"]) for f in found], [("error", True)])


def commit(root: Path, name: str) -> None:
    (root / name).write_text("x = 1\n")
    subprocess.run(["git", "-C", str(root), "add", name], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@x",
                    "commit", "-q", "-m", name], check=True)


class ClaimTest(unittest.TestCase):
    """c-605: a house wrote `change: none` over a real code change and dodged the Code flow
    board. The claim is checked against the branch before it exempts anything."""

    def lint(self, change: str, facts, order="") -> list[dict]:
        doc = planformat.parse(OUTCOME.format(boards="", order=order)
                               .replace("title: t\n", f"title: t\nchange: {change}\n"))
        result = planlint.lint(doc, ships=True, board_of=resolver({}), since=APPROVED,
                               changed=lambda: facts)
        return [f for f in result["findings"] if f["rule"] == "C33"]

    def test_none_over_commits_is_held_to_c33_with_a_message(self):
        found = self.lint("none", {"commits": 2, "files": ["keel/drain.py"]})
        self.assertIn("claim did not match", found[0]["text"])
        self.assertIn("2 commit(s)", found[0]["text"])
        self.assertTrue(any("embeds no board" in f["text"] for f in found), found)
        self.assertTrue(all(f["level"] == "error" for f in found))

    def test_none_with_no_commit_is_exempt(self):
        self.assertEqual(self.lint("none", {"commits": 0, "files": []}), [])

    def test_a_claim_nothing_could_verify_is_not_trusted(self):
        """c-605 review: no worktree read here, or a repo whose base does not resolve,
        is C33 with the reason, never an exemption."""
        found = self.lint("none", None)
        self.assertIn("could not be verified", found[0]["text"])
        self.assertTrue(any("embeds no board" in f["text"] for f in found), found)
        found = self.lint("none", {"commits": 0, "files": [], "unverified": ["the base of b (x) does not resolve"]})
        self.assertIn("the base of b (x) does not resolve", found[0]["text"])

    def test_docs_over_a_code_file_is_held_to_c33(self):
        found = self.lint("docs", {"commits": 1, "files": ["docs/atlas/x.md", "keel/drain.py"]}, ORDER)
        self.assertIn("keel/drain.py", found[0]["text"])
        self.assertTrue(any("embeds no board" in f["text"] for f in found), found)

    def test_docs_over_docs_only_needs_the_reading_order(self):
        facts = {"commits": 1, "files": ["docs/atlas/x.md", "README.md", "sub/CHANGELOG.rst",
                                         "doc/guide.adoc", "docs/notes.txt"]}
        self.assertEqual(self.lint("docs", facts, ORDER), [])

    def test_only_documentation_counts_as_docs(self):
        for path in ("requirements.txt", "CMakeLists.txt", "etc/house-contract.md", "keel/notes.md",
                     "notes.txt", "docs/img/a.png", "docs/build.py"):
            self.assertFalse(planoutcome.is_doc(path), path)
        for path in ("README", "README.md", "a/CHANGELOG.md", "docs/a/b.md", "doc/x.rst", "docs/y.txt"):
            self.assertTrue(planoutcome.is_doc(path), path)

    def test_the_branch_is_read_in_every_repo_of_the_card_against_its_own_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, two = make_repo(Path(tmp) / "one"), make_repo(Path(tmp) / "two")
            subprocess.run(["git", "-C", str(two), "branch", "-q", "trunk"], check=True)
            card = {"id": "c-9", "repo": "one,two", "options": {"worktrees": {"two": str(two)}}}
            bases = {one.name: "main", two.name: "trunk"}
            base_for = lambda root: bases[Path(root).name]          # noqa: E731
            self.assertEqual(planoutcome.branch_change(card, one, base_for),
                             {"commits": 0, "files": [], "unverified": []})
            commit(two, "code.py")
            self.assertEqual(planoutcome.branch_change(card, one, base_for),
                             {"commits": 1, "files": ["code.py"], "unverified": []})
            bases[two.name] = "no-such-base"
            facts = planoutcome.branch_change(card, one, base_for)
            self.assertEqual(facts["unverified"], ["the base of two (no-such-base) does not resolve"])

    def test_no_worktree_here_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(planoutcome.branch_change({"id": "c-9", "repo": "x", "options": {}},
                                                        Path(tmp) / "absent", lambda root: "main"))

    def test_a_stale_base_is_fetched_once_before_it_counts_against_the_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = make_repo(Path(tmp) / "origin")
            subprocess.run(["git", "clone", "-q", str(origin), str(Path(tmp) / "house")], check=True)
            house = Path(tmp) / "house"
            commit(origin, "landed.py")                       # the base moved; not fetched yet
            # by URL, so origin/main stays where the clone left it: a stale tracking ref
            subprocess.run(["git", "-C", str(house), "fetch", "-q", str(origin), "main"], check=True)
            subprocess.run(["git", "-C", str(house), "merge", "-q", "--ff-only", "FETCH_HEAD"], check=True)
            self.assertEqual(subprocess.run(["git", "-C", str(house), "rev-list", "--count", "origin/main..HEAD"],
                                            capture_output=True, text=True).stdout.strip(), "1")
            card = {"id": "c-9", "repo": "house", "options": {}}
            self.assertEqual(planoutcome.branch_change(card, house, lambda root: "main")["commits"], 0)

    def test_each_repo_takes_its_pull_requests_base_then_the_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, two = make_repo(Path(tmp) / "c-9"), make_repo(Path(tmp) / "c-9-two")
            card = {"id": "c-9", "repo": "one,two", "options": {"base": "develop",
                                                                "prs": {"two": {"pr": 3, "base": "release"}}}}
            self.assertEqual(plangate.repo_key_of(card, one), "one")
            self.assertEqual(plangate.repo_key_of(card, two), "two")
            self.assertEqual(plangate.claim_base(None, card, two), "release")
            self.assertEqual(plangate.claim_base(None, card, one), "develop")
            card["options"] = {}
            self.assertEqual(plangate.claim_base(None, card, one), "main", "the main checkout's branch")

    def test_the_stage_lint_reads_the_house_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp) / "site")
            subprocess.run(["git", "-C", str(root), "switch", "-q", "-c", "work"], check=True)
            (root / "code.py").write_text("x = 1\n")
            subprocess.run(["git", "-C", str(root), "add", "code.py"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@x",
                            "commit", "-q", "-m", "code"], check=True)
            path = Path(tmp) / "context.md"
            path.write_text(OUTCOME.format(boards="", order=ORDER).replace("title: t\n", "title: t\nchange: none\n"))
            card = {"id": "c-9", "repo": "site", "stage": "building", "events": [],
                    "options": {"base": "main", "review_session": "s"}}
            with mock.patch.object(plangate.review_gate, "started_with_pipeline", return_value=True):
                result = plangate.lint_file(path, card, root=str(root), board_of=resolver({}))
        self.assertFalse(result["ok"])
        self.assertTrue(any("claim did not match" in f["text"] for f in result["findings"]))


class ApprovedAtTest(unittest.TestCase):
    def test_the_newest_plan_approval_else_the_move_to_building(self):
        events = [{"kind": "stage", "data": {"to": "building"}, "at": "2026-09-18T00:00:00+00:00"},
                  {"kind": "approve", "data": {"gate": "plan"}, "at": "2026-09-19T00:00:00+00:00"},
                  {"kind": "approve", "data": {"gate": "outcome"}, "at": "2026-09-22T00:00:00+00:00"},
                  {"kind": "approve", "data": {"gate": "plan"}, "at": APPROVED}]
        self.assertEqual(planoutcome.approved_at(events), APPROVED)
        self.assertEqual(planoutcome.approved_at(events[:1]), "2026-09-18T00:00:00+00:00")
        self.assertIsNone(planoutcome.approved_at([]))

    def test_a_gateless_card_counts_from_the_first_move_into_building(self):
        """Review 2: a card sent back from review moves into building again; its first round's
        boards were drawn at a built head, so they are not the plan's."""
        first, again = "2026-09-18T00:00:00+00:00", "2026-09-25T00:00:00+00:00"
        events = [{"kind": "stage", "data": {"to": "building"}, "at": first},
                  {"kind": "stage", "data": {"to": "review"}, "at": "2026-09-20T00:00:00+00:00"},
                  {"kind": "stage", "data": {"to": "building"}, "at": again}]
        self.assertEqual(planoutcome.approved_at(events), first)
        drawn = "2026-09-20T00:00:00+00:00"   # the first round's board, after the build began
        self.assertEqual(c33(outcome(), {"b-001": drawn}, since=planoutcome.approved_at(events)), [])

    def test_a_naive_and_an_aware_stamp_compare(self):
        self.assertTrue(planoutcome.carried("2026-09-19T10:00:00", APPROVED))
        self.assertFalse(planoutcome.carried(None, APPROVED))
        self.assertFalse(planoutcome.carried(BEFORE, None))

    def test_written_is_at_or_past_his_gate(self):
        self.assertTrue(planoutcome.written({"stage": "shipping"}))
        self.assertFalse(planoutcome.written({"stage": "building"}))


class Stores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))

    def push(self, card: str, title: str, when: str | None = None) -> str:
        board = boards.push(self.cfg, f'board "{title}"\nnode a box "A"', card=card, new=True)["board"]
        if when:
            record = boards.read_record(self.cfg, board)
            record["last_push"]["at"] = when
            boards.write_record(self.cfg, record)
        return board


class ResolverTest(Stores):
    def test_the_local_resolver_says_when_a_board_was_last_drawn(self):
        ref = self.push("c-1", "flow", BEFORE)
        board_of = plangate.board_resolver(self.cfg)
        self.assertIsNone(board_of(ref))
        self.assertEqual(board_of.pushed(ref), BEFORE)
        self.assertIsNone(board_of.pushed("b-404"))
        self.assertEqual(boards.show(self.cfg, ref)["pushed"], BEFORE)

class Cards(Stores):
    def setUp(self):
        super().setUp()
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)

    def shipped(self, stage="review", repo="site") -> str:
        """A personal NON-Keel repo card a house built (Keel's own are Bosun's)."""
        b = self.board
        cid = b.create("personal", "outcome boards", actor="human", repo=repo, autonomy="attended")
        b.stage(cid, "assigned", "human")
        b.record_event(cid, "approve", "human", data={"gate": "plan"}, at=APPROVED)
        b.set_session(cid, "sess-1", "drain")
        b.set_fields(cid, {"options": {"review_session": "sess-1"}}, "drain")
        b.stage(cid, "building", "drain")
        if stage != "building":
            plan = self.cfg.card_dir(cid) / "plan.md"
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text("# plan\n")
            b.stage(cid, "review", "house", plan_ref=str(plan), output_ref="https://example.test/pr/1")
        if stage == "shipping":      # only Approve outcome gets there; the stage is what counts here
            with b.conn:
                b.conn.execute("UPDATE cards SET stage = 'shipping' WHERE id = ?", (cid,))
        return cid

    def write(self, cid: str, refs, order=ORDER, plan_refs=()):
        card_dir = self.cfg.card_dir(cid)
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / "context.md").write_text(outcome_text(cid, refs, order))
        if plan_refs:
            plan = card_dir / "plan.md"
            plan.write_text("---\nkind: plan\ncard: " + cid + "\ntitle: t\n---\n# t\n\nS.\n\n## Proposal\n\n"
                            + "\n".join(f"```board p\n{r}\n```\n" for r in plan_refs))
            self.board.set_fields(cid, {"plan_ref": str(plan)}, "house")


def outcome_text(cid, refs, order):
    blocks = "\n".join(f"```board flow {i}\n{ref}\n```\n" for i, ref in enumerate(refs))
    return OUTCOME.format(boards=blocks, order=order).replace("c-9", cid)


class PageTest(Cards):
    def test_the_page_tags_a_carried_board_and_warns_at_his_gate(self):
        cid = self.shipped()
        old, new = self.push(cid, "plan flow", BEFORE), self.push(cid, "Code flow: x", AFTER)
        self.write(cid, (old, new))
        answer = planroute.payload(self.cfg, self.board, cid, "outcome")
        embeds = {b["ref"]: b for b in planformat.all_blocks(answer["doc"]["blocks"]) if b["type"] == "board"}
        self.assertEqual(embeds[old].get("carried"), planoutcome.CARRIED)
        self.assertNotIn("carried", embeds[new])
        c33 = [f for f in answer["lint"]["findings"] if f["rule"] == "C33"]
        self.assertEqual([f["level"] for f in c33], ["warn"])
        self.assertTrue(answer["lint"]["ok"])

    def test_kb_stage_review_refuses_an_outcome_of_the_plans_boards_only(self):
        cid = self.shipped("building")
        old = self.push(cid, "plan flow", BEFORE)
        self.write(cid, (old,))
        card = self.board.get(cid)
        result = plangate.lint_file(self.cfg.card_dir(cid) / "context.md", card,
                                    events=self.board.events(cid), board_of=plangate.board_resolver(self.cfg))
        self.assertFalse(result["ok"])
        self.assertIn("every board the outcome embeds is the plan's", json.dumps(result["findings"]))


class BackfillTest(Cards):
    def test_it_picks_the_outcomes_at_his_gate_that_break_the_rule(self):
        stale = self.shipped()
        old = self.push(stale, "plan flow", BEFORE)
        self.write(stale, (old,), plan_refs=(old,))
        fine = self.shipped("shipping")
        self.write(fine, (self.push(fine, "Code flow: y", AFTER),))
        building = self.shipped("building")
        self.write(building, (), order="")
        dropped = self.shipped()
        kept, lost = self.push(dropped, "Code flow: z", AFTER), self.push(dropped, "plan two", BEFORE)
        self.write(dropped, (kept,), plan_refs=(lost,))
        picks = outcomeboards.select(self.cfg, self.board)
        self.assertEqual([p["card"] for p in picks], [stale, dropped])
        self.assertIn("does not embed it", " ".join(picks[1]["reasons"]))
        self.assertEqual(picks[0]["plan_boards"], [old])

    def test_only_a_card_a_house_built_is_picked(self):
        """Coordinator review: c-563 and c-578 were archived personal Keel cards. Archived,
        done and Bosun's cards (a Keel card, a personal repo card in builder mode) have no
        house and no outcome page to redraw."""
        cards = {}
        for name, repo in (("house", "site"), ("archived", "site"), ("keel", "keel")):
            cards[name] = self.shipped(repo=repo)
            self.write(cards[name], (self.push(cards[name], "plan flow", BEFORE),))
        self.board.set_fields(cards["archived"], {"options": {"archived": True}}, "human")
        picks = [p["card"] for p in outcomeboards.select(self.cfg, self.board)]
        self.assertEqual(picks, [cards["house"]])
        self.assertFalse(outcomeboards.housed({"stage": "review", "space": "personal", "repo": "site",
                                               "derived": {"bosun": True}}))
        self.assertFalse(outcomeboards.housed({"stage": "done", "space": "work", "repo": "api"}))
        self.assertFalse(outcomeboards.housed({"stage": "review", "space": "personal", "repo": "site, keel"}))
        self.assertTrue(outcomeboards.housed({"stage": "shipping", "space": "work", "repo": "keel"}))


    def test_a_dry_run_relays_nothing_and_a_run_relays_one_resume_each(self):
        cid = self.shipped()
        self.write(cid, (self.push(cid, "plan flow", BEFORE),))
        sent = []

        def relay(cfg, card, host, what, prompt):
            sent.append((card["id"], host, what, prompt))
            return {"note": "relayed"}
        with mock.patch("sys.stdout"):
            outcomeboards.main([], cfg=self.cfg, board=self.board, relay=relay)
        self.assertEqual(sent, [])
        with mock.patch("sys.stdout"):
            outcomeboards.main(["--run", "--card", cid], cfg=self.cfg, board=self.board, relay=relay)
        self.assertEqual([(s[0], s[1], s[2]) for s in sent], [(cid, self.cfg.host, "resume")])
        self.assertIn("board-only turn", sent[0][3])


class BackfillOnceTest(Cards):
    """Review 2: a second `--run` must not queue the same prompt again while the house has
    not answered; the board records what was sent, and `--force` sends again."""

    def run_it(self, argv, relay):
        with mock.patch("sys.stdout"):
            outcomeboards.main(argv, cfg=self.cfg, board=self.board, relay=relay)

    def test_an_unanswered_backfill_is_not_sent_twice(self):
        cid = self.shipped()
        self.write(cid, (self.push(cid, "plan flow", BEFORE),))
        sent = []

        def relay(cfg, card, host, what, prompt):
            sent.append(card["id"])
            return {"note": "relayed"}
        self.run_it(["--run"], relay)
        self.assertIn(outcomeboards.SENT_OPTION, self.board.get(cid)["options"])
        self.run_it(["--run"], relay)
        self.assertEqual(sent, [cid], "the second run skips a card still answering")
        self.run_it(["--run", "--force"], relay)
        self.assertEqual(sent, [cid, cid])

    def test_a_turn_end_after_the_backfill_answers_it(self):
        card = {"options": {outcomeboards.SENT_OPTION: {"at": APPROVED}}}
        stop = {"kind": "hook", "data": {"hook": "Stop"}, "at": AFTER}
        self.assertTrue(outcomeboards.pending(card, []))
        self.assertTrue(outcomeboards.pending(card, [dict(stop, at=BEFORE)]))
        self.assertFalse(outcomeboards.pending(card, [stop]))
        self.assertFalse(outcomeboards.pending({"options": {}}, []))



if __name__ == "__main__":
    unittest.main()
