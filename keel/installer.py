"""`shipyard init <dir>`: Keel set up for one user on one machine, macOS or Linux.

THE CODE IS THE CHECKOUT THIS RUNS FROM; `<dir>` IS THE INSTALL. The install holds what is
this user's and this machine's, and nothing else:

- `config.toml`: `etc/shipyard.example.toml` with its `[machine]` table filled (paths under
  `<dir>`, free ports, this machine's name) and every space's `config_dir` set to
  `<dir>/claude`.
- `state/`: the board (`board.db`, created empty), the card directories and the logs.
- `claude/`: the install's own Claude config dir. His `~/.claude` is never read or written;
  this is a NEW setup, and anything he wants from his own Claude he asks his Bosun to import.
- `services/`: the deck, drain and fetch units as rendered (`keel/appservices.py`).
- `packs/`, `builder/packs/`, `credentials/` (c-619): the install's packs as a git repo on
  `main`, listed as the personal repo `packs`; the in-app builder's own clone of it, its cwd;
  and the install's key (0700), from which Bosun's key is derived (`keel/builder.py`).
- `memory/`, `identity/` (c-722): Bosun's and the talker's memory, a git repo on `main`, and
  the user's profile, seeded once from `templates/` and never overwritten
  (`keel/memoryroot.py`); not seeded while the checkout still carries its own.
- `bin/shipyard`, `bin/keel`: two-line wrappers that name this install's config and run the
  checkout's code, so `<dir>/bin/shipyard doctor` is this install's doctor.

The install is reached by `KEEL_CONFIG=<dir>/config.toml`, not by pointing `KEEL_HOME` at
`<dir>`: the config's root is the code everywhere (`bin/keel`, `etc/house-bin`, contracts and
adapters resolve against it), a named toml is taken at its word, and houses, hooks and `kb`
children inherit `KEEL_CONFIG` already. docs/atlas/88-install.md has the whole of it.

RE-RUNNING IS SAFE. An existing `config.toml` and board are kept and said to be kept; what
is missing (a directory, the board, a wrapper, a trust entry) is made. Nothing here writes
over a user's config or state.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

from keel import appservices, builder, configedit, doctor, housetier, login, memoryroot, packclones, prereqs, trust
from keel import config as config_module
from keel import service as service_module
from keel.board import Board

EXAMPLE = Path("etc") / "shipyard.example.toml"
CLAUDE_DIR = "claude"
SUBDIRS = ("state", "state/logs", "state/cards", "segments", CLAUDE_DIR, "services", "bin")
# What another Keel in the caller's shell may have set, none of which an install wants: a
# board elsewhere (frozen, c-610), another machine's name, the live-state opt-in, another
# toml. Cleared for init's own process and by the wrappers.
FOREIGN_ENV = ("KEEL_LIVE_STATE", "KEEL_CONFIG", "KEEL_CARD", "KEEL_BOSUN")
# Ports no install takes: the live deck, lavish and voice, and the demo sandbox's deck.
RESERVED = {8790, 4387, 4390, 8890}
FIRST_PORT = {"serve_port": 8800, "lavish_port": 4401, "voice_port": 4411}
NEW_SETUP = """This is a NEW Shipyard setup with its own Claude login, kept in
  {claude}
Your own Claude (~/.claude) is not read or changed. Anything you want brought over from it
(memory, skills, settings) you can import later by asking your Bosun."""


class InitError(Exception):
    pass


def code_root() -> Path:
    return config_module.package_root()


def host_slug(name: str | None = None) -> str:
    """This machine's name as a config key. macOS's hostname can be an address
    (`192.168.1.5`, whose first part is `192`), so a Mac asks for its LocalHostName, and a
    name that is only digits falls back to "shipyard" on every system (c-634)."""
    name = name or local_host_name() or socket.gethostname()
    slug = re.sub(r"[^a-z0-9-]+", "-", name.split(".")[0].lower()).strip("-")
    if not slug or slug.isdigit():
        return "shipyard"
    return slug


def local_host_name() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        done = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def free_port(start: int, taken: set[int]) -> int:
    port = start
    while port in RESERVED or port in taken or not port_free(port):
        port += 1
    return port


def ports(deck: int | None = None) -> dict[str, int]:
    chosen: dict[str, int] = {}
    for key, start in FIRST_PORT.items():
        if key == "serve_port" and deck:
            if deck in RESERVED or not port_free(deck):
                raise InitError(f"--port {deck} is taken (in use, or reserved for another deck)")
            chosen[key] = deck
            continue
        chosen[key] = free_port(start, set(chosen.values()))
    return chosen


def set_key(text: str, key: str, value: str) -> str:
    """Every `key = <value>` line (any indentation, a trailing comment kept) given `value`."""
    pattern = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*)("[^"]*"|[^\s#]+)', re.MULTILINE)
    if not pattern.search(text):
        raise InitError(f"{EXAMPLE} has no `{key} =` line to fill")
    return pattern.sub(lambda match: match.group(1) + value, text)


quoted = configedit.literal
# What the example carries for the checkout it ships in, and a new install does not start
# with: its own repos are what the user adds in the deck's Setup view (c-618). The tables
# that name the checkout's repo for its suites and its integration branch stay, empty with
# their comments, so an install never names a repo it does not have (c-621).
FRESH_DROPS = (("spaces.personal.repos", "keel"), ("tests", "keel"), ("house_tests", "keel"),
               ("integration", "keel"), ("retests", "keel"), ("deploy_tests", "keel"))


def fresh(text: str) -> str:
    """The example without the checkout's own repo."""
    for table, key in FRESH_DROPS:
        text = configedit.remove_entry(text, table, key)
    return text


