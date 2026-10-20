"""The MACHINE half of a connected turn: the process, and nothing about the board (V12).

`keel converse` has two halves and they have always been tangled. One is about the BOARD:
the guards that read the card, the hold, the notes, the refusal sentences he hears. The
other is about the MACHINE the house actually runs on: is its process busy, is there memory
for another `claude`, stop it, own the process that takes the turns, hand back what it says.
This module is that second half, and `keel/converse.py` is the first.

THE SPLIT IS THE INTERFACE SLICE 2 REUSES. The next slice carries a conversation over the
door to the Mac, so that work houses can be talked to from the box. That is a transport and
not a rewrite only if this half already takes PLAIN DATA (a `plan` dict, a sentence, a turn
id) and answers with PLAIN JSON-ABLE EVENTS. So there is no `Board` here, no `cfg` past the
one function that builds a plan, and nothing that reads or writes a card.

WHO OWNS THE PROCESS. `keel converse` is a CLI run once per sentence, so it cannot own a
process that has to outlive the sentence. The owner is the long-lived `keel serve`, and
`SESSIONS` below is its registry, one live conversation per card id,
reached over loopback through `keel/housetier.py`. A conversation lives exactly as long as
the hold that justifies it: the same idle deadline, reaped here, and closed on every path
that ends the hold.

ONE CONVERSATION PER CARD, AND ONE TURN AT A TIME IN IT. Two sentences down one pipe at
once would each read the other's records, so every entry has its own lock; a second open
for the same card reuses the live one or replaces a dead one, and never doubles.
"""

import secrets
import threading
import time

from keel import adapters, harness, house, machine, narration, sentences
from keel.config import Config

# How often the reaper looks for a conversation that has gone quiet. Well under the hold,
# because the cost of holding a `claude` open past its welcome is memory on a 12 GB box.
REAP_EVERY = 20.0
# How long a close waits for a turn that is still running before it ends the process
# anyway. HIS RELEASE WINS, and it must not sit behind a turn that has minutes left: "back
# to Harbor" is a sentence he is waiting to hear answered, and the gateway gives the verb
# sixty seconds. A turn ended this way is reported as a failure rather than as a dead
# conversation, so nothing falls back and asks the house the same question again.
CLOSE_WAIT = 5.0


class NotSent(harness.HarnessError):
    """His sentence never reached the process, so it may be asked again.

    The only failure the caller's fallback is allowed to act on without risking a second
    turn on a question the house is already answering (review round 1, finding B).
    """


class Dead(harness.HarnessError):
    """A turn that failed AND took its conversation with it.

    The distinction the caller's fallback rests on: a turn that merely ERRORED (the model
    said so) must not be taken again as a one-shot, because that spends a second turn on a
    question already answered badly. A conversation whose PROCESS has gone must, because
    otherwise the sentence is lost. Carried over the wire as `dead` and read back as
    `housetier.Away`.
    """


# ----- the plain data a turn needs -----

def worktree_gone(cfg: Config, card: dict) -> bool:
    """This card has no worktree to talk in any more.

    A DONE card is the case V4 names: the merge reaped the worktree, and cutting a fresh one
    to answer a question would be a new checkout of work that is finished. It is asked by
    stage rather than by looking, because `house.placement` CUTS the worktree it names (that
    is how a resume finds one again), so looking would create the very thing being asked
    about. An errand has none either way and already runs in its card directory; a work
    card's path is its adapter's to give, so nothing here guesses at it.
    """
    if card["stage"] == "done":
        return True
    if not card.get("repo"):
        return False
    if adapters.space_of(cfg, card).adapter_dir is not None:
        return False
    return not adapters.worktree_dirs(cfg, card)[0].is_dir()


