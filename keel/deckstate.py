"""The deck's state document: everything `GET /api/state` returns, built from the board,
the harness listing, the drain log, the usage tee, the segments tree and the adapter.

Nothing here is stored. The document is rebuilt on demand and cached for a few seconds
(`Deck.state`); a write through `/api/action` drops the cache. Every card carries its
`derived` dict from `views` (`backlog`, `backlog_override` and `backlog_since` among the
rest), its newest event, the last thing its house said (the newest Stop hook's message), artifact links the
page can open, the agents row of its live house when there is one, and `idle`, the drain's
own answer for a house that has gone quiet mid-turn (`drain.idle_stuck`), which is what
keeps such a card from reading as working. Attention
(`needs_you`) and Now (`houses`, `running`) leave the backlog cards out; they are listed
on their own under `backlog` and counted per space, which is the deck's filter chip.
Each space also carries `login`, the kept answer of its login probe (`keel/login.py`,
`{state, why, at, fix}`, or None when this machine never probed it), which is what the
page's login banner reads.
"""

import contextlib
import json
import os
import re
import shlex
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from keel import asks as asks_module
from keel import bases, flowcards, flows
from keel import readings as readings_module
from keel import (adapters, artifacts, boards, bosuncards, cardfiles, cardspec, console, consolejournal,
                  deckevents, deployask, drain, dropin, fetch, firstrun, harness, housejobs, landpush, livestrip, login, merging,
                  planfacts,
                  planformat, planinline, readiness, receipt, repocommands, requests, reviewsettings, shipreplies, stuckcards,
                  terms, tree,
                  where)
from keel.board import Board, open_board
from keel.config import Config, Space

CACHE_SECONDS = 3.0
# The coarse component of `Deck.rev`: how long the page may sit on a 304 while the inputs
# that are neither a write nor the board file (the drain log, the usage tee) go stale. It
# is the ping's interval rather than the poll's, because with the event stream open this
# is also the only thing that says `state` on an afternoon where nothing else happens.
REV_SECONDS = 15.0


