"""A team flow's push fence (c-641, keel/flowfence.py): the format's `opens` and `bases`, the
destinations a `git push` names, the guard refusing a push to a shared branch, `kb flowpush`
pushing only under his grant, and `kb flowmove` on his word. On a scratch install and real
scratch git repos; the work pack's own flow and its `pr --flow` are in its own suite."""

import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from keel import actions, cli, flowfence, flowmoves, flows
from keel import config as config_module
from keel.board import Refused, open_board
from keel.config import human_token
from tests.test_installer import init
from tests.test_readiness import fake_tailscale

ROOT = Path(__file__).resolve().parent.parent
# A team flow of the work pack's shape, in neutral words (the pack's own is checked in its own
# suite, packs/work/tests/test_flow.py): a base, a trial environment he merges into, and an
# early move to the trunk by cherry-pick for a card based on next.
FLOW = """name = "Team"
description = "A base, a trial environment, an early move to main."

[[branch]]
id = "card"
label = "card branch"
kind = "card"

[[branch]]
id = "base"
label = "{base}"
kind = "base"

[[branch]]
id = "trial"
label = "trial"
kind = "environment"

[[branch]]
id = "trunk"
label = "main"
kind = "trunk"

[[branch]]
id = "pick"
label = "{branch}-main"
kind = "work"

[[move]]
id = "pr"
label = "Draft pull request"
from = "card"
to = "base"
by = "house"
step = "pr"
stages = ["building", "review"]

[[move]]
id = "to-trial"
label = "Merge to trial"
from = "card"
to = "trial"
by = "you"
stages = ["building", "review", "shipping"]
pushes = ["trial"]
prompt = "Merge {branch} into {target}, resolve conflicts, then kb flowpush {id} trial."

[[move]]
id = "early"
label = "Early to main"
from = "card"
to = "pick"
by = "you"
stages = ["review", "shipping"]
bases = ["next"]
pushes = ["pick"]
opens = ["trunk"]
prompt = "Cherry-pick {branch}'s commits onto {target} from main, then kb flowpush {id} pick --pr trunk."
"""


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class FormatTest(unittest.TestCase):
    def test_opens_names_a_branch_and_belongs_to_his_move(self):
        data = tomllib.loads(FLOW)
        move = next(dict(one) for one in data["move"] if one["id"] == "early")
        house = next(dict(one) for one in data["move"] if one["id"] == "pr")
        for changed, said in ((dict(move, opens=["prod"]), "opens prod"),
                              (dict(house, opens=["trunk"]), "has a prompt, pushes or opens"),
                              (dict(move, bases="next"), "`bases` must be a list")):
            with self.subTest(said=said), self.assertRaises(flows.FlowError) as caught:
                flows.parse(dict(data, move=[changed]), "f.toml")
            self.assertIn(said, str(caught.exception))

    def test_bases_decide_whether_a_move_is_offered(self):
        found = flows.parse_text(FLOW, "f.toml")
        on_next = {"stage": "review", "options": {"base": "next"}}
        on_main = {"stage": "review", "options": {"base": "main"}}
        self.assertEqual([one.id for one in flows.offered(found, on_next)], ["to-trial", "early"])
        self.assertEqual([one.id for one in flows.offered(found, on_main)], ["to-trial"])


