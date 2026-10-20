"""A stand-in for `gh` on PATH, a recording `git`, and the fixtures the pack's tests share.

`GhCase` makes a directory that is the WHOLE of PATH for a test: `sh` and `python3` linked
in from this machine, a `git` that writes down its arguments and then runs the real one,
and `gh` only once the test plans one. The stand-in gh records every call (its arguments
and what it was handed on stdin) as one JSON line and answers from the plan: the first rule
whose `when` words all appear among the arguments (a word ending `*` matches by prefix), and
that has answered fewer than its `times` calls when it says one. A
call no rule answers exits 64 and says so, so a test never passes on an answer it did not
plan. No test here can reach the real gh or the network: the real one is not on the path at
all, and every origin is a bare repository in the test's own temporary directory.

Two reads are answered for every plan unless a test plans its own: the repository's default
branch (`main`) and whether a branch is protected (it is not). `calls()` leaves them out,
since nearly every verb asks them before it writes; `asked_about_branches()` is those alone.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import suitefence  # noqa: F401 - installs the suite fence (tests/fence.py)

from keel.packkit import card as gh_card  # noqa: E402
from keel.packkit import shared as gh_shared  # noqa: E402
from keel.board import nonce_digest  # noqa: E402
from keel.config import Space  # noqa: E402
from keel.packkit import pulls as gh_pulls  # noqa: E402
from tests import helpers  # noqa: E402

PACK = suitefence.PACK
SLUG = "octo/api"
# The user's tap (c-738 r1.F3): every test runs with this nonce handed, as Keel hands it to `publish`
# inside Approve outcome or Ship, and a card inside the tap carries `TAPPED`, the marker the
# board keeps; a card without it is a house's run, which `publish` refuses.
TAP_NONCE = "a-tap-nonce"
TAPPED = {"digest": nonce_digest(TAP_NONCE), "at": "2026-10-10T10:00:00+00:00"}

SCRIPT = f"""#!{sys.executable}
import json, os, sys
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
argv = sys.argv[1:]
with open(os.environ["GH_FAKE_LOG"], "a") as out:
    out.write(json.dumps({{"argv": argv, "stdin": stdin}}) + "\\n")
with open(os.environ["GH_FAKE_PLAN"]) as handle:
    plan = json.load(handle)
def has(word, args=argv):
    return any(a.startswith(word[:-1]) for a in args) if word.endswith("*") else word in args
with open(os.environ["GH_FAKE_LOG"]) as handle:
    before = [json.loads(line)["argv"] for line in handle if line.strip()]
for rule in plan:
    seen = sum(1 for args in before if all(has(word, args) for word in rule["when"]))
    if rule.get("times") and seen > rule["times"]:
        continue
    if all(has(word) for word in rule["when"]):
        sys.stdout.write(rule.get("out", ""))
        sys.stderr.write(rule.get("err", ""))
        sys.exit(rule.get("code", 0))
sys.stderr.write("fake gh: no answer planned for " + " ".join(argv) + "\\n")
sys.exit(64)
"""

GIT_SCRIPT = """#!{python}
import json, os, sys
with open(os.environ["GIT_FAKE_LOG"], "a") as out:
    out.write(json.dumps(sys.argv[1:]) + "\\n")