def clock_step() -> int:
    """Which fifteen second step the wall clock is in: `Deck.rev`'s third term.

    Its own function so a test can hold it still. Three seconds of a fifteen second step is
    a one-in-five chance of a tick, which is exactly how often the sweep's silence test
    used to fail, and a test about the board must not be a coin toss about the wall clock.
    """
    return int(time.time() // REV_SECONDS)
def usage_file(cfg=None) -> Path | None:
    """The status line's tee: `KEEL_USAGE_FILE` (the tests point it at a fixture), else
    `[machine] usage_file`; None when this machine names none, and the meter says so."""
    named = os.environ.get("KEEL_USAGE_FILE")
    if named:
        return Path(named).expanduser()
    return getattr(cfg, "usage_file", None)


USAGE_WINDOWS = (("five_hour", "Session usage", "5h window"), ("seven_day", "Weekly usage", "7d window"))
DRAIN_LINE = re.compile(r"^(?P<at>\S+)\s+(?P<text>.*)$")
LIVE_STAGES = ("planning", "building")
# c-600: a shipping card's house lives on and answers review there, so the card carries its
# house row (Talk, Stop); Now shows its tile only while it works (`houses_of`). c-604: a house
# at review is listed and idle at his outcome gate, as at the plan gate, so it carries its
# row too: without it the pane said `not listed`, Now said none running, and Open in app,
# Logs and Stop were not drawn.
HOUSE_STAGES = LIVE_STAGES + ("review", "shipping")
PERSONAL_OPTIONS = ("repo", "autonomy", "model")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


# ----- the drain pill -----

def parse_drain_line(line: str, at: datetime | None = None, host: str | None = None) -> dict:
    """`{"host", "at", "age_seconds", "text", "alive"}` from the drain log's last line.

    `alive` is whether the line is younger than a few polls; the host is the `host=` token
    when the line carries one, else the machine this server runs on (one process today).
    """
    at = at or datetime.now().astimezone()
    host = host or "here"
    match = DRAIN_LINE.match(line.strip()) if line else None
    if not match:
        return {"host": host, "at": None, "age_seconds": None, "text": "", "alive": False}
    stamp = parse_iso(match.group("at"))
    text = match.group("text")
    named = re.search(r"\bhost=(\S+)", text)
    age = int((at - stamp).total_seconds()) if stamp else None
    return {"host": named.group(1) if named else host, "at": stamp.isoformat(timespec="seconds") if stamp else None,
            "age_seconds": age, "text": text, "alive": age is not None and age < 5 * 60}


def last_line(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 4096))
            lines = handle.read().decode("utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        if DRAIN_LINE.match(line) and "drain" in line:
            return line
    return lines[-1] if lines else ""


def drain_status(cfg: Config) -> dict:
    return parse_drain_line(last_line(cfg.logs_dir / drain.LOG_NAME), host=cfg.host)


# ----- usage -----

def read_usage(path: Path | None = None, at: float | None = None, cfg=None) -> dict:
    """The status line's tee: two windows with used percentage and reset time, plus age."""
    path = path or usage_file(cfg)
    at = at or time.time()
    try:
        data = json.loads(path.read_text()) if path else None
    except (OSError, ValueError):
        data = None
    if data is None:
        return {"available": False, "age_seconds": None, "windows": [], "model": None}
    limits = data.get("rate_limits") or {}
    windows = []
    for key, label, span in USAGE_WINDOWS:
        window = limits.get(key) or {}
        if "used_percentage" not in window:
            continue
        resets = window.get("resets_at")
        windows.append({"key": key, "label": label, "span": span,
                        "used": int(window.get("used_percentage") or 0),
                        "resets_at": datetime.fromtimestamp(resets, timezone.utc).astimezone().isoformat(timespec="seconds") if resets else None})
    captured = data.get("captured_at")
    age = int(at - captured) if captured else None
    return {"available": bool(windows), "age_seconds": age, "windows": windows,
            "model": data.get("model")}


# ----- segments -----

NOT_FETCHED = "not fetched yet"
FETCH_FAILED = "not fetched yet: its fetcher failed (state/logs/fetch.log says why)"


def segment_entry(directory: Path) -> dict | None:
    """One segment for the page. `fetched` is false for a segment that has a fetcher and no
    summary yet (c-742): it is installed and has never been fetched, and `fetch_said` is the
    page's words for that, which name a fetcher whose last run failed. A directory with
    neither a summary nor a fetcher is not a segment the page can say anything about."""
    summary_path = directory / "summary.json"
    fetched = summary_path.is_file()
    if not fetched and not (directory / "fetch.py").is_file():
        return None
    try:
        summary = json.loads(summary_path.read_text()) if fetched else {"tiles": [], "notes": []}
    except (OSError, ValueError):
        summary = {"tiles": [], "notes": ["summary.json is unreadable"]}
    has_app = (directory / "app" / "index.html").is_file()
    entry = {"name": directory.name, "summary": summary, "has_app": has_app, "fetched": fetched,
             "app_url": f"/segments/{directory.name}/app/" if has_app else None,
             "generated_at": summary.get("generated_at") or summary.get("rendered_at")}
    if not fetched:
        failed = (fetch.read_stamp(directory) or {}).get("state") == "failed"
        entry["fetch_said"] = FETCH_FAILED if failed else NOT_FETCHED
    return entry


def segments(cfg: Config) -> list[dict]:
    """One entry per segment name across `cfg.segment_roots`, the first root winning."""
    found: dict[str, Path] = {}
    for root in cfg.segment_roots:
        if not root.is_dir():
            continue
        for directory in root.iterdir():
            if directory.is_dir() and not directory.name.startswith((".", "_")):
                found.setdefault(directory.name, directory)
    entries = []
    for name in sorted(found):
        entry = segment_entry(found[name])
        if entry:
            entries.append(entry)
    return entries


# ----- spaces, options, providers, adapter verbs -----

def options_for(space: Space, cfg=None) -> list[dict]:
    """The space's option sheet: the adapter's options.json, or the built-in subset. Its
    `model` row offers real models only and defaults to the space's, else `[keel] model`;
    its autonomy and plan style rows default to the space's settings (`cardspec.sheet`)."""
    if cfg is None:
        return cardspec.sheet(space)
    # c-732 r2.F4: Base branch only for a card on a repo without an integration branch
    return cardspec.sheet(space, cfg.model, bases.integrated(cfg, space))


def declared_routes(space: Space) -> list[str]:
    """The provider routes this space's adapter ships, by the executables on this disk."""
    if space.adapter_dir is None:
        return []
    return [route for route in adapters.routes_of(space)
            if os.access(space.adapter_dir / "providers" / route, os.X_OK)]


def space_providers(cfg: Config, space: Space, kept: readings_module.Kept | None = None) -> dict:
    """A space's provider routes, from the deck's kept reading when it has one (c-638)."""
    if kept is not None:
        # A route that fails holds every route at its last good reading until it answers.
        return kept_or_soft(kept, space.name, lambda: adapters.providers_for(space, strict=True),
                            lambda: adapters.providers_for(space), (OSError,), stale=scan_moved(cfg, space.name))
    return adapters.providers_for(space)


# c-734 (14): the Reviews gear's `scan_asked` comes from a provider reading the deck keeps for
# 30 seconds, so after the drain's scan cleared the ask (`reviewsettings.scanned`) and filed its
# card the gear still said Scanning. A change to the scan file makes the space's reading stale.
SCAN_SEEN: dict = {}


def scan_moved(cfg: Config, name: str) -> bool:
    """Whether `state/review-scan.json` changed since this space's providers were last read
    here (the first look is not a change)."""
    try:
        stamp = reviewsettings.scan_path(cfg).stat().st_mtime_ns
    except OSError:
        stamp = None
    key = (str(reviewsettings.scan_path(cfg)), name)
    moved = key in SCAN_SEEN and SCAN_SEEN[key] != stamp
    SCAN_SEEN[key] = stamp
    return moved


adapter_verbs = adapters.card_verbs
adapter_links = adapters.card_links


def kept_or_soft(kept: readings_module.Kept, key, strict, soft, failures, stale: bool = False):
    """`kept`'s reading of `key`, read `strict`. When nothing is held yet and the strict read
    fails, the `soft` answer (the caller's old one, a failure read as empty) is answered
    and seeded as old, so it is read again on a thread rather than in every build (c-638).
    `stale`: the caller knows the held reading is out of date, so it is read again now."""
    try:
        return kept.get(key, strict, stale=stale)
    except failures:
        value = soft()
        kept.seed(key, value)
        return value


def space_links(space: Space, ids: list[str], kept: readings_module.Kept | None = None) -> dict:
    """`act links` for these cards: read now, or from the deck's kept reading (c-638), which
    answers at once and is read again, on its own thread, when it is old or covers fewer
    cards than asked (a card that just went live gets its links a refresh later)."""
    if kept is None:
        return adapter_links(space, ids)
    want = frozenset(ids)
    held = kept.peek(space.name)
    try:
        covered, links = kept.get(space.name,
                                  lambda: (want, adapter_links(space, sorted(want), strict=True)),
                                  stale=held is not None and not want <= held[0])
    except adapters.ReadingFailed:
        # nothing read yet, and this one failed: no links, as before, read again off the request
        kept.seed(space.name, (frozenset(), {}))
        return {}
    return {card_id: links[card_id] for card_id in ids if card_id in links}


def space_counts(cards: list[dict], name: str) -> dict:
    """What the space's chips count: its unarchived cards, the ones at a gate or blocked,
    and the ones that have backlogged. The card and backlog counts are the Cards page's, so
    a review card (listed on Reviews only, 2026-09-24) is not in them; one at his gate is
    still in needs-you, as it is in Attention."""
    mine = [card for card in cards if card["space"] == name and not card["derived"]["archived"]]
    on_cards = [card for card in mine if not (card.get("options") or {}).get("review_key")]
    return {"cards": len(on_cards),
            "needs_you": sum(1 for card in mine if card["derived"]["needs_you"]),
            "backlog": sum(1 for card in on_cards if card["derived"]["backlog"])}


def space_topics(cards: list[dict], name: str) -> list[str]:
    """The distinct topics on the space's unarchived cards, for the Cards group-by."""
    return sorted({card["topic"] for card in cards
                   if card["space"] == name and card["topic"]
                   and not card["derived"]["archived"]})


def space_verbs(space: Space, kept: readings_module.Kept | None = None) -> dict:
    """The adapter's card verbs, kept by the deck (c-638)."""
    if kept is not None:
        return kept_or_soft(kept, space.name, lambda: adapter_verbs(space, strict=True),
                            lambda: {"card": []}, (adapters.ReadingFailed,))
    return adapter_verbs(space)


def space_entry(cfg: Config, space: Space, cards: list[dict],
                kept: readings_module.Readings | None = None, board=None) -> dict:
    said = lands_said(cfg, space, board)
    return {"name": space.name, "adapter": space.adapter, "repos": list(space.repos),
            "options": options_for(space, cfg),
            "verbs": space_verbs(space, kept.verbs if kept else None),
            "topics": space_topics(cards, space.name),
            "counts": space_counts(cards, space.name),
            "login": login.public(cfg, space.name),
            # c-678: the repos whose work lands with no test run, each with why, for the card
            "untested": said["untested"],
            # c-678 review: the repos whose landing will be refused (their file changed since
            # it was adopted or saved), each with the sentence, for the card
            "unlandable": said["unlandable"],
            # c-630: what this space calls a ticket and a change, which K.term reads
            "terms": terms.public(terms.of(cfg, space)),
            # c-718: the space's pack stacks a waiting card on the one it waits for, so the
            # Split sheet asks stacked or independent for a slice that waits
            "stacks": space.name in cfg.stacking,
            # c-640: how the space's work moves, and an open proposal to change it
            "flow": dict(flows.drawn(cfg, space),
                         proposal=flowcards.proposals_in(cards).get(space.name),
                         adopted=space.name in flowcards.adopted_in(cards))}


def lands_said(cfg: Config, space: Space, board=None) -> dict:
    """What a card of each repo says before the tap, for a space that lands by a merge on
    this machine (no pack): `untested` `{repo key: sentence}` where Approve lands with no
    test run (`repocommands.untested`), and `unlandable` where Approve will be refused, the
    repo's file having changed since it was adopted or saved (`repocommands.will_refuse`).
    Read on the state build's own board (review r2.F8): no board is opened here."""
    found = {"untested": {}, "unlandable": {}}
    if space.adapter_dir is not None:
        return found
    for key in space.repos:
        refused = repocommands.will_refuse(cfg, space.name, key, board)
        if refused:
            found["unlandable"][key] = refused
            continue
        why = repocommands.untested(cfg, space.name, key, board)
        if why:
            found["untested"][key] = f"{why}, so Approve lands this without running any tests."
    return found


def builder_facts(board) -> dict:
    """What the card form needs to say who works a personal card (c-645, `views.bosun_eligible`)."""
    every = bool(getattr(board, "superuser", False))
    return {"on": bool(getattr(board, "builder", False)),
            "builds": None if every else sorted(getattr(board, "builds", ()) or ()),
            "lands": every or bool(getattr(board, "bypass", False))}


# ----- Bosun -----

JOURNAL_MAX = 50
# The answered, redirected and withdrawn asks the Bosun page's Now keeps below the open ones.
ASKS_CLOSED = 10
# Answered asks stay on the Bosun page's Now for a day, folded; after that only the Journal has
# them (2026-09-26, his call: old questions should not pile up there).
ASKS_CLOSED_HOURS = 24


def closed_since() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=ASKS_CLOSED_HOURS)).isoformat(timespec="seconds")


