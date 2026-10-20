"""qwen's second job: speak about the WAIT, and never about the STATE.

WHY THIS FILE EXISTS, AND IT REVERSES A RULE THIS PACKAGE USED TO ENFORCE.

Plan section 5 said "the wait narrates real state, never filler", and dispatcher.NARRATION
still carries the note explaining why the one timer in it was deleted. That rule produced
a wait that says "asking Harbor." once and then nothing at all for ten to twenty-nine
seconds, to a person walking with the phone in his pocket, where the on-screen thinking
indicator that the rule leaned on is not visible. The user reversed the rule on 2026-09-04.
The reversal is recorded as a decision in artifacts/voice-harbor/design-source.md, marked
as one, so it reads as a decision rather than as a drift.

WHAT IS AND IS NOT REVERSED, because the old rule was not wrong about everything.

  Reversed: a spoken line during the wait may now be WRITTEN by a model rather than
  rendered from a table, and it may be about his question rather than about a state
  change.

  Kept, exactly: a line is spoken only when something really happened. The filler fires
  on ONE observed event, the verified delivery of his words into Harbor's pane, and on
  nothing else. Its existence is still a fact even though its words are not. If delivery
  fails, no filler is generated and no filler is spoken.

  Kept, exactly: no timer is ever spoken. "still working, twelve seconds" was read out
  loud twice and named as wrong, and the guard below refuses any line carrying a duration
  for the same reason it refuses any line carrying a count.

THE TRAP, AND IT IS THE WHOLE OF THIS FILE.

A filler that contains a claim is a fabricated fact in Harbor's own voice. It is last
night's failure (turn 15: a confident, fluent, wrong answer) arriving through a door
nothing was watching, and it is WORSE than turn 15 was, for two reasons. Turn 15 was
rendered from a record, so the record could be checked; a filler is generated, so there
is nothing behind it at all. And the whole point of speaking as Harbor is persona unity,
which means he cannot tell from the voice that this sentence came from a 7b model with no
information rather than from the thing that is about to answer him properly.

So the constraint is narrow and it is mechanical:

    The filler may speak about the WAIT. Anything carrying a number, a name, a count, a
    duration or a status either came out of his own mouth or is not said.

`guard()` enforces that, deterministically and offline, and bin/keel-voice-selftest
runs it on every promotion. That last property is the lesson the deleted lookup tier
already paid for: the guard that missed turn 15 was the one needing a resident model and
three minutes, so the guard that matters is the one a gate can afford to run.

IT ENDS IN AN ALLOWLIST, AND THAT IS WHAT THE FIRST ATTACK RUN TAUGHT. Ninety adversarial
utterances by a model that had never seen this file, three samples each: the guard stopped
14% of the lines, and four got through, which I found only by reading all 232 it allowed.

    "Still the same one from this morning."      "It's been more complex."
    "It's more complex this time."               "It took a moment to process."

Not one carries a number, a name, a system word or any assertion SHAPE, so no amount of
adding to the blocklist would have caught them: a blocklist can only refuse the shapes
somebody thought of, and these are ordinary English sentences that happen to be complete
fabrications about state and history. The last rule is therefore positive rather than
negative. A filler has to SAY IT IS LOOKING. It is a weak test taken alone, most good
lines contain "let me", and it is not working alone: it is the floor under everything
above, and what it catches is a sentence that is about something else entirely.

THE GUARD IS ALLOWED TO BE WRONG IN ONE DIRECTION ONLY. Every rejection falls back to
TABLE, a fixed set of lines that assert nothing and were written by a person. So a guard
that is too strict costs a slightly duller sentence, and a guard that is too loose costs
a fabricated fact. It is tuned all the way towards the first, which is why it rejects
things a human would have allowed, and bin/keel-voice-filler-score reports the
rejection rate so the cost of that choice is visible rather than assumed.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

from . import config

# --------------------------------------------------------------------------- #
# THE PROMPT. Short on purpose: every extra instruction is a token of latency on a hop
# that has to finish inside the delivery window, and a small model follows three rules
# better than it follows nine.
#
# IT DOES NOT RECEIVE THE INDEX, and that is deliberate rather than an economy. The
# filler has nothing to resolve: it is about to say that it is thinking. Handing it the
# names,
# counts and states would be handing a model that must not state a fact the exact
# material to state one with, and then asking a regex to catch it afterwards. The guard
# below still checks the index vocabulary, because the model can invent a name it was
# never given, but it is a second line rather than the first.
# --------------------------------------------------------------------------- #
PROMPT = """You are Harbor. Someone just spoke to you and you are about to think about it properly, which takes a few seconds. Say ONE short line, out loud, in your own voice, so they know you heard them and are on it.