os.execv({git!r}, [{git!r}, *sys.argv[1:]])
"""


def answer(*when: str, out=None, err: str = "", code: int = 0, times: int = 0) -> dict:
    """One rule of the plan: `out` as text, or anything else as its JSON; with `times`, it
    answers only that many of the calls it matches, and the next rule answers the rest."""
    text = out if isinstance(out, str) else ("" if out is None else json.dumps(out))
    return {"when": list(when), "out": text, "err": err, "code": code, "times": times}


def default_branch(name: str) -> dict:
    return answer("repo", "view", "defaultBranchRef", out={"defaultBranchRef": {"name": name}})


def protection(slug: str, branch: str, protected: bool) -> dict:
    return answer("api", f"repos/{slug}/branches/{branch}", out={"name": branch, "protected": protected})


NOT_FOUND = "gh: Not Found (HTTP 404)\n"
# What every plan answers last: the default branch is main, and no branch is protected.
BRANCH_READS = [default_branch("main"), answer("api", "repos/octo/api/branches/*", out={"protected": False}),
                answer("api", "repos/octo/web/branches/*", out={"protected": False})]


def about_branches(call: list[str]) -> bool:
    return "defaultBranchRef" in call or any(w.startswith("repos/") and "/branches/" in w for w in call)


def git(repo, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *args],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


class Kb:
    """A recording board: what a verb set and noted, and the cards it lists."""

    def __init__(self):
        self.options, self.notes, self.listed = [], [], []

    def set_option(self, card_id, key, value):
        self.options.append((card_id, key, value))

    def note(self, card_id, text):
        self.notes.append((card_id, text))

    def cards(self):
        return list(self.listed)


class GhCase(unittest.TestCase):
    """A scratch space `code` on the pack: one repo `api`, cloned from a bare origin on this
    disk that git is told to read where the clone's remote says github.com, a recording
    board, and a PATH that holds nothing but sh, python3, the recording git and (once
    planned) the gh stand-in."""

    def setUp(self):
        gh_shared.forget()          # a repository's default branch is kept for a process
        self.tmp = tempfile.TemporaryDirectory(prefix="keel-github-test-")
        self.dir = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        os.symlink(shutil.which("sh"), self.bin / "sh")
        os.symlink(sys.executable, self.bin / "python3")
        recorder = self.bin / "git"
        recorder.write_text(GIT_SCRIPT.format(python=sys.executable, git=shutil.which("git")))
        recorder.chmod(0o755)
        self.log, self.plan_file, self.git_log = (self.dir / name for name in ("gh.log", "gh.plan", "git.log"))
        self.patch(mock.patch.dict(os.environ, {
            "PATH": str(self.bin), "GH_FAKE_LOG": str(self.log), "GH_FAKE_PLAN": str(self.plan_file),
            "GIT_FAKE_LOG": str(self.git_log),
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{self.dir / 'origin'}/.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/octo/"}))
        self.repo = self.make_repo("api")
        self.cfg = helpers.make_config(self.dir / "keel")
        self.cfg.spaces["code"] = Space(name="code", config_dir=self.dir / "claude", contract=None,
                                        repos={"api": self.repo}, adapter="github", adapter_dir=PACK)
        self.kb = Kb()
        self.patch(mock.patch.object(gh_card, "keel_config", lambda: self.cfg))
        self.patch(mock.patch.object(gh_card, "KB", self.kb))
        # the nonce as the verb takes it from its environment (`pulls.take_nonce`, which takes it
        # out, so a second publish in one test process would find none): every call is handed it
        self.patch(mock.patch.object(gh_pulls, "take_nonce", lambda: TAP_NONCE))
        # the verb's clock, pinned a minute after the marker was written (r2.F3: an old one opens nothing)
        tapped_at = datetime.fromisoformat(TAPPED["at"])
        self.patch(mock.patch.object(gh_pulls, "clock", lambda: tapped_at + timedelta(minutes=1)))

    def patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_repo(self, key: str) -> Path:
        """`origin/<key>.git` (bare, one commit on main) and its clone `repos/<key>`, whose
        origin reads `https://github.com/octo/<key>.git`."""
        seed = helpers.make_repo(self.dir / "seed" / key)
        bare = self.dir / "origin" / f"{key}.git"
        bare.parent.mkdir(exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True)
        clone = self.dir / "repos" / key
        subprocess.run(["git", "clone", "-q", f"https://github.com/octo/{key}.git", str(clone)], check=True)
        return clone

    def gh(self, *rules: dict) -> None:
        """Put the stand-in gh on the path, answering these rules (the first match wins),
        then the two branch reads every plan answers."""
        script = self.bin / "gh"
        script.write_text(SCRIPT)
        script.chmod(0o755)
        self.plan_file.write_text(json.dumps([*rules, *BRANCH_READS]))

    def records(self) -> list[dict]:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def calls(self) -> list[list[str]]:
        """Every gh call but the two branch reads."""
        return [one["argv"] for one in self.records() if not about_branches(one["argv"])]

    def asked_about_branches(self) -> list[list[str]]:
        return [one["argv"] for one in self.records() if about_branches(one["argv"])]

    def git_calls(self, verb: str | None = None) -> list[list[str]]:
        """What git was run with, by the pack and by the test alike, without `-C <dir>` and
        `-c key=value`; only one subcommand when `verb` names it."""
        if not self.git_log.is_file():
            return []
        out = []
        for line in self.git_log.read_text().splitlines():
            argv = json.loads(line)
            while argv[:1] in (["-C"], ["-c"]):
                argv = argv[2:]
            if verb is None or argv[:1] == [verb]:
                out.append(argv)
        return out

    def forget_git(self) -> None:
        """Drop what git has been run with so far (the test's own setup)."""
        self.git_log.unlink(missing_ok=True)

    def card(self, **over) -> dict:
        base = {"id": "c-41", "space": "code", "title": "Tidy the loader", "brief": "Make it tidy.",
                "repo": "api", "stage": "building", "options": {}, "derived": {}}
        return {**base, **over}

    @staticmethod
    def tapped(card: dict) -> dict:
        """The card inside the user's tap: the marker the board keeps while Keel runs `publish`."""
        return {**card, "options": {**(card.get("options") or {}), "publishing": TAPPED}}

    def branch(self, name: str, pushed: bool = True, key: str = "api") -> Path:
        """A worktree of a repo on `name` with one commit, pushed to origin unless told not."""
        repo = self.cfg.spaces["code"].repos[key]
        tree = self.dir / "trees" / key / name.replace("/", "-")
        git(repo, "worktree", "add", "-q", "-b", name, str(tree), "origin/main")
        self.commit(tree, "change.txt")
        if pushed:
            git(tree, "push", "-q", "origin", name)
        return tree

    def commit(self, tree: Path, file: str = "more.txt") -> str:
        (tree / file).write_text(f"{file}\n")
        git(tree, "add", file)
        git(tree, "commit", "-q", "-m", f"add {file}")
        return git(tree, "rev-parse", "HEAD")

    def origin_head(self, branch: str, key: str = "api") -> str | None:
        """The commit the bare origin has at `branch`, or None when it has no such branch."""
        found = subprocess.run(["git", "-C", str(self.dir / "origin" / f"{key}.git"), "rev-parse", "--verify",
                                "--quiet", f"refs/heads/{branch}"], capture_output=True, text=True)
        return found.stdout.strip() or None

    def others_push(self, branch: str, rewrite: bool = False, key: str = "api") -> str:
        """Someone else pushes to `branch` from a clone of their own: one more commit, or the
        branch rewritten. The origin's new head."""
        other = self.dir / "other" / key
        if not other.exists():
            other.parent.mkdir(exist_ok=True)
            subprocess.run(["git", "clone", "-q", str(self.dir / "origin" / f"{key}.git"), str(other)], check=True)
        git(other, "fetch", "-q", "origin")
        git(other, "checkout", "-q", "-B", branch, f"origin/{branch}")
        if rewrite:
            git(other, "commit", "-q", "--amend", "-m", "rewritten elsewhere")
            git(other, "push", "-q", "--force", "origin", branch)
        else:
            (other / "theirs.txt").write_text("theirs\n")
            git(other, "add", "theirs.txt")
            git(other, "commit", "-q", "-m", "a colleague's commit")
            git(other, "push", "-q", "origin", branch)
        return self.origin_head(branch, key)
