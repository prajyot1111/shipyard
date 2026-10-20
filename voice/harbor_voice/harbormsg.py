"""How a turn reaches Harbor, and how Harbor's answer comes back.

TWO DIRECTIONS, AND THEY ARE DELIBERATELY NOT SYMMETRICAL.

OUT: one headless turn in a persistent voice conversation under the talker's rules,
`claude -p --resume <uuid> --output-format json`, run with the talker's config dir. Not
a pane, not a second delivery path, and not the phone session either: it is its own
conversation with the same rulebook, the same denies and the same memory, and a separate
history. It is created on first use with a fresh uuid and that uuid is the whole record
of it (`state/voice-session`); deleting that file starts a fresh conversation.

IN: a file, the same one as before. The answer is the `result` field of that JSON, and
the thread that ran the turn writes it into the `say` inbox, which is exactly where the
pane-era Harbor used to write it. So `Dispatcher._watch` (the narrated wait, the barge-in
screen, the give-up promise) did not have to change at all.

THREE FILES, NOT ONE, AND IT MATTERS WHICH COMMAND WRITES WHICH. `say` (SAY_DIR) is the
answer channel: the watch loop in dispatcher.py ends the turn the moment it reads a line
out of it. `progress` (PROGRESS_DIR) narrates the wait without ever ending the turn, and
`opening` (OPENING_DIR) speaks once, immediately, and also never ends the turn. All three
are kept and none of them changed. The Harbor tier no longer feeds the last two, because
a `-p` turn has one output and the framing below asks for that one output rather than for
a running commentary; the gateway's own filler and narration cover the wait instead. The
inboxes stay because they are the gateway's input surface, not the pane era's leftovers:
`bin/keel-voice say` still works and the dispatcher still drains all three per turn.

WHY NOT SCRAPE ANYTHING. Same reason as before, and now it is structural rather than a
rule: there is nothing to scrape. `--output-format json` hands back one field, and what
is in that field is what is spoken.

A FAILURE SAYS WHY, IN THE LOG, AND IT SAYS IT IN CLAUDE'S OWN WORDS. The spoken sentence
is fixed and it has to be: he is not going to be read an exit code. But the reason used
to stop there, and voice's first night was three failed turns with nothing written down.
Every failed turn now writes the conversation it addressed, the command shape, and the
turn's own stderr into state/logs/voice.log. See `report_failure`.

A FAILURE MID-TURN IS SPOKEN, ONCE. `send` returns as soon as the turn has STARTED, not
when it is answered, so a turn that dies twenty seconds later cannot come back through
the return value. It writes its own spoken line into the `say` inbox instead, which is
the one channel the dispatcher is already watching, and the cause goes to the log.

THE USER SPEAKING IS THE INTENT TO SPEND. A human-initiated action may start or spend a
session, and nothing automated may. Voice is human-initiated end to end, and nothing in
this file is reachable except from a turn he started.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import capture, config, drawing, stamps

# `drawing` has put this package's own checkout on the path.
from keel.childenv import own_env                                      # noqa: E402
from keel import configpath, logins, refresh                           # noqa: E402

# Where the launchd agent's stdout and stderr are pointed, and so where anyone
# looking into "voice said it could not reach Harbor" will look first.
LOG = config.STATE / "logs" / "voice.log"

# Where `keel-voice say` leaves a line, and where the gateway watches. A directory
# rather than one file so two lines in quick succession cannot overwrite each other, and
# under the segment's own data/ because that is the gateway's whole writable surface.
SAY_DIR = config.DATA / "say"

# Where `keel-voice progress` leaves a line: narration DURING the wait, never the
# answer. A separate directory from SAY_DIR on purpose, so the two can never be
# confused by the same inbox: a progress line arriving in the say inbox would finish
# the turn early, and an answer arriving in the progress inbox would never finish it
# at all.
PROGRESS_DIR = config.DATA / "progress"

# Where `keel-voice opening` leaves a line: the pre-work line the per-turn framing
# asks for, spoken once, right away, and it can never finish the turn either. A THIRD
# directory rather than reusing SAY_DIR or PROGRESS_DIR, and for the reason named above:
# `say` finishes the turn on its first line, and the opener is not that line. It is also
# not a `progress` line: `progress` is gated on a silence timer and a shared repeat
# budget, and it is guarded for shape only, because it narrates from the live state
# document. The opener is composed by Harbor itself before any of that exists, so it is
# spoken unconditionally, the same way the final answer is.
OPENING_DIR = config.DATA / "opening"

# THE PER-TURN FRAMING. It rides in the message rather than living in the talker's
# CLAUDE.md, and the probe proved that works: the framing arrives with the thing it
# governs, every time, which a standing memory does not (tried before this change, and
# the transcript shows it did not hold turn to turn).
#
# IT IS THREE LINES NOW, AND THAT IS THE WHOLE OF THE CUTOVER'S EFFECT ON IT. The old
# framing was a page long because the pane era gave Harbor three channels to write to
# and a judgement to make about which one to open on. A `-p` turn has ONE output, so
# there is nothing left to instruct: no opener to run, no progress line to leave, no
# `say` to end the turn with. What remains is the only thing that was ever about the
# audio itself, which is that the reply is read out loud.
#
# THE COMMAND SENTENCE IS THE 70 PERCENT (<install>/history/docs/voice-two-modes.md, 1.1 item 7). Most
# converse turns are commands rather than questions, and a command answered with a
# preamble is a 30 second turn where a 10 second one would do.
#
# THE EGRESS SPLIT IS IN HERE RATHER THAN RECALLED (2026-09-18, decision V17). Every
# spoken sentence is sent to Google to be voiced, so the rule is real; it was written as
# one flat ban on work identifiers, and a flat ban makes a DIRECT ANSWER to a question he
# asked out loud unanswerable. The split is by whether he asked: unprompted speech stays
# clean, an answer may name what the question named. A turn must not have to remember a
# memory file to get that right, so the two sentences ride in the framing.
#
# THE REPO SENTENCE RIDES HERE TOO (2026-09-19). "Card it" in conversation files a card
# from this turn, and a card with no repo is an errand with no worktree, so a code card
# filed without one cannot build: c-296, c-297 and c-298 were all filed that way in one
# day. The choices are read with `kb repos` rather than recited, and an unclear repo is a
# question asked out loud rather than a guess, because his answer is one more converse
# turn and a wrong repo is a card that has to be filed again.
#
# ANSWER FIRST, LOOK SECOND (2026-09-24, lane H, H1). Measured on the box that morning: the
# model answers in 1 to 5 s even with 160k cached tokens, and a trivial turn is 5 s of wall
# time, but the turns where Harbor reached for tools (grepping the Atlas, `kb`, reading its
# memory files) took 18 to 80 s, for questions the digest attached to the turn already
# answered. So the turn answers from what it was given, looks only when that cannot answer or
# he asked it to look, and then says one short line before it does, so he is not left in
# silence. It is prose, so it is also measured: each turn's `harbor-model` stamp records the
# envelope's tool count (`harbor_voice/stamps.py`), and `keel voice latency` splits Harbor's
# turns into tool-free and with tools.
FRAMING = ("This is a VOICE turn and your reply is read aloud, so answer in one to three "
           "plain spoken sentences, no markdown, no lists, no paths. Lead with what "
           "the user can act on. Answer from the digest and what you know; use a tool only "
           "when those cannot answer or you are asked to look, and say one short line "
           "first (\"Let me check the board.\"). "
           "If it needs the deck, say so once. For a command, do it, then "
           "say what changed in one sentence, with the card id. "
           "A card that changes code carries `--repo <key>`. If their words do not "
           "settle it, file the card in the inbox without one and ask them which, naming "
           "keys from `kb repos`; their answer ends in `kb set <id> repo=<key>`. "
           "Speaking is egress, so nothing UNPROMPTED (narration, an aside, a filler, a "
           "give-up line) carries a work identifier, a ticket number or a customer name. "
           "A DIRECT ANSWER to what they just asked may name what they asked about "
           "(a pull request title, a story id, a card title), because it is their phone "
           "on their tailnet; customer names and credentials stay out of speech either way.")

# THE ONE SENTENCE THAT TRIMS THE PER-TURN BOARD BOOT, and it lives here rather than in
# the talker's rulebook on purpose: the rulebook is shared with the phone session, where
# "boot from the board" is right because a Remote Control turn has all the time it wants.
# A voice turn does not. The digest below is `index.as_json` of the warm snapshot, which
# is names, ids, states and counts and never a body, and it is already warm, so attaching
# it costs the turn nothing and saves it the two `kb` reads that were the first two tool
# calls of every turn.
#
# IT IS A DIGEST OF THE DECK NOW (decision V16), BOTH SPACES, and the note says so
# because the previous wording is what the failure was made of: told it had "a board
# digest", a turn asked about the deck's PR Review screen concluded the screen was
# somewhere else and said it could not reach the work side, while the rows were in the
# state document on this machine the whole time. `keel deck <section>` is the lookup for
# anything the digest only sampled, and reading the deck is not a work tool.
DIGEST_NOTE = ("A digest of the DECK is attached, both spaces, {age} seconds old, read "
               "from the {source}; answer from it and do not run `kb list`. Each section "
               "carries its real count beside a capped sample of rows, so count from the "
               "count. For anything on a deck screen (reviews, a card in either space, "
               "a segment, Bosun; a pull request is on its card), run `keel deck <section>`; "
               "`kb show <id>` for a card "
               "the user names; `kb needs-you` only if they ask what is waiting on them.")


# THE CONNECT DIRECTIVE, AND IT RIDES HERE BECAUSE THE KEY IS PER TURN (c-419). His
# words: "oftentimes I won't be knowing the house number, so I will be relying on the model
# to tell me". The exact-phrase table plus an id is the floor and it still matches first;
# this is the sentence the table cannot parse, and the answer to it comes back naming one
# card and carrying a directive the gateway reads in code (`verbs.connect_directive`).
#
# THE KEY IS IN THE EXAMPLE, NOT ONLY IN THE RULE, so the token to copy is in front of the
# model rather than assembled by it. It is this turn's and no other's: a directive quoted
# out of an earlier answer, or invented, carries the wrong key and pins nothing.
#
# IT TELLS HARBOR NOT TO SAY "CONNECTING", because the gateway says it: line 1 of the heard
# handoff is a pre-rendered clip and it is the only line that can promise to land at once
# (`corpus.CONNECTING`, and the Atlas page's "The handoff is heard").
#
# AND IT SAYS A HOUSE NEED NOT BE RUNNING. A session absent from `claude agents` is a house
# that is DOWN, which is the easy case for a connected turn and the usual one (see
# `keel/converse.py`, `busy_row`). A model that believed otherwise would refuse on his
# behalf, out loud, for a reason that is not true.
CONNECT_NOTE = (
    "If the user is asking to be put through to a house and the digest settles which card, say "
    "which card in one short spoken sentence, naming its id and a few words of its title "
    "(\"That's card 317, the narration one.\"), and end your reply with "
    "`<<keel-connect c-317 {key}>>` alone on the last line, the id being the card you "
    "picked and {key} exactly as written here. Do not say \"connecting\": the gateway says "
    "that. One card only, and only when the user asked to be put through. If two cards could "
    "be it, ask them which, naming both ids and titles, and emit no directive. A house does "
    "not need to be running to be connected to. Bosun is put through the same way, "
    "`<<keel-connect bosun {key}>>`, when the user asks to talk to Bosun itself.")


# BOSUN, BY VOICE (c-523, BO-5): what Harbor may do for Bosun inside a turn, and the answer
# directive's key, which rides here for the connect's reason (it is this turn's and no
# other's). The answer is RECORDED BY THE PAGE, never by Harbor or the gateway: the page is
# him on the deck, and a model never picks for him, so the directive is written only after
# he has heard the options and said yes to his pick said back.
BOSUN_NOTE = (
    "Bosun, in its words: a problem the user wants Bosun to have is filed with `kb --actor voice "
    "console ask \"<one short line>\" --detail \"<their words, verbatim>\"` (with `--card "
    "c-NNN` when it is about a card), and you say the `say` line it prints (\"Filed with "
    "Bosun as request 23.\"). The digest's `bosun` section is its state and its open asks; "
    "say \"Bosun has a question for you\" when the user asks what waits. To answer an ask by "
    "voice: read the user its options when they have not heard them, never pick for them, "
    "say their pick back with the ask's id and wait for their yes; on that yes end your reply "
    "with `<<keel-answer a-31 A {key}>>` alone on the last line, their letter, and say the "
    "pick is being recorded, not that it is done. An answer in their own words instead of an "
    "option is not recorded by voice: tell them to give it on the Console or in Bosun's chat.")


# HIS SENTENCE ARRIVES WHOLE, AND THIS NUMBER USED TO BE 160.
#
# THE BUG IT CAUSED, reproduced from his own transcript before it was touched. On
# 2026-09-04 he asked a 294 character question. The speech model got every character of
# it and the transcript records all 294. This constant was applied one screen below as a
# bare slice, so 134 of them were thrown away here, and Harbor answered "your message cut
# off at spawn a session on the work, so I did not get the actual ask." That is the whole
# defect: the product refused to work on a long question, and the only thing anywhere
# that noticed was Harbor GUESSING, because the sentence happened to stop mid-word.
#
# IT WAS NEVER LOAD-BEARING, AND THE COMMENT THAT USED TO BE HERE SAID SO. It read: the
# tag, the utterance and the framing exceed harbor-message's 240 character inline limit
# even for a short turn, "so a spoken turn always travels as a POINTER to a file in
# ledger/messages and it is the pointer sentence, not this, that is typed. The cap is
# still the thing that keeps that file's first line readable and the log record honest."
# Both halves of that are true and the conclusion does not follow. What is typed into the
# pane is a path; the body harbor-message writes beside it has no length limit of any
# kind. So the only thing this bought was a tidier first line in a file nobody reads, and
# it paid for it with the second half of his question, silently: no marker in the pane,
# no line in the log, nothing in the transcript.
#
# WHAT IS LEFT IS A SANITY BOUND, and it is deliberately far past anything a person says
# out loud: 4000 characters is about five minutes of continuous speech at 150 words a
# minute, and a push-to-talk turn that long means something upstream is wrong rather than
# that he was talkative. Crossing it is not silent either, which is the actual rule this
# file got wrong. See `send`: the delivered line says the sentence was cut and by how
# much, so Harbor answers the question it can see and knows it is not the whole one.
UTTERANCE_MAX = 4000

# The antecedent's own budget, separate from the utterance's so a long one can never eat
# the sentence he actually said. A whole spoken turn travels as a pointer to a file in
# ledger/messages rather than being typed inline, so this bounds the file's first line
# and the log record rather than the pane.
CONTEXT_MAX = 220


# ONE CONVERSATION, ONE TRANSCRIPT, ONE TURN IN FLIGHT. Until 2026-09-17 `server.on_text`
# spawned a thread per utterance and `send` a worker per turn, with no lock anywhere
# between them: two `-p --resume` runs on the same conversation, racing, and whichever
# finished last wrote the transcript. The lock is taken by the worker around the whole
# turn (the session read included), so a second utterance WAITS.
#
# AND AT MOST ONE WAITING. A third utterance is answered with the fixed line rather than
# queued: a queue would answer him about something he said a minute ago, out of order,
# and he is one person with one mouth.
_TURN_LOCK = threading.Lock()
_SLOT_LOCK = threading.Lock()
_in_flight = 0

# AND ONE TURN ACROSS PROCESSES (c-422, C3 of 2026-09-23). `_TURN_LOCK` is a threading
# lock, so it serialised the gateway's own threads and nothing else: `keel-voice ask`, run
# by the deck for a question typed on one of Harbor's boards, is another process with its
# own copy of it, and could run a second `claude -p --resume` on this one transcript while a
# spoken turn was running. The conversation's turn now also holds an `flock` on this file,
# taken by the gateway's worker and by the typed ask alike. `flock` is per open file
# description, so it serialises processes on one host, and the kernel drops it when a
# holder dies, so a crashed ask cannot wedge the voice.
TURN_LOCK_FILE = config.DATA / "harbor-turn.lock"
LOCK_POLL = 0.1
# The gateway's own turn records, where a typed ask writes its one line too.
TRANSCRIPT = config.DATA / "transcript.jsonl"
# WHAT A TYPED ASK HEARS WHEN A TURN IS ALREADY RUNNING. It is refused rather than queued:
# the page is holding a turn id, and Harbor is one conversation.
BUSY_TYPED = "Harbor is answering something else right now; ask again in a moment."


# THE WORST A TYPED ASK CAN TAKE, which the deck's wait must stay above (review F3): the
# turn under one deadline, the board pushes under one budget, and the command's own start
# and the session read around them.
TYPED_START_MARGIN = 15.0
TYPED_WORST = config.HARBOR_TURN_TIMEOUT + drawing.PUSH_BUDGET + TYPED_START_MARGIN
# WHAT THE SPOKEN PATH SAYS WHEN A TYPED QUESTION HOLDS THE CONVERSATION (review F4): at
# once, rather than a silence while it waits, and its own sentence if the wait runs out.
TYPED_FIRST = "Harbor is finishing a typed question first."
# NEUTRAL ON PURPOSE (follow-up N3): the holder may be a typed ask, a refine or another
# spoken turn, and the wait that ran out does not know which.
BUSY_SPOKEN = "Harbor was still busy with something else, so say that again in a moment."


class TurnBusy(Exception):
    """Another turn holds the conversation, in this process or another one."""


def acquire_turn(wait: float = 0.0):
    """Hold Harbor's conversation for one turn: this process's lock, then the file lock.
    Returns the open lock file, which `release_turn` gives back.

    `wait` is how long to wait for BOTH, in seconds, from one deadline (review F4): 0
    answers busy at once (the typed ask, the refine), and the gateway's worker waits the
    length of one turn, because whatever holds it is itself bounded by the same timeout.
    Raises `TurnBusy` when the wait runs out, holding nothing.
    """
    deadline = time.monotonic() + max(0.0, wait)
    if not (_TURN_LOCK.acquire(blocking=False) if wait <= 0
            else _TURN_LOCK.acquire(timeout=max(0.0, deadline - time.monotonic()))):
        raise TurnBusy("a turn is running in this process")
    handle = None
    try:
        TURN_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        handle = TURN_LOCK_FILE.open("a")
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return handle
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TurnBusy("a turn is running in another process") from None
                time.sleep(LOCK_POLL)
    except BaseException:
        if handle is not None:
            handle.close()
        _TURN_LOCK.release()
        raise


def held_elsewhere() -> bool:
    """Does ANOTHER process hold the conversation right now: a non-blocking probe.

    Only asked when this process's own lock is free, because a probe on a second open file
    description would also collide with this process's own holder.
    """
    if _TURN_LOCK.locked():
        return False
    try:
        with TURN_LOCK_FILE.open("a") as probe:
            fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
    except BlockingIOError:
        return True
    except OSError:
        return False
    return False


def release_turn(handle) -> None:
    """Give the conversation back: closing the file drops the flock with it."""
    try:
        handle.close()
    finally:
        _TURN_LOCK.release()


@contextlib.contextmanager
def conversation_turn(wait: float = 0.0):
    """`acquire_turn` and `release_turn` around one block."""
    handle = acquire_turn(wait)
    try:
        yield
    finally:
        release_turn(handle)


# WHAT `send` RETURNS WHEN THERE IS NO SLOT. A sentinel rather than a sentence, because
# the sentence he hears is the dispatcher's (NARRATION["busy"]) and there must be exactly
# one copy of it.
BUSY = "busy"


def take_slot() -> bool:
    """One running plus `HARBOR_TURN_QUEUE_MAX` waiting, and no more."""
    global _in_flight
    with _SLOT_LOCK:
        if _in_flight > config.HARBOR_TURN_QUEUE_MAX:
            return False
        _in_flight += 1
        return True


def release_slot() -> None:
    global _in_flight
    with _SLOT_LOCK:
        _in_flight = max(0, _in_flight - 1)


def in_flight() -> int:
    with _SLOT_LOCK:
        return _in_flight


def turn_running() -> bool:
    """Whether a turn in THIS process holds the conversation (a spoken turn or a refine)."""
    return _TURN_LOCK.locked()


def build_line(text: str, ante: str = "", digest: str = "", age: float | None = None,
               handover: str = "", source: str = "deck", connect_key: str = "") -> str:
    """The one line a turn travels as.

    THE `[voice]` TAG AND THE `--` SEPARATOR ARE KEPT. The transcript keys on them, and
    anything reading a turn back out of the log finds the boundary where it expects it.

    THE DIGEST GOES UNDER THE FRAMING, NOT INSIDE IT, so the sentence he is answered
    from and the record it is answered out of stay separately readable in the log.

    `source` IS SAID OUT LOUD IN THE NOTE, "deck" or "board". A digest built from the
    board alone has no provider rows and no segments, and a turn told it has the deck
    when it has the board would answer "there are no reviews" about a screen full of
    them. Saying which record it holds is the difference between an honest gap and a
    confident wrong answer.
    """
    parts = [FRAMING]
    if handover:
        parts.insert(0, handover)
    # THE CONNECT DIRECTIVE'S KEY, WHEN THE CALLER MINTED ONE (c-419). No key, no block:
    # a turn that cannot be pinned is never told how to ask for a pin.
    if connect_key:
        parts.append(CONNECT_NOTE.format(key=connect_key))
        parts.append(BOSUN_NOTE.format(key=connect_key))
    if digest:
        parts.append(DIGEST_NOTE.format(age=int(age if age is not None else 0),
                                        source=source or "board"))
    line = f"[voice] {text} -- {' '.join(parts)}"
    if ante:
        line = f"[voice] {text} -- (context: {ante}) {' '.join(parts)}"
    if digest:
        line += f"\n\nDeck digest:\n{digest}" if source == "deck" else f"\n\nBoard digest:\n{digest}"
    return line


def read_session() -> dict:
    """The voice conversation's record: `{uuid, turns, started_at}`.

    ITS WHOLE RECORD IS STILL ONE FILE. No second store, no row on the board, nothing to
    keep in agreement with anything: `state/voice-session.json` holds the uuid, how many
    turns it has answered and when it started, and deleting it starts a fresh
    conversation.

    THE OLD FILE IS MIGRATED IN PLACE, ONCE. Until 2026-09-17 this was a bare uuid in
    `state/voice-session`; a live conversation must not be thrown away by an upgrade, so
    the uuid is carried into the new record (with `turns` at 0 and `started_at` now,
    which is the honest reading: nothing local knows either) and the old file is removed
    so nothing can read it back as authoritative.
    """
    path = config.VOICE_SESSION_FILE
    try:
        if path.exists():
            rec = json.loads(path.read_text() or "{}")
            if isinstance(rec, dict) and rec.get("uuid"):
                kept = {"uuid": str(rec["uuid"]),
                        "turns": int(rec.get("turns") or 0),
                        "started_at": float(rec.get("started_at") or time.time())}
                if rec.get("memory"):
                    kept["memory"] = str(rec["memory"])
                return kept
    except Exception:                                                   # noqa: BLE001
        # A RECORD THAT CANNOT BE READ IS A FRESH CONVERSATION, not a crash. The cost is
        # one lost history; the cost of raising here is every turn failing identically
        # until somebody deletes a file by hand.
        pass
    old = config.VOICE_SESSION_LEGACY
    try:
        if old.exists() and old.read_text().strip():
            rec = {"uuid": old.read_text().strip(), "turns": 0,
                   "started_at": time.time()}
            write_session(rec)
            old.unlink(missing_ok=True)
            log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: the session file moved to "
                f"{path.name}, carrying conversation {rec['uuid'][:8]} with it.")
            return rec
    except Exception:                                                   # noqa: BLE001
        pass
    return {}


def write_session(rec: dict) -> None:
    path = config.VOICE_SESSION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1) + "\n")


def last_said(limit: int = 3) -> list[str]:
    """The last few things he actually said, for the handover line. From the transcript,
    which is the only record of a conversation this process keeps."""
    path = config.DATA / "transcript.jsonl"
    try:
        rows = path.read_text().splitlines()[-400:]
    except Exception:                                                   # noqa: BLE001
        return []
    out: list[str] = []
    for line in reversed(rows):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("kind") != "said":
            continue
        said = " ".join(str(rec.get("said") or "").split())[:80]
        if said and said not in out:
            out.append(said)
        if len(out) >= limit:
            break
    return list(reversed(out))


def memory_stamp() -> str | None:
    """Harbor's memory and rulebook as committed (`keel/refresh.py`): the install's memory
    repo once it holds the memory (c-722), else main's; None when unknown."""
    return refresh.memory_stamp(config.KEEL_HOME, configpath.install_of(config.KEEL_TOML, config.KEEL_HOME))