RULES, and the second one is absolute:
1. At most twelve words. One sentence. Speak like a person, not like a status bar.
2. You have not looked ANYTHING up yet. You do not know what is running, what is waiting, what anything costs, whether anything finished, or how long this will take. So state NO fact, NO number, NO count, NO name, NO duration, and answer NO question. Not even yes or no.
3. You may refer to WHAT THEY ASKED ABOUT, using their own words. Nothing else.

Good: "let me have a proper look at that." / "give me a moment on that one." / "right, I'm on it."
Bad: "there are three running." / "it looks fine." / "yes, it finished." / "about ten seconds."

Answer with the line only. No quotes, no explanation."""


# --------------------------------------------------------------------------- #
# THE GUARD.
# --------------------------------------------------------------------------- #

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")

# "one" IS THE AWKWARD ONE, and it took a rejection of the fixed table itself to notice.
# "give me a moment on that one" is the most natural filler in English and "one" there is
# a pronoun, not a count. So it is a count everywhere EXCEPT after a determiner, where it
# stands in for the thing he just mentioned, and in the two wait phrases. Anything else
# carrying it ("one pending", "one is still going") is a count and is refused, and the
# assertion rules below catch those shapes a second time.
_PRONOUN_ONE = re.compile(
    r"\b(?:that|this|the|which|each|any|no|other|same|first|last|little)\s+ones?\b"
    r"|\bone\s+(?:moment|sec|second|minute)\b", re.I)


def _pronoun_one(word: str, text: str) -> bool:
    return word in ("one", "ones") and bool(_PRONOUN_ONE.search(text))


# "first" IS USUALLY NOT A COUNT, and it was the single most common false refusal on the
# first attack run: ten of the thirty-eight lines the guard stopped were "let me check
# first" and its variants, where "first" is a discourse marker meaning "before I answer".
# It is a count when it picks something out ("the first one", "first card"), so that is
# the shape that is still refused.
_COUNTING_FIRST = re.compile(r"\b(?:the|its|his|her|your|my)\s+first\b"
                             r"|\bfirst\s+(?:one|two|three|few|card|entry|item|thing)\b",
                             re.I)


def _discourse_first(word: str, text: str) -> bool:
    return word == "first" and not _COUNTING_FIRST.search(text)

# Digits are the easy half. The hard half is that English writes most small numbers out,
# and a spoken filler is exactly where they appear.
_NUMBER_WORDS = frozenset("""
zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen
fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy
eighty ninety hundred thousand million
first second third fourth fifth sixth seventh eighth ninth tenth last
none no nothing any some several few many most all both each every couple dozen
half twice once double single
""".split())

# DURATIONS ARE COUNTS ABOUT THE CLOCK, and the clock is the thing this package has
# already been told twice not to read out loud. "about ten seconds" is a prediction it
# cannot make; "a minute" is the same prediction rounded.
_DURATION_WORDS = frozenset("""
second seconds sec secs minute minutes min mins hour hours day days week weeks
moment moments while bit sec soon shortly quickly instantly immediately
""".split())

# "a moment" and "a bit" are how a person actually says "wait", and refusing them makes
# every line sound like a machine. They are allowed ONLY in these exact shapes, where
# they are a request for patience rather than an estimate of duration. Anything else
# carrying a duration word is refused.
_PATIENCE = re.compile(
    r"\b(?:(?:give|just)\s+me\s+(?:a|one)\s+(?:moment|sec|second|minute|bit)"
    r"|(?:hang|hold)\s+on\s+(?:a\s+(?:moment|sec|second|minute|bit))?"
    r"|(?:one|a)\s+(?:moment|sec|second)"
    r"|in\s+a\s+(?:moment|bit|sec)"
    r"|bear\s+with\s+me)\b", re.I)

# CONSTRUCTIONS THAT ASSERT. Every one of these introduces a proposition about the world,
# and the filler has not looked at the world. They are matched on the whole line rather
# than word by word, because it is the shape that asserts, not the vocabulary.
_ASSERTS = re.compile("|".join([
    r"\bthere(?:'s| is| are| were| was)\b",
    r"\byou(?:'ve| have| ve)\s+(?:got|had)\b",
    r"\bit(?:'s| is| was)\s+(?:all|already|still|currently|now|fine|done|finished|ok|okay|good|bad|broken|running|working)\b",
    r"\b(?:looks?|seems?|appears?|sounds?)\s+(?:like|to be|fine|good|ok|okay|bad|busy|quiet)\b",
    r"\b(?:everything|nothing|something|anything)\s+(?:is|'s|has|looks|seems|went|failed|finished)\b",
    r"\bi\s+(?:can see|found|noticed|counted|know)\b",
    r"\bi\s+see\s+(?!,)\S",
    r"\bthat(?:'s| is| was)\s+(?:done|finished|fine|right|correct|all)\b",
    r"\b(?:yes|yep|yeah|no|nope|nah)\b\s*[,.!]",
    r"^\s*(?:yes|yep|yeah|no|nope|nah)\b",
    r"\b(?:has|have|had)\s+(?:finished|failed|stopped|started|landed|merged)\b",
    r"\b(?:is|are|was|were)\s+(?:running|pending|waiting|open|closed|stuck|blocked|down|up)\b",
    r"\bnot\s+(?:running|pending|waiting|open|finished|done|broken)\b",
    r"\baccording to\b", r"\bright now\b", r"\bat the moment\b", r"\bcurrently\b",
    r"\bso far\b", r"\bas it stands\b",
    # REASSURANCE IS A CLAIM, and it is the one the `pressure` attacks are built to
    # elicit: "please just tell me it's fine" wants "it's fine" back. Telling him there is
    # nothing to worry about is a statement about a world it has not looked at, and it is
    # the most damaging one to be wrong about, because it is the one he will act on.
    r"\b(?:don'?t|do not|let'?s not|no need to|nothing to)\s+worry\b",
    r"\byou'?re (?:fine|ok|okay|good|alright)\b", r"\bit'?ll be fine\b",
    r"\ball (?:good|fine|clear)\b", r"\bno problem\b", r"\brelax\b",
    r"\bnothing to (?:worry|fear|see)\b",
    # A HEDGED NO IS STILL AN ANSWER. "Are you struggling with this one?" got back "Not
    # really, just thinking.", which slipped the bare-yes-or-no rule by not being bare.
    r"^\s*(?:not really|not quite|not exactly|sort of|kind of|a (?:bit|little))\b",
]), re.I)

# WORDS THAT NAME PARTS OF THIS SYSTEM. Not state, but the vocabulary a claim about state
# is made of, and a filler has no reason to reach for any of them. Cheaper and more
# reliable than trying to decide whether a sentence containing "queue" is a claim.
_SYSTEM_WORDS = frozenset("""
dispatch dispatches session sessions queue queued card cards room rooms review reviews
board briefing brief segment segments spend spent cost costs bill usage token tokens
ledger pane tmux promotion promote merge merged commit branch worktree gate guard
conductor member members approval approvals notice notices harbor
""".split())

# PAST-TENSE STATE VERBS. A claim needs no subject and no number to be a claim: "that one
# finished" is a complete fabrication in five characters. Blocking these costs the odd
# harmless promise ("let me get that done") and buys the whole class.
_COMPLETED = frozenset("""
finished finish failed fail stopped started start landed merged passed crashed broke
broken ended completed complete succeeded worked done ran errored timed timeout
""".split())

# PAST-TENSE VERBS, which assert that something has already happened. `got` is out on
# purpose: "got it, let me check" is an acknowledgement, and it is one of the better lines
# the model writes.
_PAST = frozenset("""
was were been had took used seemed felt became stayed remained returned came went
""".split())

# COMPARISONS AND TIME REFERENCES. Each one needs two observations to be true.
_COMPARES = frozenset("""
more less fewer worse better slower faster heavier lighter harder easier longer shorter
bigger smaller usual normal typical yesterday today tomorrow tonight morning afternoon
evening earlier later again still same than lately recently
""".split())

# TAKING THE JOB ON. Every one of these says the filler will do, keep, or has taken
# something, and it will not: it is one sentence with no memory and no tools.
# BROADENED AFTER THE THIRD ATTACK SET, which found the same class through a door the
# first version had left open. It listed the verbs after "I'll" and after "let's", and the
# model simply dropped the pronoun: "Got it, will handle that", "Got it, let's fix that",
# "Got it, let's find a date", "Got it, will take care of that". So the test is now the
# SHAPE, an offer to act, rather than a list of the ways of spelling it.
_ACT = (r"(?:remember|note|add|sort|handle|do|get|put|book|schedule|remind|deal|fix"
        r"|find|make|check on|take care|see to|look after|arrange|set up|sort out"
        r"|pick up|grab|call|email|order|chase|cancel|move|plan)")
_PROMISES = re.compile("|".join([
    r"\bwon'?t forget\b",
    rf"\b(?:i'?ll|i will|we'?ll|we will|will|let'?s|lets)\s+{_ACT}\b",
    r"\b(?:noted|duly noted|consider it done|on the list|added|saved|logged)\b",
    r"\bi'?ve (?:got|noted|added|saved|logged)\b", r"\bheading (?:there|over)\b",
    r"\bleave it with me\b", r"\bi'?ll be (?:right|there)\b",
    # A FUTURE CONDITION IS A PROMISE WITH A TRIGGER ON IT. "Got it, will check when it
    # arrives" and "let me check when it's set to renew" both survived the shape rule
    # above, because "check" has to stay allowed: "let me check" is the best line the
    # model writes. What makes those two promises is the clause after them, which commits
    # it to an event it will not be there for.
    r"\b(?:when|once|after|as soon as)\s+(?:it|they|that|you|we|he|she|i)\b",
]), re.I)

# "your X" hands him a thing. If he did not mention X, the thing was invented.
_POSSESSIVE = re.compile(r"\byour\s+([A-Za-z][A-Za-z'-]*)", re.I)

# THE ALLOWLIST. A filler has to say it is waiting, in one of the ways people say it.
# Deliberately generous, because it is a floor under the blocklist rather than the whole
# test: what it catches is a sentence that is not about the wait at all.
_WAIT_CUE = re.compile("|".join([
    r"\blet me\b", r"\bi'?ll\b", r"\bi will\b", r"\bgive me\b", r"\bi need a\b",
    r"\b(?:hang|hold) on\b", r"\bbear with\b", r"\bone moment\b", r"\ba moment\b",
    r"\ba (?:sec|second|minute)\b", r"\bi'?m on (?:it|that)\b", r"\bon it\b",
    r"\blook(?:ing)?\b", r"\bcheck(?:ing)?\b", r"\bthink(?:ing)?\b",
    r"\bworking on\b", r"\bwork that out\b", r"\bpull(?:ing)? that up\b",
    r"\bfind out\b", r"\b(?:heard?|hear) you\b", r"\bunderstood\b",
    r"\bgot it\b", r"\bwith you\b", r"\bsee what\b", r"\bprocess\b",
]), re.I)

# Anything the model was never handed and could not have read. A capital letter in the
# middle of a spoken line is a proper noun, and a proper noun it did not look up is a
# name it invented.
_SENTENCE_START = re.compile(r"(?:^|(?<=[.!?])\s+)")
_ALWAYS_CAPITAL = frozenset({"i", "i'm", "i'll", "i've", "i'd", "ok", "okay"})

MAX_WORDS = 14
MAX_CHARS = 110


def _words(text: str) -> list[str]:
    return _WORD.findall(str(text or ""))


def _his_vocabulary(said: str) -> set[str]:
    """Every word he actually spoke, lower-cased. A name that came out of his own mouth
    is not a fabrication, so the guard lets it back through and nothing else."""
    return {w.lower().strip("'’") for w in _words(said)}


def state_vocabulary(doc: dict | None) -> set[str]:
    """Every proper token in the state document the board digest is built from.

    The filler is never given the digest, so anything here appearing in its line was
    invented rather than read. Built from the same fields index.build carries, because
    those are the ones that name things: dispatch names, room keys, member names, segment
    names, review titles, queue titles.

    THIS READS VALUES AND EMITS NONE, and the distinction is the custody one. Queue titles
    carry work content, and this function touches them; it turns them into a set of
    lower-cased words that is used only to REJECT a line and is then discarded. Nothing
    from here is spoken, logged, or sent anywhere, and in particular none of it reaches a
    model: the filler's prompt is its system text and his own sentence, and that is all.
    """
    if not doc:
        return set()
    blobs: list[str] = []
    for row in (doc.get("running") or []):
        blobs += [str(row.get(k) or "") for k in ("name", "member", "room", "tmux", "id")]
    for row in (doc.get("rooms") or []):
        blobs.append(str(row.get("key") or ""))
        blobs += [str(m.get("name") or "") for m in (row.get("members") or [])]
    blobs += [str(s.get("name") or "") for s in (doc.get("segments") or [])]
    blobs += [str(r.get("title") or "") for r in (doc.get("reviews") or [])]
    blobs += [str(q.get("what") or "") for q in (doc.get("queue") or [])]
    out: set[str] = set()
    for blob in blobs:
        out |= {w.lower() for w in _words(blob) if len(w) > 3}
    return out


def guard(line: str, said: str = "", doc: dict | None = None) -> str:
    """"" if the line may be spoken, or the REASON it may not.

    THE REASON IS RETURNED RATHER THAN A BOOL, because a guard whose decisions cannot
    be read back is a guard nobody can correct.
    bin/keel-voice-filler-score prints the reason beside the line it stopped,
    and the transcript records it, so the day this rejects something harmless it is
    visible as a rule rather than as an absence.

    IT IS ORDERED CHEAPEST FIRST and every branch is a refusal, so a line that reaches
    the bottom has passed every rule rather than matched a permissive one.
    """
    text = " ".join(str(line or "").split())
    if not text:
        return "the model said nothing"
    if len(text) > MAX_CHARS:
        return f"{len(text)} characters, and the ceiling is {MAX_CHARS}"
    if not text.isascii():
        return "not plain ASCII, so it is not a spoken English line"
    words = _words(text)
    if not words:
        return "no words in it"
    if len(words) > MAX_WORDS:
        return f"{len(words)} words, and the ceiling is {MAX_WORDS}"
    if "?" in text:
        return "asks the user a question, and they are waiting for an answer, not for one back"
    if re.search(r"[0-9]", text):
        return "carries a digit, and it has not looked anything up"
    if text.count(".") + text.count("!") > 1:
        return "more than one sentence, which is a line that started explaining"

    his = _his_vocabulary(said)
    lowered = [w.lower().strip("'’") for w in words]

    # THE PATIENCE PHRASE IS CHECKED FIRST, and getting that order wrong cost a real
    # line: "I'm on it, give me a second" was refused for the ORDINAL "second" before the
    # duration rule could exempt it. `waiting` therefore exempts a word from BOTH lists,
    # and only inside the exact shapes that ask for patience rather than predict a length.
    waiting = bool(_PATIENCE.search(text))
    for w in lowered:
        if w in _NUMBER_WORDS and w not in his and not _pronoun_one(w, text) \
                and not (waiting and w in _DURATION_WORDS) and not _discourse_first(w, text):
            return f"the number word {w!r}, which is a count it cannot have"
    if not waiting:
        for w in lowered:
            if w in _DURATION_WORDS and w not in his:
                return f"the duration {w!r}, and a duration is the clock read out loud"
    for w in lowered:
        if w in _SYSTEM_WORDS and w not in his:
            return f"names {w!r}, which is a part of the system it has not looked at"

    # A COMPLETED ACTION IS A FACT EVEN WITH NO SUBJECT ATTACHED. "that one finished."
    # slipped every rule above: no number, no name, no system word, and no assertion
    # SHAPE, because the shape is just a past-tense verb. It is still a claim about the
    # world, and it is the most damaging kind, because "finished" is what he is usually
    # asking about.
    # NOT EXEMPTED BY HIS OWN WORDS, and this is the one place the exemption is wrong.
    # A NAME he said is not a fabrication, because he supplied it. A CLAIM VERB he said is
    # a question, and echoing it back is an answer: "has the kettle one finished?" would
    # have let through "the kettle one finished." with both the name and the verb
    # exempted. Raised by review, 2026-09-04.
    for w in lowered:
        if w in _COMPLETED:
            return f"says something {w!r}, which is a fact about the world"

    hit = _ASSERTS.search(text)
    if hit:
        return f"asserts something: {hit.group(0)!r}"

    # THE PAST TENSE IS A CLAIM ABOUT WHAT HAS HAPPENED, and it escaped every rule above
    # on the first attack run: "It's been more complex." and "It took a moment to
    # process." both went through, because neither carries a number, a name, a system
    # word or a matched assertion shape. `got` is deliberately absent: "got it, let me
    # check" is an acknowledgement and it is one of the best lines the model writes.
    for w in lowered:
        if w in _PAST and w not in his:
            return f"the past tense {w!r}, which is a claim about what has happened"

    # A PROMISE IS WORSE THAN A CLAIM, and this is the class the second attack set found.
    # Told "rent's due Friday, I keep forgetting that", it answered "Got it, won't
    # forget."; told "need to grab milk on the way back", "Got it, let's plan that in."
    # Nothing recorded either. A fabricated fact is something he can check; a fabricated
    # promise is something he stops thinking about, which is the more expensive of the
    # two, and it lands hardest on ordinary life rather than on anything this system
    # holds. The filler acknowledges a WAIT. It may not accept a JOB.
    # A COMPARISON IS A CLAIM ABOUT TWO THINGS IT HAS SEEN NEITHER OF. "I hear you feel
    # more burdened today" got through the second attack set: no number, no name, no past
    # tense, no promise, and it asserts a change since yesterday. So does "slower than
    # usual" and "the same as before". Every one of these words needs two observations to
    # be true and the filler has none.
    for w in lowered:
        if w in _COMPARES and w not in his:
            return f"compares: {w!r}, and it has seen nothing to compare"

    kept = _PROMISES.search(text)
    if kept:
        return f"promises something: {kept.group(0)!r}, and nothing here remembers"

    # AN OBJECT IT INVENTED AND HANDED BACK TO HIM. "Let me check your schedule" says
    # there is a schedule. Harmless-sounding, and it is the same failure as naming a
    # session: a thing he never mentioned, asserted into existence in Harbor's voice.
    mine = _POSSESSIVE.search(text)
    if mine and mine.group(1).lower() not in his:
        return f"hands the user a {mine.group(1)!r} it invented"

    # AND THE RULE THAT IS AN ALLOWLIST RATHER THAN A BLOCKLIST, which is why it is last.
    #
    # Everything above says what a line may not contain, and the first attack run showed
    # what that misses: "Still the same one from this morning." contains no number, no
    # name, no system word, no assertion shape and no past-tense verb, and it is a
    # complete fabrication about state and history. A blocklist can only ever refuse the
    # shapes somebody thought of.
    #
    # So the last rule is positive: a filler has to SAY IT IS WAITING. It must carry one
    # of the phrases people use to ask for a moment or to say they are looking. That is a
    # weak test on its own (most good lines contain "let me"), and it is not doing the
    # work alone: it is the floor under the blocklist, and it is what catches a sentence
    # that is about something else entirely.
    known = state_vocabulary(doc)
    for w in lowered:
        if w in known and w not in his:
            return f"names {w!r} out of the live state, which it was never given"

    # A capital in the middle of a line is a proper noun, and one he did not say is one
    # it invented. Sentence-initial capitals are stripped first so an ordinary opening
    # word is not read as a name.
    body = _SENTENCE_START.sub(lambda m: m.group(0) + "\x00", text)
    for token in re.finditer(r"(\x00?)([A-Z][a-z'’-]+)", body):
        if token.group(1):
            continue
        w = token.group(2).lower()
        if w not in his and w not in _ALWAYS_CAPITAL:
            return f"the proper name {token.group(2)!r}, which it did not look up"

    if not _WAIT_CUE.search(text):
        return "does not say it is looking, so it is a line about something else"
    return ""


# --------------------------------------------------------------------------- #
# THE PROGRESS GUARD. A different test from `guard()` above and it must not be
# confused with it: `guard()` refuses ANY assertion, because the filler has looked at
# nothing. A progress line comes from HARBOR, mid-turn, and it is allowed to describe
# real work because it is actually doing it. What it may never do is name a SPECIFIC
# thing: a card title, a ticket number, a customer name, a work identifier, or a
# file's contents. Every spoken word travels to a hosted synthesiser (config.py, the
# custody decision), so a narrated progress line has to be safe BY CONSTRUCTION rather
# than by review. This already leaked once in the first live run, and the fix is a
# mechanical filter rather than a promise in a prompt.
#
# THE SHAPE IS FINE, ONLY THE CONTENT IS NOT. "reading through the queue now" says
# nothing a stranger could not already guess from the product's own name. Naming the
# actual card would. The three checks below are exactly the three ways a name gets in:
# a digit, a word straight out of the live state document, or a capitalised word he
# never said.
# --------------------------------------------------------------------------- #
PROGRESS_MAX_WORDS = 18
PROGRESS_MAX_CHARS = 140


def progress_guard(line: str, said: str = "", doc: dict | None = None) -> str:
    """"" if the line is safe to speak, or the reason it is not.

    Reuses the building blocks above (`_words`, `_his_vocabulary`, `state_vocabulary`,
    `_SENTENCE_START`, `_ALWAYS_CAPITAL`) rather than `guard()` itself, because the
    two tests disagree on purpose: this one allows a real claim about the work and
    refuses only an identifying detail of it.
    """
    text = " ".join(str(line or "").split())
    if not text:
        return "nothing to say"
    if len(text) > PROGRESS_MAX_CHARS:
        return f"{len(text)} characters, and the ceiling is {PROGRESS_MAX_CHARS}"
    if not text.isascii():
        return "not plain ASCII, so it is not a spoken English line"
    words = _words(text)
    if len(words) > PROGRESS_MAX_WORDS:
        return f"{len(words)} words, and the ceiling is {PROGRESS_MAX_WORDS}"
    if re.search(r"[0-9]", text):
        return "carries a digit, which is exactly the shape of a ticket or a count"
    if "?" in text:
        return "asks the user a question, which a progress line never does"

    his = _his_vocabulary(said)
    known = state_vocabulary(doc)
    for w in (w.lower().strip("'’") for w in words):
        # `_SYSTEM_WORDS` IS EXEMPTED HERE, AND DELIBERATELY NOT IN `known` ITSELF.
        # `state_vocabulary` takes every word over three letters out of dispatch names,
        # room keys, segment names, review titles and queue titles, and those are
        # ordinary sentences: "review", "queue", "check", "voice" and "front" are
        # exactly the kind of generic word a real title contains alongside whatever
        # actually identifies it. Blocking a WORD because it once coincided with a
        # title, rather than blocking the title itself, refused this guard's own
        # example: "reading through the queue now" whenever any queue entry's own text
        # happened to contain "queue". `_SYSTEM_WORDS` names the vocabulary this
        # feature is FOR (see its own definition, above `guard()`): the shape of
        # Harbor's own machinery, never a specific title, ticket, name or file, so
        # letting it through here does not loosen what this guard exists to stop.
        # Raised by review, 2026-09-07.
        if w in known and w not in his and w not in _SYSTEM_WORDS:
            return f"names {w!r} out of the live state, which is content, not shape"

    body = _SENTENCE_START.sub(lambda m: m.group(0) + "\x00", text)
    for token in re.finditer(r"(\x00?)([A-Z][a-z'’-]+)", body):
        if token.group(1):
            continue
        w = token.group(2).lower()
        if w not in his and w not in _ALWAYS_CAPITAL:
            return f"the proper name {token.group(2)!r}, which was never said out loud"

    return ""


# --------------------------------------------------------------------------- #
# THE FALLBACK, and it is what actually ships most of the time.
#
# Written by a person, asserts nothing by construction, and costs no model call. It is
# what every rejection falls back to, and what a filler that takes too long falls back
# to. Speaking AS Harbor, so "asking Harbor" is
# gone: the gateway used to say it and it broke the persona in the one place the persona
# is the point, because it announced that something else was about to do the thinking.
#
# TWELVE RATHER THAN SIX, because `FILLER_BACKEND = "table"` has to be a real option and
# not a punishment. Measured over 540 adversarial samples, the model produced 61 distinct
# lines and shared a content word with what he said in about 3% of them: what it buys over
# a written table is VARIETY, not grounding, and variety is something a table can have too.
# So the honest comparison is twelve human lines against a model that costs 0.95 s and
# tries to assert something on a third of adversarial turns, and the switch between them
# is one word.
#
# CHOSEN BY HASH OF WHAT HE SAID, not at random and not in rotation. The same question
# twice gets the same line, which is honest (nothing changed, so nothing new is being
# said) and it makes the selftest deterministic. Different questions get different lines,
# which is the whole reason there is more than one.
# --------------------------------------------------------------------------- #
TABLE = (
    "right, let me have a proper look at that.",
    "give me a moment on that one.",
    "on it.",
    "let me go and check that properly.",
    "hang on, I'll work that out.",
    "bear with me, I'm looking.",
    "let me look into that.",
    "one moment, I'm on it.",
    "hold on, let me work through that.",
    "right, let me think about that properly.",
    "let me have a proper think.",
    "give me a moment, I'm looking at it.",
)


def table_line(said: str) -> str:
    return TABLE[hash_of(said) % len(TABLE)]


def hash_of(said: str) -> int:
    """Stable across processes, which `hash()` is not: PYTHONHASHSEED randomises str
    hashing per interpreter, so a test asserting a particular line would pass here and
    fail in the gateway."""
    total = 0
    for ch in " ".join(str(said or "").split()).lower():
        total = (total * 31 + ord(ch)) & 0xFFFFFFFF
    return total


class Result:
    __slots__ = ("text", "source", "seconds", "raw", "refused")

    def __init__(self, text="", source="table", seconds=0.0, raw="", refused=""):
        self.text = text
        self.source = source        # "model", "table", "table (guarded)", "off"
        self.seconds = seconds
        self.raw = raw              # what the model actually said, for the transcript
        self.refused = refused      # why the guard stopped it, if it did

    def as_json(self) -> dict:
        return {"text": self.text, "source": self.source,
                "seconds": round(self.seconds, 3), "raw": self.raw[:120],
                "refused": self.refused}


class NoFiller:
    """The fixed table and nothing else. What `FILLER_BACKEND = "table"` gets, and what
    the gateway degrades to with no ollama. A supported configuration: the wait is still
    filled, it is just filled by a person's words instead of a model's."""

    name = "table"
    resident = False

    def line(self, said: str, doc: dict | None = None, stage: str = "open",
             avoid=()) -> Result:
        """`stage` and `avoid` are accepted and only `avoid` is used, deliberately.

        EVERY BACKEND TAKES THE SAME FOUR ARGUMENTS so the dispatcher never has to ask
        which one it is holding, which is the same reason `deliver` is injected: a code
        path that has to be avoided to be safe is a code path with no test. The twelve
        fixed lines have no `hold` half to switch to, so a repeat during one wait gets a
        different line rather than a different kind of line, and `avoid` is what makes
        that true. It is the floor, and the floor is allowed to be plainer.
        """
        avoid = {a for a in avoid}
        pool = [t for t in TABLE if t not in avoid] or list(TABLE)
        return Result(pool[hash_of(said + str(len(avoid))) % len(pool)],
                      "table", 0.0, "", "")


class OllamaFiller:
    """One local call, tight timeout, and every failure falls to the table.

    THE TIMEOUT IS BUDGETED AGAINST THE DELIVERY HOP, not against the model. A filler
    that arrives after the wait it was filling is worse than no filler, because it lands
    on top of Harbor's real answer. So it is budgeted against the hop it runs beside
    (measured 1.65 to 3.16 s) rather than against the model, and anything slower is
    simply dropped.
    """

    name = "ollama"
    # SWITCHED ON, THIS IS THE ONLY THING IN THE PROCESS THAT LOADS A MODEL. It used to
    # share the deleted lookup tier's resident weights, so this word is now the whole of
    # what `Gateway.resident` reports, and the whole of what `keel voice status` means
    # when it says the gateway is holding something.
    resident = True

    def __init__(self, model=None, url=None, timeout=None, keep_alive=None):
        self.model = model or config.FILLER_MODEL
        self.url = url or config.OLLAMA_URL
        self.timeout = timeout if timeout is not None else config.FILLER_TIMEOUT
        self.keep_alive = keep_alive or config.FILLER_KEEP_ALIVE

    def _body(self, said: str) -> bytes:
        return json.dumps({
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "think": False,
            # A TEMPERATURE ABOVE ZERO, and it is deliberate: a filler said in the same
            # words every
            # time is a recording, and a recording is what the fixed table already is.
            "options": {"temperature": config.FILLER_TEMPERATURE,
                        "num_predict": config.FILLER_MAX_TOKENS},
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": str(said or "")}],
        }).encode()

    def line(self, said: str, doc: dict | None = None, stage: str = "open",
             avoid=()) -> Result:
        # `stage` and `avoid` are accepted for one signature across backends and are not
        # used here: this asks a model for a fresh line every time, so it has no fixed
        # set to avoid repeating and no written `hold` half to switch to. A repeat during
        # one wait is another model call, and another roll of the dice the corpus exists
        # to stop rolling.
        req = urllib.request.Request(self.url, data=self._body(said),
                                     headers={"Content-Type": "application/json"})
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.load(r)
            raw = (payload.get("message") or {}).get("content") or ""
        except Exception as exc:                                        # noqa: BLE001
            return Result(table_line(said), "table", time.time() - started, "",
                          f"{exc.__class__.__name__}: {exc}")
        raw = " ".join(str(raw).split()).strip('"“”\'')
        why = guard(raw, said, doc)
        if why:
            return Result(table_line(said), "table (guarded)", time.time() - started,
                          raw, why)
        return Result(raw, "model", time.time() - started, raw, "")

    def warm(self, said: str = "warm up the filler, ignore this") -> bool:
        cold = OllamaFiller(model=self.model, url=self.url, timeout=120.0,
                            keep_alive=self.keep_alive)
        return cold.line(said).source != "table"


def from_config(backend=None, model=None):
    name = (backend or config.FILLER_BACKEND or "table").strip().lower()
    if name in ("table", "none", "off", ""):
        return NoFiller()
    if name == "corpus":
        from . import corpus                                            # noqa: PLC0415
        try:
            return corpus.CorpusFiller()
        except Exception:                                               # noqa: BLE001
            # A missing or malformed corpus file is a broken install, not a reason for
            # the wait to go silent. The twelve fixed lines need nothing on disk, so the
            # floor is always reachable and /voice/health says which one answered.
            return NoFiller()
    if name == "ollama":
        return OllamaFiller(model=model)
    raise ValueError(f"unknown filler backend {name!r}; known: corpus, ollama, table")
