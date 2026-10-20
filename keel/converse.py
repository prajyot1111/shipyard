"""`keel converse <card> "<text>"`: one turn into the card's own house session.

The primitive behind "connect me to c-272" (V4) and the one both Harbors call (V6): voice
pins to it after the connect verb, and the phone Harbor runs it when he asks about a card,
so only the ANSWER enters that conversation's context and never the plan.

THIS FILE IS THE BOARD HALF, AND ONLY THAT (V12). Everything about the MACHINE the house
runs on (is its process busy, is there memory, stop it, own the process that takes the
turns, cut the answer into sentences) is `keel/housetalk.py`, reached through this
machine's `keel serve` in `keel/housetier.py`. What is left here is what only the board can
answer: the guards that read the card, the hold, the notes, and the sentences he hears when
the turn cannot be taken.

One connected turn, and why it is shaped this way:

1. **Stop the house's process.** `claude -p --resume` is refused while a background session
   is alive (probed 2026-09-18 and again 2026-09-20): the phone door and the headless door
   are exclusive in time. A house already down (a tracking card the drain retired, a done
   card, a house between resumes) is the easy case, and it is remembered, because what was
   already down is left down at the end.
2. **Take the hold.** `options.voice_hold` on the card, one key in the one store, read by
   `drain.reconcile`, `drain.retire_tracking`, `drain.resume_quiet`, `house.resume` and both
   bodies of the Stop hook. While it is live nothing automatic moves that house.
3. **The turn**, under the card's own settings file, model, cwd and add-dirs, with
   `prompts.converse` around his sentence. It continues the same transcript under the same
   uuid, so his words land in the real conversation the house has been having with itself.
   While he is PINNED that turn goes into ONE KEPT-ALIVE PROCESS (V12), which the local
   `keel serve` owns: 1.0 to 1.5 s to the first word instead of 3.6 to 4.1 s, and the
   answer arrives sentence by sentence while it is still being written. A one-shot turn
   (the phone Harbor's, no pin) is the plain `claude -p --resume` it has always been, and
   so is every turn when the kept-alive path cannot be used.
4. **The record.** One short event per exchange, his words verbatim.
5. **The release**, on "back to Harbor" or when the hold runs out (the drain does that one):
   the conversation is CLOSED, then the hold is cleared and the house is woken with no
   prompt, so it costs no tokens and, on 2.1.278, keeps its session id and its claude.ai
   link. The order is the requirement: a wake is refused while any process still holds the
   session.

A conversation holds the house DOWN between turns (`--connect`), because waking it would
cost two seconds a turn to reopen a door he is not using while he is talking. A one-shot
turn (the phone Harbor's, no pin) takes a hold of its own and gives it straight back.

The guards are V4's: idle only (a house mid-work is refused and his question is left on the
card as a note it will see at its next turn), the hold above, and voice-aware hooks. The
memory floor is honoured too: a turn is a whole `claude` process, and one that gets the
machine OOM-killed would take the voice gateway with it.
"""

import argparse
import json
import os
import secrets
import sys
import time

from keel import (boardgrammar, boardpen, config as config_module, harness, house,
                  housetalk, housetier, logins, narration, prompts, sentences, views)
from keel.board import Refused, open_board
from keel.config import Config

# The actor every write here is recorded under. `voice` never holds the deck's token, so it
# cannot answer a gate whatever is said to it, which is the same mechanism capture runs
# under (`voice/harbor_voice/capture.py`).
ACTOR = "voice"
# A HOUSE MAY NOT RUN THIS VERB. `board.HOLD_ACTORS` stops a house writing the hold through
# `kb`; this is the same door on this side, because the verb takes the hold itself, without
# going through `kb` at all. A house talking to a house is not what V6 asks for, and the
# first thing it would do on its own card is stop the session that ran it.
HOUSE_ENV = "KEEL_CARD"
NOT_A_HOUSES = ("`keel converse` is the voice gateway's and the phone Harbor's, not a "
                "house's: it takes the hold that keeps the drain away from a session.")
# How much of the answer rides in the exchange note. The whole answer is spoken and the
# whole turn is in the transcript; the note is the record on the card, read on a phone.
ANSWER_CLIP = 220
CONNECTED_NOTE = "voice connected to this house; it is held (its session is stopped) until the user is done"
CONNECTED_DOWN_NOTE = ("voice connected to this house; its session was already stopped, so it "
                       "is held as it is and left that way afterwards")