def rotation_due(rec: dict, memory: str | None = None) -> str:
    """Why this conversation should be retired, or "" to keep it.

    EVERY `-p --resume` RE-READS THE WHOLE TRANSCRIPT, so latency grows with age and
    nothing resets it. Two bounds rather than one: turns, because a long conversation is
    usually a busy day, and age, because a thin one left open for a week is still an
    expensive prefix to re-read.

    AND HARBOR'S MEMORY MOVING UNDER IT (r-14, c-538). A conversation keeps the memory it
    started with: c-523 taught Harbor to connect to Bosun and a conversation from that
    morning said "connecting only works for cards" that evening. `memory` is the stamp
    main has now; the record's is the one it started on. A record from before the stamp,
    or a stamp that cannot be read, is not a change.
    """
    if not rec.get("uuid"):
        return ""
    if memory and rec.get("memory") and rec["memory"] != memory:
        return "Harbor's memory changed"
    if int(rec.get("turns") or 0) >= config.VOICE_SESSION_MAX_TURNS:
        return f"{rec['turns']} turns"
    age = time.time() - float(rec.get("started_at") or time.time())
    if age >= config.VOICE_SESSION_MAX_AGE:
        return f"{age / 3600:.0f} hours old"
    return ""


def open_session(for_memory: bool = False) -> tuple[str, bool, str]:
    """(uuid, existed, handover). The conversation this turn belongs to.

    ROTATION IS A NEW UUID AND A ONE LINE HANDOVER, never a silent break. The new
    conversation is told what the last one was about, in his own words from the
    transcript, so the first turn after a rotation is not a stranger.

    A MEMORY CHANGE RETIRES IT ONLY WHEN `for_memory` SAYS SO, and only the spoken turn
    says so (`send`): that runs at the start of a Harbor turn, under the conversation's
    turn lock, before the turn is sent, and the dispatcher routes a spoken sentence to
    Harbor only when voice holds no house (its pinned branch takes it). A typed ask from
    the deck, a refine or a hand-run turn comes from elsewhere and may arrive during a
    voice hold, so it never retires the conversation for memory (review r1.F1); the next
    spoken turn does. Turns and age still retire it on any path.
    """
    rec = read_session()
    handover = ""
    memory = memory_stamp()
    why = rotation_due(rec, memory if for_memory else None)
    if rec.get("uuid") and not why:
        if memory and not rec.get("memory"):
            # A record from before the stamp takes the one main has now: no rotation.
            write_session(dict(rec, memory=memory))
        return rec["uuid"], True, ""
    if why:
        recent = last_said()
        handover = ("This is a NEW conversation" + (
            "; the last one was about: " + "; ".join(recent) + "."
            if recent else "."))
        log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: rotating the voice "
            f"conversation ({why}). {rec.get('uuid', '')[:8]} is retired and the next "
            f"turn starts a fresh one.")
    fresh = {"uuid": str(uuid.uuid4()), "turns": 0, "started_at": time.time()}
    if memory:
        fresh["memory"] = memory
    write_session(fresh)
    return fresh["uuid"], False, handover