def plan(cfg: Config, card: dict) -> dict:
    """Everything a turn into this card's house needs, as JSON-able plain data.

    Built where the config is (the board's machine today, the house's machine in slice 2)
    and carried from there: strings and lists only, so it survives the wire unchanged.
    `worktree` is false for a done card, which is what `prompts.converse` reads to tell the
    house it can explain but not change.
    """
    where = ({"cwd": cfg.card_dir(card["id"]), "add_dirs": (), "restricted": house.is_fork_review(card),
              "tools": house.tools_of(card) if house.is_fork_review(card) else None,
              "sources": house.setting_sources(card), "worktree": False} if worktree_gone(cfg, card)
             else dict(house.placement(cfg, card), worktree=True))
    flags = house.harness_flags(where)
    space = adapters.space_of(cfg, card)
    return {"card": card["id"],
            "session_id": card.get("session_id") or "",
            "cwd": str(where["cwd"]),
            "config_dir": str(space.config_dir) if space.config_dir else None,
            "settings_path": str(house.settings_for(cfg, card)),
            "model": card.get("model") or None,
            "add_dirs": [str(one) for one in flags["add_dirs"]],
            "restricted": bool(flags["restricted"]),
            "tools": flags["tools"],
            "sources": flags["setting_sources"],
            "worktree": bool(where["worktree"])}


def flags_of(plan: dict) -> dict:
    """The plan as the keyword arguments every `harness` turn call takes."""
    return {"cwd": plan["cwd"], "config_dir": plan["config_dir"],
            "settings_path": plan["settings_path"], "model": plan.get("model"),
            "add_dirs": plan.get("add_dirs") or (),
            "restricted": bool(plan.get("restricted")), "tools": plan.get("tools"),
            "setting_sources": plan.get("sources")}


def extras_of(plan: dict) -> dict:
    """What only a session that is not a card's carries: Bosun's plan (c-523,
    `keel/bosuntalk.py`) names its own environment (its key) and its permission mode. A
    house's plan has neither, and its conversation opens exactly as before."""
    return {key: plan[key] for key in ("env", "permission_mode") if plan.get(key)}


# ----- the two guards that are facts about the machine -----

def listed(plan: dict) -> str | None:
    """The bg id of this card's live session, or None when nothing is running."""
    row = harness.find(plan["session_id"], harness.agents(plan["config_dir"]))
    return (row or {}).get("id")


def busy_session(session_id: str, config_dir) -> bool:
    """This session is listed and working. Guard 1: idle only.

    Absent from the listing is NOT busy: it is a house that is down, which is the easy case
    for a connected turn and the usual one for a tracking card.

    Asked by SESSION rather than by plan, because the board half asks it before it builds
    one: `house.placement` CUTS the worktree it names, and a card that is going to be
    refused must not have a worktree cut for it on the way to the refusal.
    """
    row = harness.find(session_id, harness.agents(config_dir))
    return bool(row) and row.get("status") == "busy"


def busy(plan: dict) -> bool:
    """`busy_session`, for a caller that already has the plan."""
    return busy_session(plan["session_id"], plan["config_dir"])


def memory_short(floor_mb: int) -> bool:
    """Under the machine's floor. A connected turn is a whole `claude` process, so it asks
    the same question every start asks; unlike a start, it says so out loud."""
    if not floor_mb:
        return False
    available = machine.available_mb()
    return available is None or available < floor_mb


def stop_house(plan: dict) -> bool:
    """Stop this card's background session if it is up; True when there was one.

    The two doors are exclusive in time (`harness.RUNNING_REFUSAL`), so this is what makes
    the headless one usable. What was already down is left down at the end, which is why
    the answer matters to the caller.
    """
    bg_id = listed(plan)
    if not bg_id:
        return False
    # The one house stop that does not end the house's background jobs
    # (`keel/housejobs.py`): this is a pause, and the same session is woken afterwards.
    harness.stop(bg_id, plan["config_dir"])
    return True


# ----- what a caller is told while the turn runs -----

