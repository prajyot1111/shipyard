"""Personal publish: the human's Approve outcome merges the card's branch.

A work card's outcome is published by its adapter (the pull request goes to ready, the
merge is a colleague's). A personal repo card has no adapter and its outcome is a branch
in one of the human's own repos, so publishing it IS the merge, and the tap that approves
the outcome is the human's merge decision Q3 asks for. In order: the merge commit is built
in a temporary worktree on the target's head, the repo's test command (`[tests]` in
the config, by repo name) runs on THAT tree, and the live checkout takes it by `--ff-only`
(the section below says why); the worktree and the branch are removed; the merge sha is
what `approve` records. A repo with an integration branch (`[integration]`, c-526) lands
on THAT branch instead, by `update-ref` (the section on integration below). Any refusal (a dirty checkout, a red
suite, a conflict) raises `MergeRefused` with the reason and nothing is half done: a
failed merge is aborted before the error leaves this module.

The merge is LOCAL: nothing here pushes, and what `approve` records says so (c-665).
"""

import fcntl
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from keel import (atomicfile, bases, builder, cardtitle, childenv, packclones, repocommands, repolayout, settings,
                  stacking, trust, views)
from keel.config import Config, remote_of

GIT_SECONDS = 120


class MergeRefused(Exception):
    """The outcome could not be merged; the message is the reason for the card."""


def git(repo: Path, *args: str) -> str:
    """One git command in `repo`. Every way it can fail to answer is `MergeRefused`.

    A timeout included. `subprocess.run(timeout=...)` raises `TimeoutExpired`, which is a
    `SubprocessError` and NOT an `OSError`, so every caller that meant to catch "git could
    not answer" missed it: on a loaded box a `git rev-parse` past `GIT_SECONDS` came out of
    `code_head` through `drain.code_moved`, which `drain.run` calls outside its try, and
    ended the drain loop (2026-09-20, `<install>/history/docs/decisions.md`). Converting it here is the one
    place that makes it a refusal for every caller, rather than each of them remembering.
    """
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                                timeout=GIT_SECONDS, check=False, env=childenv.own_env())
    except subprocess.TimeoutExpired:
        raise MergeRefused(f"git {' '.join(args)}: no answer in {GIT_SECONDS}s") from None
    if result.returncode != 0:
        refused = MergeRefused(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip()}")
        refused.said = f"{result.stdout}\n{result.stderr}"    # both streams, for `conflicted`
        raise refused
    return result.stdout.strip()


def abort_merge(repo: Path) -> None:
    """Undo a half-done merge. A timeout is swallowed on purpose: the caller is already
    raising the refusal that says what happened, and it must not be replaced by this."""
    try:
        subprocess.run(["git", "-C", str(repo), "merge", "--abort"], capture_output=True,
                       timeout=GIT_SECONDS, check=False, env=childenv.own_env())
    except subprocess.TimeoutExpired:
        pass


def branch_of(card: dict, worktree: Path) -> str | None:
    """The worktree's checked-out branch when the worktree is there (the one fact that
    cannot be misspelt), else the branch the outcome names: `<branch>`, `<branch> @ <sha>`
    or `branch <branch> @ <sha>` (c-264 wrote the last form and the first word was taken
    for the branch), else None (nothing to merge). A house's card only: a card Bosun
    builds never asks its worktree (`bosun_branch`, c-647)."""
    if worktree.is_dir():
        try:
            head = git(worktree, "rev-parse", "--abbrev-ref", "HEAD")
        except MergeRefused:
            head = "HEAD"
        if head != "HEAD":
            return head
    return named_branch(card)


def named_branch(card: dict) -> str | None:
    """The branch (or sha) the outcome names: `<branch>`, `<branch> @ <sha>` or `branch
    <branch> @ <sha>`, else None (a URL, a path, nothing)."""
    ref = (card.get("output_ref") or "").strip()
    if not ref or ref.startswith(("http://", "https://", "/")):
        return None
    words = [w for w in ref.split() if w not in ("branch", "branch:", "@")]
    return words[0] if words else None


NO_BRANCH = ("{card}'s outcome names no branch of Bosun's to land ({named}); stage it with the "
             "branch: `kb stage {card} review --output <branch>`")


class NoBranch(MergeRefused):
    """The outcome of a card Bosun builds names no branch to land (`bosun_branch`)."""


def bosun_card(card: dict) -> bool:
    """A card Bosun builds, as the board says it (`derived.bosun`). Only a board's own card
    carries it (`Board.get` or `list_cards`, on a board opened with `open_board`, whose
    switches say whether Bosun builds at all): a bare dict, or a card of a board opened
    without them, reads as a house's."""
    return bool((card.get("derived") or {}).get("bosun"))


def bosun_branch(cfg: Config, card: dict, repo: Path, target: str) -> str:
    """The branch a card Bosun builds lands (c-647): the one its outcome names, and only
    when that word is a BRANCH where it is read from (`refs/heads/<name>` of Bosun's clone
    when the card's repo has one, else of the live repo). Never the card's worktree, which
    may be a house's leftover; never a bare sha, the target or the trunk (in any case), and never a
    revision spelt off a branch (`main~0`, `x^0`, `x@{0}`: `plain_branch`). Anything else
    is refused with what to do (`NO_BRANCH`)."""
    name = named_branch(card)
    clone = built_clone(cfg, card)
    place = built_source(cfg, clone) if clone is not None and clone.exists() else repo
    # Casefolded: on a case-insensitive volume `Main` resolves to `refs/heads/main`.
    kept = {target.casefold(), trunk_of(repo).casefold()}
    if (not name or name.casefold() in kept or name.startswith(("-", "refs/"))
            or not plain_branch(repo, name) or not has_ref(place, f"refs/heads/{name}")):
        named = repr(card.get("output_ref")) if card.get("output_ref") else "it names nothing"
        raise NoBranch(NO_BRANCH.format(card=card["id"], named=named))
    return name


def plain_branch(repo: Path, name: str) -> bool:
    """A word git takes as a branch NAME: `refs/heads/<name>` is a well-formed ref. A
    revision is not (`~`, `^`, `@{` and `:` are no part of a ref's name)."""
    try:
        git(repo, "check-ref-format", f"refs/heads/{name}")
    except MergeRefused:
        return False
    return True


def built_clone(cfg: Config, card: dict) -> Path | None:
    """Bosun's clone this card's branch is read and fetched from (`builder.clone_for`), or
    None: not a repo the builder builds, or a card he gave a house (`options.worker`), whose
    branch is in its worktree of the live repo like any house's (c-647). On an install this
    is `bosun_card` for a board's own card; a bare card with no worker reads as Bosun's."""
    if views.worker_of(card) == "house":
        return None
    return builder.clone_for(cfg, card)


