"""The push fence a space's flow draws (c-641, docs/atlas/64-flows.md).

A flow already says which branches are shared: every branch whose kind is not `card` (the
card's own) or `work` (one a move makes for it). A house never pushes a shared branch by
hand. The house guard (`bin/keel-house-guard`) refuses a `git push` whose destination is one
(`targets` reads the command, and a push it cannot read counts as every branch), and
`kb flowpush` is the one way through: it pushes HEAD to a branch of the flow only while the
owner's tap's grant (`options.flow_move`, written by `flow.move` and human only) names it,
at the stage it was tapped at, and never forced. With `--pr` it also opens a change the
grant names, through the space's pack (`pr --flow`).

THE BOARD'S HOST JUDGES (c-641 review). `info` is computed where the board lives, from the
flow that granted the move, and reaches a house on the other machine as `kb flowinfo`; the
grant itself carries the git names the move may push and open, filled at the tap. So both
machines read one flow, whatever install the house runs in.

A GRANT IS TIED TO WHAT THE FLOW SAID (c-664). The grant keeps the flow's own label of each
branch beside the name filled from it (`labels`), and `info` ends a grant whose flow now
labels one differently, saying the flow changed since the tap: a branch whose label was
edited is not pushed under its old name, which the new flow no longer protects either. The
pack's own `pr --flow` asks `kb flowinfo` too, so it reaches the same judgment.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from keel import flowmoves, flows, terms
from keel.config import DEFAULT_REMOTE, remote_of

OPEN_KINDS = ("card", "work")         # the kinds a house may push by hand
EVERY = "*"                            # `--all`, `--mirror`, or a push it cannot read
GIT_SECONDS = 120
# One git read's clock. A caller with a clock of its own (the house guard, c-689) hands
# `targets` what it has left instead: seconds, or a callable asked before each read.
GIT_READ_SECONDS = 30
# git options that take the next word as their value (`git -C <dir> push`, `push -o <opt>`)
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
PUSH_VALUED = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
# `git config` options that take the next word as their value (`-f <file>`)
CONFIG_VALUED = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value"}
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l",
                "--show-origin", "--show-scope", "--unset", "--unset-all", "--remove-section",
                "get", "list", "unset", "remove-section"}
# a config key that says where a push goes
REMOTE_PUSH = re.compile(r"^remote\..*\.push$", re.IGNORECASE)
# a push said inside a word: `sh -c 'git push ...'`, `$(git push ...)`, `["git", "push"]`
NESTED = re.compile(r"(?<![\w-])git(?![\w/-])[^\n]*?(?<![\w-])push(?![\w-])|[\"']git[\"']\s*,.*[\"']push[\"']",
                    re.DOTALL)
# the git commands that never push, whatever their env or input: anything else run with a
# config env or under xargs may be an alias, so it counts (c-641 fix check)
NO_PUSH = frozenset(("add", "rm", "mv", "commit", "status", "log", "diff", "show", "fetch", "rebase",
                     "merge", "switch", "checkout", "restore", "reset", "stash", "cherry-pick", "revert",
                     "branch", "tag", "rev-parse", "rev-list", "ls-files", "ls-remote", "grep", "blame",
                     "describe", "apply", "am", "format-patch", "clean", "worktree", "remote", "notes",
                     "cat-file", "shortlog", "range-diff", "merge-base", "symbolic-ref", "for-each-ref",
                     "show-ref", "check-ignore", "version", "help", "init", "clone", "pull", "submodule",
                     "bisect", "gc", "reflog", "update-index", "hash-object", "config"))
# a config key that changes which branches a bare push sends
PUSH_DEFAULT = "push.default"
SHELL_WRAPPERS = "$(`'\""
# git told where to push by its environment (`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=...`)
ENV_CONFIG = re.compile(r"^GIT_CONFIG_(COUNT|PARAMETERS|KEY_\d+|VALUE_\d+|GLOBAL|SYSTEM)=")
# a refspec the shell builds at run time, or a glob refspec
BUILT = re.compile(r"[$`*?\[{~]")


class FenceError(Exception):
    """A push or pull request the flow does not allow now; the message says why."""


# ----- what a command pushes -----

def targets(command: str, cwd: str | Path | None = None, remote: str | None = None,
            timeout=GIT_READ_SECONDS) -> set[str]:
    """The branch names each `git push` in a shell command line pushes to. HEAD is its own
    branch; a bare push counts HEAD's branch and its upstream. `EVERY` for a push it cannot
    read or one aimed elsewhere: `--all`, `--mirror`, a refspec the shell builds (`$`, a
    backtick, a glob), a push run through `xargs` or with `GIT_CONFIG_*` in its env, git run
    through a variable or a function's `"$@"`, an alias that pushes (by `-c`, or written by a
    `git config` on the same line, or in the config), a `-c` or written `remote.*.push`, a
    remote with a push refspec, and a push said inside a word it cannot read (a script's
    argv). A command that pushes nothing reads as nothing, whatever runs it. `remote`: the
    space's remote, which a push that names none is read against (c-665); `origin` without.
    `timeout`: each git read's clock (`GIT_READ_SECONDS` unless the caller has less left); a
    read that gets no answer in it reads as nothing, which counts toward every branch."""
    found: set[str] = set()
    for segment in segments(command):
        found |= segment_targets(segment, cwd, remote=remote, timeout=timeout)
    return found


def segments(command: str) -> list[str]:
    """The simple commands of a line: split on `;`, `&`, `|` and newlines outside quotes, so a
    quoted command (`sh -c 'a; git push ...'`) stays one word for `segment_targets` to read
    through."""
    out, part, quote, escaped = [], [], "", False
    for char in command:
        if escaped:
            part.append(char)
            escaped = False
        elif char == "\\" and quote != "'":
            part.append(char)
            escaped = True
        elif quote:
            part.append(char)
            quote = "" if char == quote else quote
        elif char in "'\"":
            part.append(char)
            quote = char
        elif char in ";&|\n":
            out.append("".join(part))
            part = []
        else:
            part.append(char)
    out.append("".join(part))
    return [one for one in out if one.strip()]


def segment_targets(segment: str, cwd, depth: int = 0, remote: str | None = None,
                    timeout=GIT_READ_SECONDS) -> set[str]:
    try:
        words = shlex.split(segment)
    except ValueError:
        return {EVERY} if NESTED.search(segment) else set()
    at = git_at(words)
    if at is not None:
        return git_targets(words, at, cwd, remote, timeout)
    if any(word.startswith("$") for word in words) and "push" in words:
        return {EVERY}                  # `$G push ...`: git through a variable
    if any(word.startswith("`") for word in words) and "push" in words:
        return {EVERY}                  # `` `which git` push ...``: the same, by a backtick (c-723)
    nested = [word for word in words if NESTED.search(word)]
    if not nested:
        return set()
    if depth >= 2:
        return {EVERY}
    out: set[str] = set()
    for word in nested:
        inner = set()
        for part in segments(word.strip(SHELL_WRAPPERS)):
            inner |= segment_targets(part, cwd, depth + 1, remote, timeout)
        out |= inner or {EVERY}         # a push said that it could not read
    return out


def git_at(words: list[str]) -> int | None:
    return next((i for i, word in enumerate(words) if Path(word.lstrip(SHELL_WRAPPERS)).name == "git"), None)


def git_targets(words: list[str], at: int, cwd, remote: str | None = None,
                timeout=GIT_READ_SECONDS) -> set[str]:
    """One git command's push destinations, or none when it pushes nothing."""
    before = words[:at]
    told = any(ENV_CONFIG.match(word) for word in before) or "xargs" in before
    rest, where, configured, aliased = words[at + 1:], cwd, False, set()
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag in GIT_VALUED and rest:
            value = rest.pop(0)
            if flag == "-C":
                where = Path(where or ".") / value
            key, _, said = value.partition("=")
            if flag == "-c" and (REMOTE_PUSH.match(key) or key.lower() == PUSH_DEFAULT):
                configured = True
            if flag == "-c" and key.lower().startswith("alias.") and "push" in said:
                aliased.add(key[len("alias."):])
    if not rest:
        return {EVERY} if "xargs" in before else set()      # xargs supplies the subcommand
    sub = rest[0]
    if sub.startswith("$") or BUILT.search(sub):
        return {EVERY}                  # `git "$@"` in a function, `git $CMD`, `xargs -I{} git {}`
    if told and sub not in NO_PUSH:
        return {EVERY}                  # an alias its env or input may define
    if sub == "config":
        return config_targets(rest[1:])
    if sub != "push":
        alias = git_out(where, "config", "--get", f"alias.{sub}", timeout=timeout) or ""
        return {EVERY} if sub in aliased or "push" in alias else set()
    if configured or told:
        return {EVERY}                  # aimed by `-c`, by its env, or fed by xargs
    return push_targets(rest[1:], where, remote, timeout)