def bosun_board(cfg: Config, board: Board) -> dict:
    """What the Bosun page reads off the board, with or without a console session: the open
    and taken requests (c-520), the open asks and the last closed ones (c-521), their counts
    (the header's grey number is `requests`, its red one `asks`), the moves on both that the
    Journal reads beside the session's taps, with its throughput and its gaps (c-524), and
    what the Shipped section reads of the deploy asks (c-591, `deployask.shipped`)."""
    waiting = requests.listing(board)
    opened = sum(1 for row in waiting if row["state"] == "open")
    moves = requests.journal(board, JOURNAL_MAX) + asks_module.journal(board, JOURNAL_MAX)
    moves = sorted(moves, key=lambda move: move["id"], reverse=True)[:JOURNAL_MAX]
    throughput = consolejournal.throughput(board, list(cfg.spaces), board.now())
    # VOICE HOLDS BOSUN (c-523): read from the board.
    return dict(voice=bool(board.bosun_hold()), requests=waiting, journal=moves,
                throughput=throughput, gaps=consolejournal.gap_rows(board),
                shipped=deployask.shipped(board, wait=2 * float(cfg.poll_seconds or 0)),
                asks=asks_module.listing(board, closed=ASKS_CLOSED, since=closed_since()),
                counts=dict(requests=opened, asks=asks_module.open_count(board)))


def console_entry(cfg: Config, board: Board, parts: dict | None = None) -> dict | None:
    """Bosun's session as `console.view` says it, with what the board holds for it
    (`bosun_board`); None when there is no console session, and then the state carries the
    board's half on its own as `bosun`."""
    view = console.view(cfg)
    if view is None:
        return None
    parts = parts if parts is not None else bosun_board(cfg, board)
    return dict(view, attach=attach_line(cfg),
                **dict(parts, counts=dict(view.get("counts") or {}, **parts["counts"])))


def attach_line(cfg: Config) -> str:
    """The command that joins Bosun's session from a terminal on this machine (c-634): the
    install's own `bin/keel`, so the Console never names another machine to ssh into. It is
    shown with Copy, so the path is quoted where a shell would split it (c-677)."""
    home = cfg.install_home or cfg.root
    return f"{shlex.quote(f'{home}/bin/keel')} console attach"


# ----- cards and houses -----

def newest_events(board: Board) -> dict[str, dict]:
    rows = board.conn.execute(
        "SELECT card, kind, actor, at, text FROM events WHERE id IN "
        "(SELECT MAX(id) FROM events GROUP BY card)")
    return {row["card"]: {"kind": row["kind"], "actor": row["actor"], "at": row["at"],
                          "text": row["text"]} for row in rows}


def children_of(board: Board) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in board.conn.execute("SELECT id, parent FROM cards WHERE parent IS NOT NULL ORDER BY created_at, id"):
        out.setdefault(row["parent"], []).append(row["id"])
    return out


def house_row(card: dict, rows: list[dict]) -> dict | None:
    """The agents row for this card's session, by uuid or by the house's name.

    `recorded` says which (c-601): a row found by name alone is not the session the card
    records (an orphan of an earlier start, a fresh one not yet recorded), and Stop and Logs
    act on the recorded one, so the pane draws them only for a row that is it. `twins` are
    the OTHER live sessions sharing the card's name (`tellhouse.refuse_twins` names them),
    which the pane offers to stop."""
    row = livestrip.row_of(card, rows)
    facts = dropin.row_facts(row)
    if not facts:
        return None
    recorded = harness.find(card.get("session_id") or "", rows) is not None
    return dict(facts, recorded=recorded, twins=twins_of(card, rows, row))


def twins_of(card: dict, rows: list[dict], row: dict | None) -> list[str]:
    """The short ids of the other live sessions named for the card, while two or more are."""
    named = [r for r in rows if r.get("name") == card["id"] and housejobs.has_process(r)]
    if len(named) < 2:
        return []
    return [str(r.get("id") or r.get("sessionId")) for r in named if r is not row]


def links_for(cfg: Config, card: dict) -> dict:
    """The card's links: plan, the plan's live lavish surface, output and context record.
    `plan_live` is the plan's lavish surface while lavish still has a session for that file:
    the page he can annotate, on the deck's own origin, rather than the static copy the token
    serves. Null when there is no session, and then `plan` is what the deck opens."""
    context = cfg.cards_dir / card["id"] / "context.md"
    return {"plan": artifacts.url(cfg, card.get("plan_ref")),
            "plan_live": artifacts.lavish_surface(cfg, card.get("plan_ref")),
            # c-719: a named markdown output in the card's folder opens in the viewer
            "output": cardfiles.output_page(cfg, card) or artifacts.url(cfg, card.get("output_ref")),
            "context": artifacts.url(cfg, context) if context.is_file() else None,
            # The plan pages (P4-5): which documents are in the format and what they ask.
            "docs": planfacts.doc_facts(cfg, card) if card.get("stage") in livestrip.LIVE_STAGES else {}}


def unpublished_of(cfg: Config, card: dict, links: dict | None = None) -> str | None:
    """c-551: the adapter's line saying his Approve could not publish this card at the gate,
    read the way the deck reads every card's links, for the outcome page, which is opened
    without the deck's state. `links` is the card's adapter links when the caller already
    read them (`adapter_links_of`)."""
    if card.get("stage") != "review":
        return None
    return publish_refusal(cfg, card) or (
        links if links is not None else adapter_links_of(cfg, card)).get("unpublished")


