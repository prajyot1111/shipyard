"""The stuck states outside setup (c-678): what happened, in a sentence, and its fix.

A block is a line Keel wrote for itself: "house failed to start: ...", "outcome not merged:
/x/repo has uncommitted changes on main; commit or stash them, then approve again". The
first-run design asks that every such state reads the way a failed check does on the setup
pages: what happened, the fix on the page, and Bosun's session as the third part
(`K.stuck`, app/ui.stuck.js). This module is the reading and the fixes.

`read(cfg, card)` turns a card's block into `{kind, what, fix | commands, said}`, or None
for a block that is not one of these (a session's question is the session's own words, and
stays as it is). The card keeps its block untouched: this is a reading of it, made each
time, never stored.

| kind | the block | the fix |
|---|---|---|
| `no-model` | no model on the card | the space's default set (`stuck.model`), then a fresh start |
| `start-failed` | the session failed to start | Try again (`house.retry`) |
| `land-tests` | the merged tree's tests were red | Send back with the failures (`sendback`) |
| `land-dirty` | the folder landed into has uncommitted changes | Keel's own copy: Set them aside and land (`land.aside`, then `unblock` of that block, then Approve). A folder the user attached: two commands to copy |
| `land-file` | the repo's CLAUDE.md changed since it was adopted or saved, and the test command comes from it | while it stands changed, Open the file to save it (the step); once it is saved, Unblock and land (`unblock` of that block, then Approve) |
| `land-lock` | a git lock file was left behind | Remove the stale lock and land (`land.unlock`, then `unblock` of that block, then Approve) |
| `land-identity` | git has no name and email | the Check this computer step, where they are set |
| `land-other` | anything else git said | none: the line itself |

Two more stuck states live where their facts do, and this module holds their fixes:
`restart_services` (`services.restart`) restarts the drain's service (a real restart of a
job that is loaded, a start of one that is installed and stopped); `unknown_keys` reads
the config loader's unknown-key warnings, and `remove_key` and `rename_key`
(`setup.config.remove`, `setup.config.rename`) fix one.

Every fix is the page's verb, so each is the user's tap. None is forced: a stash is a
stash, and a key Keel knows is never removed this way.

NOT HERE, on purpose: a card whose pull request's branch was rewritten outside Keel. The
design asks for a button that brings the working copy in line. Keel moves no branch there
(c-653, Atlas 10: a tap that did was built and taken out, after three reviews each found a
way it could lose work), so the card still says what is so and gives the command to copy
(`keel/shipstep.py`), and nothing here runs it.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from keel import appservices, childenv, cloneerrors, configedit, drainprobe, oldwords, receipt, repocommands, repolayout
from keel import config as config_module
from keel import service as service_module
from keel import settings
from keel.setupconfig import SetupError, edit

GIT_SECONDS = 60
NO_MODEL = re.compile(r"^no model on ")
START_FAILED = re.compile(r"^house failed to start:\s*(?P<why>.+)", re.DOTALL)
DIRTY = re.compile(r"(?P<repo>\S+) has uncommitted changes on (?P<target>[^;\s]+)")
TEST_COMMAND = re.compile(r"\(`(?P<command>[^`]+)` exited \d+\)")
FAILED_NAMES = re.compile(r"failed: (?P<names>[^;\n]+)")
MORE = re.compile(r" and (\d+) more$")
LOCK = "index.lock"
# A landing refused because the repo's own CLAUDE.md changed (`repocommands.REFUSED`). The
# block is read off the board, which may hold it in the earlier release's words, so it is
# matched through `oldwords.holds` and never with `in` (c-699 review F1).
FILE_CHANGED = "and Shipyard takes this repo's test command from that file"
# A lock younger than this may be a live git's: Keel's copy is written by the fetch before
# work, a push's merge, a branch switch and a stash, any of which may hold it (review F14).
LOCK_YOUNG = 30
IDENTITY = ("empty ident", "please tell me who you are", "unable to auto-detect email")
UNKNOWN = re.compile(r"^\[(?P<table>[^\]]+)\] (?P<key>\S+) is not a key(?:; did you mean (?P<near>[^?]+)\?)?$")
ASIDE = "keel: set aside before landing {card}"


class Refused(SetupError):
    """A fix that was not made; the message says why."""


def sentence(text: str) -> str:
    text = (text or "").strip()
    return text if not text or text[-1] in ".!?" else text + "."


def first_line(text: str) -> str:
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace",
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS, env=childenv.own_env())


# ----- the reading -----

def landing_repo(cfg, card: dict) -> tuple[Path | None, bool]:
    """`(the folder the card lands into, whether it is Keel's own copy)`."""
    space = (getattr(cfg, "spaces", None) or {}).get(card.get("space") or "")
    key = str(card.get("repo") or "").split(",")[0].strip()
    repo = space.repos.get(key) if space is not None and key else None
    if repo is None:
        return None, False
    own = repolayout.home_of(Path(repo), repolayout.spaces_of(cfg)) is not None
    return Path(repo), own


def changed_files(repo: Path) -> list[str]:
    try:
        done = git(repo, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({line[3:].split(" -> ")[-1].strip() for line in done.stdout.splitlines() if len(line) > 3})


def default_model(cfg, card: dict) -> str:
    space = (getattr(cfg, "spaces", None) or {}).get(card.get("space") or "")
    return (getattr(space, "model", None) if space else None) or cfg.model


def read(cfg, card: dict, board=None) -> dict | None:
    """What a blocked card's block says happened and its fix, or None for any other block."""
    reason = card.get("blocked_reason") or ""
    card_id = card["id"]
    if NO_MODEL.match(reason):
        model = default_model(cfg, card)
        return {"kind": "no-model", "said": reason,
                "what": f"No session started for {card_id}: this card names no model, and Shipyard never guesses one.",
                "fix": {"label": f"Use {model} (this space's default) and start",
                        "body": {"verb": "stuck.model", "id": card_id}, "then": "house.retry"}}
    failed = START_FAILED.match(reason)
    if failed:
        return {"kind": "start-failed", "said": reason,
                "what": f"No session started for {card_id}: {sentence(first_line(failed['why']))}",
                "fix": {"label": "Try again", "body": {"verb": "house.retry", "id": card_id}}}
    if receipt.refused_block(card):
        return landing(cfg, card, reason[len(receipt.NOT_MERGED):].strip(), reason, board)
    return None


