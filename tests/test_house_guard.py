"""The house guard: the PreToolUse(Bash) hook that refuses a wait loop on `pgrep -f` (c-534).

Driven the way Claude Code drives it, as a subprocess with the PreToolUse payload on stdin,
because the protocol (exit 2 and the reason on stderr) is half of what is being tested.
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "bin" / "keel-house-guard"
# The command c-526's house actually ran, from its job record, cut after the loop.
C526 = ('cd /home/ubuntu/keel/state/worktrees/c-526; while pgrep -f "tests.parallel" >/dev/null; '
        'do sleep 5; done; unset FORCE_COLOR; ( time make test ) > fulltest4.log 2>&1')


def run(command=None, raw: str | None = None) -> subprocess.CompletedProcess:
    body = raw if raw is not None else json.dumps({"tool_name": "Bash",
                                                   "tool_input": {"command": command}})
    return subprocess.run([str(GUARD)], input=body, capture_output=True, text=True, timeout=30)


class RefusedTest(unittest.TestCase):
    def test_c526s_own_command_is_refused_with_the_way_out(self):
        result = run(C526)
        self.assertEqual(result.returncode, 2)
        self.assertIn("never ends", result.stderr)
        self.assertIn("kill -0 <pid>", result.stderr)
        self.assertIn("run_in_background", result.stderr)

    def test_every_spelling_of_the_loop_is_refused(self):
        for command in ('until ! pgrep -f "make test" >/dev/null 2>&1; do sleep 10; done',
                        "while pgrep -af tests.parallel; do sleep 1; done",
                        "while /usr/bin/pgrep --full keel; do sleep 1; done",
                        "while true; do pgrep -fl suite || break; sleep 5; done",
                        "bash -c 'while pgrep -f x; do sleep 1; done'",
                        "while\n  pgrep -f x\ndo sleep 1; done"):
            with self.subTest(command=command):
                self.assertEqual(run(command).returncode, 2)


class AllowedTest(unittest.TestCase):
    def test_looking_and_waiting_on_a_named_pid_are_allowed(self):
        for command in ('pgrep -f "tests.parallel"',
                        "pgrep -af keel && echo found",
                        "while kill -0 4242 2>/dev/null; do sleep 5; done",
                        "while pgrep -x sleep; do sleep 1; done",
                        "while pgrep -F pidfile; do sleep 1; done",
                        "echo meanwhile; pgrep -f x",
                        "make test"):
            with self.subTest(command=command):
                result = run(command)
                self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_it_fails_open_on_a_payload_it_cannot_read(self):
        for raw in ("", "not json", "[]"):
            with self.subTest(raw=raw):
                self.assertEqual(run(raw=raw).returncode, 0)


SAYS = """#!{python}
import json, sys
asked = json.load(sys.stdin)
if "gh pr merge" in asked["command"]:
    print(json.dumps({{"allow": False, "why": "no merge for " + sys.argv[1] + " in " + str(asked["cwd"])}}))
else:
    print(json.dumps({{"allow": True}}))
