"""The sandbox adapter's view of a card and of the sandbox it serves.

The sandbox adapter answers every verb the engine calls on a work adapter, in the same JSON
shapes, but its code host and tracker are JSON files under the sandbox's own directory
(`sb_host`, `sb_tracker`) and its repos are clones of bare origins on the same disk. It is
what the demo sandbox (`demo/sandbox/`) runs its work space on, and the example of an
adapter that needs no credential at all.

The sandbox is the directory the loaded toml sits in (`KEEL_CONFIG`), or `KEEL_SANDBOX`
when a test names one, and it must carry the `.keel-sandbox` marker `demo/sandbox/setup`
writes: a toml that is not a sandbox's never gets this adapter's writes.
"""

import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEEL_HOME = Path(os.environ.get("KEEL_HOME") or HERE.parent.parent).resolve()
# The pack this code serves is the directory it sits in, so a copy (`keel new pack`, c-634)
# serves the spaces that name the copy, never the sandbox's.
ADAPTER = HERE.name
MARKER = ".keel-sandbox"
DEFAULT_BASE = "main"
KINDS = ("bug", "feature", "chore", "research")
TRACKER_CREATE = "create at task start"
# His account on the fake code host: the author of his pull requests, the reviewer the
# review scan looks for.
ME = {"id": "me", "name": "Robin"}
# Every sandbox card id is at least this (c-9201 onward), far past the live board's. A house
# is a harness session named after its card id and the sandbox's houses share the personal
# config dir, so the live drain and the sandbox's must never both have a card of one name.
ID_FLOOR = 9000


class SandboxError(Exception):
    """A verb cannot finish; the message is the one line the caller prints."""


# ----- the sandbox and Keel's config -----

def keel_config():
    """Keel's loaded config, through Keel's own loader (found via KEEL_HOME)."""
    if str(KEEL_HOME) not in sys.path:
        sys.path.insert(0, str(KEEL_HOME))
    from keel import config as keel_config_module  # noqa: PLC0415 - Keel's loader
    return keel_config_module.load(ensure=False)


@functools.cache
def home() -> Path:
    """The sandbox directory, refused unless it carries the marker AND the toml this process
    loads opens a board inside it and reaches no board over HTTP: `KEEL_SANDBOX` alone is
    never proof, so a verb run beside the live toml writes nothing."""
    named = os.environ.get("KEEL_SANDBOX")
    if named:
        root = Path(named).expanduser()
    elif os.environ.get("KEEL_CONFIG"):
        root = Path(os.environ["KEEL_CONFIG"]).expanduser().resolve().parent
    else:
        raise SandboxError("no sandbox: KEEL_CONFIG names no sandbox toml (demo/sandbox/setup builds one)")
    if not (root / MARKER).is_file():
        raise SandboxError(f"{root} is not a sandbox (no {MARKER}); refusing to write there")
    refuse_elsewhere(root)
    return root


def refuse_elsewhere(root: Path) -> None:
    """The loaded toml must be the sandbox's own: its board inside `root`."""
    config = os.environ.get("KEEL_CONFIG")
    if not config or Path(config).expanduser().resolve() != (root / "keel.toml").resolve():
        raise SandboxError(f"KEEL_CONFIG is not {root / 'keel.toml'}; run it through demo/sandbox/run")
    cfg = keel_config()
    if not Path(cfg.db_path).resolve().is_relative_to(root.resolve()):
        raise SandboxError(f"the loaded toml opens {cfg.db_path}, not the sandbox's board; refusing")


def served_space(cfg=None) -> str:
    cfg = cfg or keel_config()
    names = [name for name, space in cfg.spaces.items() if space.adapter == ADAPTER]
    if not names:
        raise SandboxError(f"no space in the loaded toml names the {ADAPTER} adapter")
    return names[0]


def repo_paths() -> dict[str, Path]:
    cfg = keel_config()
    return dict(cfg.spaces[served_space(cfg)].repos)


def repo_path(key: str) -> Path:
    paths = repo_paths()
    if key not in paths:
        raise SandboxError(f"the sandbox has no repo {key!r}")
    return paths[key]


def origin_path(key: str) -> Path:
    return home() / "origin" / f"{key}.git"


def card_dir(card_id: str) -> Path:
    return keel_config().card_dir(card_id)


def context_text(card_id: str) -> str:
    path = card_dir(card_id) / "context.md"
    return path.read_text(errors="replace") if path.is_file() else ""


# ----- the board, through kb -----