def count_turn() -> None:
    """One more turn on this conversation's record. Best effort: a counter that raises
    would turn an answered turn into a failed one, and the bound it feeds is a latency
    bound, not a correctness one."""
    try:
        rec = read_session()
        if rec.get("uuid"):
            rec["turns"] = int(rec.get("turns") or 0) + 1
            write_session(rec)
    except Exception:                                                   # noqa: BLE001
        pass


def voice_session() -> tuple[str, bool]:
    """(uuid, existed), for the callers that do not care about the handover line."""
    session, existed, _handover = open_session()
    return session, existed


def target_session() -> str:
    """What the log names as the destination: the voice conversation's uuid."""
    return voice_session()[0]


def pane_state(session: str) -> str:
    """There is no pane. Kept as a name so nothing that reads a destination's state has
    to grow a new branch, and it answers `unknown` because that is the truth: a headless
    turn is either running or finished, and neither is a state this can observe from
    outside. dispatcher.py no longer calls it (the "blocked" narration it fed was an
    observation about a tmux pane and there is no tmux here); `report_failure` does not
    either. It stays for one reason only, which is that deleting a public name from this
    module is a separate change from repointing it."""
    return "unknown"


def turn_command(line: str, session: str = "", existed: bool | None = None,
                 model: str | None = None) -> list[str]:
    """The argv for one headless turn. `--session-id` the first time, `--resume` after.

    `--model` is always named: `model` when the caller has its own (the refine), else the
    conversation's (`config.CONVERSE_MODEL`), never the account's default.

    THE FLAG IS DECIDED BY WHETHER THE FILE EXISTED, not by trying `--resume` and
    falling back: a fallback would make a lost session file silently start a second
    conversation and keep answering, which is the shape of drift this setup refuses.

    THE PAIR IS PASSED IN, AND THAT IS NOT TIDINESS. `voice_session()` MINTS on its first
    call, so calling it twice in one turn means the second call sees a file that the
    first one just wrote and says the conversation already existed. The very first turn
    would then be `--resume <a uuid nothing has ever created>`, which is exactly the turn
    that has to work. `send` reads the pair once and hands it down; the default here mints
    or reads it for a caller who has neither (the verification one-liner in
    <install>/history/docs/voice-repoint.md, and anything else that runs a turn by hand).
    """
    if existed is None:
        session, existed = voice_session()
    flag = "--resume" if existed else "--session-id"
    return ["claude", "-p", flag, session, "--output-format", "json",
            "--permission-mode", "auto", "--model", model or config.CONVERSE_MODEL, line]