RELEASED_NOTE = "voice let this house go after {turns}"
# What is SPOKEN back when the verb cannot take the turn. Sentences, not error messages:
# every one of them is played to him.
NO_HOUSE = "{card} has no house session yet. Do you want me to start it?"
BUSY = ("{card} is building right now. I have left your question on the card, so it sees it "
        "at its next turn.")
HOUSE_REFUSED = "{host} would not open that conversation: {why}"
SHORT_ON_MEMORY = "{host} is short of memory. Try again in a minute."
TURN_FAILED = "That turn did not come back: {why}"
# HOW A MACHINE IS NAMED OUT LOUD, at the front of one of the sentences above (c-634): this
# machine is "This machine", and any other host is its key as written, so one machine never
# hears a machine's name at all.
THIS_MACHINE = "This machine"
# WHAT THE CARD GETS WHEN A TURN IS ENDED RATHER THAN ANSWERED. A turn killed mid tool-call
# still had his sentence and still did work, so the card says what it had reached before it
# stopped instead of carrying no trace of a turn that really happened. The actions are the
# narration's own words, so nothing here can name a path either.
STOPPED_NOTE = 'voice: "{said}"\n  -> the turn was ended ({why}){reached}'
REACHED = "; it had got as far as: {actions}"
NO_CARD = "I could not find a card called {card}."
ARCHIVED = ("{card} is archived, so there is nothing to talk to. Unarchive it on the deck "
            "if you want it back.")
# What is said when the hold a conversation was holding has GONE: he stopped the house from
# the deck, or answered its gate, or the drain cleared a hold that ran out. The gateway drops
# its pin on this, which is why it is an answer and not a silent re-hold.
UNPINNED = "That house was stopped, so we are back to Harbor."
# THE TWO RECORDS A KEPT-ALIVE CONVERSATION CAN LEAVE THAT A ONE-SHOT TURN CANNOT (V12).
# Neither is spoken: they are for the card, read afterwards, when a conversation behaved
# oddly and the question is what it actually did.
FELL_BACK_NOTE = ("the live conversation could not take that sentence, so it was asked as a "
                  "turn of its own ({why}); if the house had already begun answering, its "
                  "own answer is in the transcript above this note")
CLOSE_FAILED_NOTE = ("the voice hold is cleared but the live conversation would not close, "
                     "so the house is left down: the drain puts it back on its next pass")
# WHAT A ```board BLOCK IN AN ANSWER BECOMES (K3, K10, `<install>/history/docs/blackboard.md`). A house in a
# voice conversation has no shell to run `keel board push` in mid-sentence, so it writes the
# lines in a fenced block and `keel/boardpen.py` pushes them to that card's own board. The
# sentence he hears in their place is built from the push REPORT (C1): on the streamed path
# the pen answers each closing fence with the line its report earns and it is spoken as a
# part here, and on every path the pen's `take` ends the answer with the same line. The pen
# is SHARED with the talker, whose answers reach him through the gateway instead.
BoardPen = boardpen.BoardPen
BOARD_DREW = boardpen.BOARD_DREW
BOARD_REFUSED = boardpen.BOARD_REFUSED
# WHAT STANDS IN FOR A GOODBYE THE HOUSE DID NOT WRITE. `prompts.SPOKEN` asks for one short
# sentence and then `<<keel-leave>>`; an answer that is only the token has nothing left in
# it once the token is out, and the gateway would speak its "that did not come back" line
# and then leave. Short, and it says the one thing that is true of every such turn.
LEAVING_SAID = "Right, I'll let you go."
DREW_NOTE = boardpen.DREW_NOTE
NOT_DREW_NOTE = boardpen.NOT_DREW_NOTE
# ----- the guards -----

def config_dir_of(cfg: Config, card: dict):
    space = cfg.spaces.get(card["space"])
    return space.config_dir if space else None


def spoken_host(cfg: Config, host: str | None) -> str:
    """A machine's name at the front of a spoken sentence: "This machine" for this one."""
    if not host or host == cfg.host:
        return THIS_MACHINE
    return host[:1].upper() + host[1:]


