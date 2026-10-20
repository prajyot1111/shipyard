"""The backend refuses with the panel's sentence (c-631, c-628 S3).

A space whose pack does not declare a capability is refused the verbs that need it, with the
`why` its readiness row says (`readiness.refusal`): Approve outcome and Ship of a repo card
without a code host, Reviews' route without review scanning, a card verb without a tracker,
review upkeep, and `kb create` with a repo on a space that can open none. On a real scratch
install, with a copy of the sandbox pack that declares only its tracker. A space with no pack
still merges locally, and the real packs publish as before.
"""

import dataclasses
import io
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from keel import actions, adapters, cli, deckstate, readiness, reviewcards
from keel import config as config_module
from keel.board import open_board
from tests.helpers import SESSION
from tests.test_installer import init

ROOT = Path(__file__).resolve().parent.parent
NO_CODEHOST = "the trackeronly connection has no code host"


def tracker_only(text: str) -> str:
    return (text.replace('name = "sandbox"', 'name = "trackeronly"').replace("codehost = true\n", "")
            .replace("reviews = true\n", "").replace('routes = ["reviews"]', "routes = []"))


class NeedsRefusalsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        readiness.forget()
        self.addCleanup(readiness.forget)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        self.cfg = config_module.load(self.home / "config.toml", ensure=False)
        self.pack = self.home.parent / "scratch-packs" / "trackeronly"
        shutil.copytree(ROOT / "packs" / "sandbox", self.pack)
        (self.pack / "pack.toml").write_text(tracker_only((self.pack / "pack.toml").read_text()))
        self.work = self.space("work", self.pack)

    def space(self, name: str, pack: Path | None):
        space = dataclasses.replace(self.cfg.spaces["personal"], name=name, adapter=pack and pack.name,
                                    adapter_dir=pack, repos={"api": self.home.parent / "api"})
        self.cfg.spaces[name] = space
        return space

    def card(self, space: str, stage: str = "review", repo: str | None = "api") -> dict:
        return {"id": "c-1", "space": space, "repo": repo, "stage": stage, "options": {}}

    # ----- publish: Approve outcome and Ship -----

    def test_a_repo_card_is_refused_publish_with_the_sentence_before_the_pack_runs(self):
        row = readiness.capability_rows(self.cfg, self.work)["codehost"]
        self.assertEqual(row["why"], NO_CODEHOST)
        with mock.patch.object(adapters, "run") as run:
            with self.assertRaises(adapters.AdapterError) as refused:
                adapters.publish(self.cfg, self.card("work"))
            with self.assertRaises(adapters.AdapterError):
                adapters.publish(self.cfg, self.card("work", stage="shipping"))     # his Ship
            self.assertIsNone(adapters.publish(self.cfg, self.card("work", repo=None)))
        self.assertEqual(str(refused.exception), row["why"])
        run.assert_not_called()

    def test_approve_outcome_leaves_the_card_at_review_with_the_sentence(self):
        with open_board(self.cfg) as board:
            card_id = board.create("work", "rename the handler", repo="api", actor="human")
            board.stage(card_id, "assigned", "human")
            board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
            board.stage(card_id, "building", "drain")
            board.stage(card_id, "review", "house", plan_ref="plan.md", output_ref="branch")
            with self.assertRaises(adapters.AdapterError) as refused:
                board.approve(card_id, "outcome", "human", publish=adapters.publisher(self.cfg, "work"))
            self.assertEqual(str(refused.exception), NO_CODEHOST)
            self.assertEqual(board.get(card_id)["stage"], "review")

    def test_the_gate_says_it_before_the_tap(self):
        """c-551's line, at the outcome gate and on the outcome page."""
        card = self.card("work")
        self.assertEqual(deckstate.unpublished_of(self.cfg, card, {}), NO_CODEHOST)
        self.assertEqual(deckstate.publish_refusal(self.cfg, card), NO_CODEHOST)
        self.assertIsNone(deckstate.publish_refusal(self.cfg, self.card("work", stage="building")))
        self.assertIsNone(deckstate.publish_refusal(self.cfg, self.card("work", repo=None)))

    def test_a_personal_card_with_a_repo_still_publishes_by_merge(self):
        """Bosun's condition on decision publish-without-codehost: the refusal is a pack's, and
        a space with no pack keeps its local merge exactly as today."""
        card = self.card("personal")
        self.assertIsNone(adapters.publish(self.cfg, card))
        self.assertIsNone(deckstate.publish_refusal(self.cfg, card))
        with mock.patch.object(adapters.merging, "publish", return_value={"merged": "abc"}) as merge:
            self.assertEqual(adapters.publisher(self.cfg, "personal")(card), {"merged": "abc"})
        merge.assert_called_once_with(self.cfg, card)

    def test_the_real_packs_still_publish(self):
        for name in ("work", "sandbox"):
            space = self.space(name, ROOT / "packs" / name)
            self.assertIsNone(readiness.refusal(self.cfg, space, "codehost"))
            with mock.patch.object(adapters, "run", return_value="published\n") as run, \
                 mock.patch.object(adapters.reviewround, "answer_for", return_value=None):
                self.assertEqual(adapters.publish(self.cfg, self.card(name)), "published")
            self.assertEqual(run.call_args.args[1:3], ("publish", "c-1"))

    # ----- the adapter's routes and review upkeep -----

    def test_reviews_route_and_a_card_verb_are_refused_with_the_sentence(self):
        with mock.patch.object(adapters, "run_act") as act, open_board(self.cfg) as board:
            with self.assertRaises(actions.ActionError) as reviews:
                actions.act_adapter(self.cfg, board, {"space": "work", "route": "reviews", "action": "scan_now"})
            with self.assertRaises(actions.ActionError) as card:
                actions.act_adapter(self.cfg, board, {"space": "personal", "route": "card", "action": "start", "key": "c-1"})
        act.assert_not_called()
        self.assertEqual(str(reviews.exception), "the trackeronly connection has no review scanning")
        self.assertEqual(str(card.exception), "no connection is turned on for personal")

    def test_a_declared_route_still_reaches_the_pack(self):
        with mock.patch.object(adapters, "run_act", return_value={"message": "ok"}) as act, open_board(self.cfg) as board:
            actions.act_adapter(self.cfg, board, {"space": "work", "route": "card", "action": "start", "key": "c-1"})
        act.assert_called_once()

    def test_upkeep_skips_a_space_that_does_not_declare_review_scanning(self):
        with mock.patch.object(adapters, "run") as run, open_board(self.cfg) as board:
            result = reviewcards.upkeep(self.cfg, board, {"work", "personal"})
        run.assert_not_called()
        self.assertEqual(result["scanned"], 0)

    # ----- kb create with a repo -----

    def kb(self, *argv) -> tuple[int, str]:
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        os.environ["HOME"] = str(self.home.parent / "home")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, err.getvalue()

    def without(self, *patterns: str) -> None:
        path = self.home / "config.toml"
        text = path.read_text()
        for pattern in patterns:
            text = re.sub(pattern, "\n", text)
        path.write_text(text)

    def test_an_unknown_repo_is_refused_with_the_repos_sentence_first(self):
        """The scratch install lists only its own packs and memory repos, which readiness does not count.
        (With its projects directory any plain name is a project to open, so that goes.)"""
        self.without(r'\nprojects_dir = "~/projects"\n')
        code, err = self.kb("create", "--space", "personal", "--repo", "x", "--title", "t")
        self.assertNotEqual(code, 0)
        self.assertIn("no repo is cloned for personal yet; x is not a repo the personal space can open (memory, packs)", err)

    def test_a_served_space_that_can_open_no_repo_refuses_any(self):
        self.without(r'\nprojects_dir = "~/projects"\n', r'\npacks = "[^"]*"\n', r'\nmemory = "[^"]*"\n')
        code, err = self.kb("create", "--space", "personal", "--repo", "x", "--title", "t")
        self.assertNotEqual(code, 0)
        self.assertIn("no repo is cloned for personal yet", err)
        self.assertNotIn("is not a repo", err)
        code, err = self.kb("create", "--space", "personal", "--title", "an errand")
        self.assertEqual(code, 0, err)

if __name__ == "__main__":
    unittest.main()
