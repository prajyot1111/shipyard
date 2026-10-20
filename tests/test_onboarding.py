"""The deck's Setup view (keel/onboarding.py, c-618): a repo cloned into the install's layout
is listed with both tiers, a house on it works under the repo's own `trees/` without the
team's CLAUDE.md, a tier saves, turning a pack on gives a space served here on that pack,
and the setup verbs are the page's alone and an install's alone."""

import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, adapters, configedit, house, onboarding, packs, packsetup, reposetup, scaffold
from keel import config as config_module
from keel.board import Refused, open_board
from tests.helpers import no_real_tools
from tests.test_installer import init


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        self.cfg = config_module.load(self.home / "config.toml", ensure=False)

    def bare(self) -> Path:
        """A bare origin with one commit carrying the team's own CLAUDE.md."""
        work, origin = self.home.parent / "work", self.home.parent / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        (work / "CLAUDE.md").write_text("the team's own rules\n")
        for argv in (["add", "."], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "one"],
                     ["push", "-q", str(origin), "HEAD:main"]):
            subprocess.run(["git", "-C", str(work), *argv], check=True)
        return origin

    def test_a_clone_lands_in_the_layout_with_both_tiers_and_is_listed(self):
        onboarding.clone_repo(self.cfg, "personal", "api", str(self.bare()))
        folder = self.home / "spaces" / "personal" / "api"
        self.assertEqual((folder / "repo" / "CLAUDE.md").read_text(), "the team's own rules\n")
        self.assertIn("api", (folder / "CLAUDE.md").read_text())
        self.assertTrue((self.home / "spaces" / "personal" / "CLAUDE.md").is_file())
        cfg = config_module.load(self.home / "config.toml", ensure=False)
        self.assertEqual(cfg.spaces["personal"].repos["api"], folder / "repo")
        # c-729, point 17: the copy lands here, so its origin cannot be pushed to
        pushurl = subprocess.run(["git", "-C", str(folder / "repo"), "config", "--get", "remote.origin.pushurl"],
                                 capture_output=True, text=True).stdout.strip()
        self.assertEqual(pushurl, "no-push://set-by-shipyard")

    # ----- Add your repos (c-678): one verb, the space made with the first repo -----

    def add(self, cfg=None, **body):
        cfg = cfg or self.reload()
        with open_board(cfg) as board:
            return actions.act(cfg, board, {"verb": "setup.repo.add", **body})

    def test_add_makes_the_space_copies_the_repo_and_names_it_from_its_address(self):
        origin = self.bare()
        answer = self.add(space="work", url=str(origin))
        self.assertEqual((answer["cloned"], answer["space"]), ("origin", "work"))
        cfg = self.reload()
        self.assertEqual(cfg.spaces["work"].repos["origin"], self.home / "spaces" / "work" / "origin" / "repo")
        self.assertEqual(self.add(space="work", url=str(origin), key="api")["cloned"], "api")
        self.assertEqual(sorted(self.reload().spaces["work"].repos), ["api", "origin"])

    def test_add_takes_the_path_of_a_folder_on_this_computer_with_a_tilde_too(self):
        """c-729: the address field says it also takes a path; `~` is the user's home, as a
        shell would read it (git itself does not)."""
        origin = self.bare()
        os.environ["HOME"] = str(origin.parent)
        answer = self.add(space="work", url="~/" + origin.name, key="notes")
        self.assertEqual(answer["cloned"], "notes")
        repo = self.reload().spaces["work"].repos["notes"]
        self.assertEqual((repo / "CLAUDE.md").read_text(), "the team's own rules\n")

    def test_a_copy_that_fails_leaves_no_space_behind_and_says_its_kind(self):
        before = (self.home / "config.toml").read_text()
        with self.assertRaises(actions.ActionError) as refused:
            self.add(space="work", url=str(self.home.parent / "nowhere"), key="api")
        self.assertEqual(refused.exception.detail["kind"], "nosuch")
        self.assertIn("There is no repo at that address.", refused.exception.detail["sentence"])
        self.assertEqual((self.home / "config.toml").read_text(), before, "the space it made is taken back")
        self.assertFalse((self.home / "spaces" / "work" / "api").exists())
        self.assertNotIn("work", self.reload().spaces)

    def test_a_copy_that_fails_in_a_space_that_was_there_keeps_the_space(self):
        onboarding.add_space(self.cfg, "work")
        with self.assertRaises(actions.ActionError):
            self.add(space="work", url=str(self.home.parent / "nowhere"), key="api")
        self.assertIn("work", self.reload().spaces)

    def test_add_refuses_an_address_that_names_no_repo(self):
        with self.assertRaisesRegex(actions.ActionError, "needs the repo's address"):
            self.add(space="work", url="")
        with self.assertRaisesRegex(actions.ActionError, "names no repo: give it a short name"):
            self.add(space="work", url="https://example.org/")
        self.assertNotIn("work", self.reload().spaces)

    def test_an_address_that_carries_a_password_is_refused_and_never_echoed(self):
        before = (self.home / "config.toml").read_text()
        with self.assertRaises(actions.ActionError) as refused:
            self.add(space="work", url="https://sam:s3cret@git.example.invalid/team/web.git")
        self.assertEqual(str(refused.exception), "That address carries a password, and Shipyard keeps no password in an "
                         "address. Sign in with the code host's own tool or a credential helper, then give the "
                         "address without it.")
        self.assertEqual((self.home / "config.toml").read_text(), before)

    def test_a_copy_that_fails_never_says_the_user_part_of_its_address(self):
        """No host is reached: a file address with a user part is refused by git at once."""
        with self.assertRaises(actions.ActionError) as refused:
            self.add(space="work", url=f"file://tok3n@{self.home.parent}/nowhere", key="api")
        self.assertNotIn("tok3n", str(refused.exception))
        self.assertNotIn("tok3n", str(refused.exception.detail))

    def test_a_listed_repo_shows_its_address_without_a_user_part(self):
        origin = self.bare()
        self.add(space="work", url=str(origin), key="api")
        copy = self.home / "spaces" / "work" / "api" / "repo"
        subprocess.run(["git", "-C", str(copy), "remote", "set-url", "origin", "https://tok3n@git.example.invalid/a/b.git"],
                       check=True)
        row = onboarding.report(self.reload())["spaces"]["work"]["repos"][0]
        self.assertEqual(row["origin"], "https://git.example.invalid/a/b.git")

    def test_a_listed_repo_says_its_home_address_and_the_branch_it_has_out(self):
        origin = self.bare()
        self.add(space="work", url=str(origin), key="api")
        row = onboarding.report(self.reload())["spaces"]["work"]["repos"][0]
        self.assertEqual((row["key"], row["origin"], row["branch"]), ("api", str(origin), "main"))

    def test_attach_makes_the_space_too(self):
        work = self.home.parent / "mine"
        subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
        with open_board(self.cfg) as board:
            actions.act(self.cfg, board, {"verb": "setup.repo.attach", "space": "work", "key": "mine", "path": str(work)})
        self.assertEqual(self.reload().spaces["work"].repos["mine"], work)

    # ----- the draft Bosun writes with the user (c-678) -----

    def draft_of(self, board, aim: str) -> dict:
        [card] = [c for c in board.list_cards(include_archived=False)
                  if (c.get("options") or {}).get("tier_proposal") == aim]
        return card

    def test_a_copied_repo_leaves_a_draft_card_that_bosun_stages_and_the_user_adopts(self):
        """The user's Add files the card (only the user may make a proposal card); nothing
        starts on it. Bosun, in conversation, stages it and writes the draft in its own card
        folder; Adopt, the user's tap, writes the file."""
        self.add(space="work", url=str(self.bare()), key="api")
        cfg = self.reload()
        tier = self.home / "spaces" / "work" / "api" / "CLAUDE.md"
        template = tier.read_text()
        with open_board(cfg) as board:
            card = self.draft_of(board, "work/api")
            self.assertEqual((card["stage"], card["space"], card["repo"], card["title"]),
                             ("inbox", "personal", None, "Draft the work/api CLAUDE.md"))
            self.assertTrue(card["options"]["tier_draft"])
            out = self.home / "builder" / "cards" / card["id"] / "claude-md.md"
            self.assertIn(str(out), card["brief"])
            self.assertIn(str(self.home / "spaces" / "work" / "api" / "repo"), card["brief"])
            self.assertEqual(onboarding.tiercards.proposals(board)["work/api"]["draft"], True)
            board.stage(card["id"], "building", "bosun")
            out.parent.mkdir(parents=True)
            out.write_text("# api: how to work in this repo\n\n- Run the tests: `npm test`\n")
            board.stage(card["id"], "review", "bosun", output_ref=str(out))
            self.assertEqual(tier.read_text(), template, "nothing is written before Adopt")
            answer = onboarding.adopt_tier(cfg, board, card["id"])
            self.assertEqual((answer["tier"], board.get(card["id"])["stage"]), (str(tier), "done"))
        self.assertEqual(tier.read_text(), "# api: how to work in this repo\n\n- Run the tests: `npm test`\n")

    def test_no_draft_card_is_left_where_there_is_no_builder(self):
        from keel import settings
        settings.save(self.cfg, [{"table": "keel", "key": "bosun_builder", "value": False}])
        self.add(space="work", url=str(self.bare()), key="api")
        with open_board(self.reload()) as board:
            self.assertEqual([c for c in board.list_cards() if (c.get("options") or {}).get("tier_proposal")], [])

    def test_propose_from_the_repo_takes_over_a_draft_nobody_has_started(self):
        """Setup's Propose (the audit house) is not blocked by the draft card Add left: an
        untouched one is archived and the audit is filed. One Bosun has started is not."""
        self.add(space="work", url=str(self.bare()), key="api")
        cfg = self.reload()
        with open_board(cfg) as board:
            draft = self.draft_of(board, "work/api")
            audit = onboarding.propose(cfg, board, "work", "api", "")["card"]
            self.assertNotEqual(audit, draft["id"])
            self.assertTrue(board.get(draft["id"])["options"]["archived"])
            self.assertEqual(self.draft_of(board, "work/api")["id"], audit)

    def test_the_tier_a_repo_starts_from_has_the_lines_keel_reads(self):
        self.add(space="work", url=str(self.bare()), key="api")
        text = (self.home / "spaces" / "work" / "api" / "CLAUDE.md").read_text()
        for line in ("## Prepare and test", "- Prepare a fresh copy:", "- Run the tests:", "## Running the app",
                     "- Sessions run tests only until this section says how to run the app."):
            self.assertIn(line, text)
        self.assertNotIn("Finished work lands on", text, "c-734: the lands line is retired")

    def test_a_house_on_a_cloned_repo_works_under_its_trees_without_the_team_file(self):
        onboarding.clone_repo(self.cfg, "personal", "api", str(self.bare()))
        cfg = config_module.load(self.home / "config.toml", ensure=False)
        card = {"id": "c-1", "space": "personal", "repo": "api", "title": "a change", "options": {}}
        folder = self.home / "spaces" / "personal" / "api"
        self.assertEqual(adapters.worktree(cfg, card), [folder / "trees" / "c-1"])
        excluded = house.settings_body(cfg, card)["claudeMdExcludes"]
        self.assertEqual(excluded, [f"{folder}/repo/**/CLAUDE.md", f"{folder}/trees/**/CLAUDE.md"])

    def test_a_repo_an_open_card_names_is_not_removed(self):
        onboarding.clone_repo(self.cfg, "personal", "api", str(self.bare()))
        cfg = config_module.load(self.home / "config.toml", ensure=False)
        with open_board(cfg) as board:
            card = board.create("personal", "a change", repo="api", actor="human")
            with self.assertRaisesRegex(onboarding.SetupError, card):
                reposetup.remove_repo(cfg, board, "personal", "api")
        self.assertIn("api", config_module.load(self.home / "config.toml", ensure=False).spaces["personal"].repos)

    def test_the_audit_reads_a_copy_and_may_not_edit_the_clone(self):
        onboarding.clone_repo(self.cfg, "personal", "api", str(self.bare()))
        cfg = config_module.load(self.home / "config.toml", ensure=False)
        clone = self.home / "spaces" / "personal" / "api" / "repo"
        with open_board(cfg) as board:
            card = board.get(onboarding.propose(cfg, board, "personal", "api", "")["card"])
        [copy] = card["options"]["add_dirs"]
        self.assertTrue((Path(copy) / "CLAUDE.md").is_file())
        self.assertFalse(Path(copy).is_relative_to(clone))
        self.assertIn(f"Edit(/{clone}/**)", house.settings_body(cfg, card)["permissions"]["deny"])

    def test_adopt_writes_the_tier_closes_the_card_and_stops_its_finished_house(self):
        """c-621: the audit card sat at review with its house alive after Adopt."""
        onboarding.clone_repo(self.cfg, "personal", "api", str(self.bare()))
        cfg = config_module.load(self.home / "config.toml", ensure=False)
        with open_board(cfg) as board, mock.patch.object(house, "retire_finished") as retire:
            card = onboarding.propose(cfg, board, "personal", "api", "")["card"]
            board.stage(card, "building", "drain")
            board.set_session(card, "5e55-0000-0000", "drain", bg_id="5e55")
            proposal = cfg.card_dir(card) / "claude-md.md"
            proposal.write_text("small commits\n\n## Audit notes\n- seen in CI\n")
            board.stage(card, "review", "house", output_ref=str(proposal))
            answer = onboarding.VERBS["setup.tier.adopt"](cfg, {"card": card}, board)
            self.assertEqual((answer["stage"], board.get(card)["stage"]), ("done", "done"))
            [(_, _, stopped), _] = retire.call_args
            self.assertEqual(stopped["id"], card)
        self.assertEqual((self.home / "spaces" / "personal" / "api" / "CLAUDE.md").read_text(),
                         "small commits\n")

    # ----- Approve outcome on a proposal card is Adopt (c-667) -----

    def drafted(self, cfg, board, text="small commits\n\n## Audit notes\n- seen in CI\n") -> str:
        """A tier proposal for the api repo at review, its draft holding `text`."""
        card = onboarding.propose(cfg, board, "personal", "api", "")["card"]
        board.stage(card, "building", "drain")
        proposal = cfg.card_dir(card) / "claude-md.md"
        proposal.write_text(text)
        board.stage(card, "review", "house", output_ref=str(proposal))
        return card

    def cloned(self):
        onboarding.clone_repo(self.cfg, "personal", "api", str(self.bare()))
        return self.reload(), self.home / "spaces" / "personal" / "api" / "CLAUDE.md"

    def test_approve_outcome_on_a_tier_proposal_adopts_it(self):
        cfg, tier = self.cloned()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            answer = actions.act(cfg, board, {"verb": "approve", "id": card, "gate": "outcome"})
            self.assertEqual((answer["tier"], board.get(card)["stage"]), (str(tier), "done"))
        self.assertEqual(tier.read_text(), "small commits\n")

    def test_an_approve_adopt_refuses_leaves_the_card_at_review(self):
        cfg, tier = self.cloned()
        before = tier.read_text()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board, text="\n")
            with self.assertRaisesRegex(actions.ActionError, "has no proposal"):
                actions.act(cfg, board, {"verb": "approve", "id": card, "gate": "outcome"})
            self.assertEqual(board.get(card)["stage"], "review")
        self.assertEqual(tier.read_text(), before)

    def test_adopt_and_approve_together_write_the_tier_once(self):
        cfg, tier = self.cloned()
        taps = ({"verb": "setup.tier.adopt"}, {"verb": "approve", "gate": "outcome"})
        with open_board(cfg) as board:
            for first, second in (taps, taps[::-1]):
                with self.subTest(first=first["verb"]):
                    card = self.drafted(cfg, board)
                    actions.act(cfg, board, dict(first, id=card, card=card))
                    tier.write_text("edited by hand since\n")
                    answer = actions.act(cfg, board, dict(second, id=card, card=card))
                    self.assertIn("already adopted", answer["note"])
                    self.assertEqual(tier.read_text(), "edited by hand since\n")

    def test_kb_approve_adopts_too_and_only_for_him(self):
        from argparse import Namespace
        from keel import cli
        cfg, tier = self.cloned()
        before = tier.read_text()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            args = Namespace(id=card, gate="outcome", config=cfg, said=None, relay=None, to=None, checked=None)
            for actor in ("house", "drain"):
                with self.assertRaises(Refused):
                    cli.cmd_approve(board, args, actor)
            with self.assertRaises(Refused):
                board.approve(card, "outcome", "bosun")
            self.assertEqual((board.get(card)["stage"], tier.read_text()), ("review", before))
            cli.cmd_approve(board, args, "human")
            self.assertEqual(board.get(card)["stage"], "done")
        self.assertEqual(tier.read_text(), "small commits\n")

    def test_only_he_names_a_tier_proposal(self):
        with open_board(self.cfg) as board:
            card = board.create("personal", "x", actor="human")
            with self.assertRaisesRegex(Refused, "options.tier_proposal"):
                board.set_fields(card, {"options": {"tier_proposal": "personal"}}, "house")
            with self.assertRaisesRegex(Refused, "options.tier_proposal"):
                board.create("personal", "y", actor="house", options={"tier_proposal": "personal"})

    def test_the_board_and_the_writers_name_the_same_proposals(self):
        from keel import board as board_module, flowcards, tiercards
        self.assertEqual(set(board_module.PROPOSAL_OPTIONS), set(onboarding.WRITERS))
        self.assertEqual(set(onboarding.WRITERS), {tiercards.OPTION, flowcards.OPTION})
        self.assertLessEqual(set(board_module.PROPOSAL_OPTIONS), set(board_module.HIS_AT_CREATE))

    def test_a_card_naming_both_proposals_is_refused_whole(self):
        cfg, tier = self.cloned()
        before = tier.read_text()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            board.set_fields(card, {"options": {"flow_proposal": "personal"}}, "human")
            for body in ({"verb": "approve", "id": card, "gate": "outcome"}, {"verb": "setup.tier.adopt", "card": card}):
                with self.assertRaisesRegex(actions.ActionError, "both a tier and a flow"):
                    actions.act(cfg, board, body)
            self.assertEqual(board.get(card)["stage"], "review")
        self.assertEqual(tier.read_text(), before)

    def test_a_move_refused_after_the_write_is_retried_with_no_second_write(self):
        """F2: what was adopted is the card's own record, not its stage."""
        cfg, tier = self.cloned()
        taps = ({"verb": "setup.tier.adopt"}, {"verb": "approve", "gate": "outcome"})
        with open_board(cfg) as board:
            for first, second in (taps, taps[::-1]):
                with self.subTest(first=first["verb"]):
                    card = self.drafted(cfg, board)
                    with mock.patch.object(board, "approve", side_effect=Refused("held for a moment")):
                        answer = actions.act(cfg, board, dict(first, id=card, card=card))
                    self.assertIn("was not moved to done: held for a moment", answer["note"])
                    self.assertEqual((board.get(card)["stage"], tier.read_text()), ("review", "small commits\n"))
                    tier.write_text("edited by hand since\n")
                    answer = actions.act(cfg, board, dict(second, id=card, card=card))
                    self.assertIn("already adopted", answer["note"])
                    self.assertEqual((board.get(card)["stage"], tier.read_text()), ("done", "edited by hand since\n"))

    def test_a_draft_revised_after_a_refused_move_is_written_again(self):
        cfg, tier = self.cloned()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            with mock.patch.object(board, "approve", side_effect=Refused("held")):
                actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": card})
            (cfg.card_dir(card) / "claude-md.md").write_text("smaller commits\n")
            answer = actions.act(cfg, board, {"verb": "approve", "id": card, "gate": "outcome"})
            self.assertNotIn("already", answer["note"])
            self.assertEqual((board.get(card)["stage"], tier.read_text()), ("done", "smaller commits\n"))

    def test_a_tier_file_removed_since_is_written_again(self):
        """Review 2 F4: the note counts only while what it names is still there."""
        cfg, tier = self.cloned()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            with mock.patch.object(board, "approve", side_effect=Refused("held")):
                actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": card})
            tier.unlink()
            answer = actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": card})
            self.assertNotIn("already", answer["note"])
            self.assertEqual((board.get(card)["stage"], tier.read_text()), ("done", "small commits\n"))

    def test_a_done_proposal_whose_tier_is_gone_since_says_so(self):
        """It WAS adopted (his note with this digest is on the card), so it does not say
        never; and it is done, so nothing is written again."""
        cfg, tier = self.cloned()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": card})
            tier.unlink()
            for body in ({"verb": "approve", "id": card, "gate": "outcome"}, {"verb": "setup.tier.adopt", "card": card}):
                with self.assertRaisesRegex(actions.ActionError, "was adopted into .*which is gone since; it is "
                                                                 "done, so nothing is written again: propose again"):
                    actions.act(cfg, board, body)
            self.assertEqual(board.get(card)["stage"], "done")
        self.assertFalse(tier.exists())

    def test_the_drain_never_closes_a_proposal_that_was_split(self):
        from tests.test_tracking_close import finish
        with open_board(self.cfg) as board:
            card = board.create("personal", "p", actor="human", options={"tier_proposal": "personal"})
            board.stage(card, "assigned", "human")
            board.stage(card, "building", "drain")
            [piece] = board.split(card, [{"title": "a"}], "house")
            finish(board, piece)
            with self.assertRaisesRegex(Refused, "closes by Adopt"):
                board.close_tracking(card, "drain", "every slice is done")
            self.assertNotEqual(board.get(card)["stage"], "done")

    def test_only_his_own_note_of_this_draft_counts_as_adopted(self):
        """F7: a note a house wrote, naming the draft's digest, skips no write."""
        import hashlib
        cfg, tier = self.cloned()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            digest = hashlib.sha256((cfg.card_dir(card) / "claude-md.md").read_bytes()).hexdigest()
            board.note(card, "adopted", "house", data={"adopted": str(tier), "digest": digest})
            actions.act(cfg, board, {"verb": "approve", "id": card, "gate": "outcome"})
        self.assertEqual(tier.read_text(), "small commits\n")

    def test_a_second_tap_while_one_adopts_is_refused(self):
        from keel import merging
        cfg, tier = self.cloned()
        before = tier.read_text()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            with merging.approve_lock(cfg, card):
                for body in ({"verb": "approve", "id": card, "gate": "outcome"}, {"verb": "setup.tier.adopt", "card": card}):
                    with self.assertRaisesRegex(actions.ActionError, "still running"):
                        actions.act(cfg, board, body)
            self.assertEqual((board.get(card)["stage"], tier.read_text()), ("review", before))

    def test_a_stage_move_never_closes_a_proposal(self):
        """F3: `kb stage <id> done` closed one with nothing written, past any Adopt."""
        cfg, tier = self.cloned()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            for actor in ("human", "house", "drain"):
                with self.subTest(actor=actor), self.assertRaisesRegex(Refused, "closes by Adopt"):
                    board.stage(card, "done", actor)
            self.assertEqual(board.get(card)["stage"], "review")
            board.set_fields(card, {"options": {"archived": True}}, "human")     # the way to drop one
            self.assertNotIn(f"personal/api", onboarding.tiercards.proposals(board))

    def test_a_done_proposal_never_adopted_says_to_propose_again(self):
        """F5: a tier card closed before Approve adopted: nothing was written, and is not now."""
        cfg, tier = self.cloned()
        before = tier.read_text()
        with open_board(cfg) as board:
            card = self.drafted(cfg, board)
            board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
            for body in ({"verb": "approve", "id": card, "gate": "outcome"}, {"verb": "setup.tier.adopt", "card": card}):
                with self.assertRaisesRegex(actions.ActionError, "Propose again"):
                    actions.act(cfg, board, body)
        self.assertEqual(tier.read_text(), before)

    def test_kb_approve_carries_his_words_ends_the_house_and_is_a_second_tap_too(self):
        from argparse import Namespace
        from keel import cli
        cfg, tier = self.cloned()
        with open_board(cfg) as board, mock.patch.object(house, "retire_finished") as retire:
            card = self.drafted(cfg, board)
            board.set_session(card, "5e55-0000-0000", "drain", bg_id="5e55")
            args = Namespace(id=card, gate="outcome", config=cfg, said="good, thanks", relay=None, to=None, checked=None)
            answer = cli.cmd_approve(board, args, "human")
            self.assertEqual((answer["card"]["stage"], answer["note"]), ("done", f"adopted into {tier}, its audit notes left on the card"))
            self.assertEqual(retire.call_count, 1)
            self.assertIn("good, thanks", [event["text"] for event in board.events(card)])
            second = self.drafted(cfg, board)
            actions.act(cfg, board, {"verb": "setup.tier.adopt", "card": second})
            tier.write_text("edited by hand since\n")
            args = Namespace(id=second, gate="outcome", config=cfg, said="again", relay=None, to=None, checked=None)
            self.assertIn("already adopted", cli.cmd_approve(board, args, "human")["note"])
        self.assertEqual(tier.read_text(), "edited by hand since\n")

    def test_a_tier_saves(self):
        with open_board(self.cfg) as board:
            onboarding.save_tier(self.cfg, board, "personal", None, "every repo: small commits")
        self.assertEqual((self.home / "spaces" / "personal" / "CLAUDE.md").read_text(),
                         "every repo: small commits\n")

    def test_turning_the_sandbox_pack_on_serves_a_space_on_it_here(self):
        packsetup.pack_on(self.cfg, "sandbox", "work")
        cfg = config_module.load(self.home / "config.toml", ensure=False)
        self.assertEqual(cfg.spaces["work"].adapter_dir, packs.PACKAGE / "packs" / "sandbox")
        self.assertEqual(cfg.spaces["work"].config_dir, self.home / "claude")
        self.assertIn("work", cfg.served_spaces())

    # ----- demo-only packs, and Turn off (c-688) -----

    def names(self, cfg) -> list[str]:
        # The packs that ship with the core; an owner's own pack may sit beside them (c-722).
        return [row["name"] for row in packsetup.rows(cfg)[0] if row["name"] in ("github", "sandbox")]

    def test_a_demo_only_pack_is_not_offered_on_an_install_until_a_space_is_on_it(self):
        self.assertEqual(self.names(self.cfg), ["github"])
        packsetup.pack_on(self.cfg, "sandbox", "work")          # named outright, it still turns on
        cfg = self.reload()
        self.assertEqual(self.names(cfg), ["github", "sandbox"])   # shown, so it can be turned off
        sandbox = next(row for row in packsetup.rows(cfg)[0] if row["name"] == "sandbox")
        self.assertEqual(sandbox["spaces"], ["work"])

    def test_a_demo_only_pack_is_listed_where_the_config_is_not_an_installs(self):
        other = self.home / "other.toml"
        shutil.copy(self.home / "config.toml", other)
        self.assertEqual(self.names(config_module.load(other, ensure=False)), ["github", "sandbox"])

    def off(self, space: str) -> dict:
        cfg = self.reload()
        with open_board(cfg) as board:
            return packsetup.pack_off(cfg, board, space)

    def text(self) -> str:
        return (self.home / "config.toml").read_text()

    def test_turning_a_pack_off_leaves_the_space_plain_with_its_repos(self):
        onboarding.clone_repo(self.cfg, "personal", "api", str(self.bare()))
        packsetup.pack_on(self.reload(), "sandbox", "personal")
        self.assertEqual(self.reload().spaces["personal"].adapter, "sandbox")
        answer = self.off("personal")
        cfg = self.reload()
        self.assertEqual((answer["space"], answer["pack"]), ("personal", "sandbox"))
        self.assertEqual(answer["note"], "Work for personal stays on this computer now; its repos and its own settings are kept")
        self.assertEqual((cfg.spaces["personal"].adapter, cfg.spaces["personal"].adapter_dir), (None, None))
        self.assertEqual(set(cfg.spaces["personal"].repos), {"packs", "memory", "api"})
        self.assertTrue(packsetup.pack_on(cfg, "sandbox", "personal")["adopted"], "and on again")

    def test_turn_off_takes_back_every_line_turn_on_wrote(self):
        """r1.F1, r1.F4, r1.F7: a space Turn on made is left with its Claude dir alone, the
        note that named the pack gone with the pack's own keys."""
        before = self.text()
        packsetup.pack_on(self.cfg, "sandbox", "work")
        self.assertIn("# Turned on in the deck's Setup view: the sandbox pack", self.text())
        self.off("work")
        block = f'[spaces.work]\nconfig_dir = "{self.home / "claude"}"\n'
        self.assertIn(block, self.text())
        left = [line for line in self.text().splitlines() if line.strip()]
        for line in block.splitlines():
            del left[len(left) - 1 - left[::-1].index(line)]      # the last one: the new table's
        self.assertEqual(left, [line for line in before.splitlines() if line.strip()])

    def forge(self) -> None:
        """A second pack in the install's own packs, with its own contract and pipeline."""
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        scaffold.new_pack("forge", into=self.home / "packs")
        (self.home / "packs" / "forge" / "config.example.toml").write_text(
            '[spaces.work]\npack = "forge"\nconfig_dir = "~/.claude"\n'
            'contract = "etc/space-work.md"\npipeline = "etc/pipeline-personal.md"\n'
            'deny = ["mcp__one", "mcp__two"]\n')

    def test_the_next_pack_turned_on_brings_its_own_contract_and_pipeline(self):
        """r1.F1: sandbox off, another pack on. The old pack's example keys went with it, so
        the new pack's are the ones the space runs on."""
        self.forge()
        packsetup.pack_on(self.reload(), "sandbox", "work")
        root = self.reload().root
        self.assertEqual(self.reload().spaces["work"].pipeline, root / "demo" / "sandbox" / "pipeline-work.md")
        self.off("work")
        packsetup.pack_on(self.reload(), "forge", "work")
        space = self.reload().spaces["work"]
        self.assertEqual((space.adapter, space.contract, space.pipeline),
                         ("forge", root / "etc" / "space-work.md", root / "etc" / "pipeline-personal.md"))

    def rewritten(self, old: str, new: str) -> None:
        """The config with one line of the work space written another way by hand."""
        head, header, table = self.text().partition("\n[spaces.work]\n")     # the table itself, not an example
        self.assertIn(old, table)
        (self.home / "config.toml").write_text(head + header + table.replace(old, new, 1))
        self.reload()                                       # it still loads

    def test_a_key_reformatted_by_hand_is_left_in_place_and_turn_off_goes_on(self):
        """Fix check 1: a key that cannot be taken out cleanly as one line (a list over
        several lines, a quoted key) never refuses Turn off: it stays and the answer names it."""
        self.forge()
        packsetup.pack_on(self.reload(), "forge", "work")
        self.rewritten('deny = ["mcp__one", "mcp__two"]', 'deny = [\n  "mcp__one",\n  "mcp__two",\n]')
        self.rewritten('contract = "etc/space-work.md"', '"contract" = "etc/space-work.md"')
        answer = self.off("work")
        self.assertEqual(answer["left"], ["contract", "deny"])
        self.assertEqual(answer["note"], "Work for work stays on this computer now; its repos and its own settings are kept; "
                                         "left in place: contract, deny")
        table = tomllib.loads(self.text())["spaces"]["work"]
        self.assertEqual(table, {"config_dir": str(self.home / "claude"), "contract": "etc/space-work.md",
                                 "deny": ["mcp__one", "mcp__two"]})
        self.assertNotIn("Turned on", self.text())
        self.assertIsNone(self.reload().spaces["work"].adapter)

    def test_turn_off_takes_only_the_pack_line_when_its_example_cannot_be_read(self):
        """Fix check 1: with no example to compare with, nothing but `pack` and the note go."""
        self.forge()
        packsetup.pack_on(self.reload(), "forge", "work")
        (self.home / "packs" / "forge" / "config.example.toml").write_text("not = [toml\n")
        answer = self.off("work")
        self.assertEqual(answer["left"], [])
        table = tomllib.loads(self.text())["spaces"]["work"]
        self.assertEqual(sorted(table), ["config_dir", "contract", "deny", "pipeline"])
        self.assertNotIn("Turned on", self.text())

    def test_a_done_card_and_an_archived_card_do_not_hold_turn_off(self):
        packsetup.pack_on(self.cfg, "sandbox", "work")
        cfg = self.reload()
        with open_board(cfg) as board:
            done = board.create("work", "landed", actor="human")
            for stage, actor in (("assigned", "human"), ("building", "house")):
                board.stage(done, stage, actor)
            board.stage(done, "review", "house", plan_ref="p", output_ref="o")
            board.stage(done, "done", "human")
            dropped = board.create("work", "dropped", actor="human")
            board.set_fields(dropped, {"options": {"archived": True}}, "human")
            packsetup.pack_off(cfg, board, "work")
        self.assertIsNone(self.reload().spaces["work"].adapter)

    def test_a_key_the_user_changed_survives_turn_off(self):
        packsetup.pack_on(self.cfg, "sandbox", "work")
        path = self.home / "config.toml"
        path.write_text(configedit.set_entry(self.text(), "spaces.work", "contract", "etc/space-personal.md"))
        self.off("work")
        space = self.reload().spaces["work"]
        self.assertEqual((space.adapter, space.pipeline), (None, None))
        self.assertEqual(space.contract, self.reload().root / "etc" / "space-personal.md")

    def test_turning_off_refuses_a_space_with_no_pack_and_one_that_does_not_exist(self):
        before = self.text()
        with self.assertRaisesRegex(onboarding.SetupError, "personal is on no connection"):
            self.off("personal")
        with self.assertRaisesRegex(onboarding.SetupError, "there is no space 'nowhere'"):
            self.off("nowhere")
        self.assertEqual(self.text(), before)

    def test_turning_off_refuses_while_the_space_has_open_cards_naming_them(self):
        """r1.F2: a card at review there would land as a local merge where the pack would
        have opened its change, and its pack verbs would stop."""
        packsetup.pack_on(self.cfg, "sandbox", "work")
        cfg, before = self.reload(), self.text()
        with open_board(cfg) as board:
            first = board.create("work", "in flight", actor="human")
            second = board.create("work", "also in flight", actor="human")
            board.create("personal", "another space's", actor="human")
            with self.assertRaisesRegex(onboarding.SetupError,
                                        rf"work still has open cards \({first}, {second}\): .*merged on this computer.*"
                                        rf"finish or archive them first"):
                packsetup.pack_off(cfg, board, "work")
        self.assertEqual(self.text(), before)

    def test_turning_off_refuses_an_adapter_named_by_hand_and_an_inline_table(self):
        """r1.F7: both are written by hand, so both are taken off by hand."""
        onboarding.add_space(self.cfg, "work")
        path = self.home / "config.toml"
        path.write_text(configedit.set_entry(self.text(), "spaces.work", "adapter", "older"))
        before = self.text()
        with self.assertRaisesRegex(onboarding.SetupError, "work names the older adapter by hand"):
            self.off("work")
        self.assertEqual(self.text(), before)
        path.write_text(before + f'\n[spaces]\nside = {{ config_dir = "{self.home / "claude"}", pack = "sandbox" }}\n')
        before = self.text()
        self.assertEqual(self.reload().spaces["side"].adapter, "sandbox")
        with self.assertRaisesRegex(onboarding.SetupError, "written inline"):
            self.off("side")
        self.assertEqual(self.text(), before)

    def test_turn_off_is_a_setup_verb_that_changes_the_config(self):
        """r1.F8: the wiring only. That a verb is the page's alone is one rule for every
        body (`serve.refused_unproven`), held by its own tests, not per verb."""
        self.assertIn("setup.pack.off", onboarding.CONFIG_VERBS)
        packsetup.pack_on(self.cfg, "sandbox", "work")
        cfg = self.reload()
        with open_board(cfg) as board:
            actions.act(cfg, board, {"verb": "setup.pack.off", "space": "work"})
        self.assertIsNone(self.reload().spaces["work"].adapter)

    def test_a_pack_row_says_whether_it_is_demo_only(self):
        """r1.F3: the page words Turn off's confirm by it."""
        packsetup.pack_on(self.cfg, "sandbox", "work")
        rows = {row["name"]: row["demo_only"] for row in packsetup.rows(self.reload())[0]
                if row["name"] in ("github", "sandbox")}
        self.assertEqual(rows, {"github": False, "sandbox": True})

    # ----- the first run's verbs (c-632) -----

    def reload(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def test_the_space_the_first_run_makes_fetches_first_and_offers_push(self):
        """Written in its table, since the default is off (review F1): only a space the first
        run makes gets them, and the Lands step shows both as switches."""
        onboarding.add_space(self.cfg, "team")
        made = self.reload().spaces
        self.assertEqual((made["team"].fetch_before_work, made["team"].offer_push), (True, True))
        self.assertEqual((made["personal"].fetch_before_work, made["personal"].offer_push), (False, False),
                         "a space that was there names neither, and is unchanged")
        self.assertIn("Added in the deck's first run", (self.home / "config.toml").read_text())

    def test_a_space_added_from_setup_on_a_finished_install_gets_neither_switch(self):
        """Both were written on for every space the Setup verbs make (review r2.F1); the plan
        says only a space the first run makes has them."""
        from keel import firstrun     # noqa: PLC0415
        firstrun.write(self.cfg, {"skipped": {}, "finished": "2026-10-03T10:00:00+00:00"})
        onboarding.add_space(self.cfg, "team")
        made = self.reload().spaces["team"]
        self.assertEqual((made.fetch_before_work, made.offer_push), (False, False))
        text = (self.home / "config.toml").read_text()
        self.assertIn("Added from Setup", text)
        self.assertNotIn("Added in the deck's first run", text)
        self.assertNotIn("fetch_before_work", text.split("[spaces.team]")[1])

    def test_a_space_added_is_served_here_with_no_repos(self):
        onboarding.add_space(self.cfg, "work")
        cfg = self.reload()
        self.assertEqual((cfg.spaces["work"].repos, cfg.spaces["work"].adapter), ({}, None))
        self.assertEqual(cfg.spaces["work"].config_dir, self.home / "claude")
        self.assertIn("work", cfg.served_spaces())
        with self.assertRaisesRegex(onboarding.SetupError, "already a space 'work'"):
            onboarding.add_space(cfg, "work")
        with self.assertRaisesRegex(onboarding.SetupError, "is not a space name"):
            onboarding.add_space(cfg, "Work Stuff")

    def test_attach_lists_an_existing_checkout_where_it_is(self):
        checkout = self.home.parent / "mine"
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        answer = reposetup.attach_repo(self.cfg, "personal", "mine", str(checkout))
        self.assertIn("outside this install's layout", answer["note"])
        self.assertEqual(self.reload().spaces["personal"].repos["mine"], checkout)
        self.assertTrue(checkout.is_dir() and not (self.home / "spaces" / "personal" / "mine").exists())

    def test_attach_refuses_a_path_with_no_git_and_one_in_another_install(self):
        plain = self.home.parent / "plain"
        plain.mkdir()
        with self.assertRaisesRegex(onboarding.SetupError, "holds no .git"):
            reposetup.attach_repo(self.cfg, "personal", "plain", str(plain))
        other = self.home.parent / "other"
        (other / "spaces" / "personal" / "api" / "repo" / ".git").mkdir(parents=True)
        (other / "config.toml").write_text("")
        with self.assertRaisesRegex(onboarding.SetupError, f"inside the install at {other}"):
            reposetup.attach_repo(self.cfg, "personal", "api", str(other / "spaces" / "personal" / "api" / "repo"))
        self.assertEqual(set(self.reload().spaces["personal"].repos), {"packs", "memory"})

    def test_turn_on_adopts_a_plain_space_and_refuses_one_on_a_pack(self):
        onboarding.add_space(self.cfg, "work")
        before = (self.home / "config.toml").read_text()
        answer = packsetup.pack_on(self.reload(), "sandbox", "work")
        self.assertTrue(answer["adopted"])
        cfg = self.reload()
        self.assertEqual(cfg.spaces["work"].adapter_dir, packs.PACKAGE / "packs" / "sandbox")
        self.assertEqual(cfg.spaces["work"].config_dir, self.home / "claude")       # its own, kept
        self.assertEqual(cfg.spaces["work"].repos, {})                              # the example's are not taken
        self.assertTrue(before.split("[spaces.work]")[0] in (self.home / "config.toml").read_text())
        with self.assertRaisesRegex(onboarding.SetupError, "already on the sandbox connection"):
            packsetup.pack_on(cfg, "work", "work")

    def test_the_new_verbs_change_the_config_and_are_refused_with_a_caller(self):
        for verb in ("setup.space.add", "setup.repo.attach"):
            self.assertIn(verb, onboarding.CONFIG_VERBS)
        for verb in ("setup.space.add", "setup.repo.attach", "firstrun.skip", "firstrun.finish",
                     "firstrun.login.check", "firstrun.identity.save"):
            with self.subTest(verb=verb), self.assertRaisesRegex(actions.ActionError, "one machine"):
                actions.act(self.cfg, None, {"verb": verb, "space": "work", "step": "repos",
                                             "caller": {"actor": "house", "card": "c-1"}})
        self.assertNotIn("work", self.reload().spaces)

    def test_a_setup_verb_is_refused_with_a_caller(self):
        body = {"verb": "setup.pack.on", "pack": "sandbox", "space": "work",
                "caller": {"actor": "house", "card": "c-1"}}
        with self.assertRaises(actions.ActionError):
            actions.act(self.cfg, None, body)
        self.assertNotIn("work", config_module.load(self.home / "config.toml", ensure=False).spaces)

    def test_a_setup_verb_is_refused_on_a_config_that_is_not_an_install(self):
        other = self.home / "other.toml"
        shutil.copy(self.home / "config.toml", other)
        cfg = config_module.load(other, ensure=False)
        with self.assertRaises(actions.ActionError):
            actions.act(cfg, None, {"verb": "setup.pack.on", "pack": "sandbox", "space": "work"})
        self.assertEqual(other.read_text(), (self.home / "config.toml").read_text())


if __name__ == "__main__":
    unittest.main()