def refusal(cfg: Config, card: dict) -> str | None:
    """The spoken sentence that says why this turn cannot be taken, or None.

    THE CHEAP QUESTIONS COME FIRST, and that ordering is load-bearing rather than tidy: a
    card with no house, an archived one and one with no route to its machine are all
    answered before anything looks at the machine, and before any plan is built.
    `housetalk.plan` goes through `house.placement`, which CUTS the worktree it names, so a
    card on its way to a refusal must never reach it.
    """
    if card["derived"]["archived"]:
        return ARCHIVED.format(card=card["id"])
    if not card.get("session_id"):
        return NO_HOUSE.format(card=card["id"])
    if housetalk.busy_session(card["session_id"], config_dir_of(cfg, card)):
        return BUSY.format(card=card["id"])
    if housetalk.memory_short(cfg.memory_floor_mb):
        return SHORT_ON_MEMORY.format(host=spoken_host(cfg, cfg.host))
    return None


def new_turn_id() -> str:
    """An id for a turn nobody named, which is what makes it retryable (V12)."""
    return secrets.token_hex(6)


def leave_note(board, card_id: str, said: str) -> None:
    """His question, on the card, when the turn could not be taken. The house reads its own
    card at its next turn, so a refusal still gets the question to it."""
    if said:
        board.note(card_id, f'the user asked by voice, and the house could not be reached: "{said}"',
                   ACTOR)


# ----- the hold -----

def take_hold(cfg: Config, board, card: dict, pinned: bool) -> dict:
    """Stop the house if it is up, and hold the card. Returns the hold as it now stands."""
    held = board.voice_hold_of(card["id"])
    if held:
        board.hold_voice(card["id"], cfg.voice_hold_seconds)
        return board.voice_hold_of(card["id"])
    stopped = housetalk.stop_house({"session_id": card["session_id"],
                                    "config_dir": config_dir_of(cfg, card)})
    board.hold_voice(card["id"], cfg.voice_hold_seconds, stopped=stopped, turns=0)
    if pinned:
        board.note(card["id"], CONNECTED_NOTE if stopped else CONNECTED_DOWN_NOTE, ACTOR)
    return board.voice_hold_of(card["id"])


def stop_refusal(cfg: Config, card: dict, error: harness.HarnessError) -> str:
    """The sentence for a house whose stop failed (r-17). `take_hold` raised before any hold
    was written, so there is nothing to give back."""
    return HOUSE_REFUSED.format(host=spoken_host(cfg, ""), why=str(error) or "it gave no reason")


def let_go(cfg: Config, board, card_id: str, note: bool = True) -> dict:
    """Release the hold and put the house back the way voice found it.

    A house voice stopped is woken. A house that was ALREADY down is left down: waking a
    tracking card's retired session would only hand `drain.retire_tracking` the same session
    to stop again on its next pass, and waking a done card's would start a process on a card
    with nothing left to do.

    THE CONVERSATION IS CLOSED FIRST (V12), and the order is the requirement. A kept-alive
    conversation is a `claude` holding that session, and `claude --resume <id> --bg` is
    refused while anything holds it, so a wake before the close would fail and the house
    would be left down with its hold gone. Every other path that ends a hold does the same
    thing in the same order: `drain.release_holds`, the deck's Stop, and a gate answered.

    AND THE CLOSE'S ANSWER IS READ. A close that FAILED means something still holds that
    session, so the wake would be refused: the card says so and the house is left down for
    the drain's next pass to put back. A server that is merely away owns no conversation,
    which is the ordinary case for a turn typed from the deck, and nothing is in the way.
    """
    card = board.get(card_id)
    held = (card.get("options") or {}).get(views.VOICE_HOLD_OPTION) or {}
    shut = housetier.close_session(cfg, card)
    board.release_voice(card_id)
    woke = shut.woke
    if shut.status == housetier.FAILED:
        board.note(card_id, CLOSE_FAILED_NOTE, ACTOR)
    elif held.get("stopped"):
        try:
            woke = bool(house.wake(cfg, board, card_id))
        except Exception as error:  # noqa: BLE001 - the conversation is over either way
            board.note(card_id, f"the voice hold is cleared but waking the house failed: "
                                f"{error}", ACTOR)
    if note:
        turns = held.get("turns") or 0
        said = f"{turns} exchange{'s' if turns != 1 else ''}"
        board.note(card_id, RELEASED_NOTE.format(turns=said)
                   + ("; its session is awake again" if woke else ""), ACTOR)
    return {"woke": woke, "turns": held.get("turns") or 0}


