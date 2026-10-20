"""The deploy's preflight (c-725 r1.F1, F2, F4, F10): a tree of Keel's own code is refused
while the live install would read a path the tree no longer has, or would lose one owner's
things the old tree held. Asked by the deploy worker (`keel/deploy.py`) once the tree is built
and before the suite runs; each problem names the one command that clears it.

FOUR QUESTIONS, against the live checkout (the old tree) and the tree about to go live:

- **The owner's things.** When the tree drops a tracked path that `shipyard move-personal`
  moves (the work pack, the segments, the memory, the rulebook, the skill links, the history,
  the old config), the install must already hold all of it: `movepersonal.pending` says what
  a move from the live checkout would still do, and anything it would is a problem.
- **The config's paths.** Every path-valued key (`settings.PATH_KEYS`: a space's
  `config_dir`, `contract`, `projects_dir`, `pipeline` and each of its `repos`, and the
  `[machine]` paths, `adapters_dir` among them, r2.F10) that names something in the code
  must still be there in the tree; so must an `adapter` under an adapters dir in the code
  (unless the install's packs hold it).
- **The services.** Each service file whose `KEEL_HOME` is the live checkout, rendered under
  the install's `services/` or in `~/Library/LaunchAgents`, LOADED OR NOT (r2.F3: an agent
  not loaded now loads at the next login, so it is named with its unload or remove step); a
  service with no `KEEL_HOME` is not this checkout's and is skipped (r2.F2). When launchd
  cannot say which agents are loaded, that is a problem too, never a pass. One with no
  `KEEL_CONFIG` reads the checkout's own config, so it is refused when the tree drops the
  checkout's `keel.toml`; one whose `KEEL_ADAPTERS_DIR` is in the checkout, when the tree drops
  an adapter there the install's packs do not hold either; one whose `CLAUDE_CONFIG_DIR` is
  in the checkout, when the tree drops that dir's rulebook and the install holds none.
- **The install's own text** (c-726 r1.F1, r2.F6). The talker, Bosun and houses read as
  instructions the install's memory (the talker's rulebook among it), its identity profile,
  each space's files, each space's config dir `CLAUDE.md`, and its own packs' text and brief
  code (`.md` and `.py`, a pack's `tests/` aside). A line that names a path in the checkout,
  spelled absolute, from `~`, or from `$KEEL_HOME` (`${KEEL_HOME}`), that is nowhere in the
  tree would send them to nothing, so each is named with its file and line, and the fix that
  fits where it is: a memory card, a pack card on the install's packs repo, or the owner's
  own edit.

What it reads: git's tracked lists of the two trees, the install's config and its files, and
service files; it writes nothing.
"""

from __future__ import annotations

import plistlib
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from keel import configpath, drainprobe, memoryroot, movepersonal, settings

AGENTS = Path.home() / "Library" / "LaunchAgents"
SERVICE_ENV = re.compile(r'^Environment="?([A-Z_][A-Z0-9_]*)=(.*?)"?\s*$')


def tracked(tree: Path) -> set[str]:
    done = subprocess.run(["git", "-C", str(tree), "ls-files", "-z"], capture_output=True, text=True)
    return {name for name in done.stdout.split("\0") if name} if done.returncode == 0 else set()


def drops(old: set[str], new: set[str], rel: str) -> bool:
    """Whether the old tree tracked `rel` (a file, anything under a directory, or a tracked
    link it is reached through, as `adapters/work/pipeline.md` through `adapters/work`) and
    the new one does not."""
    rel = rel.rstrip("/")
    parts = rel.split("/")
    through = {"/".join(parts[:end]) for end in range(1, len(parts))}
    return any((name == rel or name.startswith(rel + "/") or name in through) and name not in new
               for name in old)


def move_command(cfg, repo: Path) -> str:
    """The move, run from the code being deployed (`<new>`), KEEL_HOME naming it too (r3.F3):
    a shell a Keel service started carries KEEL_HOME of the live checkout."""
    return f"KEEL_CONFIG={cfg.source} KEEL_HOME=<new> <new>/bin/shipyard move-personal --checkout {repo}"


NEW = "<new> being a checkout of the code being deployed"


