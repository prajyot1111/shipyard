"""What a machine needs before `shipyard init` can set Keel up on it, each with its fix.

Every check answers `{name, label, ok, said, what, fix, command, required}`. `name` is the
check's key and never changes; `label` is how a person reads it ("Your name and email for
git"); `said` is what was found (a version, a path). A check that fails carries the three
parts of a miss (c-679, the first-run design of c-668), so the installer's line and the
deck's Check this computer step say one sentence:

1. `what`: what happened, and why Keel needs the thing, as sentences;
2. `fix`: what to do, as a sentence, and `command`: the one command that does it, to copy,
   or "" where no single command does (another operating system, a package manager Keel
   cannot name);
3. `required`: whether setup stops on it.

`line(check)` is the installer's form of those parts, `miss_words(check)` a miss in one
line (readiness's row and the doctor's), and `fix_words(check)` the fix in one sentence,
command included (the doctor's). Nothing here installs anything; the installer
(`keel/installer.py`) prints the list and stops on a `required` miss, all but one the
setup page fixes itself (`page`, `blocking`). The one write is
`save_identity`, git's own global setting, made only by the user's Save on the deck.

- **The OS**: macOS or Linux. Windows runs Keel inside WSL2, which is Linux (c-804), so
  native Windows (and anything else) is refused politely, its fix naming WSL2: the services
  and paths are behind one interface (`keel/service.py`), but no Windows manager is built.
- **systemd, on WSL** (c-804): WSL leaves systemd off until `/etc/wsl.conf` turns it on, and
  without it `systemctl --user` has no manager, so no Keel service can start. Asked only on
  WSL (`service.wsl_version`, Linux only), and required; the doctor says the same miss. WSL1
  has no systemd at all, so there the miss is to convert the distro to WSL2.
- **Python 3.12 or newer**, and its `sqlite3` module (some minimal builds leave it out).
- **git**: worktrees and merges are how a card's code lands.
- **git's identity** (c-621): `user.name` and `user.email`, since a landing commits a merge.
  Without them every Approve outcome failed at the merge commit, so it is required: the
  setup page's Next waits for it. It does not stop init (c-679), which needs no identity,
  so the page's two fields are reachable on a first install. The check also carries
  `values`, what git has for each, so the deck's two fields start from them, and
  `save_identity(name, email)` writes with `git config --global` only the one git lacks.
  It carries no command: nothing here prints a name or an email to paste.
- **The `claude` CLI**, its version, and the two harness features Keel is built on: `--bg`
  (a house is a background session) and `agents --json` (the only way Keel learns what a
  session is doing). Both are read off `--help`, which costs nothing and needs no login.
- **node**: only when a chosen feature needs it. None of the core does; the browser tool a
  house drives (`bin/keel-browser`) and lavish plans are what do, so the check is asked for
  by name and says which feature wanted it.
- **gpg** (c-757): every backup copy is encrypted with it (`bin/keel-backup`), and nothing
  else needs it. So it is NOT required: an install never stops for it, its row says "for
  backup", and the Back up step refuses to turn on without it and points at this row
  (`keel/backupsetup.py`). It is looked for where the backup's jobs look (`job_path()`, the
  fixed PATH the service manager hands them, `backup.PATH_ENTRIES`), not on the PATH of
  whoever asked: a gpg only this shell can see is one the hourly job cannot run. And it
  is RUN (`gpg --version`), as the tool runs it before every copy: a file named gpg that
  does not run is a miss with its own words (r1.F9).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

MIN_PYTHON = (3, 12)
PYTHON = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
TIMEOUT = 20
# The features that need node, named so the check can say which one asked.
NODE_FEATURES = {"browser": "the house browser (bin/keel-browser)",
                 "lavish": "lavish plans (the older plan style)"}
# mark, the argv whose help carries it, the check's name, its label, what a help without
# the mark means, and why Keel needs the feature
HELP_MARKS = (("--bg", ["--help"], "claude --bg (background sessions)",
               "Claude Code can run sessions in the background",
               "Claude Code on this computer is too old to run sessions in the background.",
               "Shipyard starts every session that way."),
              ("--json", ["agents", "--help"], "claude agents --json (the session list)",
               "Claude Code can list its sessions",
               "Claude Code on this computer is too old to list its sessions.",
               "That list is how Shipyard knows what a session is doing."))
NO_HELP = "Claude Code did not answer when asked for its help, so this could not be checked."
CLAUDE_DOCS = "https://docs.claude.com/claude-code"
# c-729: the native installer leads, since it needs no root; npm's global install fails with
# EACCES for a user without it, so npm is said only where npm is, as the fallback for root.
CLAUDE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"
CLAUDE_FIX = ("Install Claude Code with its own installer, the command below, as yourself (it needs no "
              "root). It puts claude in ~/.local/bin. If your terminal then says command not found, run "
              'export PATH="$HOME/.local/bin:$PATH" and add that same line to ~/.bashrc or ~/.zshrc. '
              f"More: {CLAUDE_DOCS}.")
CLAUDE_NPM = "If you are root, npm install -g @anthropic-ai/claude-code works too."


def result(name: str, ok: bool, said: str, *, label: str = "", what: str = "", fix: str = "",
           command: str = "", required: bool = True) -> dict:
    """One check. A check that passes carries no `what`, `fix` or `command`."""
    return {"name": name, "label": label or name, "ok": ok, "said": said,
            "what": "" if ok else what or said, "fix": "" if ok else fix,
            "command": "" if ok else command, "required": required}


def mac_only(command: str, platform: str | None = None) -> str:
    """A command Homebrew or Xcode gives macOS. Linux has a package manager per
    distribution, so its fix names it in words and carries no command."""
    return command if (platform or sys.platform) == "darwin" else ""


def os_check(platform: str | None = None) -> dict:
    platform = platform or sys.platform
    if platform == "darwin":
        return result("os", True, "macOS", label="Operating system")
    if platform.startswith("linux"):
        return result("os", True, "Linux", label="Operating system")
    return result("os", False, platform, label="Operating system",
                  what=f"This computer runs {platform}. Shipyard runs on macOS and Linux, and on "
                       f"Windows inside WSL2, which is Linux.",
                  fix="On Windows, install WSL2 with Ubuntu, turn systemd on in it, and set "
                      "Shipyard up inside it. Elsewhere, use a computer that runs macOS or Linux.")


WSL_CONF = "printf '\\n[boot]\\nsystemd=true\\n' | sudo tee -a /etc/wsl.conf"
WSL_FIX = ("Add the two lines [boot] and systemd=true to /etc/wsl.conf (if it already has a "
           "[boot] section, add systemd=true under it instead), then run wsl --shutdown from "
           "Windows and open this terminal again.")
WSL1_FIX = ("Convert this distro to WSL2: in Windows' PowerShell, wsl -l -v shows its name, "
            "and wsl --set-version <distro> 2 converts it. Then open this terminal again.")


def wsl_check(wsl: int | None = None, booted: bool | None = None) -> dict | None:
    """On WSL, whether systemd runs it: WSL leaves it off until /etc/wsl.conf turns it on, and
    every Keel service is a systemd user unit. `wsl` is the WSL version (0 for none), else
    read, and only on Linux (`service.wsl_version`). WSL1 has no systemd, so its miss is to
    convert to WSL2. None anywhere but WSL, where nothing is asked."""
    if wsl is None and not sys.platform.startswith("linux"):
        return None
    from keel import service     # noqa: PLC0415 - it imports pwd, which native Windows lacks
    wsl = (service.wsl_version() or 0) if wsl is None else wsl
    if not wsl:
        return None
    if wsl == 1:
        return result("wsl systemd", False, "WSL1", label="systemd in WSL",
                      what="This is Windows' WSL1, which has no systemd, so systemctl --user cannot "
                           "run and Shipyard's services cannot start. Shipyard needs WSL2.",
                      fix=WSL1_FIX)
    on = service.systemd_booted() if booted is None else booted
    return result("wsl systemd", on, "on" if on else "off", label="systemd in WSL",
                  what="This is Windows' WSL with systemd off, so systemctl --user cannot run and "
                       "Shipyard's services cannot start.",
                  fix=WSL_FIX, command=WSL_CONF)


def python_check(version: tuple = tuple(sys.version_info[:3])) -> dict:
    said = ".".join(str(part) for part in version)
    return result("python", tuple(version[:2]) >= MIN_PYTHON, f"{said} ({sys.executable})",
                  label=f"Python {PYTHON} or newer",
                  what=f"The Python that ran this is {said}, older than {PYTHON}. "
                       f"Shipyard is written for {PYTHON} or newer.",
                  fix=f"Install Python {PYTHON} or newer (on Linux, your package manager's python3), "
                      f"then run `shipyard` with it.",
                  command=mac_only("brew install python"))


def sqlite_check() -> dict:
    try:
        import sqlite3          # noqa: PLC0415 - the check is whether it imports at all
    except ImportError as error:
        return result("sqlite3", False, str(error), label="Python's sqlite3 module",
                      what="This Python was built without its sqlite3 module. Shipyard keeps its board in SQLite.",
                      fix="Run `shipyard` with a Python that has it: the system Python and Homebrew's both do.",
                      command=mac_only("brew install python"))
    return result("sqlite3", True, f"SQLite {sqlite3.sqlite_version}", label="Python's sqlite3 module")


def run(argv: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None


def tool_check(name: str, *, label: str = "", what: str = "", fix: str = "", command: str = "",
               required: bool = True, path: str | None = None) -> dict:
    """A tool on PATH and its version; the miss is the three parts its caller names.
    `path`: where it was found, for a caller that looked somewhere of its own (`gpg_check`)."""
    path = path or shutil.which(name)
    if not path:
        return result(name, False, "not on PATH", label=label, what=what, fix=fix, command=command,
                      required=required)
    done = run([path, "--version"])
    version = (done.stdout or done.stderr).strip().splitlines()[0] if done and done.returncode == 0 else "?"
    return result(name, True, f"{version} ({path})", label=label, required=required)


def git_check() -> dict:
    return tool_check("git", label="git",
                      what="Git is not installed on this computer. Shipyard cuts a working copy for each card "
                           "and lands its work with git.",
                      fix="Install git (on Linux, with your package manager).",
                      command=mac_only("xcode-select --install"))


IDENTITY = "git identity"
IDENTITY_LABEL = "Your name and email for git"
IDENTITY_KEYS = (("name", "user.name"), ("email", "user.email"))
IDENTITY_WHY = "When work lands, git records who merged it."
# The fix names the page, and the check carries no command: a line with a placeholder name
# and email, pasted as it is, would pass this check as a real identity (review F5).
IDENTITY_FIX = "Type them into the two fields on the setup page's Check this computer step, and press Save."


def identity_check(runner=None) -> dict:
    """git's `user.name` and `user.email`, as any repo here without its own would read them:
    a landing commits a merge, and without both git refuses it (c-621). `values` is what git
    has for each, "" for one that is not set. `page` marks the one required check the
    setup page can fix itself (two fields and Save), so a miss does not stop init
    (`blocking`): nothing init does needs the identity, and the fields are reachable on a
    first install.

    A key is one of three things, and they are told apart: set, not set (git's exit 1 for a
    key it does not have), or not read (git did not answer, or answered with anything else).
    A read that failed says nothing about what git has, so the check then reads "could not
    be checked", carries `unread` (the fields nobody could read) and is not `page`: the two
    fields are not offered over a value that may be there, and `save_identity` refuses."""
    runner = runner or run
    values, unread = {}, []
    for field, key in IDENTITY_KEYS:
        done = runner(["git", "-C", "/", "config", "--get", key])
        values[field] = done.stdout.strip() if done is not None and done.returncode == 0 else ""
        if done is None or done.returncode not in (0, 1):
            unread.append(field)
    lacking = [(field, key) for field, key in IDENTITY_KEYS if not values[field]]
    if unread:
        found = result(IDENTITY, False, "could not be checked", label=IDENTITY_LABEL,
                       what=f"Git's settings could not be read just now, so your name and email could "
                            f"not be checked. {IDENTITY_WHY}",
                       fix="Check again. If it keeps happening, run `git config --list` in a terminal "
                           "to see what git says.")
        return {**found, "values": values, "unread": unread, "page": False}
    if lacking:
        found = result(IDENTITY, False, f"{' and '.join(key for _, key in lacking)} not set",
                       label=IDENTITY_LABEL,
                       what=f"Git on this computer has no {' and '.join(field for field, _ in lacking)} set. "
                            f"{IDENTITY_WHY}",
                       fix=IDENTITY_FIX)
    else:
        found = result(IDENTITY, True, f"{values['name']} <{values['email']}>", label=IDENTITY_LABEL)
    return {**found, "values": values, "unread": [], "page": True}


def save_identity(name: str, email: str, runner=None) -> dict:
    """The deck's Save on Check this computer: write git's global `user.name` and
    `user.email`, each ONLY where git has none, and answer the check read again. The rule is
    held here, not by the page: a value git already has is never rewritten, whatever is
    sent for it, and a Save once git has both is refused.

    A refusal is a ValueError. One made before git is asked writes nothing: a value that is
    empty, is not one line of printable text, or begins with a dash (which a git might read
    as an option). The two writes are one after the other and the first is not taken back,
    so when git refuses the second, the error says the first was saved. When either key
    could not be read, nothing is written either: an unread key may hold a value."""
    runner = runner or run
    now = identity_check(runner)
    if now["unread"]:
        raise ValueError("git's settings could not be read just now, so nothing was saved; try again")
    lacking = [(field, key) for field, key in IDENTITY_KEYS if not now["values"][field]]
    if not lacking:
        raise ValueError("git already has a name and email")
    wanted = {"name": str(name or "").strip(), "email": str(email or "").strip()}
    for field, _ in lacking:
        refuse_value(field, wanted[field])
    saved = []
    for field, key in lacking:
        done = runner(["git", "config", "--global", key, wanted[field]])
        if done is None or done.returncode != 0:
            why = (done.stderr.strip().splitlines() or ["no reason given"])[-1] if done else "git did not run"
            kept = f" Your {' and '.join(saved)} was saved." if saved else ""
            raise ValueError(f"git could not save your {field}: {why.rstrip('.')}.{kept}")
        saved.append(field)
    return identity_check(runner)


def refuse_value(field: str, value: str) -> None:
    if not value:
        raise ValueError(f"git needs your {field}: it is empty")
    if not value.isprintable():
        raise ValueError(f"your {field} for git must be one line of plain text")
    if value.startswith("-"):
        raise ValueError(f"your {field} for git cannot begin with a dash")


def claude_check() -> list[dict]:
    """The CLI, then one line per harness feature Keel cannot run without."""
    npm = shutil.which("npm")      # npm is named only where npm is, as root's fallback
    found = tool_check("claude", label="Claude Code",
                       what="Claude Code is not installed on this computer. Shipyard runs every session with it.",
                       fix=f"{CLAUDE_FIX} {CLAUDE_NPM}" if npm else CLAUDE_FIX, command=CLAUDE_INSTALL)
    if not found["ok"]:
        return [found]
    return [found, *(feature_check(*mark) for mark in HELP_MARKS)]


def feature_check(mark: str, argv: list[str], name: str, label: str, old: str, why: str) -> dict:
    """One harness feature, read off the help. A help that did not come back (a timeout)
    could not be checked, which is not the same miss as a Claude Code too old to have it."""
    done = run([shutil.which("claude"), *argv])
    if done is None:
        return result(name, False, "could not be checked", label=label, what=f"{NO_HELP} {why}",
                      fix="Check again. If it keeps happening, update Claude Code.")
    ok = re.search(rf"(^|\s){re.escape(mark)}\b", f"{done.stdout}\n{done.stderr}") is not None
    return result(name, ok, "present" if ok else "missing from --help", label=label,
                  what=f"{old} {why}", fix="Update Claude Code.", command="claude update")


def node_check(features: list[str]) -> list[dict]:
    wanted = [NODE_FEATURES[name] for name in features if name in NODE_FEATURES]
    if not wanted:
        return []
    asked = ", ".join(wanted)
    found = tool_check("node", label="Node.js, for " + asked,
                       what=f"Node.js is not installed on this computer. It was asked for by: {asked}.",
                       fix="Install Node.js 20 or newer (nodejs.org, or on Linux your package manager).",
                       command=mac_only("brew install node"))
    found["name"] = "node, for " + asked
    return [found]


GPG = "gpg"
GPG_LABEL = "gpg, for backup"
GPG_ONLY = "It is needed only for Back up: the install and everything else work without it."
GPG_WHAT = f"The gpg program is not installed on this computer. Shipyard encrypts every backup copy with it. {GPG_ONLY}"
GPG_FIX = "Install gpg (on Linux, your package manager's gnupg), then press Check again."
GPG_AGAIN = "Install gpg again (on Linux, your package manager's gnupg), then press Check again."
GPG_INSTALL = "brew install gnupg"


def job_path() -> tuple[str, ...]:
    """Where the backup's jobs look for a program: the PATH the service manager hands them."""
    from keel import backup     # noqa: PLC0415 - it loads the config module, which init's checks run before
    return tuple(backup.PATH_ENTRIES)