def leftover_branch(card: dict, worktree: Path, landing: str) -> str | None:
    """The branch a house left checked out in the worktree of a card Bosun builds, when it
    is not the one landing; None for a house's card and for no such worktree."""
    if not bosun_card(card):
        return None
    left = branch_of({}, worktree)
    return left if left and left not in (landing, landing.removeprefix(BUILT_REFS)) else None


# THE TAP'S BUDGET (lane E round 4, finding 4). The deck waits `SLOW_SECONDS` (180) for its
# `kb approve`, and Keel's own suite takes about 420: the deck killed kb, the suite ran on
# orphaned, the `.landing` tree was left behind, and every retap started another. So the deck
# hands kb its budget in `KEEL_TAP_SECONDS` and the suite gets no longer than that: it runs in
# a process group of its own, killed WHOLE when the budget runs out, and `Outran` unwinds
# through `build_and_test`, which removes the tree. A terminal's `kb approve` has no budget.
TAP_ENV = "KEEL_TAP_SECONDS"
OUTRAN = ("the merged-tree tests of {card} ran longer than the deck waits ({seconds} s), so they "
          "were stopped and nothing was merged; to land it run `kb approve {card} outcome` in a "
          "terminal, which has no time limit, or switch on the merge queue ([keel] merge_queue = "
          "true) and approve again")
STILL_RUNNING = ("a test of {card}'s merged tree is still running, so this approve starts no "
                 "second one; wait for it, or run `kb approve {card} outcome` in a terminal once "
                 "it ends, or switch on the merge queue ([keel] merge_queue = true)")


class Outran(MergeRefused):
    """The suite ran past the tap's budget and was stopped; nothing was merged."""


def tap_budget() -> int | None:
    try:
        seconds = int(os.environ.get(TAP_ENV) or 0)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


# A red suite's failures, as `tests/parallel.py` prints them: unittest's own `FAIL:` and
# `ERROR:` lines, and a job's `<name>: exited <n> (...)` or "exited 0 but never printed".
FAILED_TEST = re.compile(r"^(?:FAIL|ERROR): (.+)$", re.MULTILINE)
FAILED_JOB = re.compile(r"^(\w+): (exited [1-9]\d*|exited 0 but never printed)", re.MULTILINE)
SUITE_LOG = "merged-tests.log"
NAMED = 10


def dotted_id(desc: str) -> str:
    """`test_x (tests.test_a.A.test_x)` as its dotted id; a bare module name as it is."""
    found = re.search(r"\(([\w.]+)\)$", desc.strip())
    return found.group(1) if found else desc.strip().split()[0]


def failures(text: str) -> tuple[list[str], list[str]]:
    """`(tests, jobs)` a suite's output names as failed: each test's dotted id, and each
    job as `<name>: exited <n>`, in order, once each."""
    tests = [dotted_id(desc) for desc in FAILED_TEST.findall(text or "") if desc.strip()]
    jobs = [f"{name}: {how}" for name, how in FAILED_JOB.findall(text or "")]
    return list(dict.fromkeys(tests)), list(dict.fromkeys(jobs))


def failed_line(text: str, log: Path | None) -> str:
    """What a red suite's refusal says on its FIRST line, which is what the card's block,
    its note and the CLI's one line all carry (c-535: a 15 line tail named no test)."""
    tests, jobs = failures(text)
    named = tests + jobs
    said = ", ".join(named[:NAMED]) + (f" and {len(named) - NAMED} more" if len(named) > NAMED else "")
    where = f"; the whole output is in {log}" if log else ""
    return f"failed: {said or 'none named'}{where}"


def keep_output(log: Path | None, out: str) -> Path | None:
    """The suite's whole output in `log`, or None when there is nowhere to keep it."""
    if log is None:
        return None
    try:
        atomicfile.write_text(log, out)
    except OSError:
        return None
    return log


def run_tests(command: str, tree: Path, base: str = "", log: Path | None = None,
              seconds: float = settings.default("keel", "merge_test_seconds")) -> str:
    """The repo's own suite, on the MERGED tree, in its own process group; `{base}` in the
    command is the commit the merge was built on (`make test BASE={base}`, c-646). A suite
    that runs past `seconds` (`[keel] merge_test_seconds`, c-633) is a refusal like a red
    one; one that outruns the tap's budget is `Outran`. Its whole output is kept in `log`
    (the card's `merged-tests.log`), and a red one's refusal names the failed tests and jobs
    on its first line."""
    where = f"on the merged tree (your branch merged onto {base[:8]})" if base else "in the worktree"
    command = command.replace("{base}", base) if base else command
    budget = tap_budget()
    limit = min(seconds, budget) if budget else seconds
    proc = subprocess.Popen(command, shell=True, cwd=str(tree), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                            errors="replace", start_new_session=True,
                            # THE SUITE IS THE HOUSE'S OWN CODE, and it runs inside the kb the
                            # deck ran for his Approve, which holds his token (c-451, round 3).
                            env=childenv.own_env())
    try:
        out, _ = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        kill_suite(proc)
        if budget and limit == budget:
            raise Outran(f"the tests ran past the tap's {budget} s") from None
        raise MergeRefused(f"the tests did not finish in {seconds}s (`{command}`) {where}; "
                           f"nothing was merged") from None
    kept = keep_output(log, out or "")
    if proc.returncode != 0:
        tail = "\n".join((out or "").strip().splitlines()[-15:])
        raise MergeRefused(f"tests failed {where} (`{command}` exited "
                           f"{proc.returncode}); nothing was merged; {failed_line(out, kept)}\n{tail}")
    return out or ""


# ----- trees already tested (2026-09-26): a deploy of one skips its suite -----
# A landing on the integration branch tests the exact tree it lands (the merge commit's
# tree): `make test`, the core suite and what the change reaches (c-646). Only a run of
# every module with the voice selftest passing proves the tree the deploy would test (the
# deploy runs `make test-all`, voice included), so only such a run is recorded here: a
# narrow `make test` never is, and neither is one where the selector fell back to
# everything but the repo has no venv. When a deploy would make live that SAME tree (git's
# tree id), running the suite again proves nothing.
VENV = ".venv-voice"
VOICE_PASSED = re.compile(r"^voice: [0-9.]+s, exit 0$", re.MULTILINE)
# The Makefile's own skip note, at the start of a line (the runner's echoed command also holds
# the words, as its --done pattern). The skip exits 0, so its job still says `exit 0`.
VOICE_SKIP_LINE = re.compile(r"^voice selftest: skipped", re.MULTILINE)
# `tests/selector.py` says this on its own line when nothing the change touched reaches the
# voice selftest (its VOICE_UNREACHED): the run did not include it.
VOICE_UNREACHED = re.compile(r"^voice selftest: not run, ", re.MULTILINE)
# ...and this when it chose its modules (its SELECTED): the run was not every module.
NARROW = re.compile(r"^running \d+ test module\(s\):$", re.MULTILINE)


def voice_passed(out: str) -> bool:
    """The run's voice job said `exit 0` and the selftest did not skip: it ran, green."""
    return bool(VOICE_PASSED.search(out)) and not VOICE_SKIP_LINE.search(out)


