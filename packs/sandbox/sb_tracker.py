"""The sandbox's tracker: stories as JSON files, `<sandbox>/tracker/<n>.json`.

    {"number", "ref": "st-<n>", "title", "kind", "state", "created", "updated"}

A story's link is `https://tracker.sandbox.test/story/<n>`, on a reserved name that
resolves nowhere. States follow a card: `started` when it is minted at task start, `in
review` when his Approve publishes it, `done` when its pull request merges.
"""

import json
import re
from pathlib import Path

from sb_card import SandboxError, home
from sb_host import now, write_json

URL = "https://tracker.sandbox.test/story/{number}"
FIRST = 101


def url(number: int) -> str:
    return URL.format(number=int(number))


def root() -> Path:
    return home() / "tracker"


def number_of(ref) -> int | None:
    found = re.search(r"(\d+)", str(ref or ""))
    return int(found.group(1)) if found else None


def get(number: int) -> dict | None:
    path = root() / f"{int(number)}.json"
    return json.loads(path.read_text()) if path.is_file() else None


def mint(title: str, kind: str) -> dict:
    root().mkdir(parents=True, exist_ok=True)
    numbers = [int(p.stem) for p in root().glob("*.json") if p.stem.isdigit()]
    number = max(numbers, default=FIRST - 1) + 1
    story = {"number": number, "ref": f"st-{number}", "title": title, "kind": kind,
             "state": "started", "created": now(), "updated": now()}
    write_json(root() / f"{number}.json", story)
    return story


def move(number: int, state: str) -> dict:
    story = get(number)
    if story is None:
        raise SandboxError(f"the tracker has no story {number}")
    story = dict(story, state=state, updated=now())
    write_json(root() / f"{number}.json", story)
    return story
