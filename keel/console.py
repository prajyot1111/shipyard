"""Bosun's session: its settings, its state and status; the taps themselves (start, stop,
restart) are `keel/consoletaps.py` (c-517, BO-1, c-531; docs/atlas/96-bosun.md).

Bosun is ONE `claude --bg --remote-control Bosun` session on this machine, where the board
and the deck are (c-622). It is not a card and not a house: it has no `KEEL_CARD`, no fence and no
worktree, and it runs in Keel's root with his own permission mode. Three things make it
Bosun rather than any session:

- `KEEL_BOSUN` in its environment, which `kb` turns into actor `bosun` and never `human`
  (`cli.resolve_actor`); his token is withheld from every child anyway (`keel/childenv.py`)
  and its file is denied by the settings (`house.secret_deny`).
- A SessionStart hook that prints its memory, the install's `memory/bosun/` (c-722; the
  checkout's `bosun/memory/` until the move) (`keel console memory`), so who it is and
  what it may do arrive on start, on resume and after every compaction, by mechanism.
- `state/console.json`, what the harness cannot say: the session it last started, its app
  link, when it came up, and the last taps on it. Whether it is UP is never kept there: it
  is read from `claude agents --json` on every status.

Start resumes the last session when there is one (his context survives a Stop), Restart
starts a fresh one from the memory. Nothing starts, stops or restarts it by itself: every
call here is his tap, from `keel console <verb>` or from the deck
(`actions.act_console`). The one exception is his ANSWER to an ask (c-521,
`keel/asks.py`): the drain on this machine WAKES Bosun with it (`keel/consolewake.py`), by a
message into its live session, only when it is idle, and never by a stop or a start (c-530).

A row the listing keeps with no process (a killed Bosun: no pid and no status, c-530) is
STUCK: it is not up, and Start and Restart start a fresh Bosun past it instead of refusing.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from keel import atomicfile, authority, builder, harness, house, housetier, memoryroot
from keel import config as config_module
from keel.config import Config
from keel.harness import owner_of      # not through `harness`: tests replace that name

NAME = "Bosun"
# The space whose settings Bosun's session takes (its deny list, its model and its config
# dir): personal, the space of every card it builds. The console space it had until c-593
# is retired.
SPACE = "personal"
# The name Bosun wears where a card's space would go: the voice page's iris for it
# (`bosuntalk.pseudo`) and the Bosun page's palette (`app/theme-console.css`). Not a space.
LABEL = "console"
STATE_FILE = "console.json"
SETTINGS_DIR = "console"
BOSUN_ENV = "KEEL_BOSUN"
HISTORY_MAX = 20
OPS = ("start", "stop", "restart")
# The old wake's gate (c-521), which c-530's message made moot: dropped on the next launch.
STALE_MARK = "wake_keeps_id"
# The memory, in the order it is read: the index first, then what each file is for. It is
# the install's `memory/bosun` (c-722, `memory_dir`); this is the checkout's own, read only
# while the install has none.
MEMORY_DIR = Path("bosun") / "memory"
MEMORY_FILES = ("MEMORY.md", "identity.md", "needs-you.md", "authority.md", "builder.md", "requests.md",
                "asks.md", "runbook.md")
# Read last, and only by the in-app builder (`keel/builder.py`): what is different for it.
IN_APP_MEMORY = "in-app.md"
DEFAULTS = {"host": None, "permission_mode": "auto", "context_window": 1_000_000,
            "compact_at": 70}
# How much of the transcript's end is read for the last turn and its usage: a turn's
# records are a few KB, so this holds several even with a large tool result among them.
TAIL_BYTES = 256 * 1024
# The PreCompact hook's budget: two board reads of five seconds each, and the rest is local.
HANDOFF_TIMEOUT = 20

START_PROMPT = ("You are Bosun, started fresh by the user's tap. Your memory is in your context "
                "above. Say in one line that you are up, then wait for the user.")
RESUME_PROMPT = ("Started again by the user's tap, after a Stop. Carry on from where you were; "
                 "if nothing was in hand, say in one line that you are back and wait.")


class ConsoleError(Exception):
    """A tap that cannot be carried out here, with the sentence the page shows."""



# ----- where things are -----

def conf(cfg: Config) -> dict:
    """`[console]` with its defaults."""
    return {**DEFAULTS, **(cfg.console or {})}


def configured(cfg: Config) -> bool:
    """True when this config has a Bosun: an install, or a config whose `[console]` table
    names a `host`, with the personal space Bosun takes its settings from. The host named is
    always this machine (c-622, `oldconfig.console_host`), so the key only says there is a
    Bosun: the shipped example (etc/shipyard.example.toml) names none, and a checkout's own
    config has no session."""
    return SPACE in cfg.spaces and (cfg.install_home is not None or bool(conf(cfg)["host"]))


def space_of(cfg: Config):
    space = cfg.spaces.get(SPACE)
    if space is None:
        raise ConsoleError(f"no [spaces.{SPACE}] table: Bosun takes its settings from it")
    return space


def config_dir(cfg: Config) -> Path:
    """Bosun's config dir: the personal space's. It runs as the user Keel runs as (c-648)."""
    return space_of(cfg).config_dir


def cwd(cfg: Config) -> Path:
    """Where its session runs: the builder's clones (`<install>/builder/`, where it works),
    else Keel's root."""
    return builder.clones(cfg) if builder.in_app(cfg) else cfg.root