# ----- the turn -----

def take_turn(cfg: Config, board, card: dict, said: str, timeout: int,
              narrator: narration.Narrator | None = None, kept: bool = False,
              turn_id: str = "", pen: "BoardPen | None" = None,
              leave: "LeaveDirective | None" = None) -> dict:
    """One turn into the card's session; the answer, what it cost, and how it was taken.

    TWO PATHS, ONE PAYLOAD. While he is PINNED the sentence goes into the kept-alive
    conversation the local server owns (V12), which is one process for the whole
    conversation and streams the answer sentence by sentence. Everything else is the plain
    one-shot `claude -p --resume` (V4): the phone Harbor's single question, a turn typed
    from the deck, and any turn the switch has turned back. Both hand back the same
    `result` payload, so nothing past this function knows which one ran.

    THE KEPT-ALIVE CALL SENDS A CARD, A SENTENCE AND A TURN ID, AND NOTHING ELSE. The
    server builds the placement from its own config and wraps the sentence in its own
    framing, because it is the thing that runs `claude` (see `keel/housetier.py`). So the
    plan is built HERE only for the fallback, which runs in this process.

    THE FALLBACK IS HERE AND NOWHERE ELSE, AND IT IS NARROW ON PURPOSE. `housetier.Away` is
    raised only where his sentence cannot have reached a `claude`: nothing listening before
    the request was accepted, the board refusing, the sentence never written, or the
    process confirmed dead. Anything else is a failure he hears, because falling back on it
    would ask the house a question it is already answering and he would hear two answers.
    A conversation that died after part of the answer was already spoken does not fall back
    either, for the same reason in the other direction.

    STREAMED ONLY WHEN SOMEONE IS LISTENING (V5), on the one-shot path. With a narrator the
    turn runs as `--output-format stream-json --verbose` and each tool the house picks up
    becomes a sentence in the voice gateway's progress inbox while the turn is still
    running; with none it is the plain `--output-format json` turn it has always been.
    """
    on_event = events_into(narrator, pen, leave) if narrator is not None else None
    report = pen.carried if pen is not None else ""
    grammar = bool(pen is not None and pen.grammar)
    started = time.time()
    fell_back = ""
    if kept:
        try:
            payload = housetier.say(cfg, card, said, turn_id=turn_id,
                                    timeout=timeout, on_event=on_event, report=report,
                                    grammar=grammar)
            return {"answer": spoken_answer(pen, leave, payload), "kept": True,
                    "fell_back": "", "seconds": round(time.time() - started, 1)}
        except housetier.Away as away:
            if narrator is not None and narrator.parts:
                raise harness.HarnessError(str(away)) from None
            fell_back = str(away)
    plan = housetalk.plan(cfg, card)
    try:
        payload = housetalk.one_shot(plan, prompts.converse(said, worktree=plan["worktree"],
                                                            report=report),
                                     timeout=timeout, on_event=on_event)
    except harness.HarnessError as error:
        # This one-shot ran in this process, under this machine's config dir (c-558).
        logins.saw(cfg, plan["config_dir"], str(error))
        raise
    return {"answer": spoken_answer(pen, leave, payload), "kept": False,
            "fell_back": fell_back, "seconds": round(time.time() - started, 1)}


def spoken_answer(pen: "BoardPen | None", leave: "LeaveDirective | None",
                  payload: dict) -> str:
    """The turn's answer as he should hear it, with what is not speech taken out of it.

    Every path ends here, so neither a `board` block nor the leave directive can reach his
    ear whichever way the turn was taken. Without a pen (nothing to draw on) and without a
    leave (a caller that cannot act on one) it is exactly the line it always was.
    """
    if pen is None and leave is None:
        return harness.turn_answer(payload)
    raw = str(payload.get("result") or "")
    if leave is not None:
        raw = leave.take(raw)
    # THE PEN COLLAPSES THE ANSWER ITSELF, because it needs the newlines to find a block
    # first; with no pen the collapse is this line, and it is the one `turn_answer` does.
    return pen.take(raw) if pen is not None else " ".join(raw.split())