def owner(cfg, repo: Path, tree: Path, old: set[str], new: set[str]) -> list[str]:
    home = cfg.install_home
    if home is None:
        return []
    sources = [item.source.relative_to(repo).as_posix()
               for item in movepersonal.items(repo, home, Path(cfg.segments_dir))]
    sources.append(movepersonal.TALKER_SKILLS.as_posix())
    if not any(drops(old, new, rel) for rel in sources):
        return []
    return [f"{line}; run `{move_command(cfg, repo)}`, {NEW}"
            for line in movepersonal.pending(cfg, repo, tree)]


def path_values(raw: dict) -> list[tuple[str, str, str]]:
    """`(table, key, value)` for each path-valued setting the config writes
    (`settings.PATH_KEYS`), a list's items one by one."""
    found = []

    def add(table: str, key: str, value) -> None:
        for one in value if isinstance(value, list) else [value]:
            if isinstance(one, str) and one:
                found.append((table, key, one))

    for name, table in sorted((raw.get("spaces") or {}).items()):
        table = table if isinstance(table, dict) else {}
        for key in settings.PATH_KEYS["space"]:
            add(f"spaces.{name}", key, table.get(key))
        for key, value in sorted((table.get("repos") or {}).items()):
            add(f"spaces.{name}.repos", key, value)
    for section in ("machine", "keel"):
        for key in settings.PATH_KEYS["machine"]:
            add(section, key, (raw.get(section) or {}).get(key))
    return found


def removed_by(value: str, repo: Path, tree: Path, old: set[str], new: set[str]) -> str | None:
    """The path in the code `value` names, when the live checkout tracks it and the tree does
    not; None otherwise (a path outside the code, one the tree keeps, or an untracked or
    ignored one the fresh deploy tree never had, r3.F9)."""
    if value.startswith("~") or value.startswith("/"):
        rel = in_repo(value, repo)
    else:
        rel = value
    if rel in (None, "."):
        return None
    return rel if (repo / rel).exists() and not (tree / rel).exists() and drops(old, new, rel) else None


# The keys `shipyard move-personal` points at the install's copy (`movepersonal.space_files`):
# a space's `contract` and `pipeline`, and only when the value is relative to the checkout. One
# spelled absolute or from `~` is the install's own choice, which the move leaves, and it never
# edits any other path key (a `[machine]` key is the install's own, r2.F1), so the fix for
# those is an edit of the install's config.
MOVED_KEYS = ("contract", "pipeline")


def setting_fix(cfg, repo: Path, table: str, key: str, value: str) -> str:
    if table.startswith("spaces.") and table.count(".") == 1 and key in MOVED_KEYS \
            and not value.startswith(("/", "~")):
        return f"run `{move_command(cfg, repo)}`, {NEW}"
    return (f"edit `[{table}] {key}` in {cfg.source}: point it at a path outside the checkout, "
            f"or remove it to take the default")


def config_paths(cfg, repo: Path, tree: Path, old: set[str], new: set[str]) -> list[str]:
    raw = tomllib.loads(Path(cfg.source).read_text()) if cfg.source else {}
    found = []
    for table, key, value in path_values(raw):
        rel = removed_by(value, repo, tree, old, new)
        if rel is not None:
            found.append(f"[{table}] {key} names {rel}, which this tree removes; {setting_fix(cfg, repo, table, key, value)}")
    for name, table in sorted((raw.get("spaces") or {}).items()):
        table = table if isinstance(table, dict) else {}
        adapter = table.get("adapter")
        under = in_repo(cfg.adapters_dir, repo)
        if isinstance(adapter, str) and under not in (None, ".") and (repo / under / adapter).exists() \
                and not (tree / under / adapter).exists() and drops(old, new, f"{under}/{adapter}") \
                and not in_packs(cfg, adapter):
            found.append(f"[spaces.{name}] adapter {adapter} is under {under}, which this tree "
                         f"removes; run `{move_command(cfg, repo)}`, {NEW}")
    return found


def in_repo(path, repo: Path) -> str | None:
    """`path` relative to the checkout, or None when it is not in it, or empty or missing
    (r2.F2: an empty path would resolve against the cwd, which is the checkout)."""
    if not path or not str(path).strip():
        return None
    try:
        return Path(path).expanduser().resolve().relative_to(repo.resolve()).as_posix()
    except (ValueError, OSError, TypeError):
        return None


def in_packs(cfg, name: str) -> bool:
    home = cfg.install_home
    return home is not None and (home / "packs" / name / "pack.toml").is_file()


# ----- the services -----