def config_targets(args: list[str]) -> set[str]:
    """A `git config` that WRITES where a push goes (`remote.*.push`) or an alias that pushes
    is refused as every branch; reading or removing a key, and any other setting, is not."""
    words, plain = list(args), []
    while words:
        word = words.pop(0)
        if word.startswith("-") and word in CONFIG_READS:
            return set()                 # `--get`, `--unset`, `--list` and their kin
        if word in CONFIG_VALUED and words:
            words.pop(0)
        elif not word.startswith("-"):
            plain.append(word)
    if plain and plain[0] in CONFIG_READS:
        return set()                     # git 2.46's `get`, `list`, `unset` ... as the first word
    if plain and plain[0] in ("set", "add"):
        plain = plain[1:]                # git 2.46's subcommand form
    if len(plain) < 2:
        return set()                     # a key alone is a read
    key, value = plain[0], " ".join(plain[1:])
    if (REMOTE_PUSH.match(key) or key.lower() == PUSH_DEFAULT
            or (key.lower().startswith("alias.") and "push" in value)):
        return {EVERY}
    return set()


def push_targets(args: list[str], where, default: str | None = None, timeout=GIT_READ_SECONDS) -> set[str]:
    positional, words = [], list(args)
    while words:
        word = words.pop(0)
        if word in ("--all", "--mirror", "--branches"):
            return {EVERY}
        if word in PUSH_VALUED and words:
            words.pop(0)
        elif not word.startswith("-"):
            positional.append(word)
    remote = positional[0] if positional else default or DEFAULT_REMOTE
    if git_out(where, "config", "--get-all", f"remote.{remote}.push", timeout=timeout):
        return {EVERY}                   # the remote maps what is pushed, with or without a refspec
    refspecs = positional[1:]
    if not refspecs:
        return current_and_upstream(where, timeout)
    out = set()
    for spec in refspecs:
        spec = spec.rstrip(")`'\"")             # the end of a `$(...)` or a quoted command
        if BUILT.search(spec):
            return {EVERY}                     # a name the shell builds, or a glob refspec
        source, _, destination = spec.lstrip("+").partition(":")
        name = destination if ":" in spec else source
        if name in ("HEAD", "@"):
            # an explicit HEAD pushes to the branch of the same name, never its upstream
            current = git_out(where, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout)
            out.add(current if current and current != "HEAD" else EVERY)
        elif name:
            out.add(short(name))
    return out