def lands(label: str, card_id: str, reason: str, verb: str | None = None) -> dict:
    """A fix that clears the way and lands the card, for every refused landing that has one
    (c-678 fix check), so the three cannot drift apart. In order: the fix's own `verb`,
    where it has one; the deck's own `unblock` of THIS block (`expect`, so a block written
    since is never lifted); then Approve. The page sends each only when the server took the
    one before, and Approve only when the card the unblock answered with is no longer
    blocked: an unblock whose `expect` no longer matches is not refused, it answers with
    the card as it is, blocked on something else (app/ui.stuckcard.js `follow`). A bare Approve after the verb is refused on a blocked
    card where landings are queued (`Board._refuse_land`).

    With a verb the page is told to follow it with both (`then: "land"`, and the block to
    lift in `expect`); with none, the unblock is the button's own verb and Approve follows."""
    if verb is None:
        return {"label": label, "then": "approve", "body": {"verb": "unblock", "id": card_id, "expect": reason}}
    return {"label": label, "then": "land", "expect": reason, "body": {"verb": verb, "id": card_id}}


def landing(cfg, card: dict, why: str, reason: str, board=None) -> dict:
    """A refused landing, by what refused it."""
    card_id, lowered = card["id"], why.lower()
    repo, own = landing_repo(cfg, card)
    if "tests failed" in lowered:
        command = TEST_COMMAND.search(why)
        return {"kind": "land-tests", "said": reason,
                "what": f"The merged result failed `{command['command'] if command else 'the tests'}`: "
                        f"{failed_count(why)} failed. Nothing landed.",
                "fix": {"label": "Send back with the failures",
                        "body": {"verb": "sendback", "id": card_id, "reason": reason}}}
    if DIRTY.search(why):
        files = changed_files(repo) if repo is not None else []
        what = ("The folder Shipyard lands into has changes that were never committed"
                + (f": {', '.join(files)}" if files else "") + ". Shipyard will not merge over them.")
        if own:
            return {"kind": "land-dirty", "said": reason, "what": what,
                    "fix": lands("Set them aside and land", card_id, reason, "land.aside")}
        return {"kind": "land-dirty", "what": what,
                "said": "This is your own folder, so Shipyard does not move what is in it. Set the changes aside, "
                        "approve again, then bring them back:",
                "commands": [f"git -C {repo} stash push", f"git -C {repo} stash pop"] if repo is not None else []}
    if oldwords.holds(why, FILE_CHANGED):
        # c-678 fix check r2.D4: the fix is in two steps, and the button is the second. While
        # the file still stands changed it opens the file's row (which has Keep this text).
        # Once the file's record matches, the card lands as every such fix does (`lands`).
        name = repocommands.first(card.get("repo"))
        fix = ({"label": "Open the file to save it", "step": "rules"}
               if repocommands.refusal(cfg, card.get("space"), card.get("repo"), board)
               else lands("Unblock and land", card_id, reason))
        return {"kind": "land-file", "said": reason, "fix": fix,
                "what": f"Nothing landed: {name}'s CLAUDE.md changed since it was adopted or saved, and Shipyard "
                        f"takes this repo's test command from that file."}
    if LOCK in why:
        found = {"kind": "land-lock", "said": reason,
                 "what": "The merge did not go through: a git lock file was left behind in the folder Shipyard lands into."}
        if own:
            # the label says the Approve that follows (review r2.F13): the tap lands the card
            found["fix"] = lands("Remove the stale lock and land", card_id, reason, "land.unlock")
        elif repo is not None:
            found["commands"] = [f"rm {repo}/.git/{LOCK}"]
        return found
    if any(word in lowered for word in IDENTITY):
        return {"kind": "land-identity", "said": reason,
                "what": "The merge did not go through: git does not know your name and email, which every merge records.",
                "fix": {"label": "Set your name and email", "step": "prerequisites"}}
    return {"kind": "land-other", "said": reason, "what": f"The merge did not go through: {sentence(first_line(why))}"}