class Listener:
    """One turn's stream, turned into events a caller can act on.

    Two kinds, and they are different in kind rather than in degree:

    - `action`: the house picked up a tool, named from `keel/narration.py`'s CLOSED SET.
      Nothing a tool was given can reach it, so a path, a branch name or a secret in a
      command line cannot travel even by accident. The gateway speaks these in HARBOR's
      voice, because they are the gateway talking about a house.
    - `part`: a finished sentence of the house's OWN ANSWER, cut by `keel/sentences.py`
      while the rest is still being written. The gateway speaks these in the HOUSE's voice,
      because the house said them (V8). This is what makes an answer start being heard a
      second after it starts being written instead of a minute later.

    THE REPEAT RULE IS APPLIED HERE AS WELL AS AT THE GATEWAY, on purpose and for the same
    reason `narration.Narrator` applies it: a line that will never be spoken should not be
    written or sent, and the two questions ("is this worth sending" and "is this worth
    saying now") are asked by different processes with different information.
    """

    def __init__(self, on_event=None):
        self.on_event = on_event
        self.cutter = sentences.Cutter()
        self.last_action: str | None = None
        # WHAT THIS TURN GOT AS FAR AS, in order and without repeats: the record a turn
        # that is ENDED rather than answered leaves on the card (`converse.record_stopped`).
        self.seen: list[str] = []
        self.parts: list[str] = []

    def _send(self, event: dict) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:                                               # noqa: BLE001
            pass            # a listener that raises is never worth the turn it is watching

    def on_record(self, record: dict) -> None:
        """One stream record: its actions, then whatever of the answer it completed."""
        for tool, action in narration.actions_in(record):
            if narration.same_action(self.last_action, action):
                continue
            self.last_action = action
            if action not in self.seen:
                self.seen.append(action)
            self._send({"type": "action", "action": action, "tool": tool})
        text = harness.stream_text(record)
        if text:
            self._cut(self.cutter.feed(text))

    def finish(self) -> None:
        """The end of the turn: the last sentence has no whitespace after it, so without
        this the answer would be spoken up to its final full stop and no further."""
        self._cut(self.cutter.flush())

    def _cut(self, events: list[dict]) -> None:
        """Pass the cutter's events on, remembering the spoken ones.

        A `fence` travels exactly as a `part` does and is not counted as spoken: a code
        block is never read out loud (`keel/sentences.py`), and nothing downstream speaks
        the event today. It is carried because the page can show it and the blackboard
        will want it, and because a body that stopped here would have to be fetched again
        from a transcript to get it back.
        """
        for event in events:
            if event["type"] == sentences.PART:
                self.parts.append(event["text"])
            self._send(dict(event))


# ----- the one-shot turn, unchanged -----

def one_shot(plan: dict, prompt: str, *, timeout: int, on_event=None) -> dict:
    """One `claude -p --resume`, the way every connected turn ran before V12.

    STILL THE PATH FOR THE PHONE HARBOR'S SINGLE QUESTION, and still the FALLBACK for
    everything else: a server that is not answering, a conversation that will not open, a
    process that died mid-sentence. Nothing about it changed, including that it streams
    only when somebody is listening.
    """
    listener = Listener(on_event) if on_event is not None else None
    if listener is None:
        return harness.turn(plan["session_id"], prompt, timeout=timeout, **flags_of(plan))
    try:
        return harness.turn_streamed(plan["session_id"], prompt, timeout=timeout,
                                     on_record=listener.on_record, **flags_of(plan))
    finally:
        listener.finish()


# ----- the kept-alive conversation -----

class Live:
    """One TURN of one conversation, and everything already said about it.

    THIS IS WHAT MAKES A TURN IDEMPOTENT (review round 1, finding B). A sentence written to
    the process cannot be un-written, so a client whose stream broke must never be allowed
    to ask again: it would spend a second turn and he would hear the answer twice. Instead
    the turn is remembered by ITS OWN ID, with every event it has produced, and a second
    request naming that id ATTACHES: it is handed the events after the ones it says it has
    already had, then follows the turn live, then gets the same result.

    Two are kept per conversation, and only two: the one in flight and the one before it.
    A retry arrives within seconds and there is nothing to be gained by remembering an hour
    of them.
    """

    def __init__(self, turn_id: str):
        self.turn = turn_id
        self.events: list[dict] = []
        self.done = False
        self.payload: dict | None = None
        self.error: Exception | None = None
        # WHETHER HIS SENTENCE REACHED THE PROCESS. The client's whole no-double-delivery
        # rule turns on this one bit: a sentence that was never written may be asked again,
        # and one that was may not.
        self.wrote = False
        self.cond = threading.Condition()

    def add(self, event: dict) -> None:
        with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    def finish(self, payload: dict | None = None, error: Exception | None = None) -> None:
        with self.cond:
            self.done, self.payload, self.error = True, payload, error
            self.cond.notify_all()

    def follow(self, seen: int, on_event, deadline: float) -> dict:
        """Hand over everything after `seen`, then wait for the rest; the turn's result.

        The events are delivered OUTSIDE the lock: `on_event` writes to a socket, and a
        listener that blocks must not also block the turn that is producing them.
        """
        index = max(0, int(seen or 0))
        while True:
            with self.cond:
                pending = self.events[index:]
                index = len(self.events)
                done, payload, error = self.done, self.payload, self.error
                if not pending and not done:
                    self.cond.wait(timeout=0.5)
            for event in pending:
                if on_event is not None:
                    on_event(event)
            if done:
                if error is not None:
                    raise error
                return payload or {}
            if time.time() > deadline:
                raise harness.HarnessError("that turn is still running and the wait ran out")


