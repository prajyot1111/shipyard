"""SH-11: the shipping sync, from his open pull requests to the cards they belong to.

The adapter's `ship mine` is a stand-in script here: it records the cards it was handed on
stdin and answers with the pull requests the test wrote, each already matched to cards (the
real matching, by branch and by story against the code host stand-in, is the work adapter's
own test, `packs/work/tests/test_shipping_sync.py`). What is held here is the engine's
half: a tie goes to the card that records the pull request, else the most recently updated,
with a note on the other; a card whose pull requests are all ready goes to shipping from
done or from review; a draft keeps it where it is; what it records; the dry run; and a
second run changes nothing. Every pull request is invented.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from keel import shipsync
from keel.board import SHIPPING_OPTION, Board
from tests.helpers import make_config


def pr(repo="api", number=4150, branch="feature/st-41001/tidy", cards=(), draft=False,
       updated="2026-09-24T10:00:00+00:00", worktree=None) -> dict:
    return {"repo": repo, "pr": number, "branch": branch, "title": "Tidy", "draft": draft,
            "updated": updated, "url": f"https://example.invalid/{repo}/{number}",
            "worktree": worktree, "cards": list(cards), "matched_by": "story" if cards else None}


class SyncCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.host = "mac"
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        work = self.cfg.adapters_dir / "work"
        work.mkdir(parents=True)
        self.answer_file = self.dir / "mine.json"
        self.handed = self.dir / "handed.json"
        self.answer()
        (work / "ship").write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "mine" ]; then\n'
            f"  cat > {self.handed}\n"
            f"  cat {self.answer_file}\n"
            "  exit 0\n"
            "fi\n"
            "echo 'ship: only mine here' >&2; exit 1\n")
        (work / "ship").chmod(0o755)

    def answer(self, *prs):
        self.answer_file.write_text(json.dumps({"prs": list(prs)}))

    def card_at(self, stage: str, title="a card", repo="api", **options) -> str:
        card_id = self.board.create("work", title, repo=repo, actor="human", options=options)
        if stage == "inbox":
            return card_id
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        if stage == "building":
            return card_id
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        if stage == "done":
            self.board.approve(card_id, "outcome", "human", publish=lambda c: {"published": "nothing"})
        return card_id

    def sync(self, dry_run=False) -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            code = shipsync.run(self.cfg, self.board, dry_run=dry_run)
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def stage_of(self, card_id: str) -> str:
        return self.board.get(card_id)["stage"]

    def options_of(self, card_id: str) -> dict:
        return self.board.get(card_id)["options"]


class MoveTest(SyncCase):
    def test_a_done_card_with_a_ready_pull_request_ships_and_records_it(self):
        card_id = self.card_at("done")
        self.answer(pr(cards=[card_id], worktree="/wt/api/feature-st-41001-tidy"))
        said = self.sync()
        self.assertEqual(self.stage_of(card_id), "shipping")
        options = self.options_of(card_id)
        self.assertEqual(options["prs"], {"api": {"pr": 4150, "branch": "feature/st-41001/tidy"}})
        self.assertEqual((options["pr"], options["branch"], options["worktree"]),
                         (4150, "feature/st-41001/tidy", "/wt/api/feature-st-41001-tidy"))
        self.assertEqual(options[SHIPPING_OPTION]["round"], 0)
        self.assertIn(f"{card_id}  api #4150: record them, move done to shipping", said)

    def test_a_review_card_whose_pull_requests_were_published_outside_keel_ships(self):
        card_id = self.card_at("review", repo="api,web")
        self.answer(pr(cards=[card_id]), pr("web", 2178, "feature/st-41001/tidy-ui", cards=[card_id]))
        self.sync()
        self.assertEqual(self.stage_of(card_id), "shipping")
        event = [e for e in self.board.events(card_id) if e["kind"] == "stage"][-1]
        self.assertTrue(event["data"]["sync"])
        self.assertIn("nothing was published", event["text"])
        self.assertEqual(sorted(self.options_of(card_id)["prs"]), ["api", "web"])

    def test_a_draft_keeps_the_card_where_it_is(self):
        review = self.card_at("review", repo="api,web")
        done = self.card_at("done")
        self.answer(pr(cards=[review]), pr("web", 2193, "x/ui", cards=[review], draft=True),
                    pr(number=4139, branch="y", cards=[done], draft=True))
        said = self.sync()
        self.assertEqual((self.stage_of(review), self.stage_of(done)), ("review", "done"))
        self.assertIn("web #2193 is still a draft", said)
        self.assertIn("web", self.options_of(review)["prs"], "a draft is still recorded")

    def test_a_card_still_building_or_a_round_at_his_gate_stays(self):
        building = self.card_at("building")
        at_gate = self.card_at("review")
        self.board.set_fields(at_gate, {"options": {SHIPPING_OPTION: {"round": 1, "batch": []}}}, "drain")
        self.answer(pr(cards=[building]), pr(number=4151, branch="z", cards=[at_gate]))
        said = self.sync()
        self.assertEqual((self.stage_of(building), self.stage_of(at_gate)), ("building", "review"))
        self.assertIn("its house has not finished", said)
        self.assertIn("a review round is at the user's gate", said)

    def test_a_repo_the_card_did_not_name_is_added_after_its_primary(self):
        card_id = self.card_at("done")
        self.answer(pr(cards=[card_id]), pr("web", 2178, "feature/st-41001/tidy-ui", cards=[card_id],
                                            worktree="/wt/web/ui"))
        said = self.sync()
        card = self.board.get(card_id)
        self.assertEqual(card["repo"], "api,web")
        self.assertIn("repo becomes api,web", said)
        self.assertEqual(card["options"]["worktrees"], {"web": "/wt/web/ui"})

    def test_an_errand_and_a_pull_request_with_no_card_are_left_alone(self):
        errand = self.card_at("inbox", repo=None)
        self.answer(pr(cards=[errand]), pr(number=4102, branch="lonely"))
        said = self.sync()
        self.assertEqual(self.stage_of(errand), "inbox")
        self.assertIn("errand", said)
        self.assertIn("api #4102 (lonely)  no card matches it: left alone", said)

    def test_the_adapter_is_handed_the_space_s_cards(self):
        card_id = self.card_at("done", title="st-41001 tidy")
        self.answer()
        self.sync()
        handed = json.loads(self.handed.read_text())
        self.assertEqual([c["id"] for c in handed], [card_id])
        self.assertEqual(handed[0]["title"], "st-41001 tidy")


class TieTest(SyncCase):
    def test_a_pull_request_matching_two_cards_goes_to_the_newer_with_a_note_on_the_other(self):
        older = self.card_at("done", title="older")
        newer = self.card_at("done", title="newer")
        self.answer(pr(number=2186, repo="web", cards=[older, newer]))
        said = self.sync()
        self.assertEqual((self.stage_of(older), self.stage_of(newer)), ("done", "shipping"))
        note = self.board.events(older)[-1]
        self.assertEqual(note["kind"], "note")
        self.assertIn(newer, note["text"])
        self.assertIn("2186", note["text"])
        self.assertIn(f"{older}  web #2186", said)

    def test_a_second_run_changes_nothing_even_though_the_note_made_the_loser_newer(self):
        older = self.card_at("done", title="older")
        newer = self.card_at("done", title="newer")
        other = self.card_at("review", title="other")
        self.answer(pr(number=2186, repo="web", cards=[older, newer]), pr(cards=[other]))
        self.sync()
        counts = {c: len(self.board.events(c, last=0)) for c in (older, newer, other)}
        self.sync()
        self.assertEqual({c: len(self.board.events(c, last=0)) for c in (older, newer, other)}, counts)
        self.assertEqual(self.stage_of(newer), "shipping")


class DryRunTest(SyncCase):
    def test_a_dry_run_prints_every_decision_and_writes_nothing(self):
        done = self.card_at("done")
        review = self.card_at("review")
        self.answer(pr(cards=[done]), pr(number=4151, branch="b", cards=[review]),
                    pr(number=4102, branch="lonely"))
        before = {c: self.board.events(c, last=0) for c in (done, review)}
        said = self.sync(dry_run=True)
        self.assertEqual({c: self.board.events(c, last=0) for c in (done, review)}, before)
        self.assertIn(f"{done}  api #4150: would record them, would move done to shipping", said)
        self.assertIn(f"{review}  api #4151: would record them, would move review to shipping", said)
        self.assertIn("no card matches it", said)
        self.assertIn("dry run: nothing written", said)


if __name__ == "__main__":
    unittest.main()
