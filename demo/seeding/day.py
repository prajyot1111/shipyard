"""The seeded day on the sandbox board, one phase per point in the script.

    history           the week of finished cards, from c-9201 (setup runs it, so every
                      later card is numbered past the live board's)
    morning           scenes 2 and 3: two review cards with findings, a plan at the gate,
                      the search fix merged overnight; and five cards working beside them
                      (`parallel.py`: two features, a bug fix, two reviews)
    export [<card>]   scene 8: the live export card's change pushed, a draft in api and in
                      web, and its outcome at his gate (with no card, a stand-in, filed as
                      scenes 4 to 7 would leave it)
    breaks            scene 9: a card whose stage to review is refused, Bosun's fix card, and
                      one deploy question
    evening           scene 10: every gate answered, so nothing waits on him and the export
                      card is shipping, with the two parallel features; the parallel bug fix
                      and both parallel reviews are done
    all               the four in order, on the stand-in export card

Every move goes through Keel's own Board (or the adapter's verbs), by the actor who would
really make it, on a clock each phase sets, so the deck draws what a real day leaves. Each
phase checks what Harbor would read when it is done, and says so; run twice, it changes
nothing it already did.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEEL_HOME = HERE.parent.parent
sys.path[:0] = [str(KEEL_HOME), str(KEEL_HOME / "adapters" / "sandbox")]

from keel import config  # noqa: E402
from keel.board import open_board

import sb_card  # noqa: E402
import sb_host  # noqa: E402



COLLEAGUES = {"Maya Chen": {"id": "maya", "name": "Maya Chen"},
              "Tom Okafor": {"id": "tom", "name": "Tom Okafor"},
              "Robin": sb_card.ME}
EXPORT_TITLE = "Add CSV export to the reports page"
# The version of the day this seed draws, written into the recordings index so every take
# recorded on it says which day it shows (`demo/scenes/record`), and the edit refuses a take
# of another (DAY in demo/video/src/cut.js, which must match). Bump it with any change a
# take shows: 2 is c-807's parallel day (five more cards, the export drafts at api #14 and
# web #33, the fix card c-9218); a take with none is from before it.
DAY_VERSION = 2


class SeedError(Exception):
    pass


# ----- the board, its clock and its writer -----

class Day:
    def __init__(self):
        self.home = sb_card.home()      # first: it refuses a toml that is not the sandbox's
        self.cfg = config.load()
        self.board = open_board(self.cfg)
        self.now = datetime.now().astimezone().replace(microsecond=0)

    def at(self, when: datetime) -> None:
        """Every stamp the board writes from here is `when`."""
        stamp = when.isoformat(timespec="seconds")
        self.board.now = lambda: stamp

    def live(self) -> None:
        self.board.__dict__.pop("now", None)

    def stamp_recordings(self) -> None:
        """The day's version into `recordings/index.json`, where the recorder reads it for
        each new take. Only that key is written; the takes the recorder keeps are left as
        they are."""
        path = self.home / "recordings" / "index.json"
        index = json.loads(path.read_text()) if path.is_file() else {"version": 1, "scenes": {}}
        if index.get("day") == DAY_VERSION:
            return
        index["day"] = DAY_VERSION
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(index, indent=2) + "\n")

    def ago(self, **delta) -> datetime:
        return self.now - timedelta(**delta)

    def overnight(self) -> datetime:
        night = self.now.replace(hour=2, minute=10, second=0)
        return night if night < self.now else night - timedelta(days=1)

    def card(self, title: str) -> dict | None:
        return next((c for c in self.board.list_cards(include_archived=True) if c["title"] == title), None)

    def set_options(self, card_id: str, actor: str = "house", **options) -> None:
        self.board.set_fields(card_id, {"options": options}, actor)

    def card_dir(self, card_id: str) -> Path:
        path = self.cfg.card_dir(card_id)
        path.mkdir(parents=True, exist_ok=True)
        return path


class BoardKb:
    """The adapter's `record_pr` writer, through this process's board and clock."""

    def __init__(self, day: Day):
        self.day = day

    def set_option(self, card_id: str, key: str, value) -> None:
        self.day.set_options(card_id, **{key: value})

    def note(self, card_id: str, text: str) -> None:
        self.day.board.note(card_id, text, "house")


# ----- git on the sandbox's origins -----

def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                            env={**os.environ, **(env or {})})
    if result.returncode != 0:
        raise SeedError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def author_env(name: str, when: datetime) -> dict:
    email = name.lower().replace(" ", ".") + "@sandbox.test"
    stamp = when.isoformat(timespec="seconds")
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": stamp}


def commit_files(tree: Path, files: dict, subject: str, author: str, when: datetime) -> str:
    for name, text in files.items():
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git(tree, "add", *files)
    if not git(tree, "status", "--porcelain"):
        return git(tree, "rev-parse", "HEAD")
    git(tree, "commit", "--quiet", "-m", subject, env=author_env(author, when))
    return git(tree, "rev-parse", "HEAD")


def push_branch(spec: dict, when: datetime) -> str:
    """The branch on origin with the spec's commit; its head. Left as it is when there."""
    repo, branch = spec["repo"], spec["branch"]
    found = sb_host.origin_head(repo, branch)
    if found:
        return found
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch) / repo
        git(Path(scratch), "clone", "--quiet", str(sb_card.origin_path(repo)), str(tree))
        git(tree, "checkout", "--quiet", "-b", branch, "origin/main")
        head = commit_files(tree, spec["files"], spec["subject"], spec["author"], when)
        git(tree, "push", "--quiet", "origin", branch)
    return head