def failed_count(why: str) -> int | str:
    """How many tests and jobs the refusal names as failed; "some" when it names none."""
    found = FAILED_NAMES.search(why)
    names = found["names"].strip() if found else ""
    if not names or names.startswith("none named"):
        return "some"
    more = MORE.search(names)
    listed = [name for name in MORE.sub("", names).split(",") if name.strip()]
    return len(listed) + (int(more.group(1)) if more else 0)


# ----- the fixes on a card -----

def stuck_card(cfg, board, card_id: str, kind: str, what: str) -> dict:
    card = board.get(card_id)
    found = read(cfg, card)
    if not found or found["kind"] != kind:
        raise Refused(f"{card_id} is {what}")
    return card


def set_model(cfg, board, card_id: str) -> dict:
    """`stuck.model` {id}: the space's default model on a card blocked for naming none. The
    page starts it afresh afterwards (`house.retry`), which lifts the block."""
    card = stuck_card(cfg, board, card_id, "no-model", "not waiting on a model")
    model = default_model(cfg, card)
    board.set_fields(card_id, {"model": model}, "human")
    return {"card": card_id, "model": model, "note": f"{card_id} runs on {model}"}


def own_copy(cfg, card: dict) -> Path:
    repo, own = landing_repo(cfg, card)
    if repo is None or not own:
        raise Refused(f"{card['id']} lands into your own folder, which Shipyard does not change: run the commands on the card")
    return repo


def set_aside(cfg, board, card_id: str) -> dict:
    """`land.aside` {id}: stash what was never committed in Keel's own copy, so the landing
    can go; the page approves again afterwards. The stash is named for the card and kept."""
    card = stuck_card(cfg, board, card_id, "land-dirty", "not held by changes that were never committed")
    repo = own_copy(cfg, card)
    done = git(repo, "stash", "push", "-m", ASIDE.format(card=card_id))
    if done.returncode != 0:
        raise Refused(f"git could not set the changes aside: {cloneerrors.last_line(done.stderr or done.stdout)}")
    return {"card": card_id, "note": f"set aside in Shipyard's copy as a stash; `git stash pop` there brings it back"}


def unlock(cfg, board, card_id: str) -> dict:
    """`land.unlock` {id}: remove the lock file a git that died left in Keel's own copy."""
    card = stuck_card(cfg, board, card_id, "land-lock", "not held by a git lock file")
    lock = own_copy(cfg, card) / ".git" / LOCK
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        age = None          # no lock there any more: nothing to remove, and nothing to wait for
    if age is not None and age < LOCK_YOUNG:
        raise Refused(f"The lock in Shipyard's copy was written {max(0, int(age))} seconds ago. A git command may "
                      f"still be running there. Wait a moment, then try again.")
    try:
        lock.unlink(missing_ok=True)
    except OSError as error:
        raise Refused(f"the lock file could not be removed: {error.strerror or error}") from None
    return {"card": card_id, "note": "the stale lock is removed"}


# ----- the services -----

NOT_RESTARTED = "The part of Shipyard that starts sessions and lands work could not be restarted from here: {why}"