"""
REFUSES_ALL = "#!{python}\nprint('{{\"allow\": false, \"why\": \"the pack says no\"}}')\n"
BARE_NO = "#!{python}\nprint('{{\"allow\": false}}')\n"
A_LIST = "#!{python}\nprint('[1, 2]')\n"
BROKEN = "#!{python}\nimport sys\nraise SystemExit('Traceback: the pack guard fell over')\n"
NOT_JSON = "#!{python}\nprint('allowed, probably')\n"
SLOW = "#!{python}\nimport time\ntime.sleep(60)\n"


def load_hook():
    loader = importlib.machinery.SourceFileLoader("keel_house_guard_pack", str(GUARD))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PackGuardTest(unittest.TestCase):
    """A pack may ship a `guard` verb (c-689): the hook hands it the command and refuses
    with the sentence it answers. Every pack here is a script in a temporary directory."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def pack(self, body: str) -> str:
        path = self.dir / "guard"
        path.write_text(body.format(python=sys.executable))
        path.chmod(0o755)
        return str(path)

    def hook(self, command: str, *argv: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, KEEL_HOME=str(ROOT))
        body = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/work/tree"})
        return subprocess.run([str(GUARD), *argv], input=body, capture_output=True, text=True, timeout=60,
                              env=env)

    def test_the_pack_s_sentence_is_the_refusal_and_its_allow_lets_the_command_run(self):
        guard = self.pack(SAYS)
        refused = self.hook("gh pr merge 1", "c-9", guard, "gh")
        self.assertEqual((refused.returncode, refused.stderr.strip()), (2, "no merge for c-9 in /work/tree"))
        allowed = self.hook("gh pr view 1", "c-9", guard, "gh")
        self.assertEqual((allowed.returncode, allowed.stderr), (0, ""))

    def test_with_no_guard_named_nothing_changes(self):
        """A card on a pack with no `guard` verb: the hook is run as it always was."""
        for command in ("gh pr merge 1", "gh auth token", "make test"):
            done = self.hook(command, "c-9")
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""), command)
        self.assertEqual(self.hook(C526, "c-9").returncode, 2)

    def test_the_hook_s_own_loop_refusal_comes_before_the_pack_is_asked(self):
        """The pack here would refuse the same line in its own words: the hook's are the
        ones returned, so the order is the loop first, then the pack."""
        guard = self.pack(REFUSES_ALL)
        self.assertIn("the pack says no", self.hook("make test", "c-9", guard, "gh").stderr)
        done = self.hook(C526, "c-9", guard, "gh")
        self.assertEqual(done.returncode, 2)
        self.assertIn("never ends", done.stderr)
        self.assertNotIn("the pack says no", done.stderr)

    def test_a_pack_guard_that_errors_refuses_only_a_command_naming_the_pack_s_tool(self):
        for body in (BROKEN, NOT_JSON, A_LIST):
            guard = self.pack(body)
            for command in ("gh pr view 1", "/opt/homebrew/bin/gh pr merge 1", "echo x; gh status"):
                done = self.hook(command, "c-9", guard, "gh")
                self.assertEqual(done.returncode, 2, command)
                self.assertIn("is broken", done.stderr)
                self.assertIn(guard, done.stderr)               # r3.F9: it names the guard
                self.assertNotIn("in a moment", done.stderr)    # and does not say to wait for it
                self.assertIn("`gh`", done.stderr)
                self.assertNotIn("Traceback", done.stderr)
            for command in ("make test", "git status", "cat packs/github/gh_fence.py", "echo sigh", "ls -gh"):
                done = self.hook(command, "c-9", guard, "gh")
                self.assertEqual((done.returncode, done.stderr), (0, ""), command)

    def test_a_pack_guard_that_is_missing_is_one_that_errors(self):
        gone = str(self.dir / "absent")
        refused = self.hook("gh pr view 1", "c-9", gone, "gh")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("is broken", refused.stderr)
        self.assertEqual(self.hook("make test", "c-9", gone, "gh").returncode, 0)

    def test_a_pack_guard_that_does_not_answer_in_time_is_one_that_errors(self):
        hook = load_hook()
        hook.PACK_SECONDS = 0.2
        guard = self.pack(SLOW)
        said = hook.problem("gh pr view 1", "c-9", None, (guard, "gh"))
        self.assertIn("could not be checked", said)
        self.assertIn("Try again in a moment", said)
        self.assertIsNone(hook.problem("make test", "c-9", None, (guard, "gh")))

    def test_a_refusal_with_no_sentence_is_still_a_refusal(self):
        """r3.F9: `{"allow": false}` alone refuses every command, tool word or not."""
        guard = self.pack(BARE_NO)
        for command in ("make test", "gh pr view 1", "ls"):
            done = self.hook(command, "c-9", guard, "gh")
            self.assertEqual(done.returncode, 2, command)
            self.assertIn("gave no reason", done.stderr)

    def test_one_deadline_covers_the_pack_the_git_reads_and_the_board(self):
        """r3.F8: the pack, flowfence's git reads and `kb flowinfo` share one budget under
        the harness's twenty seconds, and a push the budget cannot check is refused. Every
        process here is a stand-in that takes the whole clock it is handed, on a clock the
        test moves itself."""
        from unittest import mock
        hook = load_hook()
        now, handed = [100.0], []

        def run(argv, **kwargs):
            handed.append((Path(argv[0]).name, kwargs["timeout"]))
            now[0] += kwargs["timeout"]
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        with mock.patch.object(hook.time, "monotonic", lambda: now[0]), \
                mock.patch.object(subprocess, "run", run):
            said = hook.problem("git push origin feature/x", "c-9", "/work/tree", ("/pack/guard", "gh"),
                                until=100.0 + hook.BUDGET_SECONDS)
        self.assertIn("could not be read", said)
        self.assertEqual(handed[0], ("guard", hook.PACK_SECONDS))
        self.assertEqual([name for name, _ in handed[1:]], ["git"])       # one git read took the rest
        self.assertEqual(sum(seconds for _, seconds in handed), hook.BUDGET_SECONDS)
        from keel import house
        from tests.helpers import make_config
        hooks = house.hooks_for(make_config(self.dir), "c-9", shell=True)["PreToolUse"]
        handed = [entry["timeout"] for group in hooks for entry in group["hooks"]
                  if "keel-house-guard" in entry["command"]]
        self.assertEqual(len(handed), 1)
        self.assertLess(hook.BUDGET_SECONDS, handed[0])      # the harness's clock for this hook
        self.assertEqual(now[0], 100.0 + hook.BUDGET_SECONDS)

    def test_with_no_deadline_each_part_keeps_its_own_clock(self):
        from unittest import mock
        hook = load_hook()
        handed = []

        def run(argv, **kwargs):
            handed.append((Path(argv[0]).name, kwargs["timeout"]))
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        with mock.patch.object(subprocess, "run", run):
            self.assertIn("could not be read", hook.problem("git push origin feature/x", "c-9", "/work/tree"))
        self.assertEqual(handed[-1], ("kb", hook.KB_SECONDS))
        self.assertEqual({seconds for name, seconds in handed if name == "git"}, {30})


if __name__ == "__main__":
    unittest.main()