def publish_refusal(cfg: Config, card: dict) -> str | None:
    """c-631: the sentence `adapters.publish` refuses this card's Approve with, said at the
    gate before the tap: a repo card at review in a space whose pack does not declare a
    code host. None for a space with no pack, which merges locally."""
    space = cfg.spaces.get(card.get("space") or "")
    if card.get("stage") != "review" or space is None or space.adapter_dir is None:
        return None
    return readiness.refusal(cfg, space, "codehost") if adapters.repos_of(card) else None


def adapter_links_of(cfg: Config, card: dict) -> dict:
    """One card's adapter links (`act links`); empty for a space with no adapter."""
    space = cfg.spaces.get(card.get("space") or "")
    if space is None or space.adapter_dir is None:
        return {}
    return adapter_links(space, [card["id"]]).get(card["id"]) or {}


# The stages whose outcome page links the card's pull requests (c-565): from his gate on.
OUTCOME_STAGES = ("review", "shipping", "done")


def pulls_of(links: dict) -> list[dict]:
    """The card's pull requests as the adapter linked them, `{repo, pr, url}` each (c-565)."""
    return [one for one in links.get("prs") or [] if isinstance(one, dict) and one.get("url")]


EMPTY_LINKS = {"plan": None, "plan_live": None, "output": None, "context": None, "docs": {}}


def idle_of(cfg: Config, board: Board, card: dict, rows: list[dict]) -> dict | None:
    """What the drain's quiet-house rule says about this card (`drain.idle_stuck`): it is
    idle mid-turn, since when, and when the drain will put it back.

    Asked of the drain rather than worked out from the agents row, so the house word and the
    drain cannot disagree about whether a house is working. None for every card the rule does
    not hold for, which is almost all of them.
    """
    if card["stage"] not in LIVE_STAGES:
        return None
    return drain.idle_stuck(cfg, board, card, rows)


def jobs_of(cfg: Config, card: dict, facts: dict | None) -> list[dict]:
    """The background jobs still running under this card's house while it is idle, read
    from the harness's job record (`keel/housejobs.py`): `{id, label, started_at}` each.
    Empty for a house in a turn, and for no house."""
    space = cfg.spaces.get(card["space"])
    if not facts or space is None:
        return []
    return housejobs.of_row(space.config_dir, {"id": facts.get("bg_id"), "state": facts.get("state")})


def base_of(cfg: Config, card: dict) -> str:
    """The base that applies to the card, as the server reads it (`merging.card_base`): its own
    `options.base`, except on a repo with an integration branch, where none applies (c-732).
    The deck's move buttons read this (`K.flowMoves`), never the option as stored."""
    return merging.card_base(cfg, card) or ""


def card_view(cfg: Config, board: Board, card: dict, newest: dict, kids: dict,
              rows: list[dict], extra_links: dict, strip: livestrip.Strip | None = None,
              live: dict | None = None) -> dict:
    view = dict(card)
    view["last_event"] = newest.get(card["id"])
    view["children"] = kids.get(card["id"], [])
    view["house"] = live_house(card, rows)
    # c-601 review: a done card whose own session the harness still lists, for the pane's
    # post-mortem Logs (and nothing else: a done card has no house to act on)
    view["lingering"] = bool(card["stage"] == "done" and card.get("session_id")
                             and harness.find(card["session_id"], rows))
    # c-599: what the house is doing now, and the newest Notification of its turn, drawn at once rather than when the drain blocks
    view["live"] = (live or {}).get(card["id"]) or (strip.of_session(card) if strip else None)
    view["notice"] = None
    if card["stage"] in LIVE_STAGES and card.get("session_id"):
        view["notice"] = livestrip.notice(card, board.events(card["id"]))
        if view["notice"] and livestrip.written_past(view["notice"], view["live"]):
            view["notice"] = None       # the house carried on after it: answered
    view["idle"] = idle_of(cfg, board, card, rows)
    view["jobs"] = jobs_of(cfg, card, view["house"])
    view["last_said"] = None
    if card["stage"] in HOUSE_STAGES or card["blocked_reason"]:
        view["last_said"] = drain.stop_message(board, card["id"])
    # c-678: a block read into what happened and its fix, where it is one Keel knows
    # (a session that will not start, a refused landing; `keel/stuckcards.py`)
    view["stuck"] = stuckcards.read(cfg, card, board) if card["blocked_reason"] else None
    view["base"] = base_of(cfg, card)
    view["links"] = dict(links_for(cfg, card), **(extra_links.get(card["id"]) or {}))
    docs = view["links"].pop("docs", None) or {}
    # c-551: the adapter's word that his Approve could not publish this card, and why; the
    # gate draws it in place of Approve outcome; c-631: or the code host it does not declare
    unpublished = view["links"].pop("unpublished", None)
    view["unpublished"] = publish_refusal(cfg, card) or unpublished
    view["links"]["formats"] = planfacts.formats(docs)
    view["plan_doc"] = None
    if planfacts.gate_doc(card) and any(docs.values()):
        view["plan_doc"] = planfacts.row(docs, card, board.events(card["id"]))
    return view


def houses_of(cards: list[dict]) -> list[dict]:
    """Every card with a live house, or blocked with a session: what the Now strip shows.

    A tracking card is one only while its own session is busy, and so is a shipping or done
    card (c-600: its house lives on between batches, idle, and after the merge), except a
    BLOCKED shipping card with a listed house, whose tile carries Unblock (c-605). It borrows its stage from its
    children, so an idle parent at `building` drew a house tile saying "idle 3h" beside a
    slice that was actually working (c-277, 2026-09-20); the slices are the houses, and Now
    already gathers them onto the parent's own tile.
    """
    out = []
    for card in cards:
        if card["derived"]["archived"] or card["derived"]["backlog"]:
            continue
        if (card["derived"]["tracking"] or card["stage"] in ("shipping", "done")) and not busy_house(card) \
                and not blocked_shipping(card):
            continue
        if card["house"] or (card["blocked_reason"] and card["stage"] in LIVE_STAGES):
            out.append(card["id"])
    return out


def blocked_shipping(card: dict) -> bool:
    """c-605: a blocked shipping card whose house is listed idle is on Now all the same: the
    block is his to lift, and the tile is where Unblock is (`houseActionNodes`). Never a
    tracking parent: Now already draws its tile for its slices, so a second one would carry
    the same key (c-605 review)."""
    return (card["stage"] == "shipping" and bool(card["blocked_reason"]) and bool(card["house"])
            and not card["derived"]["tracking"])


def busy_house(card: dict) -> bool:
    # the drain's pool rule (`drain.working_now`), so the header agrees with the drain log
    return bool(card["house"]) and card["house"].get("status") == "busy"


def running_of(board: Board, cards: list[dict], rows: list[dict]) -> list[str]:
    """The houses holding a pool slot, by the drain's own rule, so the header's count of
    `houses_max` agrees with the drain log. An idle house at its plan gate is not running."""
    holding = drain.house_ids(board, rows)
    return [c["id"] for c in cards if c["id"] in holding and not c["derived"]["backlog"]]


# ----- what a page asks for (c-540) -----