class LeaveDirective:
    """Whether this turn's answer asked to end the conversation, and the token taken out.

    THE SHAPE IS THE PEN'S, and so is the reason for it: the directive is read TWICE over
    and means one thing. On a streamed turn the cutter sees it as it arrives and says so
    with a `leave` event, which is what keeps the token out of the sentence that is spoken
    while the answer is still being written; the finished answer then arrives carrying it
    as well, because the answer is the whole answer. A boolean cannot be set twice, so the
    second reading is free, and it is also the ONLY reading on the one-shot path (the phone
    Harbor's single question, a turn typed into the ask box).

    IT DECIDES NOTHING AND RELEASES NOTHING. `keel converse` reports `leave` beside the
    sentence and the GATEWAY acts on it, down the same path a spoken "back to Harbor"
    takes: one release, one set of spoken lines, one re-arm.
    """

    def __init__(self):
        self.asked = False

    def heard(self) -> None:
        """The cutter saw the directive end the answer, mid-stream."""
        self.asked = True

    def take(self, raw: str) -> str:
        """The finished answer with the token out of it, remembering what it said."""
        text, ends = sentences.leave_directive(raw)
        self.asked = self.asked or ends
        return text


def events_into(narrator: narration.Narrator, pen: BoardPen | None = None,
                leave: LeaveDirective | None = None):
    """Hand the machine half's events to the narrator, which owns the inbox they go in.

    The two kinds land in the same directory and are told apart by the record: an `action`
    becomes one of `keel/narration.py`'s fixed sentences, in Harbor's voice, and a `part`
    is the house's own words, marked as a part so the gateway speaks it in the house's
    voice and without waiting for the four second silence gate (V8, V12).

    AND TWO KINDS GO NOWHERE NEAR THE INBOX, because neither is anything to say. A `fence`
    is never spoken; one whose language is `board` is DRAWN, here, the moment the block
    closes, so the board has it before the sentence saying so is spoken (K3, K10). Any
    other fence is a code block and this has nothing to do with it. A `leave` is the house
    having been asked to end the conversation, which is recorded here and answered by the
    caller once the turn is over.
    """
    def on_event(event: dict) -> None:
        if event.get("type") == "action":
            narrator.on_action(str(event.get("action") or ""), str(event.get("tool") or ""))
        elif event.get("type") == "part":
            # N7, HELD HERE: after a block that REPORTED, the rest of the answer is not
            # spoken (it is on the card). The cutter cannot know which blocks reported.
            if pen is None or not pen.silenced:
                narrator.on_part(str(event.get("text") or ""))
        elif event.get("type") == sentences.LEAVE and leave is not None:
            leave.heard()
        elif (event.get("type") == sentences.FENCE and pen is not None
              and str(event.get("lang") or "").strip().lower() == sentences.BOARD_LANG):
            # THE LINE COMES FROM THE REPORT, AFTER THE PUSH (C1). The cutter no longer
            # speaks one as the fence closes, because it cannot know what the push did.
            line = pen.on_fence(str(event.get("body") or ""))
            if line:
                narrator.on_part(line)
    return on_event


# WHERE A TROUBLED DRAWING WAITS FOR THE NEXT TURN (C1). No second store: the pen's own
# `board report:` note on the card IS the record, and it rides into the next turn's framing
# only while it sits just before the newest exchange, so it is carried exactly once.
EXCHANGE_MARK = 'voice: "'
REPORT_LOOKBACK = 12


# THE BOARD'S RULES, ONCE PER VERSION PER HOUSE (C4). The card is framed on a
# conversation's first sentence always, and on a later one when this note is missing for
# the current version; the note is written after the first turn that carried it.
GRAMMAR_GIVEN = "board grammar v{version} given to the house"


def grammar_given(board, card_id: str) -> bool:
    """Has this house been given the board's current grammar card."""
    mark = GRAMMAR_GIVEN.format(version=boardgrammar.GRAMMAR_VERSION)
    try:
        events = board.events(card_id)
    except Exception:  # noqa: BLE001 - asking again costs a few lines of framing
        return False
    return any(event.get("kind") == "note" and str(event.get("text") or "").startswith(mark)
               for event in events)


def pending_report(board, card_id: str) -> str:
    """The last turn's board report, when that turn's drawing did not land cleanly."""
    try:
        events = board.events(card_id, last=REPORT_LOOKBACK)
    except Exception:  # noqa: BLE001 - a missing report is not worth the turn
        return ""
    seen_exchange = False
    for event in reversed(events):
        text = str(event.get("text") or "") if event.get("kind") == "note" else ""
        if text.startswith(EXCHANGE_MARK):
            if seen_exchange:
                return ""
            seen_exchange = True
        elif text.startswith(boardpen.REPORT_MARK) and seen_exchange:
            return text
    return ""


