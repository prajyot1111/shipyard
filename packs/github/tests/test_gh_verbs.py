"""The verbs as the engine runs them: the executables in the pack's directory, a space that
names the pack in a real config, and a real board they read and write through `kb`.

The modules behind the verbs are held in the other test files with a recording board. This
one is the wiring: `keel/adapters.py` finds each executable, the verb loads the config
`KEEL_CONFIG` names, reads its card with `kb show`, and its answer is what the engine's own
reader takes.
"""

import json
import subprocess
import os
import unittest
from unittest import mock

from ghfake import PACK, GhCase, answer, git

import gh_fence
from keel.packkit import card as gh_card
from keel import adapters, config, house, readiness, reviewcards, reviewsettings, settings
from keel.board import Board

BRANCH = "shipyard/c-001-tidy-the-loader"


class EngineCase(GhCase):
    def setUp(self):
        super().setUp()
        toml = self.dir / "keel.toml"
        toml.write_text(
            "[keel]\n"
            f'state_dir = "{self.dir / "state"}"\n'
            "[spaces.personal]\n"
            f'config_dir = "{self.dir / "claude"}"\n'
            'contract = "etc/space-personal.md"\n'
            "[spaces.code]\n"
            'pack = "github"\n'
            f'config_dir = "{self.dir / "claude"}"\n'
            "[spaces.code.repos]\n"
            f'api = "{self.repo}"\n')
        # the verbs are other processes: they load this config, and inherit the test's PATH
        self.patch(mock.patch.dict(os.environ, {"KEEL_CONFIG": str(toml)}))
        self.cfg = config.load(toml)
        with Board(self.cfg.db_path) as board:
            self.id = board.create("code", "Tidy the loader", repo="api")

    def card(self) -> dict:
        with Board(self.cfg.db_path) as board:
            return board.get(self.id)


class GuardOnABoardTest(EngineCase):
    """r3.F3: `guard <id>` as its own process, reading the card with the real `kb show` from
    a scratch board, which is the only state the guard has."""

    def guard(self, command: str, card_id: str | None = None, **env: str) -> dict:
        done = subprocess.run([str(PACK / "guard"), card_id or self.id], text=True, capture_output=True,
                              input=json.dumps({"command": command, "cwd": str(self.repo)}), timeout=60,
                              env={**os.environ, **env})
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return json.loads(done.stdout)

    def research(self) -> str:
        with Board(self.cfg.db_path) as board:
            card_id = board.create("code", "Read the loader", repo="api")
            board.set_fields(card_id, {"options": {"kind": "research"}}, "human")
        return card_id

    def test_a_work_card_s_own_push_and_its_draft_are_allowed(self):
        for command in ("git push -u origin HEAD", f"{PACK / 'pr'} {self.id} --draft"):
            self.assertEqual(self.guard(command), {"allow": True}, command)

    def test_a_research_card_s_push_and_pr_are_refused_from_what_the_board_says(self):
        card_id = self.research()
        for command in ("git push -u origin HEAD", f"{PACK / 'pr'} {card_id} --draft"):
            said = self.guard(command, card_id)
            self.assertEqual(said["allow"], False, command)
            self.assertIn("research card", said["why"])
        self.assertEqual(self.guard("gh pr view 12", card_id), {"allow": True})

    def test_a_board_that_cannot_be_asked_holds_the_push_and_nothing_else(self):
        nowhere = self.dir / "no-keel-here"
        nowhere.mkdir()
        for command in ("git push -u origin HEAD", f"{PACK / 'pr'} {self.id} --draft"):
            said = self.guard(command, KEEL_HOME=str(nowhere))
            self.assertEqual(said["allow"], False, command)
            self.assertIn("could not be read", said["why"])
        self.assertEqual(self.guard("gh pr view 12", KEEL_HOME=str(nowhere)), {"allow": True})
        self.assertEqual(self.guard("git status", KEEL_HOME=str(nowhere)), {"allow": True})

    def test_a_review_card_s_push_and_pr_are_refused_from_what_the_board_says(self):
        """c-730: a review card's house reviews someone else's pull request: it pushes nothing
        and opens none, as a research card's does not."""
        with Board(self.cfg.db_path) as board:
            card_id = board.create("code", "Review: Faster loader", repo="api")
            board.set_fields(card_id, {"options": {"kind": "review", "review_key": "api:12", "pr": 12}}, "human")
        for command in ("git push origin HEAD", f"{PACK / 'pr'} {card_id} --draft"):
            said = self.guard(command, card_id)
            self.assertEqual(said["allow"], False, command)
            self.assertIn("review card", said["why"])
        self.assertEqual(self.guard("gh pr diff 12", card_id), {"allow": True})

    def test_a_card_with_a_review_key_and_no_kind_is_a_review_card_to_the_guard(self):
        """r1.F2: the guard calls a card a review card as the pack does (`gh_card.is_review`)."""
        with Board(self.cfg.db_path) as board:
            card_id = board.create("code", "Review: Faster loader", repo="api")
            board.set_fields(card_id, {"options": {"review_key": "api:12", "pr": 12}}, "human")
        said = self.guard("git push origin HEAD", card_id)
        self.assertEqual(said["allow"], False)
        self.assertIn("review card", said["why"])

    def test_a_card_the_board_does_not_have_holds_the_push(self):
        said = self.guard("git push -u origin HEAD", "c-999")
        self.assertEqual(said["allow"], False)
        self.assertIn("could not be read", said["why"])