def builds_itself(cfg: Config) -> bool:
    """Builder mode as the superuser: its authority is its own to build (the in-app builder's
    never is)."""
    return bool(cfg.bosun_builder) and not builder.in_app(cfg)


def permission_mode(cfg: Config) -> str:
    """The builder's on an install (`[builder] mode`: auto, or bypass for the superbuilder,
    `builder.permission_mode`), else `[console] permission_mode`."""
    return builder.permission_mode(cfg) if builder.in_app(cfg) else str(conf(cfg)["permission_mode"])


def refuse_builder(cfg: Config) -> None:
    """Why Bosun may not start, raised; first the builder's missing clones are made (a repo
    newly listed in `[builder] repos` gets its clone on the Start after)."""
    why = other_owner(cfg)
    if why:
        raise ConsoleError(why)
    try:
        builder.ensure_clones(cfg)
    except (OSError, subprocess.SubprocessError) as error:
        raise ConsoleError(f"could not clone a repo for the builder: {error}") from None
    why = builder.refusal(cfg)
    if why:
        raise ConsoleError(why)


def other_owner(cfg: Config) -> str | None:
    """Why Bosun may not start under a config dir another Unix user owns, or None. The
    harness would run its `claude` as that user through sudo (`harness.command`), while its
    settings, with its key, are written 0600 in this user's own directory: Bosun runs as the
    user Keel runs as (c-648)."""
    try:
        owner = owner_of(config_dir(cfg))
    except ConsoleError:
        return None
    if owner is None:
        return None
    return (f"Bosun's config dir {config_dir(cfg)} belongs to the Unix user {owner.pw_name}, "
            f"and Bosun runs only as the user Keel runs as: make that directory this user's")


def start_refusal(cfg: Config, cloned_at_start: bool = False) -> str | None:
    """Why a Start would be refused before anything is launched, or None: the config dir's
    owner, then the builder's own refusals. What the doctor and the readiness row show."""
    return other_owner(cfg) or builder.refusal(cfg, cloned_at_start=cloned_at_start)


def state_path(cfg: Config) -> Path:
    return Path(cfg.state_dir) / STATE_FILE


def settings_path(cfg: Config) -> Path:
    """Beside the shared key, not under `state/`: its env holds Bosun's key (c-553)."""
    return housetier.bosun_settings_path(cfg)


def memory_dir(cfg: Config) -> Path:
    """Where Bosun's memory is read from (c-722, `keel/memoryroot.py`): the install's
    `memory/bosun` once it holds one, else the checkout's `bosun/memory`."""
    return memoryroot.bosun_dir(cfg)


def memory_text(cfg: Config) -> str:
    """Bosun's memory as one text, the index first: what the SessionStart hook prints. Each
    file is headed by its full path, so Bosun knows where its memory lives."""
    parts = []
    directory = memory_dir(cfg)
    for name in MEMORY_FILES + ((IN_APP_MEMORY,) if builder.in_app(cfg) else ()):
        path = directory / name
        if path.is_file():
            parts.append(f"<!-- {path} -->\n{path.read_text().strip()}\n")
    return "\n".join(parts)


# ----- the session's settings and environment -----