def record_stopped(board, card_id: str, said: str, why: str,
                   narrator: narration.Narrator | None) -> None:
    """The record for a turn that was ENDED rather than answered.

    A turn killed at its timeout took his question and did real work with it, and until
    this the card kept nothing at all about it. What it can honestly say is what the
    narration had already said out loud, which is a list of action keys and never a path.
    """
    seen = list(getattr(narrator, "seen", ())) if narrator is not None else []
    reached = REACHED.format(actions=", ".join(seen)) if seen else ""
    board.note(card_id, STOPPED_NOTE.format(said=said, why=why, reached=reached), ACTOR)


def record(board, card_id: str, said: str, answer: str) -> None:
    """One event per exchange, his words verbatim: the deck shows the conversation happened
    and the phone Harbor can read it without being in it."""
    clipped = answer if len(answer) <= ANSWER_CLIP else answer[:ANSWER_CLIP].rstrip() + "..."
    board.note(card_id, f'voice: "{said}"\n  -> "{clipped}"', ACTOR)


# ----- the three things the verb does -----

def answer(cfg: Config, board, card_id: str, said: str, timeout: int,
           pinned: bool = False, progress: str = "", turn_id: str = "") -> dict:
    """One turn, with every guard in front of it. Never raises for an ordinary refusal: the
    caller has a microphone open and needs a sentence to say.

    `progress` IS WHERE A LISTENER WANTS TO BE TOLD WHAT THE HOUSE IS DOING (V5), and
    `turn_id` is the turn those lines belong to. Keel does not know where that directory
    is: the voice gateway passes its own progress inbox, because the segment's layout is
    the gateway's to know and `keel/` never imports `harbor_voice`. With neither, the turn
    runs exactly as it did before and nothing is written anywhere.

    `pinned` says the caller believes it is in a conversation with this card. If the hold it
    was holding has GONE (he stopped the house from the deck, he answered its gate, or the
    drain cleared one that ran out), that is the one thing the caller cannot see for itself,
    so it is answered rather than quietly re-taken: `unpin` comes back and the gateway drops
    its pin.
    """
    card = board.get(card_id)
    if pinned and not board.voice_hold_of(card_id):
        return {"ok": False, "say": UNPINNED, "card": card_id, "unpin": True}
    why = refusal(cfg, card)
    if why:
        leave_note(board, card_id, said)
        return {"ok": False, "say": why, "card": card_id}
    # A hold that is already there is his conversation, and it is kept afterwards. A turn
    # that takes its own (the phone Harbor asking one question) gives it straight back.
    pinned = bool(board.voice_hold_of(card_id))
    try:
        held = take_hold(cfg, board, card, pinned=False)
    except harness.HarnessError as error:
        leave_note(board, card_id, said)
        return {"ok": False, "say": stop_refusal(cfg, card, error), "card": card_id}
    narrator = narration.Narrator(progress, turn=turn_id) if progress else None
    # THE KEPT-ALIVE PATH IS THE CONVERSATION'S, NOT THE ONE-SHOT'S (V12). A turn with no
    # pin behind it is a single question from the phone Harbor: a process kept open for it
    # would be opened and closed again for every one, which is the cost this replaces
    # rather than the cost it adds.
    kept = bool(pinned and cfg.voice_kept_alive)
    # THE TURN ID IS ALSO THE KEY THAT STOPS A SENTENCE BEING DELIVERED TWICE (V12). The
    # gateway mints one per turn and passes it for the narration lines; a caller that did
    # not (a turn typed from the deck) gets one here, because a turn with no id could not be
    # attached to after a broken stream and would have to be asked all over again.
    turn_id = turn_id or new_turn_id()
    # THE PEN IS THIS TURN'S, and it is made whether or not anybody is listening: a `board`
    # block reaches the board from a streamed turn as the fence closes and from a one-shot
    # turn out of the finished text, and the same pen is what keeps those two from drawing
    # it twice (K3, K10).
    pen = BoardPen(cfg, boardpen.card_source(card_id),
                   note=lambda text: board.note(card_id, text, ACTOR))
    pen.carried = pending_report(board, card_id)
    pen.grammar = not grammar_given(board, card_id)
    # AND THIS TURN'S LEAVE, made for the same reason and on both paths: the directive is
    # read off the stream as it arrives (so it is never spoken) and off the finished answer
    # (so a one-shot turn reads it too), and the two readings are one boolean.
    leave = LeaveDirective()
    try:
        result = take_turn(cfg, board, card, said, timeout, narrator, kept=kept,
                           turn_id=turn_id, pen=pen, leave=leave)
    except harness.HarnessError as error:
        if not pinned:
            let_go(cfg, board, card_id, note=False)
        # THE CARD KEEPS THE TURN EITHER WAY. His question was asked and the house did
        # something with it; a failure that leaves no trace is how a conversation loses a
        # turn nobody can find afterwards.
        record_stopped(board, card_id, said, str(error), narrator)
        return {"ok": False, "say": TURN_FAILED.format(why=error), "card": card_id}
    if leave.asked and not result["answer"].strip():
        # AN ANSWER THAT WAS NOTHING BUT THE DIRECTIVE. The framing asks for a goodbye and
        # then the token, so this is a house that skipped the goodbye; with the token
        # stripped there would be nothing left to say, and the gateway would speak "that
        # did not come back" and then leave. One fixed sentence rather than that, which is
        # what the connect directive's own `connect_bare` line does at the other door.
        result["answer"] = LEAVING_SAID
    repair = pen.repair_note()
    if repair:
        board.note(card_id, repair, ACTOR)
    if pen.grammar:
        board.note(card_id, GRAMMAR_GIVEN.format(version=boardgrammar.GRAMMAR_VERSION), ACTOR)
    # THE RECORD KEEPS WHAT WAS WRITTEN, not only what was spoken: a drawing turn speaks
    # its lead and the report line (N7), and the rest of the answer belongs on the card.
    record(board, card_id, said, pen.written if pen.reports else result["answer"])
    if result.get("fell_back"):
        # HE GOT HIS ANSWER, BUT NOT THE WAY THE CONVERSATION WAS MEANT TO. It cost a
        # process of its own, and if the conversation had already written his sentence into
        # a house that then died, the house may have a turn nobody heard. The card is where
        # that is visible afterwards.
        board.note(card_id, FELL_BACK_NOTE.format(why=result["fell_back"]), ACTOR)
    turns = int((held or {}).get("turns") or 0) + 1
    if pinned:
        board.hold_voice(card_id, cfg.voice_hold_seconds, turns=turns)
        held = board.voice_hold_of(card_id)
    else:
        let_go(cfg, board, card_id, note=False)
        held = None
    card = board.get(card_id)
    return {"ok": True, "say": result["answer"], "card": card_id, "stage": card["stage"],
            "drew": pen.count,
            # THE PUSH REPORT (C1): what the gateway writes to its transcript when a
            # drawing did not land.
            "board": pen.summary(),
            # WHAT THE HOUSE ASKED FOR, BESIDE WHAT IT SAID (2026-09-21). The hold is
            # deliberately still on: the gateway hears this, speaks the goodbye, and then
            # ends the conversation exactly as a spoken "back to Harbor" does, through the
            # one release path. A second release here would be a second way out to keep in
            # step with the first.
            "leave": leave.asked,
            "seconds": result["seconds"], "held_until": (held or {}).get("until"),
            "turns": turns}


