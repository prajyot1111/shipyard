"""c-532, the engine's half: a card that leaves building has its own containers torn down by
the drain on the machine that holds its house, once per building spell.

The work adapter is a stand-in: its `ship` records each call and answers `down` with the
JSON the test wrote, which is what `packs/work/teardown.py` prints. No container is
touched and no session is started.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import drain, teardown, views
from keel.board import Board
from tests.helpers import make_config

WORKTREE = "/work/cloud-worktrees/feature-st-1-tidy"


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class TeardownCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.host = "mac"
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        patch = mock.patch.dict(teardown.CHECKED, {}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        work = self.cfg.adapters_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        self.log, self.answer = self.dir / "ship.log", self.dir / "down.json"
        self.says({"down": ["compose project wt-c272", "container preview-api"], "failed": []})
        script(work / "ship", f'echo "ship $*" >> {self.log}\n'
                              f'[ "$2" = down ] && cat {self.answer}\n')

    def says(self, out: dict) -> None:
        self.answer.write_text(json.dumps(out))

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def built(self, host: str = "mac", worktree: str | None = WORKTREE) -> str:
        options = {"worktree": worktree} if worktree else {}
        card_id = self.board.create("work", "Tidy the loader", repo="api", actor="human",
                                    options=options)
        self.board.stage(card_id, "assigned", "human")
        self.board.claim(card_id, host, "drain")
        self.board.stage(card_id, "building", "drain")
        return card_id

    def to_review(self, card_id: str) -> None:
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="https://example.invalid/pr/1")

    def run_pass(self, rows=()) -> list[str]:
        return teardown.upkeep(self.cfg, self.board, {"work"}, list(rows))

    def notes(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]


class LeavingBuildingTest(TeardownCase):
    def test_a_card_at_review_is_torn_down_once_and_says_what_went(self):
        card_id = self.built()
        self.to_review(card_id)
        self.assertEqual(self.run_pass(), [card_id])
        self.assertEqual(self.calls(), [f"ship {card_id} down"])
        [note] = self.notes(card_id)
        self.assertIn("compose project wt-c272, container preview-api", note)
        self.assertIn("the worktree is kept", note)
        self.assertEqual(self.run_pass(), [])
        self.assertEqual(len(self.calls()), 1)

    def test_a_new_building_spell_is_torn_down_again_when_it_ends(self):
        card_id = self.built()
        self.to_review(card_id)
        self.run_pass()
        self.board.stage(card_id, "building", "human", note="send back")
        self.assertEqual(self.run_pass(), [], "still building: nothing is torn down")
        self.to_review(card_id)
        self.assertEqual(self.run_pass(), [card_id])
        self.assertEqual(len(self.calls()), 2)

    def test_a_building_card_is_left_alone_until_it_is_archived(self):
        card_id = self.built()
        self.assertEqual(self.run_pass(), [])
        self.board.set_fields(card_id, {"options": {"archived": True}}, "human")
        self.assertEqual(self.run_pass(), [card_id])

    def test_a_working_house_waits_for_a_later_pass(self):
        card_id = self.built()
        self.to_review(card_id)
        busy = {"name": card_id, "status": "busy", "kind": "background"}
        self.assertEqual(self.run_pass([busy]), [])
        self.assertEqual(self.run_pass([dict(busy, status="idle")]), [card_id])

    def test_a_house_without_a_worktree_is_not_this_drains(self):
        bare = self.built(worktree=None)
        self.to_review(bare)
        self.assertEqual(self.run_pass(), [])
        self.assertEqual(self.calls(), [])

    def test_nothing_up_writes_no_note_but_answers_the_spell(self):
        self.says({"down": [], "failed": []})
        card_id = self.built()
        self.to_review(card_id)
        self.assertEqual(self.run_pass(), [], "asked, but nothing went: not logged as torn down")
        self.assertEqual(self.calls(), [f"ship {card_id} down"])
        self.assertEqual(self.notes(card_id), [])
        into = [e["id"] for e in self.board.events(card_id)
                if e["kind"] == "stage" and (e["data"] or {}).get("to") == "building"]
        self.assertEqual(self.board.get(card_id)["options"][teardown.TEARDOWN_OPTION], into[-1])

    def test_a_failure_is_noted_once_and_not_retried_every_pass(self):
        self.says({"down": [], "failed": ["docker could not be asked: docker is not on PATH"]})
        card_id = self.built()
        self.to_review(card_id)
        self.run_pass()
        self.run_pass()
        [note] = self.notes(card_id)
        self.assertIn("docker is not on PATH", note)
        self.assertEqual(len(self.calls()), 1)

    def test_an_attended_cards_spell_starts_at_his_plan_approval(self):
        card_id = self.board.create("work", "Tidy the loader", repo="api", actor="human",
                                    autonomy="attended", options={"worktree": WORKTREE})
        self.board.stage(card_id, "assigned", "human")
        self.board.claim(card_id, "mac", "drain")
        self.board.stage(card_id, "planning", "drain", plan_ref="p.md")
        self.board.approve(card_id, "plan", "human")
        self.assertEqual(self.board.get(card_id)["stage"], "building")
        self.to_review(card_id)
        self.assertEqual(self.run_pass(), [card_id])
        [approved] = [e for e in self.board.events(card_id) if e["kind"] == "approve"]
        self.assertEqual(self.board.get(card_id)["options"][teardown.TEARDOWN_OPTION], approved["id"])

    def test_an_adapter_that_fails_is_noted_once(self):
        script(self.cfg.adapters_dir / "work" / "ship",
               f'echo "ship $*" >> {self.log}\necho "docker went away" >&2\nexit 1\n')
        card_id = self.built()
        self.to_review(card_id)
        self.assertEqual(self.run_pass(), [])
        self.assertEqual(self.run_pass(), [])
        [note] = self.notes(card_id)
        self.assertIn("the teardown could not finish", note)
        self.assertEqual(len(self.calls()), 1)

    def test_a_spent_budget_takes_no_more_cards_and_bounds_each_one(self):
        ids = [self.built() for _ in range(2)]
        for card_id in ids:
            self.to_review(card_id)
        now, timeouts, real = [0.0], [], teardown.tear_down

        def slow(cfg, board, card, started, timeout):
            timeouts.append(timeout)
            now[0] += teardown.BUDGET_SECONDS - teardown.MIN_SECONDS + 1   # the first card ate it
            return real(cfg, board, card, started, timeout)
        with mock.patch.object(teardown, "tear_down", side_effect=slow):
            done = teardown.upkeep(self.cfg, self.board, {"work"}, [], clock=lambda: now[0])
        self.assertEqual(done, ids[:1])
        self.assertEqual(timeouts, [min(teardown.DOWN_SECONDS, teardown.BUDGET_SECONDS)])
        self.assertLessEqual(teardown.DOWN_SECONDS, teardown.BUDGET_SECONDS,
                             "one card may never run past the pass's budget")

    def test_approved_to_shipping_and_merged_to_done_are_leaving_too(self):
        card_id = self.built()
        self.to_review(card_id)
        self.board.set_fields(card_id, {"options": {teardown.TEARDOWN_OPTION: -1}}, "drain")
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"shipping": True})
        self.assertEqual(self.board.get(card_id)["stage"], "shipping")
        self.assertEqual(self.run_pass(), [card_id])
        self.board.stage(card_id, "done", "drain", note="merged")
        self.assertEqual(self.run_pass(), [], "one building spell, torn down once (c-600: no rounds)")

    def test_a_held_card_waits(self):
        for option, actor, hold in ((views.DROPIN_HOLD_OPTION, "human", {"until": "2999-01-01T00:00:00+00:00"}),
                                    (views.VOICE_HOLD_OPTION, "voice", {"until": "2999-01-01T00:00:00+00:00"})):
            card_id = self.built()
            self.to_review(card_id)
            self.board.set_fields(card_id, {"options": {option: hold}}, actor)
            self.assertEqual(self.run_pass(), [], option)
            self.board.set_fields(card_id, {"options": {option: None}}, actor)
            self.assertEqual(self.run_pass(), [card_id], option)

    def test_a_worktree_another_building_card_shares_is_left_alone(self):
        finished, building = self.built(), self.built()
        self.to_review(finished)
        self.assertEqual(self.run_pass(), [], "the other card is still building in it")
        self.assertEqual(self.calls(), [])
        self.to_review(building)
        self.assertEqual(sorted(self.run_pass()), sorted([finished, building]))

    def test_output_that_is_not_json_is_a_failure_noted_once(self):
        self.answer.write_text("Traceback: something broke")
        card_id = self.built()
        self.to_review(card_id)
        self.assertEqual(self.run_pass(), [])
        self.assertEqual(self.run_pass(), [])
        [note] = self.notes(card_id)
        self.assertIn("the teardown could not finish", note)

    def test_at_most_four_a_pass(self):
        ids = [self.built() for _ in range(teardown.PER_PASS + 1)]
        for card_id in ids:
            self.to_review(card_id)
        self.assertEqual(len(self.run_pass()), teardown.PER_PASS)
        self.assertEqual(self.run_pass(), ids[teardown.PER_PASS:])

    def test_the_drain_step_never_fails_the_pass(self):
        with mock.patch.object(teardown, "upkeep", side_effect=RuntimeError("boom")):
            self.assertEqual(drain.teardown_upkeep(self.cfg, self.board, {"work"}, []), 0)


if __name__ == "__main__":
    unittest.main()