def memory_hook(cfg: Config) -> str:
    return f"{cfg.root / 'bin' / 'keel'} console memory"


def handoff_hook(cfg: Config) -> str:
    """Before every compaction: the handoff note (`keel/consolehandoff.py`, c-524)."""
    return f"{cfg.root / 'bin' / 'keel'} console handoff"


def compact_env(cfg: Config) -> dict:
    """Where the harness compacts: `compact_at` percent of `context_window`, the mark the page
    draws. In the settings' env, because a `--bg` session does not inherit the launching
    process's environment (probed 2026-09-26, c-524); the harness clamps the window to
    100k..1M."""
    settings_ = conf(cfg)
    return {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": str(int(settings_["context_window"])),
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": str(int(settings_["compact_at"]))}


def requests_hook(cfg: Config) -> str:
    """Before each message he sends it: the open requests, printed as context atop the
    message (`kb console hook`, c-520). The only way a request reaches Bosun: none wakes it."""
    return f"{cfg.root / 'bin' / 'kb'} console hook"


# Bosun never taps itself: the lifecycle is his (`main` refuses under BOSUN_ENV too).
SELF_DENY = tuple(f"Bash(*keel console {op}*)" for op in OPS)


def reach_deny(cfg: Config) -> list[str]:
    """What Bosun's tools may not open: the work space's config dir (the work credentials
    live there, and Bosun holds none) and the shared house key (its own key is derived
    from it). Read, the editing tools and Bash, the same forms
    `house.secret_deny` writes. Rules for Claude's own tools, not a Unix boundary."""
    files = [housetier.shared_path(cfg), settings_path(cfg)]     # its own key is in the second
    paths = list(files)
    work = cfg.spaces.get("work")
    if work is not None and work.config_dir != config_dir(cfg):
        paths.append(work.config_dir)
    rules = []
    for path in paths:
        target = path if path in files else f"{path}/**"         # the key files, then a dir
        rules += [f"Read(/{target})", f"Edit(/{target})", f"Bash(*{path}*)"]
    return rules


def settings(cfg: Config) -> dict:
    """Its hooks, its deny list and its environment: the SessionStart hook that loads its
    memory, the UserPromptSubmit hook that puts the open requests atop his message, the stack guard every house gets (`house.guard_hooks`, which personal's config
    dir does not carry), the space's deny list, his secrets, and its own lifecycle."""
    # `KEEL_BOSUN` here (c-553, his answer to c-536): a `--bg` session runs in the daemon's
    # pre-spawned spare and never sees the launching process's environment, so the key rides
    # where every session and hook reads it. The file is 0600 beside the shared key
    # (`settings_path`), and Bosun's own tools are denied it (`reach_deny`).
    # KEEL_CARD emptied (c-524 review F2): the process a `--bg` session runs in is the
    # daemon's spare, whose environment can carry the KEEL_CARD of whichever house started
    # the daemon (`keel/house.py`), and that would make Bosun's `kb` and its hooks a house.
    # An empty one reads as unset (`cli.resolve_actor`).
    env = {"KEEL_HOME": str(cfg.root), "KEEL_CARD": "", BOSUN_ENV: key_of(cfg), **compact_env(cfg)}
    hooks = {"SessionStart": [{"hooks": [{"type": "command", "command": memory_hook(cfg)}]}],
             "UserPromptSubmit": [{"hooks": [{"type": "command", "command": requests_hook(cfg),
                                              "timeout": 10}]}],
             "PreCompact": [{"hooks": [{"type": "command", "command": handoff_hook(cfg),
                                        "timeout": HANDOFF_TIMEOUT}]}]}
    hooks["PreToolUse"] = house.guard_hooks(cfg) + [authority_hook(cfg)]
    deny = (list(space_of(cfg).deny) + house.secret_deny(cfg) + list(SELF_DENY) + reach_deny(cfg)
            + ([] if builds_itself(cfg) else authority_deny(cfg)))
    # Its own allow rules and no others: the space's allow list is a house's (c-769).
    allow = kb_allow(cfg) + (builder_allow() if builds_itself(cfg) else [])
    made = {"hooks": hooks, "permissions": {"deny": deny, "allow": allow}, "env": env}
    if builder.in_app(cfg):
        return builder.settings(cfg, made)
    if conf(cfg)["permission_mode"] == "bypassPermissions":
        # A bypass session HOLDS a peer message from a session in another permission mode
        # ("Held peer message ... set crossSessionInbound to accept", seen on its first
        # start, 2026-09-29). The drain's wake is such a message, so it is accepted.
        made["crossSessionInbound"] = "accept"
    return made


# ----- its authority, as files (c-522) -----

GUARD_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"
# The `kb` verbs Bosun runs as part of building its cards, allowed by rule so the auto-mode
# classifier is not the one deciding whether Bosun may pass a gate: builder mode and the
# checks are `keel/authority.py`'s, where the board lives.
KB_ALLOWED = ("approve", "console", "show", "list", "lint", "note", "tree", "needs-you")


def authority_hook(cfg: Config) -> dict:
    """The PreToolUse guard that refuses Bosun a write to its own authority."""
    return house.command_hook(f"{cfg.root / 'bin' / 'keel'} console guard",
                              matcher=GUARD_MATCHER, timeout=10)


def authority_deny(cfg: Config) -> list[str]:
    """The editing tools denied on the same paths the guard holds (the DOUBLE leading slash
    H6 requires); the guard is what catches a Bash write."""
    rules = []
    install = getattr(cfg, "install_home", None)
    guarded = [cfg.root / rel for rel in authority.AUTHORITY_PATHS]
    guarded += [install / rel for rel in authority.INSTALL_AUTHORITY_PATHS] if install else []
    for path in guarded:
        target = f"{path}/**" if path.suffix != ".py" else str(path)
        rules.append(f"Edit(/{target})")      # Edit(path) covers every editing tool
    return rules


def kb_allow(cfg: Config) -> list[str]:
    kb = cfg.root / "bin" / "kb"
    return [f"Bash({prefix} {verb}:*)" for verb in KB_ALLOWED for prefix in ("kb", str(kb))]


# Builder mode (`[keel] bosun_builder`): the git and test steps of building on a branch,
# allowed by rule so the auto-mode classifier does not stop Bosun building Keel. Never a
# push, a merge or a rebase: those would move `next` or the live checkout around the landing,
# and they stay the classifier's to judge.
BUILDER_GIT = ("worktree", "add", "commit", "diff", "log", "status", "show", "branch", "fetch",
               "stash", "rev-parse")
BUILDER_MAKE = ("test", "test-changed", "test-core", "test-all")


def builder_allow() -> list[str]:
    return ([f"Bash(git {verb}:*)" for verb in BUILDER_GIT]
            + [f"Bash(make {target}:*)" for target in BUILDER_MAKE])


# A Bash command that writes: a redirect, or a command that changes files. Naming an authority
# path in one is refused; reading one (cat, grep, git log) is not.
WRITES = re.compile(r"(\btee\b|\bsed\s+(-\S*\s+)*-i|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bln\b|"
                    r"\bchmod\b|\bgit\s+(checkout|restore|apply|am|reset|rm|mv)\b|\bpatch\b|"
                    r"\bdd\b|\binstall\b|\bperl\s+-\S*i|open\()")
# A git command that changes a repo's files or history, its options before the subcommand
# allowed (`git -C <dir> reset`, `git --git-dir=<d> update-ref`): r1.F2.
GIT_WRITES = re.compile(r"\bgit\b[^;&|]*?\s(checkout|restore|apply|am|reset|rm|mv|commit|merge|"
                        r"rebase|pull|stash|clean|update-ref|cherry-pick|revert|switch|branch|"
                        r"tag|config|gc|prune|filter-branch|worktree|init)\b")


def guard_verdict(cfg: Config, payload: dict) -> str | None:
    """Why this tool call is refused to Bosun, or None when it may go on."""
    tool = str(payload.get("tool_name") or "")
    given = payload.get("tool_input") or {}
    if tool == "Bash":
        command = str(given.get("command") or "")
        # Quotes are taken out first, so a path split by them is still the path it spells.
        plain = re.sub(r"['\"\\]", "", command)
        named = [rel for rel in authority.AUTHORITY_PATHS if rel in plain]
        # Its settings file holds its hooks, its denies and its key, outside Keel's root
        # (c-553): named by its file name, however the directory is spelled.
        named += [housetier.BOSUN_SETTINGS_NAME] if housetier.BOSUN_SETTINGS_NAME in plain else []
        # Any redirect counts once an authority path is named, wherever the path sits (`cd
        # bosun/memory && echo x >> f`, `p=...; echo x > $p`); only a redirect to /dev/null
        # or to another descriptor is a read's, so `cat bosun/memory/x.md 2>/dev/null` passes.
        redirects = re.sub(r"\d*>>?\s*(/dev/null|&\d+)", "", plain)
        writes = bool(WRITES.search(plain) or GIT_WRITES.search(plain))
        install, cwd = getattr(cfg, "install_home", None), payload.get("cwd")
        # The install's Bosun memory named anywhere in the text, however the rest is spelled
        # (as before r1.F2, no exclusion, `authority.text_hits`), and the memory roots by any
        # spelling (r1.F2): the install's whole root, its git repo too, and the checkout's
        # `bosun/memory` through a directory that holds it.
        for rel in (authority.text_hits(plain, install)
                    + authority.bash_hits(command, cfg.root, install, writes, ">" in redirects, cwd)):
            named += [rel] if rel not in named else []
        if builds_itself(cfg):
            # Builder mode: its authority is Bosun's to build; its settings (its key) are not.
            named = [rel for rel in named if rel == housetier.BOSUN_SETTINGS_NAME]
        if named and (">" in redirects or writes):
            return (f"{named[0]} is Bosun's own authority: changing it is a personal card he "
                    f"approves, never Bosun's own write")
        return None
    path = given.get("file_path") or given.get("notebook_path")
    hit = (authority.authority_hit(cfg.root, str(path), getattr(cfg, "install_home", None))
           if path and not builds_itself(cfg) else None)
    if path and Path(str(path)).name == housetier.BOSUN_SETTINGS_NAME:
        hit = housetier.BOSUN_SETTINGS_NAME
    if hit:
        return (f"{hit} is Bosun's own authority: changing it is a personal card he approves, "
                f"never Bosun's own write")
    return None


def guard(cfg: Config, stdin) -> dict | None:
    """`keel console guard`: the hook's answer, a PreToolUse deny or nothing."""
    try:
        payload = json.loads(stdin.read() or "{}")
    except ValueError:
        return None
    why = guard_verdict(cfg, payload)
    if why is None:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": why}}


def write_settings(cfg: Config) -> Path:
    path = settings_path(cfg)
    text = json.dumps(settings(cfg), indent=2) + "\n"      # refused first when there is no key
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)  # the credentials directory's mode
    path.parent.chmod(0o700)
    atomicfile.write_text(path, text, mode=0o600)
    return path