def short(ref: str) -> str:
    return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def current_and_upstream(cwd, timeout=GIT_READ_SECONDS) -> set[str]:
    """A bare `git push`: the branch HEAD is on and the branch its upstream names (which one
    git takes depends on `push.default`, so both count); EVERY when neither reads."""
    out = set()
    branch = git_out(cwd, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout)
    if branch and branch != "HEAD":
        out.add(branch)
    upstream = git_out(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", timeout=timeout)
    if upstream and "/" in upstream:
        out.add(upstream.split("/", 1)[1])
    return out or {EVERY}


def git_out(cwd, *args, timeout=GIT_READ_SECONDS) -> str | None:
    seconds = timeout() if callable(timeout) else timeout
    if seconds <= 0:
        return None                      # the caller's clock ran out: unread
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=seconds)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


# ----- what the board's host says (`kb flowinfo`) -----

def flow_of(cfg, card: dict) -> flows.Flow:
    space = cfg.spaces.get(card.get("space") or "")
    if space is None:
        raise FenceError(f"{card.get('id')}'s space {card.get('space')!r} is not configured here")
    return flows.of(cfg, space)


def git_name(name: str) -> bool:
    """A label that is a branch's git name: filled, and no spaces (Keel's own flows label
    some branches in words, "integration branch", which name no branch)."""
    return bool(name) and "{" not in name and not any(ch.isspace() for ch in name)