class Entry:
    """One card's live conversation, the lock that keeps it to one turn at a time, and the
    two turns it remembers."""

    def __init__(self, talk):
        self.talk = talk
        self.lock = threading.Lock()
        self.opened = time.time()
        self.turns = 0
        # SOMEBODY IS ENDING THIS CONVERSATION ON PURPOSE. A turn that fails while this is
        # set failed because of the close, so it is reported as an ordinary failure and
        # never as `Dead`: falling back would ask the house the question he has just
        # walked away from.
        self.closing = False
        self.turn_lock = threading.Lock()
        self.live: Live | None = None
        self.last: Live | None = None

    @property
    def idle(self) -> float:
        return time.time() - getattr(self.talk, "last_said", self.opened)

    def find(self, turn_id: str) -> Live | None:
        """The turn with this id, running or just finished, or None. Takes no big lock, so
        it can be asked while a turn is in flight, which is the whole point of it."""
        if not turn_id:
            return None
        with self.turn_lock:
            for one in (self.live, self.last):
                if one is not None and one.turn == turn_id:
                    return one
        return None

    def begin(self, turn_id: str) -> Live:
        live = Live(turn_id)
        with self.turn_lock:
            if self.live is not None:
                self.last = self.live
            self.live = live
        return live

    def ended(self, live: Live) -> None:
        with self.turn_lock:
            if self.live is live:
                self.live, self.last = None, live


