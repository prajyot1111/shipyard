"""The filler, as 355 written lines rendered once, instead of a model.

THE NUMBERS IN THIS FILE ARE THE SHIPPED ONES. 378 lines were drafted, 361 survived
`filler.guard`, and 355 survived the screen below; where a paragraph is about the drafting
it says "drafted" and everywhere else the number is what is in
`fixtures/filler_corpus.json`. Review found three places quoting 378 as though it were the
shipped set, in the one file whose safety argument is that a person can read the whole of
it, so the count is load-bearing here in a way it is not elsewhere.

WHAT THIS REPLACES, AND WHY IT IS NOT A DOWNGRADE.

`filler.OllamaFiller` asked qwen to write one short line about the wait, and
`filler.guard` refused it if the line asserted anything. Findings 26 and 27 attacked
that guard with 810 samples across three adversarial sets, and the honest conclusion was
about the METHOD rather than the number: the three break rates were 14%, 36% and 37%,
they were not converging, and EACH SET FOUND A CLASS OF ESCAPE THE ONE BEFORE HAD NOT
IMAGINED. The worst was not a fabricated fact at all, it was a PROMISE about his ordinary
life: told "rent is due Friday, I keep forgetting that" the model said "Got it, won't
forget", and nothing anywhere recorded it. A fact he can check; a promise he stops
thinking about.

The guard could not close that class, and finding 27 says why it never will: every escape
was found by a person READING the allowed lines, because no counter can find one. If a
counter could recognise it, the guard would already have refused it.

SO THE CLASS IS REMOVED RATHER THAN BOUNDED. These lines are written by a person and
fixed. There is nothing to escape, because nothing is generated: the guard still runs
over every line, but it runs once, at build time, over a set somebody can read in full.
A line that is wrong is wrong visibly and permanently rather than one turn in three.

THREE THINGS FALL OUT OF THAT, AND THEY ARE THE WHOLE OF THIS FILE.

  1. NO MODEL CALL. The lines are on disk. Picking one is a lookup.

  2. NO TTS CALL EITHER. Each line is rendered ONCE into a cached WAV by
     `bin/keel-voice-corpus render` and played from the cache, so speaking a filler
     costs nothing at all: no vendor call, no characters against the free allowance, no
     0.5 s of network on the one hop that is supposed to be instant. Render cost is
     trivial: the 355 lines that ship are 10,779 characters against a 1,000,000 a
     month allowance, measured on the render that produced them, and paid once.

  3. REPEATS BECOME SAFE, AND THEY ARE NOW WANTED. `FILLER_REPEAT_EVERY` has existed in
     config.py since the filler shipped and NOTHING READ IT, so setting it did nothing,
     silently. It is built now (dispatcher._watch), and the reason the old answer was
     zero has gone: findings 25 set it to zero because the model filler's escape risk was
     PER UTTERANCE, so speaking k times multiplied the one risk the guard existed to
     bound. With the model gone that multiplier is gone with it, and what is left is a
     median 12.9 second wait that one line covers about 15% of.

WHY LINES CARRY A TOPIC AND A STAGE.

STAGE is not decoration. `open` is what he hears the moment his words land; `hold` is
what he hears twenty seconds later, when he has already been told something is being
looked at. "let me look into that" is right at the first and wrong at the second, because
it announces the start of something that started twenty seconds ago. So the two are
written separately and the picker never crosses them.

TOPIC is what makes a line feel like it is about HIS question without asserting anything
about it. The topic is the kind of THINKING the question calls for, never the subject:
"let me weigh that up" for a judgement, "let me cast my mind back" for a question about
last week. That is the only kind of relevance available here, because every actual
subject is state, and state is the thing a filler may never speak about.

WHICH PICKER, AND IT WAS MEASURED RATHER THAN ASSUMED. See `bin/keel-voice-corpus
score` and the note beside PICKER in config.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import wave
from pathlib import Path

from . import config

# The written lines. Committed, because they ARE the safety argument: a person can read
# the whole set, which is the property a generated line never had.
LINES_PATH = Path(__file__).resolve().parent / "fixtures" / "filler_corpus.json"

_WORD = re.compile(r"[A-Za-z']+")

# THE TOPICS, and they are closed. A line whose topic is not one of these is a line the
# picker can never reach, so loading refuses it rather than carrying it silently.
TOPICS = ("lookup", "judgement", "explain", "action", "recall", "general")
STAGES = ("open", "hold")


# --------------------------------------------------------------------------- #
# The lines.
# --------------------------------------------------------------------------- #

class Line:
    __slots__ = ("text", "topic", "stage", "speaker", "audio_key")

    def __init__(self, text: str, topic: str, stage: str,
                 speaker: str = config.SPEAKER_HARBOR):
        self.text = " ".join(str(text or "").split())
        self.topic = topic
        self.stage = stage
        # WHO SAYS IT (V8, card c-316). Every filler line and every ack is Harbor's; the
        # handoff lines below are split between the two. It is on the line rather than
        # worked out by the caller because the cache key is built from it, and a key built
        # in two places is a key that disagrees with itself.
        self.speaker = speaker
        # THE CACHE KEY IS OF THE TEXT AND THE VOICE TOGETHER. A rendered WAV belongs to
        # the voice that spoke it, so changing the voice must not play back the old one.
        # Named `audio_key` rather than `key`, because a bare `key` attribute in this
        # package means exactly one thing and it is the credential the hosted voice
        # holds. The selftest asserts that it appears nowhere else, so a second meaning
        # for the word would be a second place somebody has to look.
        self.audio_key = key_for(self.text, _preferred(speaker))

    def as_json(self) -> dict:
        return {"text": self.text, "topic": self.topic, "stage": self.stage,
                "speaker": self.speaker}

    def __repr__(self):                                                 # pragma: no cover
        return f"<Line {self.stage}/{self.topic}: {self.text!r}>"


def _preferred(speaker: str) -> str:
    """The preferred engine's voice id for this speaker, imported late like `key_for`."""
    from . import speech                                                # noqa: PLC0415

    return speech.preferred_voice_id(speaker)