class RepoCase(unittest.TestCase):
    """A bare origin with main, next and trial, and a clone on a card branch cut from next."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = self.tmp / "seed"
        git(self.tmp, "clone", "-q", str(self.origin), str(seed))
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            git(seed, "config", key, value)
        (seed / "a.txt").write_text("one\n")
        git(seed, "add", "a.txt")
        git(seed, "commit", "-qm", "one")
        for branch in ("main", "next", "trial"):
            git(seed, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        self.clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.clone))
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            git(self.clone, "config", key, value)
        git(self.clone, "switch", "-qc", "feature/x", "origin/next")
        (self.clone / "b.txt").write_text("two\n")
        git(self.clone, "add", "b.txt")
        git(self.clone, "commit", "-qm", "two")

    def remote_head(self, branch: str) -> str:
        return git(self.origin, "rev-parse", f"refs/heads/{branch}")


class TargetsTest(RepoCase):
    def test_each_push_form_names_its_destination(self):
        """The card branch was cut from origin/next, so it tracks it, as a work worktree's
        does: HEAD still pushes to its own name, and a bare push may go to either."""
        cases = {
            "git push origin trial": {"trial"},
            "git push -u origin HEAD": {"feature/x"},
            "git push": {"feature/x", "next"},
            "git push origin HEAD:trial": {"trial"},
            "git push origin +feature/x:refs/heads/main": {"main"},
            "git push --force-with-lease origin feature/x": {"feature/x"},
            f"git -C {self.clone} push origin HEAD:next": {"next"},
            "git push --all origin": {flowfence.EVERY},
            "cd x && git push -o ci.skip origin trial && echo done": {"trial"},
            "git status && kb flowpush c-1 dev": set(),
            "git commit -m 'push the fix'": set(),
        }
        for command, wanted in cases.items():
            with self.subTest(command=command):
                self.assertEqual(flowfence.targets(command, self.clone), wanted)

    def test_a_push_said_where_it_cannot_be_read_counts_as_every_branch(self):
        """The review's bypasses: a push inside another command, or one git is told to
        aim elsewhere, is never read as no push."""
        cases = {
            "sh -c 'git push origin trial'": {"trial"},
            # the `;` inside the quotes keeps the command whole, so it is read through
            "bash -lc \"cd x; git push origin trial\"": {"trial"},
            "echo $(git push origin trial)": {"trial"},
            "python3 -c 'import subprocess; subprocess.run([\"git\", \"push\", \"origin\", \"trial\"])'": {flowfence.EVERY},
            "git -c remote.origin.push=HEAD:refs/heads/trial push origin": {flowfence.EVERY},
            "git -c alias.p=push p origin trial": {flowfence.EVERY},
        }
        for command, wanted in cases.items():
            with self.subTest(command=command):
                self.assertEqual(flowfence.targets(command, self.clone), wanted)

    def test_a_command_that_pushes_nothing_reads_as_nothing_whatever_runs_it(self):
        """The fix check's regressions: xargs, a GIT_CONFIG env, a config read or an ordinary
        setting, a one-shot alias that does not push, and a note that says git-push."""
        for command in ("git diff --name-only | xargs git add", "xargs git rm",
                        "GIT_CONFIG_GLOBAL=/dev/null git commit -m x", "git config push.default",
                        "git config alias.st", "git config --unset alias.st", "git config remote.origin.push",
                        "git config push.autoSetupRemote true", "git -c alias.st=status st",
                        "kb note c-1 \"the git-push hook\"", "kb note c-1 \"git/push flow\""):
            with self.subTest(command=command):
                self.assertEqual(flowfence.targets(command, self.clone), set())
        for command in ("git config -f .git/config alias.ship push", "git config --file .git/config alias.ship push",
                        "git config set alias.ship push", "git config set remote.origin.push HEAD:refs/heads/trial",
                        "GIT_CONFIG_GLOBAL=/x git push origin feature/x", "xargs git push origin",
                        # the second fix check's: an env alias, xargs giving the subcommand,
                        # push.default, a write with a trailing read word, a wrapped variable
                        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.ship GIT_CONFIG_VALUE_0=push git ship origin HEAD:trial",
                        "echo push origin trial | xargs git", "xargs -I{} git {} origin trial",
                        "git -c push.default=matching push", "git config push.default matching",
                        "git config alias.ship push get", "git config remote.origin.push HEAD:refs/heads/trial list",
                        "sh -c 'G=git; $G push origin trial'", "sh -c '\"git\" push origin trial'"):
            with self.subTest(command=command):
                self.assertEqual(flowfence.targets(command, self.clone), {flowfence.EVERY})

    def test_a_remote_that_says_where_a_push_goes_or_an_alias_that_pushes_counts_too(self):
        git(self.clone, "config", "remote.origin.push", "HEAD:refs/heads/trial")
        self.assertEqual(flowfence.targets("git push origin", self.clone), {flowfence.EVERY})
        self.assertEqual(flowfence.targets("git push origin feature/x", self.clone), {flowfence.EVERY})
        git(self.clone, "config", "--unset", "remote.origin.push")
        git(self.clone, "config", "alias.ship", "push origin HEAD:trial")
        self.assertEqual(flowfence.targets("git ship", self.clone), {flowfence.EVERY})

    def test_a_push_that_names_no_remote_is_read_against_the_space_s_own(self):
        """c-665 review F2: a bare `git push` goes to the space's remote, so that remote's push
        mapping is the one that counts; the guard's refusal reads it off the flow info."""
        git(self.clone, "remote", "rename", "origin", "upstream")
        git(self.clone, "config", "remote.upstream.push", "HEAD:refs/heads/trial")
        self.assertEqual(flowfence.targets("git push", self.clone, "upstream"), {flowfence.EVERY})
        found = {"card": "c-1", "space": "team", "shared": ["trial"], "remote": "upstream"}
        early = flowfence.targets("git push", self.clone)       # what the guard read before the board spoke
        self.assertNotIn(flowfence.EVERY, early)
        self.assertIn("every branch", flowfence.refusal(found, "git push", self.clone, early))

    def test_flow_info_from_a_host_that_names_no_remote_means_origin(self):
        """c-665 review F8: a board's host from before `remote` was carried."""
        self.assertEqual(flowfence.remote_in({"card": "c-1"}), "origin")
        self.assertEqual(flowfence.remote_in({"card": "c-1", "remote": None}), "origin")
        self.assertEqual(flowfence.remote_in({"card": "c-1", "remote": "upstream"}), "upstream")