class Sessions:
    """Every live conversation this process owns, one per card id.

    Held by `keel serve` (`SESSIONS` below), because it is the only thing on the machine
    long-lived enough to own a process between two sentences. Every method is safe to call
    from a request thread; `close` and `reap` are safe to call while a turn is running,
    because closing takes the entry's own lock.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.live: dict[str, Entry] = {}
        # ONE OPEN AT A TIME PER CARD. Two threads that both found no conversation used to
        # both start a `claude` and then shut one of them: two processes on a 12 GB box,
        # two transcript reads, and a session briefly held by a process about to be killed.
        # The check and the start have to be inside the same lock, and it is per card so a
        # slow open on one conversation does not hold up another.
        self.openers: dict[str, threading.Lock] = {}
        self._reaper: threading.Thread | None = None

    # -- the registry --------------------------------------------------- #

    def count(self) -> int:
        with self.lock:
            return len(self.live)

    def entry(self, card_id: str) -> Entry | None:
        with self.lock:
            return self.live.get(card_id)

    def busy(self) -> str:
        """What a code-moved restart would cut (`keel/restart.py`): an open conversation,
        or one being opened, in words; "" when there is neither."""
        with self.lock:
            live = sorted(self.live)
            opening = sorted(card for card, opener in self.openers.items()
                             if opener.locked() and card not in self.live)
        if live:
            return f"a conversation is open on {', '.join(live)}"
        if opening:
            return f"a conversation is opening on {', '.join(opening)}"
        return ""

    def state(self) -> list[dict]:
        """What is open, for `/api/house` and for the doctor: no words, only facts."""
        with self.lock:
            return [{"card": card, "turns": entry.turns,
                     "idle": round(entry.idle, 1), "alive": bool(entry.talk.alive)}
                    for card, entry in sorted(self.live.items())]

    def open(self, plan: dict, *, timeout: int = harness.TURN_TIMEOUT) -> Entry:
        """This card's conversation, opening one if there is none that is still alive.

        WARM AND FREE. Opening costs no tokens: the process starts, reads the transcript
        and waits on its stdin. That is the whole reason `--connect` opens one before he
        has said anything, so the boot happens under "Connecting you now" and the tone.

        A SECOND OPEN NEVER DOUBLES, AND NEVER STARTS TWO PROCESSES EITHER. The check and
        the start are inside one per-card lock: without it two threads both found nothing,
        both started a `claude`, and one of the two was shut immediately after reading a
        transcript nobody wanted. The live one is handed back; a dead one is replaced,
        because a half-read stream would answer the next sentence with the tail of the last.
        """
        with self.lock:
            opener = self.openers.setdefault(plan["card"], threading.Lock())
        with opener:
            with self.lock:
                entry = self.live.get(plan["card"])
                if entry is not None and entry.talk.alive:
                    return entry
                if entry is not None:
                    self.live.pop(plan["card"], None)
            if entry is not None:
                _shut(entry.talk)
            talk = harness.open_conversation(plan["session_id"], timeout=timeout,
                                             **flags_of(plan), **extras_of(plan))
            entry = Entry(talk)
            with self.lock:
                self.live[plan["card"]] = entry
            return entry

    def say(self, plan: dict, said: str, *, framing: str = "", plain: str = "",
            turn_id: str = "", seen: int = 0, timeout: int = harness.TURN_TIMEOUT,
            on_event=None) -> dict:
        """One sentence into this card's conversation; the turn's own result payload.

        THE FRAMING IS SAID ONCE (V12). `prompts.converse` wraps every sentence on the
        one-shot path because each of those is a fresh process with no memory of the last.
        In a kept-alive conversation the rules are in the transcript after the first
        sentence, so the FIRST sentence of a session carries them and every later one
        carries just his quoted words. Which of the two is used is decided HERE, because
        whether this session is new is a fact about the process and nothing else knows it.

        A TURN IS ASKED FOR BY ID, AND ASKING TWICE ASKS THE HOUSE ONCE (finding B). A
        `turn_id` this conversation already knows ATTACHES to that turn rather than writing
        the sentence again: the caller is handed the events after the `seen` it has already
        had, follows the rest live, and gets the same result. That is what makes a client
        retry after a broken stream safe, and it is checked BEFORE the turn lock, because
        the turn being attached to is usually the one holding it.

        THE TURN IS COUNTED AS SOON AS THE LINE IS WRITTEN, not when it succeeds. Counting
        on success meant a turn that errored with the process still alive left the count at
        zero, so the NEXT sentence was sent the whole framing again: tokens spent saying
        what the transcript already held, on the turn after something went wrong.

        A FAILURE THE PROCESS DID NOT SURVIVE LEAVES NO SESSION BEHIND: the entry goes with
        it, so the caller's fallback runs against a clean registry.
        """
        entry = self.open(plan, timeout=timeout)
        deadline = time.time() + timeout
        attached = entry.find(turn_id)
        if attached is not None:
            return attached.follow(seen, on_event, deadline)
        with entry.lock:
            attached = entry.find(turn_id)
            if attached is not None:
                # Nothing is running (this thread holds the lock), so this one is finished
                # and `follow` hands back what it already has without waiting.
                return attached.follow(seen, on_event, deadline)
            live = entry.begin(turn_id or _turn_id())
            listener = Listener(lambda event: (live.add(event),
                                               on_event(event) if on_event else None))

            def written() -> None:
                live.wrote = True
                entry.turns += 1

            try:
                payload = entry.talk.say(framing if entry.turns == 0 else (plain or said),
                                         on_record=listener.on_record, timeout=timeout,
                                         on_written=written)
            except harness.HarnessError as error:
                listener.finish()
                if not live.wrote:
                    # IT NEVER REACHED THE PROCESS, so it may be asked again. This is the
                    # one failure the caller is allowed to fall back on without risking a
                    # second turn on the same sentence.
                    failure = NotSent(str(error))
                elif entry.talk.alive or entry.closing:
                    failure = error     # the turn errored, or he ended the conversation
                else:
                    failure = Dead(str(error))
                if isinstance(failure, Dead) or isinstance(failure, NotSent):
                    # THE ENTRY GOES, BUT NOT THROUGH `close`: this thread already holds
                    # the entry's lock, and `close` takes it. It is dropped from the
                    # registry here and shut directly, which is the same end by the one
                    # route that cannot deadlock against the turn that failed.
                    self._forget(plan["card"], entry)
                    _shut(entry.talk)
                live.finish(error=failure)
                entry.ended(live)
                raise failure from None
            listener.finish()
            live.finish(payload=payload)
            entry.ended(live)
        return payload

    def close(self, card_id: str) -> bool:
        """End this card's conversation. True when there was one. Never raises.

        CALLED BEFORE EVERY WAKE, on every path that ends a hold: "back to Harbor", the
        drain clearing one that ran out, his Stop from the deck, his answer at a gate. A
        `claude --resume --bg` while a headless process still holds the session is the
        refusal that started all of this, so the order is not a nicety.
        """
        entry = self._forget(card_id)
        if entry is None:
            return False
        # A TURN IN FLIGHT IS WAITED FOR, BRIEFLY, AND THEN ENDED. The lock is what makes a
        # close safe while another thread is mid-sentence, and a short turn finishes inside
        # the wait so the process goes after it tidily. Past that his release wins: the
        # process is shut under the turn, which ends it, because a release that blocked for
        # the length of a five minute turn would time out in the gateway and he would be
        # told "that did not come back" about the one thing that always works.
        entry.closing = True
        held = entry.lock.acquire(timeout=CLOSE_WAIT)
        try:
            _shut(entry.talk)
        finally:
            if held:
                entry.lock.release()
        return True

    def _forget(self, card_id: str, entry: "Entry | None" = None) -> "Entry | None":
        """Drop this card from the registry and hand back what was there, if anything.
        With `entry`, only that one is dropped, so a close cannot take a conversation a
        later open has already put in its place."""
        with self.lock:
            if entry is not None and self.live.get(card_id) is not entry:
                return None
            return self.live.pop(card_id, None)

    def close_all(self) -> int:
        with self.lock:
            cards = list(self.live)
        return sum(1 for card in cards if self.close(card))

    # -- the idle deadline ------------------------------------------------ #

    def reap(self, idle_seconds: float) -> list[str]:
        """Close every conversation quiet for longer than the hold; the cards closed.

        THE SAME CLOCK AS THE HOLD, because they are the same fact: the hold is what says
        he is still talking to this house, and a process kept past it is memory held for a
        conversation that ended. The drain clears the hold itself and wakes the house; this
        is the process side of the same expiry, and either order is safe because the close
        is what the wake needs.
        """
        closed = []
        for card, entry in list(self.live.items()):
            if entry.idle >= idle_seconds or not entry.talk.alive:
                if self.close(card):
                    closed.append(card)
        return closed

    def watch(self, idle_seconds: float, every: float = REAP_EVERY) -> None:
        """Start the reaper, once. A daemon thread: it must never hold the server open."""
        if self._reaper is not None:
            return

        def loop():
            while True:
                time.sleep(every)
                try:
                    self.reap(idle_seconds)
                except Exception:                                       # noqa: BLE001
                    pass    # a reaper that dies would leak processes, quietly, for hours

        self._reaper = threading.Thread(target=loop, name="house-reap", daemon=True)
        self._reaper.start()


def _turn_id() -> str:
    """An id for a turn nobody named. The gateway always names one; a `keel converse` run
    from the deck does not, and a turn with no id could not be attached to."""
    return secrets.token_hex(6)


def _shut(talk) -> None:
    try:
        talk.close()
    except Exception:                                                   # noqa: BLE001
        pass


# THE ONE REGISTRY, and it belongs to whichever process imported it: `keel serve`, which
# is the only long-lived one. A CLI that imports this module and never opens anything holds
# an empty dict, which costs nothing.
SESSIONS = Sessions()