# WHAT THE HARNESS SAYS WHEN THE CONVERSATION NAMED IN THE SESSION FILE IS NOT THERE.
# Recorded rather than guessed, run for real on 2026-09-17 against Claude Code 2.1.274:
#
#     $ claude -p --resume <a uuid nothing created> --output-format json ...
#     No conversation found with session ID: <uuid>          (on stderr, exit 1)
#
# Matched on the phrase rather than on the exit code, which is 1 for every other kind of
# refusal too.
LOST_CONVERSATION = "no conversation found with session id"


def run_turn(line: str, timeout: float, session: str = "",
             existed: bool | None = None, model: str | None = None,
             env_extra: dict | None = None, flags: tuple = (),
             structured: bool = False, clock: dict | None = None):
    """One headless turn in the voice conversation; returns Harbor's answer, RAW.

    `clock`, WHEN GIVEN, IS FILLED IN AS THE TURN GOES (lane H, H2): `spawnAt` as the
    `claude` is started, then `doneAt` and the `envelope`'s own count of what the turn did
    (`stamps.envelope`) once it has answered. The caller writes them as `harbor-*` stamps,
    so `keel voice latency` can split process start and tools from the model's own time.

    RAW, WITH ITS NEWLINES, because `draw_and_say` below has to find a fenced block in it
    and a block whose newlines have gone is no longer a block. The collapse to one spoken
    line happens there instead, on what is left after any block has been lifted out.

    CLAUDE_CONFIG_DIR IS SET HERE AND NOWHERE ELSE, per turn. The gateway's own process
    keeps no config dir, so nothing else it ever runs can accidentally inherit the
    talker's rules, memory or credentials.
    """
    # Never his token (c-451): `own_env` drops what no child may inherit.
    env = {**own_env(), "CLAUDE_CONFIG_DIR": str(config.TALKER_CONFIG_DIR),
           "KEEL_HOME": str(config.KEEL_HOME), "HARBOR_DISPATCH_ID": "",
           **(env_extra or {})}
    # `flags` GO AFTER THE LINE (the refine's scope): a variadic flag such as `--tools`
    # before it would take the line as one more value.
    argv = [*turn_command(line, session, existed, model), *flags]
    # ONE DEADLINE FOR THE WHOLE TURN, the retry below included (review F3): two full
    # timeouts back to back would outlast every wait that was sized against one.
    deadline = time.monotonic() + timeout
    clock = {} if clock is None else clock
    clock["spawnAt"] = time.time()
    done = subprocess.run(argv, capture_output=True,
                          text=True, timeout=timeout, cwd=str(config.TALKER_CWD), env=env)
    if (done.returncode != 0 and existed is not False
            and LOST_CONVERSATION in (done.stderr or "").lower()):
        # THE SESSION FILE OUTLIVED THE CONVERSATION IT NAMES, and without this every
        # turn from here on fails identically, forever, until somebody deletes one file
        # by hand. That is a real state: a config dir rebuilt, a transcript pruned, or a
        # uuid minted by a run that then failed before the conversation existed (which is
        # how this was found, fifteen minutes after the code was written).
        #
        # IT STARTS THE CONVERSATION THE FILE ALREADY NAMES, which is why this is not the
        # "try resume and fall back" the plan refused. A fallback to a FRESH uuid would
        # quietly leave two conversations and a file naming neither. This uses the same
        # id, so the file stays authoritative and there is still exactly one voice
        # conversation; what is lost is the history that was already gone.
        log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: the voice conversation "
            f"{session} is not in {config.TALKER_CONFIG_DIR}, so this turn re-creates "
            f"it under the same id. Its earlier history is gone.")
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired("claude -p", timeout)
        clock["retried"] = True
        done = subprocess.run([*turn_command(line, session, False, model), *flags],
                              capture_output=True,
                              text=True, timeout=left, cwd=str(config.TALKER_CWD),
                              env=env)
    if done.returncode != 0:
        # ITS OWN LAST LINE, which is where a refusal explains itself. The whole of
        # stderr goes to the log through `report_failure`; this is the sentence that
        # travels back as the reason.
        said = (done.stderr or done.stdout or "").strip().splitlines()
        raise RuntimeError(said[-1] if said else f"the turn exited {done.returncode}")
    try:
        payload = json.loads(done.stdout)
    except ValueError as exc:
        raise RuntimeError(f"the turn answered something that is not JSON: {exc}") from exc
    clock["doneAt"] = time.time()
    clock["envelope"] = stamps.envelope(payload)
    if payload.get("is_error"):
        raise RuntimeError(str(payload.get("result") or "the turn errored"))
    if structured:
        # `--json-schema`'s answer (2.1.281, tests/fixtures/harness/README.md): an object
        # in `structured_output`, or None when the envelope carries none.
        found = payload.get("structured_output")
        return found if isinstance(found, dict) else None
    return str(payload.get("result") or "")