class InstallCase(RepoCase):
    """A scratch install whose personal space runs the team flow, and a card on it."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        for name in ("KEEL_HOME", "KEEL_CONFIG", "KEEL_URL", "KEEL_CARD", "KEEL_BOSUN", "KEEL_TOKEN"):
            os.environ.pop(name, None)
        self.home = self.tmp / "install"
        self.assertEqual(init(self.home), 0)
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        self.cfg = config_module.load(self.home / "config.toml", ensure=False)
        fake_tailscale(self.tmp / "bin", "{}")
        own = flows.space_file(self.cfg, "personal")
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text(FLOW)
        here = os.getcwd()
        os.chdir(self.clone)
        self.addCleanup(os.chdir, here)

    def card(self, board, stage="review", base="next") -> str:
        cid = board.create("personal", "a card", actor="human",
                           options={"branch": "feature/x", "base": base})
        board.conn.execute("UPDATE cards SET stage = ?, session_id = 's-1' WHERE id = ?", (stage, cid))
        board.conn.commit()
        return cid

    def tap(self, board, cid, move="to-trial"):
        with mock.patch.object(actions.house, "resume", return_value={"resumed": cid}):
            return actions.act(self.cfg, board, {"verb": "flow.move", "id": cid, "move": move})

    def flowpush(self, board, cid, branch, pr=None, actor="house", card=None):
        os.environ["KEEL_CARD"] = card or cid
        args = Namespace(id=cid, branch=branch, pr=pr, config=self.cfg, json=True)
        return cli.cmd_flowpush(board, args, actor)

    def merged_trial(self):
        git(self.clone, "fetch", "-q", "origin", "trial")
        git(self.clone, "switch", "-qc", "flow/trial", "origin/trial")
        git(self.clone, "merge", "-q", "--no-ff", "-m", "merge", "feature/x")


class FlowPushTest(InstallCase):
    def test_a_tapped_move_in_a_copy_pushes_by_the_remotes_address(self):
        """fix check 3: a copy's remote cannot be pushed to (`landpush.NO_PUSH`), but a flow
        move the user tapped is theirs, so `kb flowpush` pushes by the address, as the Push."""
        git(self.clone, "config", "remote.origin.pushurl", "no-push://set-by-shipyard")
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid)
            self.merged_trial()
            done = self.flowpush(board, cid, "trial")
        self.assertEqual(done["pushed"], "trial")
        self.assertEqual(self.remote_head("trial"), git(self.clone, "rev-parse", "HEAD"))
        self.assertEqual(git(self.clone, "rev-parse", "refs/remotes/origin/trial"), self.remote_head("trial"))

    def test_his_tap_lets_the_house_push_trial_and_nothing_else(self):
        with open_board(self.cfg) as board:
            cid = self.card(board)
            with self.assertRaises(Refused) as caught:
                self.flowpush(board, cid, "trial")
            self.assertIn("no flow move granted", str(caught.exception))
            self.tap(board, cid)
            for branch, said in (("base", "pushes trial, not base"), ("trunk", "pushes trial, not trunk")):
                with self.subTest(branch=branch), self.assertRaises(Refused) as caught:
                    self.flowpush(board, cid, branch)
                self.assertIn(said, str(caught.exception))
            with self.assertRaises(Refused) as caught:
                self.flowpush(board, cid, "trial", card="c-999")
            self.assertIn("own house's", str(caught.exception))
            self.merged_trial()
            done = self.flowpush(board, cid, "trial")
            notes = [row["text"] for row in board.events(cid) if "flow move to-trial" in (row["text"] or "")]
        self.assertEqual(done["pushed"], "trial")
        self.assertEqual(self.remote_head("trial"), git(self.clone, "rev-parse", "HEAD"))
        self.assertEqual(len(notes), 1)

    def test_the_grant_carries_the_git_names_filled_at_his_tap(self):
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid, "early")
            grant = board.get(cid)["options"][flowmoves.OPTION]
            found = flowfence.info(self.cfg, board.get(cid))
        self.assertEqual(grant["names"], {"pick": "feature/x-main", "trunk": "main"})
        self.assertEqual(found["grant"]["pushes"], {"pick": "feature/x-main"})
        self.assertEqual(found["shared"], ["main", "next", "trial"])

    def test_a_flow_whose_branch_was_renamed_after_the_tap_ends_the_grant(self):
        """c-664 (F11): the grant was given for `trial`; the flow now calls that branch
        `staging`, so the old name is neither granted nor pushed."""
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid)
            self.merged_trial()
            before = self.remote_head("trial")
            flows.space_file(self.cfg, "personal").write_text(FLOW.replace('label = "trial"', 'label = "staging"'))
            found = flowfence.info(self.cfg, board.get(cid))
            with self.assertRaises(Refused) as caught:
                self.flowpush(board, cid, "trial")
        self.assertIsNone(found["grant"])
        self.assertIn("changed since", str(caught.exception))
        self.assertEqual(self.remote_head("trial"), before)

    def test_a_card_whose_branch_reads_differently_keeps_its_grant(self):
        """c-664 review F6: the flow did not change, only what the card says its branch is,
        so the grant stands, with the names filled at the tap."""
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid, "early")
            board.conn.execute("UPDATE cards SET options = json_set(options, '$.branch', 'feature/y') WHERE id = ?", (cid,))
            found = flowfence.info(self.cfg, board.get(cid))
        self.assertEqual(found["why"], "")
        self.assertEqual(found["grant"]["pushes"], {"pick": "feature/x-main"})

    def test_a_grant_from_before_labels_were_kept_still_ends_on_a_rename(self):
        """A grant tapped before c-664's review carries no `labels`: its names are compared."""
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid)
            board.conn.execute("UPDATE cards SET options = json_remove(options, '$.flow_move.labels') WHERE id = ?", (cid,))
            self.assertIsNotNone(flowfence.info(self.cfg, board.get(cid))["grant"])
            flows.space_file(self.cfg, "personal").write_text(FLOW.replace('label = "trial"', 'label = "staging"'))
            self.assertIsNone(flowfence.info(self.cfg, board.get(cid))["grant"])

    def test_a_push_that_is_not_a_fast_forward_is_refused_never_forced(self):
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid)
            before = self.remote_head("trial")
            git(self.clone, "switch", "-qc", "elsewhere", "origin/main")
            (self.clone / "c.txt").write_text("three\n")
            git(self.clone, "add", "c.txt")
            git(self.clone, "commit", "-qm", "three")
            other = self.tmp / "other"
            git(self.tmp, "clone", "-q", str(self.origin), str(other))
            git(other, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "moved")
            git(other, "push", "-q", "origin", "HEAD:refs/heads/trial")
            moved = self.remote_head("trial")
            self.assertNotEqual(moved, before)
            with self.assertRaises(Refused) as caught:
                self.flowpush(board, cid, "trial")
        self.assertIn("never forced", str(caught.exception))
        self.assertEqual(self.remote_head("trial"), moved)

    def test_the_push_goes_to_the_space_s_own_remote(self):
        """c-665: `[spaces.<name>] remote`; the board's host says it (`info`), so the house's
        machine pushes there whatever its own config holds."""
        git(self.clone, "remote", "rename", "origin", "upstream")
        self.cfg.spaces["personal"].remote = "upstream"
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid)
            git(self.clone, "switch", "-qc", "flow/trial", "upstream/trial")
            git(self.clone, "merge", "-q", "--no-ff", "-m", "merge", "feature/x")
            found = flowfence.info(self.cfg, board.get(cid))
            done = self.flowpush(board, cid, "trial")
        self.assertEqual(done["pushed"], "trial")
        self.assertEqual(self.remote_head("trial"), git(self.clone, "rev-parse", "HEAD"))
        self.assertIn("git push -u upstream HEAD", flowfence.refusal(found, "git push upstream HEAD:trial", self.clone))

    def test_a_stage_move_ends_the_grant(self):
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid)
            board.stage(cid, "building", "human")
            with self.assertRaises(Refused):
                self.flowpush(board, cid, "trial")

    def test_the_early_move_pushes_the_pick_branch_and_opens_its_pull_request(self):
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid, "early")
            git(self.clone, "switch", "-qc", "feature/x-main", "origin/main")
            with mock.patch("keel.adapters.run", return_value="https://host/pr/7\n") as pack:
                done = self.flowpush(board, cid, "pick", pr="trunk")
            with self.assertRaises(Refused) as caught:
                self.flowpush(board, cid, "pick", pr="base")
        self.assertEqual(done["pushed"], "feature/x-main")
        self.assertEqual(done["pr"], "https://host/pr/7")
        self.assertEqual(pack.call_args.args[1:], ("pr", cid, "--flow", "feature/x-main", "--to", "main",
                                                   "--dir", str(self.clone)))
        self.assertEqual(self.remote_head("feature/x-main"), git(self.clone, "rev-parse", "HEAD"))
        self.assertIn("opens trunk, not base", str(caught.exception))

    def test_a_pull_request_that_fails_after_the_push_leaves_the_push_said(self):
        from keel import adapters
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid, "early")
            git(self.clone, "switch", "-qc", "feature/x-main", "origin/main")
            with mock.patch("keel.adapters.run", side_effect=adapters.AdapterError("host down")), \
                    self.assertRaises(Refused) as caught:
                self.flowpush(board, cid, "pick", pr="trunk")
            notes = [row["text"] for row in board.events(cid) if (row["text"] or "").startswith("flow move early")]
        self.assertIn("pushed feature/x-main, but", str(caught.exception))
        self.assertEqual(len(notes), 2)
        self.assertIn("pushed feature/x-main", notes[0])
        self.assertIn("host down", notes[1])

    def test_the_early_move_is_not_offered_on_a_main_card(self):
        with open_board(self.cfg) as board:
            cid = self.card(board, base="main")
            with self.assertRaises(actions.ActionError) as caught:
                self.tap(board, cid, "early")
        self.assertIn("for a card based on next", str(caught.exception))

    def test_a_worktree_that_is_not_the_cards_repo_is_refused(self):
        stranger = self.tmp / "stranger"
        git(self.tmp, "init", "-q", str(stranger))
        git(stranger, "remote", "add", "origin", str(self.tmp / "elsewhere.git"))
        found = {"card": "c-1", "space": "personal", "repos": ["keel"]}
        with mock.patch.object(self.cfg.spaces["personal"], "repo_path", return_value=self.clone):
            flowfence.check_repo(self.cfg, found, self.clone)
            with self.assertRaises(flowfence.FenceError):
                flowfence.check_repo(self.cfg, found, stranger)