def key_for(text: str, voice: str | None = None) -> str:
    """Which file this line's audio lives in, for a given voice.

    THE VOICE IS PART OF THE KEY, ENGINE AND ALL. See speech.preferred_voice_id for the
    bug that taught this: a render that degraded half way through wrote 205 clips in a
    local voice under a key naming the hosted one, and a cache hit asks no questions.
    """
    from . import speech                                                # noqa: PLC0415

    voice = voice if voice is not None else speech.preferred_voice_id()
    blob = f"{voice}\n{' '.join(str(text or '').split())}".encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def load(path: Path | None = None) -> list[Line]:
    """Every written line, checked. Raises rather than dropping a malformed one.

    A corpus that quietly skips what it cannot parse is a corpus whose size is a lie, and
    its size is one of the two things that makes it safe (the other is that a person can
    read it).
    """
    rows = json.loads(Path(path or LINES_PATH).read_text())
    out: list[Line] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        text = " ".join(str(row.get("text") or "").split())
        topic = str(row.get("topic") or "")
        stage = str(row.get("stage") or "")
        if not text:
            raise ValueError(f"line {i} has no text")
        if topic not in TOPICS:
            raise ValueError(f"line {i} has topic {topic!r}, which no picker can reach")
        if stage not in STAGES:
            raise ValueError(f"line {i} has stage {stage!r}, which no picker can reach")
        if text.lower() in seen:
            raise ValueError(f"line {i} is a duplicate: {text!r}")
        seen.add(text.lower())
        out.append(Line(text, topic, stage))
    return out


# --------------------------------------------------------------------------- #
# Checking them, once, at build time.
# --------------------------------------------------------------------------- #

# THE ONE RULE OF `filler.guard` THAT DOES NOT APPLY TO A WRITTEN LINE, and finding out
# which one is the most useful thing this round produced.
#
# Running the 378 drafted lines through `filler.guard` refused 156 of them, and 100 of
# those were one word: `still`. The guard refuses a comparison because a MODEL saying
# "still the same one from this morning" is asserting a fact about history it never read,
# which is set 1's escape class in finding 27 and is exactly right for model output.
#
# THE SAME RULE REFUSES SIX OF THE SEVEN LINES IN dispatcher.NARRATION, including
# "I'm still on it, and I'll answer in text instead", which this gateway has spoken aloud
# at ninety seconds since the day it shipped. Those lines are rendered from an
# OBSERVATION, so they are allowed to name a card and say a session started, and the
# guard would refuse every one of them.
#
# So `filler.guard` is not the test of whether a line is safe to SPEAK. It is the test of
# whether a line written by something that has looked at NOTHING is safe to speak.
# Applying it unchanged to written lines conflates two different questions, and the
# answer to the second one is not "rewrite the English until the first one is happy".
#
# WHAT THE EXEMPTION IS, AND HOW NARROW. `still` is permitted in a `hold` line, and only
# when the line passes every other rule with the word removed. "still on it" passes;
# "still the same one from this morning" is still refused, on `same`; "still the one you
# asked about" is still refused, for not being about looking; "still three of them
# waiting" is still refused, on the count. Checked, all four, and they are the checks in
# bin/keel-voice-selftest.
#
# AND WHY IT IS SAFE HERE WHERE IT WOULD NOT BE THERE. A `hold` line is about the WAIT,
# which is the one thing plan section 5 permits a filler to speak about, and its truth is
# guaranteed by its trigger rather than by its words: the line is only ever spoken because
# the turn really is still outstanding. Nothing here is generated, so there is no case
# where an unread sentence reaches this exemption.
_STILL = re.compile(r"\bstill\b", re.I)

# THE ONE RULE THE GUARD DOES NOT HAVE, AND READING THE SET IS HOW IT WAS FOUND.
#
# `filler.guard` passed all 361 that survived it. Reading them found four in the `action`
# it should not have: "let me get that sorted for you", "right, let me get that handled",
# "let me take that in hand", "right, let me get that actioned for you". Every one of
# topic that it should not have: every one is a PROMISE ABOUT AN OUTCOME, which is the
# exact class that got the model filler
# scrapped: told "rent is due Friday, I keep forgetting that" it answered "Got it, won't
# forget", and nothing recorded it. The guard's own promise rule matches "I'll <verb>"
# and these are all "let me <verb>", so they went straight through.
#
# AND THE GATEWAY CANNOT DO ANY OF IT. A voice turn is delivered into Harbor's pane and
# Harbor decides what happens; the filler speaks as Harbor, and Harbor may perfectly well
# answer that it will not. So a line saying the thing will be sorted is a commitment
# nothing in this system is in a position to make.
#
# THE LINE THIS DRAWS IS BETWEEN STARTING AND FINISHING. "let me see what I can do there"
# and "right, let me get to work" commit only to looking, which is true by the time the
# line is spoken. "let me get that sorted" commits to an outcome. Only the second class
# is refused, and this is the whole list.
#
# IT IS PROOF OF FINDING 27 RATHER THAN A COUNTER-EXAMPLE TO IT. A person reading the set
# found what every counter had passed, which is exactly what finding 27 says will keep
# happening. The difference is that here the set is finite and it was read ONCE, so the
# escape is closed permanently instead of recurring one turn in three.
_OUTCOME = re.compile(
    r"\b(?:sorted|handled|actioned|arranged|in hand|taken care|take care of"
    r"|dealt with|fixed for you|done for you|see to it)\b", re.I)


