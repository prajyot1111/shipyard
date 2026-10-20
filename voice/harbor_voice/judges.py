"""The judges: one interface, two implementations, and a switch per answer.

A JUDGE is a named decision point with a typed verdict and two implementations behind the
same call: the RULE, which is what decides today (possibly "always proceed"), and JEV. V10
names two, and this module is the contract every seat builds against. Its shape was settled
at c-313's plan gate and approved as written; slices 2, 3 and 7 (c-311, c-314, c-317) build
against it, so it does not change without a note on all three.

WHAT c-317 ADDED, and the note it owes the other two: `shadow_busy()` and `skipped()`. Both
exist because the `narrate` seat is the first one asked MANY TIMES IN ONE TURN (per house
activity event, V5) rather than once per utterance, and the shadow slot is one and is
shared. Neither changes how `ask` behaves, so `preturn` reads exactly as it did; what they
give a chatty seat is a way to stand down from the slot on purpose and to say in the log
that it did. Nothing in the interface above moved.

WHAT c-552 ADDED, and the note it owes the three: `ask(answers=...)` and `ask(facts=...)`,
and `outcome(**fields)`. `answers` names which of a judge's answers this call asks (by
default, the ones the rule gave a verdict for, which is what every seat already passed), so
a seat can leave out one that means nothing in the state it is in (`route` while pinned,
where c-542 found it wrong 4 of 6 times and nothing reads it). `facts` are a few words
about the turn that ride on the call line (the page's space, the card the turn touches,
whether the listen was hands-free) so the report can keep work turns out without reading
what was said. An outcome may now carry fields (the card a talker connected to, the deck
reads it made). Leaving all three out reads exactly as before.

WHY FOUR NEW SEATS ARE ANSWERS ON `preturn` AND NOT JUDGES (c-552, his call at the plan
gate). Three are asked at the same moment `preturn` is, and the client holds ONE
connection behind ONE lock with a budget that includes the wait for it: four calls a turn
would queue, and the later ones would time out as misses. One call, many answers, is rule
4 below. The call line records how many questions rode it (`questions`), so the report can
show whether the wider call got slower.

WHAT A SEAT WRITES, and it is the whole of the interface:

    rule = judges.rule("preturn", complete=True, addressed=True, route="talk")
    ruling = judges.ask("preturn", said, rule, turn=turn.id, criteria={"route": menu})

    if ruling["complete"].value is False:
        hold(said)                      # entered only when that answer is `on`

    judges.outcome(turn.id, "carried-on")       # later, when the turn says who was right

    with judges.pretend(complete=(False, 0.91)):     # in a test, with no network anywhere
        ...

THE FOUR RULES THAT MAKE IT SAFE TO BUILD AGAINST.

1. `ask` ALWAYS returns a `Ruling`. Immediately in `off` and `shadow`, within the budget in
   `on`. It never raises and never blocks past the budget, so a seat needs no try/except
   and no timeout of its own. Every failure, a timeout, an error, a missing key, a
   malformed answer, is the rule's verdict and a counted miss: never a stall and never a
   spoken error.
2. Every answer carries its own `source`, `rule` or `jev`. In `off` and `shadow` every
   source is `rule`, so a seat written today behaves identically whatever the switch later
   says. That is what "on day one Jev decides NOTHING" is, as a mechanism.
3. The switch is per ANSWER, not per judge, which is what V10's four keys mean. A judge
   AWAITS its call only when at least one of its answers is `on`; otherwise the call runs
   on the shadow thread beside the turn and is never awaited, so shadowing costs the turn
   nothing.
4. A judge asks Jev ONCE per call whatever the number of answers, so `preturn` costs one
   round trip for three answers.

THE SWITCH is `keel/judges.py`'s, read here and never written here: `[voice.judges]` in
`keel.toml` for the shipped defaults, `state/voice/judges.json` for the live override that
`keel voice judge` writes. Both are read on their mtime at the start of each turn, so a
flip needs no restart and no deploy. A key nothing names reads `off`, and a key that is
`on` with no confidence floor reads `shadow`: the fallback is never the one that starts
sending his transcripts out.

THE SHADOW LOG is `state/voice/judges.jsonl`, append-only, and it is the evidence for a
flip. One line per call, one line per outcome, and (written by the verb, not here) one line
per flip. Nothing here ever turns a judge on.
"""

