"""Deploy: main moves to the integration branch, only on his Yes (c-526; Atlas: the drain).

A repo named in `[integration]` (`next` for Keel) takes every approved outcome on that branch
(`keel/merging.py`), so nothing is live until he deploys. This module is the other half:

- **The drain's step** (`upkeep`, the board's own host only, for a repo whose trunk this
  machine owns): when the integration branch is ahead of the trunk it raises the deploy ask
  (`keel/deployask.py`), one per sha; a branch that moved withdraws the open one and raises
  another. His Deploy is started here, as a worker in its own session, because the suite
  runs for minutes; a worker that died is answered on the ask. The `kb` that records his
  Deploy kicks the drain, whose kick thread starts it at once (`kicked`, c-636).
- **The phases** (c-636): the worker records each as it begins (`start`, `merge`, `suite`,
  `live`), so the Bosun page shows where a deploy is and since when (`deployask.steps_of`).
- **The worker** (`python3 -m keel.deploy <ask>`), under the same repo lock as a landing:
  the pinned sha checked out in a temporary tree, the trunk merged in when it moved (his
  own commits), the repo's FULL suite run there WITH THE VOICE SELFTEST (`[deploy_tests]`,
  `make test-all` for Keel, else `[tests]`; c-646), the live checkout's `.venv-voice` linked
  in. The deploy is the gate that runs every module: a landing runs only `make test`, the
  core suite and what its change reaches. A machine without the venv refuses, and so does a
  run that skipped voice, did not reach it, or chose its modules rather than running them
  all. On red the failures rerun once (`[retests]`), deploying only if they pass and saying
  so. Then the live checkout's trunk takes it by `--ff-only`, which restarts the
  drain and the deck on the new code. The ask's record says
  what the move refreshes (`keel/refresh.py`): the voice gateway when `voice/` changed, and
  Harbor's two conversations when its memory did, each at its own quiet moment. A red or
  refused deploy moves nothing and files an open console request for Bosun ("deploy of next ...
  refused: <why>"), one per refusal.
- **The preflight** (`keel/deploypreflight.py`, c-725): before the suite, a tree of Keel's own
  code is refused while the install would read a path it removes or lose one owner's things
  the old tree held, each problem naming the command that clears it.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from keel import childenv, config as config_module, deployask, deploypreflight, landing, merging, refresh, requests, settings
from keel.board import Refused, open_board
from keel.config import Config

VENV = ".venv-voice"
# How long a deploy of Keel's own checkout waits for the deck to answer on the new code
# (c-637), beyond the drain's own restart: a deck on its own follows its checkout within
# `serve.CODE_POLL_SECONDS`; one that shares the drain's process restarts with the drain,
# between passes, so the wait adds two of the drain's polls (`deck_wait`). Later than that
# only while a conversation, a call or a deck action would be cut.
DECK_WAIT_SECONDS = 60.0
LOG_NAME = "deploy.log"
CARD_OF_MERGE = re.compile(r"\((c-\d+)\)\s*$")


# ----- what is waiting -----

def repos(cfg: Config) -> list[dict]:
    """The integration repos, once each, by path (Keel is in two spaces)."""
    found, seen = [], set()
    for space_name, key in sorted(cfg.integrated):
        path = cfg.spaces[space_name].repo_path(key)
        if path is None or not (path / ".git").exists():
            continue
        real = path.resolve()
        if real in seen:
            continue
        seen.add(real)
        found.append({"repo": key, "space": space_name, "path": path,
                      "target": cfg.integration_of(space_name, key)})
    return found


def carried(path: Path, trunk: str, sha: str) -> list[str]:
    """The cards whose landing merges are on `sha` and not on the trunk, oldest first."""
    subjects = merging.git(path, "log", "--merges", "--reverse", "--format=%s", f"{trunk}..{sha}")
    cards = [m.group(1) for m in (CARD_OF_MERGE.search(line) for line in subjects.splitlines()) if m]
    return list(dict.fromkeys(cards))


def ahead(cfg: Config, one: dict) -> dict | None:
    """What a deploy of this repo would carry, or None when the trunk already has it."""
    path, target = one["path"], one["target"]
    trunk = merging.trunk_of(path)
    sha = merging.ref_head(path, target)
    if sha is None or merging.ancestor(path, sha, trunk):
        return None
    return {"repo": one["repo"], "space": one["space"], "target": target, "trunk": trunk,
            "sha": sha, "cards": carried(path, trunk, sha)}


# ----- the drain's step -----

def upkeep(cfg: Config, board) -> None:
    """Every pass, on the board's own host: answer a dead worker, start a Deploy he said,
    and keep one open deploy ask per waiting sha. Never raises for one repo's trouble."""
    if not hasattr(board, "conn"):
        return
    for one in repos(cfg):
        try:
            step(cfg, board, one)
        except (merging.MergeRefused, Refused, OSError) as error:
            log(cfg, f"deploy upkeep of {one['repo']}: {error}")