def environment(path: Path) -> tuple[str, dict] | None:
    """`(label, environment)` of a plist or a systemd unit, or None when it cannot be read."""
    try:
        if path.suffix == ".plist":
            data = plistlib.loads(path.read_bytes())
            return str(data.get("Label") or path.stem), dict(data.get("EnvironmentVariables") or {})
        env = {}
        for line in path.read_text().splitlines():
            match = SERVICE_ENV.match(line.strip())
            if match:
                env[match.group(1)] = match.group(2)
        return path.stem, env
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def launchd_loaded() -> set[str] | None:
    """The labels launchd has loaded; None when it cannot say (r2.F3: never read as none)."""
    if sys.platform != "darwin":
        return set()
    try:
        done = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return {line.split()[-1] for line in done.stdout.splitlines()[1:] if line.split()}


def service_files(cfg, agents: Path) -> list[Path]:
    """Every service file of the install's `services/` and every launch agent, loaded or not."""
    found = []
    if cfg.install_home is not None:
        found += sorted(cfg.services_dir.glob("*.plist")) + sorted(cfg.services_dir.glob("*.service"))
    found += [path for path in (sorted(agents.glob("*.plist")) if agents.is_dir() else []) if path not in found]
    return found


def fix_for(cfg, repo: Path, label: str) -> str:
    verb = ("voice install --load" if label.endswith(".voice")
            else "talker install" if label.endswith(".talker") else None)
    if verb:
        return f"KEEL_CONFIG={cfg.source} {repo}/bin/keel {verb}"
    return f"KEEL_CONFIG={cfg.source} {repo}/bin/shipyard service install"


UNREAD = object()        # `loaded` not given: ask launchd


def services(cfg, repo: Path, tree: Path, old: set[str], new: set[str],
             agents: Path = AGENTS, loaded=UNREAD) -> list[str]:
    loaded = launchd_loaded() if loaded is UNREAD else loaded
    found, ours = [], []
    for path in service_files(cfg, agents):
        read = environment(path)
        if read is None:
            continue
        label, env = read
        if in_repo(env.get("KEEL_HOME"), repo) != ".":
            continue
        ours.append(path)
        fix = f"`{fix_for(cfg, repo, label)}`"
        if label in drainprobe.OLD_LABELS:
            # r3.F8: no install command renders the old engine's agent any more, so the one
            # step that clears it is to boot it out (when loaded) and remove it.
            out = f"launchctl bootout gui/$(id -u)/{label} && " if loaded is not None and label in loaded else ""
            fix = f"`{out}rm {path}` (the old engine's agent, which nothing renders now)"
        elif path.parent == agents and loaded is not None and label not in loaded:
            fix = (f"{fix}; it is not loaded now but loads at the next login, so either re-render "
                   f"it, or remove it: `rm {path}`")
        if not env.get(configpath.CONFIG_ENV) and not (repo / configpath.INSTALL_CONFIG).is_file() \
                and drops(old, new, configpath.SHIPPED_CONFIG):
            found.append(f"{path} has no KEEL_CONFIG, so it reads {repo / configpath.SHIPPED_CONFIG}, "
                         f"which this tree removes; run {fix}")
        under = in_repo(env.get("KEEL_ADAPTERS_DIR", ""), repo)
        if under not in (None, "."):
            for name in sorted({rel.split("/")[1] for rel in old if rel.startswith(under + "/") and "/" in rel}):
                if drops(old, new, f"{under}/{name}") and not (env.get(configpath.CONFIG_ENV) and in_packs(cfg, name)):
                    found.append(f"{path} reads the adapter {under}/{name}, which this tree removes, "
                                 f"and has no KEEL_CONFIG to find the install's pack; run {fix}")
        rules_dir = in_repo(env.get("CLAUDE_CONFIG_DIR", ""), repo)
        own_rules = memoryroot.install_dir(memoryroot.TALKER, cfg.install_home)
        if rules_dir not in (None, ".") and drops(old, new, f"{rules_dir}/{memoryroot.RULEBOOK}") \
                and not (own_rules and (own_rules / memoryroot.RULEBOOK).is_file()):
            found.append(f"{path} runs the talker from {rules_dir}, whose rulebook this tree removes, "
                         f"and the install holds none; run `{move_command(cfg, repo)}`, {NEW}")
    if loaded is None and any(path.parent == agents for path in ours):
        found.append("launchctl list could not be read, so whether this checkout's launch agents are "
                     "loaded is unknown, and the deploy does not guess; run `launchctl list` and deploy again")
    return found


