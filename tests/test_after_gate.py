"""c-600, after the gate: the pieces around the shipping flow that `tests/test_shipping.py`
does not drive through the watcher.

- the house guard refuses a push while the card is at shipping, reading the stage live;
- `kb verdict` gathers the reply file and each commit's diff in the house's own clone;
- `keel check` picks a fix check, a full pass, or nothing;
- his Ship through the door of the machine that holds the house (the nonce, then the record);
- the outcome page's send back needs his words, and an outcome's Ask says outcome.
"""

import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from keel import actions, fixcheck, planactions, shipreplies
from keel.board import SHIPPING_OPTION, Board
from tests.helpers import SESSION, make_config

ROOT = Path(__file__).resolve().parent.parent


def load_guard():
    loader = importlib.machinery.SourceFileLoader("keel_house_guard", str(ROOT / "bin" / "keel-house-guard"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.guard = load_guard()

    def test_a_push_is_refused_only_while_the_card_is_at_shipping(self):
        pushes = ("git push origin feature/x", "git -C /wt push --force-with-lease",
                  "cd /wt && git push", "$KEEL_HOME/adapters/work/pr c-1 --ready",
                  "$KEEL_HOME/packs/work/pr c-1 --body",
                  "/home/x/keel/adapters/sandbox/publish c-1")
        for stage, refused in (("shipping", True), ("building", False)):
            # what `kb flowinfo` answers: at shipping a flow with a shared branch, which the
            # shipping rule refuses before it is read; at building one that shares nothing,
            # since `/wt` is not a worktree here and an unread push counts as every branch
            shared = ["dev"] if stage == "shipping" else []
            flow_info = {"card": "c-1", "space": "work", "stage": stage, "shared": shared, "grant": None}
            with mock.patch.object(self.guard, "card_of", return_value=flow_info) as asked:
                for command in pushes:
                    with self.subTest(stage=stage, command=command):
                        said = self.guard.problem(command, "c-1")
                        self.assertEqual(bool(said), refused)
                        if refused:
                            self.assertIn("only the user's Ship pushes", said)
                self.assertEqual(asked.call_count, len(pushes))

    def test_other_commands_never_read_the_board(self):
        with mock.patch.object(self.guard, "card_of") as asked:
            for command in ("git status", "git commit -m 'push the fix'", "ls adapters/work/prsend.py",
                            "kb verdict c-1 c11 --verdict valid"):
                self.assertIsNone(self.guard.problem(command, "c-1"), command)
        asked.assert_not_called()

    def test_a_board_that_cannot_be_read_holds_the_push(self):
        with mock.patch.object(self.guard, "card_of", side_effect=RuntimeError("no board")):
            self.assertIn("could not be read", self.guard.problem("git push", "c-1"))

    def test_without_a_card_id_it_is_the_old_guard(self):
        self.assertIsNone(self.guard.problem("git push", None))


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


class GitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.tree = self.dir / "tree"
        self.tree.mkdir()
        git(self.tree, "init", "-q", "-b", "main")
        git(self.tree, "config", "user.email", "t@example.invalid")
        git(self.tree, "config", "user.name", "T")
        (self.tree / "a.py").write_text("CAP = 40\n")
        git(self.tree, "add", "a.py")
        git(self.tree, "commit", "-qm", "base")

    def commit(self, text: str) -> str:
        (self.tree / "a.py").write_text(text)
        git(self.tree, "commit", "-qam", "name the cap")
        return git(self.tree, "rev-parse", "HEAD").strip()


class VerdictGatherTest(GitCase):
    def args(self, **given):
        base = dict(data=None, handle="c11", verdict="valid", why="checked", summary="why 40",
                    severity="", reply=None, reply_file=None, commit=None)
        return SimpleNamespace(**dict(base, **given))

    def test_the_reply_file_and_each_commit_s_diff_are_read_here(self):
        sha = self.commit("PAGE_SIZE = 40\n")
        reply = self.dir / "reply.md"
        reply.write_text("Named it after the host's page size.\n")
        data = shipreplies.gather(self.args(reply_file=str(reply), commit=[sha[:10]]), [self.tree])
        self.assertEqual(data["reply"].strip(), "Named it after the host's page size.")
        self.assertIn("+PAGE_SIZE = 40", data["commits"][0]["diff"])

    def test_a_commit_no_worktree_has_is_refused(self):
        with self.assertRaisesRegex(shipreplies.VerdictRefused, "no worktree"):
            shipreplies.gather(self.args(commit=["abcdef1234"]), [self.tree])
        with self.assertRaisesRegex(shipreplies.VerdictRefused, "not a commit"):
            shipreplies.gather(self.args(commit=["HEAD; rm -rf /"]), [self.tree])


class FixCheckTest(GitCase):
    def setUp(self):
        super().setUp()
        self.card_dir = self.dir / "card"
        self.card_dir.mkdir()
        self.card = {"id": "c-1", "repo": "api", "options": {"worktree": str(self.tree), "base": "main"}}

    def plan(self, stamped):
        return fixcheck.plan(self.card, self.card_dir, [self.tree], stamped, self.tree)[0]

    def stamp_at(self, head):
        key = str(self.tree.resolve())
        return {"head": head, "heads": {key: head}}

    def test_nothing_to_check_when_the_stamp_covers_head(self):
        head = git(self.tree, "rev-parse", "HEAD").strip()
        self.assertEqual(self.plan(self.stamp_at(head)), "checked")

    def test_a_fix_check_after_a_closed_pass_and_a_full_pass_otherwise(self):
        head = git(self.tree, "rev-parse", "HEAD").strip()
        self.commit("CAP = 41\n")
        self.assertEqual(self.plan({}), "full", "no pass yet")
        (self.card_dir / "review-rounds.json").write_text(json.dumps([{"round": 1, "complete": False}]))
        with mock.patch.object(fixcheck.stamp, "read_rounds", return_value=[{"round": 1, "complete": True}]):
            self.assertEqual(self.plan(self.stamp_at(head)), "fix")
        with mock.patch.object(fixcheck.stamp, "read_rounds", return_value=[{"round": 1, "complete": False}]):
            self.assertEqual(self.plan(self.stamp_at(head)), "full")


class ShipTapTest(unittest.TestCase):
    """His Ship for a card whose house is on the other machine: the same one-shot nonce as
    his Approve; the door runs the adapter there, and only its answer is recorded here."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        card_id = self.board.create("work", "Tidy", repo="api", actor="human", options={"pr": 4})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"shipping": True})
        told = dict(self.board.get(card_id)["options"][SHIPPING_OPTION],
                    told=[{"handle": "c11", "kind": "comment", "batch": 1}], round=1)
        self.board.set_fields(card_id, {"options": {SHIPPING_OPTION: told}}, "drain")
        self.board.verdict(card_id, {"handle": "c11", "verdict": "not-valid", "why": "w",
                                     "reply": "It is the page size."}, "house", card_id)
        self.card = card_id

    def test_the_deck_s_ship_tap_runs_kb_ship_here(self):
        with mock.patch.object(actions, "run_kb", return_value={"id": self.card}) as ran:
            answer = actions.act(self.cfg, self.board, {"verb": "ship", "id": self.card})
        ran.assert_called_once_with(self.cfg, ["ship", self.card])
        self.assertIn("note", answer)

    def test_a_caller_cannot_send_ship(self):
        with self.assertRaisesRegex(actions.ActionError, "one machine"):
            actions.act(self.cfg, self.board, {"verb": "ship", "id": self.card, "caller": {"actor": "house"}})


class OutcomePageTest(unittest.TestCase):
    """The e2e run: an outcome sent back with no notes went at once, and said "plan"."""

    def test_a_send_back_with_nothing_said_is_refused(self):
        card = {"id": "c-1", "stage": "review", "space": "work", "session_id": None}
        board = mock.Mock(get=mock.Mock(return_value=card), events=mock.Mock(return_value=[]))
        with mock.patch.object(planactions, "document", return_value={"blocks": [], "sections": []}), \
                mock.patch.object(planactions.receipt, "receipt", return_value=None), \
                mock.patch.object(planactions.receipt, "answerable", return_value=True):
            with self.assertRaisesRegex(planactions.SendError, "needs your reason"):
                planactions.send(None, board, {"id": "c-1", "mode": "sendback", "doc": "outcome"},
                                 approve=None, sendback=None, run_kb=None, gate_of=lambda c: "outcome")


if __name__ == "__main__":
    unittest.main()
