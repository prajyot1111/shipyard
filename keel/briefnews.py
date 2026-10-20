"""The brief's card block, and the news a live house has not heard yet (c-533).

A house reads its card once, in the fenced JSON block of `brief.md`, and never again. A
field changed after that (c-530's autonomy, set 18 seconds after its house started) would
never reach it. So the block in `brief.md` is the record of what the house was TOLD: the
difference between it and the card now is the news, and there is no second record that has
to agree with the board.

Two turn boundaries deliver it, and neither ends a session: the Stop hook (`keel/ending.py`)
answers `block` with the news as its reason, and `house.resume_card` appends it to the
resume prompt. Each rewrites the block once the house has it, so it is said once.

Only the fields that instruct the house are compared: stage and plan_ref are the house's
own moves, and most options are Keel's bookkeeping (claim, provenance, app_link).
"""

import json
import re
from pathlib import Path

CARD_BLOCK_FIELDS = ("id", "title", "brief", "autonomy", "repo", "model", "stage", "plan_ref", "options")
BRIEFED_FIELDS = ("title", "brief", "autonomy", "repo", "model")
BRIEFED_OPTIONS = ("base", "browser")
BRIEF_FILE = "brief.md"
BLOCK = re.compile(r"^## The card\n\n```json\n(.*?)\n```", re.MULTILINE | re.DOTALL)
SHOWN = 80          # a longer value is named as changed, and the block holds the whole of it
HINTS = {
    ("autonomy", "autonomous"): "It is autonomous now: do not wait at the plan gate; set "
                                "plan_ref with `kb set` and carry on to the outcome.",
    ("autonomy", "attended"): "It is attended now: if your plan has not been through the user's gate, "
                              "stage planning with it and end your turn there.",
}
MODEL_HINT = "The model takes effect when you are next resumed."


def card_block(card: dict) -> str:
    fields = {name: card.get(name) for name in CARD_BLOCK_FIELDS}
    return "## The card\n\n```json\n" + json.dumps(fields, indent=2) + "\n```"


def told(text: str) -> dict | None:
    """The card as the brief gave it, or None when the brief has no readable block."""
    match = BLOCK.search(text)
    if not match:
        return None
    try:
        card = json.loads(match.group(1))
    except ValueError:
        return None
    return card if isinstance(card, dict) else None


def briefed(card: dict) -> dict:
    options = card.get("options") or {}
    fields = {name: card.get(name) for name in BRIEFED_FIELDS}
    fields.update({f"options.{key}": options.get(key) for key in BRIEFED_OPTIONS})
    return fields


def changes(before: dict, card: dict) -> list[tuple[str, object, object]]:
    """Each briefed field whose value differs, as (name, what the house was told, now)."""
    old, new = briefed(before), briefed(card)
    return [(name, old[name], new[name]) for name in new if old[name] != new[name]]


def set_names(data: dict) -> list[str]:
    options = data.get("options") if isinstance(data.get("options"), dict) else {}
    return [name for name in data if name != "options"] + [f"options.{key}" for key in options]


def own_moves(events: list[dict]) -> set[str]:
    """The briefed fields whose last `set` was the house's own: a house that retitles its
    card after his redirect (`prompts.REDIRECTED`) already knows, and is not told again."""
    last = {}
    for event in events:
        if event.get("kind") == "set" and isinstance(event.get("data"), dict):
            last.update({name: event.get("actor") for name in set_names(event["data"])})
    return {name for name, actor in last.items() if actor == "house"}


def shown(value) -> str | None:
    text = "none" if value in (None, "") else str(value)
    return text if len(text) <= SHOWN and "\n" not in text else None


def worded(name: str, old, new) -> str:
    was, now = shown(old), shown(new)
    if was is None or now is None:
        return f"{name} changed"
    return f"{name}: {was} -> {now}"


def wording(found: list[tuple[str, object, object]], path: Path) -> str:
    lines = [f"Your card changed since your brief: {'; '.join(worded(*c) for c in found)}."]
    lines += [HINTS[(name, new)] for name, _, new in found if (name, new) in HINTS]
    if any(name == "model" for name, _, _ in found):
        lines.append(MODEL_HINT)
    lines.append(f"The card block in {path} now says so; take the change into the work.")
    return " ".join(lines)


def brief_path(card_dir: Path) -> Path:
    return Path(card_dir) / BRIEF_FILE


def news(card_dir: Path, card: dict, events: list[dict] = ()) -> str | None:
    """What the house has not been told, worded for it, or None. A brief that is missing,
    unreadable or has no block is no news: an old card is never flooded. A field the house
    set itself (`own_moves` over the card's `events`) is not news either."""
    path = brief_path(card_dir)
    try:
        before = told(path.read_text())
    except OSError:
        return None
    if before is None:
        return None
    mine = own_moves(events)
    found = [change for change in changes(before, card) if change[0] not in mine]
    return wording(found, path) if found else None


def refresh(card_dir: Path, card: dict) -> bool:
    """Rewrite the brief's card block from `card`, in place; the rest of the brief is kept.
    False when there is no brief or no block to rewrite. Never raises."""
    path = brief_path(card_dir)
    try:
        text = path.read_text()
        if not BLOCK.search(text):
            return False
        fresh = BLOCK.sub(lambda _: card_block(card), text, count=1)
        if fresh != text:
            path.write_text(fresh)
        return True
    except OSError:
        return False