def check(text: str, stage: str = "open") -> str:
    """"" if this written line may ship, or the REASON it may not.

    RUN ONCE, AT BUILD TIME, over a set somebody can read in full, which is the whole
    difference between this and the guard it wraps. `bin/keel-voice-corpus check` runs
    it and so does the selftest, so a line that drifts into the file is refused before it
    is ever spoken rather than one turn in three after.
    """
    from . import filler                                                # noqa: PLC0415

    promise = _OUTCOME.search(text)
    if promise:
        return (f"promises an outcome, {promise.group(0)!r}, and nothing here is in a "
                "position to promise one: the turn goes to Harbor and Harbor decides")
    why = filler.guard(text, "", None)
    if not why:
        return ""
    if stage == "hold" and why.startswith("compares: 'still'"):
        # The one exemption, and it has to earn itself: with the word removed the line
        # must pass every other rule, so `still` may only ever be attached to a sentence
        # that was already allowed to be spoken.
        without = _STILL.sub("", text)
        without = " ".join(without.split()).replace(" ,", ",")
        rest = filler.guard(without, "", None)
        if not rest:
            return ""
        return f"{why} (and with 'still' removed it is refused anyway: {rest})"
    return why


# --------------------------------------------------------------------------- #
# Picking one.
# --------------------------------------------------------------------------- #

# WHAT EACH TOPIC LOOKS LIKE IN HIS OWN WORDS. The dumb baseline, and the thing the
# embedding picker had to beat to earn its place: see bin/keel-voice-corpus score.
#
# Ordered, and the FIRST topic with a hit wins, because the classes overlap in real
# speech and the order is the priority. "can you tell me how it works" is an explanation
# and not an action, so `explain` is asked before `action`; "what did I ask you to spawn
# yesterday" is a recall before it is an action.
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("recall", ("earlier", "yesterday", "last week", "last night", "before",
                "this morning", "the other day", "again", "remind me", "we said",
                "you said", "i said", "just now", "ago", "back then", "previously")),
    ("judgement", ("should", "worth", "better", "instead", "rather", "prefer",
                   "make of", "think of", "opinion", "reckon", "advise", "recommend",
                   "merge", "approve", "risky", "safe to", "or not", "which one",
                   "good idea", "bad idea", "makes sense", "shall i")),
    ("explain", ("how does", "how do", "how is", "how it", "why does", "why is",
                 "why did", "what is", "what's the", "explain", "mean", "means",
                 "works", "work", "difference", "supposed to", "tell me about",
                 "what does")),
    ("lookup", ("running", "queue", "waiting", "open", "pending", "status", "going on",
                "anything", "what have you got", "rooms", "review", "board", "brief",
                "briefing", "spend", "spent", "cost", "dispatch", "session",
                "segments", "up to", "left to", "on my plate")),
    ("action", ("can you", "could you", "would you", "spawn", "start", "close", "stop",
                "kill", "run ", "open up", "make ", "change", "set ", "turn on",
                "turn off", "add ", "remove", "send", "write", "build", "fix",
                "please", "go ahead", "do it")),
)


def topic_by_keyword(said: str) -> str:
    """The zero-model baseline: which topic his sentence looks like, by its words."""
    lowered = " " + " ".join(str(said or "").lower().split()) + " "
    for topic, words in KEYWORDS:
        for word in words:
            if word in lowered:
                return topic
    return "general"


def stable_hash(text: str) -> int:
    """Stable across processes, which `hash()` is not: PYTHONHASHSEED randomises str
    hashing per interpreter, so a test asserting a particular line would pass here and
    fail in the gateway. Same function filler.hash_of uses, and for the same reason."""
    total = 0
    for ch in " ".join(str(text or "").split()).lower():
        total = (total * 31 + ord(ch)) & 0xFFFFFFFF
    return total


class KeywordPicker:
    """Topic by keyword, then one of that topic's lines by a stable hash.

    NO MODEL AT ALL, which is the point of measuring it: the whole reason the fast tier
    was switched off was to stop holding a model resident, and a picker that is
    indistinguishable to the ear should win on its own merits rather than on RAM.
    """

    name = "keyword"
    resident = False

    def __init__(self, lines: list[Line] | None = None):
        self.lines = lines if lines is not None else load()

    def topic(self, said: str) -> str:
        return topic_by_keyword(said)

    def pick(self, said: str, stage: str = "open", avoid=()) -> Line:
        return choose(self.lines, self.topic(said), stage, said, avoid)