def merge(repo: str, branch: str, number: int, when: datetime) -> None:
    """Merge the branch into origin's main, as the code host's merge button would."""
    with tempfile.TemporaryDirectory() as scratch:
        tree = Path(scratch) / repo
        git(Path(scratch), "clone", "--quiet", str(sb_card.origin_path(repo)), str(tree))
        if git(tree, "branch", "-r", "--contains", f"origin/{branch}", "--list", "origin/main"):
            return
        git(tree, "merge", "--quiet", "--no-ff", f"origin/{branch}", "-m",
            f"Merge pull request #{number} from {branch}", env=author_env("Maya Chen", when))
        git(tree, "push", "--quiet", "origin", "main")


def open_pr(spec: dict, title: str, description: str, when: datetime, draft: bool = False,
            reviewers: list[str] | None = None, number: int | None = None) -> dict:
    """The spec's pull request on the JSON host, opened once: found by its branch after."""
    repo = spec["repo"]
    for pr in sb_host.listed(repo):
        if pr["branch"] == spec["branch"]:
            return pr
    push_branch(spec, when)
    if number is not None:
        # Numbers as a lived-in host has them: the next one opened takes this number. A
        # placeholder only fills a number nobody holds, and a host already past it refuses.
        if sb_host.next_number(repo) > number:
            raise SeedError(f"{repo} is already past #{number}; the seed's texts name that number")
        if not sb_host.path_of(repo, number - 1).exists() and sb_host.next_number(repo) < number:
            sb_host.write_json(sb_host.path_of(repo, number - 1), placeholder(repo, number - 1, when))
    pr = sb_host.open_pr(repo, title, spec["branch"], "main", description, draft=draft,
                         author=COLLEAGUES[spec["author"]], reviewers=reviewers,
                         at=when.isoformat(timespec="seconds"))
    return pr


def placeholder(repo: str, number: int, when: datetime) -> dict:
    """An older, merged pull request, so numbering starts where a real repo's would."""
    stamp = (when - timedelta(days=20)).isoformat(timespec="seconds")
    return {"repo": repo, "number": number, "title": "Earlier work", "description": "",
            "author": COLLEAGUES["Maya Chen"], "branch": f"earlier/{number}", "base": "main",
            "state": "merged", "draft": False, "head": None, "reviewers": [], "reviews": [],
            "comments": [], "ci": {"state": "passed"}, "created": stamp, "updated": stamp}


def push_board(card_id: str, ops: str) -> str:
    """One board on the card, pushed through the sandbox's `keel board push`; its id."""
    with tempfile.NamedTemporaryFile("w", suffix=".ops", delete=False) as handle:
        handle.write(ops)
        path = handle.name
    try:
        result = subprocess.run([str(KEEL_HOME / "bin" / "keel"), "board", "push", "--card", card_id,
                                 "--new", "--file", path], capture_output=True, text=True)
    finally:
        os.unlink(path)
    words = result.stdout.split()
    if result.returncode != 0 or not words or not words[0].startswith("b-"):
        raise SeedError(f"keel board push for {card_id}: {result.stderr.strip() or result.stdout.strip()}")
    return words[0]