def render_config(example: str, home: Path, chosen: dict[str, int], host: str) -> str:
    """The example with this install's machine filled in. Only keys the example carries are
    set, so a key renamed there fails here by name rather than silently."""
    text = fresh(example)
    text = set_key(text, "config_dir", quoted(home / CLAUDE_DIR))
    text = set_key(text, "state_dir", quoted(home / "state"))
    text = set_key(text, "segments_dir", quoted(home / "segments"))
    text = set_key(text, "fetch_lock_dir", quoted(home / "state" / "fetch-locks"))
    for key, port in chosen.items():
        text = set_key(text, key, str(port))
    text = text.replace("\n[machine]\n", f'\n[machine]\nhost = {quoted(host)}\n', 1)
    head = (f"# Written by `shipyard init` on {date.today().isoformat()} for the install at {home}.\n"
            f"# Yours to edit: re-running init never writes over it.\n\n")
    return head + text


def wrapper(home: Path, root: Path, name: str) -> str:
    return ("#!/bin/sh\n"
            f"# Written by `shipyard init`: this install's config, the code at {root}.\n"
            f"unset {' '.join(name for name in FOREIGN_ENV if name != 'KEEL_CONFIG')}\n"
            f"export KEEL_CONFIG={shlex.quote(str(home / 'config.toml'))}\n"
            f"export KEEL_HOME={shlex.quote(str(root))}\n"
            f"exec {shlex.quote(sys.executable)} {shlex.quote(str(root / 'bin' / name))} \"$@\"\n")