def spellings(repo: Path, home: Path | None = None) -> list[str]:
    """How a text names a path in the checkout: absolute, and from `~` when it is under home."""
    home = Path.home() if home is None else Path(home)
    found = [f"{repo}/"]
    if Path(repo).is_relative_to(home):
        found.append(f"~/{Path(repo).relative_to(home).as_posix()}/")
    return found


MEMORY_FIX = "point it at the install's copy (a change to the install's memory is a memory card the owner approves)"
PACK_FIX = "point it at the install's copy (a change to the install's pack is a pack card on its packs repo)"
OWN_FIX = "point it at the install's copy (the file is the owner's own to edit)"


def under(base: Path, pattern: str) -> list[Path]:
    if not base.is_dir():
        return []
    return [path for path in base.rglob(pattern) if ".git" not in path.relative_to(base).parts]


def install_texts(home: Path, config_dirs=()) -> list[tuple[Path, str]]:
    """The install's own text a reader takes as instructions, each with the fix for it: its
    memory (the talker's rulebook among it) and identity profile, each space's files, the
    install's own packs (their text and their brief code, which a work house reads, r2.F6),
    and each space's config dir rulebook."""
    found = [(path, MEMORY_FIX) for base in (home / memoryroot.MEMORY, home / "identity")
             for path in under(base, "*.md")]
    found += [(path, OWN_FIX) for path in sorted((home / "spaces").glob("*/*.md"))]
    found += [(path, PACK_FIX) for pattern in ("*.md", "*.py") for path in under(home / "packs", pattern)
              if "tests" not in path.relative_to(home / "packs").parts]     # a pack's tests instruct no one
    found += [(Path(config_dir) / "CLAUDE.md", OWN_FIX) for config_dir in config_dirs]
    return sorted({path: fix for path, fix in found if path.is_file()}.items())


# The shell's spelling of the live checkout (r2.F6): a house runs with KEEL_HOME naming it.
KEEL_HOME_SPELLINGS = ("$KEEL_HOME/", "${KEEL_HOME}/")


PATH_TOKEN = re.compile(r"[A-Za-z0-9_.@+/-]+")


def gone(old: set[str], new: set[str], rel: str) -> bool:
    """Whether `rel` (a file, or a directory by what it holds) is in the old tree and nowhere in
    the new one: a directory the tree keeps, with some files gone, still resolves."""
    rel = rel.rstrip("/")

    def holds(names: set[str]) -> bool:
        return any(name == rel or name.startswith(rel + "/") for name in names)
    parts = rel.split("/")
    through = {"/".join(parts[:end]) for end in range(1, len(parts))}
    return (holds(old) or bool(through & old)) and not holds(new) and not (through & new)


def install_text(cfg, repo: Path, old: set[str], new: set[str]) -> list[str]:
    """r1.F1: each line of the install's own text naming a checkout path the tree drops."""
    home = cfg.install_home
    if home is None:
        return []
    prefixes = spellings(repo) + list(KEEL_HOME_SPELLINGS)
    dirs = {space.config_dir for space in cfg.spaces.values() if getattr(space, "config_dir", None)}
    found = []
    for path, fix in install_texts(Path(home), sorted(dirs)):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            for prefix in prefixes:
                start = line.find(prefix)
                while start != -1:
                    token = PATH_TOKEN.match(line, start + len(prefix))
                    rel = token.group(0).rstrip(".") if token else ""
                    if rel and gone(old, new, rel):
                        found.append(f"{path}:{number} names {prefix}{rel}, which this tree removes; {fix}")
                    start = line.find(prefix, start + 1)
    return found


def problems(cfg, repo: Path, tree: Path, agents: Path = AGENTS, loaded=UNREAD) -> list[str]:
    """Each reason the tree may not go live on this install yet; empty when it may."""
    repo, tree = Path(repo).resolve(), Path(tree).resolve()
    old, new = tracked(repo), tracked(tree)
    found = owner(cfg, repo, tree, old, new) + config_paths(cfg, repo, tree, old, new)
    found += services(cfg, repo, tree, old, new, agents, loaded)
    found += install_text(cfg, repo, old, new)
    return list(dict.fromkeys(found))


def said(found: list[str]) -> str:
    return ("the install is not ready for this tree:\n" + "\n".join(f"- {line}" for line in found))