def ran_whole(out: str) -> bool:
    """The run was every module with the voice selftest passing: what a deploy runs."""
    return voice_passed(out) and not NARROW.search(out)
TESTED_FILE = "tested-trees.json"
TESTED_KEEP = 100


def link_venv(repo: Path, tree: Path) -> bool:
    """The live checkout's voice venv linked into a temporary tree, so its suite runs voice."""
    venv = repo / VENV
    # executable, as the Makefile's `voice-test` asks (`-x`), or the selftest would skip
    if not os.access(venv / "bin" / "python", os.X_OK) or (tree / VENV).exists():
        return False
    (tree / VENV).symlink_to(venv.resolve(), target_is_directory=True)
    exclude_link(tree)
    return True


def exclude_link(tree: Path) -> None:
    """The link is never a change to commit, whatever the repo's .gitignore says: git's own
    exclude list (shared by every worktree of the repo) names it."""
    try:
        path = Path(git(tree, "rev-parse", "--git-path", "info/exclude"))
    except MergeRefused:
        return
    path = path if path.is_absolute() else tree / path
    have = path.read_text() if path.exists() else ""
    if VENV not in have.split():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(have + ("" if not have or have.endswith("\n") else "\n") + VENV + "\n")


def tree_of(repo: Path, commit: str) -> str:
    return git(repo, "rev-parse", f"{commit}^{{tree}}")