class ClockTest(unittest.TestCase):
    """c-689: the house guard hands `targets` what is left of its own clock for git's reads."""

    def clocks(self, **kwargs) -> set:
        handed = set()

        def run(argv, **given):
            handed.add(given["timeout"])
            raise subprocess.TimeoutExpired(argv, given["timeout"])

        with mock.patch.object(flowfence.subprocess, "run", run):
            self.assertEqual(flowfence.targets("git push", "/nowhere", **kwargs), {flowfence.EVERY})
        return handed

    def test_git_reads_keep_thirty_seconds_unless_the_caller_says(self):
        self.assertEqual(self.clocks(), {30})
        self.assertEqual(self.clocks(timeout=2.5), {2.5})
        self.assertEqual(self.clocks(timeout=lambda: 1.5), {1.5})

    def test_a_clock_that_has_run_out_reads_nothing_and_counts_as_every_branch(self):
        self.assertEqual(self.clocks(timeout=0), set())


class GuardTest(InstallCase):
    """The guard as a house runs it: a subprocess fed the hook's JSON, reading `kb flowinfo`
    from the scratch install its env names, and exiting 2 with the sentence."""

    def hook(self, cid, command):
        env = dict(os.environ, KEEL_HOME=str(ROOT))
        env.pop("KEEL_CARD", None)
        payload = json.dumps({"tool_input": {"command": command}, "cwd": str(self.clone)})
        return subprocess.run([str(ROOT / "bin" / "keel-house-guard"), cid], input=payload, text=True,
                              capture_output=True, env=env, timeout=60)

    def test_a_push_to_a_shared_branch_is_refused_and_the_cards_own_is_not(self):
        with open_board(self.cfg) as board:
            cid = self.card(board, stage="building")
        for command in ("git push origin trial", "git push origin HEAD:next",
                        "git push origin HEAD:main", "git push --all origin",
                        "sh -c 'git push origin trial'",
                        # the review's evasions, each through the real hook (c-641 review 2)
                        "git -c alias.p=push p origin HEAD:trial",
                        "git config alias.ship push; git ship origin HEAD:trial",
                        "G=git; $G push origin trial",
                        'g(){ git "$@"; }; g push origin trial',
                        "T=trial; git push origin HEAD:$T",
                        'git push origin "HEAD:$(printf trial)"',
                        "git push origin 'refs/heads/tri*:refs/heads/tri*'",
                        "echo HEAD:trial | xargs git push origin",
                        "git config remote.origin.push refs/heads/feature/x:refs/heads/trial",
                        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.push GIT_CONFIG_VALUE_0=x git push origin feature/x"):
            with self.subTest(command=command):
                done = self.hook(cid, command)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("shared branch", done.stderr)
                self.assertIn(f"kb flowpush {cid}", done.stderr)
        for command in ("git push -u origin HEAD", "git push origin feature/x-main",
                        "kb flowpush c-1 trial", "git status"):
            with self.subTest(command=command):
                done = self.hook(cid, command)
                self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_the_brief_s_literal_board_push_passes_and_its_variable_form_is_still_refused(self):
        """r-56 (c-723): the guard is unchanged; the brief now writes the card and the file
        literally (`prompts.literal_board_push`), which is the form that passes."""
        with open_board(self.cfg) as board:
            cid = self.card(board, stage="building")
        ops = self.tmp / "state" / "cards" / cid / "flow.txt"
        done = self.hook(cid, f"keel board push --card {cid} --new --file {ops}")
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        done = self.hook(cid, "keel board push --card $KEEL_CARD --new --file $CLAUDE_JOB_DIR/flow.txt")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("shared branch", done.stderr)

    def test_a_backtick_lookup_of_git_is_git_through_a_variable(self):
        """c-723: `` `which git` push `` was read as no push at all; it is refused as
        `$(which git) push` always was."""
        with open_board(self.cfg) as board:
            cid = self.card(board, stage="building")
        for command in ("`which git` push origin trial", "$(which git) push origin trial"):
            with self.subTest(command=command):
                done = self.hook(cid, command)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("shared branch", done.stderr)

    def test_end_to_end_his_tap_then_the_house_merges_to_trial(self):
        """The tap tells the house; its raw push is refused by the hook; `kb flowpush`
        lands the merge."""
        with open_board(self.cfg) as board:
            cid = self.card(board)
            self.tap(board, cid)
            board.conn.commit()
            self.merged_trial()
            refused = self.hook(cid, "git push origin HEAD:trial")
            self.flowpush(board, cid, "trial")
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.remote_head("trial"), git(self.clone, "rev-parse", "HEAD"))