import contextlib
import json
import re
import threading
import time
import tomllib

from harbor_voice import config, jev as jev_module

# V10's keys, and they are the code's rather than the file's. Kept identical to
# `keel.judges.KEYS`; `fixtures/judges_switch.json` is read by both suites so the two
# cannot drift silently. The last four are c-542's ranked seats (c-552), each an answer on
# the one `preturn` call rather than a judge of its own: see "WHAT c-552 ADDED" above.
KEYS = ("preturn.complete", "preturn.addressed", "preturn.route", "narrate",
        "preturn.card", "preturn.prefetch", "preturn.repair", "preturn.bargein")
MODES = ("off", "shadow", "on")
FALLBACK = "off"

# WHAT THEN HAPPENED, which is the column that says who was right. V10 names the first
# four; `answered` is the ordinary ending, and `ended-quietly` was added with the paths
# that can end a turn without answering it (c-314: an `addressed: no` verdict, and the
# words that close a conversation). A turn that ended quietly is not one that was
# answered, and reading the report would be harder if it had to pretend otherwise.
OUTCOMES = ("carried-on", "barged-in", "abandoned", "label-corrected", "answered",
            "ended-quietly", "connected", "reads")


# ----- the typed verdict -----

class Answer:
    """One typed answer: what was decided, how sure, and by which implementation."""

    __slots__ = ("value", "confidence", "source")

    def __init__(self, value, confidence: float = 1.0, source: str = "rule"):
        self.value = value
        self.confidence = float(confidence)
        self.source = source

    def __repr__(self) -> str:
        return f"Answer({self.value!r}, {self.confidence:g}, {self.source})"

    def __eq__(self, other) -> bool:
        return (isinstance(other, Answer) and other.value == self.value
                and other.confidence == self.confidence and other.source == self.source)


class Ruling:
    """A judge's answers. Indexing is the read a seat uses; `.value` is for a default."""

    __slots__ = ("judge", "answers")

    def __init__(self, judge: str, answers: dict[str, Answer]):
        self.judge = judge
        self.answers = answers

    def __getitem__(self, name: str) -> Answer:
        return self.answers[name]

    def __contains__(self, name: str) -> bool:
        return name in self.answers

    def value(self, name: str, default=None):
        found = self.answers.get(name)
        return default if found is None else found.value

    def by(self, name: str) -> str:
        """Which implementation decided this answer: `rule` or `jev`."""
        found = self.answers.get(name)
        return "rule" if found is None else found.source

    def as_json(self) -> dict:
        return {name: {"value": a.value, "confidence": a.confidence, "source": a.source}
                for name, a in self.answers.items()}


def rule(judge: str, **values) -> Ruling:
    """What decides today, as a `Ruling`. Confidence 1.0: the rule is not guessing, it is
    the definition of what happens now."""
    return Ruling(judge, {name: Answer(value, 1.0, "rule") for name, value in values.items()})


# ----- the two judges V10 names -----

class Judge:
    """A named decision point: its answers, and how each is asked."""

    def __init__(self, name: str, questions: dict):
        self.name = name
        self.questions = questions

    def key(self, answer: str) -> str:
        """The switch key for one answer. `narrate` has one answer and no suffix."""
        return answer if answer == self.name else f"{self.name}.{answer}"


# THE `addressed` WORDING WAS WRONG ON 12 OF 33 PERSONAL TURNS (c-542), every one a plain
# question to the assistant doubted at 0.54 to 0.67, and never above 0.78. The old question
# ("was it said to their assistant, or to someone else who is there?") invites the doubt:
# a short question reads as either. This one says what makes speech NOT addressed, so the
# default is the ordinary case (c-552).
ADDRESSED_QUESTION = (
    "A voice assistant heard this. People mostly speak to it directly, in short questions, "
    "requests and remarks, often with misheard words. Is this meant for the assistant? "
    "Answer no only when it is plainly speech to another person in the room: it names or "
    "answers someone else, or it cannot make sense as something said to an assistant.")

# THE PREFETCH MENU (c-552, c-542 seat 3): the deck reads the voice framing names
# (`harbormsg.DIGEST_NOTE`), as sections. `keel deck <section>` for the first four, `kb show`
# for one card, `kb needs-you`. `READ_SECTIONS` is what `harborlive` maps a talker's tool
# call onto, so the truth and the question speak the same names.
READ_SECTIONS = ("cards", "reviews", "segments", "bosun", "card", "needs_you")