class Init:
    """One run of init; `say` is where every line goes."""

    def __init__(self, home: Path, *, deck_port: int | None = None, services: str = "install",
                 features: tuple = (), probe_login: bool = True, open_deck: bool = True,
                 say=print):
        self.home = Path(home).expanduser().resolve()
        self.root = code_root()
        self.deck_port = deck_port
        self.services = services
        self.features = features
        self.probe_login = probe_login
        self.open_deck = open_deck
        self.say = say
        self.config_path = self.home / config_module.INSTALL_CONFIG

    def run(self) -> int:
        for name in FOREIGN_ENV:
            os.environ.pop(name, None)
        os.environ[config_module.HOME_ENV] = str(self.root)
        if not self.check():
            return 1
        self.refuse_inside_code()
        self.layout()
        self.config()
        self.wrappers()
        cfg = config_module.load(self.config_path)
        self.board(cfg)
        # The memory first: a memory repo it seeds is listed by the builder's step (r1.F1).
        self.say(memory_line(self.home, self.root))
        cfg = self.builder(cfg)
        self.trust(cfg)
        self.login(cfg)
        code = self.start(cfg)
        self.doctor()
        self.deck(cfg, started=code == 0 and self.services == "install")
        return code

    # ----- the steps -----

    def check(self) -> bool:
        """Each check on a line; a miss in its three parts (what happened, the fix with its
        command, whether it is required: `prereqs.line`, the sentences the deck's Check this
        computer step draws). A required miss stops init before anything is made, all but
        git's name and email (`prereqs.blocking`): nothing init does needs them, its line
        says the setup page asks for them, and that page's Next waits for them."""
        self.say("Checking this machine:")
        checks = prereqs.gather(list(self.features))
        for item in checks:
            self.say(prereqs.line(item))
        missing = prereqs.blocking(checks)
        if missing:
            count = "1 thing" if len(missing) == 1 else f"{len(missing)} things"
            fixes = "the fix" if len(missing) == 1 else "each fix"
            self.say(f"\nStopped: {count} to fix first. Do {fixes} above, then run this command again.")
        return not missing

    def refuse_inside_code(self) -> None:
        if self.home == self.root or self.home.is_relative_to(self.root):
            raise InitError(f"{self.home} is inside the code at {self.root}; choose a directory "
                            f"outside it (the install holds your state, the checkout the code)")

    def layout(self) -> None:
        made = [name for name in SUBDIRS if not (self.home / name).is_dir()]
        for name in SUBDIRS:
            (self.home / name).mkdir(parents=True, exist_ok=True)
        self.say(f"\nInstall: {self.home}" + (f" (made {', '.join(made)})" if made else " (all there)"))
        self.say(f"Code:    {self.root} (this checkout runs the install; it is not copied)")

    def config(self) -> None:
        if self.config_path.exists():
            self.say(f"Config:  {self.config_path} kept as it is")
            return
        example = (self.root / EXAMPLE).read_text()
        chosen = ports(self.deck_port)
        self.config_path.write_text(render_config(example, self.home, chosen, host_slug()))
        self.say(f"Config:  {self.config_path} written (deck port {chosen['serve_port']}, "
                 f"host {host_slug()})")

    def wrappers(self) -> None:
        for name in ("shipyard", "keel"):
            path = self.home / "bin" / name
            text = wrapper(self.home, self.root, name)
            if not path.exists() or path.read_text() != text:
                path.write_text(text)
                path.chmod(0o755)

    def board(self, cfg) -> None:
        existed = Path(cfg.db_path).exists()
        Board(cfg.db_path).close()
        self.say(f"Board:   {cfg.db_path} " + ("kept" if existed else "created, empty"))

    def builder(self, cfg):
        """The builder's: the install's key, the packs repo, each of the install's own repos
        (packs, and the memory once it is a repo, r1.F1) listed as a personal repo the builder
        builds, and Bosun's own clone of each repo it builds. What is there is kept; the config
        as it now is."""
        made = []
        if not housetier.shared_path(cfg).exists():
            housetier.mint_shared(cfg)
            made.append("the install's key")
        repo = self.home / builder.PACKS
        if not (repo / ".git").exists():
            packs_repo(repo)
            made.append("the packs repo")
        clones = self.home / builder.CLONES
        if packclones.ensure_ignored(repo):     # c-740: a pack cloned into the packs folder
            made.append("the packs repo's ignore of its cloned packs")
        text = self.config_path.read_text()
        kept = builder.unlist_gone(text, cfg, self.home)    # r1.F5: a cloned pack that is gone
        if kept != text:
            self.config_path.write_text(kept)
            cfg = config_module.load(self.config_path)
            made.append("a cloned pack that is gone unlisted")
        for key, path in builder.own_repos(self.home).items():
            listed_at = cfg.spaces["personal"].repos.get(key) if "personal" in cfg.spaces else None
            if listed_at is not None and not builder.same(listed_at, path):
                continue                        # the user's own repo has that key: it stays theirs
            text = self.config_path.read_text()
            listed = builder.list_own(text, cfg, key, path)
            if listed != text:
                self.config_path.write_text(listed)
                cfg = config_module.load(self.config_path)
                made.append(f"{key} listed")
            if not (clones / key / ".git").exists():
                git(["clone", "--quiet", "--no-hardlinks", str(path), str(clones / key)])
                made.append("Bosun's clone" if key == builder.PACKS else f"its clone of {key}")
        made += [f"its clone of {key}" for key in builder.ensure_clones(cfg)]   # the other repos it builds
        self.say(f"Builder: {repo}, its clones under {clones}" + (f" (made {', '.join(made)})" if made else " (kept)"))
        return cfg

    def trust(self, cfg) -> None:
        """The install and the code trusted in the install's own `.claude.json`, so the
        first house and Bosun start without a prompt nobody is there to accept."""
        dirs = {space.config_dir for space in cfg.spaces.values()}
        for config_dir in sorted(dirs, key=str):
            for path in (self.home, cfg.state_dir, self.root):
                trust.grant(config_dir, path)
        self.say(f"Trust:   {self.home} and {self.root} trusted for Claude in "
                 + ", ".join(str(d) for d in sorted(dirs, key=str)))

    def login(self, cfg) -> None:
        claude = self.home / CLAUDE_DIR
        self.say("\n" + NEW_SETUP.format(claude=claude))
        found = login.probe(claude) if self.probe_login else {"state": "unchecked"}
        if found["state"] == login.GOOD:
            self.say("Claude:  logged in for this install (a one-word `claude -p` answered).")
            return
        why = {"unchecked": " (not checked: --no-login-probe)",
               login.UNKNOWN: f" (the probe could not tell: {found.get('why')})"}.get(found["state"], "")
        self.say(f"Claude:  not logged in for this install{why}. Log in once, in a terminal:\n"
                 f"    CLAUDE_CONFIG_DIR={shlex.quote(str(claude))} claude /login")

    def start(self, cfg) -> int:
        if self.services == "none":
            self.say(f"\nServices: not installed (--no-services). Run them by hand:\n"
                     f"    {self.home / 'bin' / 'shipyard'} serve\n"
                     f"    {self.home / 'bin' / 'shipyard'} drain\n"
                     f"    {self.home / 'bin' / 'shipyard'} fetch")
            return 0
        self.say(f"\nServices ({service_module.platform()}):")
        try:
            return appservices.run(cfg, "install", dry=self.services == "dry-run")
        except service_module.Unsupported as refusal:
            self.say(f"  {refusal}")
            return 1

    def doctor(self) -> None:
        self.say("\nDoctor (this machine's checks):")
        report = doctor.gather(self.config_path, single=True, probe_logins=self.probe_login)
        report["missing"] = doctor.problems(report)
        self.say(doctor.render(report))

    def deck(self, cfg, started: bool) -> None:
        url = f"http://127.0.0.1:{cfg.serve_port}/"
        self.say(f"\nThe deck: {url}" + ("" if started else "  (once `serve` is running)"))
        self.say(f"Your command: {self.home / 'bin' / 'shipyard'} (add {self.home / 'bin'} to PATH)")
        if started and self.open_deck:
            open_url(url)