def restart_services(cfg, manager=None) -> dict:
    """`services.restart`: the service that runs the drain (`keel/appservices.py`), restarted.

    A job the manager has loaded is hung or crash-looping when the deck says the drain is
    down, and a start leaves a running one as it is, so it gets the manager's real restart
    (`Manager.restart`, review F8). One that is installed and not loaded is started. One
    that was never installed is refused, and so is a start beside another drain of this
    user (`drainprobe.refusal`), as `shipyard service start` refuses it."""
    manager = manager or service_module.Manager(Path.home())
    drain = next(item for item in appservices.services(cfg, manager.home) if item.label.endswith(".drain"))
    try:
        loaded = manager.state(drain.label)[0]
        if not loaded and not any((manager.installed_dir / name).exists() for name in manager.files(drain)):
            raise Refused(NOT_RESTARTED.format(why="its service is not installed on this computer "
                                                   "(`shipyard service install` installs it)"))
        other = drainprobe.refusal(appservices.install_dir(cfg) / config_module.INSTALL_CONFIG)
        if other:
            raise Refused(NOT_RESTARTED.format(why=other))
        ok, said = manager.restart(drain.label) if loaded else manager.start(drain)
    except (OSError, subprocess.SubprocessError, appservices.NotAnInstall) as error:
        raise Refused(NOT_RESTARTED.format(why=error)) from None
    if not ok:
        raise Refused(NOT_RESTARTED.format(why=cloneerrors.last_line(said) or "the service manager gave no reason"))
    return {"note": f"{'restarted' if loaded else 'started'}: sessions start and work lands again in a moment"}


# ----- an unknown key in the config -----

def unknown_keys(cfg) -> list[dict]:
    """The loader's unknown-key warnings, read into `{table, key, near, what, line}`."""
    found = []
    for line in getattr(cfg, "warnings", None) or []:
        match = UNKNOWN.match(line)
        if match:
            found.append({"table": match["table"], "key": match["key"], "near": match["near"], "line": line,
                          "what": f"config.toml has a setting Shipyard does not know: `[{match['table']}] {match['key']}`. "
                                  f"It was ignored and the default is in use."})
    return found


def kind_of(table: str) -> str:
    return "space" if table.startswith("spaces.") else table


def refuse_known(table: str, key: str) -> None:
    if kind_of(table) not in settings.TABLES:
        raise Refused(f"[{table}] is not a table of settings")
    if key in settings.known(kind_of(table)):
        raise Refused(f"[{table}] {key} is a setting Shipyard knows; change it in Settings")


def remove_key(cfg, table: str, key: str) -> dict:
    """`setup.config.remove` {table, key}: take an unknown key's line out of the config."""
    refuse_known(table, key)
    try:
        done = edit(cfg, lambda text: configedit.remove_entry(text, table, key))
    except configedit.EditError as error:
        raise Refused(str(error)) from None
    return {**done, "note": f"[{table}] {key} is removed"}


def renamed(text: str, table: str, key: str, to: str) -> str:
    where = configedit.span(text, table)
    lines = text.splitlines()
    found = configedit.entry_line(lines, *where, key) if where else None
    if found is None:
        raise configedit.EditError(f"[{table}] has no {key}")
    if configedit.entry_line(lines, *where, to) is not None:
        raise configedit.EditError(f"[{table}] already has {to}; remove {key} instead")
    lines[found] = re.sub(rf"^(\s*){re.escape(configedit.key_text(key))}(\s*=)",
                          lambda m: f"{m.group(1)}{configedit.key_text(to)}{m.group(2)}", lines[found], count=1)
    return configedit.joined(lines, True)


def rename_key(cfg, table: str, key: str, to: str) -> dict:
    """`setup.config.rename` {table, key, to}: an unknown key's line kept under the name Keel
    knows. The config is loaded again before it is written, so a value the setting may not
    take is refused and nothing changes."""
    refuse_known(table, key)
    if to not in {setting.key for setting in settings.of(kind_of(table))}:
        raise Refused(f"{to} is not a setting of [{table}]")
    try:
        done = edit(cfg, lambda text: renamed(text, table, key, to))
    except configedit.EditError as error:
        raise Refused(str(error)) from None
    return {**done, "note": f"[{table}] {key} is now {to}"}


def text_of(body: dict, name: str) -> str:
    return str(body.get(name) or "").strip()


VERBS = {
    "stuck.model": lambda cfg, body, board: set_model(cfg, board, text_of(body, "id")),
    "land.aside": lambda cfg, body, board: set_aside(cfg, board, text_of(body, "id")),
    "land.unlock": lambda cfg, body, board: unlock(cfg, board, text_of(body, "id")),
    "services.restart": lambda cfg, body, board: restart_services(cfg),
    "setup.config.remove": lambda cfg, body, board: remove_key(cfg, text_of(body, "table"), text_of(body, "key")),
    "setup.config.rename": lambda cfg, body, board: rename_key(cfg, text_of(body, "table"), text_of(body, "key"),
                                                               text_of(body, "to")),
}
CONFIG_VERBS = ("setup.config.remove", "setup.config.rename")