# THE CLOSED VOCABULARY FOR HEARING REPAIR (c-552, c-300 overlooked place 4): the names
# this product is made of, which is what Parakeet mishears ("Boson", "cardree", "pouse").
# Closed and short on purpose: many-class questions are Jev's stated weak spot (c-542
# source 2). Every one is a term `etc/dictation-vocabulary.md` or `hearing.py` already
# carries; this adds no vocabulary.
REPAIR_VOCABULARY = ("Keel", "Harbor", "Bosun", "Jev", "card", "board", "deck", "house",
                     "pane", "tree", "capture", "segment", "review", "inbox", "backlog")

def read_section(tool: str, given: dict) -> str:
    """The prefetch section one talker tool call read, or "" when it read none (c-552).

    The truth for `preturn.prefetch` is the FIRST of these in a turn. Only the section's
    name is ever kept, never the command's arguments, so a card id or a search term he said
    never reaches the log."""
    if tool != "Bash":
        return ""
    command = str((given or {}).get("command") or "")
    found = re.search(r"\bkeel deck\s+(cards|reviews|segments|bosun)\b", command)
    if found:
        return found.group(1)
    if re.search(r"\bkb\s+show\b", command):
        return "card"
    if re.search(r"\bkb\s+needs-you\b", command):
        return "needs_you"
    if re.search(r"\bkb\s+(list|queue)\b", command):
        return "cards"
    return ""


PRETURN = Judge("preturn", {
    "addressed": jev_module.noul(
        ADDRESSED_QUESTION,
        yes="Meant for the assistant", no="Plainly said to another person"),
    "complete": jev_module.noul(
        "Is the speaker's thought finished, or did they stop part way through a sentence?",
        yes="The thought is finished and can be answered",
        no="They paused mid-sentence and are still speaking"),
    "route": jev_module.choice(
        "The speaker said this to their personal assistant, which runs a board of work "
        "cards. Where should the utterance go?",
        {"talk": "A question or remark that needs a conversation",
         "capture": "Dictates an idea or a task to be saved as a new card",
         "board_read": "Asks for one of the fixed facts that can be read straight off the board",
         "other": None}),
    # WHICH CARD, BY DESCRIPTION (c-542 seat 2). The menu is the caller's (the personal
    # cards in the digest the turn already holds), handed in through `criteria`; with no
    # menu it is not asked. Rule: `none`, because the talker is what picks the card today.
    "card": jev_module.choice(
        "The speaker said this to their assistant, which can put them through to the "
        "worker on one card. If they are asking to be put through, which card do they "
        "mean? If they are not asking to be put through, answer none.",
        {"none": "Not asking to be put through to a card"}),
    # WHAT THE TURN WILL READ (c-542 seat 3). Rule: `none`, because the digest is all a
    # turn is handed today; the truth is the first deck read the talker then made.
    "prefetch": jev_module.choice(
        "The speaker asked their assistant this. It already holds a short summary of their "
        "board. Which one fuller read of the board would it need to answer, if any?",
        {"cards": "The full list of cards, beyond the summary",
         "reviews": "The code reviews and pull requests",
         "segments": "The segments and their headlines",
         "bosun": "Bosun's requests and questions",
         "card": "One card they named, in full",
         "needs_you": "What is waiting on them",
         "none": "The summary answers it, or it needs no board at all"}),
    # A MISHEARD NAME (c-300's hearing repair, c-542 seat 5). Asked after the exact-string
    # table has run, so what it measures is what the table missed. Rule: `none`.
    "repair": jev_module.choice(
        "A speech model transcribed this and often mishears proper names. Is one of these "
        "names in it, misheard as a different word? If none was misheard, answer none.",
        {**{word: None for word in REPAIR_VOCABULARY},
         "none": "No name here was misheard"}),
    # BARGE-IN (c-542 seat 6). Asked only on the first utterance after he cut an answer
    # off. Rule: `true`, because the press did cut it.
    "bargein": jev_module.noul(
        "The assistant was speaking, the listener cut it off, and then said this. Was it an "
        "interruption with something new to say?",
        yes="A new request, a question, or a correction: stop and answer this",
        no="A backchannel such as mm-hm, yeah or go on: they wanted it to keep talking"),
})

