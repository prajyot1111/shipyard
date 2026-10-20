"""Whether the drain may start a card here, and what the deck says when it cannot.

A card is startable only when every repo it names exists on this machine, or it is a
new-project card and the space has the projects directory to scaffold it in. A space with
an adapter is not checked: its adapter says where its repos are and cuts their worktrees.

`waiting` is derived, never stored: the deck's one line for a startable card the drain
will not start, and why ("Cannot start this: ..."), which the row and the pane both show.
Until c-622 this module also placed a card between two machines (a pin, the repos each
machine pushed); one machine has nothing to place.
"""

from pathlib import Path

from keel import adapters
from keel.config import Config


def can_scaffold(cfg: Config, card: dict) -> bool:
    """A new-project card, in a space that has the projects directory to open it in."""
    space = cfg.spaces.get(card["space"])
    return (adapters.new_project_wanted(card) and space is not None
            and space.projects_dir is not None and space.projects_dir.is_dir())


def missing_repos(cfg: Config, card: dict) -> list[str]:
    """The card's repo keys this machine does not have; empty when it has them all."""
    space = cfg.spaces.get(card["space"])
    if space is None:
        return adapters.repos_of(card)
    if space.adapter_dir is not None:
        return []
    missing = []
    for key in adapters.repos_of(card):
        path = space.repo_path(key)
        if path is None or not Path(path).is_dir():
            missing.append(key)
    if missing and can_scaffold(cfg, card):
        return []
    return missing


def startable_here(cfg: Config, card: dict, served: set[str]) -> bool:
    """In a space this drain serves, and every repo it needs is on this disk."""
    return card["space"] in served and not missing_repos(cfg, card)


def waiting_text(cfg: Config, card: dict) -> str | None:
    """Why a startable card at assigned will not start, in one line, or None when it will."""
    derived = card.get("derived") or {}
    if derived.get("archived") or card.get("blocked_reason"):
        return None
    if card["stage"] != "assigned" or not derived.get("startable"):
        return None
    if card["space"] not in cfg.served_spaces():
        return f"Cannot start this: this install does not serve {card['space']}"
    missing = missing_repos(cfg, card)
    if missing:
        return (f"Cannot start this: {card['space']} needs {', '.join(missing)}, "
                f"and this install does not have it")
    return None


def waiting(cfg: Config, cards: list[dict]) -> dict[str, str]:
    """`{card id: line}` for every card that cannot start, for the deck."""
    out = {}
    for card in cards:
        text = waiting_text(cfg, card)
        if text:
            out[card["id"]] = text
    return out