class EmbeddingPicker:
    """Relevance by cosine over static embeddings. He asked for semantic search.

    THE MODEL IS THE ONE THIS MACHINE ALREADY HOLDS, and that is deliberate rather than
    incidental: `minishlab/potion-base-8M` through model2vec is what `csr`'s thread search
    uses, so the machine holds ONE static embedding model rather than two. It is tens of
    megabytes, it is a lookup table rather than a network, and it needs no torch, which is
    why it does not reopen the resident-cost question that retiring the lookup tier closed.

    NOT IMPORTED FROM csr. `~/.claude/tools/smart-resume/semantic.py` is a different tool
    with its own lifecycle; reaching into it would make voice break when it moves. This
    depends on model2vec and on the same model NAME, and keeps its own vectors.

    VECTORS ARE PRECOMPUTED AND CACHED, so a pick is a matrix multiply against a few
    hundred rows and nothing else.
    """

    name = "embed"
    # It holds a lookup table rather than a network. Reported as not resident because the
    # word means "holds a large model in memory that this process chose to load", and
    # tens of megabytes of static vectors is not what the 4.7 GB decision was about. The
    # figure is on /voice/health either way, as `picker`.
    resident = False
    MODEL_NAME = "minishlab/potion-base-8M"

    def __init__(self, lines: list[Line] | None = None, model_name: str | None = None):
        self.lines = lines if lines is not None else load()
        self.model_name = model_name or self.MODEL_NAME
        from model2vec import StaticModel                               # noqa: PLC0415

        self.model = StaticModel.from_pretrained(self.model_name)
        # ONE VECTOR PER TOPIC, not per line, and that is the whole design. A filler line
        # says nothing about its topic ("bear with me" is `general` because somebody
        # decided so, not because the words say it), so embedding the LINES and comparing
        # them to his sentence compares two things that share no vocabulary. What does
        # carry the meaning is what a question of that KIND sounds like, so that is what
        # is embedded, his sentence is compared against those, and the line is then
        # chosen inside the winning topic exactly as the keyword picker does.
        #
        # EXEMPLARS, MEANED, RATHER THAN ONE PROSE DESCRIPTION, and the difference was
        # measured rather than assumed. model2vec averages static token vectors, so a
        # long description is a blur of many words and a short spoken sentence compared
        # against a blur does badly: 60% on the scoring set, against 73% taking the best
        # single exemplar and 77% taking the mean of them. This is the formulation the
        # model deserved before it was judged, and it is the one it is judged on.
        self.topics = list(TOPICS)
        self.matrix = self._normalise(
            [self._normalise(self.model.encode(EXEMPLARS[t])).mean(axis=0)
             for t in self.topics])

    @staticmethod
    def _normalise(vectors):
        import numpy as np                                              # noqa: PLC0415

        v = np.asarray(vectors, dtype="float32")
        if v.ndim == 1:
            v = v.reshape(1, -1)
        norms = np.linalg.norm(v, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return v / norms

    def topic(self, said: str) -> str:
        import numpy as np                                              # noqa: PLC0415

        said = " ".join(str(said or "").split())
        if not said:
            return "general"
        q = self._normalise(self.model.encode([said]))
        return self.topics[int(np.argmax(self.matrix @ q[0]))]

    def pick(self, said: str, stage: str = "open", avoid=()) -> Line:
        return choose(self.lines, self.topic(said), stage, said, avoid)


# WHAT EACH TOPIC IS, IN WORDS THE EMBEDDING CAN SEE. These are not spoken and never
# reach him: they exist so a sentence he says can be compared against a description of a
# kind of question rather than against a filler line, which shares no vocabulary with any
# question at all.
# WHAT A QUESTION OF EACH KIND SOUNDS LIKE, in a handful of short sentences. These are
# never spoken and never reach him: they are what his sentence is compared AGAINST.
#
# DELIBERATELY NOT THE SCORING SET in bin/keel-voice-corpus, and not the keyword list
# either. Reusing the scored sentences here would be scoring the model on its own answer
# key, which is finding 1 of this project happening a second time: a matcher written
# alongside its own test scored 100% on the fixtures and 0% on a held-out set, because
# the same hand wrote both.
EXEMPLARS = {
    "lookup": ["what is going on", "anything pending", "show me the list",
               "what is open", "read me what is there", "is anything happening",
               "what is the status", "how many are there", "what is left"],
    "judgement": ["is it worth it", "which is better", "should we do that",
                  "what is your opinion", "do you think that is right", "is that wise",
                  "would you go ahead", "is that a good plan", "yes or no"],
    "explain": ["how does that work", "why is it like that", "what does that mean",
                "explain it to me", "what is the reason", "how is it built",
                "tell me about it", "what is the idea behind it",
                "what is the difference"],
    "action": ["do that for me", "start it up", "shut it down", "make a change",
               "please run it", "carry that out", "set that up", "get rid of it",
               "put that together"],
    "recall": ["what did I say", "from yesterday", "earlier today", "last week",
               "what we discussed", "before now", "in the past", "remind me",
               "the conversation we had"],
    "general": ["hello", "how are you", "just chatting", "never mind", "thanks",
                "good morning", "small talk", "nothing important", "carry on"],
}

# The prose form, kept because it is the readable statement of what each topic MEANS and
# it is what the topic list is documented by. It was also the first formulation tried for
# the embedding picker, and it is why EXEMPLARS exists: see EmbeddingPicker.
TOPIC_DESCRIPTIONS = {
    "lookup": ("asking what is happening right now, what is running, what is waiting, "
               "what is open, reading a list or a status or a count off a record"),
    "judgement": ("asking whether something is worth doing, which of two things is "
                  "better, whether to go ahead, what you make of it, an opinion or a "
                  "recommendation or a decision"),
    "explain": ("asking how something works, why something is the way it is, what "
                "something means, an explanation of a mechanism or a reason"),
    "action": ("asking you to do something, to start or stop or change or make or send "
               "something, a request to carry something out"),
    "recall": ("asking about something from earlier, yesterday, last week, what was "
               "said before, remembering a past conversation"),
    "general": ("small talk, a greeting, an aside, anything that is not a question "
                "about work"),
}


def choose(lines: list[Line], topic: str, stage: str, said: str, avoid=()) -> Line:
    """One line of that topic and stage, chosen stably, not repeating what he just heard.

    CHOSEN BY HASH OF WHAT HE SAID, not at random. The same question twice gets the same
    line, which is honest (nothing changed, so nothing new is being said) and it makes
    every test in this package deterministic. `avoid` is what has already been spoken
    DURING THIS WAIT, which is the one place a repeat would be heard as a stutter.

    FALLS BACK ALONG ONE AXIS AT A TIME, and never across stages. A topic with no `hold`
    lines falls to `general`'s `hold` lines rather than to its own `open` ones, because
    an opener spoken twenty seconds in is the specific thing `stage` exists to prevent.
    """
    avoid = {a for a in avoid}
    pools = [[ln for ln in lines if ln.stage == stage and ln.topic == topic],
             [ln for ln in lines if ln.stage == stage and ln.topic == "general"],
             [ln for ln in lines if ln.stage == stage]]
    for pool in pools:
        fresh = [ln for ln in pool if ln.text not in avoid]
        if fresh:
            return fresh[stable_hash(said + str(len(avoid))) % len(fresh)]
        if pool:
            # Everything in this pool has been heard already during this one wait, which
            # takes a wait long enough to exhaust a topic. Better a repeat than silence.
            return pool[stable_hash(said) % len(pool)]
    raise ValueError(f"the corpus has no {stage!r} lines at all")


def picker_from_config(name: str | None = None, lines: list[Line] | None = None):
    """The one place a picker is chosen. Falls back rather than failing to boot.

    An embedding picker that cannot import is a missing install, not a reason for the
    assistant to stop speaking during waits, and the keyword picker is measurably close
    enough that degrading to it is a degradation nobody hears. /voice/health says which
    one answered.
    """
    want = (name or config.FILLER_PICKER or "keyword").strip().lower()
    if want in ("keyword", "none", ""):
        return KeywordPicker(lines)
    if want == "embed":
        try:
            return EmbeddingPicker(lines)
        except Exception:                                               # noqa: BLE001
            return KeywordPicker(lines)
    raise ValueError(f"unknown filler picker {want!r}; known: embed, keyword")


# --------------------------------------------------------------------------- #
# The rendered audio.
# --------------------------------------------------------------------------- #

class AudioCache:
    """One WAV per line, rendered once, played from disk forever after.

    UNDER THE SEGMENT'S OWN data/, which is the gateway's whole writable surface and is
    not repository content. Rendering the 355 lines that ship cost 10,779 characters
    against a 1,000,000 a month allowance, so it is generated on install rather than
    committed: 355 clips of speech is 32 MB, and a repository is not where thirty
    megabytes of generated audio belongs.

    KEYED ON THE TEXT AND THE VOICE TOGETHER, so changing the voice does not play back
    the old one. Changing the voice means re-rendering, and a missing clip is not an
    error: the chain synthesises that line the ordinary way and the wait is still filled.
    """

    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory or (config.DATA / "cache" / "filler-audio"))
        self._lock = threading.Lock()

    def path_for(self, text: str, voice: str | None = None) -> Path:
        return self.dir / f"{key_for(text, voice)}.wav"

    def read(self, text: str, voice: str | None = None) -> bytes:
        """The PCM for that line, or b"" if it has not been rendered.

        Never raises. A cache that can throw is a cache that can cost a spoken line, and
        the whole point of it is that speaking a filler costs nothing.
        """
        try:
            with wave.open(str(self.path_for(text, voice))) as w:
                if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (
                        1, 2, config.TTS_RATE):
                    return b""
                return w.readframes(w.getnframes())
        except Exception:                                               # noqa: BLE001
            return b""

    def write(self, text: str, pcm: bytes, voice: str | None = None) -> Path:
        path = self.path_for(text, voice)
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(config.TTS_RATE)
                w.writeframes(pcm)
            tmp.rename(path)                # atomic: a half-written clip never plays
        return path

    def stats(self, lines: list[Line] | None = None, voice: str | None = None) -> dict:
        """How much of the corpus has audio, for one voice. NEVER RAISES.

        `voice` names the set (V7): since the control lets him pick an engine per
        session, `TTSChain.synthesize` reads the cache under THAT engine's key, so there
        is a set of clips per engine the control offers and "how much is rendered" has to
        be asked per set. None is the preferred one, which is what every caller that
        predates V7 means.

        `load()` refuses a malformed corpus rather than skipping rows, which is right:
        a corpus that quietly drops what it cannot parse has a size that is a lie, and
        its size is half of what makes it safe. But this is read by /voice/health, and a
        health endpoint that stops answering when the corpus is broken has failed at the
        one moment it was wanted: the filler itself degrades correctly to the fixed
        table, so the gateway keeps speaking while the surface that would say why has
        gone. Raised by review, 2026-09-04.
        """
        if lines is None:
            try:
                lines = load()
            except Exception as exc:                                    # noqa: BLE001
                return {"lines": 0, "rendered": 0, "missing": 0, "bytes": 0,
                        "dir": str(self.dir), "voice": voice or "",
                        "error": f"{exc.__class__.__name__}: {exc}"}
        have = sum(1 for ln in lines if self.path_for(ln.text, voice).exists())
        try:
            size = sum(p.stat().st_size for p in self.dir.glob("*.wav"))
        except Exception:                                               # noqa: BLE001
            size = 0
        return {"lines": len(lines), "rendered": have,
                "missing": len(lines) - have, "voice": voice or "",
                "bytes": size, "dir": str(self.dir)}