NARRATE = Judge("narrate", {
    "narrate": jev_module.noul(
        "A background task just did this. Is this step worth saying out loud to someone "
        "who is listening while it works?",
        yes="Worth saying: it changes what they know or what they would do",
        no="Not worth saying: routine, or a detail of a step already mentioned"),
})

JUDGES = {judge.name: judge for judge in (PRETURN, NARRATE)}


# ----- the switch, read on mtime -----

class Switch:
    """The effective mode per key, re-read only when either file changes.

    An ordinary turn costs two `stat` calls. This is the one place the gateway reads
    `keel.toml`, and `config.KEEL_TOML` says why."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stamp = None
        self._table: dict[str, dict] = {}

    def _fingerprint(self) -> tuple:
        out = []
        for path in (config.KEEL_TOML, config.JUDGES_SWITCH):
            try:
                stat = path.stat()
                out.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def table(self) -> dict[str, dict]:
        stamp = self._fingerprint()
        with self._lock:
            if stamp != self._stamp:
                self._table = self._read()
                self._stamp = stamp
            return self._table

    def _read(self) -> dict[str, dict]:
        shipped = self._toml("judges")
        bars = self._toml("judge_floors")
        live = self._override()
        out = {}
        for key in KEYS:
            if key in live:
                mode, source = live[key], "override"
            elif str(shipped.get(key)) in MODES:
                mode, source = str(shipped[key]), "default"
            else:
                mode, source = FALLBACK, "fallback"
            try:
                floor = float(bars[key])
            except (KeyError, TypeError, ValueError):
                floor = None
            held = mode == "on" and floor is None
            out[key] = {"mode": "shadow" if held else mode, "from": source,
                        "floor": floor, "held": held}
        return out

    @staticmethod
    def _toml(name: str) -> dict:
        try:
            with open(config.KEEL_TOML, "rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        table = (data.get("voice") or {}).get(name) or {}
        return {key: table[key] for key in KEYS if key in table}

    @staticmethod
    def _override() -> dict[str, str]:
        try:
            data = json.loads(config.JUDGES_SWITCH.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {key: str(data[key]) for key in KEYS
                if key in data and str(data[key]) in MODES}


SWITCH = Switch()


def modes(judge: str) -> dict[str, dict]:
    """One entry per answer of this judge, keyed by ANSWER name rather than switch key,
    because that is what a seat and a log line both speak in."""
    spec = JUDGES[judge]
    table = SWITCH.table()
    out = {}
    for answer in spec.questions:
        entry = dict(table.get(spec.key(answer)) or
                     {"mode": FALLBACK, "from": "fallback", "floor": None, "held": False})
        if _PRETEND and answer in _PRETEND[-1]:
            entry.update({"mode": "on", "floor": 0.0, "held": False, "from": "pretend"})
        out[answer] = entry
    return out


# ----- the log -----

_LOG_LOCK = threading.Lock()


def _append(row: dict) -> None:
    """Append-only, one open per line. The volume is one line a turn, and append-only is
    what makes it safe for the shadow thread to write while a turn is running."""
    try:
        config.JUDGES_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK, config.JUDGES_LOG.open("a") as out:
            out.write(json.dumps(row) + "\n")
    except OSError:
        pass                    # a log that cannot be written is never a failed turn


def outcome(turn: str, what: str, **fields) -> None:
    """What then happened, which is the thing that says who was right.

    Written as its own line rather than back into the call's line: the outcome is known
    seconds later, and in `shadow` the call may not even have landed when the turn ends.
    `fields` say more about it where one word cannot (c-552): `connected` carries the
    `card`, `reads` carries the `sections` the talker read. Never words he said."""
    row = {"at": _now(), "kind": "outcome", "turn": str(turn), "outcome": str(what)}
    row.update({key: value for key, value in fields.items() if key not in row})
    _append(row)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


# ----- asking -----

CLIENT = jev_module.Jev()

_PRETEND: list[dict] = []           # a stack of one: see `pretend`
_SHADOW = None                      # the one worker thread, built on first need
_SHADOW_BUSY = threading.Lock()


def ask(judge: str, state: str, ruling: Ruling, *, turn: str = "",
        criteria: dict | None = None, answers=None, facts: dict | None = None) -> Ruling:
    """Ask a judge. Always returns a `Ruling`; never raises; never blocks past the budget.

    `ruling` is what the rule decided, from `judges.rule`. `criteria` replaces one
    question's criteria for this call, which is how `route` is handed the board-read menu
    that the caller owns and this module should not. `answers` names the answers this call
    asks; left out, it is every answer the RULE gave a verdict for, which is what every
    seat asked before c-552 (an answer with no rule verdict has nothing to be compared
    against). One not asked is neither sent nor logged, and the rule's verdict stands for
    it. `facts` ride on the call line as they are (c-552)."""
    spec = JUDGES.get(judge)
    if spec is None:
        return ruling
    table = modes(judge)
    wanted = set(ruling.answers if answers is None else answers)
    table = {name: entry for name, entry in table.items() if name in wanted}
    asked = {name: entry for name, entry in table.items() if entry["mode"] != "off"}
    if not asked:
        return ruling                       # nothing to ask, nothing to log
    questions = _questions(spec, asked, criteria)
    extra = dict(facts or {})
    awaited = any(entry["mode"] == "on" for entry in asked.values())
    if not awaited:
        _shadow(judge, state, ruling, turn, questions, table, extra)
        return ruling
    reply, miss = _call(state, questions)
    decided = _merge(ruling, table, reply)
    _log(judge, state, turn, ruling, table, reply, miss, decided, questions, extra)
    return decided


def _questions(spec: Judge, asked: dict, criteria: dict | None) -> dict:
    out = {}
    for name in asked:
        question = dict(spec.questions[name])
        if criteria and name in criteria:
            question["criteria"] = dict(criteria[name])
        out[name] = question
    return out


def _call(state: str, questions: dict):
    """(reply or None, miss reason). The one place a `JevError` becomes a counted miss."""
    client = _PRETEND[-1]["client"] if _PRETEND else CLIENT
    try:
        return client.ask(state, questions), ""
    except jev_module.JevError as exc:
        return None, exc.reason
    except Exception:                                                   # noqa: BLE001
        return None, "error"


def _merge(ruling: Ruling, table: dict, reply) -> Ruling:
    """Per answer: Jev decides only when its answer is `on`, arrived, and cleared the floor.

    Anything else is the rule's verdict, which is what "fail open" means here."""
    if reply is None:
        return ruling
    answers = dict(ruling.answers)
    for name, entry in table.items():
        said = reply.answers.get(name)
        if entry["mode"] != "on" or said is None:
            continue
        floor = entry["floor"]
        if floor is None or said["confidence"] < floor:
            continue
        answers[name] = Answer(said["value"], said["confidence"], "jev")
    return Ruling(ruling.judge, answers)