def connect(cfg: Config, board, card_id: str) -> dict:
    """Pin to a card: take the hold, no turn, no tokens. What the connect verb runs before
    he has said anything, so the page can name the card and the house is already his.

    AND IT WARMS THE CONVERSATION (V12). The hold has just stopped the house's process, so
    the session is free; opening the kept-alive one now means the `claude` boots, reads the
    transcript and waits on its stdin while "Connecting you now" and the tone are playing,
    which is time that was going to be spent anyway. It costs no tokens: a process with
    nothing on its stdin takes no turn. It is best effort and its failure is never spoken,
    because the first sentence opens one or falls back and either way he is connected.
    """
    card = board.get(card_id)
    why = refusal(cfg, card)
    if why:
        return {"ok": False, "say": why, "card": card_id}
    try:
        held = take_hold(cfg, board, card, pinned=True)
    except harness.HarnessError as error:
        return {"ok": False, "say": stop_refusal(cfg, card, error), "card": card_id}
    if cfg.voice_kept_alive:
        housetier.open_session(cfg, card, timeout=harness.TURN_TIMEOUT)
    # `space` IS FOR THE VOICE PAGE'S HEADER (V8, card c-316): it takes the house's colour
    # for as long as the pin holds, and a house's colour is its card's space, which is the
    # deck's own two palettes rather than a third invented for one page. It costs a key on
    # an answer that already carries the title.
    return {"ok": True, "say": f"Connected to {card_id}, {card['title']}.", "card": card_id,
            "stage": card["stage"], "title": card["title"], "space": card["space"],
            "held_until": (held or {}).get("until")}