# HARBOR DRAWS THE WAY A HOUSE DOES (2026-09-21, c-302). A house answering by voice writes
# its board ops in a fenced block whose language is `board` and Keel pushes them as the
# fence closes; Harbor's answers come back through here instead, and until this call
# existed such a block was read as a code block and thrown away. Asked out loud to draw,
# Harbor filed a CARD asking somebody else to do it. The reading is the house's own
# (`keel/boardpen.py`, through `voice/harbor_voice/drawing.py`), so there is one rule about
# what a block is and one sentence standing in for it.
#
# NEVER FATAL. A board that will not take a block is not a lost turn: the answer is spoken
# either way and the reason goes to the log, which is the same bargain every other side
# effect in this file keeps.
def draw_and_say(raw: str, turn: str = "") -> str:
    """Harbor's answer with anything it drew lifted out of it, ready to be spoken."""
    try:
        said, drew = drawing.lift(raw, log=log, turn=turn)
        if drew:
            log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: Harbor drew {drew} "
                f"block(s) on its own board from that answer.")
        return said
    except Exception as exc:                                            # noqa: BLE001
        log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: a board block in Harbor's "
            f"answer could not be drawn ({exc.__class__.__name__}: {exc}); the answer is "
            f"spoken as it stands.")
        return " ".join(str(raw or "").split())