# The pages ask for a SCOPE; a bare `/api/state` is the whole document, as every machine
# reader (Harbor's digest, the voice gateway, the cutover checks) has always read it. A
# scope keeps only the cards that page draws and clips each brief: briefs were half of a
# 2 MB document, and only the pane shows a whole one, from `/api/card/<id>`.
SCOPES = ("deck", "bosun")
# How many scoped documents the deck keeps at once: a page per (scope, archived, open card).
KEPT_DOCUMENTS = 8
BRIEF_CHARS = 400


def in_scope(card: dict, scope: str | None, archived: bool, asked: str | None = None) -> bool:
    """Does a page asking for `scope` get this card. The top-level lists never read this:
    they are the whole board's in every scope, so a count or needs-you cannot move with it.
    `asked` is the card the page has open (`?card=`): it is held whatever the scope, so the
    Inspector can open a personal card an ask names, or an archived one
    it was linked to (c-540, review F2)."""
    if scope is None or card["id"] == asked:
        return True
    if card["derived"]["archived"] and not archived:
        return False
    if scope == "bosun":
        # The Bosun page (app/ui.console.js, c-591): the cards Bosun builds, and nothing else.
        return bool(card["derived"].get("bosun"))
    return True


# A page draws its LIVE part first and brings the done cards in behind the draw (c-549): done
# cards were 225 of the deck's 294 and two thirds of its bytes. Both parts are cut from the
# one scoped build, so asking for two costs no second build; a scope with no part is whole.
PARTS = ("live", "done")


def in_done_part(view: dict, asked: str | None = None) -> bool:
    """Does this card travel in the done part. Done, and nothing about it is live: a done
    card that needs him, has a house, is blocked or is the page's open card stays live, so
    the first draw never misses a card any count, gate or tile reads. So does a REVIEW
    card: a posted review is `done` and Reviews lists it by default (`review_state`)."""
    stage = view["derived"].get("parent_stage") or view["stage"]
    return (stage == "done" and view["id"] != asked and not view["derived"].get("needs_you")
            and not view.get("house") and not view.get("blocked_reason")
            and not (view.get("options") or {}).get("review_key")
            # c-592: a Keel card he filed that is on next, not live, still shows on his board
            and not (view["derived"].get("keel_card") or {}).get("shown"))


def part_of(doc: dict, part: str, asked: str | None = None) -> dict:
    """One part of a scoped document, never the cached one itself. The live part is the
    document with the done cards taken out: every top-level list stays the whole board's.
    The done part is those cards alone, with `now` and `scope`, and nothing else."""
    done = part == "done"
    cards = [view for view in doc["cards"] if in_done_part(view, asked) == done]
    scope = dict(doc["scope"], part=part)
    if done:
        return {"now": doc["now"], "cards": cards, "scope": scope}
    return dict(doc, cards=cards, scope=scope)


def clipped(view: dict) -> dict:
    brief = view.get("brief") or ""
    if len(brief) > BRIEF_CHARS:
        view["brief"] = brief[:BRIEF_CHARS]
        view["brief_clipped"] = True
    return view


def idle_houses(cards: list[dict]) -> list[str]:
    """The cards whose house the harness lists out of a turn (`housejobs.working`, through
    the row's `working`), at a live stage, not archived: the houses holding memory while
    doing nothing (c-607). Idle is the harness's word, never a guess from how quiet it is."""
    return [card["id"] for card in cards
            if card.get("house") and not card["house"].get("working")
            and card["stage"] in HOUSE_STAGES and not card["derived"]["archived"]
            and card["house"].get("kind") != dropin.INTERACTIVE]


def live_house(card: dict, rows: list[dict]) -> dict | None:
    """`card_view`'s house, alone: what Now needs of a card the scope left out. A
    shipping card's house lives on (c-600), so it has one too, and so does a done card whose
    session the harness still lists: the merge made it done, and the drain ends that house
    only once the harness lists it idle (a-72, `keel/shipidle.py`), so while it works the row
    is where his Stop is drawn."""
    if card["stage"] == "done" and card.get("session_id"):
        return house_row(card, rows)
    if not (card["stage"] in HOUSE_STAGES or card["blocked_reason"]):
        return None
    return house_row(card, rows)


def listing_ahead(cfg: Config) -> Callable[[], list[dict]]:
    """Start the harness listing in a thread and hand back its join. It is the slower half
    of a cold build (a `claude agents` per config dir), so the board is read meanwhile."""
    out: dict = {}

    def listing():
        try:
            out["rows"] = harness.agents_across(space.config_dir for space in cfg.spaces.values())
        except BaseException as error:  # noqa: BLE001 - handed to the join, raised there
            out["error"] = error

    worker = threading.Thread(target=listing, name="deck-agents", daemon=True)
    worker.start()

    def join() -> list[dict]:
        worker.join()
        if "error" in out:
            raise out["error"]
        return out.get("rows", [])
    return join