CACHE = AudioCache()


# --------------------------------------------------------------------------- #
# The capture acks.
# --------------------------------------------------------------------------- #

# WHAT HE HEARS WHEN A CAPTURE LANDS. Fixed sentences, rendered once into the same cache
# as the filler by `bin/keel-voice-corpus render`, so speaking one costs no synthesiser
# call and sends nothing anywhere: the chain finds the clip by its text and plays it
# (speech.TTSChain.synthesize reads the cache before any engine). The ramble itself is
# never spoken back, and neither is the card id, which would need a synthesiser call and
# which he can read on the page.
#
# NOT RUN THROUGH `check`. That screen is for a line written by something that has looked
# at nothing. These are said only after `kb create` printed an id, so "it's on the board"
# is an observation, the same kind of sentence dispatcher.NARRATION holds.
ACKS = (
    "Got it, it's on the board.",
    "Got it, that's on the board.",
    "Noted, it's on the board.",
    "Kept, it's in your inbox.",
    "Done, that one's on the board.",
)

# THE ONE FAILURE LINE, for a `kb` refusal. True by construction: the page draws what he
# said the moment it is transcribed, and the transcript file has it too, so nothing is
# lost and he can see it to say it again.
ACK_FAILED = "That did not land, it's on the page"


def ack_lines() -> list[Line]:
    """The acks and the failure line as `Line`s, so `render` and `stats` treat them like
    any other clip. Their topic and stage are `ack`, which no picker ever asks for."""
    return [Line(text, "ack", "ack") for text in (*ACKS, ACK_FAILED)]