def on_path(name: str, entries) -> str | None:
    """`name` as a program in the first of `entries` that has it, or None."""
    for entry in entries:
        found = os.path.join(entry, name)
        if os.path.isfile(found) and os.access(found, os.X_OK):
            return found
    return None


def gpg_check() -> dict:
    """gpg, where the backup's jobs would find it (`job_path`). Never required. A gpg that
    is on this process's PATH and not on theirs is a miss too, and says where it is."""
    entries = job_path()
    found = on_path(GPG, entries)
    miss = {"label": GPG_LABEL, "required": False, "command": mac_only(GPG_INSTALL)}
    if found:
        done = run([found, "--version"])
        if done is not None and done.returncode == 0:
            version = ((done.stdout or done.stderr).strip().splitlines() or ["?"])[0]
            return result(GPG, True, f"{version} ({found})", label=GPG_LABEL, required=False)
        said = ((done.stderr or done.stdout).strip().splitlines() or [""])[-1] if done is not None else ""
        why = said.rstrip(".") or ("it did not answer" if done is None else f"it exited {done.returncode}")
        return result(GPG, False, "does not run", fix=GPG_AGAIN, **miss,
                      what=f"The gpg program at {found} does not run: {why}. "
                           f"Shipyard encrypts every backup copy with it. {GPG_ONLY}")
    elsewhere = shutil.which(GPG)
    if not elsewhere:
        return result(GPG, False, "not installed", what=GPG_WHAT, fix=GPG_FIX, **miss)
    return result(GPG, False, f"at {elsewhere}, where the backup does not look",
                  what=f"The gpg program is at {elsewhere}, where the backup's jobs do not look. They look in "
                       f"{', '.join(entries)}. Shipyard encrypts every backup copy with it. {GPG_ONLY}",
                  fix="Install gpg into one of those folders, or link it there, then press Check again.", **miss)