def record_tested(cfg: Config, tree_id: str, card_id: str) -> None:
    path = Path(cfg.state_dir) / TESTED_FILE
    try:
        rows = json.loads(path.read_text())
    except (OSError, ValueError):
        rows = []
    rows = [row for row in rows if row.get("tree") != tree_id][-(TESTED_KEEP - 1):]
    rows.append({"tree": tree_id, "card": card_id,
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    atomicfile.write_text(path, json.dumps(rows, indent=1) + "\n")


def tested_whole(cfg: Config, tree_id: str) -> dict | None:
    """Who ran every module on this exact tree green, voice included (a landing whose run
    was `make test-all`, or `kb tested`), or None."""
    try:
        rows = json.loads((Path(cfg.state_dir) / TESTED_FILE).read_text())
    except (OSError, ValueError):
        return None
    return next((row for row in reversed(rows) if row.get("tree") == tree_id), None)


SUITE_GRACE = 2.0


def kill_suite(proc: subprocess.Popen) -> None:
    """End the suite's WHOLE process group, addressed by the leader's pid (it leads its own
    session), so a leader that has already exited cannot hide its children: SIGTERM, a
    grace, then SIGKILL, reaping the leader as it goes. Never raises."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        deadline = time.time() + SUITE_GRACE
        while time.time() < deadline:
            proc.poll()
            try:
                os.killpg(proc.pid, 0)
            except (ProcessLookupError, PermissionError):
                break
            time.sleep(0.05)
        else:
            continue
        break
    try:
        proc.communicate(timeout=SUITE_GRACE)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass


@contextmanager
def approve_lock(cfg: Config, card_id: str):
    """Held while an Approve outcome tests and lands this card; a second one is refused
    rather than started beside it."""
    path = cfg.state_dir / "locks" / f"approve-{card_id}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MergeRefused(STILL_RUNNING.format(card=card_id)) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# ----- the merged tree: built beside, tested, then landed by fast-forward -----
#
# c-298: the suite used to run on the BRANCH as it was, and the merge then landed a tree
# nobody had tested. Now the merge commit is built in a temporary worktree (detached at the
# target's head), the suite runs on exactly that tree, and the live checkout takes it with
# `--ff-only`, which is the compare-and-swap: a target that moved while the suite ran
# refuses the fast-forward, and the whole thing is built again on the new head, once. The
# card's own branch and worktree are never touched by the trial.

CONFLICT = ("merge conflict: {target} moved past {branch} and the two disagree; the house "
            "has to merge {target} into its branch first")
# Not a "merge conflict": no house can answer it, so it blocks the card for him.
TRUNK_CONFLICT = ("{trunk} has commits that conflict with {target}, so nothing can land on "
                  "{target} until {trunk} is merged into it by hand")
# c-621: any other failure of the merge (no committer identity, a hook, a lock) is no
# conflict: a house that merges main changes nothing, so the card stays for him with git's
# own words, and the drain never sends it back to building.
NOT_CONFLICT = "the merge of {branch} onto {target} failed, not on a conflict, so nothing was merged; git said: {said}"
ATTEMPTS = 2


def conflicted(tree: Path, error: MergeRefused) -> bool:
    """Whether a failed merge in `tree` is a real conflict: git reported CONFLICT, or left
    unmerged paths. Asked before `abort_merge`, which clears both."""
    if "CONFLICT" in getattr(error, "said", str(error)):
        return True
    try:
        return bool(git(tree, "ls-files", "--unmerged"))
    except MergeRefused:
        return False


def not_conflict(error: MergeRefused, branch: str, target: str) -> MergeRefused:
    """The landing error for a merge that failed some other way, with git's first lines."""
    text = getattr(error, "said", str(error))
    said = "; ".join([line.strip() for line in text.splitlines() if line.strip()][:5])
    return MergeRefused(NOT_CONFLICT.format(branch=branch, target=target, said=said or "nothing"))


def trial_path(cfg: Config, card_id: str) -> Path:
    """Where the merged tree is built: beside the card's worktree, never inside it."""
    return cfg.worktrees_dir / f"{card_id}.landing"


def drop_tree(repo: Path, tree: Path) -> None:
    """Remove the temporary worktree, whatever state it is in. Never raises."""
    for args in (("worktree", "remove", "--force", str(tree)), ("worktree", "prune")):
        try:
            subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                           timeout=GIT_SECONDS, check=False, env=childenv.own_env())
        except subprocess.TimeoutExpired:
            pass


# The card's title in a merge subject, cut at a word (c-729): a card filed with a paragraph
# for a title never puts the paragraph on main.
SUBJECT_TITLE = 72


def merge_message(card: dict, branch: str) -> str:
    title = cardtitle.cut(card.get("title") or "", SUBJECT_TITLE) or card["id"]
    return f"Merge {branch}: {title} ({card['id']})"


def build_and_test(cfg: Config, card: dict, repo: Path, branch: str, base: str,
                   target: str, command: str | None, source: str | None = None,
                   trunk: tuple[str, str] | None = None) -> str:
    """The merge commit of `branch` onto `base`, built in a temporary worktree, with the
    repo's suite run on that exact tree. Returns its sha; `MergeRefused` on a conflict, a
    merge git refused some other way (`NOT_CONFLICT`, never sent to the house), or a red
    suite. The temporary worktree is gone when this returns, either way.

    `trunk` is `(name, sha)` of the branch the checkout runs, to merge in FIRST when the
    target is an integration branch that lacks it (his own commits to main): the suite then
    runs on what the integration branch will be, and a later deploy is a fast-forward. A
    conflict names both when the trunk was merged in, so the house takes his commits to main
    as well and the next landing is clean (review 2, F3 and F4)."""
    tree = trial_path(cfg, card["id"])
    drop_tree(repo, tree)
    tree.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", str(tree), base)
    try:
        target_ref, trunk_ref = target, trunk[0] if trunk else None
        conflict_refs = target_ref
        if trunk is not None and not ancestor(repo, trunk[1], base):
            conflict_refs = f"{target_ref},{trunk_ref}"
            try:
                git(tree, "merge", "--no-ff", trunk[1], "-m", f"Merge {trunk[0]} into {target}")
            except MergeRefused as error:
                real = conflicted(tree, error)
                abort_merge(tree)
                if not real:
                    raise not_conflict(error, trunk[0], target) from error
                raise MergeRefused(TRUNK_CONFLICT.format(trunk=trunk[0], target=target)) from error
        try:
            # `source` is the sha a queued approve pinned: the merge takes THAT commit, never
            # whatever the branch name points at by now (round 3, finding 1).
            git(tree, "merge", "--no-ff", source or branch, "-m", merge_message(card, branch))
        except MergeRefused as error:
            real = conflicted(tree, error)
            abort_merge(tree)
            if not real:
                raise not_conflict(error, branch, target) from error
            raise MergeRefused(CONFLICT.format(target=conflict_refs, branch=branch)) from error
        merged = git(tree, "rev-parse", "HEAD")
        if command:
            prepare_merged(cfg, card, tree)
            voiced = trunk is not None and link_venv(repo, tree)
            out = run_tests(command, tree, base, log=cfg.card_dir(card["id"]) / SUITE_LOG,
                            seconds=cfg.merge_test_seconds)
            if voiced and ran_whole(out):
                record_tested(cfg, tree_of(repo, merged), card["id"])
        return merged
    finally:
        drop_tree(repo, tree)


def prepare_merged(cfg: Config, card: dict, tree: Path) -> None:
    """The repo's prepare command in the merged tree, before its tests (c-678): the tree is a
    fresh worktree, so what a session's own copy got when it was cut, this one needs too."""
    command = repocommands.prepare_of(cfg, card.get("space"), card.get("repo"))
    if not command:
        return
    # inside the tap's budget, as the suite is (review F5): a prepare that outruns it is
    # stopped with its whole process group and the tap is answered, not left waiting
    budget = tap_budget()
    limit = min(repocommands.PREPARE_SECONDS, budget) if budget else repocommands.PREPARE_SECONDS
    try:
        repocommands.prepare(command, tree, limit)
    except repocommands.PrepareTimedOut as failed:
        if budget and limit == budget:
            raise Outran(f"preparing the merged tree ran past the tap's {budget} s") from None
        raise MergeRefused(f"the merged tree could not be prepared, so its tests did not run and "
                           f"nothing was merged: {failed}") from None
    except repocommands.PrepareFailed as failed:
        raise MergeRefused(f"the merged tree could not be prepared, so its tests did not run and "
                           f"nothing was merged: {failed}") from None


def base_of(repo: Path, target: str) -> str:
    """The commit the merge is built on: the target's head."""
    return git(repo, "rev-parse", target)


IGNORED_SHOWN = 5       # how many files a refusal names before it counts the rest
TREE_ID = re.compile(r"^[0-9a-f]{40,64}$")


def merged_tree(repo: Path, base: str, tip: str) -> str | None:
    """The tree a merge of `tip` into `base` would write, computed without touching the
    checkout, the index or any ref (`git merge-tree --write-tree`); None when it cannot be
    known here: a conflict, a git too old for it, or no answer (c-740 r2.D1)."""
    try:
        first = (git(repo, "merge-tree", "--write-tree", base, tip).splitlines() or [""])[0].strip()
    except MergeRefused:
        return None
    return first if TREE_ID.match(first) else None


def ignored_in_the_way(repo: Path, base: str, tip: str) -> list[str]:
    """The files `tip` adds since `base` that the checkout at `repo` holds as ignored files:
    what a fast-forward would write over (c-740 r2.F2). Git is asked only about the added
    paths, so a checkout full of ignored build output is not listed."""
    # r2.D2: no rename detection, or a file renamed onto an ignored path is not an add
    added = [path for path in git(repo, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=A",
                                  base, tip).split("\0") if path]
    held: list[str] = []
    for start in range(0, len(added), 200):
        specs = [f":(literal){path}" for path in added[start:start + 200]]
        out = git(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", *specs)
        held += [path for path in out.split("\0") if path]
    return sorted(held)


def refuse_ignored(repo: Path, base: str, tip: str) -> None:
    """A landing that would write over ignored files in the live checkout is refused in plain
    words: which files, where, that nothing was merged, and what to do. The fast-forward's
    `--no-overwrite-ignore` is the mechanism; this says it before git would, and before the
    suite where the caller knows the tip."""
    held = ignored_in_the_way(repo, base, tip)
    if not held:
        return
    shown = ", ".join(held[:IGNORED_SHOWN])
    more = f" and {len(held) - IGNORED_SHOWN} more" if len(held) > IGNORED_SHOWN else ""
    raise MergeRefused(f"{repo} holds ignored files this change would write over: {shown}{more}. "
                       f"Nothing was merged. Move or delete them there, then approve again.")


def settle(repo: Path, target: str, base: str, merged: str) -> bool:
    """Land `merged` if the target is still at `base`: True when it landed, False when the
    target moved (the caller builds again). The fast-forward IS the check."""
    if git(repo, "rev-parse", target) != base:
        return False
    refuse_ignored(repo, base, merged)
    try:
        # r1.F2 of c-740: an ignored file in the checkout is the user's, never the merge's to write over
        git(repo, "merge", "--ff-only", "--quiet", "--no-overwrite-ignore", merged)
    except MergeRefused:
        if git(repo, "rev-parse", target) != base:
            return False
        raise
    return True


# ----- the integration branch (c-526) -----
#
# For a repo where merging is deploying, the approved outcome lands on an integration branch
# (`[integration]`, `next` for Keel) that nothing has checked out, so it moves by
# `git update-ref <ref> <new> <old>`: the compare and swap `--ff-only` is for main. The
# branch is created at the trunk's head the first time anything lands on it, and the trunk's
# own commits (his direct commits to main) are merged in before the card's branch, so the
# integration branch always contains the trunk and his deploy is a fast-forward.

ZERO = "0" * 40


def trunk_of(repo: Path) -> str:
    """The branch the repo's checkout has out: what the machine runs."""
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def ancestor(repo: Path, older: str, newer: str) -> bool:
    try:
        done = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer],
                              capture_output=True, timeout=GIT_SECONDS, env=childenv.own_env())
    except subprocess.TimeoutExpired:
        raise MergeRefused(f"git merge-base: no answer in {GIT_SECONDS}s") from None
    return done.returncode == 0


