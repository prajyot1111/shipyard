"""Lane RC, RC-2: a review card runs Keel's review core in PEER mode.

A review card's house reviews a colleague's pull request with the same two agents and the
same finding schema as a house's self review, and none of what makes a self review a gate:
the harness records the rounds, but no stamp is ever written for a review card and the Stop
hook never holds one (HP-8). The house drafts each surviving finding's public comment in
its `public_comment` slot through `keel-review draft`, which refuses what could not be
posted. Every pull request here is invented.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import ending, house
from keel.board import Board
from keel.review import agents, gate, prep, stamp
from tests.helpers import SESSION, FakeHarness, make_config, make_repo

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")
FOUND = [{"id": "F1", "axis": "standards", "severity": "high", "path": "thing.txt", "line": 1,
          "claim": "the cap is read too early", "evidence": "thing.txt:1", "suggestion": "read it later"},
         {"id": "F2", "axis": "standards", "severity": "low", "path": "thing.txt", "line": None,
          "claim": "a name", "evidence": "thing.txt", "suggestion": "rename"}]
REVIEW_OPTIONS = {"review_key": "keel:4150", "kind": "review", "slot": "review", "pr": 4150}


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def answer(items) -> str:
    return "```json\n" + json.dumps(items) + "\n```"


class PeerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.cfg = make_config(self.dir, repos={"keel": self.repo})
        self.cfg.spaces["personal"].house_review = True
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        patch = mock.patch.object(house, "harness", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def review_card(self, **options) -> str:
        card_id = self.board.create("personal", "Review: Tidy the loader", repo="keel",
                                    brief="The loader reads its page cap once.", actor="human",
                                    options=dict(REVIEW_OPTIONS, **options))
        self.board.stage(card_id, "assigned", "human")
        return card_id

    def worktree(self, card_id: str) -> Path:
        tree = self.cfg.worktrees_dir / card_id
        self.cfg.worktrees_dir.mkdir(parents=True, exist_ok=True)
        sh(self.repo, "git", "worktree", "add", "-q", "-b", f"pr/{card_id}", str(tree))
        (tree / "thing.txt").write_text("CAP = 40\n")
        sh(tree, *GIT, "add", "thing.txt")
        sh(tree, *GIT, "commit", "-q", "-m", "the pull request's change")
        return tree

    def finished(self, card_id, tree, agent, said, peer=True):
        return stamp.stamp(self.cfg, card_id, {
            "hook_event_name": "SubagentStop", "agent_type": agent, "cwd": str(tree),
            "session_id": SESSION, "last_assistant_message": said}, peer=peer)


class PeerLaunchTest(PeerCase):
    def test_a_review_card_gets_the_agents_and_the_peer_steps_not_the_pipeline(self):
        card_id = self.review_card()
        house.launch(self.cfg, self.board, card_id)
        self.assertEqual(set(json.loads(self.fake.starts[0]["agents"])), {agents.REVIEWER, agents.VERIFIER})
        brief = (self.cfg.card_dir(card_id) / "brief.md").read_text()
        for word in ("keel-review prep", "keel-review draft", agents.REVIEWER, agents.VERIFIER):
            self.assertIn(word, brief)
        for word in ("**Preship.**", "**Risk.**", "keel-review answer"):
            self.assertNotIn(word, brief)
        requirements = (self.cfg.card_dir(card_id) / gate.REQUIREMENTS_FILE).read_text()
        self.assertIn("The loader reads its page cap once.", requirements)

    def test_its_hooks_record_the_rounds_in_peer_mode_and_the_record_is_not_the_house_s(self):
        card_id = self.review_card()
        house.launch(self.cfg, self.board, card_id)
        settings = json.loads((self.cfg.card_dir(card_id) / "settings.json").read_text())
        groups = settings["hooks"]["SubagentStop"]
        self.assertEqual({g["matcher"] for g in groups}, {agents.REVIEWER, agents.VERIFIER})
        for group in groups:
            self.assertTrue(group["hooks"][0]["command"].endswith(f"{card_id} --peer"))
        self.assertIn(f"Write(/{self.cfg.card_dir(card_id) / stamp.FINDINGS_FILE})",
                      settings["permissions"]["deny"])

    def test_a_card_that_is_not_a_review_card_is_not_in_peer_mode(self):
        card_id = self.board.create("personal", "Add a thing", repo="keel", actor="human")
        self.board.stage(card_id, "assigned", "human")
        house.launch(self.cfg, self.board, card_id)
        settings = json.loads((self.cfg.card_dir(card_id) / "settings.json").read_text())
        self.assertNotIn("--peer", json.dumps(settings["hooks"]["SubagentStop"]))


class ReReviewBriefTest(PeerCase):
    def test_a_re_review_is_handed_the_change_since_and_what_he_posted_and_dropped(self):
        posted = {"head": "feedface00112233", "round": 1, "ledger": [
            {"id": "r1-f1", "path": "app/loader.py", "line": 40, "choice": "post", "claim": "the cap is read early"},
            {"id": "r1-f3", "path": "app/loader.py", "line": 12, "choice": "drop", "claim": "a name"}]}
        card_id = self.review_card(review_posted=posted, review_round=2)
        house.launch(self.cfg, self.board, card_id)
        brief = (self.cfg.card_dir(card_id) / "brief.md").read_text()
        self.assertIn("--since feedface00112233", brief)
        self.assertIn(prep.SINCE_FILE, brief)
        ledger = (self.cfg.card_dir(card_id) / "review-ledger.md").read_text()
        self.assertIn("- posted r1-f1 at `app/loader.py:40`: the cap is read early", ledger)
        self.assertIn("- dropped r1-f3 at `app/loader.py:12`: a name", ledger)
        self.assertIn("Never raise one of those again", brief)

    def test_a_first_round_has_no_ledger(self):
        card_id = self.review_card()
        house.launch(self.cfg, self.board, card_id)
        self.assertFalse((self.cfg.card_dir(card_id) / "review-ledger.md").exists())
        self.assertNotIn("--since", (self.cfg.card_dir(card_id) / "brief.md").read_text())


class FocusTest(PeerCase):
    """2026-09-24: his Review settings carry an optional focus note (`options.review_focus`)
    that reaches the reviewer with the diff: in the brief's own words, and as a file among
    the ONLY paths the reviewer is handed. A focus weighs where to look hardest; it does not
    narrow what the reviewer judges."""

    def test_the_focus_reaches_the_brief_and_the_reviewer_s_paths(self):
        card_id = self.review_card(review_focus="Look hardest at the retry loop's cap.")
        house.launch(self.cfg, self.board, card_id)
        card_dir = self.cfg.card_dir(card_id)
        brief = (card_dir / "brief.md").read_text()
        self.assertIn("Look hardest at the retry loop's cap.", brief)
        focus = card_dir / "review-focus.md"
        self.assertIn("Look hardest at the retry loop's cap.", focus.read_text())
        review_step = next(line for line in brief.split("\n\n") if "subagent_type" in line and agents.REVIEWER in line)
        self.assertIn(str(focus), review_step)

    def test_no_focus_says_nothing_and_leaves_no_file_behind(self):
        card_id = self.review_card(review_focus="an old note")
        house.launch(self.cfg, self.board, card_id)
        self.board.set_fields(card_id, {"options": {"review_focus": None}}, "human")
        house.review_block(self.cfg, self.board.get(card_id))
        card_dir = self.cfg.card_dir(card_id)
        self.assertFalse((card_dir / "review-focus.md").exists())
        self.assertNotIn("review-focus.md", house.review_block(self.cfg, self.board.get(card_id)))


class NoStampTest(PeerCase):
    def test_a_complete_peer_round_is_recorded_and_never_stamped(self):
        card_id = self.review_card()
        tree = self.worktree(card_id)
        self.assertIsNone(self.finished(card_id, tree, agents.REVIEWER, answer(FOUND)))
        self.assertIsNone(self.finished(card_id, tree, agents.VERIFIER, answer(
            [{"id": "r1.F1", "verify": "kept", "reason": "it holds", "evidence": "thing.txt:1"}])))
        rounds = stamp.read_rounds(self.cfg.card_dir(card_id))
        self.assertTrue(rounds[-1]["complete"])
        self.assertEqual(rounds[-1]["findings"][0]["verify"], "kept")
        self.assertFalse(stamp.stamp_path(self.cfg, card_id).exists())

    def test_the_stop_hook_never_holds_a_review_card_at_its_gate(self):
        card_id = self.review_card()
        tree = self.worktree(card_id)
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.set_fields(card_id, {"options": {gate.SESSION_OPTION: SESSION}}, "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="https://example.invalid/pr/4150")
        self.assertIsNone(ending.check(self.cfg, self.board, card_id, {"cwd": str(tree)}))
        self.assertEqual(self.board.get(card_id)["stage"], "review")

    def test_the_stamp_script_passes_peer_through(self):
        card_id = self.review_card()
        tree = self.worktree(card_id)
        payload = {"hook_event_name": "SubagentStop", "agent_type": agents.REVIEWER, "cwd": str(tree),
                   "session_id": SESSION, "last_assistant_message": answer([])}
        with mock.patch.object(stamp, "stamp", return_value=None) as called, \
                mock.patch("keel.config.load", return_value=self.cfg), \
                mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps(payload))):
            stamp.stamp_main([card_id, "--peer"])
        self.assertTrue(called.call_args.kwargs["peer"])


class DraftTest(PeerCase):
    def round_with(self, card_dir, *found):
        stamp.save_rounds(card_dir, [{"round": 1, "head": "abc", "complete": True, "findings": list(found)}])

    def one(self, **over):
        base = dict(FOUND[0], id="r1.F1", verify="kept", verify_reason="holds", verify_evidence="",
                    public_comment=None)
        return dict(base, **over)

    def test_a_draft_fills_the_finding_s_public_comment_and_shows_in_review_md(self):
        card_dir = self.dir / "card"
        card_dir.mkdir()
        self.round_with(card_dir, self.one())
        prep.draft(card_dir, "r1.F1", "Could the cap be read inside the call instead?")
        found = stamp.read_rounds(card_dir)[-1]["findings"][0]
        self.assertEqual(found["public_comment"], "Could the cap be read inside the call instead?")
        self.assertIn("Could the cap be read inside the call", (card_dir / stamp.REVIEW_FILE).read_text())

    def test_a_draft_that_could_not_be_posted_is_refused(self):
        card_dir = self.dir / "card"
        card_dir.mkdir()
        self.round_with(card_dir, self.one(), self.one(id="r1.F2", line=None),
                        self.one(id="r1.F3", verify="refuted", severity="low"))
        for fid, text, why in (("r1.F1", "A dash \u2014 here", "em-dash"), ("r1.F1", "  ", "says nothing"),
                               ("r1.F2", "Rename it.", "no line"), ("r1.F3", "Rename it.", "refuted"),
                               ("r1.F9", "Rename it.", "not a finding")):
            with self.assertRaisesRegex(prep.PrepError, why):
                prep.draft(card_dir, fid, text)

    def test_since_writes_the_change_since_the_reviewed_head(self):
        card_id = self.review_card()
        tree = self.worktree(card_id)
        reviewed = sh(tree, "git", "rev-parse", "HEAD")
        (tree / "thing.txt").write_text("CAP = settings.cap()\n")
        sh(tree, *GIT, "commit", "-qam", "read the cap later")
        card_dir = self.dir / "card"
        prep.prepare(card_dir, "main", [tree], since=reviewed)
        since = (card_dir / prep.SINCE_FILE).read_text()
        self.assertIn("+CAP = settings.cap()", since)
        self.assertNotIn("+CAP = 40", since)


if __name__ == "__main__":
    unittest.main()