# The pass's step and the kick thread's start hold it, so within one drain the two never
# answer a dead worker and start its successor at once. What makes a start happen once,
# across processes too (`keel drain --once`), is the board's claim (`deployask.claim`).
STEP_LOCK = threading.Lock()


def kicked(cfg: Config, board) -> None:
    """A kick's part (c-636): start a Deploy he just said at once, not at the drain's next
    pass. The `kb` that recorded his answer kicked this machine's drain (`kick.after_deploy`),
    whose kick thread runs this. Never raises for one repo's trouble."""
    if not hasattr(board, "conn"):
        return
    for one in repos(cfg):
        try:
            with STEP_LOCK:
                rows = deployask.rows_for(board, one["repo"])
                if not running(cfg, board, rows):
                    start_said(cfg, board, one["repo"])
        except (merging.MergeRefused, Refused, OSError) as error:
            log(cfg, f"deploy kick of {one['repo']}: {error}")


def running(cfg: Config, board, rows: list[dict]) -> bool:
    """Whether a deploy worker of these asks is running; one that died is answered."""
    live = False
    for row in rows:
        if row["state"] != "answered":
            continue
        state = deployask.deploying(board, row["id"])
        if state is None:
            continue
        if landing.dead(cfg, state.get("data") or {}):
            finish(cfg, board, row, None, "the deploy worker ended without an answer")
        else:
            live = True
    return live


def start_said(cfg: Config, board, repo: str) -> bool:
    """Start the Deploy he said that no worker has taken; whether this drain took it."""
    wanted = deployask.to_start(board, repo)
    return wanted is not None and start(cfg, board, wanted)


def step(cfg: Config, board, one: dict) -> None:
    with STEP_LOCK:
        rows = deployask.rows_for(board, one["repo"])
        live = running(cfg, board, rows)
        if not live and start_said(cfg, board, one["repo"]):
            return
    found = ahead(cfg, one)
    opened = [row for row in rows if row["state"] == "open"]
    for row in opened:
        if found is None:
            deployask.withdraw(board, row, f"{one['target']} is no longer ahead of the trunk")
        elif deployask.facts_of(row)["sha"] != found["sha"]:
            deployask.withdraw(board, row, f"{found['target']} moved to {found['sha'][:8]}")
    if found is None or live:
        return
    asked = [row for row in deployask.rows_for(board, one["repo"])
             if row["state"] != "withdrawn" and deployask.facts_of(row)["sha"] == found["sha"]]
    if not asked:
        deployask.raise_deploy(board, found)


def start(cfg: Config, board, row: dict) -> bool:
    """His Deploy, handed to a worker. The board's claim comes first (`deployask.claim`, one
    write transaction), so no two drains, in this process or another, start two; False when
    another drain had already taken it."""
    if not deployask.claim(board, row, "deploying: the worker starts", host=cfg.host,
                           at=board.now()):
        return False
    try:
        pid = spawn(cfg, row["id"])
    except OSError as error:
        finish(cfg, board, row, None, f"the deploy worker would not start: {error}")
        return True
    deployask.record(board, row["id"], deployask.DEPLOYING, f"deploy worker {pid}",
                     host=cfg.host, pid=pid, phase=deployask.START)
    return True