def git(argv: list[str], cwd: Path | None = None) -> str:
    done = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise InitError(f"git {argv[0]} failed: {(done.stderr.strip().splitlines() or ['no reason'])[-1]}")
    return done.stdout.strip()


def packs_repo(repo: Path) -> None:
    """`<install>/packs` as a git repo on `main`, with what is in it as its first commit. A
    machine with no git identity yet (no name, no email, or neither) commits as Shipyard: the
    user's own is never set here (`memoryroot.commit`, which the memory repo is made by too),
    so init needs no identity."""
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        # c-740 r1.F7: a pack cloned there before the repo is made is ignored before the first
        # add, or `git add -A` would commit it as an embedded repo and the ignore do nothing
        git(["init", "--quiet", "-b", "main"], repo)
        packclones.ensure_ignored(repo)
    try:
        memoryroot.commit(repo, "The install's packs (shipyard init)")
    except OSError as error:
        raise InitError(str(error)) from error


def memory_line(home: Path, root: Path) -> str:
    """The install's memory (c-722): seeded from the templates where it has none, kept where
    it has, and said to come from the checkout while the checkout still carries it."""
    try:
        seeded = memoryroot.seed(home, root)
    except OSError as error:
        raise InitError(str(error)) from error
    held = [part for part in memoryroot.held_by_checkout(root) if not memoryroot.in_install(part, home)]
    if held:
        return (f"Memory:  read from the checkout at {root} for {', '.join(held)} until "
                f"`shipyard move-personal` brings it into {home}")
    if seeded:
        return f"Memory:  {home / memoryroot.MEMORY} (seeded {', '.join(seeded)} from the templates)"
    return f"Memory:  {home / memoryroot.MEMORY} (kept)"


def open_url(url: str) -> None:
    """The browser on a desk that has one: `open` on macOS, `xdg-open` under a display, and
    on WSL Windows' own browser (`wslview`, else `explorer.exe`), which reaches the deck at
    the same localhost address (c-804)."""
    if sys.platform.startswith("linux") and service_module.on_wsl():
        opener = next((name for name in ("wslview", "explorer.exe") if shutil.which(name)), "")
        if opener:
            subprocess.run([opener, url], capture_output=True)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    has_desk = sys.platform == "darwin" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    if has_desk and shutil.which(opener):
        subprocess.run([opener, url], capture_output=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="shipyard init",
                                     description="set Shipyard up in a directory you choose")
    parser.add_argument("dir", help="the install: config, board, logs and its own Claude login")
    parser.add_argument("--port", type=int, help="the deck's port (default: the first free from 8800)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--no-services", action="store_true", help="install no launchd or systemd service")
    group.add_argument("--dry-run-services", action="store_true",
                       help="print the service files and commands instead of installing them")
    parser.add_argument("--with", dest="features", action="append", default=[],
                        choices=tuple(prereqs.NODE_FEATURES), help="a feature that needs node")
    parser.add_argument("--no-login-probe", action="store_true", help="skip the one-word claude -p check")
    parser.add_argument("--no-open", action="store_true", help="print the deck's URL, do not open it")
    args = parser.parse_args(argv)
    services = "none" if args.no_services else "dry-run" if args.dry_run_services else "install"
    try:
        return Init(Path(args.dir), deck_port=args.port, services=services,
                    features=tuple(args.features), probe_login=not args.no_login_probe,
                    open_deck=not args.no_open).run()
    except (InitError, config_module.ConfigError, configedit.EditError, trust.Untrusted) as refusal:
        print(f"shipyard init: {refusal}", file=sys.stderr)
        return 1
