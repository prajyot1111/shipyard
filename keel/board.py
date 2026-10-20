"""The board: one SQLite file, four tables, every write in a transaction.

`cards` is the fold and `events` is the append-only record; `requests` holds Bosun's
requests (`keel/requests.py`) and `asks` its questions for him (`keel/asks.py`), whose moves
are events too. Everything else (gates,
needs-you, a parent's stage, whether a card can start) is derived on read and attached to
each returned card under `derived` (see `views.py`). Refusals raise `Refused`, whose
message is the one-line reason the CLI prints.
"""

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from keel import (authority, bases, cardspec, planstate, repair, shipauto, shipreplies, shipupgrade, stacking, terms,
                  views)
from keel.models import model_problem

# `shipping` (lane SHIP): a work card whose pull request is ready. Approve outcome moves it
# there when its publish says so, and it reaches `done` when the pull request merges.
STAGES = ("inbox", "assigned", "planning", "building", "review", "shipping", "done")
# Where a card waits before work starts: an attended card may go back to one from planning.
QUEUED = ("inbox", "assigned")
AUTONOMY = ("attended", "autonomous")
EVENT_KINDS = ("create", "set", "stage", "note", "hook", "session", "resume",
               "block", "unblock", "split", "approve", "claim", "relay", "carried", "correct",
               "mark", "reply", "request", "ask", "intervene", "wake",
               # c-734: what the drain's next wake tells Bosun of a card (`keel/pausewake.py`)
               "tell",
               # c-600: the house's verdict on a review comment, and his Ship
               "verdict", "ship",
               # history: his grant over a driven card's gates, retired in c-593
               "grant")
CARD_FIELDS = ("id", "space", "title", "brief", "autonomy", "repo", "model", "stage",
               "blocked_reason", "session_id", "plan_ref", "output_ref", "parent", "after",
               "from", "topic", "options", "created_at", "updated_at", "rank")
SETTABLE = ("title", "brief", "autonomy", "repo", "model", "blocked_reason", "session_id",
            "plan_ref", "output_ref", "parent", "after", "from", "topic", "options")
# The fields that name another card. An empty value clears one rather than storing "": that
# is what `kb set <id> parent=` types, and storing it is what left c-294 parented to nothing.
LINK_FIELDS = ("parent", "after", "from")
# The stages a card reaches only because work started on it. `create --parent` refuses one
# of these as a parent: making it a tracking card takes its own gate away.
WORKED_STAGES = ("planning", "building", "review", "shipping", "done")
# Columns added after the first schema, each with the ALTER that adds it: `open` applies
# the ones the file lacks, so an older board.db migrates on open and a new one is complete.
MIGRATIONS = (("topic", "ALTER TABLE cards ADD COLUMN topic TEXT"),
              ("from", 'ALTER TABLE cards ADD COLUMN "from" TEXT'),
              # A card's place in the drain's queue among its peers, lowest first; null is the
              # order it was filed in. Written only by `kb next` (`keel/tree.py`).
              ("rank", "ALTER TABLE cards ADD COLUMN rank REAL"))
STOP_BLOCK_BUDGET = 2
# An ask card's one output file (`keel/fetch.py` puts it on the card), and the note the
# Stop hook leaves when it files that card on the house's behalf.
DROP_OPTION = "drop"
# `options.claim`: which drain host took a startable card (`Board.claim`), so a drain on
# another machine polling the same board never starts it too.
CLAIM_OPTION = views.CLAIM_OPTION
# `options.voice_hold`: voice is talking to this card's house (`keel converse`). One key on
# the card, because Keel has one store, and every choke point that could move a house reads
# it: `drain.reconcile`, `drain.retire_tracking`, `drain.resume_quiet`, `house.resume`, and
# both bodies of the Stop hook below.
VOICE_HOLD_OPTION = views.VOICE_HOLD_OPTION
# WHO MAY WRITE THAT KEY, and it is the point of the key existing. A held card is skipped by
# `reconcile`, by `retire_tracking`, by `resume_quiet` and by the Stop hook's nudge, so a
# house that could set it on its own card would be granting itself immunity from the drain
# and from the nudge in one line, and `kb` is on every house's PATH. Only the connected turn
# takes or releases a hold: `voice` is the actor `keel converse` writes under, `drain` is
# `release_holds`, and `human` is his own tap. A house's actor is `house`, and `cli.resolve_actor`
# is the other half of this: a process carrying KEEL_CARD cannot claim another actor.
HOLD_ACTORS = ("voice", "drain", "human")
# `options.dropin_hold` (U3): the same immunity, so the same guard. His Drop in takes it
# (the deck's `kb`, as him) and the drain marks and releases it; a house never may.
DROPIN_HOLD_OPTION = views.DROPIN_HOLD_OPTION
DROPIN_HOLD_ACTORS = ("drain", "human")
# WHO MAY SET A FIELD AS A GUESS after create (`kb set --assumed`): the capture refine only.
ASSUMING_ACTORS = ("voice",)
# `options.landing` is the landing worker's record (`keel/landing.py`), which `kb land` reads:
# nobody else writes it (lane E review round 3, finding 4).
LANDING_OPTION = "landing"
PRETEST_OPTION = "pretest"      # the drain's pre-run of the merged tree (`keel/landing.py`)
LANDING_ACTORS = ("drain",)
PUSH_OPTION = "push"        # the push after a local landing, as its worker left it (`keel/landpush.py`)
# `options.rotate` is the rotation's own record (`keel/rotate.py`), the drain's alone too.
ROTATE_OPTION = "rotate"
# r2.D1: `options.cut_from` ({repo key: the usual branch the card was cut from}) is the cut's
# record (`adapters.cut_point`), and the landing prefers it (`merging.cut_from`): the drain's
# alone and never brought in at create, so no house or Bosun can aim its own landing. A re-cut
# by the drain overwrites that repo's entry (r2.D3), and the reader takes only a branch name.
CUT_FROM_OPTION = "cut_from"
# A relay kind that needs a `[keel]` switch on before it may be written at all.
SWITCHED_RELAYS = {"land": "merge_queue", "rotate": "rotate"}
# A `relay` is the human's tap on a deck that is not the house's machine (`Board.relay`):
# what that machine's drain is to do for the house, carried by it once (`Board.carry`).
# `finished` ends a house whose outcome was just approved, and only if the harness does not
# list it as working (lane L): unlike `stop`, it is never an interrupt.
RELAY_WHATS = ("resume", "stop", "start", "land", "rotate", "finished", "close-idle")
# What a block or a note by the drain or the review gate says it is: a resume that failed,
# the review limit reached, a house auto mode paused (which wakes Bosun, `keel/pausewake.py`).
MARKS = {"failed-resume": {"failed": "resume"}, "review-limit": {"limit": "review"},
         "permission-pause": {"paused": "permission"},
         # A block that is Keel's own mechanics (a house that failed to start, a round that
         # could not start, a landing that merged but did not move): the one kind Bosun may
         # repair on any card (c-575, `repair.refuse_unless_mechanics`). Only the drain and
         # the hook write it (`repair.refuse_mechanics_mark`).
         "mechanics": {"mechanics": True},
         # The drain's block of a shipping card whose re-offered batch's turn ended with items
         # unjudged (`keel/shipidle.py`, c-654), and the one block the watcher still looks
         # past for a merge or a decline (`shipreoffer.awaits_him`). HIS, not mechanics: the
         # block is how the card needs him, so Bosun's repairs are refused on it
         # (`repair.refuse_unless_mechanics`), as on the two below.
         "unjudged": {"unjudged": True},
         # The two blocks of a fresh start Keel would not make (`keel/afresh.py`, c-654),
         # each with the session it is about in its data (`session`): the harness says the
         # conversation is gone and the card shows a turn inside the retention
         # (`afresh-withheld`), or a house started afresh is gone too before it ran a turn
         # (`afresh-twice`). HIS unblock of either is his answer, and the next resume starts
         # the house afresh, once (`afresh.answered`).
         "afresh-withheld": {"withheld": "afresh"},
         "afresh-twice": {"withheld": "twice"},
         # A landing's own refusal (`keel/landing.py`, `REFUSED_MARK`): the house staging
         # review again clears it in the same write (`_clear_stale_block`), since a new
         # outcome is a new approve; c-575 sat blocked at its gate after one (r-26).
         "landing-refused": {"landing": "refused"},
         # The Stop hook's own block at building (`stop_check`): the house stopped twice
         # without moving on. It is ABOUT building, so any move off building clears it in
         # the same write (`_clear_stale_block`, c-601): it rode a house's own `kb stage
         # review` into Approve and shipping, where the deck called a shipping card
         # "stopped at building".
         "stop-check": {"stopped": "building"},
         # His Stop tap (the deck's `house.stop`, here or carried by the drain that holds the
         # house): the session is down because he put it down, so the drain's resume of an
         # exited house passes it over until his Resume or Retry (`house.stopped_by_him`,
         # c-605). Only he, or the drain carrying his tap, writes it.
         "human-stop": {"stop": "human"},
         # His "Close idle house" tap (the deck's `house.close_idle`, c-607): a human stop
         # too, of a house the harness listed idle, but NOT one that waits for his Resume:
         # its next review batch, a gate tap of his, or his Resume brings it back with its
         # conversation (`views.stop_kind`). The drain passes it over like his Stop, and
         # never writes one of its own accord: it only carries his tap.
         "closed-idle": {"stop": "idle"},
         # a-72 (c-607): the drain ended the idle house of a card its merge made done
         # (`keel/shipidle.py`); final, since a done card is never resumed. The drain's alone.
         "merged-end": {"stop": "merged"}}
HUMAN_STOP_ACTORS = ("human", "drain")
HUMAN_STOP_MARKS = ("human-stop", "closed-idle")
STOP_CHECK_TEXT = "stopped at building after "
UNJUDGED_MOOT = ("the card is done, so the block for the review items its house left unjudged "
                 "is lifted: they are moot now")
# `options.publishing` was the one-shot marker of his Approve outcome while it was published
# on another machine (until c-622): the SHA-256 of a random nonce, which that machine checked
# the call's nonce against before it ran the adapter. The nonce itself is never stored. Only `mark_publishing` and
# `clear_publishing` write the marker, and any stage move drops it (`_move`). It marks the user's
# Ship (c-600) and, again, the Approve outcome through a pack (c-738 r1.F3): the pack's `publish` is
# handed the nonce and runs only when its digest is this marker's.
PUBLISHING_OPTION = "publishing"
# `options.shipping` is the pull request watcher's record (`keel/shipwatch.py`, lane SHIP):
# the ids it has seen, the batch waiting, what the house was told, what his Ship posted, its
# timers and the facts the deck's chip says. Only the drain and he write it: a house that
# could would be forging what the reviewers said, or its own answer to them.
SHIPPING_OPTION = "shipping"
SHIPPING_ACTORS = ("drain", "human")
# `options.reoffer` is the ask of `kb ship <id> reoffer` (c-651, `keel/shipreoffer.py`): his
# alone, written only by `Board.reoffer` (and its failed looks counted by `keep_reoffer`). It
# is cleared by the drain that answers it, by any move off shipping (`_move`), by the sync's
# fresh record (`ship_from_sync`), and by a block or an archive (`_drop_reoffer`). It names
# no item, so it forges nothing: the drain's own look decides what is offered.
REOFFER_OPTION = "reoffer"
REOFFER_DROPPED = ("re-offer cleared: the card was {why}, and the drain does not tend it while "
                   "it is, so the ask would wait unseen; ask again once it is not")
# `options.sendback` is his send-backs at shipping that the drain has not put in the batch
# yet (c-663, `keel/shipsendback.py`): a list, each with its handle and his words. His alone
# and never part of `options.shipping`, so the drain's write of its record cannot drop one:
# only `Board.send_back` adds to it and `Board.take_sendback` takes from it, by handle
# (`set_fields` refuses every actor). A move off shipping drops it (`_move`): nothing
# answers it there, and a note names what was dropped untold (`SENDBACK_DROPPED`). A block or an archive KEEPS it, unlike a re-offer: these are his words,
# and they are told once the drain tends the card again.
SENDBACK_OPTION = "sendback"
SENDBACK_DROPPED = ("the user's send-back dropped untold ({handles}): the card moved to {stage}, where "
                    "nothing tells it to the house; the user's words are in the note that asked")
# Where a card at shipping may go, and who moves it (c-600): only to done, when its pull
# request merged (the drain) or he says so. The house answers review AT shipping, so nothing
# sends the card back to building or to his gate.
SHIPPING_NEXT = ("done",)
# The records only Keel's own paths write: no create, split or row insert may bring one in,
# by any actor (lane L round 3). `set_fields` guards each of them by its own rule.
RESERVED_OPTIONS = (PUBLISHING_OPTION, LANDING_OPTION, ROTATE_OPTION, DROPIN_HOLD_OPTION,
                    SHIPPING_OPTION, REOFFER_OPTION, SENDBACK_OPTION, CUT_FROM_OPTION)
# Options only he changes after create: `kind` decides the deny entries a work adapter adds
# for the card (a research card cannot push), so any other actor changing it lifts them.
# c-640: `flow_move` is the push grant his tap writes (a flow move's `pushes`, which a pack's
# fence reads) and `flow_proposal` names the space a proposal card would adopt into; a house
# that could set either on its own card would grant itself a push or aim an Adopt.
FLOW_MOVE_OPTION = "flow_move"
# c-667: the options that make a card a PROPOSAL, spelled here once for the board (the
# writers' own names, `flowcards.OPTION` and `tiercards.OPTION`, are held equal to these by
# `tests/test_onboarding.py`). The outcome of such a card is its draft adopted
# (`onboarding.adopt_proposal`), so the option is his for a tier too: a house that set it on
# its own card would turn his tap into a write of the rules every session reads.
FLOW_PROPOSAL_OPTION, TIER_PROPOSAL_OPTION = "flow_proposal", "tier_proposal"
PROPOSAL_OPTIONS = (FLOW_PROPOSAL_OPTION, TIER_PROPOSAL_OPTION)
FLOW_OPTIONS = (FLOW_MOVE_OPTION, FLOW_PROPOSAL_OPTION)
# A proposal closes one way, and it is the way that writes its draft.
PROPOSAL_CLOSES = "{card} is a proposal: it closes by Adopt, which writes its draft; archive it to drop it"
# c-655: a card's own two switches for automatic handling at shipping (`keel/shipauto.py`)
# are his as well, at create too: a house that set one would be deciding what wakes it.
SHIP_AUTO_OPTIONS = tuple(shipauto.KEYS.values())
# c-718: whether a waiting card is stacked on the card it waits for, or independent of it
# (`keel/stacking.py`), is the owner's too, at create too: a house that set it would choose its own
# base and when it starts.
HIS_AT_CREATE = (FLOW_MOVE_OPTION,) + PROPOSAL_OPTIONS + SHIP_AUTO_OPTIONS + (stacking.OPTION,
                                                                           stacking.SPLIT_OPTION)