def build(cfg: Config, board: Board, rows: list[dict] | None = None,
          scope: str | None = None,
          archived: bool = False, listing: Callable[[], list[dict]] | None = None,
          asked: str | None = None, strip: livestrip.Strip | None = None,
          readings: readings_module.Readings | None = None, steps: bool = True) -> dict:
    """The whole document; `rows` is the harness listing (tests pass their own). `scope` and
    `archived` say which
    cards the page gets in `cards` (`in_scope`); every other key is the whole board's.
    `listing` is a started listing's join (`Deck.listing`), else one is started here.
    `readings` is the deck's kept readings (c-638): with them, nothing slow runs here.
    `steps` is whether the page shows the first-run steps (the Start view asks, `?steps=1`):
    without it a finished install's steps are not read (`firstrun.report`, c-678 review)."""
    joined = (lambda: rows) if rows is not None else (listing or listing_ahead(cfg))
    with artifacts.roots_held(cfg):
        newest, kids = newest_events(board), children_of(board)
        raw = board.list_cards()
        # c-592: a Keel card's filer, Bosun's state and whether his board shows it
        bosuncards.annotate(cfg, board, raw, readings and (
            lambda config: kept_or_soft(readings.on_next, "next",
                                        lambda: bosuncards.on_next(config, strict=True),
                                        lambda: bosuncards.on_next(config),
                                        (merging.MergeRefused, OSError))))
        kept = [card for card in raw if in_scope(card, scope, archived, asked)]
        extra = {}
        for space in cfg.spaces.values():
            if space.adapter_dir is not None:
                # every live card of the space, whatever this page's scope: one kept reading
                # serves every scope, and a narrow page must not narrow it (c-638 review)
                ids = [c["id"] for c in (raw if readings else kept)
                       if c["space"] == space.name and not c["derived"]["archived"]]
                extra.update(space_links(space, ids, readings.links if readings else None))
        rows = joined()
        live = livestrip.facts_for(cfg, kept, rows)
        cards = [card_view(cfg, board, card, newest, kids, rows, extra, strip, live) for card in kept]
        if scope is not None:
            cards = [clipped(view) for view in cards]
            for view in cards:
                if not in_scope(view, scope, archived):
                    view["outside"] = True      # held only because the page has it open
    housed = [dict(card, house=live_house(card, rows)) for card in raw]
    ready = readiness.build(cfg)
    parts = bosun_board(cfg, board)
    entry = console_entry(cfg, board, parts)
    spaces_out = {name: space_entry(cfg, space, raw, readings, board) for name, space in cfg.spaces.items()}
    return {
        "now": now_iso(),
        "cards": cards,
        # Harbor reads this list out loud. A card of a space no longer configured (the
        # retired console, c-593) is never in it.
        "needs_you": [c["id"] for c in raw if c["derived"]["needs_you"] and c["space"] in cfg.spaces],
        # The assigned cards in the order the drain takes them (`tree.queue`): the Cards
        # view numbers them, so the deck never works the order out a second way.
        "queue": tree.queue(raw),
        "backlog": [c["id"] for c in raw
                    if c["derived"]["backlog"] and not c["derived"]["archived"]],
        "houses": houses_of(housed),
        # c-607: every listed house out of a turn at a live stage, wherever Now draws it or not
        # (an idle shipping house has no Now tile): Now's Idle houses panel reads these.
        "idle": idle_houses(housed),
        "running": running_of(board, raw, rows),
        "drain": drain_status(cfg),
        "usage": read_usage(cfg=cfg),
        "segments": segments(cfg),
        "spaces": spaces_out,
        "providers": {name: space_providers(cfg, space, readings.providers if readings else None)
                      for name, space in cfg.spaces.items() if space.adapter_dir is not None},
        # What is set up and what is not, per space and for the install (c-629): the pages
        # that depend on a capability and the first-run stepper read this, not a guess.
        "readiness": ready,
        # The first-run stepper (c-632): each step done, skipped or open, Finish, and whether
        # the deck opens Start in place of Now. Done is read from `ready`, never stored.
        "firstrun": (first := firstrun.report(cfg, board, ready, steps=steps)),
        # Bosun's session (c-519): the header's entry and the Console page's strip.
        "console": entry,
        # The Bosun page's board half (Shipped, the asks, the Journal) when there is no
        # console session to carry it.
        "bosun": None if entry else dict(parts, attach=attach_line(cfg)),
        # `{card id: line}`: a startable card the drain will not start, and why
        # (`keel/where.py`). The row and the pane both show it.
        "waiting": where.waiting(cfg, raw),
        # Which cards `cards` holds, so a page can tell a card it was not sent from one
        # that does not exist (it asks again with `archived=1`).
        "scope": {"name": scope or "all", "archived": archived or scope is None, "card": asked,
                  # whether every first-run step was read: the Start view asks again when not
                  "steps": not any(step.get("light") for step in first["steps"])},
        "config": {"houses_max": cfg.houses_max, "drain_paused": cfg.drain_paused,
                   "rotate": cfg.rotate, "merge_queue": cfg.merge_queue,
                   "lavish_port": cfg.lavish_port, "backlog_days": cfg.backlog_days,
                   # c-592: while plans are pages, the card form's Plan style decides nothing
                   "plan_pages": cfg.plan_pages,
                   # c-645: who may work a personal card, for the form's Worker row: builder
                   # mode, the repos Bosun builds (None: every one), and whether he lands
                   "builder": builder_facts(board),
                   # c-633: what the loader did not take (an unknown key, a wrong value);
                   # Now draws them in a warning panel with a way to Settings
                   # c-640: and a space flow file that did not load (the next one is used)
                   "warnings": list(cfg.warnings) + [line for one in spaces_out.values()
                                                     for line in one["flow"]["warnings"]],
                   # c-678: the unknown keys among them, each with its fix (`keel/stuckcards.py`)
                   "unknown": stuckcards.unknown_keys(cfg)},
    }


# ----- one card's detail -----

def research_said(text: str) -> str:
    """What a research outcome (`kind: research`, c-719) says it found, for the pane's "what
    it says": its lede, the paragraph under its title, in plain words; else the first
    paragraph of its Findings. Empty for any other record."""
    if not text.startswith("---"):
        return ""
    doc = planformat.parse(text, "context.md")
    if doc["kind"] != "research":
        return ""
    if doc.get("summary"):
        return planinline.plain(doc["summary"])
    first = next((b for b in planformat.section_blocks(doc, "findings") if b["type"] == "paragraph"), None)
    return planinline.plain(first["text"]) if first else ""


