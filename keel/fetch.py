"""The fetch role: every segment's fetch.py on a schedule, and its asks turned into cards.

Two tiers, both mechanical. The first runs `<segments_dir>/*/fetch.py` under the same
per-segment lock directory Harbor's own hourly job and minute worker take
(`<locks>/.fetch-<segment>.lock` holding a `pid` file), so while both systems exist no
fetcher runs twice at once: hourly for every segment, every minute for a segment whose
inputs moved (a drop in `data/inbox/`, or a source file newer than `summary.json`). The
second turns a segment's `data/asks/` into one autonomous errand card per pass, briefed
with the worker.md body and confined to the worker's tools, after moving the asks into
`data/asks/taken/` so each is consumed exactly once. From there it is an ordinary card:
the drain starts it, its house writes one journal drop into the segment's `data/inbox/`,
the Stop hook reads that drop and files the card at `review` on the house's behalf
(`board.file_drop`, since a confined house may have no shell to stage it with), and the
next fetch folds the drop in AND CLOSES THE CARD (`close_folded` below). `daily_cap` is
the number of that segment's cards created today.

A pass also files the `[recurring.<key>]` cards that are due (`keel/recurring.py`): work
repeated on a schedule, decided from the board.

This module is what a pass does. The loop that runs the passes is `keel/fetchloop.py`.

Every run also leaves `data/.last-fetch` (`{at, host, state, ok_at}`, `stamp`), which is what
`keel doctor` reads to say a segment has stopped updating.
"""

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from keel import logins, recurring
from keel.board import Board, Refused, open_board
from keel.config import Config

LOG_NAME = "fetch.log"
LOCK_STALE_SECONDS = 3600
FETCH_TIMEOUT = 600
FULL_SECONDS = 3600
PASS_SECONDS = 60
PRUNED = ("data", "__pycache__")
DEFAULT_TOOLS = "Read,Write,Edit,Glob,Grep"
DEFAULT_CAP = 20
DEFAULT_TIMEOUT = 900
APPLIED_DIR = "inbox-applied"
FOLDED_NOTE = "folded by the fetcher, so the outcome gate was already met"


# ----- log -----