# c-718 r1.F2: the branch a card is taken against is changed after create only by the owner's
# actors (`WORKER_SETTERS`: the token, voice, the talker). A house that could would aim its own
# change, and a house shell that drops KEEL_CARD is `cli`, so naming the house is not enough.
OWNERS_OPTIONS = ("base",)
# c-718 r1.F1: a card's branch is written once (its worktree verb names it at the first cut,
# the shipping sync when it finds one) and changed after that only by the owner: a stacked
# card's base is its parent's branch, so a house that renamed another card's branch would aim
# its own.
ONCE_OPTIONS = ("branch",)
HUMAN_ONLY_OPTIONS = ("kind", views.WORKER_OPTION) + HIS_AT_CREATE    # and these at create too
# A card's worker moves only before anything has started on it (c-645): a house mid-build or
# Bosun mid-plan is not handed over silently.
WORKER_STAGES = ("inbox", "assigned")
# Who may name a worker when a card is made or split (c-645): the actors that are his, by his
# token, by voice or through the talker, the same three `bosuncards.HIS_ACTORS` reads as his.
# Bosun, a house, the drain, and a shell that runs `kb` as itself (`cli`) are refused. `kb`
# takes `--actor voice` or `talker` on its word, as it does for every verb (`cli.resolve_actor`).
WORKER_SETTERS = ("human", "voice", "talker")
# A review card (lane RC): the fields `Board.rereview` reads and writes.
REVIEW_KEY_OPTION = "review_key"
REVIEW_POSTED_OPTION = "review_posted"
REVIEW_NEW_OPTION = "review_new"
REVIEW_ROUND_OPTION = "review_round"
CARRY_OUTCOMES = ("taken", "superseded")
# Who may make a tracking card's own moves (`_refuse_tracking_move`): the drain takes it back
# when a slice leaves done; he sends it back, or brings it to review (Back to your gate).
TRACKING_MOVERS = ("drain", "human")
# Who closes a tracking card to done when every slice is (c-649): the drain alone, through
# `Board.close_tracking`, which no `kb` verb reaches. His Approve outcome closes one waiting
# at review through the same `_close_tracking`.
TRACKING_CLOSER = "drain"
FILED_NOTE = "the drop was written, so the turn-end hook filed this card at review"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY,
  space TEXT NOT NULL,
  title TEXT NOT NULL,
  brief TEXT NOT NULL DEFAULT '',
  autonomy TEXT NOT NULL DEFAULT 'autonomous',
  repo TEXT,
  model TEXT,
  stage TEXT NOT NULL DEFAULT 'inbox',
  blocked_reason TEXT,
  session_id TEXT,
  plan_ref TEXT,
  output_ref TEXT,
  parent TEXT,
  after TEXT,
  "from" TEXT,
  topic TEXT,
  options TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  rank REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  card TEXT NOT NULL,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  actor TEXT NOT NULL,
  text TEXT,
  data TEXT
);
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY,
  n INTEGER NOT NULL UNIQUE,
  actor TEXT NOT NULL,
  card TEXT,
  what TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  key TEXT,
  seen INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  state TEXT NOT NULL,
  taken_by TEXT,
  how TEXT,
  gap TEXT,
  note TEXT,
  filed_as TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS holds (
  name TEXT PRIMARY KEY,
  hold TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asks (
  id TEXT PRIMARY KEY,
  n INTEGER NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  actor TEXT NOT NULL,
  card TEXT,
  question TEXT NOT NULL,
  why TEXT NOT NULL,
  options TEXT NOT NULL,
  state TEXT NOT NULL,
  answer TEXT,
  words TEXT,
  message TEXT,
  channel TEXT,
  answered_by TEXT,
  answered_at TEXT,
  filed_as TEXT,
  claimed_at TEXT,
  claimed_by TEXT,
  delivered_at TEXT,
  delivered_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

# The indexes, apart from the tables because they run AFTER `migrate`: an index on a column
# a migration is about to add cannot be created on the older file that still lacks it.
INDEXES = """
CREATE INDEX IF NOT EXISTS events_card ON events(card, id);
CREATE INDEX IF NOT EXISTS cards_parent ON cards(parent);
CREATE INDEX IF NOT EXISTS cards_from ON cards("from");
CREATE INDEX IF NOT EXISTS requests_key ON requests(key, state);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind, id);
CREATE INDEX IF NOT EXISTS events_tier ON events(json_extract(data, '$.tier')) WHERE kind = 'note';
CREATE INDEX IF NOT EXISTS events_reap_later ON events(json_extract(data, '$.reap_later')) WHERE kind = 'note';
CREATE INDEX IF NOT EXISTS requests_card ON requests(card, state);
CREATE INDEX IF NOT EXISTS asks_card ON asks(card, state);
"""


def quoted(names) -> list[str]:
    """Column names as SQL identifiers. `from` is a keyword, so every generated statement
    quotes every column rather than knowing which one needs it."""
    return [f'"{name}"' for name in names]


class Refused(Exception):
    """A write the board will not make; the message is the reason."""


class NotFound(Refused):
    """No card with that id."""


def checked_count(name: str, value: int | None) -> int:
    """A row count from the caller: None and 0 mean no cap, a negative is refused."""
    if value is None:
        return 0
    if value < 0:
        raise Refused(f"{name} must be 0 or more, got {value}")
    return value


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def card_number(card_id: str) -> int | None:
    prefix, _, digits = card_id.partition("-")
    return int(digits) if prefix == "c" and digits.isdigit() else None



def unchanged(row: sqlite3.Row, update: dict) -> bool:
    """Every field in the update already holds that value (options compared as JSON, so
    key order does not count). A set that changes nothing records nothing: the backup's
    hourly job re-stating an open notice put a `set` event on the card every hour."""
    for name, value in update.items():
        if name == "options":
            if json.loads(row["options"] or "{}") != json.loads(value):
                return False
        elif row[name] != value:
            return False
    return True


def nonce_digest(nonce: str) -> str:
    """What the board keeps of a publish nonce: its SHA-256, never the nonce."""
    return hashlib.sha256(str(nonce).encode("utf-8", "surrogateescape")).hexdigest()


def refuse_reserved(options) -> None:
    """Refuse a new card row that carries a record only Keel's own paths write."""
    found = json.loads(options or "{}") if isinstance(options, str) else (options or {})
    reserved = sorted(set(RESERVED_OPTIONS) & set(found))
    if reserved:
        raise Refused(f"options.{reserved[0]} is Keel's own record; no card is filed with one")


def ships(published) -> bool:
    """Does a publish's answer say the card's pull request is ready and watched (lane SHIP)?

    The answer is what the space's publish printed: the work adapter's JSON text, or a dict
    from a caller that already decoded it. Only an explicit `"shipping": true` counts, so a
    personal merge, a research or tracking card's note and an unreadable answer all go to
    done exactly as before."""
    if isinstance(published, str):
        try:
            published = json.loads(published)
        except ValueError:
            return False
    return isinstance(published, dict) and published.get("shipping") is True


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def heads_of(published) -> dict:
    """`{repo: sha}` a publish or a Ship says the pull request's branch is at (c-600 review):
    what his next Ship leases its push against. Only full shas count."""
    if isinstance(published, str):
        try:
            published = json.loads(published)
        except ValueError:
            return {}
    if not isinstance(published, dict):
        return {}
    heads = {}
    for key in ("heads", "pushed"):
        found = published.get(key)
        if isinstance(found, dict):
            heads.update({str(repo): str(sha) for repo, sha in found.items() if FULL_SHA.match(str(sha))})
    return heads


def merge_options(stored: dict, incoming: dict) -> dict:
    """The card's options with `incoming` folded in; a null value REMOVES its key.

    `set options.k=null` is the deck's and the CLI's way of handing a key back to its
    default, so it must leave the same JSON `kb backlog <id> auto` leaves: the key gone,
    not present and null. `views.backlog_override` reads a null as auto either way, but
    two shapes for one state is how the next reader gets it wrong.
    """
    merged = dict(stored)
    for key, value in incoming.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def drop_problem(drop: str) -> str | None:
    """Why the drop cannot be filed yet, or None when it can.

    The engine checks exactly what every segment's fetcher checks before it reads a drop:
    the file is there, it is not empty, and it parses as JSON. Whether the entries inside
    are well formed is the segment's own business and its fold validates them again, so
    checking more here would be Keel learning one segment's shape.
    """
    path = Path(drop)
    try:
        raw = path.read_text()
    except OSError:
        return "it is not written yet"
    if not raw.strip():
        return "the file is empty"
    try:
        json.loads(raw)
    except ValueError as why:
        return f"it is not valid JSON ({why})"
    return None


def running_background_tasks(payload: dict | None) -> list:
    """The Stop payload's background tasks (subagents, shells) that are still running."""
    tasks = (payload or {}).get("background_tasks") or []
    return [t for t in tasks if isinstance(t, dict) and t.get("status") == "running"]

# Left beside a board file that was moved away (the 2026-09 cutover left one in the old
# checkout's state). Opening a board there would create an empty one and every write into it
# would be lost without a sound, so a board beside this marker refuses to open, and says
# where it went.
MOVED_MARKER = "board.moved"


def refuse_moved(path: Path) -> None:
    marker = path.parent / MOVED_MARKER
    if marker.exists():
        try:
            where = marker.read_text().strip()
        except OSError:
            where = ""
        raise Refused(f"the board is not here any more: it moved{' to ' + where if where else ''} "
                      f"({marker})")


def laid_over(now, before, new: dict) -> dict:
    """`now` with only the entries a step changed between `before` and `new`: one it set
    takes `new`'s value, one it removed is removed, every other entry keeps `now`'s."""
    now, before = (dict(side) if isinstance(side, dict) else {} for side in (now, before))
    for key in set(before) | set(new):
        if key in new and before.get(key, before) != new[key]:
            now[key] = new[key]
        elif key not in new and key in before:
            now.pop(key, None)
    return now


def proposals_of(options) -> list[str]:
    """The proposal options a card carries (a dict, or the row's JSON text), in
    `PROPOSAL_OPTIONS` order: one for a tier or a flow proposal, none for any other card.
    The one reading of "is this a proposal" (c-667): an option that is set to nothing is not."""
    if isinstance(options, str):
        options = json.loads(options or "{}")
    return [name for name in PROPOSAL_OPTIONS if (options or {}).get(name)]


class Board:
    def __init__(self, path: str | Path, backlog_days: int = views.DEFAULT_BACKLOG_DAYS,
                 defaults: cardspec.Defaults | None = None, switches=(), integrated=(),
                 builds=(), terms=None, ship_idle_hours: int | None = None,
                 drain_paused: bool = False,
                 cards_dir: str | Path | None = None, ship_auto=None, run_rule=None, stacks=()):
        self.path = Path(path)
        # The spaces whose pack stacks a waiting card on the card it waits for (c-718,
        # `Config.stacking`): `options.stack` is refused anywhere else.
        self.stacks = frozenset(stacks)
        # `(space, repo key) -> bool | None` (c-678, `repocommands.runs`): whether the repo's
        # adopted CLAUDE.md says how to run its app; None for a repo with no such file. A
        # card on a repo that answers False may not carry `options.browser`. Without it
        # (tests, tools) nothing is refused.
        self.run_rule = run_rule
        # `state/cards` (`Config.cards_dir`), beside the database unless the config says:
        # where a tracking card's close writes its rollup (c-649, `_close_tracking`).
        self.cards_dir = Path(cards_dir) if cards_dir else self.path.parent / "cards"
        # What each space calls a change (c-630): a space's name to its `terms.Terms`, which
        # `open_board` hands in from the config. Without it (tests, tools) a refusal says
        # the core's defaults.
        self.terms = terms
        # `[keel] ship_idle_hours` (c-633): what `views.ship_idle` says the drain closes at.
        self.ship_idle_hours = ship_idle_hours
        # `[keel] drain_paused`, for what the deck says of a send-back that waits (c-663,
        # `views.ship_sendback`): the drain itself reads its own config.
        self.drain_paused = drain_paused
        # A space's name to its two automatic-handling switches (c-655, `shipauto.of_space`),
        # which `views.ship_auto` lays a card's own options over. Without it both are off.
        self.ship_auto = ship_auto
        # `(space, repo)` pairs whose outcomes land on an integration branch (c-526,
        # `Config.integrated`): an `after` on such a card is met only once it has landed.
        self.integrated = frozenset(integrated)
        # The `[keel]` switches that let a relay kind be written at all (`Config.switches`):
        # `merge_queue` for `land`, `rotate` for `rotate`. A board opened without them writes
        # neither, whoever asks (lane E round 4, finding 3).
        self.switches = frozenset(switches)
        # Builder mode (`[keel] bosun_builder`, `keel/authority.py`): Bosun acts on personal
        # cards as on its own board. Read where the board lives, like every authority rule.
        self.builder = authority.BUILDER in self.switches
        # Which builder (c-619, `keel/builder.py`): the superuser approves its own outcomes and
        # files any personal card; the in-app builder does neither. `builds` is the repo keys
        # Bosun builds (`builder.repos`): a personal card on any other repo is a house's.
        self.superuser = authority.SUPERUSER in self.switches
        # An install's builder in bypass: it passes its own cards' plan and outcome gates.
        self.bypass = authority.BYPASS in self.switches
        self.builds = frozenset(builds)
        # How long a card may sit at its outcome gate before it backlogs (`views.backlog`).
        # the config's `backlog_days`; the callers that hold a Config pass it in.
        self.backlog_days = backlog_days
        # The card defaults every create is resolved against (`keel/cardspec.py`): each
        # space's model, confirm list and option sheet. Without a Config it is Keel's own
        # layer alone, which still leaves no card without a model.
        self.defaults = defaults or cardspec.Defaults()
        refuse_moved(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.migrate()
        self.conn.executescript(INDEXES)

    def columns(self) -> list[str]:
        return [row["name"] for row in self.conn.execute("PRAGMA table_info(cards)")]

    def migrate(self) -> list[str]:
        """Add every column in MIGRATIONS the file lacks; returns the names added."""
        present = set(self.columns())
        added = []
        for name, statement in MIGRATIONS:
            if name not in present:
                self.conn.execute(statement)
                added.append(name)
        return added

    def close(self) -> None:
        self.conn.close()

    # `with Board(path) as board:` closes it on the way out, however the block ends. A
    # board left to the collector is closed whenever it runs, with a ResourceWarning in
    # whichever code is running then (tests/boardleak.py).
    def __enter__(self) -> "Board":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def now(self) -> str:
        """The board's clock: every stamp it writes, and the instant the backlog rule
        measures against. One method so a test can hand the board a fake clock."""
        return now()

    @contextmanager
    def tx(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ----- reads -----

    def _row(self, card_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise NotFound(f"no card {card_id}")
        return row

    def _stage_of(self, card_id: str) -> str:
        return self._row(card_id)["stage"]

    def exists(self, card_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone() is not None

    def get(self, card_id: str) -> dict:
        return views.attach(self, self._row(card_id))

    def list_cards(self, space: str | None = None, stage: str | None = None,
                   needs_you: bool = False, include_archived: bool = True,
                   limit: int | None = None, topic: str | None = None,
                   backlog: bool | None = None) -> list[dict]:
        """Cards oldest first after every filter; `limit` keeps the first N (None or 0: all)."""
        count = checked_count("card limit", limit)
        clauses, params = [], []
        if space:
            clauses.append("space = ?")
            params.append(space)
        if topic:
            clauses.append("topic = ?")
            params.append(topic)
        if stage:
            if stage not in STAGES:
                raise Refused(f"unknown stage {stage}; one of {', '.join(STAGES)}")
            clauses.append("stage = ?")
            params.append(stage)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM cards {where} ORDER BY created_at, id", params)
        cards = [views.attach(self, row) for row in rows]
        if needs_you:
            cards = [card for card in cards if card["derived"]["needs_you"]]
        if not include_archived:
            cards = [card for card in cards if not card["derived"]["archived"]]
        if backlog is not None:
            cards = [card for card in cards if card["derived"]["backlog"] is backlog]
        return cards[:count] if count else cards

    def filed_by(self, actor: str, limit: int = 20) -> list[dict]:
        """The newest cards whose `create` event is `actor`'s, newest first: the first-run
        stepper's First card (c-632) reads the human's without listing the whole board."""
        count = checked_count("card limit", limit)
        rows = self.conn.execute(
            "SELECT cards.* FROM cards JOIN events ON events.card = cards.id AND events.kind = 'create' "
            "WHERE events.actor = ? ORDER BY cards.created_at DESC, cards.id DESC LIMIT ?", (actor, count or -1))
        return [views.attach(self, row) for row in rows.fetchall()]

    def needs_you(self, space: str | None = None, backlog: bool = False) -> list[dict]:
        """Cards at a gate or blocked. A backlog card is not one of them unless asked for."""
        cards = self.list_cards(space=space, include_archived=False)
        return [card for card in cards
                if card["derived"]["needs_you"] or (backlog and card["derived"]["backlog"])]

    def review_since(self, row: sqlite3.Row) -> str | None:
        """When this card reached its outcome gate: the newest `stage` event that moved it
        to review, else its `created_at`.

        Only an imported card falls back, since every stage move Keel makes is an event.
        `created_at` and not `updated_at`: the fold gave every imported card the timestamp
        of the ledger's last write for it, and a bulk ledger pass on 2026-09-15 stamped all
        ten of the cards that have sat at review since July and August with the same minute.
        """
        found = self._review_event(row)
        return found["at"] if found else row["created_at"]

    def _review_event(self, row: sqlite3.Row) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT id, at FROM events WHERE card = ? AND kind = 'stage' "
            "AND json_extract(data, '$.to') = 'review' ORDER BY id DESC LIMIT 1",
            (row["id"],)).fetchone()

    def _acted_since(self, card_id: str, event: int) -> str | None:
        """When he last acted on this card himself after event `event` (`views.his_action`),
        or None. Newest first over the card's own index, so it stops at the first hit."""
        # The cursor is walked, never fetched whole: `events(card, id)` gives this order with
        # no sort, so SQLite steps back from the card's newest event and each row is decoded
        # only when reached. What it decodes is bounded by the events of his that do not
        # count and are newer than the one that does (a few backlog switches or passes);
        # what the index steps over is the card's events since it reached review.
        marks = ", ".join("?" for _ in views.HIS_ACTORS)
        rows = self.conn.execute(
            f"SELECT kind, data, at FROM events WHERE card = ? AND id > ? AND actor IN ({marks}) "
            "ORDER BY id DESC", (card_id, event, *views.HIS_ACTORS))
        for kind, data, at in rows:
            if views.his_action(kind, json.loads(data) if data else None):
                return at
        return None

    def backlog_clock(self, row: sqlite3.Row) -> str | None:
        """The instant the backlog rule counts from (c-673): the newest of the card reaching
        its outcome gate (`review_since`) and his newest own action on it since. A tap of
        his on a card that has waited a week is him looking at it, so the week starts again;
        a house's note or the drain's bookkeeping never is, however recent.

        Two indexed reads of the card's events, and nothing stored: `views.derived` asks once
        per card and hands the answer to both the rule and the stamp the deck shows."""
        found = self._review_event(row)
        reached = found["at"] if found else row["created_at"]
        acted = self._acted_since(row["id"], found["id"] if found else 0)
        return views.later(reached, acted)

    # The events that OPEN each kind of wait (`opened_since`). A plan gate opens with the
    # last of its three conditions: the stage to planning, the plan_ref (given by `stage
    # --plan` or by `set`), or the card made attended.
    OPENED_BY = {
        "blocked": "(kind = 'block' OR (kind = 'set' "
                   "AND json_extract(data, '$.blocked_reason') IS NOT NULL))",
        "plan": "((kind = 'stage' AND json_extract(data, '$.to') = 'planning') "
                # a repair's path normalising re-opens nothing (c-575, review 3.F6)
                "OR (json_extract(data, '$.plan_ref') IS NOT NULL "
                "AND json_extract(data, '$.repair') IS NULL) "
                "OR (kind = 'set' AND json_extract(data, '$.autonomy') = 'attended'))",
    }

    def opened_since(self, row: sqlite3.Row, kind: str) -> str:
        """When the wait of `kind` (blocked, plan, outcome, notice) on this card opened: the
        newest event that opened it. An outcome gate is `review_since`; a notice waits from
        its filing. A card with no such event (an import) falls back to `updated_at`."""
        if kind == "outcome":
            return self.review_since(row)
        if kind == "notice":
            return row["created_at"]
        found = self.conn.execute(
            f"SELECT at FROM events WHERE card = ? AND {self.OPENED_BY[kind]} "
            "ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
        return found["at"] if found else row["updated_at"]

    def children(self, card_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM cards WHERE parent = ? ORDER BY created_at, id", (card_id,)).fetchall()

    def tracked_children(self, card_id: str) -> list[sqlite3.Row]:
        """The children that make this card a tracking card (`views.tracked`): its live
        ones, and none at all when the card itself is archived (c-427)."""
        return views.tracked(self._row(card_id), self.children(card_id))

    def follow_ups(self, card_id: str) -> list[str]:
        """The cards that came OUT of this one (`from`), oldest first.

        The other half of `children`, and deliberately nothing like it: a follow-up is a
        record of where a card came from and never touches this card's stage or its gate.
        """
        rows = self.conn.execute(
            'SELECT id FROM cards WHERE "from" = ? ORDER BY created_at, id', (card_id,))
        return [row["id"] for row in rows]

    def events(self, card_id: str, last: int | None = None) -> list[dict]:
        """A card's events oldest first; `last` keeps only the newest N (None or 0: all)."""
        count = checked_count("event count", last)
        if not count:
            rows = self.conn.execute("SELECT * FROM events WHERE card = ? ORDER BY id", (card_id,))
            return [views.event_dict(row) for row in rows]
        rows = self.conn.execute(
            "SELECT * FROM events WHERE card = ? ORDER BY id DESC LIMIT ?", (card_id, count))
        return [views.event_dict(row) for row in reversed(rows.fetchall())]

    def next_id(self) -> str:
        highest = 0
        for (card_id,) in self.conn.execute("SELECT id FROM cards"):
            number = card_number(card_id)
            if number is not None and number > highest:
                highest = number
        return f"c-{highest + 1:03d}"

    # ----- writes -----

    def record_event(self, card_id: str, kind: str, actor: str, text: str | None = None,
                     data: dict | None = None, at: str | None = None) -> int:
        if kind not in EVENT_KINDS:
            raise Refused(f"unknown event kind {kind}")
        cursor = self.conn.execute(
            "INSERT INTO events (card, at, kind, actor, text, data) VALUES (?, ?, ?, ?, ?, ?)",
            (card_id, at or self.now(), kind, actor, text, json.dumps(data) if data is not None else None))
        return cursor.lastrowid

    def _update(self, card_id: str, fields: dict, at: str | None = None) -> None:
        fields = dict(fields, updated_at=at or self.now())
        assignments = ", ".join(f"{name} = ?" for name in quoted(fields))
        self.conn.execute(f"UPDATE cards SET {assignments} WHERE id = ?",
                          (*fields.values(), card_id))

    def insert_card(self, row: dict, actor: str, at: str | None = None) -> str:
        """Insert a complete card row (the importer's path); records `create`."""
        row = {name: row.get(name) for name in CARD_FIELDS}
        if row["id"] is None:
            row["id"] = self.next_id()
        if row["space"] is None or row["title"] is None:
            raise Refused("a card needs a space and a title")
        if row["stage"] not in STAGES:
            raise Refused(f"unknown stage {row['stage']}")
        if row["autonomy"] not in AUTONOMY:
            raise Refused(f"unknown autonomy {row['autonomy']}")
        row["brief"] = row["brief"] or ""
        refuse_reserved(row["options"])
        row["options"] = json.dumps(row["options"] or {}) if not isinstance(row["options"], str) else row["options"]
        row["created_at"] = row["created_at"] or self.now()
        row["updated_at"] = row["updated_at"] or row["created_at"]
        columns = ", ".join(quoted(CARD_FIELDS))
        marks = ", ".join("?" for _ in CARD_FIELDS)
        self.conn.execute(f"INSERT INTO cards ({columns}) VALUES ({marks})",
                          tuple(row[name] for name in CARD_FIELDS))
        self.record_event(row["id"], "create", actor, text=row["title"], at=at or row["created_at"])
        return row["id"]

    def create(self, space: str, title: str, brief: str = "", autonomy: str | None = None,
               repo: str | None = None, model: str | None = None, parent: str | None = None,
               after: str | list | None = None, options: dict | None = None, actor: str = "cli",
               stage: str = "inbox", topic: str | None = None,
               from_card: str | None = None, assumed=()) -> str:
        """File a card. Every creator ends here, so the card defaults resolve here
        (`cardspec.resolve`): `repo`, `model`, `autonomy` and `topic` are filled from what
        was stated, then inherited from `from_card` (else `parent`), then the space's
        default, then Keel's, and each one's provenance lands in `options.provenance`.
        `assumed` names the given fields that were a guess rather than his words."""
        with self.tx():
            return self.create_in_tx(space, title, brief=brief, autonomy=autonomy, repo=repo,
                                     model=model, parent=parent, after=after, options=options,
                                     actor=actor, stage=stage, topic=topic,
                                     from_card=from_card, assumed=assumed)

    def create_in_tx(self, space: str, title: str, brief: str = "", autonomy: str | None = None,
                     repo: str | None = None, model: str | None = None,
                     parent: str | None = None, after: str | list | None = None,
                     options: dict | None = None, actor: str = "cli", stage: str = "inbox",
                     topic: str | None = None, from_card: str | None = None,
                     assumed=(), errand: bool = False) -> str:
        """`create`'s whole body, for a caller that already holds the write (an escalation's
        answer files its card in the same transaction, `keel/asks.py`). `errand` says "no
        repo" was stated, so a repo is not inherited from `from_card` (c-550: the ask files
        exactly what it showed him)."""
        if not space:
            raise Refused("a card needs a space")
        if not title:
            raise Refused("a card needs a title")
        authority.refuse_create(space, options, actor, self.builder, repo=repo,
                                scope=None if self.superuser else self.builds)
        granted = sorted(set(HIS_AT_CREATE) & set(options or {}))
        if granted and actor != "human":
            raise Refused(f"options.{granted[0]} is the owner's to set (with their token), not {actor}'s")
        if shipauto.option_problem(options):
            raise Refused(shipauto.option_problem(options))
        after = views.after_text(views.afters(",".join(after) if isinstance(after, list) else after))
        for ref in (parent, from_card):
            if ref is not None:
                self._row(ref)
        if parent is not None:
            self._refuse_tracking_parent(parent)
            self._refuse_other_space(parent, space)
        after = self._refuse_after(None, after, parent=parent)
        source = from_card or parent
        inherit = dict(self._row(source)) if source else None
        if errand and inherit:
            inherit["repo"] = None
        # c-760: a slice (a parent, and no `--from`) takes its parent's stated options too
        above = dict(self._row(parent)) if parent and not from_card else None
        spec, missing = self._resolve(space, {"repo": repo, "model": model, "autonomy": autonomy,
                                              "topic": topic, "options": options},
                                      assumed, inherit, above)
        spec, notes = self._untaken(space, spec, options, above)
        if stacking.OPTION in (options or {}):
            # r1.F1: on what the card resolved to, its inherited base given up to the stack first
            spec = self._stand_stack(space, spec, options, views.afters(after), above, notes)
        self._refuse_worker_setter(options, actor)
        self._inherit_worker(spec, inherit)
        self._refuse_worker({"space": space, "repo": spec.get("repo"), "options": spec.get("options") or {}})
        self._refuse_browser(space, spec.get("repo"), spec.get("options") or {})
        self._refuse_base(space, spec.get("repo"), spec.get("options") or {})
        if errand:
            spec["options"][cardspec.PROVENANCE_OPTION]["repo"] = cardspec.STATED
        made = self.insert_card(dict(spec, space=space, title=title, brief=brief,
                                     stage=stage, parent=parent, after=after,
                                     **{"from": from_card}), actor)
        self._hold_left_behind(made, missing, above, actor)
        self._note_all(made, notes, actor)
        return made

    def _untaken(self, space: str, spec: dict, stated: dict | None,
                 parent: dict | None) -> tuple[dict, list[str]]:
        """c-760 r1.F10: an inherited value that a create-time rule refuses does not travel.
        Each rule answers for its own key (`_base_problem`, `_browser_problem`), and is asked
        only of a value that came from the parent (in the resolved options, absent from the
        stated ones). One that fails is given up, with one note for the slice. The same list
        runs at create and at the split; a stated value is refused as it always was."""
        options, notes = spec.get("options") or {}, []
        if parent is None:
            return spec, notes
        rules = {"base": self._base_problem, "browser": self._browser_problem}
        for key, problem in rules.items():
            why = None if key in (stated or {}) or key not in options else problem(
                space, spec.get("repo"), options)
            if why:
                notes.append(self._untaken_note(key, options[key], parent["id"], why))
                options = cardspec.without(options, key)
        return dict(spec, options=options), notes

    @staticmethod
    def _untaken_note(key: str, value, parent_id: str, why: str) -> str:
        return f"{key} {cardspec.words(value)} was {parent_id}'s and was not taken: {why}"

    def _note_all(self, card_id: str, notes: list[str], actor: str) -> None:
        for text in notes:
            self.record_event(card_id, "note", actor, text=text)

    def _stack_base(self, options: dict, stated: dict | None, after: list[str], value,
                    parent: dict | None) -> tuple[dict, str | None]:
        """c-760: a base a slice inherited yields to its stack, at the split and at create
        alike (r1.F1). A stacked card merges into the base of the card it is stacked on, so
        an inherited one that differs is given up: `(the options to try, the note saying so)`.
        The caller keeps the options it had when the stack does not stand (r1.F3)."""
        if (value != stacking.STACKED or not after or parent is None or "base" in (stated or {})
                or not options.get("base")):
            return options, None
        theirs = stacking.parent_facts(self, after[0]).get("base")
        if options["base"] == theirs:
            return options, None
        why = f"this card is stacked on {after[0]}, which merges into {theirs or bases.BLANK}"
        return (cardspec.without(options, "base"),
                self._untaken_note("base", options["base"], parent["id"], why))

    def _stand_stack(self, space: str, spec: dict, stated: dict | None, after: list[str],
                     parent: dict | None, notes: list[str]) -> dict:
        """A stated stack answer checked on the resolved card, or refused."""
        value = (stated or {})[stacking.OPTION]
        options, note = self._stack_base(spec.get("options") or {}, stated, after, value, parent)
        self._refuse_stack_value(space, value, after, {"repo": spec.get("repo"), "base": options.get("base")})
        notes.extend([note] if note else [])
        notes.extend(self._stack_spread(value, after, spec.get("repo")))
        return dict(spec, options=options)

    def _hold_left_behind(self, card_id: str, missing: list[dict], parent: dict | None,
                          actor: str) -> None:
        """c-760 r1.F7: a slice that took a mode from its parent and not the parent's own
        thing the mode needs (`cardspec.left_behind`: a link to one ticket, say) is BLOCKED
        as it is filed, with the two ways on, so it cannot start as it stands. The split
        goes through: the deck's Split cannot state a mode per slice, so a refusal there
        would be a dead end."""
        if not missing or parent is None:
            return
        reason = " ".join(cardspec.held_reason(row, parent["id"], card_id) for row in missing)
        self._update(card_id, {"blocked_reason": reason})
        self.record_event(card_id, "block", actor, text=reason)

    def _refuse_base(self, space: str, repo: str | None, options: dict) -> None:
        """c-732 r1.F4: a card on a repo whose cards land on an integration branch names no
        base of its own: that branch is config, never a card field. Asked at create and at
        set; `merging.card_base` ignores one that got past, beneath this."""
        base = str(options.get("base") or "").strip()
        if not base:
            return
        problem = bases.branch_problem(base)      # r1.F12: the one branch-name rule
        if problem:
            raise Refused(f"options.base: {problem}")
        problem = self._base_problem(space, repo, options)
        if problem:
            raise Refused(f"{problem}: leave Base branch empty")

    def _base_problem(self, space: str, repo: str | None, options: dict) -> str | None:
        """Why a card on `repo` takes no base, or None: one of its repos lands on its
        integration branch. Not the branch-name rule, which refuses whoever named it."""
        if not str(options.get("base") or "").strip():
            return None
        for key in [part.strip() for part in str(repo or "").split(",") if part.strip()]:
            if (space, key) in self.integrated:
                return f"{key} lands on its integration branch, so a card on it names no base of its own"
        return None

    def _refuse_browser(self, space: str, repo: str | None, options: dict) -> None:
        """Tests only until the repo's file says how to run the app (c-678, decision
        `testsonly`): a card on a repo whose adopted CLAUDE.md has no run rule cannot take
        the browser. Asked at create and whenever a set would leave a card so."""
        problem = self._browser_problem(space, repo, options)
        if problem:
            raise Refused(f"{problem}: sessions there run tests only until it does")

    def _browser_problem(self, space: str, repo: str | None, options: dict) -> str | None:
        if options.get("browser") is not True or self.run_rule is None:
            return None
        for key in [part.strip() for part in str(repo or "").split(",") if part.strip()]:
            if self.run_rule(space, key) is False:
                return (f"{key}'s CLAUDE.md does not say how to run the app yet, so a card on it "
                        f"cannot take the browser")
        return None

    def _refuse_worker_setter(self, options: dict | None, actor: str) -> None:
        if views.WORKER_OPTION in (options or {}) and actor not in WORKER_SETTERS:
            raise Refused(f"options.{views.WORKER_OPTION} is the owner's to choose, not {actor}'s")

    @staticmethod
    def _inherit_worker(spec: dict, source) -> None:
        """A card made from a house's card (a slice, or `--from`) is a house's too unless it
        says otherwise (c-645 r1.F2). Only `house` is carried: `bosun` is the same as none."""
        if not source:
            return
        options = authority.options_of(source)
        mine = spec.setdefault("options", {})
        if options.get(views.WORKER_OPTION) == "house" and views.WORKER_OPTION not in mine:
            mine[views.WORKER_OPTION] = "house"

    def _refuse_worker_move(self, row, fields: dict) -> None:
        """His move of a card between workers: before anything started on it (c-645)."""
        if row["stage"] not in WORKER_STAGES or row["session_id"]:
            raise Refused(f"{row['id']} has started (it is at {row['stage']}"
                          f"{', with a session' if row['session_id'] else ''}): its worker changes only "
                          f"at {' or '.join(WORKER_STAGES)}, before anything starts; stop it first")
        if views.claimed(row):
            raise Refused(f"{row['id']} is claimed by a drain that is starting it: its worker "
                          f"changes only before that")
        # the children that make it a tracking card, as the pane counts them (archived ones not)
        if self.tracked_children(row["id"]):
            raise Refused(f"{row['id']} is a tracking card: each of its slices has its own worker")
        merged = merge_options(json.loads(row["options"] or "{}"), fields.get("options") or {})
        self._refuse_worker({"space": row["space"], "repo": fields.get("repo", row["repo"]), "options": merged})

    def _refuse_worker(self, row) -> None:
        """A worker is one of WORKERS, and Bosun only on a card he may build (c-645)."""
        worker = (row["options"] or {}).get(views.WORKER_OPTION)
        if worker is None:
            return
        if worker not in views.WORKERS:
            raise Refused(f"options.{views.WORKER_OPTION} is one of {', '.join(views.WORKERS)}, not {worker!r}")
        if worker == "bosun" and not views.bosun_eligible(self, row):
            raise Refused("Bosun builds only a personal card on a repo it builds, in builder mode; "
                          "this card's worker is a house")

    def _resolve(self, space: str, fields: dict, assumed=(), source: dict | None = None,
                 parent: dict | None = None) -> tuple[dict, list[dict]]:
        """The card as resolved, and what a slice now needs that its parent did not hand it.
        r1.F6, r2.F1: no slice takes an option its creator could not have stated at create
        (the owner's, a worker, Keel's own records), whoever splits. `kind` is not one: any
        creator may state it, so it travels (`cardspec.OWN_KINDS` aside)."""
        try:
            return cardspec.resolve(self.defaults, space, fields, assumed, source, parent,
                                    held=HIS_AT_CREATE + (views.WORKER_OPTION,) + RESERVED_OPTIONS)
        except cardspec.SpecError as why:
            raise Refused(str(why)) from None

    def _refuse_tracking_parent(self, parent_id: str) -> None:
        """Refuse `--parent X` when X is a card a house is working or has worked.

        A house that filed one follow-up under its own card turned that card into a
        tracking card and lost its gate with it: c-295 lost its plan gate, c-286 could not
        stage to review, c-292 was nudged at `building` with nothing left to do (all on
        2026-09-19). A card already tracking is exempt, because another child changes
        nothing about it: that is how the planner adds a phase card under c-278.
        """
        row = self._row(parent_id)
        if views.archived(row):
            # Before the exemption below, on purpose: another child under an archived card
            # is exactly how c-014 came back on the board as a tracking card (c-427).
            raise Refused(
                f"{parent_id} is archived, and a slice under it would bring it back as a "
                f"tracking card. For work that came out of it, use `--from {parent_id}`; to "
                f"really slice it, unarchive it first (`kb set {parent_id} options.archived=null`).")
        if self.children(parent_id):
            return
        if row["session_id"]:
            worked = "has a house session"
        elif json.loads(row["options"] or "{}").get(CLAIM_OPTION):
            worked = "is claimed by a drain"
        elif row["stage"] in WORKED_STAGES:
            worked = f"is at {row['stage']}"
        else:
            return
        raise Refused(
            f"{parent_id} {worked}, so it cannot become a tracking card: a parent's stage "
            f"follows its children and it loses its own gate. For a follow-up, or work "
            f"someone else will do, use `--from {parent_id}` instead. To really cut "
            f"{parent_id}'s own work into slices, use `kb split {parent_id}`.")

    def _refuse_link(self, card_id: str, name: str, target: str) -> None:
        """Refuse a `parent` or `from` that names no card, this card, or a cycle."""
        self._row(target)
        if target == card_id:
            raise Refused(f"{card_id} cannot be its own parent" if name == "parent"
                          else f"{card_id} cannot have come out of itself")
        if name != "parent":
            return
        seen, walk = {card_id}, target
        while walk:
            if walk in seen:
                raise Refused(f"{target} is below {card_id} already; that parent is a cycle")
            seen.add(walk)
            walk = self._row(walk)["parent"] or None

    def _refuse_other_space(self, parent_id: str, space: str) -> None:
        """A slice lives in its parent's space: a tree is one space's work, and the drain,
        the deck and `kb queue` all read a tree from the space its top card is in."""
        theirs = self._row(parent_id)["space"]
        if theirs != space:
            raise Refused(f"{parent_id} is in the {theirs} space, not {space}; a slice is "
                          f"filed in its parent's space (for related work elsewhere, use --from)")

    def _refuse_multi_after(self, ids: list) -> None:
        """Several ids in one `after` only with `[keel] multi_after` on. A drain or deck on
        code from before c-302 (the Mac's `keel run` reads this board over HTTP) reads the
        column as ONE id and fails on the whole board when it meets a comma list, so the
        switch goes on only after both machines run this code (Atlas: cards and gates)."""
        if len(ids) > 1 and "multi_after" not in self.switches:
            raise Refused("a card waits for one card while [keel] multi_after is off; "
                          f"{', '.join(ids)} is several (switch on [keel] multi_after to "
                          "allow several)")

    def _above(self, card_id: str | None) -> list[str]:
        """The card and every card above it, nearest first."""
        found, walk = [], card_id
        while walk and walk not in found:
            found.append(walk)
            walk = self._row(walk)["parent"] or None
        return found

    def _waits_on(self, card_id: str) -> list[str]:
        """What a card's own finishing depends on: every card its `after` names and, for a
        tracking card, every tracked slice (its stage follows theirs, `views.parent_stage`)."""
        row = self._row(card_id)
        slices = [child["id"] for child in views.tracked(row, self.children(card_id))]
        return views.afters(row["after"]) + slices

    def _refuse_after(self, card_id: str | None, text: str | None,
                      parent: str | None = None, above: list[str] | None = None) -> str | None:
        """An `after` as the column stores it (`c-311,c-313`), every card it names checked:
        it exists, it is not this card, and nothing it waits for, however far down and
        through a tree's slices as well as its afters, is this card or a card above it (a
        tracking card finishes only when its slices do, so waiting on one's own tree, or on
        a tree that waits on this card, is a cycle that leaves every card on it waiting for
        ever). `card_id` is None for a card being filed, which stands under `parent`;
        `above` is the card and its ancestors when a `set` is moving it at the same time."""
        ids = views.afters(text)
        for target in ids:
            self._row(target)
        if card_id is not None and card_id in ids:
            raise Refused(f"{card_id} cannot wait for itself")
        self._refuse_multi_after(ids)
        if above is None:
            above = self._above(card_id if card_id is not None else parent)
        self._refuse_waits(ids, set(above), card_id or "this card")
        return views.after_text(ids)

    def _refuse_waits(self, start: list[str], barred: set, who: str) -> None:
        """Refuse when anything `start` waits for, through afters and a tree's slices
        however far down, is in `barred` (a card and every card above it)."""
        todo, seen = list(start), set()
        while todo:
            walk = todo.pop()
            if walk in seen:
                continue
            seen.add(walk)
            if walk in barred:
                raise Refused(f"{walk} is {who} or above it, and a tree finishes only when its "
                              f"slices do; that after is a cycle")
            for after in self._waits_on(walk):
                if after in barred:
                    raise Refused(f"{walk} already waits for {after}, which is {who} or above "
                                  f"it; that after is a cycle")
                todo.append(after)

    def _refuse_stack(self, row: sqlite3.Row, fields: dict, actor: str) -> None:
        """c-718: `options.stack` only where it means something (`stacking.problem`), read
        against what this same set leaves the card with. r1.F1: on a card that carries a
        choice, its `after`, `repo` and `options.base` decide what it is stacked on, so a change
        of any of them is the owner's alone and is checked again."""
        options = fields.get("options") or {}
        held = json.loads(row["options"] or "{}")
        value = options[stacking.OPTION] if stacking.OPTION in options else held.get(stacking.OPTION)
        moves = [name for name in ("after", "repo") if name in fields] + (["options.base"] if "base" in options else [])
        if value is None or (stacking.OPTION not in options and not moves):
            return
        if moves and actor != "human":
            raise Refused(f"{row['id']} is {value} (options.stack), so its {moves[0]} is the owner's "
                          f"to change, not {actor}'s")
        after = fields["after"] if "after" in fields else row["after"]
        after = views.afters(",".join(after) if isinstance(after, list) else after)
        base = options["base"] if "base" in options else held.get("base")
        self._refuse_stack_value(row["space"], value, after,
                                 {"repo": fields.get("repo", row["repo"]), "base": base})

    def _slice_stack(self, parent: sqlite3.Row, piece: dict, spec: dict, after: list[str],
                     after_titles: list[str], said: list[str], answers: dict, used: set,
                     notes: list[str]) -> dict:
        """c-718's addition: a slice's stacked or independent answer, from the start. The one
        the owner gave on the slice (the deck's Split) is checked like any (r1.F9) and refuses
        the split when it cannot stand. The one the owner approved on the card being split
        (`options.split_stack`) is given only when the slice waits for exactly the slice it was
        approved on (r2.F1, `stacking.split_answer`) and it can stand; otherwise it is left off
        and said, since the house running the split cannot change it. c-760: a base the slice
        inherited is given up to a stack that stands, said in the split's note and in the slice's
        own (`notes`); a slice left without a choice keeps the options it had (r1.F3). c-772: a
        slice needs one repo in common with the slice it is stacked on, and one that names more
        is read back per repo, in the split's note and its own, as create and set say it."""
        own = dict(spec.get("options") or {})
        own.pop(stacking.SPLIT_OPTION, None)
        given = (piece.get("options") or {}).get(stacking.OPTION)
        own.pop(stacking.OPTION, None)
        if stacking.title_key(piece["title"]) in answers:
            used.add(stacking.title_key(piece["title"]))
        if given is not None:
            value, why = given, None
            if not after:
                value, why = None, f"'{piece['title']}' waits for nothing, so it starts at once"
        else:
            value, why = stacking.split_answer(answers, piece["title"], after_titles)
        if why:
            said.append(why)
        if value is None:
            return dict(spec, options=own)
        tried, note = self._stack_base(own, piece.get("options"), after, value, dict(parent))
        try:
            self._refuse_stack_value(parent["space"], value, after,
                                     {"repo": spec.get("repo"), "base": tried.get("base")})
        except Refused as error:
            if given is not None:
                raise Refused(f"slice {piece['title']!r}: {error}") from None
            said.append(f"'{piece['title']}' left without a choice: {error}")
            return dict(spec, options=own)
        # c-772: a slice stacked in only some of its repos says which, here and in its own note
        spread = self._stack_spread(value, after, spec.get("repo"))
        said.append(f"'{piece['title']}' " + (spread[0].removeprefix("this card is ") if spread else value))
        notes.extend(spread)
        if note:
            said.append(f"'{piece['title']}': {note}")
            notes.append(note)
        return dict(spec, options=dict(tried, **{stacking.OPTION: value}))

    def _block_stacked_on(self, card_id: str, actor: str) -> tuple[list[str], list[str]]:
        """r2.F5: the cards stacked on a card that is being split. It becomes a tracking card
        with no branch of its own, so each is blocked once, in the split's own write, with the
        sentence naming it and the way on, as `block` blocks (its re-offer ask dropped with a
        note, `_drop_reoffer`). `(blocked, already)`: the ones blocked now, and the ones
        already blocked for another reason, left as they are and named all the same."""
        blocked, already = [], []
        rows = self.conn.execute('SELECT * FROM cards WHERE "after" IS NOT NULL AND stage != \'done\'').fetchall()
        for row in rows:
            if (stacking.choice(row) != stacking.STACKED or stacking.afters_of(row)[:1] != [card_id]
                    or views.archived(row)):
                continue
            if row["blocked_reason"]:
                already.append(row["id"])
                continue
            reason = stacking.SPLIT_UNDER.format(parent=card_id, id=row["id"])
            self._update(row["id"], {"blocked_reason": reason})
            self.record_event(row["id"], "block", actor, text=reason,
                              data={"stack": {"parent": card_id, "event": "split"}})
            self._drop_reoffer(row["id"], actor, "blocked")
            blocked.append(row["id"])
        return blocked, already

    def _refuse_once(self, row: sqlite3.Row, fields: dict, actor: str) -> None:
        """r1.F1: `ONCE_OPTIONS` are written once; a different value later is the owner's."""
        options = fields.get("options") or {}
        held = json.loads(row["options"] or "{}")
        for name in ONCE_OPTIONS:
            if name in options and held.get(name) and options[name] != held[name] and actor != "human":
                raise Refused(f"{row['id']}'s options.{name} is {held[name]} already: a card's {name} "
                              f"is named once, and changed after that only by the owner")

    def _refuse_stack_value(self, space: str, value, after: list[str], child: dict) -> None:
        """`stacking.problem` with what the board knows of the card it would stack on."""
        parent = stacking.parent_facts(self, after[0]) if value == stacking.STACKED and after else None
        said = stacking.problem(value, after, space, self.stacks, parent, child)
        if said:
            raise Refused(said)

    @staticmethod
    def _slice_repos(parent: sqlite3.Row, piece: dict) -> str | None:
        """A slice's stated repos (`cardspec.slice_repos`), or the split refused with why."""
        repos, why = cardspec.slice_repos(piece.get("repo"), parent["repo"], parent["id"])
        if why:
            raise Refused(f"slice {piece['title']!r}: {why}")
        return repos

    def _stacked_on(self, card_id: str) -> list[sqlite3.Row]:
        """The cards stacked on this one that are not done or archived."""
        rows = self.conn.execute('SELECT * FROM cards WHERE "after" IS NOT NULL AND stage != \'done\'').fetchall()
        return [row for row in rows if stacking.choice(row) == stacking.STACKED
                and stacking.afters_of(row)[:1] == [card_id] and not views.archived(row)]

    def _refuse_repo_under_stack(self, row: sqlite3.Row, repo) -> list[sqlite3.Row]:
        """c-772: a card's `repo` decides where the cards stacked on it are stacked (they are
        cut from its branch only in a repo it names). A set that would leave one of them
        sharing no repo with it is refused, naming that card. The ones whose stacked and
        not-stacked repos the set changes, for the note each gets once it is written."""
        new, old, moved = stacking.repos_of(repo), stacking.repos_of(row["repo"]), []
        for kid in self._stacked_on(row["id"]):
            mine = stacking.repos_of(kid["repo"])
            if not any(key in new for key in mine):
                raise Refused(f"{kid['id']} is stacked on {row['id']} and works in {', '.join(mine) or 'no repo'}: "
                              f"with repo {', '.join(new) or 'cleared'}, {row['id']} would have no branch in any "
                              f"repo of {kid['id']} to stack on. Make {kid['id']} independent first (`kb set "
                              f"{kid['id']} options.stack=independent`), or keep a repo the two share")
            if [key for key in mine if key in new] != [key for key in mine if key in old]:
                moved.append(kid)
        return moved

    def _say_repo_under_stack(self, card_id: str, moved: list[sqlite3.Row], actor: str) -> None:
        """One note on each card whose stack this card's new `repo` moved (`stacking.spread`)."""
        for kid in moved:
            said = self._stack_spread(stacking.STACKED, [card_id], kid["repo"]) or [
                f"this card is stacked on {card_id} in every repo it names ({kid['repo']})"]
            self.record_event(kid["id"], "note", actor, text=f"{card_id}'s repos changed: {said[0]}")

    def _stack_spread(self, value, after: list[str], repo) -> list[str]:
        """c-772: the note that reads a stacked choice back per repo (`stacking.spread`), for a
        card that names a repo the card it is stacked on does not; none for any other card."""
        if value != stacking.STACKED or not after:
            return []
        said = stacking.spread(after[0], stacking.repos_of(repo),
                               stacking.parent_facts(self, after[0]).get("repos") or [])
        return [f"this card is {said}"] if said else []

    def _link_fields(self, card_id: str, fields: dict) -> dict:
        """The update with every link field cleaned: "" clears it, a value is checked.
        An `after` is checked against the parent the card will have once this `set` lands."""
        update = dict(fields)
        row = self._row(card_id)
        parent = (update["parent"] or None) if "parent" in update else row["parent"]
        above = [card_id] + self._above(parent)
        for name in LINK_FIELDS:
            if name not in update:
                continue
            target = update[name] or None
            if name == "after":
                update[name] = self._refuse_after(card_id, target, above=above)
                continue
            update[name] = target
            if target is not None:
                self._refuse_link(card_id, name, target)
        if parent is not None and parent != row["parent"]:
            self._refuse_new_parent(row, parent, update.get("after", row["after"]), above)
        return update

    def _refuse_new_parent(self, row: sqlite3.Row, parent: str, after: str | None,
                           above: list[str]) -> None:
        """`kb set parent=` answers to what `create --parent` does (J-2): the new parent
        makes a tracking card as surely as a filing under it (c-427), a slice lives in its
        parent's space, and the card, through its afters and its own slices, may not wait
        for the tree it is joining (the new parent then waits for it: a cycle)."""
        self._refuse_tracking_parent(parent)
        self._refuse_other_space(parent, row["space"])
        slices = [child["id"] for child in views.tracked(row, self.children(row["id"]))]
        self._refuse_waits(views.afters(after) + slices, set(above), row["id"])

    def _record_corrections(self, row: sqlite3.Row, update: dict, actor: str,
                            assumed=()) -> None:
        """A `set` of a field that was assumed or defaulted is his correction of it: one
        `correct` event each, and the field is then `stated` (`cardspec.corrections`).

        A field named in `assumed` is the setter's guess, not a correction: it is left out
        of the comparison and tagged `assumed` (D-3, the capture's refine choosing a repo
        his words did not settle), so his own later change of it is still a correction."""
        stored = dict(row, options=json.loads(row["options"] or "{}"))
        incoming = dict(update, options=update.get("options") or {})
        for name in assumed:
            incoming.pop(name, None)
        found, tags = cardspec.corrections(stored, incoming, self.defaults.for_space(row["space"]))
        for each in found:
            self.record_event(row["id"], "correct", actor, text=cardspec.correction_text(each),
                              data=each)
        if assumed:
            tags = dict(tags if tags is not None else
                        stored["options"].get(cardspec.PROVENANCE_OPTION) or {})
            tags.update({name: cardspec.ASSUMED for name in assumed})
        if tags is not None:
            options = json.loads(self._row(row["id"])["options"] or "{}")
            self._update(row["id"], {"options": json.dumps(
                dict(options, **{cardspec.PROVENANCE_OPTION: tags}))})

    def _check_assumed(self, card_id: str, assumed: set, actor: str) -> None:
        """A guess may be set only by the voice actor (the capture's refine), and never
        over a field he stated: his words and his corrections are never relabelled."""
        if actor not in ASSUMING_ACTORS:
            raise Refused(f"--assumed is the capture refine's, not {actor}'s")
        tags = json.loads(self._row(card_id)["options"] or "{}").get(
            cardspec.PROVENANCE_OPTION) or {}
        stated = sorted(name for name in assumed if tags.get(name) == cardspec.STATED)
        if stated:
            raise Refused(f"{', '.join(stated)} is stated on {card_id}; a guess never "
                          f"replaces the user's words")

    def _check_stated(self, card_id: str, fields: dict, assumed: set) -> None:
        """The voice actor never overwrites what he STATED, guess or not (round 2, item
        C): a tracked field tagged `stated` is his words or his correction."""
        tags = json.loads(self._row(card_id)["options"] or "{}").get(
            cardspec.PROVENANCE_OPTION) or {}
        stated = sorted(name for name in fields
                        if name in cardspec.TRACKED and tags.get(name) == cardspec.STATED
                        and name not in assumed)
        if stated:
            raise Refused(f"{', '.join(stated)} is stated on {card_id}; the voice actor "
                          f"never overwrites the user's words")

    def set_fields(self, card_id: str, fields: dict, actor: str, assumed=(),
                   mend: dict | None = None) -> dict:
        """`mend` ({why, facts}) is Bosun's repair (c-575, `keel/repair.py`): only the paths
        Keel reads, on a card in any space, checked and counted in this write."""
        assumed = set(assumed or ())
        stray = sorted(assumed - set(fields))
        if stray:
            raise Refused(f"--assumed names a field this set does not give: {', '.join(stray)}")
        if assumed:
            self._check_assumed(card_id, assumed, actor)
        if actor in ASSUMING_ACTORS:
            self._check_stated(card_id, fields, assumed)
        for guarded in (LANDING_OPTION, ROTATE_OPTION, PUSH_OPTION, CUT_FROM_OPTION):
            if guarded in (fields.get("options") or {}) and actor not in LANDING_ACTORS:
                raise Refused(f"options.{guarded} is the drain's, not {actor}'s to set")
        if PUBLISHING_OPTION in (fields.get("options") or {}):
            raise Refused(f"options.{PUBLISHING_OPTION} is written only by the owner's Approve outcome")
        if SHIPPING_OPTION in (fields.get("options") or {}) and actor not in SHIPPING_ACTORS:
            raise Refused(f"options.{SHIPPING_OPTION} is the watcher's and the owner's, not {actor}'s to set")
        if REOFFER_OPTION in (fields.get("options") or {}) and actor != "drain":
            raise Refused(f"options.{REOFFER_OPTION} is asked with `kb ship <id> reoffer`, "
                          f"and only the drain answering it clears it")
        if SENDBACK_OPTION in (fields.get("options") or {}):
            raise Refused(f"options.{SENDBACK_OPTION} is the owner's send-back at shipping: it is asked with "
                          f"`kb ship <id> sendback`, and only the drain's fill takes it")
        fixed = sorted(set(HUMAN_ONLY_OPTIONS) & set(fields.get("options") or {}))
        refused = sorted(set(OWNERS_OPTIONS) & set(fields.get("options") or {}))
        if refused and actor not in WORKER_SETTERS:
            raise Refused(f"options.{refused[0]} is the owner's to change after create, not {actor}'s")
        if fixed and actor != "human":
            raise Refused(f"options.{fixed[0]} is the owner's to change after create (with their token), "
                          f"not {actor}'s")
        if shipauto.option_problem(fields.get("options")):
            raise Refused(shipauto.option_problem(fields.get("options")))
        if VOICE_HOLD_OPTION in (fields.get("options") or {}) and actor not in HOLD_ACTORS:
            raise Refused(f"options.{VOICE_HOLD_OPTION} is the connected turn's "
                          f"(`keel converse`), not {actor}'s to set")
        if DROPIN_HOLD_OPTION in (fields.get("options") or {}) and actor not in DROPIN_HOLD_ACTORS:
            raise Refused(f"options.{DROPIN_HOLD_OPTION} is the owner's Drop in's and the drain's, "
                          f"not {actor}'s to set")
        if "space" in fields:
            raise Refused("space is immutable")
        if "stage" in fields:
            raise Refused("stage moves go through `stage`")
        unknown = [name for name in fields if name not in SETTABLE]
        if unknown:
            raise Refused(f"not a card field: {', '.join(unknown)}")
        if "autonomy" in fields and fields["autonomy"] not in AUTONOMY:
            raise Refused(f"autonomy is one of {', '.join(AUTONOMY)}")
        if "model" in fields and model_problem(fields["model"]):
            raise Refused(f"model: {model_problem(fields['model'])}")
        with self.tx():
            row = self._row(card_id)
            if views.WORKER_OPTION in (fields.get("options") or {}):
                self._refuse_worker_move(row, fields)
            self._refuse_stack(row, fields, actor)
            moved = self._refuse_repo_under_stack(row, fields["repo"]) if "repo" in fields else []
            self._refuse_once(row, fields, actor)
            if "repo" in fields or "base" in (fields.get("options") or {}):
                self._refuse_base(row["space"], fields.get("repo", row["repo"]),
                                  merge_options(json.loads(row["options"] or "{}"), fields.get("options") or {}))
            if "repo" in fields or "browser" in (fields.get("options") or {}):
                self._refuse_browser(row["space"], fields.get("repo", row["repo"]),
                                     merge_options(json.loads(row["options"] or "{}"), fields.get("options") or {}))
            if mend is None:
                authority.refuse_set(row, fields, actor, self.builder)
            else:
                repair.refuse_repair_set(row, fields, mend.get("facts") or {})
            update = self._link_fields(card_id, fields)
            # The event says what the card now holds, so a cleared link reads as null and
            # not as the empty string that was typed; `options` stays the incoming dict.
            recorded = dict(update)
            if "options" in update:
                recorded["options"] = fields["options"]
                update["options"] = json.dumps(
                    merge_options(json.loads(row["options"]), update["options"] or {}))
            if unchanged(row, update):
                return self.get(card_id)   # no event and no new updated_at (c-440)
            if mend is not None:
                self._repair(row, "field", actor, mend.get("why"))   # a no-op records none
                recorded["repair"] = True
            self._update(card_id, update)
            self.record_event(card_id, "set", actor, data=recorded)
            if stacking.OPTION in (fields.get("options") or {}) or "after" in fields or "repo" in fields:
                held = self._row(card_id)       # c-772: which repos the stack holds in, read back
                self._note_all(card_id, self._stack_spread(stacking.choice(held), stacking.afters_of(held),
                                                           held["repo"]), actor)
            self._say_repo_under_stack(card_id, moved, actor)
            self._record_corrections(row, fields, actor, assumed)
            if views.archived(self._row(card_id)):
                self._drop_reoffer(card_id, actor, "archived")
        return self.get(card_id)

    def set_backlog(self, card_id: str, value: str, actor: str) -> dict:
        """The human's manual `backlog|active|auto` on a card; `auto` clears it back to
        the date rule. Recorded as a `set` event, like any other option."""
        if value not in views.BACKLOG_CHOICES:
            raise Refused(f"backlog takes one of {', '.join(views.BACKLOG_CHOICES)}, got {value!r}")
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            if value == views.BACKLOG_AUTO:
                options.pop("backlog", None)
            else:
                options["backlog"] = value
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", actor,
                              data={"options": {"backlog": options.get("backlog")}})
        return self.get(card_id)

    # ----- stage moves -----

    def stage(self, card_id: str, new_stage: str, actor: str, plan_ref: str | None = None,
              output_ref: str | None = None, note: str | None = None,
              relay: dict | None = None, why: str | None = None) -> dict:
        """Move a card. `relay` ({prompt, to}) also records a `resume` relay in the same
        transaction: the deck's Send back for a house on another machine. `why` is Bosun's
        repair (c-575): the stage the card is already at, replayed, on a card in any space."""
        if new_stage not in STAGES:
            raise Refused(f"unknown stage {new_stage}; one of {', '.join(STAGES)}")
        if why is not None:
            return self._replay(card_id, new_stage, actor, why, refs=self._refs(plan_ref, output_ref),
                                note=note, relay=relay)
        with self.tx():
            row = self._row(card_id)
            refs = self._refs(plan_ref, output_ref)
            authority.refuse_move(row, actor, builder=self.builder)
            self._refuse_stage(card_id, row, new_stage, refs, actor)
            self._move(row, new_stage, actor, refs, note)
            self._cancel_landing(card_id, row, new_stage)
            self._drop_pretest(card_id, new_stage)
            self._clear_stale_block(row, new_stage, actor)
            if relay is not None:
                self._relay(row, "resume", actor, relay.get("to"), relay.get("prompt"), gate=True)
        return self.get(card_id)

    def _replay(self, card_id: str, stage: str, actor: str, why: str, refs: dict,
                note: str | None, relay: dict | None) -> dict:
        """Bosun's repair re-stage (c-575): the move checked again and signed, and NOTHING
        else. It records its `intervene` event only, never a `stage` event: every reader that
        measures a move (the landing guard, a gate's age, the review trip, the drain's quiet
        streak) reads `stage` events, and a replay that looked like a move withdrew his approve
        or reset those clocks (reviews 1.F1, 2.F1, 4.F4). It changes no field and no option."""
        with self.tx():
            row = self._row(card_id)
            repair.refuse_restage(row, stage, refs, relay, note)
            self._refuse_stage(card_id, row, stage, refs, actor)    # a tracking card's, above all
            self._repair(row, "stage", actor, why)
        return self.get(card_id)

    def _clear_stale_block(self, row: sqlite3.Row, new_stage: str, actor: str) -> None:
        """Lift, in the same write, a block the move makes untrue, and only such a block:
        a landing's refusal (`landing-refused`) on a move to review, since the outcome it
        refused is superseded by the one staged now; the Stop hook's block at building
        (`stop-check`) on any move off building, since it says where the card stopped; and
        the unjudged block (`unjudged`, c-654) on the move to done, since the items its house
        left unjudged are moot once the card is done, and a done card left blocked would sit
        under needs you asking for a re-offer nothing accepts. In the move's own write, so
        that block is never lifted while the card stays at shipping."""
        if not row["blocked_reason"]:
            return
        found = self.conn.execute("SELECT * FROM events WHERE card = ? AND kind = 'block' "
                                  "ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
        block = views.event_dict(found) if found else None
        if not block or block["text"] != row["blocked_reason"]:
            return
        data = block["data"] or {}
        if new_stage == "review" and data.get("landing") == MARKS["landing-refused"]["landing"]:
            why = "a new outcome was staged, so the landing's refusal no longer stands"
        elif new_stage != "building" and (data.get("stopped") == "building"
                                          or row["blocked_reason"].startswith(STOP_CHECK_TEXT)):
            why = f"moved to {new_stage}, so the stop at building no longer stands"
        elif new_stage == "done" and data.get("unjudged"):
            why = UNJUDGED_MOOT
        else:
            return
        self._update(row["id"], {"blocked_reason": None})
        self.record_event(row["id"], "unblock", actor, text=why)

    def _cancel_landing(self, card_id: str, row: sqlite3.Row, new_stage: str) -> None:
        """A card that leaves review (a Send back) while its landing is testing withdraws the
        approve: the landing is marked cancelled, and the worker honours it before it lands."""
        options = json.loads(row["options"] or "{}")
        landing = options.get(LANDING_OPTION) or {}
        if row["stage"] != "review" or new_stage == "done" or landing.get("state") != "testing":
            return
        options[LANDING_OPTION] = dict(landing, state="cancelled", why=f"moved to {new_stage}")
        self._update(card_id, {"options": json.dumps(options)})

    def _drop_pretest(self, card_id: str, new_stage: str) -> None:
        """A move to review drops a finished pre-run's result (c-621): it answered for the
        outcome staged before, and Approve showed it for the new one. A running pre-run is
        kept; it is keyed on the heads it tested, and the drain runs it again when they moved."""
        options = json.loads(self._row(card_id)["options"] or "{}")
        pre = options.get(PRETEST_OPTION)
        if new_stage != "review" or not pre or pre.get("state") == "running":
            return
        options.pop(PRETEST_OPTION)
        self._update(card_id, {"options": json.dumps(options)})

    def _refs(self, plan_ref: str | None, output_ref: str | None) -> dict:
        refs = {}
        if plan_ref is not None:
            refs["plan_ref"] = plan_ref
        if output_ref is not None:
            refs["output_ref"] = output_ref
        return refs

    def _refuse_stage(self, card_id: str, row: sqlite3.Row, new_stage: str, refs: dict,
                      actor: str) -> None:
        if new_stage == "done" and proposals_of(row["options"]):
            # c-667: for every actor, his own stage move too: only the adopt closes one
            raise Refused(PROPOSAL_CLOSES.format(card=card_id))
        slices = self.tracked_children(card_id)
        if slices:
            self._refuse_tracking_move(row, new_stage, slices, actor)
            return
        self._refuse_shipping_move(row, new_stage, actor)
        closing_notice = new_stage == "done" and self._open_notice(row)
        # Forward past the plan gate only by `approve plan`. Back to the queue (a card started
        # by mistake, 2026-10-03: the cards the Mac's import had started) skips no gate, and
        # is his or Bosun's (the door scopes Bosun to its own cards); never a house's, whose
        # card the drain would start again.
        requeue = new_stage in QUEUED and actor in ("human", authority.BOSUN)
        if (row["stage"] == "planning" and row["autonomy"] == "attended"
                and new_stage != "planning" and not requeue and not closing_notice):
            raise Refused(f"{card_id} is attended: it leaves planning only through `approve plan`, "
                          f"or back to {' or '.join(QUEUED)}")
        if new_stage == "review":
            if not (refs.get("plan_ref") or row["plan_ref"]):
                raise Refused("review needs a plan_ref (pass --plan or set it first)")
            if not (refs.get("output_ref") or row["output_ref"]):
                raise Refused("review needs an output_ref (pass --output)")
        # The superuser's own landing only (c-619): the in-app builder's card reaches done
        # through the user's Approve outcome alone.
        landed_by_bosun = (actor == authority.BOSUN and self.builder and self.superuser
                           and views.bosun_builds(self, row) and row["stage"] != "shipping")
        if (new_stage == "done" and row["stage"] not in ("review", "shipping")
                and not closing_notice and not landed_by_bosun):
            raise Refused(f"done is reached only from review or shipping ({card_id} is at {row['stage']})")

    @staticmethod
    def _refuse_shipping_move(row: sqlite3.Row, new_stage: str, actor: str) -> None:
        """A card reaches `shipping` through Approve outcome (`_approve_outcome`), and from
        done or review through the shipping sync's own move (`ship_from_sync`, SH-11). It leaves
        only for done (c-600), and only the drain or he moves it: its house answers review
        there, and has no business closing its own pull request's card."""
        if new_stage == "shipping" and row["stage"] != "shipping":
            if row["stage"] != "done":
                raise Refused(f"{row['id']} reaches shipping only through Approve outcome")
            if actor not in SHIPPING_ACTORS:
                raise Refused(f"only the drain or the user brings a done card back to shipping, not {actor}")
        if row["stage"] == "shipping" and new_stage != "shipping":
            if actor not in SHIPPING_ACTORS:
                raise Refused(f"{row['id']} is shipping; the drain or the user moves it on, not {actor}")
            if new_stage not in SHIPPING_NEXT:
                raise Refused(f"{row['id']} is shipping; it goes on to {', '.join(SHIPPING_NEXT)}")

    @staticmethod
    def _refuse_tracking_move(row: sqlite3.Row, new_stage: str, slices: list, actor: str) -> None:
        """A tracking card's stage follows its children, with two stage moves of its own
        (lane X): to `review` once every slice is done (his Back to your gate), and back to
        `building` from `review` (his Send back, or the drain when a slice has left done) or
        from `done` while a slice is not done (the drain reopening one it closed, c-649). A
        house makes neither. `done` is never a stage move, whoever the actor says he is: it
        is `close_tracking`, the drain's, or his Approve outcome at review (c-649 review F6)."""
        at_gate = new_stage == "review" and row["stage"] not in ("review", "done")
        if new_stage == "done" or at_gate:
            refuse_open_slices(row, new_stage, slices)
        if new_stage == "done":
            raise Refused(f"{row['id']} is a tracking card; the drain closes it when every slice "
                          f"is done (or the user's Approve outcome at review), never a stage move")
        back = new_stage == "building" and (row["stage"] == "review" or (
            row["stage"] == "done" and not views.all_done(slices)))
        if not (at_gate or back) or actor not in TRACKING_MOVERS:
            raise Refused(f"{row['id']} is a tracking card; its stage follows its children")

    def close_tracking(self, card_id: str, actor: str, note: str) -> dict:
        """The drain's close of a tracking card whose slices are all done (c-649): to done
        from any stage, with its rollup as its outcome. No `kb` verb reaches it, so a shell
        that names itself the drain still cannot close one (review F6)."""
        if actor != TRACKING_CLOSER:
            raise Refused(f"a tracking card is closed by the drain, not {actor}")
        with self.tx():
            row = self._row(card_id)
            if proposals_of(row["options"]):        # c-667: a proposal that was split
                raise Refused(PROPOSAL_CLOSES.format(card=card_id))
            if not self.tracked_children(card_id):
                raise Refused(f"{card_id} is not a tracking card")
            if row["stage"] == "done":
                raise Refused(f"{card_id} is already done")
            self._close_tracking(row, actor, note)
        return self.get(card_id)

    def _close_tracking(self, row: sqlite3.Row, actor: str, note: str | None,
                        kind: str = "stage", data: dict | None = None) -> None:
        """Every close of a tracking card, in the caller's transaction: its slices read again
        here (one reopened since the caller looked refuses it), the rollup drafted beside its
        place, the move made with it as `output_ref`, and only then the rollup put in place.
        A refused move leaves no rollup behind (review F1, F5, F7)."""
        from keel import trackclose     # noqa: PLC0415 - the rollup reads the board
        slices = self.tracked_children(row["id"])
        refuse_open_slices(row, "done", slices)
        temp, path = trackclose.draft_rollup(self, self.get(row["id"]),
                                             [self.get(s["id"]) for s in slices], self.cards_dir)
        try:
            self._move(row, "done", actor, {"output_ref": str(path)}, note, kind=kind, data=data)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _open_notice(row: sqlite3.Row) -> bool:
        """A segment's notice closes from wherever it sits (S4: "open until staged done"; J-1).
        It has no outcome gate to pass: it sits at inbox, and a close refused there is how
        every automatic close failed until c-440 sat open after three good pulls. Anyone
        may file a notice, so anyone may close one; every other card still reaches done
        only from review."""
        return views.notice(row, json.loads(row["options"] or "{}"))

    def _move(self, row: sqlite3.Row, new_stage: str, actor: str, refs: dict,
              note: str | None, kind: str = "stage", data: dict | None = None) -> None:
        fields = dict(refs, stage=new_stage)
        options = json.loads(row["options"] or "{}")
        if PUBLISHING_OPTION in options:
            # The marker never outlives the approve it was written for (lane L round 3).
            options.pop(PUBLISHING_OPTION)
            fields["options"] = json.dumps(options)
        if new_stage != row["stage"] and options.get(FLOW_MOVE_OPTION):
            # His flow move's push grant is for the stage he tapped it at (c-640): a move on
            # ends it, so no grant outlives the move it was given for.
            options.pop(FLOW_MOVE_OPTION)
            fields["options"] = json.dumps(options)
        if new_stage != "shipping" and REOFFER_OPTION in options:
            # His re-offer is an ask of the drain's shipping watcher (c-651): off shipping
            # nothing answers it, so it never outlives the stage it was asked at.
            options.pop(REOFFER_OPTION)
            fields["options"] = json.dumps(options)
        untold = self._sendback_untold(options) if new_stage != "shipping" else []
        if new_stage != "shipping" and SENDBACK_OPTION in options:
            # his send-back is told at shipping (c-663): off it nothing tells it
            options.pop(SENDBACK_OPTION)
            fields["options"] = json.dumps(options)
        if new_stage == "assigned" and CLAIM_OPTION in options:
            # Back to assigned is a fresh start (Retry): any drain may take it again.
            options.pop(CLAIM_OPTION)
            fields["options"] = json.dumps(options)
        self._update(row["id"], fields)
        payload = dict(data or {}, **{"from": row["stage"], "to": new_stage}, **refs)
        self.record_event(row["id"], kind, actor, text=note, data=payload)
        if untold:
            self.record_event(row["id"], "note", actor, data={"sendback_dropped": untold},
                              text=SENDBACK_DROPPED.format(handles=", ".join(untold), stage=new_stage))

    @staticmethod
    def _sendback_untold(options: dict) -> list[str]:
        """The handles of his send-backs the house was never told (c-663): the asks still on
        the card, and his items still waiting in the batch."""
        waits = (options.get(SHIPPING_OPTION) or {}).get("pending") or []
        found = [str(asked.get("handle")) for asked in options.get(SENDBACK_OPTION) or []]
        found += [str(item.get("handle")) for item in waits if item.get("kind") == "his"]
        return sorted(set(found), key=found.index)

    def approve(self, card_id: str, gate: str, actor: str, publish=None,
                relay: dict | None = None, bosun: dict | None = None) -> dict:
        """Pass a gate. `relay` ({prompt, to}) at the plan gate records the `resume` relay
        in the move's own transaction, so the house's machine never sees the card at
        building without the prompt the approval carries.

        Bosun passes a gate only through `authority.gate_approval`: a personal card's
        outcome in builder mode, with `bosun` ({checked, facts}) saying what it checked and
        what the outcome holds (c-593: a plan gate is always his)."""
        if actor == authority.BOSUN:
            return self._approve_as_bosun(card_id, gate, relay, bosun or {})
        if actor != "human":
            raise Refused("approve is the human's alone (the token is missing or wrong)")
        if gate not in ("plan", "outcome"):
            raise Refused("approve takes `plan` or `outcome`")
        if relay is not None and gate != "plan":
            raise Refused("only the plan gate carries a relay")
        if gate == "plan":
            with self.tx():
                row = self._row(card_id)
                self._approve_plan(row, actor)
                if relay is not None:
                    self._relay(row, "resume", actor, relay.get("to"), relay.get("prompt"), gate=True)
        else:
            self._approve_outcome(card_id, actor, publish)
        return self.get(card_id)

    def _approve_plan(self, row: sqlite3.Row, actor: str, data: dict | None = None,
                      note: str | None = None) -> None:
        if row["stage"] != "planning":
            raise Refused(f"{row['id']} is at {row['stage']}, not planning")
        self._move(row, "building", actor, {}, note, kind="approve", data=data or {"gate": "plan"})

    def _approve_as_bosun(self, card_id: str, gate: str, relay: dict | None, bosun: dict) -> dict:
        with self.tx():
            row = self._row(card_id)
            # a card whose worker is a house is never Bosun's, the superuser's included (c-645)
            if views.worker_of(row) == "house" or (not self.superuser and not views.bosun_builds(self, row)):
                raise Refused(f"{card_id} is not a card the builder builds: its gates are the user's")
            if proposals_of(row["options"]):
                # c-667: a proposal's outcome is its draft adopted, which is his tap alone
                raise Refused(f"{card_id} is a proposal: its plan gate is the user's" if gate == "plan" else
                              f"{card_id} is a proposal: approving its outcome adopts its draft, which is the user's tap")
            if gate == "outcome":
                self._refuse_land(row)
            signed = authority.gate_approval(row, gate, bosun.get("facts"),
                                             bosun.get("checked") or "", self.builder,
                                             superuser=self.superuser, bypass=self.bypass)
            if gate == "plan":
                self._approve_plan(row, authority.BOSUN, data=signed["data"], note=signed["note"])
                return self.get(card_id)
            # Bosun's outcome approval is a `land` relay like his queued tap (c-526): the
            # landing worker merges it onto the integration branch after the suite, and
            # `land` moves the card to done. Main moves only on his deploy.
            self.record_event(card_id, "note", authority.BOSUN, text=signed["note"],
                              data={"approval": signed["data"]})
            self._relay(row, "land", authority.BOSUN, bosun.get("to"), None,
                        sha=signed["data"]["sha"], approval=signed["data"])
        return self.get(card_id)

    def _row_or_none(self, card_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()

    # ----- Bosun's repairs (c-575) -----

    def _repair(self, row: sqlite3.Row, kind: str, actor: str, why: str | None) -> None:
        """One of Bosun's repairs (c-575), checked and recorded in the caller's transaction;
        the event carries the why, so the card says who mended what and why."""
        why = (why or "").strip()
        repair.refuse_repair(row, kind, actor, why, self.events(row["id"]))
        self.record_event(row["id"], authority.INTERVENE_EVENT, actor, text=f"repair {kind}: {why}",
                          data={"what": repair.REPAIR, "repair": kind, "why": why})

    def repair(self, card_id: str, kind: str, actor: str, why: str, words: str = "") -> dict:
        """A house repair (resume, retry) recorded before `repairhouse` carries it out; `words` is what
        Bosun asked to say to the house, refused here, where the rule is fenced (review F4)."""
        if kind not in ("resume", "retry"):
            raise Refused(f"a {kind} repair goes through its own verb with --why")
        repair.refuse_words(words)
        with self.tx():
            self._repair(self._row(card_id), kind, actor, why)
        return self.get(card_id)

    def restart_card(self, card_id: str, actor: str) -> dict:
        """Bosun's retry repair, already recorded (`repair`): the block cleared and the card
        back at assigned for a fresh house, as his Retry does."""
        with self.tx():
            row = self._row(card_id)
            if actor != authority.BOSUN:
                raise Refused("a retry by anyone else is the deck's Retry")
            authority.refuse_retry(row)
            if row["blocked_reason"] is not None:
                self._update(card_id, {"blocked_reason": None})
                self.record_event(card_id, "unblock", actor)
                row = self._row(card_id)
            if row["stage"] != "assigned":
                self._refuse_stage(card_id, row, "assigned", {}, actor)
                self._move(row, "assigned", actor, {}, "retry by Bosun")
            else:
                # Claimed by a drain that never started it: freed, as his Retry frees it.
                options = json.loads(row["options"] or "{}")
                if options.pop(CLAIM_OPTION, None) is not None:
                    self._update(card_id, {"options": json.dumps(options)})
                    self.record_event(card_id, "claim", actor, text="released by Bosun's retry")
        return self.get(card_id)

    def record_wake(self, card_id: str, actor: str, told: dict) -> int:
        with self.tx():
            self._row(card_id)
            return self.record_event(card_id, "wake", actor, text=f"told up to event {told['event']}",
                                     data=told)

    def _refuse_outcome(self, row: sqlite3.Row) -> None:
        if row["stage"] != "review":
            raise Refused(f"{row['id']} is at {row['stage']}, not review")
        slices = self.tracked_children(row["id"])
        if slices and not views.all_done(slices):
            left = ", ".join(s["id"] for s in slices if s["stage"] != "done")
            raise Refused(f"{row['id']} is a tracking card and {left} is not done yet; "
                          f"it closes when every slice is")

    def _approve_outcome(self, card_id: str, actor: str, publish) -> None:
        """Publish outside the transaction (the adapter writes notes through `kb`, which
        needs the database), then move to done, re-checking the refusals first.

        A TRACKING card is closed, not published (lane X): each slice landed or published
        on its own when he approved it, so the callable is never called for it, whatever
        the caller passed (a merge, the adapter's publish), and nothing needs credentials.
        It closes through `_close_tracking`, as the drain's close does, so its rollup is
        its outcome either way (c-649 review F1)."""
        row = self._row(card_id)
        self._refuse_outcome(row)
        # c-600 review: an old review round (or the old declined-at-review) is never a plain
        # publish, which would lose the round's replies; `keel/shipupgrade.py` says what to do
        old = shipupgrade.refusal(views.attach(self, row))
        if old:
            raise Refused(old)
        if self.tracked_children(card_id):
            with self.tx():
                row = self._row(card_id)
                self._refuse_outcome(row)
                self._close_tracking(row, actor, None, kind="approve",
                                     data={"gate": "outcome", "tracking": True})
            return
        started = self.now()     # c-604: the watcher's baseline ends here, not after the publish
        published = publish(views.attach(self, row)) if publish else None
        data = {"gate": "outcome"}
        if published is not None:
            data["published"] = published
        # A publish that closes without landing says why (r-24, `merging.NOTHING_TO_LAND`).
        note = published.get("note") if isinstance(published, dict) else None
        target = "shipping" if ships(published) else "done"
        with self.tx():
            row = self._row(card_id)
            self._refuse_outcome(row)
            if target == "shipping":
                self._enter_shipping(row, heads_of(published), since=started)
                row = self._row(card_id)
            self._move(row, target, actor, {}, note, kind="approve", data=data)

    def _enter_shipping(self, row: sqlite3.Row, heads: dict | None = None, since: str | None = None) -> None:
        """The watcher's record as Approve outcome begins it (lane SHIP). Inside the move's
        own transaction, so no reader sees the card at shipping without it. `heads` is where
        the publish found each branch: his first Ship's push leases against it. `since` is
        when his Approve began, before the publish: the watcher's first look takes only
        what is no later than it as already seen (c-604)."""
        options = json.loads(row["options"] or "{}")
        shipped = dict(options.get(SHIPPING_OPTION) or {}) or {"since": since or self.now(), "round": 0}
        shipped.pop("state", None)
        if heads:
            shipped["heads"] = dict(shipped.get("heads") or {}, **heads)
        options[SHIPPING_OPTION] = shipped
        self._update(row["id"], {"options": json.dumps(options)})

    # ----- review at shipping (c-600): the house's verdicts, his Ship -----

    def verdict(self, card_id: str, data: dict, actor: str, caller_card: str | None) -> int:
        """The house's verdict on one item it was told (`keel/shipreplies.py`), recorded as a
        `verdict` event. The card's OWN house only, at shipping: a verdict carries the words
        his Ship may post, so nothing else may write one."""
        if actor != "house" or caller_card != card_id:
            raise Refused(f"a verdict on {card_id}'s review comments is {card_id}'s own house's")
        with self.tx():
            row = self._row(card_id)
            if row["stage"] != "shipping":
                raise Refused(f"{card_id} is at {row['stage']}, not shipping: verdicts answer "
                              f"review on a shipped {self.words(row['space'])['change']}")
            try:
                data = shipreplies.check(data, views.attach(self, row), self.words(row["space"]))
            except shipreplies.VerdictRefused as refused:
                raise Refused(str(refused)) from None
            said = f"{data['handle']}: {data['verdict']}" + (f", {data['summary']}" if data["summary"] else "")
            return self.record_event(card_id, "verdict", actor, text=said, data=data)

    def words(self, space: str | None) -> terms.Terms:
        """What `space` calls a ticket and a change, for a refusal's sentence."""
        found = self.terms(space) if callable(self.terms) else (self.terms or {}).get(space)
        return found or terms.BASE

    def _refuse_ship(self, row: sqlite3.Row) -> None:
        if row["stage"] != "shipping":
            raise Refused(f"{row['id']} is at {row['stage']}, not shipping: nothing to ship")
        shipped = json.loads(row["options"] or "{}").get(SHIPPING_OPTION) or {}
        if shipped.get("state") == "declined":
            raise Refused(f"{row['id']}'s {self.words(row['space'])['change']} was declined: nothing is shipped")

    def ship(self, card_id: str, actor: str, publish) -> dict:
        """His Ship (c-600): the adapter pushes the house's commits, flips a draft to ready
        and posts the replies he kept (`publish`, outside the transaction, since the adapter
        writes through `kb`), then the record keeps what was posted, so a second Ship never
        says it twice. The card stays at shipping. His alone. Nothing stands between the
        adapter's answer and this write (c-660 review): the worktrees are read again only
        after it (`shipping.after_ship`). What this write does without any git is stop saying
        the send still waits: `local.ahead` and `local.unchecked` go (`SHIP_SENDS`), since
        the send was just made, and what is known of a branch behind stays."""
        if actor != "human":
            raise Refused("ship is the human's alone (the token is missing or wrong)")
        row = self._row(card_id)
        self._refuse_ship(row)
        published = publish(views.attach(self, row))
        answer = published if isinstance(published, dict) else json.loads(published or "{}")
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            shipped = dict(options.get(SHIPPING_OPTION) or {})
            line = shipreplies.ship_line(answer, before=shipped.get("heads"))
            words = {one["handle"]: one["text"] for one in answer.get("sent") or []
                     if isinstance(one, dict) and one.get("handle")}
            posted = dict(shipped.get("posted") or {})
            posted.update({handle: shipreplies.digest(text) for handle, text in words.items()})
            shipped.update(posted=posted, shipped_at=self.now())
            heads = heads_of(answer)
            if heads:
                shipped["heads"] = dict(shipped.get("heads") or {}, **heads)   # the next lease
            if answer.get("ready"):
                shipped["facts"] = dict(shipped.get("facts") or {}, draft=False)
            if isinstance(shipped.get("local"), dict):
                shipped["local"] = {key: value for key, value in shipped["local"].items()
                                    if key not in self.SHIP_SENDS}
            options[SHIPPING_OPTION] = shipped
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "ship", actor, text=line, data=answer)
        return self.get(card_id)

    def ship_from_sync(self, card_id: str, actor: str, note: str) -> dict:
        """The shipping sync's move (SH-11, `keel/shipsync.py`): a card whose pull requests
        are all open and ready goes to `shipping` from done or from review, with a fresh
        watcher's record, in one transaction, and the stage event says `sync`. From review
        this is the one way in besides Approve outcome, and it publishes nothing: the pull
        requests are already out. Never for a card at review that already has a watcher's
        record: that is a review round (or a declined pull request) at his gate, which only
        his Approve moves on."""
        if actor not in SHIPPING_ACTORS:
            raise Refused(f"only the drain or the user moves a card to shipping, not {actor}")
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            if row["stage"] not in ("done", "review"):
                raise Refused(f"the sync moves a card to shipping from done or review ({card_id} is at {row['stage']})")
            if self.tracked_children(card_id):
                raise Refused(f"{card_id} is a tracking card; its slices carry the "
                              f"{self.words(row['space'])['changes']}")
            if row["stage"] == "review" and options.get(SHIPPING_OPTION):
                raise Refused(f"{card_id} is a review round at the user's gate; the user's Approve moves it")
            # what was collected and never told is kept across the fresh record (c-655)
            untold = (options.get(SHIPPING_OPTION) or {}).get(shipauto.UNTOLD)
            options[SHIPPING_OPTION] = {"since": self.now(), "round": 0, "synced": True,
                                        **({shipauto.UNTOLD: untold} if untold else {})}
            options.pop(REOFFER_OPTION, None)     # a fresh record: no ask from before it (c-651)
            self._update(card_id, {"options": json.dumps(options)})
            self._move(self._row(card_id), "shipping", actor, {}, note, data={"sync": True})
        return self.get(card_id)

    def reoffer(self, card_id: str, actor: str, rebase: bool = False) -> dict:
        """`kb ship <id> reoffer` (c-651, `keel/shipreoffer.py`): his ask that the drain offer
        the card's house the review it was never told, or was told and never judged (c-654),
        (and with `rebase`, its branch brought up to its base by merging it in), written as `options.reoffer` with a note saying it, in
        one transaction. Refused off shipping, on a blocked or archived card (the drain does
        not tend one), while an ask waits, and with nothing to offer: what the house is
        still on (a told batch whose own turn has not ended, `shipreoffer.held`) is not
        something to offer."""
        from keel import shipreoffer, shipreplies      # noqa: PLC0415 - small, for this one write
        if actor not in shipreoffer.REOFFER_ACTORS:
            raise Refused(f"a re-offer is the user's word alone, not {actor}'s")
        with self.tx():
            row = self._row(card_id)
            if row["stage"] != "shipping":
                raise Refused(f"{card_id} is at {row['stage']}; a re-offer is for a card at shipping")
            if row["blocked_reason"]:
                raise Refused(f"{card_id} is blocked ({row['blocked_reason']}): the drain does not tend "
                              f"it until the user unblocks it, so a re-offer would wait unseen")
            if views.archived(row):
                raise Refused(f"{card_id} is archived: the drain does not tend it, so a re-offer "
                              f"would wait unseen")
            options = json.loads(row["options"] or "{}")
            change = self.words(row["space"])["change"]
            shipped, events = options.get(SHIPPING_OPTION) or {}, self.events(card_id)
            # a batch whose own turn has not ended is the house's still (c-654 review)
            on = shipreoffer.held(shipped, events)
            left = shipreplies.unjudged({"options": options}, events, but=on)
            busy = len(shipreplies.unjudged({"options": options}, events, batch=on)) if on else 0
            why = shipreoffer.refusal(shipped, bool(options.get(REOFFER_OPTION)),
                                      rebase, change, unjudged=left, on=on, busy=busy)
            if why:
                raise Refused(f"{card_id}: {why}")
            options[REOFFER_OPTION] = shipreoffer.ask(actor, rebase, self.now())
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", actor, data={"options": {REOFFER_OPTION: options[REOFFER_OPTION]}})
            text = shipreoffer.ASKED_NOTE.format(
                change=change, rebase=", with its base merged into its branch" if rebase else "")
            self.record_event(card_id, "note", actor, text=text)
        return self.get(card_id)

    def send_back(self, card_id: str, actor: str, words: str) -> dict:
        """`kb ship <id> sendback` (c-663, `keel/shipsendback.py`): his own notes on a card
        at shipping, kept as one more entry of `options.sendback` with the handle its item
        will have, and a note carrying his words, in one transaction. The card stays at
        shipping; the drain puts the item in the batch on its next pass. His alone."""
        from keel import shipsendback      # noqa: PLC0415 - small, for this one write
        if actor not in shipsendback.ACTORS:
            raise Refused(f"a send-back at shipping is the user's word alone, not {actor}'s")
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            why = shipsendback.refusal(row["stage"], row["blocked_reason"], views.archived(row),
                                       options.get(SHIPPING_OPTION) or {}, str(words or ""),
                                       self.words(row["space"])["change"])
            if why:
                raise Refused(f"{card_id} {why}")
            asked = shipsendback.ask(actor, str(words), self.now(), shipsendback.next_handle(options))
            options[SENDBACK_OPTION] = list(options.get(SENDBACK_OPTION) or []) + [asked]
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", actor, data={"options": {SENDBACK_OPTION: options[SENDBACK_OPTION]}})
            # c-723 review r1.F5: the prepared items it answers, by the handle Answer leads with
            answers = shipsendback.answers(asked["text"], options.get(SHIPPING_OPTION) or {})
            self.record_event(card_id, "note", actor, data={"sendback": asked["handle"], "answers": answers},
                              text=shipsendback.ASKED_NOTE.format(handle=asked["handle"], words=asked["text"]))
        return self.get(card_id)

    def take_sendback(self, card_id: str, handles: list[str]) -> None:
        """The drain's take of the send-backs it put in the batch (c-663): the option is
        re-read in this transaction and only the asks with these handles leave it, so one he
        sent while the pass ran stays for the next."""
        with self.tx():
            options = json.loads(self._row(card_id)["options"] or "{}")
            asks = list(options.get(SENDBACK_OPTION) or [])
            left = [asked for asked in asks if str(asked.get("handle")) not in set(handles)]
            if len(left) == len(asks):
                return
            options[SENDBACK_OPTION] = left
            if not left:
                options.pop(SENDBACK_OPTION)
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", "drain", data={"options": {SENDBACK_OPTION: left or None}})

    # The key of `options.shipping` the drain never writes from a copy it read earlier: the
    # next Ship's lease, which only a publish and a Ship write (`Board.approve`, `Board.ship`).
    SHIPPING_NOT_THE_DRAINS = ("heads",)
    # The keys whose value is a dict other writers change entry by entry (his Ship marks
    # `facts.draft` and adds to `posted`): a step's change to one is laid over the board's
    # dict entry by entry too, never the whole dict from the step's older copy.
    SHIPPING_BY_ENTRY = ("facts", "posted")
    # The entries of `local` that say a send still waits: his Ship drops them in its own write
    # (c-660), and the next read of the worktrees (his Ship's, or the drain's) writes them again.
    SHIP_SENDS = ("ahead", "unchecked")

    def keep_shipping(self, card_id: str, before: dict | None, new: dict, actor: str = "drain",
                      unless_moved: tuple[str, ...] = ()) -> dict:
        """THE seam for a drain step's write of `options.shipping` (c-653 review, r2.F1). A
        step works on the copy it read at the start of its pass, and writing that whole copy
        back undid whatever landed meanwhile: his Ship's `posted` and its lease, a mark another
        step wrote. So the record is RE-READ in this transaction
        and only what the step itself changed between `before` and `new` is laid over it: a
        key it set or changed takes `new`'s value, a key it removed is removed, and every
        other key keeps what the board holds now (his Ship's `posted`, a mark of
        `mark_reoffer`, another step's write, a key another writer removed). `facts` and
        `posted` are laid over the same way one level down (`SHIPPING_BY_ENTRY`): a batch's
        take sets `facts.waiting` and forgets the re-told handles' entries of `posted`, and
        the draft his Ship marked ready and the replies it posted meanwhile stay. `heads` is
        never the drain's: it keeps the board's value whatever the copies say. `before` None:
        `new` is the whole record the step means, less `heads`. `unless_moved` (c-660) names
        keys whose value on the board must still be `before`'s: when one moved since the
        step's read (`shipped_at`: his Ship landed, and what the step read of the worktrees
        may be from before its push), nothing is written and the board's record is what
        comes back, for the step to go on from. The record as written."""
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            now = dict(options.get(SHIPPING_OPTION) or {})
            if before is not None and any(now.get(key) != before.get(key) for key in unless_moved):
                return now
            keys = set(new) | set(before if before is not None else now)
            changed = {}
            for key in keys - set(self.SHIPPING_NOT_THE_DRAINS):
                if before is not None and before.get(key, self) == new.get(key, self):
                    continue
                want = new.get(key, self)
                if before is not None and key in self.SHIPPING_BY_ENTRY and isinstance(want, dict):
                    want = laid_over(now.get(key), before.get(key), want)
                if want is not self and now.get(key, self) != want:
                    now[key] = changed[key] = want
                elif want is self and key in now:
                    del now[key]
                    changed[key] = None
            if changed:
                options[SHIPPING_OPTION] = now
                self._update(card_id, {"options": json.dumps(options)})
                self.record_event(card_id, "set", actor, data={"options": {SHIPPING_OPTION: changed}})
        return now

    def mark_reoffer(self, card_id: str, batch: int, fields: dict) -> bool:
        """The drain's marks on a told re-offer (`options.shipping.reoffer`, c-651): the turn
        that started it, its close, or that it is over. The record is re-read in this
        transaction and only the mark changes, so a Ship that landed while the house was
        being stopped keeps what it posted and pushed. False when the record no longer holds
        that batch's re-offer."""
        from keel import shipreoffer      # noqa: PLC0415 - a small module, for this one write
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            shipped = dict(options.get(SHIPPING_OPTION) or {})
            mark = shipped.get(shipreoffer.RECORD_KEY) or {}
            if mark.get("batch") != batch:
                return False
            shipped[shipreoffer.RECORD_KEY] = dict(mark, **fields)
            options[SHIPPING_OPTION] = shipped
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", "drain",
                              data={"options": {SHIPPING_OPTION: {shipreoffer.RECORD_KEY: shipped[shipreoffer.RECORD_KEY]}}})
        return True

    def mark_publishing(self, card_id: str, actor: str, ship: bool = False) -> str:
        """His Approve outcome (or his Ship, c-600), about to be published on another
        machine: re-check the gate and write the one-shot marker in one transaction; the
        nonce the door call carries. The event records that it was written, never the nonce."""
        if actor != "human":
            raise Refused("approve is the human's alone (the token is missing or wrong)")
        nonce = secrets.token_hex(16)
        with self.tx():
            row = self._row(card_id)
            self._refuse_ship(row) if ship else self._refuse_outcome(row)
            options = json.loads(row["options"] or "{}")
            options[PUBLISHING_OPTION] = {"digest": nonce_digest(nonce), "at": self.now()}
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", actor, data={"options": {PUBLISHING_OPTION: "marked"}})
        return nonce

    def clear_publishing(self, card_id: str, nonce: str) -> None:
        """Remove the marker this nonce wrote; a marker another tap wrote is left alone."""
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            if (options.get(PUBLISHING_OPTION) or {}).get("digest") != nonce_digest(nonce):
                return
            options.pop(PUBLISHING_OPTION)
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", "human", data={"options": {PUBLISHING_OPTION: None}})

    # ----- notes, blocks, split -----

    def note(self, card_id: str, text: str, actor: str, data: dict | None = None,
             mark: str | None = None) -> int:
        data = dict(data or {}, **MARKS[mark]) if mark else data
        if mark in HUMAN_STOP_MARKS and actor not in HUMAN_STOP_ACTORS:
            raise Refused(f"--mark {mark} records the user's tap: only the user, or the drain "
                          f"carrying it, writes one")
        if mark == "merged-end" and actor != "drain":
            raise Refused("--mark merged-end is the drain's end of a merged card's idle house")
        with self.tx():
            authority.refuse_note(self._row(card_id), actor, self.builder)
            return self.record_event(card_id, "note", actor, text=text, data=data)

    def mark(self, card_id: str, data: dict, actor: str) -> int:
        """One answer or note HE left on a plan or an outcome (`keel/planstate.py`).

        His alone, by actor: a mark is what the resume prompt quotes as his words, so a
        house writing one would be putting words in his mouth. The shape is checked by
        `planstate.check_mark` before anything is written."""
        if actor != "human":
            raise Refused("a mark is the user's answer or note on a plan: only the human leaves one")
        try:
            data = planstate.check_mark(data)
        except ValueError as error:
            raise Refused(str(error)) from None
        with self.tx():
            row = self._row(card_id)
            late = shipreplies.refuse_after_post(views.attach(self, row), data, self.words(row["space"]))
            if late:
                raise Refused(late)
            return self.record_event(card_id, "mark", actor, text=data.get("text"), data=data)

    def reply(self, card_id: str, ask: int, text: str, actor: str, caller_card: str | None) -> dict:
        """The house's answer to a question he asked on its plan (Ask, P2-9), recorded as a
        `reply` event tied to his `ask` mark, so the page pins it under the question.

        The card's OWN house only, and only to a question that is open: an answer is put
        under his question on his page, so nothing else may put one there. What it answers
        is the next open question, if there is one, which is how asks in a row queue."""
        if actor != "house" or caller_card != card_id:
            raise Refused(f"a reply to the user's question on {card_id}'s plan is {card_id}'s own house's")
        text = (text or "").strip()
        if not text:
            raise Refused("a reply says something")
        with self.tx():
            self._row(card_id)
            events = self.events(card_id)
            asked = [e for e in events if e["id"] == ask and e["kind"] == "mark"
                     and (e.get("data") or {}).get("what") == "ask"]
            if not asked:
                raise Refused(f"event {ask} on {card_id} is not a question the user asked")
            doc = asked[0]["data"].get("doc") or "plan"
            if ask not in [a["event"] for a in planstate.open_asks(events, doc)]:
                raise Refused(f"the user's question {ask} on {card_id} already has its answer")
            event = self.record_event(card_id, "reply", actor, text=text,
                                      data={"ask": ask, "doc": doc, "text": text})
            waiting = planstate.open_asks(self.events(card_id), doc)
        return {"event": event, "ask": ask, "next": waiting[0] if waiting else None}

    def block(self, card_id: str, reason: str, actor: str, mark: str | None = None,
              data: dict | None = None) -> dict:
        """`mark` says what kind of block it is (`MARKS`): the drain's failed resume, the
        review limit, a house paused on a permission prompt (`keel/permpause.py`, which wakes
        Bosun, `keel/pausewake.py`), Keel's own mechanics or a landing's refusal. `data`
        rides with the mark's own (the session a withheld fresh start is about)."""
        data = dict(MARKS[mark], **(data or {})) if mark else data
        if not reason:
            raise Refused("block needs a reason")
        with self.tx():
            self._row(card_id)
            self._update(card_id, {"blocked_reason": reason})
            self.record_event(card_id, "block", actor, text=reason, data=data)
            self._drop_reoffer(card_id, actor, "blocked")
        return self.get(card_id)

    def _drop_reoffer(self, card_id: str, actor: str, why: str) -> None:
        """His re-offer ask on a card the drain will not tend now (blocked or archived,
        c-651 review): cleared with a note, in the caller's transaction, so it never waits
        unseen and never fires long after he blocked or archived the card."""
        options = json.loads(self._row(card_id)["options"] or "{}")
        if REOFFER_OPTION not in options:
            return
        options.pop(REOFFER_OPTION)
        self._update(card_id, {"options": json.dumps(options)})
        self.record_event(card_id, "set", actor, data={"options": {REOFFER_OPTION: None}})
        self.record_event(card_id, "note", actor, text=REOFFER_DROPPED.format(why=why))

    def keep_reoffer(self, card_id: str, asked: dict, kept: dict | None) -> bool:
        """A failed look's count on his re-offer ask (`kept`, or None to clear it, c-651):
        the ask is re-read in this transaction and written only while the card is still at
        shipping with that same ask, so a block, an archive or a move while the look ran is
        never undone. False when it was not written."""
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            if row["stage"] != "shipping" or options.get(REOFFER_OPTION) != asked:
                return False
            if kept is None:
                options.pop(REOFFER_OPTION)
            else:
                options[REOFFER_OPTION] = kept
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", "drain", data={"options": {REOFFER_OPTION: kept}})
        return True

    def rereview(self, card_id: str, actor: str) -> dict:
        """His Re-review of a posted review card with new commits (lane RC, RC-5): a new
        round on the SAME card, back to `assigned` for the drain to start fresh in the review
        pool, its round counted and the new commits taken. His alone: it starts work."""
        if actor != "human":
            raise Refused("Re-review is the user's to start: only the human re-reviews a card")
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            if not options.get(REVIEW_KEY_OPTION):
                raise Refused(f"{card_id} is not a review card")
            if row["stage"] != "done" or not options.get(REVIEW_POSTED_OPTION):
                raise Refused(f"{card_id} has no posted review to follow up (it is at {row['stage']})")
            new = options.get(REVIEW_NEW_OPTION)
            if not new:
                raise Refused(f"{card_id} has no new commits since your review")
            number = int(options.get(REVIEW_ROUND_OPTION) or 1) + 1
            options.pop(REVIEW_NEW_OPTION, None)
            options[REVIEW_ROUND_OPTION] = number
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "set", actor,
                              data={"options": {REVIEW_ROUND_OPTION: number, REVIEW_NEW_OPTION: None}})
            self._move(self._row(card_id), "assigned", actor, {},
                       f"re-review, round {number}: new commits up to {str(new.get('head'))[:12]}")
        return self.get(card_id)

    def unblock(self, card_id: str, actor: str, counted: bool = True,
                expect: str | None = None, why: str | None = None) -> dict:
        """`counted=False` is a house repair by Bosun that is already recorded (`repair`);
        `expect` clears the block only while it is still that one, so a question the resumed
        house has just asked is never cleared by the answer to the last one. `why` is Bosun's
        repair (c-575): a block Keel wrote, on a card in any space. Without it Bosun lifts
        only a block on a card it builds."""
        with self.tx():
            row = self._row(card_id)
            if expect is not None and row["blocked_reason"] != expect:
                return self.get(card_id)
            if why is not None:
                self._repair(row, "unblock", actor, why)
            elif actor == authority.BOSUN and counted:
                authority.refuse_unblock(row, actor, self.builder)
            self._update(card_id, {"blocked_reason": None})
            self.record_event(card_id, "unblock", actor)
        return self.get(card_id)

    def split(self, card_id: str, slices: list[dict], actor: str) -> list[str]:
        """Create one child per slice; `after` names one earlier sibling by title, or a list
        of them, so a slice can wait for several (and, naming only earlier ones, no cycle).
        c-771: `repo` on a slice is the repos it states, its parent's or fewer (`cardspec.slice_repos`);
        a slice with none takes the parent's. One refusal files no slice."""
        if not slices:
            raise Refused("split needs at least one --slice")
        with self.tx():
            parent = self._row(card_id)
            authority.refuse_move(parent, actor, "splits", self.builder)
            ids_by_title, stacked, used = {}, [], set()
            answers = stacking.approved(json.loads(parent["options"] or "{}"))
            for piece in slices:
                after_titles = piece.get("after") or []
                after_titles = [after_titles] if isinstance(after_titles, str) else after_titles
                self._refuse_multi_after(after_titles)
                for after_title in after_titles:
                    if after_title not in ids_by_title:
                        raise Refused(f"slice {piece['title']!r} waits for unknown sibling {after_title!r}")
                # Through the resolver with the parent as the source, so a slice inherits
                # its four fields and records that it did, and a parent with no model (an
                # imported card) still hands its slices one. c-760: and the options the
                # parent stated, for the keys the space's sheet declares. c-771: its repos are
                # its own when it states them, and every rule below is asked of those.
                spec, missing = self._resolve(parent["space"], {"repo": self._slice_repos(parent, piece),
                                                                "options": piece.get("options")},
                                              source=dict(parent), parent=dict(parent))
                spec, notes = self._untaken(parent["space"], spec, piece.get("options"), dict(parent))
                # c-645 r1.F2: a slice of a house's card is a house's, and a worker a slice
                # names is checked as any card's is
                self._refuse_worker_setter(piece.get("options"), actor)
                if stacking.OPTION in (piece.get("options") or {}) and actor != "human":
                    raise Refused(f"options.{stacking.OPTION} is the owner's to set (with their token), "
                                  f"not {actor}'s")
                self._inherit_worker(spec, dict(parent))
                # c-732 r2.F1: a slice names a base only where create would let it, and
                # the browser too (c-760 r1.F10: the split asks what create asks)
                self._refuse_base(parent["space"], spec.get("repo"), spec.get("options") or {})
                self._refuse_browser(parent["space"], spec.get("repo"), spec.get("options") or {})
                self._refuse_worker({"space": parent["space"], "repo": spec.get("repo"),
                                     "options": spec.get("options") or {}})
                spec = self._slice_stack(parent, piece, spec, [ids_by_title[t] for t in after_titles],
                                         after_titles, stacked, answers, used, notes)
                child = self.insert_card(dict(
                    spec, space=parent["space"], title=piece["title"],
                    brief=piece.get("brief", ""), stage="assigned", parent=card_id,
                    after=views.after_text([ids_by_title[t] for t in after_titles])), actor)
                self._hold_left_behind(child, missing, dict(parent), actor)
                self._note_all(child, notes, actor)
                ids_by_title[piece["title"]] = child
            self._update(card_id, {})
            self.record_event(card_id, "split", actor, data={"children": list(ids_by_title.values())})
            unmatched = [title for title in answers if title not in used]
            if unmatched:          # r2.F1: an approved answer no slice took is said, never dropped
                stacked.append("approved but matched no slice: " + ", ".join(f"'{t}'" for t in unmatched))
            held, already = self._block_stacked_on(card_id, actor)
            if held:
                stacked.append("blocked, as they were stacked on this card: " + ", ".join(held))
            if already:
                stacked.append("stacked on this card and already blocked for another reason, so not "
                               "blocked again (they need a new parent too): " + ", ".join(already))
            if stacked:
                self.record_event(card_id, "note", actor, text="stacking at the split: " + "; ".join(stacked))
        return list(ids_by_title.values())

    # ----- claims -----

    def claim(self, card_id: str, host: str, actor: str) -> dict:
        """Take a startable card for the drain on `host`, in one transaction.

        Claiming a card already claimed is a no-op, so a drain whose reply was lost can
        simply ask again; who starts it is settled under the card's lock (`house.launch`).
        Keel runs on one machine, so a claim under another host name (the retired box, or
        this machine before a rename) is this machine's: it is taken over under `host`
        (c-622 r1.F1). The claim stays on the card after the house starts; a stage move
        back to `assigned` clears it.
        """
        if not host:
            raise Refused("claim needs a host")
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            held = options.get(CLAIM_OPTION) or {}
            if held.get("host") == host:
                return views.attach(self, row)
            if held:
                options[CLAIM_OPTION] = {"host": host, "at": held.get("at") or self.now()}
                self._update(card_id, {"options": json.dumps(options)})
                self.record_event(card_id, "claim", actor, text=host,
                                  data={"host": host, "from": held.get("host")})
                return views.attach(self, self._row(card_id))
            if not views.startable(self, row, bool(self.tracked_children(card_id))):
                raise Refused(f"{card_id} is not startable (assigned, unblocked, unarchived, "
                              f"not tracking, its `after` at review or done)")
            options[CLAIM_OPTION] = {"host": host, "at": self.now()}
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "claim", actor, text=host, data={"host": host})
        return self.get(card_id)

    def release(self, card_id: str, actor: str, host: str | None = None) -> dict:
        """Hand a claim back. A drain releases only its own host's claim; the human may
        release any, which is how a card claimed by a machine that went away is freed."""
        with self.tx():
            row = self._row(card_id)
            options = json.loads(row["options"] or "{}")
            held = options.get(CLAIM_OPTION)
            if not held:
                return views.attach(self, row)
            if actor != "human" and host is not None and held.get("host") != host:
                raise Refused(f"{card_id} is claimed by {held.get('host')}, not {host}; "
                              f"only that host or the human releases it")
            options.pop(CLAIM_OPTION)
            self._update(card_id, {"options": json.dumps(options)})
            self.record_event(card_id, "claim", actor, text=f"released {held.get('host')}",
                              data={"released": held.get("host")})
        return self.get(card_id)

    # ----- relays: his tap on a house, recorded for this machine's drain to carry -----

    def relay(self, card_id: str, what: str, actor: str, to: str | None,
              prompt: str | None = None, sha: str | None = None, gate: bool = False,
              held: bool = False, bulk: bool = False) -> dict:
        """Record the human's tap for the drain on `to` to carry: resume the house (with
        `prompt`), stop it, or start the card. The event is the whole mechanism: pending is
        a relay no `carried` names (`pending_relays`), so there is no queue to agree with."""
        with self.tx():
            self._relay(self._row(card_id), what, actor, to, prompt, sha, gate=gate, held=held,
                        bulk=bulk)
        return self.get(card_id)

    def _relay(self, row: sqlite3.Row, what: str, actor: str, to: str | None,
               prompt: str | None, sha: str | None = None, approval: dict | None = None,
               gate: bool = False, held: bool = False, bulk: bool = False) -> int:
        """`gate`: the tap answers a gate (Approve, Send back), so its words mean something
        only at the stage it left the card at, which is recorded (c-604 review: a comment or
        an Ask is information at any stage and is told wherever the card now is). `held`:
        the deck held it for a house it saw working (`actions.hold_here`). `bulk`: one of a
        pass over many cards (`kb relay --bulk`), carried like any other and never his own
        action on this card (`views.his_action`, c-673)."""
        # Every relay is his tap but one: a `land` is Bosun's as its checked outcome approval
        # (`approval`, c-526). Its house repairs relay nothing: every house is here (c-648).
        bosun_may = what == "land" and approval is not None
        if not (actor == "human" or (actor == authority.BOSUN and bosun_may)):
            raise Refused("a relay is the human's tap (the token is missing or wrong)")
        if what not in RELAY_WHATS:
            raise Refused(f"a relay is one of {', '.join(RELAY_WHATS)}, not {what!r}")
        if not to:
            raise Refused("a relay needs the host it is for (--to)")
        needs = SWITCHED_RELAYS.get(what)
        if needs and needs not in self.switches:
            raise Refused(f"a {what} relay needs [keel] {needs} = true, and it is off")
        if what == "land":
            self._refuse_land(row)
            if not sha:
                raise Refused("a land relay pins the branch sha the user approved (--sha)")
        # The session it was tapped for: a relay whose card has moved on to another session
        # is superseded rather than carried (`drain.carry_relays`).
        # And, for a gate's tap, the stage the card is at once its move is made (the row is
        # read again: an Approve plan moved it to building in this transaction), so it is
        # refused with a note when carried after the card moved on, never acted on stale (c-604).
        data = {"what": what, "to": to, "session": row["session_id"]}
        if gate:
            data["stage"] = self._row(row["id"])["stage"]
        if held:
            data["held"] = True
        if bulk:
            data.update(views.BULK_DATA)
        if prompt:
            data["prompt"] = prompt
        if sha:
            data["sha"] = sha
        if approval is not None:
            data["approval"] = approval
        return self.record_event(row["id"], "relay", actor, text=what, data=data)

    def _refuse_land(self, row: sqlite3.Row) -> None:
        """A `land` relay is Approve outcome carried to the machine that holds the worktree
        (`keel/landing.py`): only at review, and one at a time. Never for a tracking card:
        it lands nothing, since each slice landed on its own (lane X). Never for a proposal
        (c-667): a landing would close it with its draft unwritten."""
        self._refuse_outcome(row)
        if proposals_of(row["options"]):
            raise Refused(PROPOSAL_CLOSES.format(card=row["id"]))
        if self.tracked_children(row["id"]):
            raise Refused(f"{row['id']} is a tracking card; it lands nothing (each slice "
                          f"landed on its own), so Approve outcome closes it in the tap")
        if row["blocked_reason"]:
            raise Refused(f"{row['id']} is blocked; unblock it before approving its outcome")
        if any(relay["what"] == "land" for relay in self.pending_relays(row["id"])):
            raise Refused(f"{row['id']} is already queued to land")
        landing = (json.loads(row["options"] or "{}").get("landing") or {})
        if landing.get("state") == "testing":
            raise Refused(f"{row['id']} is landing already (on {landing.get('host')})")

    def land(self, card_id: str, relay_id: int, actor: str, published: str | None = None,
             merge_queue: bool = False, verify=None) -> dict:
        """Finish an Approve outcome a drain carried (`keel/landing.py`): the card to done,
        recorded as the approve it is, naming the relay that asked for it.

        FACTS, not options (lane E review round 3, finding 4): the relay must be the human's
        (or Bosun's checked outcome approval, c-526), a `land`, and taken; the card at review and not blocked; the sha the relay PINNED
        must equal the worker's `options.landing.sha` for that relay; and `verify(card, sha)`
        (git, on this machine) must say that sha is in the repo's target branch. With no
        verifier, or the queue switched off, it refuses. A same-user shell cannot be kept out
        of the board entirely, but "done with nothing merged" needs git to agree."""
        if not merge_queue:
            raise Refused("the merge queue is switched off ([keel] merge_queue = false); nothing lands through it")
        if actor != "drain":
            raise Refused("a landing is finished by the drain that carried it (--actor drain)")
        if verify is None:
            raise Refused("a landing is finished only where the merge can be verified")
        row = self._row(card_id)
        pinned = self._taken_land_sha(card_id, relay_id)
        landing = json.loads(row["options"] or "{}").get(LANDING_OPTION) or {}
        if (landing.get("relay") != relay_id or landing.get("state") != "landed"
                or landing.get("sha") != pinned):
            raise Refused(f"{card_id} has no landed record for relay {relay_id} naming the sha the user "
                          f"approved; one relay, one outcome")
        why = verify(views.attach(self, row), pinned)
        if why:
            raise Refused(f"{card_id} is not landed: {why}")
        with self.tx():
            row = self._row(card_id)
            self._refuse_outcome(row)
            if row["blocked_reason"]:
                raise Refused(f"{card_id} is blocked; a blocked card does not land")
            data = {"gate": "outcome", "relay": relay_id, "sha": pinned}
            if published is not None:
                data["published"] = published
            self._move(row, "done", actor, {}, None, kind="approve", data=data)
        return self.get(card_id)

    def _taken_land_sha(self, card_id: str, relay_id: int) -> str:
        """The sha a taken `land` relay pinned, his tap's or Bosun's checked approval's (c-526);
        Refused when there is none."""
        relay = self.conn.execute(
            "SELECT actor, data FROM events WHERE id = ? AND card = ? AND kind = 'relay' "
            "AND json_extract(data, '$.what') = 'land' AND (actor = 'human' OR (actor = 'bosun' "
            "AND json_extract(data, '$.approval') IS NOT NULL))", (relay_id, card_id)).fetchone()
        taken = self.conn.execute(
            "SELECT 1 FROM events WHERE card = ? AND kind = 'carried' "
            "AND json_extract(data, '$.relay') = ? AND json_extract(data, '$.outcome') = 'taken'",
            (card_id, relay_id)).fetchone()
        sha = json.loads(relay["data"] or "{}").get("sha") if relay else None
        if relay is None or taken is None or not sha:
            raise Refused(f"{card_id} has no land relay {relay_id} a drain has taken")
        return sha

    def pending_relays(self, card_id: str) -> list[dict]:
        """The card's relays that no `carried` event names yet, oldest first."""
        rows = self.conn.execute(
            "SELECT * FROM events AS r WHERE r.card = ? AND r.kind = 'relay' AND NOT EXISTS "
            "(SELECT 1 FROM events AS c WHERE c.card = r.card AND c.kind = 'carried' "
            "AND json_extract(c.data, '$.relay') = r.id) ORDER BY r.id", (card_id,))
        return [views.relay_dict(views.event_dict(row)) for row in rows]

    def carry(self, card_id: str, relay_id: int, actor: str, outcome: str = "taken",
              why: str | None = None) -> dict:
        """Mark a relay carried, BEFORE the drain acts on it (as a claim comes before a
        start), so it is carried at most once even by two drains or a drain that dies
        mid-way. `superseded` answers one the drain will not act on, with the reason."""
        if actor != "drain":
            raise Refused("a relay is carried by a drain (--actor drain)")
        if outcome not in CARRY_OUTCOMES:
            raise Refused(f"carried takes one of {', '.join(CARRY_OUTCOMES)}")
        with self.tx():
            self._row(card_id)
            found = self.conn.execute("SELECT id FROM events WHERE id = ? AND card = ? AND kind = 'relay'",
                                      (relay_id, card_id)).fetchone()
            if found is None:
                raise Refused(f"{card_id} has no relay {relay_id}")
            if not any(relay["id"] == relay_id for relay in self.pending_relays(card_id)):
                raise Refused(f"relay {relay_id} on {card_id} was already carried")
            self.record_event(card_id, "carried", actor, text=why or outcome,
                              data={"relay": relay_id, "outcome": outcome})
        return self.get(card_id)

    # ----- the voice hold -----

    def hold_voice(self, card_id: str, seconds: int, stopped: bool | None = None,
                   turns: int | None = None) -> dict:
        """Take or refresh the hold: voice is talking to this house, so nothing automatic
        moves it until `until` passes or it is released.

        `stopped` records whether the connected turn is the one that stopped the house's
        process, and it decides the release: a house voice put down is woken again, a house
        that was already down (a tracking card the drain retired, a done card, a house the
        drain had not put back yet) is LEFT down, because waking it would only give the drain
        something to retire on its next pass.

        One event, when the hold is TAKEN (none was there): a re-offered batch reads it as his
        own turn in the board's order (c-651 review, `shipreoffer.batch_turn`). None on a
        refresh: the hold is refreshed on every turn of a conversation and a per-turn event
        would bury the record it is there to keep. What the card records is the exchange
        itself, and one note when the conversation starts and ends (`keel/converse.py`).
        """
        now = datetime.now().astimezone()
        with self.tx():
            row = self._row(card_id)
            held = dict(json.loads(row["options"] or "{}").get(VOICE_HOLD_OPTION) or {})
            taken = not held
            held["until"] = (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")
            held.setdefault("at", now.isoformat(timespec="seconds"))
            if stopped is not None:
                held.setdefault("stopped", stopped)
            if turns is not None:
                held["turns"] = turns
            self._update(card_id, {"options": json.dumps(
                merge_options(json.loads(row["options"]), {VOICE_HOLD_OPTION: held}))})
            if taken:
                self.record_event(card_id, "set", "voice", data={"options": {VOICE_HOLD_OPTION: held}})
        return self.get(card_id)

    def release_voice(self, card_id: str) -> dict:
        """Let the house go. Returns the card as it is afterwards; the hold it carried is
        `voice_hold_of` before this, which is what the caller needs to decide about waking."""
        with self.tx():
            row = self._row(card_id)
            self._update(card_id, {"options": json.dumps(
                merge_options(json.loads(row["options"]), {VOICE_HOLD_OPTION: None}))})
        return self.get(card_id)

    def voice_hold_of(self, card_id: str) -> dict | None:
        """The card's live hold, or None. Every reader asks this or `views.voice_hold`."""
        row = self._row(card_id)
        return views.voice_hold(json.loads(row["options"] or "{}"))

    # Bosun's voice hold (c-523): the one row of `holds`, `keel/bosunhold.py`.
    def bosun_hold(self) -> dict | None:
        from keel import bosunhold
        return bosunhold.live(self)

    def bosun_hold_expired(self) -> dict | None:
        from keel import bosunhold
        return bosunhold.expired(self)

    def bosun_hold_state(self) -> dict:
        """Both readings at once, `kb console held`'s payload: {hold, expired}."""
        return {"hold": self.bosun_hold(), "expired": self.bosun_hold_expired()}

    def hold_bosun(self, actor: str, seconds: int, stopped: bool | None = None,
                   turns: int | None = None) -> dict:
        from keel import bosunhold
        return bosunhold.take(self, actor, seconds, stopped=stopped, turns=turns)

    def release_bosun(self, actor: str) -> dict | None:
        from keel import bosunhold
        return bosunhold.release(self, actor)

    # ----- sessions and hooks -----

    def set_session(self, card_id: str, session_id: str, actor: str,
                    transcript_path: str | None = None, bg_id: str | None = None,
                    app_link: str | None = None, expect: str | None = None) -> dict:
        """Record the session the harness minted for this card's house, and the claude.ai
        link it is reachable at (`options.app_link`), in the one `session` event."""
        if not session_id:
            raise Refused("session needs --set <uuid>")
        data = {"session_id": session_id, "transcript_path": transcript_path, "bg_id": bg_id}
        if app_link:
            data["app_link"] = app_link
        with self.tx():
            row = self._row(card_id)
            if expect is not None and row["session_id"] != expect:
                # Compare-and-swap (`keel/rotate.py`): only while the card is still on the
                # session the caller started from.
                raise Refused(f"{card_id} is on session {str(row['session_id'])[:8]} now, not "
                              f"{expect[:8]}; the new session is not recorded")
            update = {"session_id": session_id}
            if app_link:
                update["options"] = json.dumps(
                    merge_options(json.loads(row["options"]), {"app_link": app_link}))
            self._update(card_id, update)
            self.record_event(card_id, "session", actor, data=data)
        return self.get(card_id)

    def record_resume(self, card_id: str, actor: str, prompt: str, result: dict,
                      app_link: str | None = None) -> dict:
        """Record that the card's house was resumed with `prompt`, and the session the resume
        minted when it is a new one. The `resume` event is the drain's once-only mark
        (`drain.reconcile`), so it is written first and on its own."""
        with self.tx():
            self._row(card_id)
            self.record_event(card_id, "resume", actor, text=prompt, data=dict(result))
        session_id = result.get("session_id")
        if session_id and session_id != self.get(card_id)["session_id"]:
            return self.set_session(card_id, session_id, actor, bg_id=result.get("bg_id"),
                                    app_link=app_link)
        return self.get(card_id)

    def record_hook(self, card_id: str, hook_name: str, payload: dict | None,
                    extra: dict | None = None) -> int:
        payload = payload or {}
        data = {"hook": hook_name, "session_id": payload.get("session_id"),
                "transcript_path": payload.get("transcript_path"), "payload": payload}
        data.update(extra or {})
        text = (payload or {}).get("reason")
        with self.tx():
            self._row(card_id)
            return self.record_event(card_id, "hook", "hook", text=text, data=data)

    def stop_blocks(self, card_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE card = ? AND kind = 'hook' "
            "AND json_extract(data, '$.stop_blocked') = 1", (card_id,)).fetchone()
        return row[0]

    def drop_of(self, row: sqlite3.Row) -> str | None:
        """The card's `options.drop`: the one file an ask card's house is asked to write."""
        return json.loads(row["options"] or "{}").get(DROP_OPTION) or None

    def file_drop(self, card_id: str, payload: dict | None, drop: str) -> bool:
        """Stage an ask card to `review` with its drop as the output, on the house's behalf.

        The finishing step must never need a tool the house does not have. An ask card's
        house is confined to the tools its `worker.md` names (the daybook's are `Read,Write`,
        with no shell at all), and the brief used to end by asking it for a `kb stage` it
        could not run: c-270 wrote its drop correctly on 2026-09-18, was nudged twice for
        the command it had no Bash for, and blocked. The drop on disk IS the finish, so the
        hook files it and nobody is asked for a command.
        """
        try:
            self.stage(card_id, "review", "hook", output_ref=drop, note=FILED_NOTE)
        except Refused as why:
            self.note(card_id, f"the drop is written but this card could not be filed: {why}", "hook")
            return False
        self.record_hook(card_id, "Stop", payload, {"filed_drop": drop})
        return True

    def stop_reason(self, card_id: str, drop: str | None, problem: str | None) -> str:
        """The nudge. A card with a drop is asked for the FILE and never for a command:
        the house that writes a drop usually has no shell to run one in."""
        if drop:
            return (f"Card {card_id} is still at building and its drop is not ready ({problem}). "
                    f"Write it to {drop} and end your turn. Keel reads the drop when your turn "
                    f"ends and files the card itself, so there is no command for you to run.")
        return (f"Card {card_id} is still at building. Finish the work, then "
                f"`kb stage {card_id} review --output <ref>`, or `kb block {card_id} \"<what you need>\"`.")

    def held_tap(self, card_id: str, session: str | None = None) -> dict | None:
        """His tap waiting for this house's turn to end (a `resume` or `stop` relay the drain
        held while the house worked, c-598), or None. While one waits, no Stop rule sends the
        house back: the turn ends, the Stop's kick carries his tap, and his words reach the
        house before anything of the hook's (c-604: the nudge at building sent a house on
        without his Approve's prompt, which then arrived 97 s later at review)."""
        row = self._row(card_id)
        if session and session != row["session_id"]:
            return None                   # a superseded session's Stop: not this house's turn
        claim = json.loads(row["options"] or "{}").get(CLAIM_OPTION)
        host = claim.get("host") if isinstance(claim, dict) else None
        return views.held_tap(self.pending_relays(card_id), row["session_id"], host)

    def stop_check(self, card_id: str, payload: dict | None) -> dict | None:
        """The Stop hook: file an ask card whose drop is written, else send the house back
        while it is still at building, twice. Never while his tap waits (`held_tap`)."""
        row = self._row(card_id)
        if views.voice_hold(json.loads(row["options"] or "{}")):
            # Guard 3. A connected turn fires this hook like any other (probed 2026-09-20),
            # and the nudge below does not merely cost one of the two tries: a `block`
            # decision sends the house back to WORK, in the middle of a sentence he is
            # waiting on. A held card is his; the hook is recorded and nothing else.
            self.record_hook(card_id, "Stop", payload, {"voice_hold": True})
            return None
        if row["stage"] != "building" or row["blocked_reason"]:
            self.record_hook(card_id, "Stop", payload)
            return None
        if views.rotating(json.loads(row["options"] or "{}")):
            # The checkpoint turn of a rotation (`keel/rotate.py`) ends here on purpose: the
            # fresh session carries the work on, so a nudge would undo the one thing asked.
            self.record_hook(card_id, "Stop", payload, {"rotating": True})
            return None
        if self.tracked_children(card_id):
            # A tracking card's stage follows its children and `kb stage` refuses it, so
            # there is nothing this house could do with a nudge. c-292 was sent back at
            # `building` until its budget ran out for exactly that reason (2026-09-19).
            self.record_hook(card_id, "Stop", payload, {"tracking": True})
            return None
        if running_background_tasks(payload):
            # A turn that ends while its own subagent or background shell is still running
            # is a WAIT, not a stop: the harness re-invokes the session when that work
            # hands back. Nudging here made the first real work card (c-260, 2026-09-16)
            # spend its whole budget while a review subagent was still working.
            self.record_hook(card_id, "Stop", payload, {"waiting_on_background": True})
            return None
        drop = self.drop_of(row)
        problem = drop_problem(drop) if drop else None
        if drop and problem is None and self.file_drop(card_id, payload, drop):
            return None
        tap = self.held_tap(card_id, (payload or {}).get("session_id"))
        if tap is not None:
            # c-604: his tap waits for this turn to end; the nudge (and its budget's block)
            # would send the house on without it. Only the nudge yields: the rest ran above.
            self.record_hook(card_id, "Stop", payload, {"tap_waiting": tap["id"]})
            return None
        blocks = self.stop_blocks(card_id)
        if blocks >= STOP_BLOCK_BUDGET:
            self.record_hook(card_id, "Stop", payload)
            self.block(card_id, f"{STOP_CHECK_TEXT}{blocks} nudges", "hook", mark="stop-check")
            return None
        reason = self.stop_reason(card_id, drop, problem or "it could not be filed")
        self.record_hook(card_id, "Stop", payload, {"stop_blocked": True, "reason": reason})
        return {"decision": "block", "reason": reason}


def refuse_open_slices(row: sqlite3.Row, new_stage: str, slices: list) -> None:
    """A tracking card reaches `new_stage` (review, or done by its close) only when every
    slice is done; the refusal names the ones that are not."""
    if not views.all_done(slices):
        left = ", ".join(s["id"] for s in slices if s["stage"] != "done")
        raise Refused(f"{row['id']} is a tracking card; it comes to {new_stage} only when every "
                      f"slice is done ({left} not yet)")


def open_board(cfg) -> Board:
    """The board, opened with the config's `[keel]` switches and card defaults. Every
    construction from a config goes through this: a Board opened without them has builder
    mode, the merge queue, rotation and `after=a,b` all off, so the deck's POST paths once
    ran every action as if none were set (c-591 review)."""
    from keel import builder, repocommands     # noqa: PLC0415 - they read the config, which the board need not
    board = Board(cfg.db_path, backlog_days=cfg.backlog_days, defaults=cardspec.defaults_from(cfg),
                  switches=cfg.switches, integrated=cfg.integrated, builds=builder.repos(cfg),
                  terms=lambda space: terms.of(cfg, space), ship_idle_hours=cfg.ship_idle_hours,
                  drain_paused=cfg.drain_paused,
                  cards_dir=cfg.cards_dir,
                  ship_auto=lambda space: shipauto.of_space(cfg.spaces.get(space)),
                  stacks=cfg.stacking)
    # asked with the board itself: whether the file is the adopted text is one query on it (F3)
    board.run_rule = lambda space, repo: repocommands.runs(cfg, space, repo, board)
    return board