class VerbsTest(EngineCase):
    def test_the_space_s_pack_is_this_directory(self):
        self.assertEqual(self.cfg.spaces["code"].adapter_dir.resolve(), PACK)

    def test_worktree_brief_deny_and_publishable_through_the_engine(self):
        self.gh()
        (tree,) = adapters.worktree(self.cfg, self.card())
        card = self.card()
        self.assertEqual((card["options"]["branch"], card["options"]["worktree"]), (BRANCH, str(tree)))
        self.assertEqual(git(tree, "rev-parse", "--abbrev-ref", "HEAD"), BRANCH)
        self.assertIn(f"{PACK / 'pr'} {self.id} --draft", adapters.brief(self.cfg, card))
        self.assertEqual(adapters.extra_deny(self.cfg, card), [])       # the guard reads commands instead
        self.assertEqual(house.pack_guard(self.cfg, card), f" {PACK / 'guard'} gh")
        self.assertIn(f"branch {BRANCH} is not on the remote", adapters.publishable(self.cfg, card))

    def test_a_verb_that_cannot_ask_github_refuses_in_one_line(self):
        with Board(self.cfg.db_path) as board:
            board.set_fields(self.id, {"options": {"pr": 12, "branch": BRANCH}}, "human")
        self.gh(answer("pr", "view", code=1, err="GraphQL: Could not resolve to a PullRequest "
                                                 "with the number of 12. (repository.pullRequest)\n"))
        with self.assertRaises(adapters.AdapterError) as refused:
            adapters.run(self.cfg.spaces["code"], "ship", self.id, "poll")
        self.assertEqual(str(refused.exception),
                         f"github/ship {self.id} exited 1: ship: gh pr view failed: GraphQL: Could not "
                         f"resolve to a PullRequest with the number of 12. (repository.pullRequest)")

    def test_approve_s_publish_is_the_engine_s_own_process_whatever_a_house_is_denied(self):
        """r1.F3: every house is refused this pack's `publish`, by the guard that reads what
        a house types. Approve outcome is not a house: the engine runs the executable itself."""
        with Board(self.cfg.db_path) as board:
            board.set_fields(self.id, {"options": {"pr": 12, "branch": BRANCH}}, "human")
            if board.get(self.id)["stage"] != "review":
                board.stage(self.id, "review", "human", plan_ref="plan.md", output_ref="pull request 12")
        card = self.card()
        self.assertIn("Approve outcome", gh_fence.problem(f"{PACK / 'publish'} {self.id}"))
        self.gh(answer("pr", "view", out={
            "number": 12, "url": "https://github.com/octo/api/pull/12", "isDraft": True, "title": "t",
            "state": "OPEN", "headRefOid": "f" * 40, "headRefName": BRANCH, "baseRefName": "main"}),
            answer("pr", "ready"))
        with self.assertRaisesRegex(adapters.AdapterError, "inside your Approve outcome or your Ship"):
            adapters.publish(self.cfg, card)                            # c-738 r1.F3: no tap, no publish
        with Board(self.cfg.db_path) as board:
            nonce = board.mark_publishing(self.id, "human")             # the user's Approve outcome, as `kb` marks it
            try:
                said = json.loads(adapters.publish(self.cfg, self.card(), nonce=nonce))
            finally:
                board.clear_publishing(self.id, nonce)
        self.assertEqual((said["pr"], said["shipping"], said["draft"]), (12, True, False))
        self.assertIn(["pr", "ready", "12", "-R", "github.com/octo/api"], self.calls())

    def test_a_space_on_the_pack_starts_with_review_scanning_off_until_the_user_says(self):
        """c-730: the pack can file review cards, and a space on it files none until the user
        turns `review_scan` on (Where finished work goes asks)."""
        self.assertFalse(self.cfg.spaces["code"].review_scan)
        self.assertEqual(readiness.refusal(self.cfg, self.cfg.spaces["code"], "reviews"),
                         "review scanning is off for code")
        self.gh()
        with Board(self.cfg.db_path) as board:
            self.assertEqual(reviewcards.upkeep(self.cfg, board, {"code"})["scanned"], 0)
        self.assertEqual(self.calls(), [])

    def test_once_it_is_on_the_drain_files_a_review_card_from_the_pack_s_scan(self):
        """The engine's own reader (`keel/reviewcards.py`, unchanged) takes the pack's rows."""
        cfg = self.reviews_on()
        self.gh(answer("pr", "list", "review-requested:@me", out=[{
            "number": 12, "title": "Faster loader", "body": "It reads the file once.", "author": {"login": "ana"},
            "createdAt": "2026-10-01T10:00:00Z", "updatedAt": "2026-10-02T09:00:00Z",
            "url": "https://github.com/octo/api/pull/12", "headRefName": "ana/faster-loader", "headRefOid": "f00d",
            "baseRefName": "main", "isCrossRepository": True, "isDraft": False}]))
        reviewcards.LAST_SCANNED.pop("code", None)
        with Board(cfg.db_path) as board:
            done = reviewcards.upkeep(cfg, board, {"code"})
            (filed,) = done["filed"]
            card = board.get(filed)
        self.assertEqual((card["title"], card["stage"], card["repo"]), ("Review: Faster loader", "inbox", "api"))
        self.assertEqual({key: card["options"][key] for key in ("kind", "review_key", "pr", "branch", "base", "slot")},
                         {"kind": "review", "review_key": "api:12", "pr": 12, "branch": "ana/faster-loader",
                          "base": "main", "slot": "review"})
        self.assertEqual(card["options"]["review_pr"]["url"], "https://github.com/octo/api/pull/12")
        self.assertTrue(card["options"]["review_fork"])          # r1.F1: GitHub said it is a fork's

    def test_the_reviews_gear_reads_and_sets_the_space_s_own_settings(self):
        cfg = self.reviews_on()
        space = cfg.spaces["code"]
        shown = adapters.providers_for(space)["reviews"]["settings"]
        self.assertEqual((shown["auto_review"], shown["review_model"]), (False, "sonnet"))
        self.assertEqual([verb["verb"] for verb in shown["verbs"]], ["set_auto_review", "set_review_model", "scan_now"])
        adapters.run_act(space, "reviews", "set_auto_review", "", {"value": "on"})
        self.assertTrue(reviewsettings.effective(cfg, "code")["auto"])
        adapters.run_act(space, "reviews", "scan_now", "", {})
        self.assertIn("asked", reviewsettings.scan_state(cfg, "code"))

    def test_settings_shows_the_pack_s_value_as_the_space_s_default(self):
        """c-730: Where finished work goes draws `review_scan` in the Settings form's field: off
        from the pack is the space's default, so the field says off, not "default on", and
        going back to the default turns it off again."""
        rows = settings.space_values(self.cfg, "code", self.cfg.spaces["code"])
        self.assertEqual(rows["space.review_scan"], {"value": False, "source": "pack", "default": False})
        self.assertNotIn("default", rows["space.review_auto"])        # one the pack does not set
        cfg = self.reviews_on()
        rows = settings.space_values(cfg, "code", cfg.spaces["code"])
        self.assertEqual(rows["space.review_scan"], {"value": True, "source": "config", "default": False})

    def reviews_on(self):
        toml = self.dir / "keel.toml"
        toml.write_text(toml.read_text().replace('pack = "github"\n', 'pack = "github"\nreview_scan = true\n'))
        return config.load(toml)

    def test_no_real_gh_is_reachable_from_here(self):
        self.assertFalse((self.bin / "gh").exists())
        self.assertEqual(gh_card.git(self.repo, "--version").returncode, 0)
        self.assertEqual(os.environ["PATH"], str(self.bin))


if __name__ == "__main__":
    unittest.main()