def log(cfg: Config, text: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.logs_dir / LOG_NAME, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {text}\n")


def summary_line(results: dict, created: dict) -> str:
    counts = {state: sum(1 for value in results.values() if value == state)
              for state in ("ok", "failed", "skipped", "unusable")}
    fields = " ".join(f"{state}={count}" for state, count in counts.items())
    return f"fetch: {fields} cards={len(created)}"


# ----- segments -----

def segments(cfg: Config, only: str | None = None) -> list[Path]:
    """Every segment directory, sorted; `only` keeps the one named."""
    if not cfg.segments_dir.is_dir():
        return []
    dirs = sorted(path for path in cfg.segments_dir.iterdir()
                  if path.is_dir() and not path.name.startswith("."))
    return [path for path in dirs if only is None or path.name == only]


def fetchers(cfg: Config, only: str | None = None) -> list[Path]:
    """The segments with a fetch.py."""
    return [path for path in segments(cfg, only) if (path / "fetch.py").is_file()]


def interpreter(cfg: Config) -> str:
    """The venv beside the segments tree when it runs (not merely exists), else the code
    checkout's, else python3. On an install the segments tree is the install's and the venv
    built from `etc/segment-requirements.txt` is still the checkout's (c-742)."""
    for base in dict.fromkeys((cfg.segments_dir.parent, cfg.root)):
        venv = base / ".venv" / "bin" / "python"
        try:
            subprocess.run([str(venv), "-c", ""], capture_output=True, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError):
            continue
        return str(venv)
    return "python3"


# ----- the lock -----

def lock_path(cfg: Config, segment: str) -> Path:
    return cfg.fetch_locks / f".fetch-{segment}.lock"


def _claim(lock: Path) -> bool:
    try:
        lock.mkdir()
        (lock / "pid").write_text(f"{os.getpid()}\n")
    except OSError:
        return False
    return True


def _owner(lock: Path) -> int | None:
    try:
        return int((lock / "pid").read_text().strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _age(lock: Path) -> float:
    try:
        return time.time() - lock.stat().st_mtime
    except OSError:
        return 0.0


def _clear(lock: Path) -> bool:
    """rmdir, never a recursive delete: a fresh lock always holds a pid file, so a loser
    reading the same dead owner fails here instead of removing the winner's lock."""
    try:
        (lock / "pid").unlink(missing_ok=True)
        lock.rmdir()
    except OSError:
        return False
    return True


def take_lock(lock: Path) -> str:
    """`taken`, `held` (another job runs this fetcher), or `unusable` (the lock directory
    itself cannot be created, which is a broken state dir rather than a busy one)."""
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if _claim(lock):
        return "taken"
    if not lock.is_dir():
        if _claim(lock):
            return "taken"
        return "held" if lock.is_dir() else "unusable"
    owner = _owner(lock)
    ancient = _age(lock) > LOCK_STALE_SECONDS
    if not ancient and (owner is None or _alive(owner)):
        return "held"
    return "taken" if _clear(lock) and _claim(lock) else "held"


def release_lock(lock: Path) -> bool:
    return _clear(lock)


# ----- tier one: fetchers -----

def run_fetcher(cfg: Config, segment: Path, python: str) -> tuple[str, str]:
    """Run one fetch.py under its lock: (`ok`|`failed`|`skipped`|`unusable`, log text)."""
    lock = lock_path(cfg, segment.name)
    state = take_lock(lock)
    if state == "held":
        return "skipped", "skipped, another job holds its fetch lock"
    if state == "unusable":
        return "unusable", f"NOT RUN, its fetch lock {lock} is unusable"
    try:
        result = subprocess.run([python, str(segment / "fetch.py")], cwd=segment,
                                capture_output=True, text=True, timeout=FETCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "failed", f"FAILED, still running after {FETCH_TIMEOUT}s"
    except OSError as error:
        return "failed", f"FAILED, {error}"
    finally:
        release_lock(lock)
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        return "ok", "ok  " + (output.splitlines()[-1] if output else "")
    return "failed", f"FAILED (exit {result.returncode})\n{output}"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def inbox_has_work(segment: Path) -> bool:
    inbox = segment / "data" / "inbox"
    if not inbox.is_dir():
        return False
    return any(p.is_file() and not p.name.startswith(".") for p in inbox.iterdir())


def sources_changed(segment: Path) -> bool:
    """Anything outside data/ and __pycache__ newer than summary.json (or no summary yet)."""
    stamp = segment / "summary.json"
    if not stamp.exists():
        return True
    since = _mtime(stamp)
    for root, dirs, files in os.walk(segment):
        dirs[:] = [name for name in dirs if name not in PRUNED]
        if any(_mtime(Path(root) / name) > since for name in dirs + files):
            return True
    return False


def inputs_changed(segment: Path) -> bool:
    return inbox_has_work(segment) or sources_changed(segment)


def once(cfg: Config, segment: str | None = None, changed_only: bool = False,
         board: Board | None = None) -> dict:
    """Run every fetcher (or only those whose inputs moved); one log line per segment run.
    Returns {segment: state}. One failing fetcher never stops the others.

    The fold is the last step of an ask card, so closing what the fold consumed happens
    here too, on the same pass: see `close_folded`.
    """
    results: dict = {}
    python = None
    for path in fetchers(cfg, segment):
        if changed_only and not inputs_changed(path):
            continue
        python = python or interpreter(cfg)
        state, text = run_fetcher(cfg, path, python)
        results[path.name] = state
        log(cfg, f"{path.name:<12} {text}")
        if state == "failed":
            logins.saw_fetch(cfg, path, text)
        if state in ("ok", "failed"):
            stamp(path, cfg.host, state)
    close_folded(cfg, results, board)
    return results


# ----- the stamp every run leaves -----

LAST_FETCH = ".last-fetch"
# A segment whose newest good run is older than this has stopped updating. The fetch role
# runs every segment hourly, so three missed runs is not a slow pass.
STALE_SECONDS = 3 * 3600


def stamp(segment: Path, host: str, state: str) -> None:
    """Record this run in `data/.last-fetch`, keeping when the last good one was."""
    data = segment / "data"
    data.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    previous = read_stamp(segment) or {}
    record = {"at": now, "host": host, "state": state,
              "ok_at": now if state == "ok" else previous.get("ok_at")}
    write_atomic(data / LAST_FETCH, json.dumps(record).encode())


def read_stamp(segment: Path) -> dict | None:
    try:
        value = json.loads((segment / "data" / LAST_FETCH).read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def stamp_age(segment: Path, now: datetime | None = None) -> float | None:
    """Seconds since this segment's last good run, or None when it never had one."""
    record = read_stamp(segment) or {}
    try:
        ok = datetime.fromisoformat(record.get("ok_at") or "")
    except (TypeError, ValueError):
        return None
    now = now or datetime.now().astimezone()
    return (now - ok).total_seconds()


def write_atomic(target: Path, raw: bytes) -> None:
    """Write by rename, so the app never reads half a file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(raw)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def staleness(cfg: Config) -> list[dict]:
    """One entry per segment with a fetch.py, for `keel doctor`: how long since its last
    good fetch. A segment with no data at all has never run: nothing there to go stale. One
    with data and no good run recorded is the silent stop this exists for."""
    out = []
    for path in fetchers(cfg):
        age = stamp_age(path)
        has_data = (path / "data").is_dir()
        out.append({"name": path.name, "age_seconds": age, "state": (read_stamp(path) or {}).get("state"),
                    "data": has_data,
                    "ok": (age <= STALE_SECONDS) if age is not None else not has_data})
    return out


# ----- the fold is an ask card's approval -----

def applied_twin(drop: Path) -> Path:
    """Where a folded drop lands: `data/inbox-applied/<name>`, beside `data/inbox/`. Every
    segment's `apply_inbox` moves a drop there rather than deleting it, so a bad drop can
    still be read afterwards, and so this can tell folded from discarded."""
    return drop.parent.parent / APPLIED_DIR / drop.name


def fold_verdict(drop: Path, ran_ok: bool) -> tuple[str, str] | None:
    """What the fetcher did with this drop: ("folded"|"refused", why), or None while
    nothing has happened to it yet.

    Read off the disk rather than out of the fetcher's stdout, because the fold is the
    segment's own code and the only thing every segment's fold agrees on is where the file
    ends up. Three states worth naming:

    - it is in `inbox-applied/`: the fold took it. The outcome gate is already met.
    - it is still in `data/inbox/` and the fetcher just ran and exited ok: the fold ran and
      left it, which is a refusal. A successful fold always empties the inbox.
    - it is in neither: the fetcher took it out of the inbox without applying it.

    A drop still in the inbox after a fetcher that FAILED or was skipped is none of these.
    It is "not yet", and the next pass looks again.
    """
    if applied_twin(drop).is_file():
        return "folded", FOLDED_NOTE
    if drop.is_file():
        if ran_ok:
            return "refused", ("the fetcher ran and left this drop in the inbox, so the fold "
                               "would not take it; this card is the one that needs a look")
        return None
    return "refused", (f"this drop is gone from the inbox and never reached {APPLIED_DIR}/, "
                       f"so the fetcher discarded it rather than folding it")


def already_said(board: Board, card_id: str, text: str) -> bool:
    """Has this card already been told this. The refusal check runs every sixty seconds and
    a note per pass would bury the card's own history under one repeated sentence."""
    return any(event.get("text") == text for event in board.events(card_id, last=20))


def close_one(cfg: Config, board: Board, card: dict, results: dict) -> str | None:
    """Close, or explain, one ask card sitting at `review` with a drop. Returns the state."""
    drop = (card["options"] or {}).get("drop")
    if not drop:
        return None
    verdict = fold_verdict(Path(drop), results.get((card["options"] or {}).get("segment")) == "ok")
    if verdict is None:
        return None
    state, why = verdict
    if state == "refused":
        if not already_said(board, card["id"], why):
            board.note(card["id"], why, "fetch")
            log(cfg, f"{card['id']}: the drop was not folded, so it stays at review")
        return state
    try:
        board.stage(card["id"], "done", "fetch", note=why)
    except Refused as refused:
        log(cfg, f"{card['id']}: the drop was folded but the card could not be closed ({refused})")
        return None
    log(cfg, f"{card['id']}: done, {why}")
    return state


def close_folded(cfg: Config, results: dict, board: Board | None = None) -> dict:
    """Close every ask card whose drop the fetcher has folded. Returns {card id: state}.

    Autonomy decides only the PLAN gate. Every card still has an outcome gate at review,
    and for an ask card that gate is empty: the drop is folded by the fetcher before anyone
    looks at it, so there is nothing left for a human to decide. c-270 sat at review under
    "needs you" on 2026-09-18 with its briefing already on the page, and there would be one
    of those every morning. The fold IS the approval, so the fetcher closes the card.

    Read off the disk, so a card whose drop was folded BEFORE this existed closes on the
    next pass rather than waiting for a re-drop it will never get. A drop the fold refused
    is the one case that deserves a look: it stays at review and is told why, once.
    """
    own = board is None
    if own and not cfg.db_path.exists():
        return {}      # no board, so no card is waiting on a fold
    board = board or open_board(cfg)
    closed: dict = {}
    try:
        for card in board.list_cards(stage="review"):
            state = close_one(cfg, board, card, results)
            if state:
                closed[card["id"]] = state
    finally:
        if own:
            board.close()
    return closed


# ----- tier two: asks -----

@dataclass
class Worker:
    segment: Path
    space: str
    daily_cap: int
    timeout: int
    tools: str
    body: str


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """`key: value` lines between two `---` lines; a `# comment` line or tail is dropped."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    fields: dict = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fields, "\n".join(lines[index + 1:]).strip()
        key, sep, value = line.partition(":")
        if sep and not line.lstrip().startswith("#"):
            fields[key.strip()] = value.split("#", 1)[0].strip()
    return fields, ""


def _integer(fields: dict, key: str, default: int) -> int:
    raw = fields.get(key, "")
    if raw == "":
        return default
    if not raw.isdigit():
        raise ValueError(f"{key} in worker.md is not a plain integer; refusing to spend anything")
    return int(raw)


def read_worker(segment: Path, spaces: set[str]) -> Worker:
    """The segment's worker.md; fails closed (raises ValueError) on a bad declaration."""
    fields, body = parse_frontmatter((segment / "worker.md").read_text())
    space = fields.get("space", "")
    if space not in spaces:
        raise ValueError(f"worker.md must name a space ({', '.join(sorted(spaces))})")
    return Worker(segment=segment, space=space, daily_cap=_integer(fields, "daily_cap", DEFAULT_CAP),
                  timeout=_integer(fields, "timeout", DEFAULT_TIMEOUT),
                  tools=fields.get("tools") or DEFAULT_TOOLS, body=body)


def pending_asks(segment: Path) -> list[Path]:
    asks = segment / "data" / "asks"
    if not asks.is_dir():
        return []
    return sorted(path for path in asks.glob("ask-*.json") if path.is_file())


def take_asks(cfg: Config, segment: Path, files: list[Path]) -> list[Path]:
    """Move the asks into data/asks/taken/ BEFORE the card exists: a house that dies
    half way cannot be re-run by the next pass, and losing one answer is recoverable."""
    taken = segment / "data" / "asks" / "taken"
    taken.mkdir(parents=True, exist_ok=True)
    moved = []
    for path in files:
        target = taken / path.name
        try:
            os.replace(path, target)
        except OSError as error:
            log(cfg, f"{segment.name}: could not take {path.name} ({error}); skipping it")
            continue
        moved.append(target)
    return moved


def cards_today(board: Board, segment: str) -> int:
    today = date.today().isoformat()
    return sum(1 for card in board.list_cards()
               if card["options"].get("segment") == segment and card["created_at"][:10] == today)


def drop_path(segment: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return segment / "data" / "inbox" / f"worker-{stamp}.json"


def ask_brief(worker: Worker, moved: list[Path], drop: Path) -> str:
    """The worker.md body, then this run: the ask paths (not their contents, since asks
    carry attachments a session with Read opens itself), the drop, and how to finish."""
    segment = worker.segment
    listing = "\n".join(f"  {path}" for path in moved)
    return f"""{worker.body}

--- this run ---

You are answering asks for the "{segment.name}" segment. Its directory is:

  {segment}

These ask files are yours to answer. They have already been moved out of the queue into
`data/asks/taken/`, so nothing else will pick them up:

{listing}

Read each one, do what it asks, and write your answers as ONE journal drop at:

  {drop}

The drop is the same shape the segment's app posts, and the segment's fetch.py folds it
in on its next run. The keys are k, v and t, and they are not abbreviations you may expand:

  {{"entries": [ {{"k": "<key>", "v": <value>, "t": "<ISO8601>"}}, ... ]}}

An entry using "key" or "at" instead is written to disk, parses as JSON, and is then
silently skipped by the fold. The asks are already consumed, so nothing retries them.
Check the three key names before you write the file.

When the drop is written, your turn is finished: end it. Keel reads the drop when your turn
ends and files the card at review itself, with the drop as its output. There is no command
to run and nothing to stage. If the drop is not there when your turn ends you are sent back
with its path, never with a command, because this house may have no shell to run one in.

Rules for this run, none of them negotiable:

- Write ONLY the drop above. Nothing else under {segment}/data/ is yours: it is the
  fetcher's, and the drop is your only output.
- Do NOT write into {segment}/data/asks/. Creating an ask from here would make this run
  trigger the next one, forever. If something cannot be answered, say so in an entry.
- Do NOT run commands, fetch anything over the network, or start another session.
"""


def create_card(board: Board, worker: Worker, moved: list[Path]) -> str:
    """One autonomous errand at `assigned`; `plan_ref` is worker.md so review only
    needs the drop as `--output`. `add_dirs` opens the segment to the restricted house."""
    segment = worker.segment
    drop = drop_path(segment)
    count = len(moved)
    options = {"tools": worker.tools, "segment": segment.name,
               "asks": [path.name for path in moved], "add_dirs": [str(segment)],
               "drop": str(drop)}
    card_id = board.create(worker.space, f"{segment.name}: {count} ask{'s' if count != 1 else ''}",
                           brief=ask_brief(worker, moved, drop), autonomy="autonomous",
                           repo=None, options=options, actor="fetch", stage="assigned")
    board.set_fields(card_id, {"plan_ref": str(segment / "worker.md")}, "fetch")
    return card_id


def drain_asks(cfg: Config, board: Board, segment: Path) -> str | None:
    """One segment's asks into one card, unless the cap is spent or worker.md is bad."""
    pending = pending_asks(segment)
    if not pending:
        return None
    try:
        worker = read_worker(segment, set(cfg.spaces))
    except ValueError as why:
        log(cfg, f"{segment.name}: {why}; {len(pending)} ask(s) waiting")
        return None
    spent = cards_today(board, segment.name)
    if spent >= worker.daily_cap:
        log(cfg, f"{segment.name}: daily cap reached ({spent}/{worker.daily_cap}), "
                 f"{len(pending)} ask(s) waiting")
        return None
    moved = take_asks(cfg, segment, pending)
    if not moved:
        return None
    card_id = create_card(board, worker, moved)
    log(cfg, f"{segment.name}: {card_id} created for {len(moved)} ask(s)")
    return card_id


def asks(cfg: Config, segment: str | None = None, board: Board | None = None) -> dict:
    """Every segment with a worker.md and pending asks gets one card. Returns {segment: id}."""
    own = board is None
    board = board or open_board(cfg)
    created = {}
    try:
        for path in segments(cfg, segment):
            if not (path / "worker.md").is_file():
                continue
            card_id = drain_asks(cfg, board, path)
            if card_id:
                created[path.name] = card_id
    finally:
        if own:
            board.close()
    return created


# ----- recurring cards -----

def due_cards(cfg: Config) -> dict:
    """The third thing a pass does: file every `[recurring.<key>]` card that is due
    (`keel/recurring.py`). Decided from the board alone, so a pass that runs every minute
    files each at most once: the card it filed is open, and an open card holds the next."""
    filed = recurring.file_due(cfg)
    for key, card_id in filed.items():
        log(cfg, f"recurring {key}: {card_id} filed")
    return filed
