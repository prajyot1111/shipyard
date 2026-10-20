"""Where an install keeps the repos it cloned, their tiers and their cards' worktrees (c-618, a-84).

    <install>/spaces/<space>/CLAUDE.md            the space tier: rules for every repo of it
    <install>/spaces/<space>/<key>/CLAUDE.md      the repo tier: this repo's conventions
    <install>/spaces/<space>/<key>/repo/          the clone, its team's own CLAUDE.md untouched
    <install>/spaces/<space>/<key>/trees/<card>/  each card's worktree

Claude Code loads every CLAUDE.md from a session's directory up, so a house started in
`trees/<card>` reads the repo tier and the space tier with no flag at all. The team's
CLAUDE.md inside `repo/` (and so inside every worktree) is excluded from every house in
the layout by `claudeMdExcludes` in its settings file (`excludes`, `house.settings_body`):
it is read once, by the proposal card that turns it into a repo tier, and never again.

A repo is "in the layout" when its path is `<install>/spaces/<space>/<key>/repo` of the
loaded install config (`spaces_of`), so a repo a config lists anywhere else (an existing
checkout), and every repo of a config that is not an install's, keeps everything as before.
"""

from __future__ import annotations

import os
from pathlib import Path

SPACES = "spaces"
REPO = "repo"
TREES = "trees"
TIER = "CLAUDE.md"
TEMPLATES = Path("etc") / "claude-md"


def space_dir(install: Path, space: str) -> Path:
    return Path(install) / SPACES / space


def repo_home(install: Path, space: str, key: str) -> Path:
    """`<install>/spaces/<space>/<key>`: the repo tier, the clone and its worktrees."""
    return space_dir(install, space) / key


def spaces_of(cfg) -> Path | None:
    """`<install>/spaces` for an install's config (its `config.toml` outside the code, the
    rule of `appservices.install_dir`), else None: only an install has a layout."""
    source = Path(cfg.source) if getattr(cfg, "source", None) else None
    if source is None or source.name != "config.toml" or source.parent == cfg.root:
        return None
    return source.parent / SPACES


def spaces_named() -> Path | None:
    """`spaces_of` for the config `KEEL_CONFIG` names, for a caller with no config in hand
    (`plangate`)."""
    named = os.environ.get("KEEL_CONFIG")
    path = Path(named).expanduser().resolve() if named else None
    return path.parent / SPACES if path is not None and path.name == "config.toml" else None


def home_of(repo: Path | None, spaces: Path | None) -> Path | None:
    """The `<key>` folder of a repo in the layout under `spaces`, or None for a repo
    anywhere else (or no install)."""
    if repo is None or spaces is None:
        return None
    repo = Path(repo)
    home = repo.parent
    inside = home.parent.parent.resolve() == Path(spaces).resolve()
    return home if repo.name == REPO and inside else None


def tree_of(repo: Path | None, card_id: str, spaces: Path | None) -> Path | None:
    """`<key>/trees/<card>` for a repo in the layout, else None."""
    home = home_of(repo, spaces)
    return home / TREES / card_id if home else None


def in_tree(path: Path, spaces: Path | None) -> bool:
    """True for a path inside a card's worktree in the layout (`<spaces>/<space>/<key>/trees/...`)."""
    if spaces is None:
        return False
    try:
        parts = Path(path).resolve().relative_to(Path(spaces).resolve()).parts
    except ValueError:
        return False
    return len(parts) > 3 and parts[2] == TREES


def first_repo(card: dict) -> str | None:
    keys = [key.strip() for key in str(card.get("repo") or "").split(",") if key.strip()]
    return keys[0] if keys else None


def card_tree(cfg, card: dict) -> Path:
    """A personal card's (first) worktree: under its repo's `trees/` in the layout, else
    `<state_dir>/worktrees/<id>` as before."""
    space = cfg.spaces.get(card.get("space"))
    key = first_repo(card)
    repo = space.repo_path(key) if space is not None and key else None
    return tree_of(repo, card["id"], spaces_of(cfg)) or cfg.worktrees_dir / card["id"]


def holds_tree(path: Path) -> bool:
    """A card's worktree directory that is there and not EMPTY (c-789). A done card's Drop in
    remakes a torn-down worktree as an empty folder for its resume, and one left behind is
    no worktree: refs resolved in it all fail. Not empty, rather than a `.git`, because a
    pack's `worktree` verb only has to print a directory (tests/test_adapters.py)."""
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def excludes(repos, spaces: Path | None) -> list[str]:
    """Absolute `claudeMdExcludes` globs for the repos in the layout: the team's CLAUDE.md
    files in the clone and in every worktree. The tiers above them still load."""
    found = []
    for repo in repos:
        home = home_of(repo, spaces)
        if home:
            found += [f"{home / REPO}/**/{TIER}", f"{home / TREES}/**/{TIER}"]
    return found


def template(root: Path, name: str, **words: str) -> str:
    return filled((Path(root) / TEMPLATES / f"{name}.md").read_text(), words)


def filled(text: str, words: dict) -> str:
    for word, value in words.items():
        text = text.replace(f"<{word}>", value)
    return text


EARLIER = "earlier"     # `etc/claude-md/earlier/<name>-<card>.md`: a template a tier may still be


def unwritten(root: Path, name: str, **words: str) -> list[str]:
    """Every text a tier nobody has written may hold: the template, and each earlier one it
    replaced (c-734: the repo template lost its lands line, and a tier copied from the c-678
    one is still unwritten)."""
    earlier = sorted((Path(root) / TEMPLATES / EARLIER).glob(f"{name}-*.md"))
    return [template(root, name, **words), *(filled(path.read_text(), words) for path in earlier)]