def shared(cfg, card: dict, found: flows.Flow | None = None, facts: dict | None = None) -> list[str]:
    """The git names of the card's space flow's shared branches."""
    found = found or flow_of(cfg, card)
    facts = facts or flowmoves.facts(cfg, card, None, found)
    names = (flowmoves.name_of(found, one.id, facts["base"], facts["branch"])
             for one in found.branches if one.kind not in OPEN_KINDS)
    return sorted({name for name in names if git_name(name)})


def info(cfg, card: dict) -> dict:
    """What a house's guard and `kb flowpush` need, judged on the board's host:
    `{card, space, stage, shared: [names], grant: {move, label, pushes: {id: name},
    opens: {id: name}} or None, why, remote}`, `why` saying why there is no live grant and
    `remote` the space's git remote (`config.remote_of`, c-665), so the house's machine
    pushes where the board's host says."""
    grant, why = None, ""
    held = (card.get("options") or {}).get(flowmoves.OPTION) or {}
    found = flow_of(cfg, card)
    facts = flowmoves.facts(cfg, card, None, found)     # read once, for the grant and the fence
    move = found.move(str(held.get("id") or "")) if held else None
    if not held.get("id"):
        why = (f"{card['id']} has no flow move granted: a shared branch is pushed only after the "
               f"move is tapped on the card (or asked of the talker)")
    elif move is None or not move.yours:
        why = f"the grant names {held['id']!r}, which the {card['space']} flow no longer has"
    elif card.get("stage") not in move.stages:
        why = f"{move.label} was granted at another stage; {card['id']} is at {card.get('stage')}"
    else:
        names = held.get("names") or {}
        pick = lambda ids, allowed: {one: names[one] for one in ids if one in allowed and one in names}  # noqa: E731
        grant = {"move": move.id, "label": move.label,
                 "pushes": pick(held.get("pushes") or [], move.pushes),
                 "opens": pick(held.get("opens") or [], move.opens)}
        why = renamed(card, found, move, held, {**grant["pushes"], **grant["opens"]}, facts)
        grant = None if why else grant
    return {"card": card["id"], "space": card.get("space"), "stage": card.get("stage"),
            "repos": [key.strip() for key in str(card.get("repo") or "").split(",") if key.strip()],
            "shared": shared(cfg, card, found, facts), "grant": grant, "why": why,
            "remote": remote_of(cfg, card.get("space"))}


def renamed(card: dict, found: flows.Flow, move: flows.Move, held: dict, granted: dict[str, str],
            facts: dict) -> str:
    """Why a grant no longer stands, or nothing (c-664): the FLOW calls a branch it names
    differently now than at the tap (`labels`, kept beside the names), so the old name is
    not pushed and the new one was never granted. Only the flow ends it: a card whose base
    or branch reads differently for a moment keeps its grant and its tap-time names. A
    grant from before the labels were kept has its names compared instead."""
    was = held.get("labels")
    was = was if isinstance(was, dict) else granted
    now = flowmoves.labels_of(found, granted) if was is not granted else flowmoves.names_of(found, granted, facts)
    moved = [f"{one} was {was.get(one)} and is {now[one]}" for one in sorted(granted) if now[one] != was.get(one)]
    if not moved:
        return ""
    return (f"the {card.get('space')} flow changed since {move.label} was tapped ({'; '.join(moved)}), "
            f"so that grant no longer stands: the move is tapped again on the card")


def remote_in(flow_info: dict) -> str:
    """The remote the board's host named (`info`); a host from before it named one, the default."""
    return str(flow_info.get("remote") or DEFAULT_REMOTE)


def check_repo(cfg, flow_info: dict, cwd) -> None:
    """The worktree must be a clone of one of the card's repos: its remote one of theirs, as
    this machine's config knows them. A machine that knows none of them says nothing."""
    space = cfg.spaces.get(flow_info.get("space") or "") if cfg is not None else None
    if space is None:
        return
    origins, remote = set(), remote_in(flow_info)
    for key in flow_info.get("repos") or []:
        try:
            path = space.repo_path(key)
        except (KeyError, AttributeError, TypeError):
            path = None
        url = git_out(path, "remote", "get-url", remote) if path else None
        if url:
            origins.add(url)
    here = git_out(cwd, "remote", "get-url", remote)
    if origins and here not in origins:
        raise FenceError(f"{cwd} is not a clone of {', '.join(flow_info.get('repos') or [])}, "
                         f"{flow_info.get('card')}'s repos")