def ref_head(repo: Path, ref: str) -> str | None:
    """The sha a branch is at here, or None when it does not exist."""
    return git(repo, "rev-parse", f"refs/heads/{ref}") if has_ref(repo, f"refs/heads/{ref}") else None


def integration_base(repo: Path, target: str, trunk: str) -> tuple:
    """`(base, old, trunk_head)`: the commit the merge is built on (the integration branch's
    head, or the trunk's while it does not exist yet), the value the swap expects (None:
    must not exist), and the trunk's head to merge in when the branch lacks it."""
    trunk_head = git(repo, "rev-parse", trunk)
    old = ref_head(repo, target)
    return old or trunk_head, old, trunk_head


def settle_integration(repo: Path, target: str, old: str | None, merged: str) -> bool:
    """Move the integration branch to `merged` if it is still at `old`: True when it moved,
    False when it moved meanwhile (the caller builds again)."""
    try:
        git(repo, "update-ref", f"refs/heads/{target}", merged, old or ZERO)
    except MergeRefused:
        if ref_head(repo, target) != old:
            return False
        raise
    return True


NOT_RUN = "not run"         # a pre-run's result when Keel could not know what to test


class FileChanged(MergeRefused):
    """Nothing was built: the repo's own CLAUDE.md, which the test command would have come
    from, changed since the user adopted or saved it (`repocommands.landing`)."""


def test_command(cfg: Config, card: dict) -> str | None:
    """The command a landing of `card` runs on the merged tree, from ONE reading of the
    repo's file (`repocommands.landing`), or `FileChanged` where that reading refuses the
    landing: the command and the refusal cannot disagree (c-678 fix check r2.D2)."""
    command, refused = repocommands.landing(cfg, card.get("space"), card.get("repo"))
    if refused:
        raise FileChanged(repocommands.REFUSED.format(name=repocommands.first(card.get("repo"))))
    return command


def land(cfg: Config, card: dict, repo: Path, branch: str, target: str,
         source: str | None = None, guard=None) -> str:
    """Build, test and land the merged tree; the landed sha. Built again once when the
    target moved while the suite ran; a second move is a refusal. `source` (a pinned sha)
    is what is merged on every attempt; `guard()` is asked right before the fast-forward and
    a reason from it lands nothing."""
    command = test_command(cfg, card)       # before any tree is built; `FileChanged` lands nothing
    trunk = trunk_of(repo)
    for _ in range(ATTEMPTS):
        base, old, rest = footing(cfg, card, repo, target, trunk)
        # r2.F2: said before the suite is paid for, as `settle` would. r2.D1: against the tree the
        # merge would write, never the branch's tip, which a branch behind its target differs
        # from in every path the target changed since; where that tree cannot be known yet,
        # nothing is asked here and the exact checks below and in `settle` answer.
        would = merged_tree(repo, base, source or branch) if target == trunk else None
        if would:
            refuse_cloned_pack(cfg, repo, base, would)      # first: it names the repo to use
            refuse_ignored(repo, base, would)
        merged = build_and_test(cfg, card, repo, branch, base, target, command, source=source, **rest)
        why = guard() if guard else None
        if why:
            raise MergeRefused(f"not landed: {why}")
        refuse_cloned_pack(cfg, repo, base, merged)
        settled =(settle_integration(repo, target, old, merged) if target != trunk
                   else settle(repo, target, base, merged))
        if settled:
            return merged
    raise MergeRefused(f"{target} moved twice while the tests ran; nothing was merged, "
                       f"approve again")


def refuse_cloned_pack(cfg: Config, repo: Path, base: str, merged: str) -> None:
    """A landing into the install's packs repo that changes any path under a folder with a
    repo of its own (`packclones.nested`, c-740 r1.F2) is refused, naming the repo to use: the
    packs repo ignores a cloned pack, and git writes over an ignored file without asking."""
    home = cfg.install_home
    if not home or not builder.same(repo, home / builder.PACKS):
        return
    clones = packclones.nested(repo)
    if not clones:
        return
    # r2.F4: names are compared case-folded, since `Team/x` lands in `team/` on a disk that folds case
    touched = {path.split("/", 1)[0].casefold()
               for path in git(repo, "diff", "--name-only", "-z", base, merged).split("\0") if path}
    for name in clones:
        if name.casefold() in touched:
            raise MergeRefused(f"this change touches {name}/ in the packs repo, and {name} is a pack with "
                               f"a repo of its own; nothing was merged. Build it as a card on the repo "
                               f"{packclones.KEY}{name}, which lands in the pack's own repo")


def footing(cfg: Config, card: dict, repo: Path, target: str, trunk: str) -> tuple:
    """`(base, old, rest)` of a merge into `target`: the commit it is built on, the value the
    swap expects, and `build_and_test`'s extra arguments. The trunk lands as it always did;
    a card's own base that the checkout does not have out (c-732) lands plainly on that
    branch, built on it (or on the remote's, while the copy has none of its own) with nothing
    else merged in, and so does the repo's usual branch when the copy has another out (c-734,
    `usual_branch`); the repo's integration branch takes `integration_base`."""
    if target == trunk:
        base = base_of(repo, target)
        return base, base, {}
    if cfg.integration_of(card.get("space"), card.get("repo")) == target:
        base, old, trunk_head = integration_base(repo, target, trunk)
        return base, old, {"trunk": (trunk, trunk_head)}
    where = checked_out(repo, target)
    if where:
        raise MergeRefused(f"{target} is checked out in {where}, so Shipyard does not move it under that "
                           f"working tree and nothing was merged. Check out another branch there, then "
                           f"approve again.")
    old = ref_head(repo, target)
    theirs = f"refs/remotes/{remote_of(cfg, card.get('space'))}/{target}"
    if old is None and not has_ref(repo, theirs):
        whose = "this card's base" if card_base(cfg, card) == target else "the repo's usual branch"
        raise MergeRefused(f"{target}, {whose}, is not a branch of {repo.name} on this computer, "
                           f"so nothing was merged")
    return old or git(repo, "rev-parse", theirs), old, {}


def checked_out(repo: Path, branch: str) -> str | None:
    """The working tree that has `branch` out, the copy's own or any linked one (`git worktree
    list --porcelain`), or None. A branch out in a working tree is never moved by `update-ref`
    under it (c-732 r1.F9)."""
    path = None
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}":
            return path
    return None


def own_base(card: dict) -> str | None:
    """The base a card names itself (`options.base`, c-732), or None: the space's own rule
    applies (the integration branch, else the checkout's branch)."""
    return str((card.get("options") or {}).get("base") or "").strip() or None


def card_base(cfg: Config, card: dict, key: str | None = None) -> str | None:
    """The base a card is cut from and lands on by its own word, or None. Never on a repo
    whose cards land on an integration branch (c-732 r1.F4): that branch is config, never a
    card field, so `options.base` there is ignored and the integration rule applies (the
    board refuses it at create and at set; this is the protection beneath that, and beneath
    Bosun's own outcome check)."""
    base = own_base(card)
    if base and cfg.integration_of(card.get("space"), key or card.get("repo")):
        return None
    return base