def log(text: str) -> None:
    """One record into the gateway's log, wherever that actually is.

    Under launchd, stderr IS state/logs/voice.log, so writing to both would double every
    line. Run by hand it is a terminal, and the log is still where the next person will
    look, so it wants both. Comparing the inode settles which of the two this is instead
    of guessing from an environment variable, and a log that cannot be written is never
    allowed to cost the turn.
    """
    try:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    except Exception:                                                   # noqa: BLE001
        pass
    # EVERY FAILURE HERE IS SWALLOWED, and `Exception` rather than `OSError` because the
    # first thing this touches is not a file operation. `sys.stderr.fileno()` raises
    # ValueError on a closed stream and io.UnsupportedOperation on one with no real
    # descriptor, neither of which is an OSError, and this is called from the delivery
    # path with nothing above it to catch: a log that raises would turn a failed turn
    # into a crashed one, which is the single thing a log must never do.
    try:
        here = os.fstat(sys.stderr.fileno())
        there = LOG.stat()
        if (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino):
            return
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(text + "\n")
    except Exception:                                                   # noqa: BLE001
        pass


def report_failure(session: str, line: str, why: str,
                   returncode: int | None = None,
                   stderr: str = "", stdout: str = "") -> None:
    """Say WHY a turn did not reach Harbor, in the place somebody will look.

    THE SPOKEN SENTENCE IS FOR HIM AND THIS IS FOR WHOEVER FIXES IT, and until this
    existed there was only the first. Voice shipped, every Harbor-tier turn came back "I
    could not get that through to Harbor", and the reason went nowhere: not the log, not
    the transcript. The tool had said so on its own stderr, in one sentence, every single
    time.

    THE COLUMNS FOLLOWED THE ROUTE. They used to name a tmux session and what that pane
    was doing, which were the two facts the pane era could get wrong. There is no pane
    now, so the record carries what CAN go wrong instead: which conversation was
    addressed, the command shape that addressed it, the config dir it ran under, and the
    turn's own words.
    """
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    rows = [f"[{stamp}] voice: a turn did NOT reach Harbor.",
            f"    target      the voice conversation {session!r}",
            f"    command     claude -p --resume <session> --output-format json",
            f"    config dir  {config.TALKER_CONFIG_DIR}",
            f"    working in  {config.TALKER_CWD}",
            f"    what        {why}"]
    if returncode is not None:
        rows.append(f"    exit        {returncode}")
    for name, blob in (("stderr", stderr), ("stdout", stdout)):
        for i, said in enumerate((blob or "").strip().splitlines()):
            rows.append(f"    {name if i == 0 else '':<11} {said}")
    rows.append(f"    sent        {len(line)} characters: {line[:120]!r}")
    log("\n".join(rows))
    # A lost login marks the talker dir's Logins row at once (c-558), so the deck turns
    # amber on this turn rather than on the next scheduled check.
    logins.saw_at(config.STATE, config.TALKER_CONFIG_DIR,
                  "\n".join((why, stderr or "", stdout or "")))


def send(utterance: str, context: str = "", timeout: float = 60.0,
         digest: str = "", age: float | None = None, source: str = "deck",
         turn_id: str = "", connect_key: str = "") -> tuple[bool, str]:
    """Put one spoken turn to the voice conversation. (accepted, what happened).

    ACCEPTED MEANS STARTED, NOT ANSWERED. The turn runs on a thread and the answer lands
    in the `say` inbox when the model returns, which is exactly where the pane-era Harbor
    used to write it, so Dispatcher._watch narrates the wait and speaks the answer
    unchanged. A failure to START is reported here, in the return value, and the
    dispatcher speaks its one fixed sentence. A failure MID-TURN cannot come back this
    way, so it is written to the inbox as a spoken failure line, once, and to the log
    with the cause.

    WHY THIS RETURNS IN ABOUT 50 MS AND WHY THAT MATTERS. The filler is only ever spoken
    about a wait that is real, and its trigger is this function returning True. Starting
    a thread is not a claim that the model answered, it is a claim that the turn is
    running, which is the same claim the pane era's verified delivery made.

    `context` IS ONE LINE OF ANTECEDENT AND NOTHING ELSE. A fast-tier answer never
    reaches this conversation, so a follow-up to one arrives as a bare pronoun with
    nothing before it: "and how long has that one been going". The dispatcher supplies
    the previous exchange only when the fast tier answered it (see
    Dispatcher._antecedent), so this never repeats something Harbor already said.

    IT IS CLIPPED SEPARATELY from the utterance, deliberately. Clipping the pair together
    would let a long antecedent eat the sentence he actually spoke, which is the one part
    of this line that must arrive whole.

    `timeout` IS THE OLD CALLERS' ARGUMENT AND IT IS NOT THE TURN'S. Starting a thread
    cannot time out; the turn itself is bounded by config.HARBOR_TURN_TIMEOUT, which is
    the number that was measured against a real model turn. The parameter is kept so
    every existing caller still type-checks and reads the same.
    """
    spoken = " ".join(str(utterance or "").split())
    if not spoken:
        return False, "nothing was said"
    # NOTHING IS DROPPED WITHOUT SAYING SO, which is the rule the 160 character cap
    # broke. Past the sanity bound the line carries its own damage report, so Harbor is
    # told the sentence is incomplete rather than left to infer it from where it stops,
    # and the log carries the same fact for whoever is reading it afterwards.
    text = spoken
    if len(spoken) > UTTERANCE_MAX:
        lost = len(spoken) - UTTERANCE_MAX
        text = (spoken[:UTTERANCE_MAX]
                + f" [cut here: {lost} more characters were spoken and did not survive "
                  "the gateway, so ask the user for the rest]")
        log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: an utterance of "
            f"{len(spoken)} characters was cut to {UTTERANCE_MAX} on the way to Harbor, "
            f"and the delivered line says so.")
    ante = " ".join(str(context or "").split())[:CONTEXT_MAX]
    if not take_slot():
        # THE THIRD UTTERANCE IS ANSWERED, NOT QUEUED. One conversation, one transcript,
        # one turn in flight and at most one waiting: past that, a queue would answer
        # him about something he said a minute ago, out of order, which is worse than
        # being told to wait.
        return False, BUSY

    def worker():
        session = "(unopened)"
        line = ""
        try:
            # THE LOCK IS TAKEN AROUND THE WHOLE TURN, and the session is read inside it.
            # Two `-p --resume` runs on one transcript race each other, and the pair
            # (uuid, existed) decides `--session-id` against `--resume`: read outside the
            # lock, a second turn starting while the first is still creating the
            # conversation would try to create it again. Capture never takes this lock,
            # because it has no model turn to serialise.
            with conversation_turn(wait=config.HARBOR_TURN_TIMEOUT):
                session, existed, handover = open_session(for_memory=True)
                # THE LAST DRAWING'S REPORT, when it did not land (C1): read once and
                # framed with the turn, so Harbor can draw it again correctly.
                handover = " ".join(part for part in (handover, drawing.carried_report())
                                    if part)
                line = build_line(text, ante, digest, age, handover, source,
                                  connect_key)
                if config.HARBOR_KEPT_ALIVE:
                    answer = kept_alive_turn(line, session, existed, turn_id)
                else:
                    answer = one_shot_turn(line, session, existed, turn_id)
                count_turn()
        except TurnBusy as busy:
            report_failure(session, line, f"the conversation stayed busy: {busy}")
            answer = BUSY_SPOKEN
        except subprocess.TimeoutExpired:
            report_failure(session, line,
                           f"the turn did not finish within "
                           f"{config.HARBOR_TURN_TIMEOUT:.0f}s")
            answer = "I did not get an answer back in time."
        except Exception as exc:                                        # noqa: BLE001
            report_failure(session, line, f"{exc.__class__.__name__}: {exc}")
            answer = "I could not get that to Harbor."
        finally:
            release_slot()
        # ALWAYS ONE LINE INTO THE INBOX, on every path. The watch loop ends a turn on a
        # line in the say inbox and on nothing else, so a worker that returned quietly
        # would leave the turn running until the gateway's own give-up mark, with a
        # cause written nowhere he can hear.
        # STAMPED WITH THE TURN IT ANSWERS, so the watch loop that is waiting for THIS
        # answer is the one that claims it. See SayInbox.claim.
        SayInbox(SAY_DIR).write(answer or "Harbor had nothing to say.", turn=turn_id,
                                boards=drawing.drawn_for(turn_id))

    if held_elsewhere():
        # A TYPED QUESTION HOLDS THE CONVERSATION (review F4): said on the PROGRESS channel,
        # keyed to this turn, so the wait behind it is not a silence. Not the opening
        # channel (follow-up N2): that is claimed once per turn, and this line would take
        # the place of Harbor's own opener.
        SayInbox(PROGRESS_DIR).write(TYPED_FIRST, turn=turn_id)
    threading.Thread(target=worker, name="voice-turn", daemon=True).start()
    return True, ("turn started" if in_flight() == 1 else
                  "turn queued behind the one still running")