# THERE IS NO CONNECTED OPENER ANY MORE (2026-09-21), and its clip is gone with it.
#
# V5 asked for "a pre-rendered 'heard you, changing that now' within a second of release",
# and `HOUSE_OPENER` was that line: "Heard you, passing that to the house now", spoken at
# the top of every connected turn, rendered into this cache beside the capture acks. It was
# cover for a COLD PROCESS, back when a connected turn's first second was spent stopping one
# `claude` and starting another. V12 opens the conversation at the connect, so the first
# spoken sentence of the answer lands in about three seconds, and V13 made Harbor ENTER the
# house rather than hand the microphone over: the line was wrong twice over, because nothing
# is being passed to anybody and he is already in there.
#
# WHAT COVERS THAT WAIT NOW IS THE FILLER CORPUS, the same one a Harbor turn uses, chosen
# the same way and spoken only when the wait really goes quiet (`dispatcher._ask_house` and
# the silence gate in `_watch`). It needs nothing here, because every one of its lines is
# already in this file's own corpus and already rendered.


# --------------------------------------------------------------------------- #
# The handoff (V8, card c-316).
# --------------------------------------------------------------------------- #

# THE FIXED HALF OF THE FOUR SPOKEN MOMENTS. Said by code, never by a model turn, so no
# tokens are spent on any of them and none of them can be wrong about who is speaking: the
# gateway knows which it is, because it is the thing that took the pin.
#
# LINE 1 NAMES NO CARD, AND THAT IS THE ONE PLACE THIS DEPARTS FROM V8's OWN WORDING. The
# text there reads "Connecting you to c-272", and a line with a card id in it cannot be
# pre-rendered, because the clips are made by `bin/keel-voice-corpus render` long before
# anybody knows which card. The whole job of line 1 is to land AT ONCE, over a wait that is
# about to happen, and a live synthesis is the one thing that cannot promise that. So line
# 1 is fixed and line 2, which is synthesised anyway, names the card two seconds later. His
# own words at the time were "Harbor should say connecting" (approved at c-316's plan gate,
# 2026-09-20).
#
# THE ENTERING AND LEAVING LINES ARE NOT HERE because they are not fixed: they carry the
# card, and the entering one its title too, cut to a few words by `verbs.short_title`. They
# are synthesised at the moment of the switch, which the wait covers.
CONNECTING = "Connecting you now."
# SAID ONCE AND NEVER TWICE, however long the connect takes. A second "still connecting" is
# a machine filling silence, which is the thing the whole filler corpus exists to avoid
# doing badly.
STILL_CONNECTING = "Still connecting."
# THE ONE LEAVING LINE THAT NAMES NOTHING, and it is the one nobody asked for: the hold ran
# out while he was quiet. An expiry is UNPROMPTED, and the egress split (decision V17) lets
# a direct answer name the card he just asked about while holding unprompted speech to
# naming nothing at all.
#
# IT WAS "Harbor here, I'm back" UNTIL V13, and that sentence announced a speaker ARRIVING.
# Nobody arrives any more, because nobody left: there is one voice, and it went somewhere
# and came back. "Leaving that house" is the same fact with the second person taken out of
# it, which is the whole of the persona change in one line.
LEFT_HOUSE = "Leaving that house. Back with you."

# EVERY FIXED LINE IS HARBOR'S NOW (V13). V8 had one that a house spoke ("Handing you
# back."), said in the house's own voice because the handoff WAS a change of speaker. There
# is no change of speaker left to voice, so that line is gone rather than recoloured, and
# what replaces it is `verbs.leaving`: one line, naming the card, Harbor's like the rest.
HANDOFF = ((CONNECTING, config.SPEAKER_HARBOR),
           (STILL_CONNECTING, config.SPEAKER_HARBOR),
           (LEFT_HOUSE, config.SPEAKER_HARBOR))


def handoff_lines(speaker: str = "") -> list[Line]:
    """The fixed handoff lines as `Line`s, all of them or one speaker's.

    Their topic and stage are `handoff`, which no picker ever asks for, exactly as the
    acks' are `ack`: they are in the corpus's cache because they are spoken from it, not
    because anything might choose them.
    """
    return [Line(text, "handoff", "handoff", who) for text, who in HANDOFF
            if not speaker or who == speaker]