def refusal(flow_info: dict, command: str, cwd, names: set[str] | None = None,
            timeout=GIT_READ_SECONDS) -> str | None:
    """Why the guard refuses this command for this card's house, or None. `names`: what
    the guard already read off the command, before the board said which remote the space
    pushes to; read again when that is not the default one."""
    if names is None or remote_in(flow_info) != DEFAULT_REMOTE:
        names = targets(command, cwd, remote_in(flow_info), timeout)
    if not names:
        return None
    protected = set(flow_info.get("shared") or [])
    hit = sorted(names & protected) or (["every branch"] if EVERY in names and protected else [])
    if not hit:
        return None
    card = flow_info.get("card")
    return (f"{', '.join(hit)} is a shared branch of the {flow_info.get('space')} flow (or a push "
            f"the guard cannot read): only a flow move tapped on the card pushes it, and then with "
            f"`kb flowpush {card} <branch>`. Push your own branch by name "
            f"(`git push -u {remote_in(flow_info)} HEAD` from it).")


# ----- `kb flowpush` (where the worktree is) -----

def allowed(flow_info: dict, branch_id: str, pr_to: str | None) -> tuple[str, str | None]:
    """The git names the grant lets this push (and change) use; FenceError otherwise."""
    grant = flow_info.get("grant")
    if not grant:
        raise FenceError(flow_info.get("why") or "no flow move is granted on this card")
    if branch_id not in grant["pushes"]:
        raise FenceError(f"{grant['label']} pushes {', '.join(grant['pushes']) or 'nothing'}, "
                         f"not {branch_id}")
    if pr_to is not None and pr_to not in grant["opens"]:
        raise FenceError(f"{grant['label']} opens {', '.join(grant['opens']) or 'none'}, not {pr_to}")
    return grant["pushes"][branch_id], (grant["opens"][pr_to] if pr_to is not None else None)


def push(flow_info: dict, branch_id: str, cwd) -> dict:
    """Push HEAD to the flow branch `branch_id` under the grant, never forced."""
    name, _ = allowed(flow_info, branch_id, None)
    head = git_out(cwd, "rev-parse", "HEAD")
    if not head:
        raise FenceError(f"{cwd} is not a git worktree")
    # c-729: the move is the user's tap, so it pushes by the same rule as the Push: through a
    # copy's fence to the remote's address (`landpush.push_to`), else to the remote as before
    from keel import landpush      # noqa: PLC0415 - landpush reads merging, which is heavy
    done = landpush.push_to(Path(cwd), remote_in(flow_info), head, name)
    if done.returncode != 0:
        said = (done.stderr.strip() or done.stdout.strip()).splitlines()
        raise FenceError(f"git push to {name} was refused (it is never forced: fetch, merge "
                         f"again, and retry): {said[-1] if said else done.returncode}")
    return {"move": flow_info["grant"]["move"], "pushed": name, "head": head[:12]}


def open_pr(cfg, flow_info: dict, pr_to: str, source: str, cwd) -> str:
    """The space's pack opens the change the move names (`pr <id> --flow <branch> --to
    <target> --dir <worktree>`, the worktree saying which repo) and prints its URL."""
    from keel import adapters      # noqa: PLC0415 - only a pull request needs the pack
    grant = flow_info.get("grant") or {}
    if pr_to not in (grant.get("opens") or {}):
        raise FenceError(f"{grant.get('label') or 'no move'} opens {', '.join(grant.get('opens') or {}) or 'none'}, not {pr_to}")
    target = grant["opens"][pr_to]
    space = cfg.spaces.get(flow_info.get("space") or "")
    if space is None:
        raise FenceError(f"the {flow_info.get('space')} space's pack is not on this machine")
    top = git_out(cwd, "rev-parse", "--show-toplevel") or str(cwd)
    try:
        said = adapters.run(space, "pr", flow_info["card"], "--flow", source, "--to", target, "--dir", top)
    except adapters.AdapterError as error:
        what = terms.say(terms.of(cfg, space), "the {change}")
        raise FenceError(f"{what} to {target} was not opened: {error}") from None
    return said.strip().splitlines()[-1] if said.strip() else ""


def note(done: dict) -> str:
    return f"flow move {done['move']}: pushed {done['pushed']} at {done['head']}"