def one_shot_turn(line: str, session: str, existed: bool, turn_id: str,
                  timeout: float | None = None) -> str:
    """Harbor's turn as one `claude -p`, stamped (H2): the answer as `draw_and_say` returns
    it. The stamps are written whether or not the turn answered, as far as it got."""
    clock: dict = {}
    try:
        raw = run_turn(line, config.HARBOR_TURN_TIMEOUT if timeout is None else timeout,
                       session, existed, clock=clock)
        answer = draw_and_say(raw, turn=turn_id)
        clock["penAt"] = time.time()
        return answer
    finally:
        stamps.record(TRANSCRIPT, turn_id, clock)


def kept_alive_turn(line: str, session: str, existed: bool, turn_id: str) -> str:
    """Harbor's turn down the kept-alive, streamed process (R2, `harborlive.py`), with the
    conversation lock already held by the caller. Its answer, as `draw_and_say` returns one.

    V12-3's FALLBACK: a process that would not open or died before any part was left is
    run one-shot instead, silently; one that died after a part was spoken is not asked
    again, and the turn ends on `harborlive.BROKE_OFF`. An overrun raises as a one-shot
    does. Imported here, not at the top, so the flag off loads nothing new.
    """
    from . import harborlive
    started = time.monotonic()
    turns = int(read_session().get("turns") or 0)
    try:
        read = harborlive.LIVE.turn(line, session, existed, turns, turn_id, PROGRESS_DIR,
                                    config.HARBOR_TURN_TIMEOUT, log)
        clock = dict(read.get("clock") or {})
        clock["penAt"] = clock.get("penAt") or time.time()
        stamps.record(TRANSCRIPT, turn_id, clock)
        return read["said"]
    except harborlive.LiveError as error:
        log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: the kept-alive Harbor turn "
            f"failed ({error}); " + ("it had started speaking, so it is not asked again."
                                     if error.spoke else "falling back to a one-shot turn."))
        if error.spoke:
            return harborlive.BROKE_OFF
    # ONE DEADLINE FOR THE TURN (review F3): the fallback gets what is left of it.
    left = config.HARBOR_TURN_TIMEOUT - (time.monotonic() - started)
    if left <= 0:
        raise subprocess.TimeoutExpired("claude -p", config.HARBOR_TURN_TIMEOUT)
    return one_shot_turn(line, session, True, turn_id, timeout=left)


def run_turn_now(text: str, context: str = "", source: str = "deck",
                 turn_id: str = "") -> dict:
    """One turn in the voice conversation, IN THE FOREGROUND: the answer, or why not.

    THE TYPED ASK (c-422). `send` starts a turn on a daemon thread and returns, which is
    right inside the gateway and fatal in a command that exits straight afterwards: the
    thread died with it, mid `claude -p`. This runs the same turn inline, under the same
    conversation lock (without waiting: a busy conversation is answered, not queued), and
    returns only when the turn is over, with what Harbor said and how many blocks it drew.
    It speaks nothing: the answer goes back to whoever asked, and the transcript keeps it.
    """
    spoken = " ".join(str(text or "").split())[:UTTERANCE_MAX]
    if not spoken:
        return {"ok": False, "busy": False, "answer": "nothing was asked", "drew": 0}
    turn_id = turn_id or uuid.uuid4().hex[:12]
    ante = " ".join(str(context or "").split())[:CONTEXT_MAX]
    session, line = "(unopened)", ""
    try:
        with conversation_turn(wait=0):
            session, existed, handover = open_session()
            handover = " ".join(part for part in (handover, drawing.carried_report()) if part)
            line = build_line(spoken, ante, "", None, handover, source)
            raw = run_turn(line, config.HARBOR_TURN_TIMEOUT, session, existed)
            read = drawing.read_answer(raw, log=log, turn=turn_id)
            answer, drew = read["said"], read["drew"]
            count_turn()
    except TurnBusy:
        typed_record(turn_id, spoken, "", source, busy=True)
        return {"ok": False, "busy": True, "answer": BUSY_TYPED, "drew": 0, "turn": turn_id}
    except subprocess.TimeoutExpired:
        why = f"the turn did not finish within {config.HARBOR_TURN_TIMEOUT:.0f}s"
        report_failure(session, line, why)
        return {"ok": False, "busy": False, "answer": why, "drew": 0, "turn": turn_id}
    except Exception as exc:                                            # noqa: BLE001
        report_failure(session, line, f"{exc.__class__.__name__}: {exc}")
        return {"ok": False, "busy": False, "answer": f"Harbor did not answer: {exc}",
                "drew": 0, "turn": turn_id}
    answer = answer or "Harbor had nothing to say."
    # THE WHOLE TEXT GOES BACK (review F6): a typed ask is read, not heard, so only speech
    # is capped, and the deck shows `written`.
    written = read["written"] or answer
    typed_record(turn_id, spoken, answer, source, written=written)
    return {"ok": True, "busy": False, "answer": answer, "written": written, "drew": drew,
            "turn": turn_id}