def lines_for(speaker: str = config.SPEAKER_HARBOR,
              filler: list[Line] | None = None) -> list[Line]:
    """Every clip one speaker has: what has to be rendered for it.

    A HOUSE HAS NO CLIPS AT ALL SINCE V13, and the empty list is the truthful answer rather
    than an oversight. Harbor enters and leaves a house, so every sentence code renders is
    Harbor's; what a house says is only ever its ANSWER, which a model writes and which can
    therefore never be a clip. The set is kept rather than removed so the render
    (`bin/keel-voice-corpus`) and the count (`keel voice audio`) keep walking ONE
    enumeration, which is what stops a cache reporting itself full while something in it is
    silent; it is simply empty now, and an empty set renders nothing and counts nothing.

    THE CONNECTED OPENER IS NO LONGER ONE OF THESE (2026-09-21). `HOUSE_OPENER` was here,
    as Harbor's despite its name, and it is deleted rather than recoloured: a connected wait
    is covered by the filler corpus now, whose lines are already in `base`. The ordering in
    `_ask_house` is unchanged and still what decides the voice: a turn starts as Harbor's
    and only the ANSWER moves it, so every progress line and the give-up line are Harbor's
    without anything having to decide it.
    """
    if speaker == config.SPEAKER_HOUSE:
        return handoff_lines(config.SPEAKER_HOUSE)
    base = load() if filler is None else list(filler)
    return base + ack_lines() + handoff_lines(config.SPEAKER_HARBOR)


def audio_sets(chain=None, filler: list[Line] | None = None) -> list[dict]:
    """One set of clips per (engine he can pick) x (speaker), with the voice each belongs to.

    THE ONE PLACE THAT ENUMERATES THE SETS, read by `bin/keel-voice-corpus render` and by
    `keel voice audio` so that what is rendered and what is counted cannot disagree. Before
    V8 the second dimension did not exist and the render keyed every clip as Harbor's: a
    house line rendered through it landed in a Harbor-keyed slot, where playback would
    never look for it and the count would call the cache full.

    `filler` is the written corpus, read once by the caller rather than per set: `load()`
    parses 355 lines and refuses a malformed file, and doing that eight times over is four
    parses of the same thing plus four ways to ask the same question.
    """
    from . import speech                                                # noqa: PLC0415

    if filler is None:
        filler = load()
    offered = config.engines_for_page(chain) or [{"id": "", "backend": ""}]
    out = []
    for engine in offered:
        backend = str(engine.get("backend") or "")
        for speaker in config.SPEAKERS:
            out.append({"engine": str(engine.get("id") or ""), "backend": backend,
                        "speaker": speaker,
                        "voice": speech.voice_id_for(backend, speaker) if backend else None,
                        "lines": lines_for(speaker, filler)})
    return out


def pick_ack(avoid: str = "") -> str:
    """One ack, at random, and not the one he heard last: a run of captures is the
    common case, and the same four words five times in a row is a machine talking."""
    choices = [text for text in ACKS if text != avoid] or list(ACKS)
    return random.choice(choices)


# --------------------------------------------------------------------------- #
# The backend the dispatcher actually holds.
# --------------------------------------------------------------------------- #