def key_of(cfg: Config) -> str:
    key = authority.bosun_key(cfg)
    if not key:
        raise ConsoleError(f"this machine holds no shared key ({housetier.shared_path(cfg)}), "
                           f"so Bosun would have no key and its kb would be refused")
    return key


def launch_env(cfg: Config) -> dict:
    """The process environment it starts with: its config dir and Keel's root; no card, and
    (as for every child) no token. NOT its key (c-553): the key rides in its settings, and a
    launch that carried it would hand it to the daemon it spawns, and so to every house that
    daemon's spares later run."""
    env = harness.scoped_env(config_dir(cfg))
    env.pop("KEEL_CARD", None)
    key_of(cfg)                     # refused here too, before anything is started
    env["KEEL_HOME"] = str(cfg.root)
    if builder.in_app(cfg):
        env["KEEL_CONFIG"] = str(cfg.source)
    return env


# ----- console.json -----

def read_state(cfg: Config) -> dict:
    try:
        data = json.loads(state_path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(cfg: Config, data: dict) -> None:
    atomicfile.write_text(state_path(cfg), json.dumps(data, indent=1) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def noted(data: dict, what: str, actor: str, session: str | None) -> dict:
    """`data` with one tap added to its history, the newest last, at most HISTORY_MAX."""
    history = list(data.get("history") or [])
    history.append({"at": now_iso(), "what": what, "by": actor, "session": session})
    return dict(data, history=history[-HISTORY_MAX:])


# ----- the transcript: last turn, model and context used -----

def transcript_of(config_dir: Path, session_id: str | None) -> Path | None:
    if not session_id:
        return None
    found = sorted(Path(config_dir).glob(f"projects/*/{session_id}.jsonl"))
    return found[0] if found else None


def tail_bytes(path: Path, size: int) -> tuple[bytes, bool]:
    """The last `size` bytes of a file, and whether it was cut."""
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        handle.seek(max(0, end - size))
        return handle.read(), end > size


def tail_records(path: Path, size: int = TAIL_BYTES) -> list[dict]:
    """The whole records in the last `size` bytes of a jsonl, oldest first; none from a file
    that cannot be opened."""
    try:
        raw, cut = tail_bytes(path, size)
    except OSError:
        return []
    lines = raw.split(b"\n")
    if cut:
        lines = lines[1:]           # the first line was cut part way through
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def turn_facts(records: list[dict], window: int) -> dict:
    """The last turn's time, the model it ran on and how much context it filled."""
    facts = {"last_turn": None, "model": None, "used": None, "percent": None}
    for record in reversed(records):
        if record.get("timestamp") and facts["last_turn"] is None:
            facts["last_turn"] = record["timestamp"]
        message = record.get("message") if record.get("type") == "assistant" else None
        usage = (message or {}).get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict) and not record.get("isSidechain"):
            used = sum(int(usage.get(key) or 0) for key in (
                "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            facts.update(model=message.get("model"), used=used,
                         percent=round(100 * used / window) if window else None)
            break
    return facts


# ----- status -----

def running_row(cfg: Config, data: dict, strict: bool = False) -> dict | None:
    """Its `claude agents --json` row, by the session it last started, or None. `strict`
    (every tap) raises when the listing itself failed: a Start must never read a failed
    listing as "not running" and resume a Bosun that is up."""
    session = data.get("session_id")
    if not session:
        return None
    return harness.find(session, harness.agents(config_dir(cfg), strict=strict))


def stuck(row: dict) -> bool:
    """A listed row with no process behind it, as the listing itself says it: probed
    2026-09-26 (c-530), a killed background session stays listed with no `pid` and no
    `status`. A live session waiting on its user is `blocked` too, but it has both."""
    return row.get("pid") is None and row.get("status") is None


def status(cfg: Config) -> dict:
    """What the strip shows, all derived now except what only console.json can say."""
    data, settings_ = read_state(cfg), conf(cfg)
    row = running_row(cfg, data)
    dead = row is not None and stuck(row)
    if dead:
        row = None
    if row is not None and not data.get("app_link"):
        data = late_link(cfg, data, row)
    window = int(settings_["context_window"])
    path = transcript_of(config_dir(cfg), data.get("session_id"))
    facts = turn_facts(tail_records(path), window) if path else turn_facts([], window)
    if row is not None:
        word = "working" if row.get("status") == "busy" else "idle"
    else:
        word = "stuck" if dead else "stopped" if data.get("session_id") else "never"
    return {"state": word, "up": row is not None,
            "session_id": data.get("session_id"), "bg_id": data.get("bg_id"),
            "app_link": data.get("app_link") if row is not None else None,
            "up_since": data.get("up_since") if row is not None else None,
            "last_turn": facts["last_turn"], "model": facts["model"] or space_of(cfg).model,
            "context": {"used": facts["used"], "window": window, "percent": facts["percent"],
                        "compact_at": int(settings_["compact_at"])},
            "history": list(data.get("history") or []), "builder": builder.status(cfg)}


_asked_link: dict[str, float] = {}
LINK_ASK_SECONDS = 60


def late_link(cfg: Config, data: dict, row: dict) -> dict:
    """The app link a launch did not see within its few seconds, asked of the log again
    and kept once it is there, so Open in Claude app does not wait for a Restart.

    A log with no link is asked again at most once a minute per session (it is a `claude
    logs` run, and a status runs on every push). A link found is written only under the tap
    lock, taken without waiting: a tap under way owns the file, so the link waits for the
    next status, and is then written into what is on disk for that same session."""
    bg_id = row.get("id") or data.get("bg_id") or ""
    if time.time() - _asked_link.get(bg_id, 0.0) < LINK_ASK_SECONDS:
        return data
    try:
        link = harness.remote_link(bg_id, config_dir(cfg))
    except harness.HarnessError:
        link = None
    if not link:
        _asked_link[bg_id] = time.time()    # only a log with no link spends the minute
        return data
    with held_lock(cfg) as held:
        if not held:
            return data
        now_on_disk = read_state(cfg)
        if now_on_disk.get("session_id") != data.get("session_id") or now_on_disk.get("app_link"):
            return now_on_disk
        data = dict(now_on_disk, app_link=link)
        write_state(cfg, data)
    return data


# ----- the tap lock, and whether there is a Bosun -----

NO_BOSUN = "this config has no Bosun: it is not an install, and [console] host is unset"


def refuse_unconfigured(cfg: Config) -> None:
    if not configured(cfg):
        raise ConsoleError(NO_BOSUN)


def lock_path(cfg: Config) -> Path:
    return Path(cfg.state_dir) / SETTINGS_DIR / "lock"


@contextlib.contextmanager
def held_lock(cfg: Config):
    """The tap lock, taken without waiting: yields True when this caller holds it."""
    path = lock_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


# ----- what the deck draws -----

_seen = {"at": 0.0, "status": None}
LOCAL_SECONDS = 10


def view(cfg: Config) -> dict | None:
    """What the deck draws: the status, read at most every LOCAL_SECONDS (the deck builds
    its state often); None when this config has no Bosun."""
    if not configured(cfg):
        return None
    if _seen["status"] is None or time.time() - _seen["at"] > LOCAL_SECONDS:
        _seen.update(at=time.time(), status=status(cfg))
    return dict(_seen["status"])


def forget_view() -> None:
    """Drop the status the deck holds, so the next read is fresh (after a tap)."""
    _seen.update(at=0.0, status=None)


# ----- his terminal -----

def attach_argv(cfg: Config, bg_id: str) -> tuple[list[str], dict, str]:
    """`claude attach <bg_id>` under Bosun's config dir, in Keel's root."""
    env = harness.scoped_env(config_dir(cfg))
    full, run_env, cwd = harness.command(["attach", bg_id], env, str(cfg.root))
    return full, run_env if run_env is not None else env, cwd or str(cfg.root)


def attach(cfg: Config) -> int:
    """`keel console attach`: his terminal joins the running Bosun, the same session (what he
    types lands in its conversation; Ctrl+Z steps out and it keeps running). A Bosun that is
    down is started first, by this tap. Never a `--resume`: on a live session that is a copy."""
    from keel import consoletaps     # it reads this module: imported here, not at the top
    row = running_row(cfg, read_state(cfg), strict=True)
    if row is None or stuck(row):
        consoletaps.tap(cfg, "start", "cli")
    data = read_state(cfg)
    bg_id = data.get("bg_id")
    if not bg_id:
        raise ConsoleError("Bosun has no running session to join")
    argv, env, cwd = attach_argv(cfg, bg_id)
    os.chdir(cwd)
    os.execvpe(argv[0], argv, env)


# ----- `keel console <verb>` -----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel console", description="Bosun's session")
    parser.add_argument("verb", choices=(*OPS, "status", "memory", "guard", "handoff", "attach"))
    parser.add_argument("--json", action="store_true")
    return parser


def say(result: dict) -> str:
    context = result.get("context") or {}
    line = f"Bosun is {result['state']}"
    if result.get("up_since"):
        line += f", up since {result['up_since']}"
    if context.get("percent") is not None:
        line += f", context {context['percent']}%"
    if result.get("app_link"):
        line += f"\n{result['app_link']}"
    return line


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_module.load()
    if args.verb == "memory":
        from keel import consolehandoff     # it reads this module: imported here, not at the top
        print(consolehandoff.session_start(cfg, sys.stdin))
        return 0
    if args.verb == "handoff":
        from keel import consolehandoff
        print(consolehandoff.main_hook(cfg, sys.stdin))
        return 0
    if args.verb == "guard":
        answer = guard(cfg, sys.stdin)
        if answer is not None:
            print(json.dumps(answer))
        return 0
    if args.verb in (*OPS, "attach") and os.environ.get(BOSUN_ENV):
        print(f"keel console {args.verb}: Bosun's lifecycle is his tap, never Bosun's own",
              file=sys.stderr)
        return 1
    try:
        refuse_unconfigured(cfg)
        if args.verb == "attach":
            return attach(cfg)
        if args.verb == "status":
            result = status(cfg)
        else:
            from keel import consoletaps     # it reads this module: imported here, not at the top
            result = consoletaps.tap(cfg, args.verb, "cli")
    except ConsoleError as error:
        print(f"keel console {args.verb}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=1) if args.json else say(result))
    return 0