CUT_FROM = "cut_from"      # options.cut_from: {repo key: the usual branch a card was cut from}


def cut_from(card: dict, key: str | None) -> str | None:
    """The usual branch the card's worktree for `key` was cut from (r2.F1,
    `adapters.cut_point`), or None for a card cut before it was recorded, and for a name that
    is not a branch name by the bases' own rule (r2.D1, `bases.branch_problem`): the board lets
    only the drain write it, and this is the check beneath that."""
    found = ((card.get("options") or {}).get(CUT_FROM) or {})
    name = found.get(key or "") if isinstance(found, dict) else None
    name = name.strip() if isinstance(name, str) else ""
    return name if name and bases.branch_problem(name) is None else None


def base_in(cfg: Config, card: dict, key: str | None = None) -> str | None:
    """THE base of a card in one of its repos (c-772): `key`, else its first. One rule, for
    every reader that takes a card's change against a branch (`house.target_of`, `keel check`,
    the shipping pass for a repo that is not the card's first, the brief's and a fresh start's
    words). In order: the stacked base in that repo (`stacking.base_of`: the parent's branch,
    and after it lands the base it merged into, only in a repo the parent names), the card's
    own base (`card_base`), the repo's integration branch, the branch its worktree was cut
    from (`cut_from`), the repo's usual branch (`usual_branch`). None when none of them
    answers (a repo the space cannot place, a checkout git cannot read): never a guess, and
    never another repo's base."""
    repos = [one.strip() for one in str(card.get("repo") or "").split(",") if one.strip()]
    key = key or (repos[0] if repos else None)
    base = stacking.base_of(card, key) or card_base(cfg, card, key)
    if base:
        return str(base)
    try:
        integration = integration_ref(cfg, card.get("space"), key)
    except MergeRefused:
        integration = None       # an unread ref is never named: the checkout's branch below,
        #                          and the stage check refuses until the remote answers
    if integration:
        return integration
    cut = cut_from(card, key)       # r2.F1: where it was cut, whatever the default is now
    if cut:                         # (r2.D1: a name that is not a branch name is not read)
        return cut
    space = cfg.spaces.get(card.get("space") or "")
    path = space.repo_path(key) if space is not None and key else None
    try:
        return usual_branch(cfg, card.get("space"), path) if path else None
    except (MergeRefused, OSError):
        return None


def landing_target(cfg: Config, card: dict, repo: Path) -> str:
    """Where a card in a space with no pack lands: its repo's integration branch, else its own
    base, else the branch it was cut from (`cut_from`, r2.F1: a team that moves its default
    after the cut never has this card land on the new one with the old one's history), else
    the repo's usual branch (`usual_branch`)."""
    return (cfg.integration_of(card["space"], card["repo"]) or card_base(cfg, card)
            or cut_from(card, card.get("repo")) or usual_branch(cfg, card.get("space"), repo))