def section(text: str, heading: str) -> str:
    text = planformat.strip_comments(text)          # read as the page reads it (c-719 r1.F4)
    match = re.search(rf"^##\s*{re.escape(heading)}[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.S | re.M | re.I)
    return match.group(1).strip() if match else ""


PR_BODY = re.compile(r"^##\s*PR body[^\n]*\n(.*)\Z", re.S | re.M | re.I)
PLACEHOLDER = re.compile(r"^_.*_$")


def pr_body(text: str) -> str:
    """The PR body the pane shows: exactly what the work adapter's `pulls.pr_body_section`
    posts, so the pane never shows less than the pull request will say (lane RETIRE, RT-3).
    In an outcome in the plan format it is the ```copy block under `## PR body`; otherwise
    it is everything under that heading TO THE END OF THE FILE, because the body carries
    `##` headings of its own and a section read would stop at the first of them. An empty
    section or a single italic placeholder line is no body."""
    if text.startswith("---"):
        doc = planformat.parse(text, "context.md")
        for block in planformat.section_blocks(doc, "pr_body"):
            if block["type"] == "copy":
                return block["text"].strip()
    match = PR_BODY.search(planformat.strip_comments(text))
    body = match.group(1).strip() if match else ""
    if "\n" not in body and PLACEHOLDER.match(body):
        return ""
    return body


def touched(path: Path | None) -> str | None:
    """When the plan file was last written, for the pane's plan block.

    The deck knows nothing else about when a plan moved: the board records the approve and
    the `set` that pointed at it, but a house rewriting the document in place is not an
    event. An `http` plan_ref has no mtime here, and then the page falls back to those
    events. Null rather than an exception on anything unreadable.
    """
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds") if path else None
    except OSError:
        return None


def detail(cfg: Config, board: Board, card_id: str, listed: list | None = None) -> dict:
    """`listed` is the card's files when the caller already listed them (r1.F11)."""
    card = board.get(card_id)
    files = card_files(cfg, card)
    text = files["context"]
    events = board.events(card_id)
    return {"card": card, "events": events, "context": text,
            # c-537: the newest gate answer and what follows it, as the plan page draws it
            "receipt": receipt.receipt(cfg, card, events, None),
            "pr_body": pr_body(text), "stands": section(text, "Where it stands"),
            # c-719: a research outcome opens with what it found, not where it stands
            "findings": research_said(text),
            "plan_text": files["plan_text"], "plan_at": files["plan_at"],
            # c-719: every markdown file the card wrote, each a page of its viewer
            "files": cardfiles.listed(cfg, card) if listed is None else listed,
            # The card's newest board, beside plan, output and context: a card that has
            # been drawn on carries a record of what it was shown as, and the pane links
            # it. The board store is the deck's own host's, exactly as `state/cards` is.
            "board": boards.card_board(cfg, card_id),
            # c-678: a card that landed by a local merge, in a space with no pack: whether
            # its branch is pushed, and the button that pushes it (`keel/landpush.py`)
            "push": landpush.offer(cfg, card),
            "children": [board.get(c) for c in children_of(board).get(card_id, [])],
            # c-600: a shipping card's standing batch, one row per item its house was told
            "shipping": shipping_rows(card, events)}


def shipping_rows(card: dict, events: list[dict]) -> dict | None:
    """The standing batch and its counts for a card at shipping (`keel/shipreplies.py`)."""
    if card.get("stage") != "shipping":
        return None
    return {"rows": shipreplies.rows(card, events), "summary": shipreplies.summary(card, events)}


# The pane's preview of a plan is cut here; the plan page reads the whole file.
PLAN_TEXT_MAX = 20000


def card_files(cfg: Config, card: dict) -> dict:
    """The card's context record and plan text, for the pane."""
    context = cfg.cards_dir / card["id"] / "context.md"
    text = context.read_text(errors="replace") if context.is_file() else ""
    plan = artifacts.local_path(card["plan_ref"], cfg.root) if card.get("plan_ref") and not str(card["plan_ref"]).startswith("http") else None
    plan_text = plan.read_text(errors="replace") if plan and plan.is_file() and artifacts.kind(plan) == "markdown" else ""
    return {"context": text, "plan_text": plan_text[:PLAN_TEXT_MAX], "plan_at": touched(plan)}


# ----- the cache and the revision -----

def mtime_ns(path: Path) -> int:
    """That file's mtime in nanoseconds, or 0 when it is not there to ask."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


# WHAT THE REVISION IS NOT ALLOWED TO BE: A FILE'S MTIME.
#
# It was, and it was wrong on the running deck. The board runs in WAL mode, so the stamp
# had to include `board.db-wal` to see another process's write; but that file exists only
# while somebody has the board open, and SQLite checkpoints it away and deletes it when the
# last connection closes. A deck opens and closes a connection on every card read, every
# action and every `kb`, so the file appeared and vanished all day and the revision
# alternated between two unrelated magnitudes with nothing written at all. The page was
# told "the state changed" on every sweep, refetched continuously, and no client ever got
# a 304 from the tag it had just been handed.
#
# So the revision is read off what the board CONTAINS. A read cannot move that.
# How long one board stamp is reused. Under the stream's own sweep interval, so it
# collapses the concurrent subscribers' calls into one query without ever being the
# reason an out-of-process write is noticed late.
STAMP_TTL = 0.2


class Deck:
    def __init__(self, cfg: Config, board_factory=None):
        self.cfg = cfg
        # With the config's switches (c-591): `derived.bosun` reads builder mode off the
        # Board, and without them no card was ever Bosun's on the deck or the Bosun page.
        # The default reads `self.cfg` when it is called, so a config read again in place
        # (`reread`, c-729) is the one the board opens with.
        self.board_factory = board_factory or (lambda: open_board(self.cfg))
        self.lock = threading.Lock()
        # One document per (scope, archived) a page asked for, each with when it was built.
        self.cached: dict[tuple, tuple[float, dict]] = {}
        self.writes = 0
        # The hello watch's last answer (`heard`, r1.F7)
        self.hello = False
        # The slow readings (c-638), kept between builds and refreshed on their own threads;
        # one that moves drops the documents and tells the pages (`moved`).
        self.kept = readings_module.Readings(self.moved)
        # The live strip (c-599): what each house is doing now, in memory only, and the
        # thread that reads it while a stream is open (`keel/livestrip.py`).
        self.strip = livestrip.Strip()
        self.watcher = livestrip.Watcher(self)
        # The stamp's own connection and memo. One connection rather than a `Board` per
        # call, because `Board.__init__` runs the schema and the migrations and this is
        # asked four times a second per open stream; one memo so the cost is one query a
        # second however many streams are open.
        self.stamp_lock = threading.Lock()
        self.stamp_conn: sqlite3.Connection | None = None
        self.stamped = ""
        self.stamped_at = 0.0

    def build(self, scope: str | None = None, archived: bool = False, asked: str | None = None,
              steps: bool = True) -> dict:
        board = self.board_factory()
        try:
            return build(self.cfg, board, scope=scope, archived=archived,
                         listing=self.listing(), asked=asked, strip=self.strip, readings=self.kept, steps=steps)
        finally:
            board.close()

    def board_stamp(self) -> str:
        """What the board holds, as one short string: the newest event and the newest card.

        Both are read with a SELECT and neither moves when somebody merely reads, which is
        the whole point. `MAX(id)` on the events table is the rowid, so it is an index seek
        rather than a count, and it moves on every write the board records; `MAX(updated_at)`
        catches a card written without an event of its own.

        The connection is kept and reused, and it only ever runs these two SELECTs. It is
        idle between them, so it does not hold a read transaction open and does not stop
        the log being checkpointed. Anything unreadable answers the empty string, which is
        a revision that does not move rather than an error on a poll.
        """
        with self.stamp_lock:
            if self.stamped and time.monotonic() - self.stamped_at < STAMP_TTL:
                return self.stamped
            try:
                if self.stamp_conn is None:
                    self.stamp_conn = sqlite3.connect(self.cfg.db_path, isolation_level=None,
                                                      check_same_thread=False)
                row = self.stamp_conn.execute(
                    "SELECT (SELECT MAX(id) FROM events), (SELECT MAX(updated_at) FROM cards), "
                    "(SELECT MAX(updated_at) FROM requests), (SELECT MAX(updated_at) FROM asks), "
                    "(SELECT COUNT(*) || ':' || IFNULL(MAX(updated_at), '') FROM holds)").fetchone()
                # A request's count going up writes no event (c-520), nor does an answer's
                # delivery (c-521), nor Bosun's voice hold (c-523: the count moves when it is
                # released, the clock when it is taken), so their own clocks are here.
                self.stamped = (f"{row[0] or 0}.{row[1] or ''}.{row[2] or ''}.{row[3] or ''}"
                                f".{row[4] or ''}")
            except sqlite3.Error:
                if self.stamp_conn is not None:
                    with contextlib.suppress(sqlite3.Error):
                        self.stamp_conn.close()
                self.stamp_conn = None
                self.stamped = self.stamped or "0."
            self.stamped_at = time.monotonic()
            return self.stamped

    def strip_cards(self) -> list[dict]:
        """The cards the live strip may read (c-599), with only what `livestrip.watched`
        asks of them, read on the stamp's own connection: the watcher runs beside every
        request, and a `Board` here would run the migrations every few seconds. Empty once
        the server has closed (`serve.DeckServer`)."""
        with self.stamp_lock:
            if self.stamp_conn is None and self.stamped_at == float("inf"):
                return []
            try:
                if self.stamp_conn is None:
                    self.stamp_conn = sqlite3.connect(self.cfg.db_path, isolation_level=None,
                                                      check_same_thread=False)
                rows = self.stamp_conn.execute(
                    "SELECT id, space, stage, blocked_reason, session_id, options FROM cards "
                    "WHERE session_id IS NOT NULL AND session_id != ''").fetchall()
            except sqlite3.Error:
                return []
        return [livestrip.card_of(*row) for row in rows]

    def rev(self) -> str:
        """THE ONE FUNCTION. Everything that names a revision calls this: the ETag on
        `/api/state`, the `state` line every publisher sends, and the event stream's own
        sweep. Two formulas is how the page came to be told the state had changed four
        times a second while nothing was happening.

        Three parts, and only equality is ever read off the whole.

        - The writes THIS process has made, which is what drops the cache below. It covers
          a write that touched something the board stamp does not, and it moves the instant
          the write lands rather than when the memo next refreshes.
        - What the board CONTAINS (`board_stamp`), so a `kb` at the desk, the drain or a
          house writing in another process is seen too. Read, never stat-ed.
        - A coarse clock, because two of the document's inputs are neither of those (the
          drain log and the usage tee), so a deck with nothing else happening still
          refreshes them. It is the ping's interval rather than the poll's: with the
          stream open it is also the only thing that says `state` on a quiet afternoon.
        """
        written, clock = self.rev_parts()
        return f"{written}.{clock}"

    def rev_parts(self) -> tuple[str, str]:
        """`rev`'s two halves: what was WRITTEN, and the coarse clock.

        They are read apart by the event stream's sweep and nowhere else, because only the
        sweep has to tell "the document changed" from "fifteen seconds passed". Answering
        the second with a `state` line is what had an open deck that nobody was touching
        refetch `/api/state` four times a minute to move some ages; it is a `tick` now
        (`keel/deckevents.py`). Everything else still reads `rev` whole, which is what
        keeps the stream's line and the route's ETag the same function.
        """
        return f"{self.writes}.{self.board_stamp()}", str(clock_step())

    def card_rev(self, card_id: str) -> str | None:
        """That card's own revision, read WITHOUT building the detail document.

        `detail` reads the plan off disk; answering a conditional request with that would be
        doing the expensive half in order to decide not to send it.

        Three cheap facts instead, and they have to be all three. The card's `updated_at`
        and its event count cover every way the BOARD moves a card. `context.md` is the
        third because the pane shows it (the PR body, where it stands) and a house writes
        that file without the card gaining an event of its own, so a card whose record had
        been rewritten and nothing else used to answer a stale 304.
        """
        board = self.board_factory()
        try:
            card = board.get(card_id)
            if not card:
                return None
            context = mtime_ns(self.cfg.card_dir(card_id) / "context.md")
            return f'{card.get("updated_at")}-{len(board.events(card_id))}-{context}'
        except Exception:  # noqa: BLE001 - an unknown id has no revision, and says so
            return None
        finally:
            board.close()

    def listing(self, fresh: bool = False) -> Callable[[], list[dict]]:
        """The harness listing's join, from the deck's kept reading (c-638). A cold deck reads
        it on a thread now and joins it, so a cold build still reads the board meanwhile
        (c-540). Otherwise it is answered at once and read again on its own thread after two
        seconds, or at once after a write (`drop`); a listing that changed tells the pages
        (`moved`). `fresh` (the live strip) is the listing as it is now, read on its own and
        never kept, so the kept reading's own refresh still sees each change and tells the
        pages. Called under `self.lock`; the join may be waited on outside it."""
        if fresh:
            return listing_ahead(self.cfg)
        if self.kept.agents.age("all") is None:
            return self.kept.agents.ahead("all", self.read_agents)
        rows = self.kept.agents.get("all", self.read_agents)
        return lambda: rows

    def read_agents(self) -> list[dict]:
        return harness.agents_across((space.config_dir for space in self.cfg.spaces.values()),
                                     strict=True)

    def state(self, scope: str | None = None, archived: bool = False, asked: str | None = None,
              steps: bool = False) -> dict:
        """The document for that scope (`in_scope`), built at most once per CACHE_SECONDS.
        `steps`: the page shows the first-run steps (`?steps=1`); the whole document, which a
        machine reader asks for with no scope, always carries them."""
        asked = asked if scope is not None else None
        steps = bool(steps) or scope is None
        key = (scope, bool(archived), asked, steps)
        with self.lock:
            held = self.cached.get(key)
            if held is None or time.monotonic() - held[0] > CACHE_SECONDS:
                built = self.build(scope, bool(archived), asked, steps)
                if len(self.cached) >= KEPT_DOCUMENTS:
                    self.cached = {}            # one per open page, so a few; never a pile
                # stamped when it is READY, as it always was: a build slower than the
                # window would otherwise be stale on arrival and built again every time
                held = (time.monotonic(), built)
                self.cached[key] = held
            return held[1]

    def drop(self) -> None:
        """A write landed: the cache goes, the revision moves, and the page is told.

        The board stamp's memo is dropped in the same breath, so the revision published
        here is the one `/api/state` will answer on the fetch this line provokes rather
        than one the memo is a second behind on.
        """
        self.moved()
        # A write may have started or ended a house: list the sessions again now (c-638).
        # When the listing did change, that refresh calls `moved` a second time, so a page
        # draws the write at once and the house a listing later (a quarter second).
        self.kept.agents.refresh("all", self.read_agents)

    def reread(self, cfg: Config) -> None:
        """Run on `cfg` from now (`keel/deckreload.py`, c-729): its documents and its kept
        readings were built from the old config (a space's pack, its verbs and links, the
        config dirs the harness is asked about), so both go, and the pages are told. The old
        readings' refreshes in flight are joined on a thread of their own, so the answer to
        the change is not held up by a `claude agents` still running."""
        old = self.kept
        with self.lock:
            self.cfg = cfg
            self.kept = readings_module.Readings(self.moved)
        threading.Thread(target=old.close, name="kept-close", daemon=True).start()
        self.moved()

    def heard(self, hello: bool) -> bool:
        """Meet Bosun's hello watch answered (`GET /api/hello`, r1.F6, r1.F7): the documents go,
        and the pages are told, only when the answer changed, so a page asking every few
        seconds moves nothing until the hello arrives."""
        with self.lock:
            changed, self.hello = hello != self.hello, hello
        if changed:
            self.moved()
        return hello

    def moved(self) -> None:
        """The documents go, the revision moves, and the pages are told: `drop`'s first
        half, and what a kept reading that changed calls (c-638). Nothing once the server
        has closed (`serve.DeckServer`), which keeps its stamp connection shut."""
        with self.stamp_lock:
            if self.stamped_at == float("inf"):
                return
        with self.lock:
            self.cached = {}
            self.writes += 1
        with self.stamp_lock:
            if self.stamped_at == float("inf"):     # pinned while the cache was dropped
                return
            self.stamped_at = 0.0
        deckevents.HUB.state(self.rev())

    def detail(self, card_id: str, files: list | None = None) -> dict:
        board = self.board_factory()
        try:
            return detail(self.cfg, board, card_id, files)
        finally:
            board.close()

    def card_files_of(self, card_id: str) -> list | None:
        """The card's files, listed from its own row (c-719), or None for an unknown id."""
        board = self.board_factory()
        try:
            return cardfiles.listed(self.cfg, board.get(card_id))
        except Exception:  # noqa: BLE001 - an unknown id is answered by the detail's 404
            return None
        finally:
            board.close()