class CorpusFiller:
    """`FILLER_BACKEND = "corpus"`. Written lines, picked by relevance, spoken from cache.

    THE SAME INTERFACE AS THE MODEL ONE IT REPLACES (`line(said, doc) -> filler.Result`),
    so the dispatcher does not know which it is holding and the selftest can still inject
    either. The guard still runs, and it runs over a written line: it cannot fail here,
    which is exactly the claim being made, so a failure would mean the corpus itself had
    drifted and it falls to the old fixed table rather than speaking something unchecked.
    """

    name = "corpus"
    resident = False

    def __init__(self, picker=None, lines: list[Line] | None = None, cache=None):
        self.lines = lines if lines is not None else load()
        self.cache = cache if cache is not None else CACHE
        # THE PICKER IS BUILT ON FIRST USE, NOT HERE, and the reason is where `here` is.
        # This runs inside Dispatcher.__init__, which runs inside Gateway.__init__,
        # which runs BEFORE the HTTP listener binds. EmbeddingPicker loads a static
        # model, and on a first install that is a 123 MB download with no timeout of
        # ours: the gateway would sit unreachable, saying nothing, while a network it
        # cannot see decides how long to take. Nothing about picking a filler line is
        # needed until he speaks. Raised by review, 2026-09-04.
        self._picker = picker
        self._picker_lock = threading.Lock()
        self._picker_building = False
        self._keyword: KeywordPicker | None = None
        # Why the configured picker is not the one answering, if it is not. Reported on
        # /voice/health, because a name nothing recognises has to be visible somewhere.
        self._picker_why = ""

    @property
    def picker(self):
        """A picker, NOW, without ever waiting for one to be built.

        THE FIRST VERSION OF THIS HELD THE LOCK WHILE IT BUILT, and that moved a stall
        rather than removing it. `dispatcher._watch` calls `filler.line` inline, on the
        watch thread, and that thread is the only thing draining Harbor's say inbox. So
        on a first install the repeat filler would have blocked on a 123 MB download
        while Harbor's real answer sat unclaimed, and a download outlasting
        TURN_MAX_SECONDS would have marked the turn abandoned. Raised by review,
        2026-09-04.

        So the configured picker is built on a thread of its own and, until it is ready,
        the keyword picker answers. That is not a degradation invented for this: it is
        the fallback `picker_from_config` already uses when model2vec is absent, it needs
        nothing on disk, and finding 34 measured what it costs (a slightly less apt
        filler line on some questions, never a wrong answer).
        """
        with self._picker_lock:
            if self._picker is not None:
                return self._picker
            # `if start`, AND THAT WORD IS THE WHOLE OF A BLOCKING REVIEW FINDING. This
            # was `start = not self._picker_building` followed by an UNCONDITIONAL
            # `self._picker_building = start`, which writes False whenever a build is
            # already running: the second caller during a build turned the guard off and
            # the third started another one. With `embed` as the default and the repeat
            # filler firing up to six times a wait, a first install would have fanned out
            # three or more concurrent 123 MB builds for one wait, and more on every turn
            # until one landed, which is precisely the resource event this property was
            # written to bound to one. It also made `picker_name` report "not started"
            # while a build was in flight, so /voice/health said the opposite of what was
            # happening. Raised as blocking by review, 2026-09-04.
            start = not self._picker_building
            if start:
                self._picker_building = True
            if self._keyword is None:
                self._keyword = KeywordPicker(self.lines)
            waiting = self._keyword
        if start:
            def build():
                made, why = None, ""
                try:
                    made = picker_from_config(lines=self.lines)
                except Exception as exc:                                # noqa: BLE001
                    why = f"{exc.__class__.__name__}: {exc}"
                with self._picker_lock:
                    self._picker_building = False
                    if made is not None:
                        self._picker = made
                        return
                    # A NAME NOTHING KNOWS IS A CONFIGURATION FACT, NOT WEATHER, and
                    # swallowing it was a silent repeating failure of exactly the kind
                    # this package keeps naming as its recurring fault. `embed` failing
                    # to import already degrades inside picker_from_config, so the only
                    # way to arrive here is a value nothing recognises: a typo in
                    # HARBOR_VOICE_FILLER_PICKER used to mean every filler line spawned
                    # another thread that raised and was swallowed, forever, with
                    # /voice/health saying "<typo> (not started)" and nothing anywhere
                    # saying the name is not a picker. It settles on the keyword picker
                    # permanently and the reason is on /voice/health. Raised by review.
                    self._picker = self._keyword
                    self._picker_why = why

            threading.Thread(target=build, name="voice-filler-picker",
                             daemon=True).start()
        return waiting

    @property
    def picker_name(self) -> str:
        """What /voice/health says, WITHOUT building one and without waiting."""
        with self._picker_lock:
            if self._picker is not None:
                if self._picker_why:
                    return (f"{self._picker.name} (fell back from "
                            f"{config.FILLER_PICKER!r}: {self._picker_why})")
                return self._picker.name
            if self._picker_building:
                return f"keyword (building {config.FILLER_PICKER})"
            return f"{config.FILLER_PICKER} (not started)"

    def line(self, said: str, doc: dict | None = None, stage: str = "open",
             avoid=()) -> "object":
        from . import filler                                            # noqa: PLC0415

        # BOUND ONCE. `self.picker` can change under a caller now that the configured
        # one is built on a background thread, and a record naming a picker that did not
        # choose the line is a small lie in the one place this package keeps its receipts.
        picker = self.picker
        chosen = picker.pick(said, stage, avoid)
        why = check(chosen.text, chosen.stage)
        if why:
            # UNREACHABLE IF THE CORPUS IS WHAT IT CLAIMS TO BE, and checked at build
            # time by bin/keel-voice-corpus check and by the selftest. Here it means
            # the file on disk has drifted from the set that was checked, so it falls to
            # the twelve fixed lines rather than speaking something that failed a guard.
            return filler.Result(filler.table_line(said), "table (guarded)", 0.0,
                                 chosen.text, why)
        return filler.Result(chosen.text, f"corpus/{picker.name}/{chosen.topic}",
                             0.0, chosen.text, "")

    def audio(self, text: str) -> bytes:
        """The rendered clip for a line, or b"" so the chain synthesises it instead."""
        return self.cache.read(text)

    def as_json(self) -> dict:
        return {"backend": self.name, "model": "", "resident": self.resident,
                "picker": self.picker_name, "lines": len(self.lines),
                "stages": {stage: sum(1 for ln in self.lines if ln.stage == stage)
                           for stage in STAGES},
                "audio": self.cache.stats(self.lines)}


def set_stats(chain=None, filler: list[Line] | None = None) -> list[dict]:
    """How much of each (engine, speaker) set is rendered. NEVER RAISES.

    The same walk `keel voice audio` prints and `bin/keel-voice-corpus render` fills, so
    the health page, the verb and the render all count the same sets. A health endpoint
    that stops answering when the corpus is malformed has failed at the one moment it was
    wanted, so a broken corpus comes back as one row carrying the error.
    """
    try:
        sets = audio_sets(chain, filler)
    except Exception as exc:                                            # noqa: BLE001
        return [{"engine": "", "speaker": "", "lines": 0, "rendered": 0, "missing": 0,
                 "error": f"{exc.__class__.__name__}: {exc}"}]
    out = []
    for one in sets:
        row = CACHE.stats(one["lines"], one["voice"])
        row["engine"] = one["engine"]
        row["speaker"] = one["speaker"]
        out.append(row)
    return out


def env_note() -> dict:
    """What /voice/health says about the corpus, without loading a picker.

    `audio` IS THE FILLER IN THE PREFERRED VOICE, which is what it has always been and what
    the filler machinery actually reads. `sets` is the whole picture beside it (V8): one
    row per engine he can pick and per speaker, because a cache that is full for Harbor and
    empty for a house reads as full from `audio` alone, and the house's line is exactly the
    one nobody would notice was silent.
    """
    try:
        lines = load()
    except Exception as exc:                                            # noqa: BLE001
        return {"lines": 0, "error": f"{exc.__class__.__name__}: {exc}"}
    return {"lines": len(lines), "picker": config.FILLER_PICKER,
            "audio": CACHE.stats(lines), "sets": set_stats(filler=lines)}


__all__ = ["Line", "load", "KeywordPicker", "EmbeddingPicker", "CorpusFiller",
           "AudioCache", "CACHE", "TOPICS", "STAGES", "picker_from_config",
           "topic_by_keyword", "key_for", "choose", "env_note", "check",
           "ACKS", "ACK_FAILED", "ack_lines", "pick_ack",
           "CONNECTING", "STILL_CONNECTING", "LEFT_HOUSE", "HANDOFF",
           "handoff_lines", "lines_for", "audio_sets", "set_stats"]