class Kb:
    """`kb` under KEEL_HOME, with the caller's KEEL_CONFIG: the sandbox's own board."""

    def __init__(self, keel_home: Path = KEEL_HOME):
        self.path = keel_home / "bin" / "kb"

    def run(self, *args: str) -> str:
        env = dict(os.environ, KEEL_CONFIG=str(home() / "keel.toml"))
        result = subprocess.run([str(self.path), *args], capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise SandboxError(f"kb {' '.join(args[:2])}: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout

    def show(self, card_id: str) -> dict:
        return json.loads(self.run("show", card_id, "--json", "--events", "0"))

    def cards(self) -> list[dict]:
        return json.loads(self.run("list", "--all", "--json"))

    def set_option(self, card_id: str, key: str, value) -> None:
        raw = value if isinstance(value, str) else json.dumps(value)
        self.run("set", card_id, f"options.{key}={raw}")

    def note(self, card_id: str, text: str) -> None:
        self.run("note", card_id, text)


KB = Kb()


def load_card(card_id: str) -> dict:
    return KB.show(card_id)


# ----- options and kinds -----

def option(card: dict, key: str, default=None):
    value = (card.get("options") or {}).get(key)
    return default if value is None else value


def repos_of(card: dict) -> list[str]:
    return [key.strip() for key in (card.get("repo") or "").split(",") if key.strip()]


def primary_repo(card: dict) -> str:
    keys = repos_of(card)
    if not keys:
        raise SandboxError(f"card {card['id']} has no repo")
    return keys[0]


def kind_of(card: dict) -> str:
    kind = str(option(card, "kind", "feature")).lower()
    return kind if kind in KINDS else "feature"


def is_research(card: dict) -> bool:
    return kind_of(card) == "research"


def is_review(card: dict) -> bool:
    return bool(option(card, "review_key")) or str(option(card, "kind") or "").lower() == "review"


def is_tracking(card: dict) -> bool:
    return bool((card.get("derived") or {}).get("tracking"))


def refuse_no_pr(card: dict) -> None:
    """A research or review card opens, readies and pushes no pull request of its own."""
    if is_research(card):
        raise SandboxError(f"{card['id']} is a research card: its outcome is its record, not a pull request")
    if is_review(card):
        raise SandboxError(f"{card['id']} is a review card: it reviews a colleague's pull request and opens none")


def base_of(card: dict) -> str:
    return str(option(card, "base") or DEFAULT_BASE)


# ----- branches and stories -----

STORY = re.compile(r"\bst-(\d+)\b", re.I)
SLUG_MAX = 40


def slug(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(words) <= SLUG_MAX:
        return words or "work"
    return words[:SLUG_MAX].rsplit("-", 1)[0] or words[:SLUG_MAX]


def story_of(text) -> str | None:
    """`st-<n>` from a branch, a title or a reference, else None."""
    found = STORY.search(str(text or ""))
    return f"st-{found.group(1)}" if found else None


def branch_for(card: dict) -> str:
    existing = option(card, "branch")
    if existing:
        return str(existing)
    story = story_of(option(card, "tracker_ref")) or "no-story"
    return f"{kind_of(card)}/{story}/{slug(card.get('title', ''))}"


def branch_in(card: dict, repo: str) -> str:
    entry = (option(card, "prs") or {}).get(repo)
    return str(entry.get("branch") or branch_for(card)) if isinstance(entry, dict) else branch_for(card)


# ----- a card's pull requests, one per repo -----

def prs_of(card: dict) -> list[dict]:
    """Every pull request the card carries, `{repo, pr, branch, primary}`, primary first:
    `options.prs` ({repo: {pr, branch}}), and `options.pr` for the primary repo."""
    keys, found = repos_of(card), {}
    recorded = option(card, "prs") or {}
    for repo, entry in (recorded.items() if isinstance(recorded, dict) else ()):
        if isinstance(entry, dict) and entry.get("pr"):
            found[repo] = {"pr": int(entry["pr"]), "branch": entry.get("branch")}
    if keys and keys[0] not in found and option(card, "pr"):
        found[keys[0]] = {"pr": int(option(card, "pr")), "branch": None}
    order = [key for key in keys if key in found] + sorted(key for key in found if key not in keys)
    return [{"repo": repo, "pr": found[repo]["pr"],
             "branch": found[repo]["branch"] or (branch_for(card) if keys and repo == keys[0] else None),
             "primary": index == 0} for index, repo in enumerate(order)]


def recorded_pr(card: dict, repo: str) -> int | None:
    return next((entry["pr"] for entry in prs_of(card) if entry["repo"] == repo), None)


def record_pr(card: dict, repo: str, number: int, kb=None) -> dict:
    """The primary's number in `options.pr`; on a cross-repo card every one in
    `options.prs[repo]` with its branch. The card as it now stands."""
    kb = kb or KB
    options, keys = dict(card.get("options") or {}), repos_of(card)
    if keys and repo == keys[0] and options.get("pr") != number:
        kb.set_option(card["id"], "pr", number)
        options["pr"] = number
    if len(keys) > 1 or repo not in keys[:1]:
        prs = dict(options.get("prs") or {}) if isinstance(options.get("prs"), dict) else {}
        entry = {"pr": number, "branch": branch_in(card, repo)}
        if prs.get(repo) != entry:
            prs[repo] = entry
            kb.set_option(card["id"], "prs", prs)
            options["prs"] = prs
    return dict(card, options=options)


def worktree_of(card: dict, repo: str) -> Path | None:
    recorded = (option(card, "worktrees") or {}).get(repo)
    if recorded:
        return Path(str(recorded))
    keys = repos_of(card)
    if option(card, "worktree") and (not keys or keys[0] == repo):
        return Path(str(option(card, "worktree")))
    return None


def git(repo, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def as_json(value) -> str:
    return json.dumps(value, sort_keys=True)
