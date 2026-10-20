"""The install's memory: Bosun's, the talker's, and the user's identity profile (c-722).

WHERE IT LIVES. In the install, beside its config and packs:

- `<install>/memory/bosun/`: Bosun's memory, which its SessionStart hook prints
  (`keel/console.py`) and its guard holds as its authority (`keel/authority.py`);
- `<install>/memory/talker/`: the talker's durable memory, linked in as its auto-memory
  (`keel/talkerdirs.py`), and its rulebook (`CLAUDE.md`), linked in as its config dir's own;
- `<install>/identity/`: the user's profile, which both read to know who they work for.

`<install>/memory` is a git repo on `main`, as the install's packs are, so a change to it is
a commit that can be read back and reviewed. The talker's own writes stay uncommitted, and
only a commit moves the stamp the talker rotates on (`keel/refresh.py`).

SEEDED ONCE, NEVER OVERWRITTEN. `shipyard init` copies `templates/memory/<part>` and
`templates/identity` into a part the install does not have yet, and records each template
file's hash in `memory/.seeded.json`. A part that exists is never written again, whatever is
in it. When a shipped template moves on, `template_news` says which file did (the doctor's
`memory` lines); the user's copy is theirs to compare and change.

THE CHECKOUT, ONLY WHILE THE INSTALL HAS NONE. Before c-722 the memory lived in the code
checkout (`bosun/memory`, `talker/memory`, `identity/`). Every reader asks `dir_of`, which
answers the install's directory once it holds the part, and the checkout's until then, so an
install made before the move keeps working until `shipyard move-personal` brings its memory
in. For the same reason init does not seed a part the checkout still holds: the templates
would hide the user's own memory.

Stdlib only and 3.10-clean: the voice gateway imports it on its own interpreter.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

MEMORY = "memory"
BOSUN, TALKER, IDENTITY = "bosun", "talker", "identity"
PARTS = (BOSUN, TALKER, IDENTITY)
INDEX = "MEMORY.md"
# The talker's rulebook, kept beside its memory (`memory/talker/CLAUDE.md`, c-722 landing B)
# and linked in as its config dir's CLAUDE.md by `keel talker install` (`keel/talkerdirs.py`).
RULEBOOK = "CLAUDE.md"
# The talker's skill links, name to target, recorded by `shipyard move-personal` (r1.F3) and
# made again in its config dir's `skills/` by `keel talker install` (`talkerdirs.link_skills`).
SKILLS = "skills.json"
SEEDED = ".seeded.json"
TEMPLATES = Path("templates")
# Where each part's template is, under the code.
TEMPLATE = {BOSUN: TEMPLATES / MEMORY / BOSUN, TALKER: TEMPLATES / MEMORY / TALKER,
            IDENTITY: TEMPLATES / IDENTITY}
# Where the code checkout kept each part before it moved to the install.
CHECKOUT = {BOSUN: Path("bosun") / "memory", TALKER: Path("talker") / "memory",
            IDENTITY: Path("identity")}
# Who commits on a machine with no git identity yet: the user's own is never set here.
FALLBACK_AUTHOR = ["-c", "user.name=Shipyard", "-c", "user.email=shipyard@localhost"]


def root(install: Path | None) -> Path | None:
    """`<install>/memory`, the git repo; None without an install."""
    return Path(install) / MEMORY if install else None


def install_dir(part: str, install: Path | None) -> Path | None:
    """Where `part` lives in the install, whether or not it is there yet."""
    if not install:
        return None
    return Path(install) / IDENTITY if part == IDENTITY else Path(install) / MEMORY / part


def has(directory: Path | None, part: str) -> bool:
    """Whether `directory` holds `part`: its index, or for the identity any profile."""
    if directory is None or not directory.is_dir():
        return False
    if part == IDENTITY:
        return any(path.is_file() for path in directory.glob("*.md"))
    return (directory / INDEX).is_file()


def dir_of(part: str, install: Path | None, code: Path) -> Path:
    """The directory `part` is read from: the install's once it holds it, else the checkout's."""
    own = install_dir(part, install)
    return own if has(own, part) else Path(code) / CHECKOUT[part]


def in_install(part: str, install: Path | None) -> bool:
    return has(install_dir(part, install), part)


def held_by_checkout(code: Path) -> list[str]:
    """The parts the code checkout still carries in its own tree."""
    return [part for part in PARTS if has(Path(code) / CHECKOUT[part], part)]


# ----- for a loaded config -----

def bosun_dir(cfg) -> Path:
    return dir_of(BOSUN, cfg.install_home, cfg.root)


def talker_dir(cfg) -> Path:
    return dir_of(TALKER, cfg.install_home, cfg.root)


def identity_dir(cfg) -> Path:
    return dir_of(IDENTITY, cfg.install_home, cfg.root)


def guarded(cfg) -> Path | None:
    """The install's memory root, its git repo included, which only an approved card may
    change (`keel/authority.py`, r1.F2): the history is the memory's as much as the files."""
    return root(cfg.install_home)