def spawn(cfg: Config, aid: str) -> int:
    env = childenv.own_env()      # the worker runs the repo's suite: never his token (c-451)
    if cfg.source is not None and not cfg.scratch:
        env["KEEL_CONFIG"] = str(cfg.source)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.logs_dir / LOG_NAME, "a") as out:
        proc = subprocess.Popen([sys.executable, "-m", "keel.deploy", aid], cwd=str(cfg.root),
                                env=env, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid


def log(cfg: Config, line: str) -> None:
    try:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        with open(cfg.logs_dir / LOG_NAME, "a") as out:
            out.write(line.rstrip() + "\n")
    except OSError:
        pass


def finish(cfg: Config, board, row: dict, merged: str | None, why: str,
           refreshes: list[str] | None = None, deck: bool | None = None) -> None:
    """The deploy's end, on the ask's record; a refusal is also a console request for Bosun.
    A deploy's record also says what it refreshes (`refresh.effects`, c-538), and, for a
    deploy of Keel's own checkout, whether the deck was seen on the new code (`deck`)."""
    facts = deployask.facts_of(row)
    if merged:
        said = why + ("".join(f"; {one}" for one in refreshes) if refreshes else "")
        seen = {} if deck is None else {"deck": deck}
        deployask.record(board, row["id"], deployask.DEPLOYED, said, sha=merged,
                         cards=facts.get("cards"), refreshes=refreshes or [], **seen)
        return
    deployask.record(board, row["id"], deployask.REFUSED, f"not deployed: {why}")
    try:
        # An OPEN request at once, not a sighting: a deploy is refused once per sha, so a
        # sighting would never reach its repeat and nobody would be shown it (review F1).
        what = f"deploy of {facts['target']} ({facts['sha'][:8]}) refused: {why.splitlines()[0]}"
        requests.ask(board, clip(what, requests.WHAT_MAX), "drain",
                     detail=clip(why, requests.DETAIL_MAX))
    except Refused as refused:
        log(cfg, f"deploy request for {row['id']} not filed: {refused}")


# ----- the worker -----

def clip(text: str, limit: int) -> str:
    """A request's text within its cap, so a long git error can never stop the filing."""
    text = " ".join(str(text).split()) if limit < 1000 else str(text).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


class NotDeployed(Exception):
    """The reason main did not move."""


FULL_SUITE = "KEEL_FULL_SUITE"


def run_suite(command: str, tree: Path, out_path: Path,
              seconds: float = settings.default("keel", "deploy_test_seconds"),
              full: bool = False) -> int:
    """The suite on the tree, its output to `out_path`; its exit status (124 when it runs
    past `seconds`, `[keel] deploy_test_seconds`, c-633). `full` asks a repo's own `make
    test` for every module (`KEEL_FULL_SUITE`), for a deploy that fell back to `[tests]`."""
    env = childenv.own_env()
    if full:
        env[FULL_SUITE] = "1"
    with open(out_path, "w") as out:
        proc = subprocess.Popen(command, shell=True, cwd=str(tree), stdout=out,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True, env=env)
        try:
            return proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            merging.kill_suite(proc)
            return 124


def tail(path: Path, lines: int = 12) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").strip().splitlines()[-lines:])
    except OSError:
        return ""


def link_voice(cfg: Config, repo: Path, tree: Path) -> None:
    """The voice selftest needs its own interpreter: the live checkout's venv, linked in."""
    venv = repo / VENV
    if not os.access(venv / "bin" / "python", os.X_OK):
        raise NotDeployed(f"no {VENV} in {repo} on {cfg.host}, so the voice selftest cannot run "
                          f"and a deploy without it is refused; build it with `bin/keel voice venv`")
    (tree / VENV).symlink_to(venv.resolve(), target_is_directory=True)


# The skip is the Makefile's own line, at the start of a line; the runner's echoed command
# also holds the words (its --done pattern), which refused the first real deploy (2026-09-26).
VOICE_SKIP_LINE = merging.VOICE_SKIP_LINE


def read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def whole(path: Path) -> None:
    """Refused unless the run was every module with voice: not one that skipped the selftest,
    one the selector says did not reach it, or one that chose its modules (c-646)."""
    text = read(path)
    if VOICE_SKIP_LINE.search(text):
        raise NotDeployed("the suite skipped the voice selftest; a deploy needs it run")
    if merging.VOICE_UNREACHED.search(text):
        raise NotDeployed("the suite did not run the voice selftest (the change did not reach "
                          "it); a deploy runs it whatever changed (`[deploy_tests]`)")
    if merging.NARROW.search(text):
        raise NotDeployed("the suite ran the modules the change reaches, not every module; a "
                          "deploy runs them all (`[deploy_tests]`)")


def voice_ran(*paths: Path) -> None:
    """Refused when a leg skipped the voice selftest, or no leg shows it passing (`exit 0`
    with no skip note: a skip exits 0 too)."""
    texts = [read(path) for path in paths]
    if any(VOICE_SKIP_LINE.search(text) for text in texts) or not any(
            merging.voice_passed(text) for text in texts):
        raise NotDeployed("the suite skipped the voice selftest; a deploy needs it run")


def tested(cfg: Config, facts: dict, tree: Path, base: str) -> str:
    """Run the full suite, voice included (`[deploy_tests]`, else `[tests]`; `{base}` is the
    trunk's head), and, on red, its failures once more; what to record."""
    deploy = (cfg.deploy_tests.get(facts["repo"]) or "").strip()
    command = deploy or cfg.repo_tests.get(facts["repo"])
    # an install config written before c-646 names only `[tests]`: ask it for every module
    full = not deploy
    if not command:
        raise NotDeployed(f"{facts['repo']} has no [deploy_tests] or [tests] command; a deploy "
                          f"runs the full suite")
    command = command.replace("{base}", base)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    first = cfg.logs_dir / f"deploy-{facts['repo']}-suite.log"
    code = run_suite(command, tree, first, cfg.deploy_test_seconds, full)
    whole(first)
    if code == 0:
        voice_ran(first)
        return "the full suite was green (voice included)"
    retest = cfg.repo_retests.get(facts["repo"])
    if not retest:
        raise NotDeployed(f"the suite was red (`{command}` exited {code}):\n{tail(first)}")
    again = cfg.logs_dir / f"deploy-{facts['repo']}-rerun.log"
    rerun = run_suite(retest.replace("{log}", str(first)), tree, again, cfg.deploy_test_seconds)
    if rerun != 0:
        raise NotDeployed(f"the suite was red, and its failures failed again on the rerun "
                          f"(`{command}` exited {code}):\n{tail(again)}")
    voice_ran(first, again)
    failed = failed_names(first)
    return (f"the full suite was red on {len(failed) or 'some'} failure(s) "
            f"({', '.join(failed[:6]) or 'see ' + str(first)}), and they passed when rerun "
            f"once (voice included)")


def failed_names(path: Path) -> list[str]:
    """The tests and jobs a red run names, by `merging.failures` (one parser for both)."""
    tests, jobs = merging.failures(read(path))
    return list(dict.fromkeys(tests + [job.split(":")[0] for job in jobs]))


def build(cfg: Config, repo: Path, facts: dict, tree: Path) -> tuple[str, str]:
    """The tree to deploy: the pinned sha, with the trunk merged in when it moved. Returns
    `(tree head, trunk head it was built on)`."""
    trunk = facts["trunk"]
    trunk_head = merging.git(repo, "rev-parse", trunk)
    merging.drop_tree(repo, tree)
    tree.parent.mkdir(parents=True, exist_ok=True)
    merging.git(repo, "worktree", "add", "--detach", str(tree), facts["sha"])
    if not merging.ancestor(repo, trunk_head, facts["sha"]):
        try:
            merging.git(tree, "merge", "--no-ff", trunk_head, "-m",
                        f"Merge {trunk} into {facts['target']}")
        except merging.MergeRefused:
            merging.abort_merge(tree)
            raise NotDeployed(merging.TRUNK_CONFLICT.format(trunk=trunk, target=facts["target"]))
    return merging.git(tree, "rev-parse", "HEAD"), trunk_head


def preflight(cfg: Config, repo: Path, tree: Path) -> None:
    """A tree of Keel's own code goes live only once the install no longer needs anything the
    tree removes (`keel/deploypreflight.py`, c-725): refused before the suite, naming the one
    command that clears each problem."""
    if not same_path(repo, cfg.root):
        return
    found = deploypreflight.problems(cfg, repo, tree)
    if found:
        raise NotDeployed(deploypreflight.said(found))


def go_live(repo: Path, facts: dict, merged: str, trunk_head: str) -> None:
    """The trunk takes the tested tree by fast-forward, if nothing moved it meanwhile; the
    integration branch follows when it is still where the ask pinned it."""
    trunk = facts["trunk"]
    if merging.trunk_of(repo) != trunk:
        raise NotDeployed(f"{repo} is not on {trunk} any more; once it is, `kb console deploy`")
    if merging.git(repo, "rev-parse", trunk) != trunk_head:
        raise NotDeployed(f"{trunk} moved while the suite ran; say Deploy again with "
                          f"`kb console deploy`, which asks afresh")
    if merging.git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise NotDeployed(f"{repo} has uncommitted changes on {trunk}; once they are committed, "
                          f"`kb console deploy`")
    merging.git(repo, "merge", "--ff-only", "--quiet", merged)
    if merged != facts["sha"]:
        try:
            merging.git(repo, "update-ref", f"refs/heads/{facts['target']}", merged, facts["sha"])
        except merging.MergeRefused:
            pass           # it moved on: its next landing merges the trunk in


def deploy(cfg: Config, board, aid: str) -> int:
    """The worker: 0 when main moved, 1 when it did not. Answers on the ask, never raises."""
    row = deployask.asks.get(board, aid)
    facts = deployask.facts_of(row)
    if facts is None or row["state"] != "answered" or row["answer"] != "A":
        print(f"keel.deploy: {aid} is not a deploy the user said Yes to", file=sys.stderr)
        return 1
    if any(move in (deployask.DEPLOYED, deployask.REFUSED) for move in deployask.moves(board, aid)):
        print(f"keel.deploy: {aid} has already run; a Yes deploys once", file=sys.stderr)
        return 1
    other = take(cfg, board, aid)
    if other is not None:
        print(f"keel.deploy: {aid} is being deployed by worker {other}", file=sys.stderr)
        return 1
    repo = cfg.spaces[facts["space"]].repo_path(facts["repo"])
    tree = cfg.worktrees_dir / f"deploy-{facts['repo']}.landing"
    try:
        with landing.repo_lock(cfg, {"space": facts["space"], "repo": facts["repo"]}):
            try:
                phase(cfg, board, aid, deployask.MERGE,
                      f"building {facts['sha'][:8]}, with {facts['trunk']} merged in if it moved")
                merged, trunk_head = build(cfg, repo, facts, tree)
                preflight(cfg, repo, tree)
                # The SAME tree a full run already proved green, voice included: a landing
                # whose run was every module, or `kb tested` (2026-09-26, his call; c-646).
                # A landing's narrow `make test` records nothing. A trunk merged in makes a
                # new tree, which is tested as before.
                known = merging.tested_whole(cfg, merging.tree_of(repo, merged))
                if known:
                    said = (f"the full suite was green (voice included) on this exact tree "
                            f"at {known['card']}'s landing, so it was not run again")
                    phase(cfg, board, aid, deployask.SUITE, said)
                else:
                    link_voice(cfg, repo, tree)
                    phase(cfg, board, aid, deployask.SUITE,
                          f"the full suite runs (voice included) on {merged[:8]}")
                    said = tested(cfg, facts, tree, trunk_head)
            finally:
                merging.drop_tree(repo, tree)
            go_live(repo, facts, merged, trunk_head)
            refreshes = refreshed(repo, trunk_head, merged)
    except (NotDeployed, merging.MergeRefused) as error:
        finish(cfg, board, row, None, str(error))
        return 1
    except Exception as error:  # noqa: BLE001 - the worker answers on the ask, not in a traceback
        finish(cfg, board, row, None, f"the deploy failed: {type(error).__name__}: {error}")
        return 1
    deck = None
    if same_path(repo, cfg.root):
        deck, on_deck = deck_after(cfg, board, aid, facts, merged)
        said += "; " + on_deck
    else:
        went_live(cfg, board, aid, f"{facts['trunk']} is at {merged[:8]}")
    finish(cfg, board, row, merged, f"deployed {merged[:8]} to {facts['trunk']}: {said}", refreshes,
           deck=deck)
    return 0


def take(cfg: Config, board, aid: str) -> int | None:
    """The worker takes its ask, in one write transaction: refused when the newest
    `deploying` record names another worker that is still alive (review F2), else its own
    `start` phase is recorded. The other worker's pid, or None when this one took it."""
    with board.tx():
        data = (deployask.deploying(board, aid) or {}).get("data") or {}
        if data.get("pid") not in (None, os.getpid()) and not landing.dead(cfg, data):
            return data["pid"]
        deployask.asks.record(board, aid, None, deployask.DEPLOYING, deployask.RAISER,
                              f"deploy worker {os.getpid()}", host=cfg.host, pid=os.getpid(),
                              phase=deployask.START)
    return None


def phase(cfg: Config, board, aid: str, name: str, text: str) -> None:
    """The deploy's phase on its ask, as it begins (c-636), with the worker's pid."""
    deployask.record(board, aid, deployask.DEPLOYING, text, host=cfg.host, pid=os.getpid(),
                     phase=name)


def went_live(cfg: Config, board, aid: str, text: str) -> None:
    """Main has moved: the `live` phase on the ask. A record that fails here is only not
    said: nothing after main moved can turn the deploy into a refusal."""
    try:
        phase(cfg, board, aid, deployask.LIVE_PHASE, text)
    except Exception:  # noqa: BLE001,S110 - main moved; `finish` still records the end
        pass


def deck_after(cfg: Config, board, aid: str, facts: dict, merged: str) -> tuple[bool, str]:
    """Main has moved: say so on the ask while the deck restarts, then whether it came up on
    the new code, and in words. Nothing here can turn a deploy that moved main into a
    refusal: a deck not seen on it is still `deployed`, marked `deck: false` (review F1)."""
    try:
        phase(cfg, board, aid, deployask.LIVE_PHASE,
              f"{facts['trunk']} is at {merged[:8]}; the deck restarts onto it")
        return deck_on(cfg, merged)
    except Exception as error:  # noqa: BLE001 - main moved; this only reports on the deck
        return False, f"the deck could not be checked: {type(error).__name__}: {error}"


def same_path(one: Path, other: Path) -> bool:
    try:
        return Path(one).resolve() == Path(other).resolve()
    except OSError:
        return False


def serve_head(cfg: Config) -> str | None:
    """The code the deck on this machine runs (`/api/health`'s `serve_head`), or None when
    it does not answer, as while it restarts. The deck's exec cuts the reply it was sending,
    and a body cut short is `IncompleteRead`: an `HTTPException`, which is no `OSError`
    (c-662: it would have ended the wait, and the deploy, with main already moved)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{cfg.serve_port}/api/health", timeout=3) as reply:
            return json.loads(reply.read()).get("serve_head")
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return None


def deck_wait(cfg: Config) -> float:
    """`DECK_WAIT_SECONDS` plus two drain polls: the restart a deck sharing the drain's
    process waits for comes between passes (c-637 review)."""
    return DECK_WAIT_SECONDS + 2 * float(cfg.poll_seconds or 0)


def deck_on(cfg: Config, sha: str, seconds: float | None = None, read=None) -> tuple[bool, str]:
    """Whether the deck came up on `sha`, and in words for the deploy's record: a deploy of
    Keel's own code waits for the page to be served by the code it moved to."""
    seconds = deck_wait(cfg) if seconds is None else seconds
    read = read or serve_head
    deadline = time.monotonic() + seconds
    while True:
        if read(cfg) == sha:
            return True, "the deck restarted onto it"
        if time.monotonic() >= deadline:
            return False, (f"the deck has not restarted onto it in {int(seconds)} s; it restarts "
                           f"once no conversation, call or action it holds would be cut")
        time.sleep(0.5)


def refreshed(repo: Path, trunk_head: str, merged: str) -> list[str]:
    """What moving main from `trunk_head` to `merged` refreshes, from the files it changed.
    Main has moved by now, so a diff git will not give is said as the engine alone."""
    try:
        changed = merging.git(repo, "diff", "--name-only", trunk_head, merged).splitlines()
    except merging.MergeRefused:
        return [refresh.ENGINE]
    return refresh.effects(changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keel.deploy", description="deploy one answered ask")
    parser.add_argument("ask")
    args = parser.parse_args(argv)
    cfg = config_module.load()
    board = open_board(cfg)
    try:
        return deploy(cfg, board, args.ask)
    finally:
        board.close()


if __name__ == "__main__":
    raise SystemExit(main())