def _log(judge: str, state: str, turn: str, ruling: Ruling, table: dict,
         reply, miss: str, decided: Ruling, questions: dict | None = None,
         facts: dict | None = None) -> None:
    row = {
        "at": _now(), "turn": str(turn), "judge": judge,
        "modes": {name: entry["mode"] for name, entry in table.items()},
        "text": state,
        "rule": {name: answer.value for name, answer in ruling.answers.items()
                 if name in table},
        "jev": dict(reply.answers) if reply is not None else {},
        "latency": round(reply.seconds, 4) if reply is not None else None,
        "miss": miss,
        "decided_by": {name: answer.source for name, answer in decided.answers.items()
                       if name in table},
    }
    # HOW MANY QUESTIONS RODE THIS CALL (c-552): the one call now carries up to seven, and
    # this is what lets the report say whether the wider call got slower.
    if questions is not None:
        row["questions"] = len(questions)
    if facts:
        row["facts"] = facts
    _append(row)


# ----- the shadow thread -----

def _shadow(judge, state, ruling, turn, questions, table, facts=None) -> None:
    """Run the call beside the turn and never wait for it.

    A queue of one, the shape `HARBOR_TURN_QUEUE_MAX` already has in this package: a second
    shadow call while one is in flight is dropped and counted, because a shadow call that
    queues would be spending the budget of a turn that has already moved on."""
    if not _SHADOW_BUSY.acquire(blocking=False):
        _log(judge, state, turn, ruling, table, None, "busy", ruling, questions, facts)
        return

    def run():
        try:
            reply, miss = _call(state, questions)
            _log(judge, state, turn, ruling, table, reply, miss, ruling, questions, facts)
        finally:
            _SHADOW_BUSY.release()

    thread = threading.Thread(target=run, name="judge-shadow", daemon=True)
    thread.start()
    global _SHADOW
    _SHADOW = thread