# ----- seeding -----

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def template_files(code: Path, part: str) -> list[Path]:
    base = Path(code) / TEMPLATE[part]
    return sorted(path for path in base.rglob("*") if path.is_file()) if base.is_dir() else []


def seed(install: Path, code: Path) -> list[str]:
    """Copy each part the install lacks from its template, commit the memory root, and
    return the parts seeded. A part that exists, or that the checkout still holds, is left."""
    install, code = Path(install), Path(code)
    held = set(held_by_checkout(code))
    record = read_seeded(install)
    seeded, written = [], []
    for part in PARTS:
        target = install_dir(part, install)
        files = template_files(code, part)
        if target.exists() or part in held or not files:
            continue
        for source in files:
            relative = source.relative_to(code / TEMPLATE[part])
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            (target / relative).write_bytes(source.read_bytes())
            written.append(target / relative)
            record[source.relative_to(code).as_posix()] = digest(source)
        seeded.append(part)
    if seeded:
        write_seeded(install, record)
        written.append(root(install) / SEEDED)
    # Only what this run wrote is committed (r1.F11): the talker's own writes and an edit to
    # Bosun's memory stay uncommitted, for a card or the user to review.
    mine = [path for path in written if path.is_relative_to(root(install))]
    if mine:
        commit(root(install), "Memory seeded from the shipped templates (shipyard init)", mine)
    return seeded


def read_seeded(install: Path) -> dict:
    try:
        found = json.loads((root(install) / SEEDED).read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def write_seeded(install: Path, record: dict) -> None:
    path = root(install) / SEEDED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")


def seeded(part: str, install: Path | None, record: dict | None = None) -> bool:
    """Whether `shipyard init` seeded this part of the install's memory from its template, by
    its own record (`SEEDED`), never by what the files are called (r3.F4)."""
    record = (read_seeded(install) if install else {}) if record is None else record
    return any(key.startswith(TEMPLATE[part].as_posix() + "/") for key in record)


def template_news(install: Path | None, code: Path) -> list[str]:
    """Each shipped template file that moved on since this install was seeded from it, as
    `<path> changed` or `<path> is new`. Only a seeded part is compared."""
    record = read_seeded(install) if install else {}
    seeded_parts = {part for part in PARTS if seeded(part, install, record)}
    news = []
    for part in PARTS:
        if part not in seeded_parts:
            continue
        for source in template_files(code, part):
            key = source.relative_to(code).as_posix()
            if key not in record:
                news.append(f"{key} is new")
            elif record[key] != digest(source):
                news.append(f"{key} changed")
    return news


# ----- the doctor's lines -----

def report(cfg) -> dict:
    """Where each part is read from; the parts an install still reads from the checkout;
    and each template that moved on since seeding. Information, never a problem."""
    install, code = cfg.install_home, cfg.root
    held = held_by_checkout(code)
    return {"dirs": {part: str(dir_of(part, install, code)) for part in PARTS},
            "from_checkout": [part for part in PARTS
                              if install is not None and part in held and not in_install(part, install)],
            "news": template_news(install, code)}


def lines(found: dict) -> list[str]:
    said = [f"memory        {part} {path}" for part, path in found["dirs"].items()]
    if found["from_checkout"]:
        said.append(f"memory        read from the checkout for {', '.join(found['from_checkout'])} "
                    f"until `shipyard move-personal` brings it into the install")
    said += [f"memory        {item} since your install was seeded; yours is kept, compare and "
             f"take what you want" for item in found["news"]]
    return said


# ----- git -----

def git(argv: list[str], repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True, timeout=120)


def commit(repo: Path, message: str, paths: list[Path] | None = None) -> bool:
    """`repo` as a git repo on `main` with `paths` committed (every change in it when none
    are named, which only a repo's first commit asks for); True when a commit was made. A
    machine with no git identity yet commits as Shipyard."""
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        done = git(["init", "--quiet", "-b", "main"], repo)
        if done.returncode != 0:
            raise OSError(f"git init failed in {repo}: {done.stderr.strip()}")
    has_identity = all(git(["config", key], repo).stdout.strip() for key in ("user.name", "user.email"))
    if paths is None:
        git(["add", "-A"], repo)
    else:
        named = [Path(path).relative_to(repo).as_posix() for path in paths]
        for start in range(0, len(named), 200):
            git(["add", "--", *named[start:start + 200]], repo)
        if git(["diff", "--cached", "--quiet"], repo).returncode == 0:
            return False
    first = git(["rev-parse", "--verify", "--quiet", "HEAD"], repo).returncode != 0
    if not first and git(["diff", "--cached", "--quiet"], repo).returncode == 0:
        return False
    done = git([*([] if has_identity else FALLBACK_AUTHOR), "commit", "--quiet", "--allow-empty",
                "-m", message], repo)
    if done.returncode != 0:
        raise OSError(f"git commit failed in {repo}: {(done.stderr.strip().splitlines() or ['no reason'])[-1]}")
    return True