def release(cfg: Config, board, card_id: str) -> dict:
    """"Back to Harbor": let the house go, and say so."""
    card = board.get(card_id)
    if not (card.get("options") or {}).get(views.VOICE_HOLD_OPTION):
        return {"ok": True, "say": "Back to Harbor.", "card": card_id, "held_until": None}
    result = let_go(cfg, board, card_id)
    return {"ok": True, "say": "Back to Harbor.", "card": card_id, "held_until": None,
            "turns": result["turns"]}


# ----- the verb -----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel converse", description=(
        "one turn into a card's own house session, guarded by the voice hold"))
    parser.add_argument("card", help="the card whose house to talk to, or bosun (c-523)")
    parser.add_argument("text", nargs="?", default="", help="what the user said, verbatim")
    parser.add_argument("--connect", action="store_true",
                        help="take the hold and pin to the card, without taking a turn")
    parser.add_argument("--pinned", action="store_true",
                        help="the caller is already in a conversation with this card, so a "
                             "hold that has gone is answered with `unpin` rather than retaken")
    parser.add_argument("--release", action="store_true",
                        help="let the house go and wake it (back to Harbor)")
    parser.add_argument("--json", action="store_true", help="the whole answer as JSON")
    parser.add_argument("--timeout", type=int, default=harness.TURN_TIMEOUT,
                        help=f"seconds to wait for the turn (default {harness.TURN_TIMEOUT})")
    parser.add_argument("--progress", default="",
                        help="a directory to narrate this turn's activity into (V5)")
    parser.add_argument("--turn", default="",
                        help="the turn id those narration lines belong to")
    return parser


def run(cfg: Config, board, args) -> dict:
    if args.card.strip().lower() == housetier.BOSUN:
        return run_bosun(cfg, board, args)
    if args.release:
        return release(cfg, board, args.card)
    if args.connect:
        return connect(cfg, board, args.card)
    if not args.text.strip():
        return {"ok": False, "say": "Say something to send it.", "card": args.card}
    return answer(cfg, board, args.card, args.text.strip(), args.timeout,
                  pinned=args.pinned, progress=args.progress, turn_id=args.turn)


def run_bosun(cfg: Config, board, args) -> dict:
    """"Put me through to Bosun" (c-523): the same three forms, on Bosun's own session and
    the board's `holds` row instead of a card (`keel/bosuntalk.py`)."""
    from keel import bosuntalk
    if args.release:
        return bosuntalk.release(cfg, board)
    if args.connect:
        return bosuntalk.connect(cfg, board)
    if not args.text.strip():
        return {"ok": False, "say": "Say something to send it.", "card": bosuntalk.TARGET}
    return bosuntalk.answer(cfg, board, args.text.strip(), args.timeout, pinned=args.pinned,
                            progress=args.progress, turn_id=args.turn)


def main(argv: list[str] | None = None) -> int:
    """`keel converse <card> ...`: the spoken answer on stdout, exit 1 when it is a refusal.

    A refusal is still a sentence: the caller is holding a microphone open, so what it needs
    is words to say, not a stack trace. `--json` carries the same thing with the hold's
    expiry beside it, which is how the gateway knows when its pin runs out.
    """
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    if os.environ.get(HOUSE_ENV):
        print(NOT_A_HOUSES, file=sys.stderr)
        return 1
    cfg = config_module.load()
    board = open_board(cfg)
    try:
        result = run(cfg, board, args)
    except Refused as refused:
        result = {"ok": False, "say": NO_CARD.format(card=args.card), "why": str(refused),
                  "card": args.card}
    finally:
        board.close()
    if args.json:
        print(json.dumps(result))
    else:
        print(result["say"])
    return 0 if result.get("ok") else 1