def remote_default(repo: Path, remote: str) -> str | None:
    """The branch the remote names as its default (`refs/remotes/<remote>/HEAD`, which a clone
    sets), or None when the copy holds no such ref, or one that names a branch the remote no
    longer has (r1.F4: a dangling symref is never trusted). Fetch before work refreshes it
    (`landpush.fetch_first`, `git remote set-head <remote> --auto`), so a team that changes its
    default is followed."""
    try:
        found = git(repo, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
    except MergeRefused:
        return None
    name = found[len(remote) + 1:] if found.startswith(f"{remote}/") else ""
    if not name or name.startswith("-") or name == "HEAD":
        return None
    return name if has_ref(repo, f"refs/remotes/{remote}/{name}") else None


def usual_branch(cfg: Config, space_name: str | None, repo: Path) -> str:
    """Where a card naming no base starts and lands, on a repo with no integration branch
    (c-734): for a repo the install copied, the remote's default branch, never whichever branch
    the copy has out (an Adopt before c-734 switched it, and a stray checkout can); else the
    branch the checkout has out, as it always was, since a checkout of the user's own is the
    user's to point. A copy whose remote names no default falls back to its checkout too."""
    if repolayout.home_of(repo, repolayout.spaces_of(cfg)) is not None:
        found = remote_default(repo, remote_of(cfg, space_name))
        if found:
            return found
    return trunk_of(repo)


def has_ref(repo: Path, ref: str) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except MergeRefused:
        return False
    return True


# r-24: what Approve outcome records on a card it closes without landing.
NOTHING_TO_LAND = "nothing to land: the outcome is its record"
RESEARCH = "research"


def placed(cfg: Config, card: dict, fetch: bool = False) -> tuple | None:
    """`(space, repo, worktree, branch, target)` for a card with something to merge here,
    None when there is nothing (no repo, an adapter's space, no branch, already on it, a
    research card, or a branch that adds nothing to its target: `nothing_to_land`)."""
    if is_research(card):
        return None
    found = branch_placed(cfg, card, fetch)
    if found is None or ancestor(found[1], found[3], found[4]):
        return None
    return found


def built_source(cfg: Config, clone: Path) -> Path:
    """Bosun's clone as the landing may read it (`builder.real_clone`), or the refusal."""
    source = builder.real_clone(cfg, clone)
    if source is None:
        raise MergeRefused(f"{clone} is not a real clone under {builder.clones(cfg)} (a link or a "
                           f"gitfile), so nothing is fetched from it")
    return source


def is_research(card: dict) -> bool:
    return (card.get("options") or {}).get("kind") == RESEARCH


def nothing_to_land(cfg: Config, card: dict, fetch: bool = False) -> bool:
    """Approve outcome closes this card as done with `NOTHING_TO_LAND` and no pretest, merge
    or suite (r-24): a research card, whose outcome is its findings, or one whose branch has
    no commit its target lacks. A branch that cannot be read here is not "nothing": it
    takes the landing path, which says why. `fetch` is `branch_placed`'s: the user's tap
    asks with it (`landing.route`'s `tap`; `publish` reads the same way), and so does the
    superbuilder's own approval (`authority.outcome_facts`)."""
    if is_research(card):
        return True
    try:
        found = branch_placed(cfg, card, fetch)
        return found is not None and ancestor(found[1], found[3], found[4])
    except MergeRefused:
        return False


def branch_placed(cfg: Config, card: dict, fetch: bool = False) -> tuple | None:
    """`placed` before its nothing-to-land check: where the card's branch is, and its target.
    `fetch` is an Approve outcome reading it: the user's (`landing.route`'s `tap` and
    `publish`, which may find nothing to land, c-773; `branch_head`, `land_card`), or the
    superbuilder's own in bypass (`authority.outcome_facts`). Only then is the builder's
    branch fetched from its clone (c-619). Before it, such a branch is not here, and nothing
    reads, pre-runs or tests it.

    Which branch: a house's card lands its worktree's (`branch_of`); a card Bosun builds
    lands the one its outcome names, or is refused (`bosun_branch`, c-647). `card` is the
    board's own (`bosun_card`)."""
    space = cfg.spaces.get(card["space"])
    if space is None or space.adapter_dir is not None or not card.get("repo"):
        return None
    worktree = repolayout.card_tree(cfg, card)
    branch = None if bosun_card(card) else branch_of(card, worktree)
    if not branch and not bosun_card(card):
        return None
    # A listed repo, or a project discovered under the space's `projects_dir`: a card that
    # opened a new project merges by the same tap as any other (`Space.repo_path`).
    repo = space.repo_path(card["repo"])
    if repo is None or not (repo / ".git").exists():
        raise MergeRefused(f"repo {card['repo']!r} is not a repository of the {space.name} space")
    target = landing_target(cfg, card, repo)
    if branch == target:
        return None
    if built_clone(cfg, card) is not None and not fetch:
        raise MergeRefused(f"{card['id']} is the in-app builder's: its branch is read only "
                           f"when the user's Approve outcome lands it")
    if bosun_card(card):
        branch = bosun_branch(cfg, card, repo, target)
    if built_clone(cfg, card) is not None:
        branch = fetch_built(cfg, card, repo, branch, target) or branch
    if not has_ref(repo, branch):
        # c-306: a card whose house ran on the other machine. Its branch is not here, and
        # "main moved" (what a failed merge used to say) sent the house to merge a main
        # that had not moved at all.
        raise MergeRefused(f"{branch} is not in {repo} on this machine: the house built it "
                           f"elsewhere, so it lands on the machine that holds its worktree")
    return space, repo, worktree, branch, target


BUILT_REFS = "refs/builder/"


def fetch_built(cfg: Config, card: dict, repo: Path, branch: str, target: str) -> str | None:
    """The in-app builder's card (c-619): its branch is in Bosun's own clone
    (`builder.clone_for`), which the sandbox lets it write, and never in the live repo. So
    the branch is fetched from there, as this process's user, into a ref of its own
    (`refs/builder/<branch>`), and the merge takes that ref: nothing under `refs/heads` of
    the live repo is ever written by the fetch. Only from a real clone under
    `<install>/builder` (`builder.real_clone`). The ref merged, or None (not its card)."""
    clone = built_clone(cfg, card)
    if clone is None or not clone.exists():
        return None
    source = built_source(cfg, clone)
    if branch in (target, trunk_of(repo)) or branch.startswith(("-", "refs/")):
        raise MergeRefused(f"{branch} is not a branch of Bosun's own: its work lands from one, by a merge")
    git(repo, "check-ref-format", "--branch", branch)
    ref = BUILT_REFS + branch
    git(repo, "fetch", "--quiet", "--no-tags", str(source), f"+refs/heads/{branch}:{ref}")
    return ref


def integration_ref(cfg: Config, space_name: str | None, repo_key: str | None) -> str | None:
    """The ref a card's review base, rebase and stage check read for its integration branch,
    fresh (review F4): `next`; None when the repo has none, or nothing has landed on it yet
    (the card is then based on the trunk, which is the checkout's branch)."""
    target = cfg.integration_of(space_name, repo_key)
    space = cfg.spaces.get(space_name or "")
    repo = space.repo_path(str(repo_key).split(",")[0].strip()) if target and space else None
    if repo is None or not (repo / ".git").exists():
        return target
    return target if ref_head(repo, target) else None


def target_head(repo: Path, target: str) -> str:
    """The target's head here: an integration branch not created yet reads as the trunk's."""
    return ref_head(repo, target) or git(repo, "rev-parse", "HEAD")


def branch_head(cfg: Config, card: dict) -> str | None:
    """The full sha the card's branch is at on this machine, or None when there is nothing
    to merge. What a `land` relay pins, so the tree that lands is the one he approved."""
    found = placed(cfg, card, fetch=True)      # his Approve pins it (c-619)
    if found is None:
        return None
    _, repo, _, branch, _ = found
    return git(repo, "rev-parse", branch)


def publish(cfg: Config, card: dict) -> str | dict | None:
    """Merge the card's branch into its repo, or None when the card has nothing to merge
    (no repo, a space with an adapter, or an outcome that is not a branch). A card with
    nothing to land answers `{"published": "nothing", "note": ...}`, which the board records
    on the approve (r-24). It is the user's tap, so a builder's branch is read from its clone
    here as the landing reads it (c-773): one that already landed under another card closes
    as nothing to land. It is read once: the close and the landing take that answer, and a
    branch that cannot be read is refused here with the reason (`nothing_to_land`'s rule)."""
    found = None if is_research(card) else branch_placed(cfg, card, fetch=True)
    if is_research(card) or (found is not None and ancestor(found[1], found[3], found[4])):
        notes = close_unlanded(cfg, card, found)
        return {"published": "nothing", "note": "; ".join([NOTHING_TO_LAND, *notes])}
    landed = land_card(cfg, card, found=found) if found is not None else None
    return landed["published"] if landed else None


def land_card(cfg: Config, card: dict, expect: str | None = None, cleanup: bool = True,
              guard=None, found: tuple | None = None) -> dict | None:
    """`publish`'s whole answer: `{"sha", "pinned", "published", "kept", "notes"}`, or None
    with nothing to merge.

    `expect` is the branch sha a queued approve pinned (`keel/landing.py`): it is what gets
    merged, and a branch that has moved since is refused. `guard()` is asked right before
    the fast-forward (a reason lands nothing) and again right before any cleanup (a reason
    keeps the worktree and the branch). `cleanup` false keeps them too. A failed cleanup
    after a merge that landed is a note, never a refusal: the merge happened. `found` is
    `publish`'s own read of a branch with something to land, taken in place of a second."""
    found = found or placed(cfg, card, fetch=True)
    if found is None:
        return None
    _, repo, worktree, branch, target = found
    head = git(repo, "rev-parse", branch)
    if expect is not None and head != expect:
        raise MergeRefused(f"{branch} moved since you approved it ({expect[:8]} then, "
                           f"{head[:8]} now); nothing was merged, approve again")
    if target == trunk_of(repo) and git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise MergeRefused(f"{repo} has uncommitted changes on {target}; commit or stash them, "
                           f"then approve again")
    left = leftover_branch(card, worktree, branch)
    merged = land(cfg, card, repo, branch, target, source=expect, guard=guard)
    sha = git(repo, "rev-parse", "--short", merged)
    kept_for = (guard() if guard else None) or (None if cleanup else "its house is live")
    notes = [f"the worktree and branch were kept: {kept_for}"] if kept_for else clean_up(repo, worktree, branch, target)
    if left and has_ref(repo, f"refs/heads/{left}"):
        notes.append(f"a house left the branch {left} in {repo.name}; it is not what landed, "
                     f"and it was kept")
    if not kept_for and not worktree.exists():
        forget_worktree(cfg, card, worktree)
    return {"sha": merged, "pinned": expect or head, "kept": bool(kept_for), "notes": notes,
            "target": target,
            "published": f"{sha} merged into {target} locally, not pushed"}


def close_unlanded(cfg: Config, card: dict, found: tuple | None = None) -> list[str]:
    """A card closed with nothing to land gives up its worktree as a landed one does (r-24,
    c-553 review F4): the worktree removed and its trust entry forgotten, and the branch
    deleted only when its target already holds it. A research branch with commits of its
    own is kept, and said. Notes, never raises.

    `found` is what the user's tap read with the fetch (`publish`, c-773). A builder's
    branch is then here as `refs/builder/<branch>`, and that fetched ref goes with a
    worktree a house left at the card's path (`drop_branch`): the ref may be another card's
    branch that landed with this one's work, and Bosun's clone keeps the branch itself.
    Without `found` the branch is read here with no fetch, so a builder's is refused and
    nothing is removed."""
    try:
        found = found or branch_placed(cfg, card)
    except NoBranch:
        return drop_leftover_tree(cfg, card)      # c-647: no branch was read; its tree still goes
    except MergeRefused:
        return []
    if found is None:
        return []
    _, repo, worktree, branch, target = found
    notes = []
    try:
        if worktree.is_dir():
            git(repo, "worktree", "remove", "--force", str(worktree))
        if not ancestor(repo, branch, target):
            notes.append(f"{branch} holds commits {target} does not, so it was kept")
        elif built_clone(cfg, card) is None or branch.startswith(BUILT_REFS):
            # A builder's card gives up only the ref the tap fetched: with its clone gone
            # the branch read is one of the live repo's own, and that one stays.
            drop_branch(repo, branch)
    except MergeRefused as error:
        notes.append(f"nothing landed, but {str(error).splitlines()[0]}")
    if not worktree.exists():
        forget_worktree(cfg, card, worktree)
    return notes


def drop_leftover_tree(cfg: Config, card: dict) -> list[str]:
    """A card Bosun builds, closed with nothing to land, whose outcome names no branch to
    read (`NoBranch`, c-647): a worktree a house left at the card's own path still goes, and
    its trust entry with it, as `close_unlanded` does for any card. No branch is deleted
    here: none was read. Only that refusal: any other (a clone's branch not read before the
    tap, a repo that is not here) removes nothing, as before. Notes, never raises."""
    space = cfg.spaces.get(card["space"])
    repo = space.repo_path(card["repo"]) if space is not None and card.get("repo") else None
    worktree = repolayout.card_tree(cfg, card)
    if repo is None or not worktree.is_dir():
        return []
    notes = []
    try:
        git(repo, "worktree", "remove", "--force", str(worktree))
    except MergeRefused as error:
        notes.append(f"nothing landed, but {str(error).splitlines()[0]}")
    if not worktree.exists():
        forget_worktree(cfg, card, worktree)
    return notes


def forget_worktree(cfg: Config, card: dict, worktree: Path) -> None:
    """The reaped worktree's trust entry in its space's `.claude.json` goes with it
    (`keel/trust.py`), so the file does not keep one per merged card forever."""
    space = cfg.spaces.get(card["space"])
    if space is not None:
        trust.forget(space.config_dir, worktree, cfg.state_dir)


def clean_up(repo: Path, worktree: Path, branch: str, target: str) -> list[str]:
    """Remove the card's worktree and branch after a merge that landed; notes, never raises.

    The branch goes only once it is an ancestor of the branch it landed on, and then by
    `-D`: `git branch -d` checks it against the checkout's HEAD, which is main, so it
    refused every branch landed on `next` (c-530, c-535). A branch that is not in the target
    (it moved after the merge) is kept, and said."""
    notes = []
    try:
        if worktree.is_dir():
            git(repo, "worktree", "remove", "--force", str(worktree))
        if not ancestor(repo, branch, target):
            return [f"merged, but {branch} is not in {target}, so it was kept"]
        drop_branch(repo, branch)
    except MergeRefused as error:
        notes.append(f"merged, but {str(error).splitlines()[0]}")
    return notes


def drop_branch(repo: Path, branch: str) -> None:
    """Delete a branch its target already holds (the caller checked): the builder's fetched
    ref by its full name (c-619), which is no branch of the live repo and which Bosun's
    clone still has; a house's branch by `-D` (`clean_up` says why)."""
    if branch.startswith(BUILT_REFS):
        git(repo, "update-ref", "-d", branch)
    else:
        git(repo, "branch", "-D", branch)


def target_has(cfg: Config, card: dict, sha: str) -> str | None:
    """Why `sha` is NOT in this repo's target branch here, or None when it is (`kb land`'s
    fact check, round 3 finding 4)."""
    space = cfg.spaces.get(card["space"])
    repo = space.repo_path(card["repo"]) if space and card.get("repo") else None
    if repo is None or not (repo / ".git").exists():
        return f"{card.get('repo')} is not a repository on {cfg.host}, so the merge cannot be verified here"
    target = landing_target(cfg, card, repo)
    if ref_head(repo, target) is None:
        return f"{target} does not exist on {cfg.host}, so {sha[:8]} is not in it"
    return None if ancestor(repo, sha, target) else f"{sha[:8]} is not in {target} on {cfg.host}"


def trial(cfg: Config, card: dict) -> dict | None:
    """The merged tree built and tested WITHOUT landing it (R5, the drain's pre-run): what
    Approve outcome would find, recorded on the card before he taps. None when there is
    nothing to merge."""
    found = placed(cfg, card)
    if found is None:
        return None
    _, repo, _, branch, target = found
    base, _, rest = footing(cfg, card, repo, target, trunk_of(repo))
    head = git(repo, "rev-parse", branch)
    record = {"base": base, "branch": head, "target": target}
    try:
        build_and_test(cfg, card, repo, branch, base, target, test_command(cfg, card), **rest)
    except FileChanged as waits:
        # not a red tree: nothing was built. It is run once the file's record matches
        # (`landing.pre_run_one`), since a Save moves neither head (r2.D4).
        return dict(record, result=NOT_RUN, said=str(waits))
    except MergeRefused as refused:
        said = str(refused)
        result = "conflict" if said.startswith("merge conflict") else "red"
        return dict(record, result=result, said=said)
    return dict(record, result="green", said="the merged tree is green")


def code_head(root: Path) -> str | None:
    """The commit the checkout at `root` is on, or None when it cannot be read.

    Serve and the drain compare it with the one they started on: when it moves, the running
    code is stale. Outside a repo, and on a git that did not answer in `GIT_SECONDS`, the
    head is UNKNOWN, and every caller reads unknown as "not moved": no restart, no crash.
    """
    try:
        return git(root, "rev-parse", "HEAD")
    except (MergeRefused, OSError):
        return None