def shadow_busy() -> bool:
    """Is a shadow call in flight right now (c-317, the `narrate` seat).

    THE SLOT IS ONE AND IT IS SHARED BY EVERY JUDGE, which is fine for a seat asked once
    per utterance and wrong for one asked per house activity event: `narrate` fires up to
    twenty times in a long connected turn, and every one of those would be a chance to
    drop the `preturn` call that has a turn WAITING on it. So the seat that has nothing
    waiting on it asks this first and stands down, rather than racing for the slot and
    logging the loser as `busy`.

    Advisory by nature: the answer can be stale the instant it is read, which is why the
    real protection is still `_shadow`'s own non-blocking acquire. This only stops the
    common case, which is a seat firing into a slot it can see is taken.
    """
    if _SHADOW_BUSY.acquire(blocking=False):
        _SHADOW_BUSY.release()
        return False
    return True


def skipped(judge: str, state: str, ruling: Ruling, *, turn: str = "",
            why: str = "skipped") -> None:
    """The seat decided not to ask, and the log says so (c-317).

    A judge that is simply not asked writes nothing, which is right for `off` ("nothing to
    ask, nothing to log"). It is WRONG for a seat that throttles itself: a report showing
    five `narrate` calls on a forty-event turn would read as a quiet turn rather than a
    capped one, and the difference is the whole question of whether the cap is set right.

    So this writes an ordinary call line with the rule's verdict on it and `miss` set to
    the reason, which `keel/judges.py`'s tally already handles: a miss is an absence, never
    counted as an agreement or a disagreement.
    """
    table = modes(judge)
    if not table:
        return
    asked = {name: entry for name, entry in table.items() if entry["mode"] != "off"}
    if not asked:
        return
    _log(judge, state, turn, ruling, asked, None, why, ruling)


def wait_for_shadow(timeout: float = 5.0) -> bool:
    """Only a test waits: the gateway never does, and that is the point of `shadow`."""
    thread = _SHADOW
    if thread is None:
        return True
    thread.join(timeout)
    return not thread.is_alive()


# ----- the fake judge -----

class _Fake:
    """Answers from a dict, with no network. V10 says the held and quiet paths are tested by
    a fake judge, so this is part of the contract rather than a test helper."""

    def __init__(self, answers: dict, seconds: float = 0.05, error: str = ""):
        self.answers = answers
        self.seconds = seconds
        self.error = error

    def ask(self, state: str, questions: dict):
        if self.error:
            raise jev_module.JevError(self.error, "the fake judge was told to fail")
        found = {name: {"value": value, "confidence": confidence}
                 for name, (value, confidence) in self.answers.items()
                 if name in questions}
        if not found:
            raise jev_module.JevError("malformed", "the fake judge was asked nothing it knows")
        return jev_module.Reply(found, self.seconds, "req_fake")


@contextlib.contextmanager
def pretend(_error: str = "", **answers):
    """Force the named answers `on` with a fake judge behind them.

    Each value is `(value, confidence)`. The floor is 0 for the duration, so a test states
    the confidence it means rather than also having to arrange a floor. `pretend(_error=
    "timeout")` makes every call fail that way instead, which is how a seat proves it fails
    open."""
    client = _Fake({name: value for name, value in answers.items()}, error=_error)
    _PRETEND.append({"client": client, **{name: True for name in answers}})
    try:
        yield client
    finally:
        _PRETEND.pop()


# ----- what /voice/health says -----

def health() -> dict:
    """The effective switch, where it came from, and whether the judges can reach the key.

    One document, three readers: `keel doctor`, `keel voice status` and the voice page's
    settings sheet. `keel voice judges` reads the log instead, because that is a report
    about what happened and not about what is configured."""
    table = SWITCH.table()
    return {"keys": {key: {"mode": entry["mode"], "from": entry["from"],
                           "floor": entry["floor"], "held": entry["held"]}
                     for key, entry in table.items()},
            "log": str(config.JUDGES_LOG),
            "switch": str(config.JUDGES_SWITCH),
            "jev": CLIENT.as_json()}