class FlowMoveTest(InstallCase):
    def args(self, cid):
        return Namespace(id=cid, move="to-trial", config=self.cfg, json=True)

    def test_his_word_through_harbor_makes_the_move_with_his_token(self):
        with open_board(self.cfg) as board:
            cid = self.card(board)
            for actor in ("house", "bosun", "cli"):
                with self.subTest(actor=actor), self.assertRaises(Refused):
                    cli.cmd_flowmove(board, self.args(cid), actor)
            os.environ["KEEL_TOKEN"] = human_token(self.cfg.token_path)
            actor = cli.resolve_actor("voice", self.cfg.token_path)
            with mock.patch.object(actions.house, "resume", return_value={"resumed": cid}) as resume:
                done = cli.cmd_flowmove(board, self.args(cid), actor)
            grant = board.get(cid)["options"][flowmoves.OPTION]
        self.assertEqual((actor, done["move"]), ("voice", "to-trial"))
        self.assertEqual(grant["pushes"], ["trial"])
        self.assertIn("Merge feature/x into trial", resume.call_args.kwargs["prompt"])

    def test_a_bare_actor_voice_is_not_him(self):
        """Any process without KEEL_CARD may type `--actor voice`; without his token it
        grants nothing (the review's hole)."""
        with open_board(self.cfg) as board:
            cid = self.card(board)
            actor = cli.resolve_actor("voice", self.cfg.token_path)
            with self.assertRaises(Refused) as caught:
                cli.cmd_flowmove(board, self.args(cid), actor)
            self.assertFalse(board.get(cid)["options"].get(flowmoves.OPTION))
        self.assertIn("carries your token", str(caught.exception))

if __name__ == "__main__":
    unittest.main()