def typed_record(turn_id: str, said: str, answer: str, source: str, busy: bool = False,
                 written: str = "") -> None:
    """The typed turn's one transcript line. Best effort: a log never costs the answer."""
    try:
        TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
        with TRANSCRIPT.open("a") as handle:
            handle.write(json.dumps({"at": time.time(), "turn": turn_id, "kind": "typed-ask",
                                     "tier": "harbor", "mode": "typed", "source": source,
                                     "said": said, "answer": answer,
                                     "written": written or answer, "busy": busy}) + "\n")
    except OSError:
        pass


# AN ANSWER HE CANNOT HEAR GOES ON THE BOARD, WHICH IS THE ONE PLACE HE LOOKS (decision
# D3). Keel's Q8 (no general queue) is why this is a card and not a notice: there is one
# store, and a sentence he still has to act on has to live in it or it lives nowhere. The
# old `harbor-queue add` and the dashboard's "from voice" group are both gone; what
# replaces them is one `kb create` with `kind=answer`, an inbox card he archives when he
# has read it.
#
# TITLE `Answer: <what he asked>`, so the Cards route reads as a list of questions rather
# than a list of replies. The body is his question verbatim and then the answer, because
# the answer alone is unreadable a day later.
#
# WHERE IT IS FILED IS NOT THE CAPTURE DEFAULT. Personal, always: a give-up answer is a
# message to him, and a machine deciding it belongs on a work board is exactly the guess
# `space` being immutable makes expensive.
ANSWER_SPACE = "personal"
ANSWER_TITLE_CHARS = 60


def queue_answer(said: str, answer: str, turn_id: str = "") -> bool:
    """File an answer he was not there to hear (or was promised in text) as a card.

    RETURNS TRUE WHEN `kb` PRINTED AN ID, and the caller
    (`Dispatcher._finish_silent`'s `queue=True` branch) records `queued` against that.
    Before 2026-09-17 this returned False by contract and the answer reached only the
    log, which meant "I'll answer in text instead" pointed at a page he has said plainly
    he does not read after the fact.

    BEST EFFORT, LIKE EVERY OTHER SIDE EFFECT IN THIS FILE. The real text has already
    reached the turn record and the log by the time this runs, so a failure here must
    never turn an answered turn into a crashed one.
    """
    text = " ".join(str(answer or "").split())
    if not text:
        return False
    said_clip = " ".join(str(said or "").split())
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    log(f"[{stamp}] voice: a turn's answer was not spoken, so it goes on the board.\n"
        f"    asked       {said_clip[:120]!r}\n"
        f"    turn        {turn_id or '(none)'}\n"
        f"    answer      {text}")
    title = said_clip[:ANSWER_TITLE_CHARS] or "a voice turn"
    argv = ["--actor", "voice", "create", "--space", ANSWER_SPACE,
            "--topic", "voice", "--title", f"Answer: {title}",
            "--brief", f"{said_clip}\n\n{text}",
            "--option", "source=voice", "--option", "kind=answer"]
    try:
        card = capture.create(argv)
    except Exception as exc:                                            # noqa: BLE001
        log(f"[{stamp}] voice: and it could NOT be filed: "
            f"{exc.__class__.__name__}: {exc}")
        return False
    log(f"[{stamp}] voice: filed as {card.get('id')}.")
    return bool(card.get("id"))


class SayInbox:
    """Everything Harbor has said out loud, in the order it said it.

    A DIRECTORY WATCH RATHER THAN A FILE WATCH, and the reason is the narration channel:
    Harbor may call `say` several times during one turn, and a single file would have the
    second line overwrite the first before anything read it.

    Lines are claimed by moving them aside, so nothing is spoken twice and a restart
    mid-turn does not replay the last answer.
    """

    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory or SAY_DIR)
        self.spoken = self.dir / "spoken"

    def write(self, text: str, turn: str = "", eta: float | None = None,
              boards: list | None = None) -> Path:
        """What `bin/keel-voice say` calls. The only INPUT to the gateway.

        `eta` IS ONLY EVER READ OFF AN `opening` RECORD (c-229): it rides on the same
        write because a fourth file for one number would be more machinery than the
        number, and every other caller simply never passes it, so this stays a no-op
        for `say` and `progress`.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{time.time():.6f}-{os.getpid()}.json"
        tmp = path.with_suffix(".part")
        rec = {"text": " ".join(str(text).split()), "at": time.time(), "turn": turn}
        if eta is not None:
            rec["eta"] = eta
        if boards:
            # THE BOARDS THE ANSWER DREW (VP-5), so the turn can name them to the page.
            rec["boards"] = [str(b) for b in boards]
        tmp.write_text(json.dumps(rec))
        tmp.rename(path)                     # atomic: a half-written line never reads
        return path

    def claim(self, turn: str = "") -> list[dict]:
        """Every unspoken line for this turn, oldest first, moved aside as it is taken.

        A LINE BELONGS TO A TURN, AND TWO WATCH LOOPS CAN BE RUNNING AT ONCE. A turn he
        has moved on from is HELD rather than cancelled: its loop keeps watching for the
        answer it is still owed, so while a second turn is in flight there are two loops
        reading this one directory. Without a turn id, whichever polls first claims
        whatever arrived, and the two answers are recorded against each other's
        questions. Observed live on 2026-09-18, with the first answer landing on the
        second turn and the second on the first.

        A LINE WITH NO TURN ON IT IS ANYBODY'S, which is what `bin/keel-voice say` writes
        and what the pane era always wrote. A line for a turn that is no longer watching
        is left where it is and drained, with a record, by the next `begin()`.
        """
        if not self.dir.is_dir():
            return []
        out = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                rec = json.loads(path.read_text())
            except Exception:                                           # noqa: BLE001
                path.unlink(missing_ok=True)
                continue
            owner = str(rec.get("turn") or "")
            if turn and owner and owner != turn:
                continue
            rec["path"] = str(path)
            out.append(rec)
            try:
                self.spoken.mkdir(parents=True, exist_ok=True)
                path.rename(self.spoken / path.name)
            except OSError:
                path.unlink(missing_ok=True)
        return out

    def drain(self) -> list[dict]:
        """Throw away anything waiting, without speaking it, and say what was thrown away.

        Called when a turn starts, so an answer to the PREVIOUS question that arrived
        while he was already asking the next one is not spoken over the new turn. It is
        the file-side half of the generation counter.

        RETURNS WHAT IT DROPPED rather than nothing, so the caller can log it. This is
        the fix for the one drop path in the opener that used to have no record at all:
        an opener that lost the race to `say` (both pending in the same watch pass) sat
        in OPENING_DIR until the next turn's `begin()` deleted it here, unlogged. Review
        round 3, 2026-09-07.
        """
        dropped = []
        for path in list(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            try:
                dropped.append(json.loads(path.read_text()))
            except Exception:                                           # noqa: BLE001
                pass
            path.unlink(missing_ok=True)
        return dropped