def git_checks() -> list[dict]:
    """git, then its name and email, which are asked only where git is: with no git there is
    no identity to read, and a failed read of it would say "could not be checked" when the
    truth is that git is missing. The ONE guard, for `gather` and for the doctor."""
    git = git_check()
    return [git, identity_check()] if git["ok"] else [git]


def gather(features: list[str] = ()) -> list[dict]:
    """Every check, the OS first: on an OS that is refused the rest are not asked."""
    first = os_check()
    if not first["ok"]:
        return [first]
    wsl = [check for check in [wsl_check()] if check]
    return [first, *wsl, python_check(), sqlite_check(), *git_checks(),
            *claude_check(), *node_check(list(features)), gpg_check()]


def missing(checks: list[dict]) -> list[dict]:
    return [check for check in checks if not check["ok"] and check["required"]]


def blocking(checks: list[dict]) -> list[dict]:
    """The misses `shipyard init` stops on: every required one but a check the setup page
    fixes itself (`page`, git's name and email)."""
    return [check for check in missing(checks) if not check.get("page")]


def miss_words(check: dict) -> str:
    """A miss in one line, its label and what happened, with no closing full stop so it
    joins: what readiness's row and the doctor say, in the words the page and init use."""
    what = check.get("what") or check["said"]
    return f"{check.get('label') or check['name']}: {what.rstrip('.')}"


def fix_words(check: dict) -> str:
    """The fix as one sentence, its command after it in code marks where it has one."""
    command = check.get("command") or ""
    return check["fix"] + (f" `{command}`" if command else "")


REQUIRED_WORDS = {True: "Required: setup stops until this is fixed.",
                  False: "Not required: setup goes on without it."}
PAGE_WORDS = ("Required, and the install goes on: the setup page asks for it on "
              "Check this computer (two fields and Save).")


def line(check: dict) -> str:
    """The installer's line for a check. A miss says its three parts under it: what
    happened, the fix (its command on a line of its own, to copy), and whether it is
    required."""
    label = check.get("label") or check["name"]
    if check["ok"]:
        return f"  ok   {label}: {check['said']}"
    parts = [f"  MISS {label}: {check['said']}",
             f"       What happened: {check.get('what') or check['said']}"]
    if check.get("fix"):
        parts.append(f"       The fix: {check['fix']}")
    if check.get("command"):
        parts.append(f"           {check['command']}")
    last = PAGE_WORDS if check["required"] and check.get("page") else REQUIRED_WORDS[bool(check["required"])]
    return "\n".join([*parts, f"       {last}"])
