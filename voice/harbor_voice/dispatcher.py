"""The turn machine: one turn at a time, a generation counter, and the narration table.

THE GENERATION COUNTER IS THE WHOLE OF BARGE-IN, and it is the prior art's hardest-won
bug expressed for a browser. Every turn takes the next generation. Any audio, any text,
any `say` line carrying an older generation is dropped at the boundary rather than
cancelled at the source. Without that, the dead turn's stop signal races in and kills the
NEW answer, which is a bug that only appears when somebody interrupts quickly, which is
exactly when they are least willing to forgive it.

BARGE-IN DURING A HARBOR TURN STOPS THE SPEAKING, NOT THE TURN. Harbor cannot be
un-asked from here: the headless turn is already running and it is already thinking. So
the answer, when it arrives, is KEPT and offered rather than spoken over. That is the
second of the two barge-in screens the mockup draws, and it is a product decision rather
than a limitation to apologise for.

THE NARRATION TABLE IS A TABLE. Every sentence is rendered from an OBSERVED state change,
and the set of sentences is fixed. No model writes narration. Generic filler is what makes
an assistant feel fake and it wears out in a week; "asking Harbor" is a fact, because the
turn really was started before anything was said about waiting for it.

THE ONLY FAILURE DIRECTION IS HARBOR. There is one code-rendered answer left (the exact
phrase table in verbs.py, "what's waiting on me") and if anything about it goes wrong,
`kb` refusing, the fold raising, a sentence that comes back empty, the turn goes to
Harbor. There is no path in this file from any kind of trouble to a guessed answer, and
nothing here ever says it does not know. It asks instead.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import capture as capturemod
from . import config, connected, corpus, drawing, filler, index, speech, verbs
from . import judges as judgesmod
from . import harbormsg
from .harbormsg import SayInbox, send as send_to_harbor

HARBOR = "harbor"
# THE ONE ANSWER CODE STILL RENDERS, and it is a tier only in the sense that the page
# labels it: "board, 0.3s" against "Harbor, 14s". No model, no classifier, no router.
INSTANT = "instant"
# WHAT THE JUDGE'S MENU CALLS THE INSTANT TIER. `judges.PRETURN`'s `route` question offers
# `board_read`, so the rule verdict has to be spelled the judge's way; the tier keeps the
# name the page labels it with. One constant rather than a literal, because the two
# spellings meeting in `rule_route` is exactly where a typo would go unnoticed.
INSTANT_ROUTE = "board_read"
# NOT A THIRD ANSWERING TIER, A SECOND KIND OF TURN. A capture asks nothing, so there is
# nothing to route and nothing to wait for: the words become a card and a fixed ack is
# played. It shares `begin`, `_finish`, the transcript and the generation counter with
# the other two, which is the whole reason it lives in this class.
CAPTURE = "capture"

# NOR IS THIS ONE. A turn that ends quietly (V10's `addressed: no`, and the words that
# close a conversation) asks nothing and answers nothing: it exists so that what he said
# is on the record and no Harbor turn is spent on it. It shares `begin`, the transcript
# and the generation counter with the other three, for the same reason.
QUIET = "quiet"

# THE FOURTH PLACE AN UTTERANCE CAN GO (V4), and it is a real destination rather than a
# tier of answer: a turn taken into ONE CARD'S OWN HOUSE, through `keel converse`. While
# the page is pinned to a card, every talk turn goes there; the page says which card, the
# label says so too, and "back to Harbor" is what ends it.
HOUSE = "house"
CONNECTED_ROUTE = "connected"
# The fourth option the `preturn` judge's `route` question is handed WHILE PINNED, and
# only while pinned (`judges.ask(criteria=...)`, which exists for exactly this). Asking
# the judge to choose between places one of which does not exist yet is what would make
# the shadow log's agreement column measure the wrong thing.
CONNECTED_CRITERIA = {CONNECTED_ROUTE: "Said to the house working on the card they are "
                                       "connected to, whatever it is about"}
# THE SAME SEAM, THE OTHER WAY ROUND (c-419): while he is NOT pinned there is now a place
# an utterance can go that the phrase table cannot name, which is "put me through to the
# house doing that work". The judge is offered it in SHADOW ONLY and nothing reads the
# verdict: the model that picks the CARD is Harbor, with the digest in front of it, and a
# classifier that knows a connect request when it hears one still could not say which house.
# `rule_route` deliberately does NOT answer `connect`, because the rule is what the turn
# actually does and what it does is ask Harbor; a disagreement in the shadow log is the
# measurement, not a bug in the rule.
CONNECT_ROUTE = "connect"
CONNECT_CRITERIA = {CONNECT_ROUTE: "Asks to be put through to the house working on some "
                                   "piece of work, described rather than named by id"}
# WHAT IS SAID WHEN A PIN IS TAKEN OR LET GO LIVES IN `corpus` NOW (V8, card c-316), with
# the rest of the fixed lines, because those lines have rendered clips and a speaker each:
# `corpus.CONNECTING`, `STILL_CONNECTING`, `LEFT_HOUSE`, and `verbs.entering` /
# `verbs.leaving` for the two with the card's name in them. Two placeholders that used
# to sit here ("Connected to {card}.", "Back to Harbor.") are gone rather than kept beside
# them: a second set of words for the same moment is the way a voice starts disagreeing
# with itself.

# HOW MANY TIMES THE `narrate` JUDGE IS ASKED IN ONE CONNECTED TURN (V10, c-317).
#
# `judges._SHADOW_BUSY` is ONE SLOT AND IT IS MODULE-GLOBAL, shared by every judge. A
# chatty turn is forty tool calls and about twenty narration candidates, and a seat that
# asked on every one of them would spend the whole turn holding the slot: `preturn`, which
# has a turn WAITING on it, would be dropped as `busy` for the length of the conversation,
# and so would most of this seat's own calls. So the seat asks about the first few
# candidates and then stops asking, and the stopping is LOGGED (`CAPPED`) rather than
# silent, because a judge report that showed five calls on a forty-call turn would
# otherwise read as a quiet turn rather than a capped one.
NARRATE_SHADOW_CAP = 5
# The miss reason written when the cap or the `preturn` guard turned a call away. It is a
# miss and not a disagreement, which is what `keel/judges.py`'s tally already does with
# every other reason: an absence, never evidence either way.
CAPPED = "capped"
# HOW LONG THE DELAYED ANSWER WAITS FOR HIM TO STOP TALKING (V5). It never interrupts him,
# so when it lands mid-sentence it waits for that turn to end, the same "is a turn over"
# question `refine` already asks. Past this it is treated as him being gone.
LATE_ANSWER_WAIT = 120.0
LATE_ANSWER_POLL = 0.4


def narration_repeat(previous: str, current: str) -> bool:
    """V5's "never the same progress line twice in a row", asked of the ACTION.

    The same rule `keel/narration.py` enforces on the writing side, restated here because
    this is the side that decides what is SPOKEN and the two are not the same question: the
    writer stops a duplicate from crowding the inbox, this stops one that arrived anyway
    (a `keel converse` from another machine's relay, a line left from a turn that was cut)
    from being said twice running.
    """
    return bool(current) and previous == current


def answer_left(parts: list, answer: str) -> tuple[str, str]:
    """(what of this answer still has to be said out loud, and why), given what was spoken.

    THIS IS WHAT "HE HAS ALREADY HEARD IT" COSTS TO BE TRUE (V13, 2026-09-21). V12 ended a
    streamed turn silently whenever `spoke_parts` was non-empty, which reads as "some of it
    was spoken" and was used as "all of it was". On 2026-09-21 turn `8c5a99dae023` spoke
    one sentence of two and finished as "the answer was spoken as it streamed"; the second
    sentence was never said at all. The fix is not a better guess, it is a COMPARISON: the
    claim is checked against the answer before it is made, and what it answers is exactly
    the text that is still owed.

    THE THREE ANSWERS, and each one is a different thing to do:

    - `""` means the parts COVER the answer and the turn may finish silently.
    - a SLICE of the answer means the stream stopped short, and that slice is spoken. It
      is taken out of the answer's own text, never rebuilt out of the parts, so what he
      hears is the house's words rather than this function's idea of them.
    - the WHOLE answer means there is no honest remainder: nothing was spoken, or what was
      spoken is not the beginning of this answer. Taking a remainder off a wrong prefix
      would cut a sentence off at its start, which is worse than hearing one sentence
      twice.

    THE COMPARISON IS ON WHAT CAN BE HEARD. A streamed part has had its markdown stripped
    by the cutter and the final answer has not, so the two spellings of one sentence differ
    by characters nobody can hear; `verbs.heard_key` is that normalisation, and it keeps
    the map back into the real text that the slice is taken with.

    AND A CODE BLOCK IS THE CUTTER'S STAND-IN ON BOTH SIDES (lane H, H5). The parts said
    "There is a code block in my answer" where the block was; the answer still carried the
    code, so a covered answer never matched and was spoken again, code included. So `whole`
    is the answer's SPEAKABLE form (`verbs.without_code`): what is spoken from here, the
    remainder or the whole, never carries a block either.
    """
    whole = verbs.as_heard(answer)
    if not whole:
        return "", "there was nothing to say"
    spoken_key, _ = verbs.heard_key(" ".join(str(one or "") for one in parts))
    if not spoken_key:
        return whole, "nothing of it was spoken"
    key, where = verbs.heard_key(whole)
    if not key.startswith(spoken_key):
        return whole, "what was spoken is not the start of the answer"
    if len(spoken_key) >= len(key):
        return "", "covered"
    # THE FIRST CHARACTER OF THE ANSWER HE HAS NOT HEARD, in the cleaned text rather than
    # in the key: `where` is what carries that across. The leading punctuation and space
    # between the two sentences belong to the one already spoken, so they are trimmed.
    return whole[where[len(spoken_key)]:].lstrip(" .,;:!?-"), "the stream stopped short"


def new_turn_id() -> str:
    """The id of a turn, mintable BEFORE the turn exists.

    V10's `preturn` judge is asked in the gateway, after the transcript and before this
    module is reached, so the seat needs the id the turn will carry in order to log its
    call against it (`voice/harbor_voice/server.py`). One function rather than two spellings
    of `uuid4().hex[:12]`, so the judges log and the turn log can never name a turn
    differently.
    """
    return uuid.uuid4().hex[:12]


class Turn:
    """One thing he said and everything that came of it."""

    __slots__ = ("id", "generation", "said", "tier", "started", "route_seconds",
                 "answered_at", "answer", "narration", "phase", "held", "error",
                 "verb", "provenance", "last_spoken_at", "gave_up", "spoken",
                 "clients_at_start", "opened", "eta", "mode", "card", "space", "pcm",
                 "engine", "speaker", "spoke_with", "house", "connect_key", "connect",
                 "spoke_parts", "parts_cut", "answering", "leave", "first_audio_at",
                 "streams", "typed", "boards", "picked")

    def __init__(self, generation: int, said: str, turn_id: str = ""):
        # MINTED HERE UNLESS SOMEBODY ALREADY NEEDED IT. The preturn seat mints the id
        # before the turn starts so its shadow-log line names this turn; everything else
        # passes nothing and gets a fresh one.
        self.id = str(turn_id or "") or new_turn_id()
        # THE RECORDING THIS TURN CAME OUT OF, when the opt-in corpus recorder is on.
        # Set on the instance rather than only in `begin` so every Turn ever built,
        # including the ones the selftest makes by hand, can be logged.
        self.pcm = ""
        # WHAT `keel converse` SENT BACK BESIDE THE SENTENCE, on a connected turn (V5):
        # the hold's new expiry and whether the pin has gone. The worker thread stashes
        # it here and the watching thread acts on it, because the pin is not the worker's
        # to move. None on every other kind of turn.
        self.house: dict | None = None
        self.generation = generation
        self.said = said
        self.tier = HARBOR
        self.started = time.time()
        self.route_seconds = 0.0
        self.answered_at = 0.0
        self.answer = ""
        self.narration: list[str] = []
        self.phase = "routing"
        self.held = False        # an answer that arrived after he cut in
        self.error = ""
        self.verb = ""
        self.provenance = ""
        # WHEN SOMETHING WAS LAST ACTUALLY SAID, so the wait can tell a real silence
        # from one that just started. Starts at `started` rather than 0.0: before
        # anything has been spoken, the wait is measured from the turn itself.
        self.last_spoken_at = self.started
        # ONCE TRUE, THE PROMISE IS TEXT. The 90 s giveup line says "I'll answer in
        # text instead", and it used to be just words: whatever arrived after it was
        # still spoken out loud the moment it landed. This flag is what makes the
        # promise binding for the rest of this turn.
        self.gave_up = False
        # WHETHER THE FINAL ANSWER WAS ACTUALLY VOICED. True for the instant answer and
        # for an ordinary Harbor turn; false when it went to text instead, either because
        # he had already been told to expect that (`gave_up`) or because nobody was
        # there to hear it.
        self.spoken = True
        # RECORDED, NOT ACTED ON. How many clients were connected when this turn
        # began, so a later reading of the transcript can tell whether he was on the
        # line at the start without having to have been watching live.
        self.clients_at_start = 0
        # WHETHER THE PRE-WORK LINE HAS BEEN SPOKEN. `opening` is claimed at most once
        # per turn; once this is true the watch loop stops looking at that inbox for
        # the rest of the turn, so a second `opening` call (a framing violation, not a
        # thing the machine should trust) cannot repeat it.
        self.opened = False
        # WHAT HARBOR ITSELF SAID TO EXPECT (c-229), IN SECONDS, OR NONE. Read off the
        # `opening` call's own `--eta`, if it carried one; the give-up mark then tracks
        # this instead of the flat default. None for a "quick" turn, or a caller that
        # never sent one, which keeps today's behaviour exactly.
        self.eta: float | None = None
        # WHICH OF THE TWO MODES THIS TURN IS (config.MODES), on every transcript line so
        # a later reading can tell a capture from a conversation without guessing from
        # the tier. `card` and `space` are a capture's receipt: the id `kb create`
        # printed and the space it was filed in. Shown on the page, never spoken.
        self.mode = config.MODE_TALK
        self.card = ""
        self.space = ""
        # WHICH SYNTHESISER HE ASKED FOR (V7), carried on the `end` message beside the
        # mode. Empty is "no preference": the configured chain in its configured order.
        self.engine = ""
        # AND WHICH ONES ACTUALLY SPOKE, in the order they first did. Not the same
        # question: the chain demotes per sentence, so a turn can start on Google and
        # finish on Kokoro, and only this knows it. Shown on the page's provenance line.
        self.spoke_with: list[str] = []
        # WHEN THIS TURN'S FIRST SYNTHESISED AUDIO LEFT FOR THE PAGE (D-5), for
        # `keel voice latency`. Recorded once, as a `first-audio` transcript line.
        self.first_audio_at: float | None = None
        # A HARBOR TURN WHOSE ANSWER STREAMS IN PARTS (R2, `[voice] harbor_kept_alive`).
        # False is every Harbor turn as it was: one answer, spoken whole.
        self.streams = False
        # WHOSE ANSWER THIS IS (V8, card c-316). Harbor's, unless the turn went to a
        # connected house and the house actually answered: see `_ask_house`, where a
        # REFUSAL sets it back, because a refusal is the gateway speaking about a house
        # and not the house speaking.
        self.speaker = config.SPEAKER_HARBOR
        # THE CONNECT DIRECTIVE'S TWO HALVES (c-419). `connect_key` is minted for this turn
        # on the way OUT, in `_ask_harbor`, and rides in the framing; `connect` is the card
        # the answer named on the way back, once the key matched. Both are empty on every
        # other kind of turn, and an empty key can match nothing, which is what stops a
        # house's answer from moving the pin.
        self.connect_key = ""
        self.connect = ""
        # HIS PICK ON ONE OF BOSUN'S ASKS (c-523): (ask, letter).
        self.picked: tuple[str, str] | None = None
        # WHAT OF THE ANSWER HAS ALREADY BEEN SAID OUT LOUD (V12), sentence by sentence,
        # while the turn was still running. Non-empty means the final answer must not be
        # spoken again: he has already heard it. `parts_cut` says the streaming was
        # STOPPED part way (he barged in, or nobody was listening any more), which is the
        # one case where the whole answer IS spoken afterwards, because what he heard was
        # half of one. `answering` is the latch that ends this turn's narration: once the
        # house has started answering, nothing may be said over it.
        self.spoke_parts: list[str] = []
        self.parts_cut = False
        self.answering = False
        # WHETHER THE HOUSE ASKED TO END THE CONVERSATION (2026-09-21). `keel converse`
        # reads the `<<keel-leave>>` directive off its own answer and reports it beside the
        # sentence; this carries it from the worker to the watching thread, exactly as
        # `house` carries the hold's new expiry, because the pin is not the worker's to
        # move. False on every other kind of turn.
        self.leave = False
        # TYPED, SO ANSWERED IN TEXT ONLY (VP-3, his decision of 2026-09-24). Set by the
        # gateway on a line typed on the voice page, and read at the one place a turn
        # becomes sound, `Dispatcher._say`, so a typed turn has no second path to drift
        # along: its narration, its filler, its streamed parts and its answer are all shown
        # and none of them is spoken. True inside a Conversation as well.
        self.typed = False
        # THE BOARDS THIS TURN'S ANSWER DREW (VP-5), as the say record carried them from
        # `drawing.read_answer`, so the page can draw the real board as the receipt.
        self.boards: list[str] = []

    @property
    def elapsed(self) -> float:
        return (self.answered_at or time.time()) - self.started

    def as_json(self) -> dict:
        return {"id": self.id, "tier": self.tier, "since": round(self.elapsed, 2),
                "phase": self.phase, "text": self.said, "verb": self.verb,
                "answer": self.answer, "narration": list(self.narration),
                "held": self.held, "provenance": self.provenance,
                "routeSeconds": round(self.route_seconds, 3),
                "spoken": self.spoken, "gaveUp": self.gave_up, "eta": self.eta,
                "mode": self.mode, "card": self.card, "space": self.space,
                "engine": self.engine, "speaker": self.speaker,
                "spokeWith": list(self.spoke_with), "error": self.error,
                "typed": self.typed, "boards": list(self.boards)}


# THE NARRATION TABLE. Trigger on the left, spoken sentence on the right, and every
# trigger is something this process OBSERVED rather than assumed.
#
# THERE IS NO TIMER IN HERE, AND THERE MUST NEVER BE ONE AGAIN. This table used to carry
#
#     "elapsed": "still working, twelve seconds."
#
# and it was spoken aloud twice on 2026-09-03, at 23:59 and again at 00:01. The user named
# it as wrong, and it is: nobody says "twelve seconds" to a person. It is a stopwatch read
# out loud. It also broke the rule this table exists to enforce, because the elapsed time
# is not an observation about HIS QUESTION, it is an observation about the clock, and the
# clock has nothing to say. The plan's words are "the wait narrates real state and never
# filler"; a number counting up is the purest filler there is.
#
# It was replaced by nothing rather than by a better sentence, and that is the decision.
# The wait is SHOWN, not spoken: the page already has a thinking state, a waveform and a
# loading flag, and a screen is where a progress indicator belongs. Speech is for things
# worth interrupting a person to say.
#
# What survived is the one thing that IS worth saying at twelve seconds, and only when it
# is true: that Harbor has stopped and is waiting on something. That is not the clock, it
# is a state change, and it is the difference between a wait that will end and one that
# will not.
#
# PERSONA UNITY, 2026-09-04, and it is why these sentences are in the first person now.
# The wait used to open "asking Harbor.", which is a true sentence said by the wrong
# mouth: it told him that the thing he was talking to was not the thing about to answer.
# Every line here is Harbor speaking as itself, and the filler that now opens the wait
# (filler.py) is written in the same voice, so the whole wait is one person talking.
#
# The one instant answer is deliberately NOT in the first person. It is read out of the
# board by code, it leads with the record it read (WAITING_LEAD below, which is what is
# left of the turn-15 fix), and the app labels it "board, 0.3s" against "Harbor, 14s". A
# record that speaks impersonally and a dispatcher that says "I" is the distinction he
# can hear, and it is worth keeping audible.
NARRATION = {
    # Said once, as soon as the turn is really running. It is an acknowledgement, not
    # a progress report: it tells him he was heard, and then the gateway is quiet until
    # there is an answer. This is the FALLBACK wording; when the filler is on, the line
    # spoken here is the filler's, and the trigger is the same verified delivery.
    "delivered": "right, let me have a proper look at that.",
    "spawned": "I've just started {name}.",
    "card": "a card just landed: {title}.",
    "review": "a review page just opened.",
    # THE FLAT BACKSTOP, for a turn that never named an eta (a "quick" turn Harbor
    # judged wrong with nothing to hold it to, or an older client). Unchanged from
    # c-221.
    "giveup": "I'm still on it, and I'll answer in text instead.",
    # c-229: A TURN THAT NAMED A NUMBER AND MISSED IT. Reports the broken promise in
    # words, never the clock (dispatcher.py's own standing rule, a few lines up): this
    # says WHAT happened ("longer than I said"), not by how much.
    "giveup_eta": "That's taking longer than I said, so I'll answer in text instead.",
    # NO LONGER "into Harbor's pane": the destination is a conversation, and naming a
    # thing that does not exist is the one way a fixed sentence can be wrong. What he
    # needs to hear is unchanged, which is that the turn did not get there.
    "undelivered": "I could not get that through to Harbor.",
    # THE GIVE-UP ON A CONNECTED TURN, AND IT IS THE ONE PLACE THAT PATH DIFFERS (V5).
    # An ordinary turn promises TEXT, and that promise is binding: the answer goes to a
    # card and is never spoken. A connected turn cannot make that promise, because the
    # answer is already going to the card he is talking to (`converse.record` writes the
    # exchange with his words verbatim), so a second card would be a duplicate record
    # filed against a different card. It promises the ANSWER instead, and holds it.
    # THERE IS NO CONNECTED OPENER IN THIS TABLE ANY MORE, AND THAT IS THE DECISION
    # (2026-09-21). V5 put `corpus.HOUSE_OPENER` here, "Heard you, passing that to the
    # house now", spoken at the top of EVERY connected turn: it was cover for a cold
    # process, back when connecting meant stopping one `claude` and starting another. With
    # V12 the conversation is already open and the first spoken part lands in about three
    # seconds, so the line was both wrong in fact (he is already inside the house, nothing
    # is being passed anywhere) and wrong in shape, because it announced a wait that had
    # usually ended before it finished playing. A connected wait is covered the way a
    # Harbor wait is now: the ordinary filler corpus, and only when the wait really goes
    # quiet (`_ask_house`, and the silence gate in `_watch`).
    # NOT "still working": that phrase is banned outright by the selftest, because
    # "still working, twelve seconds" was spoken on 2026-09-03 and named as wrong. The
    # ban is on the words rather than on the clock, and the words are not worth an
    # argument.
    "giveup_house": "The house is still going. I'll tell you when it answers.",
    # WHAT AN ANSWER THAT ARRIVED MINUTES LATE OPENS WITH. It is unattributable by ear
    # otherwise: he asked three minutes and one other question ago. One line, once, and
    # it names the card because he asked about that card, which the egress split allows.
    "house_late": "About {card}.",
    # AN ANSWER THAT WAS NOTHING BUT A DIRECTIVE (c-419). The framing asks for a sentence
    # and then the directive, so this is a model that skipped the sentence; the turn would
    # otherwise end in silence and then four lines of handoff out of nowhere. It names no
    # card, because the handoff's own line 2 names it a second later and in the house's
    # own voice.
    "connect_bare": "Right, putting you through.",
    # A CONNECTED TURN THAT WAS ENDED RATHER THAN ANSWERED. Said once and it is the only
    # thing said on that path: the card has the rest, including how far it got.
    # NOT "that one": the selftest bans every number word outside `busy`, because a
    # number in a spoken line is almost always a stopwatch being read out.
    "house_stopped": "That did not come back. It is on the card.",
    # A THIRD UTTERANCE WHILE ONE RUNS AND ONE WAITS. One conversation, one transcript,
    # and he is one person with one mouth: the honest answer is that there is already a
    # queue of one, not a third turn racing the other two.
    "busy": "One at a time, I'm still on the last one.",
}

class Dispatcher:
    """Everything that happens between him letting go of the button and hearing an answer.

    One turn at a time, deliberately. He is one person with one mouth, and a second
    concurrent turn would mean two answers competing for one speaker.
    """

    def __init__(self, snapshot, bus, speak, inbox=None, transcript=None,
                 deliver=None, filler_model=None, progress_inbox=None, open_inbox=None,
                 notify=None, presence=None, clients_fn=None, queue_answer=None,
                 attending=None,
                 file_capture=None, captured=None, turn_over=None, pin_changed=None,
                 connect_asked=None, leave_asked=None, answer_asked=None):
        self.snapshot = snapshot
        # WHO SPEAKS DURING THE WAIT. Injected like `deliver`, and for the same reason:
        # the selftest has to be able to exercise the wait without a resident model.
        self.filler = filler_model if filler_model is not None else filler.from_config()
        self.bus = bus
        # callable(text, generation, spoken) -> the chain's report, whose "engines"
        # key names what actually spoke. `spoken` is speech.Spoken: this call's
        # engine and speaker (V7), never chain state.
        self.speak = speak
        # HOW A TURN REACHES HARBOR, injected rather than imported, and that is not
        # abstraction for its own sake. It was a module-level import, and the selftest
        # therefore could not exercise the Harbor tier without ACTUALLY typing into
        # Harbor's live pane: two spurious questions per run, on every promotion gate and
        # every harbor-check, which Harbor then answered and spent a turn on. Review
        # caught it, and the pane confirmed it had already happened. A test that has to
        # avoid a code path to be safe is a code path with no test.
        self.deliver = deliver or send_to_harbor
        self.inbox = inbox or SayInbox()
        # HARBOR'S OWN NARRATION OF THE WAIT, a separate inbox from the answer's. See
        # harbormsg.PROGRESS_DIR: writing here can never finish a turn early, the way
        # writing into `self.inbox` would.
        self.progress_inbox = progress_inbox or SayInbox(harbormsg.PROGRESS_DIR)
        # THE PRE-WORK LINE, a third inbox again for the same reason: `say` ends the
        # turn on its first line, and the opener the per-turn framing asks for is not
        # that line. See harbormsg.OPENING_DIR and review round 1, 2026-09-07, which
        # found the version that shared `say` for both.
        self.open_inbox = open_inbox or SayInbox(harbormsg.OPENING_DIR)
        # WHETHER HE IS ACTUALLY THERE. Injected like everything else that reaches
        # outside this file: the default assumes he is, which is what every existing
        # caller and test wants, and the gateway is the one place that supplies a real
        # answer. `notify` is the best this process can do when he is not: broadcast to
        # any page that IS open, so it can raise its own notification. Neither call may
        # ever cost the answer, so both are wrapped at the call site.
        self.presence = presence or (lambda: True)
        # A PAGE HE CAN SEE (D-2), stricter than `presence` and read by unprompted speech
        # alone: a screen switched off keeps its socket, and `presence` cannot tell.
        self.attending = attending or (lambda: True)
        self.notify = notify or (lambda turn, text, reason: False)
        self.clients_fn = clients_fn or (lambda: 0)
        # HOW THE GIVE-UP PROMISE IS KEPT (c-229). Injected like `deliver`: the selftest
        # has to be able to assert on this without actually shelling out to
        # `harbor-queue`, the same reason `deliver` is not a bare module import.
        self.queue_answer = queue_answer or harbormsg.queue_answer
        # HOW A CAPTURE REACHES THE BOARD, and what is told once it has. Injected like
        # `deliver`, so the turn machine can be exercised without a `kb` anywhere.
        # `captured(turn, card)` is the gateway's: it broadcasts the id to the page and,
        # when the refine is on, queues the card for it. It may never cost the capture.
        self.file_capture = file_capture or capturemod.file
        self.captured = captured or (lambda turn, card: None)
        # WHEN A TURN IS REALLY OVER, which is what conversation mode needs and nothing
        # else in this file has ever had to know. Injected like the rest: this class
        # holds no socket and has no opinion about whether another utterance is coming.
        #
        # IT IS NOT "WHEN SOMETHING FINISHED SPEAKING". `speak` runs for every narration
        # line and every filler too, and re-arming a microphone on one of those would
        # open it in the middle of a turn, while Harbor was still thinking. So the hook
        # is on the two places a TURN ends, `_finish` and `_finish_silent`, after the
        # phase is `done`.
        self.turn_over = turn_over or (lambda turn: None)
        self.last_ack = ""
        # THE PIN (V4): the card he is connected to, when it runs out, and nothing else.
        # It is the only state this class keeps between utterances, and it is deliberately
        # a copy of what the BOARD holds: `options.voice_hold` on the card is the lock, and
        # `held_until` comes back on every answer so the two cannot drift. A gateway that
        # restarts mid-conversation forgets the pin and the hold expires by itself, which
        # is the right way round: the board heals, the process does not have to.
        self.pin: dict | None = None
        # WHAT TO TELL WHEN THE PIN MOVES (V8), injected by the gateway exactly as
        # `deliver` and `speak` are, and for the same reason: this class decides, and the
        # thing with a socket and a synthesiser does. The gateway uses it to arm the
        # announcement of the pin's own expiry, so a conversation he walks away from ends
        # in a sentence rather than in silence.
        self.pin_changed = pin_changed or (lambda state: None)
        # WHAT TAKES A PIN THE MODEL ASKED FOR (c-419), injected exactly as `pin_changed`
        # and `deliver` are. This class decides WHETHER a directive may be acted on, and
        # the thing with a socket, a synthesiser and `keel converse` behind it does the
        # connecting: `Gateway.connect_to`, the same call the spoken phrase makes, so
        # every guard, every refusal and all four lines of the heard handoff are the ones
        # that already exist rather than a second copy of any of them.
        self.connect_asked = connect_asked or (lambda card: False)
        # WHAT ENDS THE CONVERSATION WHEN THE HOUSE WAS ASKED TO (2026-09-21), injected
        # exactly as `connect_asked` is and for the same reason: this class decides WHETHER
        # the directive may be acted on, and the thing with a socket, a synthesiser and
        # `keel converse` behind it does the leaving. It is `Gateway.leave_by_house`, which
        # is `disconnect(spoken=True)`, the same call the spoken phrase and the tap on the
        # header make, so the release, the line, the tone and the re-arm are the ones that
        # already exist rather than a second copy of any of them.
        self.leave_asked = leave_asked or (lambda: False)
        # WHAT RECORDS HIS ANSWER TO ONE OF BOSUN'S ASKS (c-523), injected like the two
        # above: this class decides whether the directive may be acted on (this turn's key,
        # the end of the answer, spoken), and `Gateway.answer_by_model` hands it to the page,
        # which is him on the deck, to record. Nothing here holds his token.
        self.answer_asked = answer_asked or (lambda ask, letter, words: False)
        self.transcript_path = Path(transcript or (config.DATA / "transcript.jsonl"))
        self.generation = 0
        self.turn: Turn | None = None
        self.history: list[Turn] = []
        self._lock = threading.Lock()
        self._watcher: threading.Thread | None = None
        # HELD FOR THE WHOLE OF EACH WATCH PASS (c-418). A pass claims the answer inbox and
        # then the opener inbox; a writer between the two claims made "which one did this
        # pass see" a matter of timing, and the selftest that proves an opener losing the
        # race to the answer failed on a slow machine. Holding this while writing both is
        # how a test says "the same pass". One uncontended lock per poll in production.
        self.pass_gate = threading.Lock()

    # -- what the page sees ------------------------------------------------ #

    def alert(self) -> bool:
        """A pending approval, or a blocked dispatch. Read from the document, never
        derived: `counts.alert.now` is the same flag the dashboard's badge goes red on,
        so the bar in the app and the badge on the dashboard cannot disagree."""
        counts = (self.snapshot.doc.get("counts") or {})
        flags = counts.get("alert") or {}
        return bool(flags.get("now") or flags.get("running") or flags.get("rooms"))

    # -- starting a turn --------------------------------------------------- #

    def rule_route(self, said: str, mode: str = "") -> str:
        """Where this utterance goes today: `capture`, `connected`, `board_read` or `talk`.

        THIS IS THE `preturn` JUDGE'S RULE VERDICT for `route` (V10), asked by the
        gateway's seat before the turn starts. It lives here, and it reads the same
        `verbs.is_waiting_question` that `_instant` reads, so the verdict written to the
        shadow log is the decision this class is about to make rather than a second
        router's guess at it. A rule that could disagree with what then happened would
        make the log's agreement column measure the copy instead of the model.
        """
        if mode == config.MODE_CAPTURE:
            return CAPTURE
        if self.pinned():
            # PINNED BEATS THE READ, and the rule says so rather than saying "talk" and
            # meaning something else. While he is connected, the sentence goes to the
            # house: that is what the pin IS, and a `board_read` verdict may not take a
            # sentence away from the house he is talking to (the seat ignores `route`
            # while pinned, and this is the verdict the log compares against).
            return CONNECTED_ROUTE
        return INSTANT_ROUTE if verbs.is_waiting_question(said) else "talk"

    # -- the pin (V4) ------------------------------------------------------ #

    def pinned(self) -> str:
        """The card he is connected to, or "". An expired pin is no pin: the board's hold
        runs out on the same clock, and the drain wakes the house when it does."""
        if not self.pin:
            return ""
        if self.pin.get("until") and time.time() >= self.pin["until"]:
            self.pin = None
            return ""
        return self.pin.get("card") or ""

    def pin_to(self, card: str, until: float | None = None, title: str = "",
               space: str = "") -> None:
        # THE SPACE TRAVELS WITH THE PIN (V8) because the header takes the house's colour
        # while it holds, and a house's colour is its card's space: the deck has exactly
        # two palettes and they already mean something, so a third invented here would
        # mean one thing on this page and nothing anywhere else.
        self.pin = {"card": card, "until": until, "title": title, "space": space}
        self.bus.set_connected(self.pin_state())
        self.pin_changed(self.pin_state())

    def unpin(self) -> str:
        """Drop the pin and say which card it was."""
        card = (self.pin or {}).get("card") or ""
        self.pin = None
        self.bus.set_connected(None)
        self.pin_changed(None)
        return card

    def pin_state(self) -> dict | None:
        """What the page shows in its header while connected."""
        card = self.pinned()
        if not card:
            return None
        return {"card": card, "title": self.pin.get("title") or "",
                "space": self.pin.get("space") or "",
                "until": self.pin.get("until")}

    def hold_seconds(self, until: str | None) -> float | None:
        """The board's `held_until` as this process's clock, so one number governs both the
        card's hold and the page's pin."""
        if not until:
            return None
        try:
            stamp = datetime.fromisoformat(until)
        except (TypeError, ValueError):
            return None
        if stamp.tzinfo is None:
            stamp = stamp.astimezone()
        return time.time() + max(0.0, (stamp - datetime.now().astimezone()).total_seconds())

    def begin(self, said: str, pcm: str = "", turn_id: str = "") -> Turn:
        """A new turn, which supersedes whatever was going on.

        `turn_id` IS THE ID THE PRETURN JUDGE ALREADY LOGGED AGAINST, when the gateway
        minted one before this turn started (`new_turn_id`). Empty is the ordinary case
        and mints a fresh one.

        `pcm` IS THE RECORDING THIS TURN CAME OUT OF, when the opt-in recorder is on
        (record.py): the wav's file name, carried onto every transcript line the turn
        writes so `bin/keel-voice-vad-measure` can join text to audio. Empty is the
        shipping case and empty writes no field at all.

        THE ORDER MATTERS. The generation moves FIRST, so anything still in flight is
        already stale by the time it tries to speak, and the say inbox is drained so an
        answer to the previous question cannot be spoken over this one.
        """
        with self._lock:
            self.generation += 1
            previous = self.turn
            turn = Turn(self.generation, " ".join(str(said or "").split()), turn_id)
            turn.pcm = str(pcm or "")
            self.turn = turn
        if previous is not None and previous.phase not in ("done", "held"):
            # HELD, NOT CANCELLED, when something is still thinking about it. We cannot
            # un-ask Harbor or a house, so the answer is kept rather than discarded or
            # spoken over. Everything else is simply superseded.
            #
            # A HOUSE TURN IS HELD TOO, AND UNTIL c-317's SEND-BACK IT WAS NOT. `held` is
            # what keeps `_watch`'s loop alive past the generation moving; without it a
            # superseded connected turn left the loop on the next 0.4 s tick and its
            # answer sat in the say inbox until the next `begin()` drained it as
            # `dropped`. Never spoken, never noted, and the `held_until` and `unpin` the
            # verb asked for went with it.
            #
            # THAT WAS A CORNER UNTIL V5 AND IT IS THE COMMON CASE NOW. A connected turn
            # used to block inside `_ask_house` and come back answered, so "he said
            # something else while it was running" could not happen; it is asynchronous
            # now, and a house turn that edits something takes a minute.
            #
            # The two tiers then part company at the claim: a held HARBOR answer is kept
            # to be READ ("Harbor answered while you were talking"), because he re-asked
            # the question and the old answer is usually stale. A held HOUSE answer is
            # kept to be SPOKEN, by `_house_answer`, because it is a minute of that
            # house's work on a question he has not re-asked and could not re-ask without
            # waiting all over again.
            held_tiers = (HARBOR, HOUSE)
            previous.phase = "held" if previous.tier in held_tiers else "superseded"
            previous.held = previous.tier in held_tiers
        # EVERY DROP IS LOGGED, against the turn that supersedes it: a line that lost the
        # race (an opener that arrived in the same pass `say` claimed and ended the turn
        # on, most commonly) is not spoken, but it is not silent either. Review round 3,
        # 2026-09-07, found the opener was the one channel here with no record at all.
        for channel, inbox in (("say", self.inbox), ("progress", self.progress_inbox),
                                ("opening", self.open_inbox)):
            for rec in inbox.drain():
                text = str((rec or {}).get("text") or "").strip()
                if not text:
                    continue
                if (rec or {}).get("part"):
                    # A SENTENCE OF AN ANSWER, ARRIVING AFTER ITS TURN WAS OVER (V13).
                    # It is not a generic drop and reading it as one is what hid the
                    # truncated answer in his transcript: four `dropped` lines on the
                    # progress channel read as narration going missing, when what had
                    # gone missing was most of what the house said. Named, and named
                    # WITH THE TURN IT BELONGED TO, because the turn it is logged
                    # against is the one that superseded it.
                    self._log(turn, "late-part", channel=channel, text=text,
                              forTurn=str((rec or {}).get("turn") or ""))
                    continue
                self._log(turn, "dropped", channel=channel, text=text)
        self.bus.set_turn(turn.as_json())
        return turn

    def cut(self) -> None:
        """He pressed while it was speaking. Stop the speaking, keep the turn.

        Q3 is built as `cut_and_listen`: the same press that cuts also starts listening,
        so an interruption is one gesture rather than two. The listening half is the
        page's, because the microphone is; this is the half that stops the audio.
        """
        with self._lock:
            self.generation += 1
        self.bus.set_state("idle")
        turn = self.turn
        if turn is not None and turn.phase == "speaking":
            turn.phase = "cut"

    # -- capturing --------------------------------------------------------- #

    def capture(self, said: str, space: str = "", heard=None,
                released_at: float | None = None, pcm: str = "",
                engine: str = "", turn_id: str = "", typed: bool = False) -> Turn:
        """The whole of a capture: file the card, play the ack. No model, no wait.

        `released_at` IS WHEN HE LET GO OF THE BUTTON, when the socket knows it. The
        number under the turn is the one he experiences, release to ack, so it includes
        the speech model; a typed capture has no release and is measured from `begin`.

        NOT GATED ON PRESENCE, unlike a late Harbor answer: he spoke a second ago, so he
        is there. And never under harbormsg's turn lock: there is no model turn here to
        serialise, so a capture lands inside a second even while Harbor is thinking.
        """
        turn = self.begin(said, pcm, turn_id)
        turn.engine = engine
        turn.typed = bool(typed)
        turn.mode = config.MODE_CAPTURE
        turn.tier = CAPTURE
        turn.phase = "capturing"
        since = released_at or turn.started
        try:
            turn.clients_at_start = int(self.clients_fn())
        except Exception:                                              # noqa: BLE001
            turn.clients_at_start = 0
        repairs = [{"heard": a, "readAs": b} for a, b in (heard or [])]
        extra = {"repairs": repairs} if repairs else {}
        self._log(turn, "said", clients=turn.clients_at_start, **extra)
        self.bus.set_turn(turn.as_json())
        try:
            card = self.file_capture(turn.said, space, heard)
        except Exception as exc:                                       # noqa: BLE001
            # SPOKEN, ONCE, AND NOTHING IS LOST. His words are already on the page and
            # in the transcript (the `said` record above), which is what the failure
            # line tells him. The cause goes to the log in kb's own words.
            turn.error = f"{exc.__class__.__name__}: {exc}"
            self._log(turn, "capture-failed", error=turn.error)
            harbormsg.log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: a capture did "
                          f"NOT land on the board: {turn.error}")
            return self._finish(turn, corpus.ACK_FAILED, CAPTURE, "not captured")
        turn.card = str(card.get("id") or "")
        turn.space = str(card.get("space") or "")
        ack = corpus.pick_ack(avoid=self.last_ack)
        self.last_ack = ack
        seconds = time.time() - since
        self._log(turn, "captured", card=turn.card, space=turn.space,
                  seconds=round(seconds, 2))
        harbormsg.log(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] voice: captured "
                      f"{turn.card} in {turn.space}, {seconds:.2f}s from release to "
                      f"ack, playing {ack!r} "
                      f"({'rendered' if corpus.CACHE.read(ack) else 'not rendered, synthesised'})")
        try:
            self.captured(turn, card)
        except Exception as exc:                                       # noqa: BLE001
            self._log(turn, "captured-hook-failed",
                      error=f"{exc.__class__.__name__}: {exc}")
        return self._finish(turn, ack, CAPTURE, f"card {turn.card}, {seconds:.1f}s")

    def announce(self, text: str) -> bool:
        """Speak one sentence that belongs to no turn. The refine used to be its caller and
        speaks no more (D-3); this stays the one door for a line nobody asked for, gated
        on a page he can see (D-2).

        NOT THROUGH THE SAY INBOX, and that is a deliberate departure from the plan's
        wording ("into the say inbox"). The watch loop ENDS a turn on the first line it
        reads out of that inbox, so a refine landing there while a converse turn is in
        flight would be spoken as that turn's answer and the real one would be dropped at
        the next `begin()`. The plan's intent is that a refine is spoken only when he is
        there to hear it; this does that without the hazard.

        REFUSED WHILE A TURN IS LIVE, for the same reason. A refine is worth a sentence
        and never worth talking over an answer he asked for; the card carries whatever it
        said, which is what makes dropping it safe.
        """
        line = " ".join(str(text or "").split())
        if not line:
            return False
        turn = self.turn
        if turn is not None and turn.phase not in ("done", "held", "abandoned", "failed"):
            return False
        if not self._live() or not self._attending():
            # NOBODY ASKED FOR THIS LINE, so it is said only to a page he can see (D-2,
            # c-438); an open socket on a phone in his pocket is not him listening.
            return False
        self.bus.set_narration(line)
        # NO TURN OF ITS OWN, so it speaks with the last turn's engine: a refine arriving
        # a minute after he chose Kokoro should not come back in Google's voice. Nothing
        # is remembered for this beyond the turn already on `self`.
        self.speak(line, self.generation,
                   speech.Spoken(engine=getattr(turn, "engine", "") if turn else ""))
        self._log(turn or Turn(self.generation, ""), "refine-said", line=line)
        return True

    # -- ending quietly ----------------------------------------------------- #

    def quiet(self, said: str, heard=None, pcm: str = "", engine: str = "",
              turn_id: str = "", why: str = "not addressed") -> Turn:
        """A turn that ends with NO HARBOR TURN SPENT and the transcript line kept.

        V10's `addressed: no`: he was talking to someone else in the room, and an open
        microphone heard it. The utterance is a real turn, because it really happened and
        the record of it is the evidence the shadow log is read against; what it is not
        is a question, so nothing is asked and nothing is said back.

        IT IS THE SAME SHAPE AS `capture` AND `answer`, deliberately: it begins a turn,
        takes the generation (so anything still in flight is already stale), writes the
        transcript line, and finishes. The difference is the middle, which is empty.

        AND NOTHING IS SPOKEN, not even an acknowledgement. Saying "I will let that one
        pass" out loud, in the room, to a man who is talking to somebody else, would be
        exactly the interruption the verdict exists to avoid. The page shows the line;
        that is the whole of the feedback.

        WHICH PHRASE ENDED A CONVERSATION COMES THROUGH `why` for the same reason. "that
        is all" is a turn he really took and it belongs in the transcript, and it is not
        a question either.
        """
        turn = self.begin(said, pcm, turn_id)
        turn.engine = engine
        turn.tier = QUIET
        turn.phase = "quiet"
        repairs = [{"heard": a, "readAs": b} for a, b in (heard or [])]
        if repairs:
            self._log(turn, "said", repairs=repairs, quiet=why)
        else:
            self._log(turn, "said", quiet=why)
        turn.answer = ""
        turn.provenance = why
        turn.answered_at = time.time()
        turn.phase = "done"
        turn.spoken = False
        self.bus.set_loading(False)
        self.bus.set_state("idle")
        self.bus.set_turn(turn.as_json())
        self.history.append(turn)
        del self.history[:-config.TRANSCRIPT_KEEP]
        self._log(turn, "quiet", spoken=False, reason=why)
        self._over(turn)
        return turn

    # -- answering --------------------------------------------------------- #

    def answer(self, said: str, heard=None, pcm: str = "", engine: str = "",
               turn_id: str = "", route: str = "", typed: bool = False) -> Turn:
        """The whole of a converse turn: the one instant answer, or Harbor, then speak it.

        TWO STEPS, AND THAT IS THE WHOLE CASCADE (decision D4). If the WHOLE utterance is
        the one question code answers, it is answered here from the board, with no model
        and no turn lock. Everything else is one headless turn in the voice conversation,
        which is what "never confidently wrong" costs and buys.

        `heard` is what hearing.repair changed, if anything. It is logged rather than
        merely broadcast, because that table's whole safety argument is that its mistakes
        are visible, and a broadcast nothing reads is not visibility. Caught by review,
        2026-09-04.
        """
        turn = self.begin(said, pcm, turn_id)
        turn.engine = engine
        turn.typed = bool(typed)
        # RECORDED, NOT ACTED ON. Section 6 of findings.md: until now nothing recorded
        # whether he was still on the line, so no turn in the log could be checked
        # after the fact. This is that record for the START of the turn; the LATE
        # answer path checks presence live, at the moment it actually matters.
        try:
            turn.clients_at_start = int(self.clients_fn())
        except Exception:                                              # noqa: BLE001
            turn.clients_at_start = 0
        # `readAs`, not `read as`. The websocket message and the transcript line are the
        # same record read by two audiences, and they were spelled differently for one
        # commit: a key with a space in it is also awkward for anything that reads the
        # transcript back. camelCase matches routeSeconds and ageSeconds next door.
        repairs = [{"heard": a, "readAs": b} for a, b in (heard or [])]
        # WHOSE TURN IT IS, DECIDED BEFORE THE FIRST RECORD (lane H, H3). A turn said to a
        # connected house wrote its `said` record as Harbor's, because the tier moved only
        # in `_ask_house`, one record later; `keel voice latency` then had two labels for
        # one turn. The pin is read once here and the branch below uses the same answer.
        pinned = self.pinned()
        if pinned:
            turn.tier = HOUSE
        extra = {"typed": True} if turn.typed else {}
        if repairs:                      # reads the same document or they disagree
            self._log(turn, "said", repairs=repairs, clients=turn.clients_at_start, **extra)
        else:
            self._log(turn, "said", clients=turn.clients_at_start, **extra)

        turn.phase = "routing"
        self.bus.set_state("thinking")
        self.bus.set_turn(turn.as_json())

        # PINNED FIRST, AND BEFORE THE INSTANT ANSWER'S ROUTE IS READ. While he is
        # connected to a card, a talk turn is that house's: nothing else may take the
        # sentence off it (V4). The two conversation words and the connect phrases are
        # matched by the gateway before this, so what arrives here is a question.
        if pinned:
            return self._ask_house(turn)
        answered = self._instant(turn, route)
        if answered is not None:
            return answered
        return self._ask_harbor(turn)

    def _ask_house(self, turn: Turn) -> Turn:
        """One turn into the card's own house, through `keel converse` (V4, V6, V5).

        IT IS A WATCHED TURN NOW, AND IT USED TO BE A SILENT BLOCK. `connected.ask` waits
        on the house's own model turn, which is about seven seconds for a question and a
        minute or more when it edits something; until V5 that wait sat inside this method
        with nothing polling anything, so the filler, the real narration, the give-up clock
        and the abandon were all idle through the longest turns the gateway takes.

        So the verb is moved onto a worker thread that writes the answer into the SAY
        inbox, stamped with this turn's id, exactly as `harbormsg`'s Harbor worker already
        does, and this hands off to `_watch` exactly as `_ask_harbor` does. Everything that
        machinery knows how to do then works on a connected turn without a second copy of
        it: that is the whole of "it needs no new plumbing".

        THE NARRATION COMES BACK DOWN THE SAME CALL. `connected.ask` is given this turn's
        id, which tells `keel converse` to stream the house's real activity into the
        progress inbox `_watch` is already claiming (V5).

        A REFUSAL IS AN ANSWER, and it goes through the same inbox as one: the verb says
        out loud why it could not take the turn (the house is building, the machine it runs
        on is short of memory or away), and that sentence is spoken and the turn ends. What the verb sends back BESIDE the sentence (the hold's new expiry, an
        `unpin`) is stashed on the turn for `_watch` to act on when it finishes, because
        the worker must not touch the pin from under the thread that is speaking.

        AND A REFUSAL IS HARBOR'S, WHICH IS THE WHOLE RULE ABOUT WHO SPEAKS (V8). The voice
        follows whose answer it is: what the house said comes back in the house's voice, and
        everything the gateway says ABOUT a house comes back in Harbor's, because the house
        did not say it. `turn.speaker` is therefore set from the RESULT, in `_house_landed`,
        and never from the fact that a pin exists: every refusal path (mid-work, no house,
        the other machine away, short of memory, a relaunch that failed, a hold that went) is
        Harbor's without any of them having to remember to say so. Everything this method
        says BEFORE the answer lands is Harbor's for free, because a turn starts as Harbor's
        and only the answer moves it: the filler that covers the wait, every progress line
        V5 narrates, the give-up line. That ordering is the mechanism, not a coincidence.
        """
        card = self.pinned()
        turn.tier = HOUSE
        turn.phase = "delivering"
        turn.verb = CONNECTED_ROUTE
        turn.card = card
        self.bus.set_loading(True)
        self.bus.set_turn(turn.as_json())
        self._log(turn, "connected", card=card)
        # THE WAIT IS COVERED THE WAY A HARBOR TURN'S IS (2026-09-21), and nothing is said
        # at the top of the turn any more. V5's opener ("Heard you, passing that to the
        # house now") was spoken here within a second of release, as a rendered clip,
        # because connecting meant stopping a process and starting a `claude`. V12 opened
        # the conversation at the connect, so the first spoken part of the answer lands in
        # about three seconds and he is already inside the house: the line was wrong about
        # where he was and it talked over a wait that was usually already over.
        #
        # SO THE FILLER IS STARTED THE WAY `_ask_harbor` STARTS IT, on a thread, while the
        # verb is being handed off, and `_watch` speaks it ONLY if the wait actually goes
        # quiet for `config.PROGRESS_SILENCE_AT`. There is no second filler mechanism here:
        # it is the same corpus, the same picker, the same `Result`, and the same silence
        # gate a progress line waits behind.
        opener: list = []
        threading.Thread(
            target=lambda: opener.append(self.filler.line(turn.said, self.snapshot.doc)),
            name="voice-filler", daemon=True).start()

        def run():
            """The verb, off the watching thread. It always writes exactly one say line."""
            try:
                result = connected.ask(card, turn.said, turn=turn.id,
                                       progress=str(self.progress_inbox.dir))
            except Exception as exc:                                    # noqa: BLE001
                result = {"ok": False,
                          "say": connected.BROKE.format(why=exc.__class__.__name__)}
            turn.house = result
            # THIS DISPATCHER'S OWN SAY INBOX, never the module's: it is injected, and the
            # loop that is about to claim this line is reading the injected one. The
            # boards ride on the record exactly as Harbor's do (VP-8).
            self.inbox.write(
                result.get("say") or connected.BROKE.format(why="it said nothing"),
                turn=turn.id, boards=self._house_boards(turn, card, result))

        threading.Thread(target=run, name="voice-house", daemon=True).start()
        turn.phase = "waiting"
        self.bus.set_turn(turn.as_json())
        self._watch(turn, opener=opener)
        return turn

    def _house_boards(self, turn: Turn, card: str, result: dict) -> list[str]:
        """The boards the house drew during this turn, as the deck's board list has them.

        WHY THE DECK IS ASKED (VP-8). A house draws with `keel board push --card` from its
        own shell, into the deck's store; nothing of that passes through here, so unlike
        Harbor's drawings (`drawing.note_drawn`) the gateway holds no ids. The list's rows
        whose card is this one and whose update time is at or after the turn began are
        what this turn drew. A refusal drew nothing, so it is not asked. A deck that fails
        or is slow costs the receipt and one transcript line, never the turn: the wait is
        `drawing.HOUSE_LIST_TIMEOUT` at most.
        """
        if not result.get("ok"):
            return []
        try:
            return drawing.house_drew(card, turn.started)
        except Exception as exc:                                        # noqa: BLE001
            self._log(turn, "house-boards-failed", card=card,
                      error=f"{exc.__class__.__name__}: {str(exc)[:200]}")
            return []

    def _house_landed(self, turn: Turn) -> None:
        """What the verb sent back beside the sentence, acted on once the answer is in.

        Run from the watching thread at the moment the answer is claimed, never from the
        worker: the pin is read by the socket handler and by the next turn, and moving it
        from a thread that is about to be thrown away is how two turns disagree about which
        card they are in.
        """
        result = turn.house or {}
        card = turn.card or self.pinned()
        if result.get("held_until"):
            # THE TITLE AND THE SPACE ARE CARRIED OVER, not re-fetched and not dropped. A
            # connected turn extends the hold, so this runs on EVERY turn of a
            # conversation, and the verb's answer here carries neither: `--connect` is what
            # reads them off the board, once. Dropping the space would take the house's
            # colour out of the header at his first question (V8) and dropping the title
            # would empty what the header reads under the card id.
            self.pin_to(card, self.hold_seconds(result["held_until"]),
                        (self.pin or {}).get("title", ""),
                        (self.pin or {}).get("space", ""))
        # WHO SPEAKS THE ANSWER IS DECIDED HERE, ON THIS LINE, AND NOWHERE ELSE (V8). It
        # travels on the turn and `_say` hands it to the chain. It belongs wherever the
        # RESULT is first in hand, which is why it moved here with the result when V5 made
        # the verb a worker: deciding it from `self.pinned()` instead would make every
        # refusal speak in the house's voice, which is the one thing the rule exists to
        # prevent. And it is set BEFORE `_house_answer` speaks, which is the ordering that
        # makes the answer the house's and everything said while waiting for it Harbor's.
        turn.speaker = (config.SPEAKER_HOUSE if result.get("ok")
                        else config.SPEAKER_HARBOR)
        # THE HOUSE WAS ASKED TO LEAVE AND SAID GOODBYE (2026-09-21). Recorded here, beside
        # the hold, and acted on only after the goodbye has been SPOKEN (`_take_leave`): a
        # release he cannot hear would take him out of a house with nothing to say it
        # happened, which is the same rule the connect directive follows in the other
        # direction. A refusal can never carry one, because the directive is read off an
        # answer and a refusal is the gateway's own sentence.
        if result.get("leave") and result.get("ok"):
            turn.leave = True
            self._log(turn, "leave-directive", card=card)
        # A DRAWING THAT DID NOT LAND (C1). `keel converse` reports the push beside the
        # sentence; the card already has the note, and the transcript gets the record.
        drawn = result.get("board") or {}
        if drawn.get("state") in ("partial", "refused"):
            self._log(turn, "draw-failed", card=card, board=drawn)
        if result.get("unpin"):
            # THE HOLD WENT WHILE HE WAS TALKING: he stopped the house from the deck, or
            # answered its gate. The verb is the only one that can see that, so the pin is
            # dropped here and the sentence it sent back is what is spoken.
            self._log(turn, "connected-unpinned", card=card, why=result.get("say"))
            self.unpin()
        elif not result.get("ok"):
            self._log(turn, "connected-refused", card=card, why=result.get("say"))

    def _instant(self, turn: Turn, route: str = "") -> Turn | None:
        """A reply read off the board, or None meaning "this is Harbor's".

        `route` IS V10'S VERDICT AND IT IS EMPTY UNLESS JEV DECIDED IT (c-314). The
        gateway passes it only when `Ruling.by("route")` says `jev`, which cannot happen
        while the key is `off` or `shadow`, so with the rule judge this reads exactly as
        it did before: the one question in the table is answered here and everything else
        is Harbor's.

        WHAT A `board_read` VERDICT CANNOT DO IS INVENT A RENDERER. `route` says a fixed
        board read was asked for; it does not say WHICH, because the menu Jev is asked
        with is four items wide (talk, capture, board_read, other). Only `needs-you` has
        a renderer today, so a board read this file cannot render falls to Harbor, and
        the fall is logged: answering "what is building" with the contents of the queue
        would be the confidently wrong answer this whole package is arranged to refuse.

        IT READS THE BOARD ITSELF, freshly, and it never takes `harbormsg._TURN_LOCK`:
        there is no conversation involved, so a converse turn already in flight is not
        delayed by this one and this one is not queued behind it.

        ANY TROUBLE IS A FALL TO HARBOR. `kb` refusing, the fold raising, an empty
        sentence: the failure direction is the same one the whole package has, and the
        reason goes on the record so a table that stops working is visible as a cause
        rather than as an absence.
        """
        which = verbs.board_read(turn.said)
        if route == INSTANT_ROUTE and not which:
            self._log(turn, "board-read-unrendered", route=route)
            return None
        if not which:
            return None
        if route and route != INSTANT_ROUTE:
            # THE VERDICT DECIDED OTHERWISE, and it decided after reading the whole
            # utterance. A route that says `talk` about something the table matches is
            # Jev disagreeing with the table, and when a judge is `on` its answer is the
            # one that decides.
            return None
        try:
            sentence = verbs.waiting_answer()
        except Exception as exc:                                        # noqa: BLE001
            self._log(turn, "instant-failed",
                      error=f"{exc.__class__.__name__}: {exc}")
            return None
        turn.verb = "queue"
        return self._finish(turn, sentence, INSTANT, f"board, {turn.elapsed:.1f}s")

    # -- the Harbor tier --------------------------------------------------- #

    def _digest(self) -> tuple[str, float, str]:
        """The deck digest for the framing, how old it is, and which record it came from.

        NEVER RAISES: a turn that cannot be given a digest is a slower turn, not a failed
        one. THE SOURCE RIDES WITH IT ("deck" or "board") because a digest built from the
        board alone has no provider rows and no segments, and a turn told it holds the
        deck would answer "there are no reviews" about a screen full of them.
        """
        doc = self.snapshot.doc
        try:
            return (index.as_json(doc), float(self.snapshot.age),
                    str(doc.get("source") or "board"))
        except Exception as exc:                                        # noqa: BLE001
            self._log(self.turn or Turn(self.generation, ""), "digest-failed",
                      error=f"{exc.__class__.__name__}: {exc}")
            return "", 0.0, "board"

    def _ask_harbor(self, turn: Turn) -> Turn:
        turn.tier = HARBOR
        # ITS PARTS ARE SPOKEN AS THEY ARRIVE only on the kept-alive path (R2); with the
        # flag off nothing below reads this and the turn is exactly what it was.
        turn.streams = config.HARBOR_KEPT_ALIVE
        turn.phase = "delivering"
        self.bus.set_loading(True)
        self.bus.set_turn(turn.as_json())

        # THE FILLER IS WRITTEN WHILE THE LINE IS BEING TYPED, which is why it costs
        # nothing. Delivery into the pane was measured at 1.65 to 3.16 s and the filler's
        # timeout is 2.0 s, so the line is usually ready before there is anywhere to
        # speak it, and when it is not the written table speaks instead.
        # It is started BEFORE delivery and read AFTER, and if delivery fails it is
        # thrown away unspoken: a filler is only ever said about a wait that is real.
        pending: list = []
        writer = threading.Thread(
            target=lambda: pending.append(self.filler.line(turn.said, self.snapshot.doc)),
            name="voice-filler", daemon=True)
        writer.start()

        # THE DIGEST RIDES ON THE TURN, which is what removes the two `kb` reads that
        # were the first two tool calls of every turn (<install>/history/docs/voice-two-modes.md, 1.1
        # item 2). It is the warm snapshot through index.as_json: names, ids, states and
        # counts, never a body, and never a value code would read to answer. A snapshot
        # that cannot be indexed sends no digest rather than failing the turn, and the
        # framing then carries no claim about one.
        digest, age, source = self._digest()
        # THIS TURN'S CONNECT KEY (c-419), minted here and nowhere else: it goes out in the
        # framing and comes back in the directive, and only a directive carrying it may pin.
        # Minted per turn rather than per gateway so a directive quoted out of an earlier
        # answer is stale by construction.
        turn.connect_key = verbs.connect_key()
        delivered, what = self.deliver(turn.said, "", digest=digest, age=age,
                                       source=source, turn_id=turn.id,
                                       connect_key=turn.connect_key)
        if not delivered and what == harbormsg.BUSY:
            # NOT A FAILURE, AND IT MUST NOT SOUND LIKE ONE. Nothing went wrong: he is
            # ahead of the conversation. The fixed line is spoken and the turn ends here,
            # with no model turn behind it to wait for.
            self._log(turn, "busy")
            return self._finish(turn, NARRATION["busy"], HARBOR, "one at a time")
        if not delivered:
            # SPOKEN, not swallowed, and spoken ONCE. A failure he cannot hear is a turn
            # that vanished; a failure he hears twice is a bug he can hear.
            self._narrate(turn, "undelivered")
            turn.error = what
            turn.phase = "failed"
            turn.answered_at = time.time()
            self.bus.set_loading(False)
            self.bus.set_turn(turn.as_json())
            # WITH THE REASON ON IT. The narration table has one sentence for every way
            # this can fail, deliberately, because he does not want to hear a stack
            # trace. The transcript is the other audience and it was getting the same
            # sentence: three `undelivered` records in a row saying nothing about which
            # of a dozen causes it was. The delivery side writes the full record to
            # state/logs/voice.log; this is the line that lets the transcript agree with it.
            self._log(turn, "undelivered", error=what)
            self._rest_typed(turn)
            return turn

        # WHICH RECORD THE TURN WAS ANSWERED OUT OF, written down (decision V16). A turn
        # holding the board rather than the deck cannot see the provider rows, and the
        # difference is invisible in the answer itself: it reads as a flat "there are no
        # reviews". One line per delivered turn is what makes it visible afterwards,
        # which is the only way "voice said something odd last night" is ever diagnosed.
        self._log(turn, "digest", source=source, ageSeconds=round(age, 1),
                  bytes=len(digest))

        # However long is left of the filler's budget, and no longer. A filler that
        # arrives after the wait it was filling lands on top of Harbor's real answer.
        writer.join(timeout=config.FILLER_TIMEOUT)
        said_line = pending[0] if pending else None
        self._narrate(turn, "delivered",
                      text=said_line.text if said_line else None)
        if said_line is not None:
            self._log(turn, "filler", **said_line.as_json())
        turn.phase = "waiting"
        self.bus.set_turn(turn.as_json())
        self._watch(turn)
        return turn

    def _watch(self, turn: Turn, opener: list | None = None) -> None:
        """Wait for Harbor to say something, narrating real changes while it thinks.

        `opener` IS A CONNECTED TURN'S FILLER LINE, still being written when this is
        called (`_ask_house` starts the writer and hands the list over rather than waiting
        on it, because waiting here would hold the first part of the answer in its inbox
        for as long as the filler took). It is spoken at most once, and only if the wait
        actually goes quiet; a Harbor turn passes none, because its filler is spoken at the
        top of the turn where the delivery already cost it the same seconds.
        """
        # A ONE-ELEMENT LIST rather than an attribute on self, so two overlapping turns
        # cannot read each other's answer. Same reason the refusal reason is returned
        # rather than stashed: this dispatcher is one-turn-at-a-time by design, and that
        # is not a reason to put per-turn state where a second turn could reach it.
        # THE "IS HARBOR STOPPED" QUESTION IS GONE WITH THE PANE. `_ask_pane_state` asked
        # harbor-session-state whether Harbor's tmux pane was blocked, twelve seconds in,
        # and narrated "I've stopped, and I'm waiting on something" when it was. A
        # headless turn has no pane and no such state: it is running or it is finished,
        # and a turn that fails writes its own spoken line into the say inbox from
        # harbormsg's worker thread, which this loop is already watching. So the
        # observation, the thread it ran on and the narration it fed are all removed
        # rather than left asking a question nothing can answer.

        def run():
            before = _observable(self.snapshot.doc)
            said_elapsed = said_giveup = False
            # WHAT HAS ALREADY BEEN SAID DURING THIS WAIT, so a second line is a
            # different line rather than the same one twice. Per turn, discarded with it.
            already = {line for line in turn.narration}
            repeat_every = max(0.0, config.FILLER_REPEAT_EVERY)
            repeats_left = max(0, config.FILLER_REPEAT_LIMIT)
            # HARBOR'S OWN PROGRESS HAS ITS OWN BUDGET, separate from the canned
            # filler's above. They used to share one counter, so a wait that had
            # already spent it on the canned hold line would silence real progress for
            # the rest of the turn, with nothing recorded: `progress_inbox.claim()` was
            # never even called once the shared counter hit zero, so a line written
            # after that sat in the directory until the next turn's `begin()` deleted
            # it unlogged. Raised by review, 2026-09-07.
            progress_repeats_left = max(0, config.PROGRESS_REPEAT_LIMIT)
            # THE LAST ACTION SPOKEN IN THIS WAIT (V5), so the next one can be refused for
            # being the same. Per turn and discarded with it, like `already` above.
            last_action = ""
            # WHEN THE NEWEST PART OF THE ANSWER WAS WRITTEN, by the clock that wrote it.
            # It is what tells a narration line that arrived BEFORE the answer started
            # (stale, and never spoken over it) from one that arrived after (the house
            # went back to work, so what it said was a preamble).
            last_part_at = 0.0
            # THE NARRATION LINE THAT HAS BEEN CLAIMED BUT NOT YET SPOKEN (V12). A
            # connected turn claims the inbox on every pass now, so the wait between
            # claiming a line and the silence gate opening is held here rather than in the
            # directory. One slot, because only the freshest line is ever worth saying.
            waiting = None
            # THE LINE THAT OPENS A CONNECTED WAIT, while it is still being written. It is
            # bound to a local of this loop rather than used through the parameter, the way
            # every other per-turn slot in here is, and it is emptied the moment it is
            # spoken or refused so it can only ever be said once.
            opening_filler = opener
            # HOW MANY `narrate` CALLS THIS TURN HAS LEFT. See NARRATE_SHADOW_CAP: one
            # global shadow slot, shared with the judge that has a turn waiting on it.
            narrate_left = NARRATE_SHADOW_CAP
            next_line = time.time() + repeat_every if repeat_every else 0.0
            while turn.generation == self.generation or turn.held:
                # ONE PASS AT A TIME UNDER `pass_gate` (c-418): a test holding it can put two
                # files in the inboxes and know the next pass sees both.
                with self.pass_gate:
                    # HE MOVED ON MID-ANSWER, LATCHED BEFORE ANYTHING IS CLAIMED (2026-09-24).
                    # The latch used to sit below the `say` claim, so an answer that landed
                    # within one tick of his barge-in was claimed first, compared as a
                    # REMAINDER of parts he had cut off, and he heard its tail instead of the
                    # whole of it. Under load the tick stretches and that window with it:
                    # three barge-in checks failed on the box's first run after a restart.
                    if turn.spoke_parts and turn.generation != self.generation:
                        turn.parts_cut = True
                    for line in self.inbox.claim(turn.id):
                        text = str(line.get("text") or "").strip()
                        if not text:
                            continue
                        # WHICH BOARDS THE ANSWER DREW (VP-5), for the page's receipt.
                        turn.boards = [str(b) for b in line.get("boards") or [] if b]
                        # THE CONNECT DIRECTIVE COMES OFF HERE (c-419), BEFORE EVERY BRANCH
                        # BELOW, because the token must never be spoken, filed, shown on the
                        # page or written to the card whichever way this turn ends. Whether it
                        # may actually PIN is a separate question and it is asked once, in the
                        # one branch that speaks (`_finish`, below): an answer he cannot hear
                        # must not move him to a house he was never told about.
                        #
                        # A HOUSE'S ANSWER CAN NEVER CARRY ONE: `connect_key` is only ever set
                        # on a Harbor turn, and an empty key matches nothing. The way back is
                        # the gateway's (V8), and so is the way in.
                        text, asked = verbs.connect_directive(text, turn.connect_key)
                        if asked:
                            turn.connect = asked
                            self._log(turn, "connect-directive", card=asked)
                            # THE TRUTH FOR `preturn.card` (c-552): the card the talker
                            # picked, whether or not the pin then succeeds.
                            try:
                                judgesmod.outcome(turn.id, "connected", card=asked)
                            except Exception:                           # noqa: BLE001
                                pass
                        # AND AN ANSWER TO ONE OF BOSUN'S ASKS (c-523), off by the same rules.
                        text, picked = verbs.answer_directive(text, turn.connect_key)
                        if picked:
                            turn.picked = picked
                            self._log(turn, "answer-directive", ask=picked[0], letter=picked[1])
                        if not text:
                            # A DIRECTIVE AND NOTHING ELSE. There is nothing to say, so the
                            # turn would end in silence; the connect's own lines are the
                            # answer he hears, and the framing asks for a sentence anyway.
                            text = NARRATION["connect_bare"]
                        if turn.generation != self.generation and turn.tier != HOUSE:
                            # HE ALREADY MOVED ON. The answer is kept and offered rather than
                            # spoken over the turn he is having now. This is the second
                            # barge-in screen: "Harbor answered while you were talking".
                            turn.answer = text
                            turn.held = True
                            turn.phase = "held"
                            turn.answered_at = time.time()
                            self._drop_connect(turn, "the user had already moved on")
                            self._log(turn, "held")
                            return
                        # A CONNECTED TURN THAT HE MOVED ON FROM FALLS THROUGH TO
                        # `_house_answer` (V5). Harbor's answer to a superseded question is
                        # usually stale, because he re-asked it; a house's is a minute of its
                        # own work on a question he has not re-asked and could not re-ask
                        # without waiting all over again. So it is held to be SPOKEN once he
                        # is quiet, rather than held to be read.
                        if turn.tier == HOUSE:
                            # V5: A CONNECTED TURN HOLDS ITS ANSWER, and this is the one place
                            # the give-up path differs from an ordinary turn's. It never files
                            # a card, because `converse.record` has already written this
                            # exchange onto the card he is talking to; a second one would be a
                            # duplicate record filed against a different card. And it never
                            # interrupts him: if he is mid-sentence when it lands, it waits.
                            self._house_landed(turn)
                            self._house_answer(turn, text)
                            # AND THEN, IF THE HOUSE SAID GOODBYE, THE LEAVING ITSELF. After
                            # the answer, never during it: the release speaks a line of its own
                            # and that line belongs after his goodbye, not on top of it. This
                            # is the connect directive's ordering, the other way round.
                            self._take_leave(turn)
                            return
                        if turn.gave_up:
                            # THE PROMISE IS BINDING, AND IT NEVER REACHES AUDIO AGAIN. "I'll
                            # answer in text instead" was said out loud at the give-up mark,
                            # so whatever arrives now must not be spoken, however live he
                            # turns out to be (c-221). c-229: it also no longer shows on THIS
                            # page, because that turned out not to be where he wanted it read
                            # either -- it is staged as a queue notice instead, see
                            # `_finish_silent`'s own `queue=True` branch.
                            self._drop_connect(turn, "the answer is text, not audio")
                            self._finish_silent(turn, text, HARBOR,
                                                f"Harbor, {turn.elapsed:.0f}s (text)",
                                                "gave up, so the answer is text",
                                                queue=True, redact=not turn.typed)
                            return
                        if not self._live():
                            # NOBODY IS THERE TO HEAR IT. findings.md section 5: zero
                            # barge-ins across 27 turns, and he has said plainly he leaves
                            # after a few lines. Speaking into that is wasted audio; the
                            # turn record still carries the real text either way.
                            self._drop_connect(turn, "nobody is there to hear the switch")
                            self._finish_silent(turn, text, HARBOR,
                                                f"Harbor, {turn.elapsed:.0f}s (text)",
                                                "not live", queue=True, redact=False)
                            return
                        if turn.streams:
                            # WHAT HE HAS ALREADY HEARD IS NOT SAID AGAIN (R2, V13-G7):
                            # the parts are compared with the answer, as a house's are.
                            if self._harbor_streamed(turn, text):
                                self._take_connect(turn)
                                return
                            left = self._harbor_left(turn, text)
                            self._finish(turn, text, HARBOR,
                                         f"Harbor, {turn.elapsed:.0f}s"
                                         + (" (the rest)" if left != text else ""), say=left)
                            self._take_connect(turn)
                            return
                        self._finish(turn, text, HARBOR,
                                     f"Harbor, {turn.elapsed:.0f}s")
                        # THE ANSWER WAS SPOKEN, SO THE SWITCH CAN BE HEARD. After the turn
                        # is over, never during it: the connect speaks four lines of its own
                        # and the first of them belongs after Harbor's sentence, not on top
                        # of it.
                        self._take_connect(turn)
                        return
                    # THE PRE-WORK LINE. A separate inbox from the one above, so claiming it
                    # can never end the turn: this is exactly the mistake review round 1
                    # found in the version that asked Harbor to call `say` twice. Checked
                    # every pass rather than gated on silence, because the whole point is
                    # that it is heard as soon as Harbor has said it, not after a wait.
                    if not turn.opened and turn.generation == self.generation:
                        opening = self.open_inbox.claim()
                        if opening:
                            turn.opened = True
                            last = opening[-1] or {}
                            # WHAT HARBOR SAID TO EXPECT (c-229), READ REGARDLESS OF LIVENESS:
                            # this is about the give-up TIMER, not about whether to speak, so
                            # it is captured even on the "not live" branch below, unlike the
                            # opener text itself.
                            o_eta = last.get("eta")
                            if o_eta is not None:
                                try:
                                    turn.eta = float(o_eta)
                                except (TypeError, ValueError):
                                    turn.eta = None
                            o_text = str(last.get("text") or "").strip()
                            if o_text and self._live():
                                self._narrate(turn, "delivered", text=o_text)
                            elif o_text:
                                self._log(turn, "opening-refused", why="not live",
                                          text=o_text)
                    now = _observable(self.snapshot.doc)
                    for kind, detail in _changes(before, now):
                        self._narrate(turn, kind, **detail)
                    before = now
                    if not said_elapsed and turn.elapsed >= config.NARRATE_ELAPSED_AT:
                        # NOTHING IS SAID HERE ANY MORE, AND THAT IS THE POINT. The old line
                        # spoke the elapsed seconds unconditionally; the one that replaced it
                        # asked whether Harbor's pane was blocked and spoke only if it was,
                        # which was a fact about his question rather than about the clock.
                        # There is no pane to ask now (see the note above `run`), and there is
                        # no headless equivalent: inventing one would be the narration
                        # speaking about the clock again, by another name. The mark is still
                        # passed, once, so the transcript records that the wait reached it.
                        said_elapsed = True
                        self._log(turn, "elapsed-mark",
                                  at=round(turn.elapsed, 1))
                    # HARBOR'S OWN PROGRESS, GIVEN PRIORITY OVER THE CANNED REPEAT. Checked
                    # first and gated on SILENCE rather than on a fixed schedule: it fires
                    # the moment the wait would otherwise go quiet for PROGRESS_SILENCE_AT
                    # (about 4 s), not on the filler's own slower cadence. A turn that
                    # finishes inside that window never reaches this line at all, which is
                    # the whole of "never chatter through a 2 second turn": there is no
                    # timer to disarm, only a silence that has to actually happen.
                    #
                    # ONLY WHILE HE IS STILL WAITING ON THIS TURN, and never once he has
                    # been told to expect text instead: speaking about a wait he was just
                    # promised would land in text is the same contradiction the giveup
                    # fix below exists to close.
                    #
                    # THE INBOX IS ALWAYS CLAIMED once the silence gate opens, whether or
                    # not there is anything left to say it with. `said_giveup` and a spent
                    # `progress_repeats_left` used to gate the claim itself, which meant a
                    # line arriving after either was never read back and never logged: it
                    # sat in the directory until the next turn's `begin()` deleted it with
                    # no record at all. Now every reason not to speak it is a logged
                    # refusal, the same way the shape guard's refusal already was.
                    # A CONNECTED TURN CLAIMS THE INBOX EVERY PASS (V12), because the same
                    # directory now also carries the ANSWER, sentence by sentence, and an
                    # answer must not wait four seconds for a silence gate that exists to
                    # protect him from chatter. Nothing else changes channel: a Harbor turn
                    # claims exactly when it always did, and a narration line still waits for
                    # the gate, the budget and the shape guard wherever it came from.
                    # HE MOVED ON MID-ANSWER (V12). The streaming stops with the generation,
                    # because `_say` would drop the audio anyway; what matters is that the
                    # turn REMEMBERS it was cut, so the answer that lands afterwards is spoken
                    # whole once he is quiet. Half an answer heard is not an answer heard.
                    if turn.spoke_parts and turn.generation != self.generation:
                        turn.parts_cut = True
                    claim_now = (turn.generation == self.generation
                                 and (turn.tier == HOUSE or turn.streams
                                      or time.time() - turn.last_spoken_at
                                      >= config.PROGRESS_SILENCE_AT))
                    if claim_now:
                        for claimed in self.progress_inbox.claim(turn.id):
                            if not (claimed or {}).get("part"):
                                # THE FRESHEST ONE, NOT A QUEUE. A progress line is a snapshot
                                # of where things stand, not a backlog of things to say; if he
                                # called it three times while nothing was listening, only the
                                # last of those three is still true. The one it replaces is
                                # refused on the record rather than dropped.
                                if waiting is not None:
                                    self._log(turn, "progress-refused",
                                              why="a newer line arrived first",
                                              text=str(waiting.get("text") or ""),
                                              action=str(waiting.get("action") or ""))
                                waiting = claimed
                                continue
                            # THE HOUSE'S OWN WORDS, ARRIVING (V12). Spoken at once, in the
                            # HOUSE's voice (V8), and they end this turn's narration: once the
                            # answer has started, a line about what the house is doing would
                            # be talked over the thing he actually asked for.
                            part_text = str((claimed or {}).get("text") or "").strip()
                            if not part_text or turn.parts_cut:
                                continue
                            last_part_at = max(last_part_at,
                                               float((claimed or {}).get("at") or 0.0))
                            if not self._house_part(turn, part_text):
                                turn.parts_cut = True
                        if (waiting is not None and turn.answering
                                and float(waiting.get("at") or 0.0) <= last_part_at):
                            # WRITTEN BEFORE THE ANSWER STARTED, and claimed after it: this
                            # line is about work the house had already finished when it began
                            # speaking, so saying it now would be narration over the answer.
                            # The two times are both `keel converse`'s own clock, written into
                            # the records by `keel/narration.py`, so they really are ordered.
                            self._log(turn, "progress-refused",
                                      why="the house is answering now",
                                      text=str(waiting.get("text") or ""),
                                      action=str(waiting.get("action") or ""))
                            waiting = None
                        elif waiting is not None and turn.answering:
                            # THE HOUSE SPOKE AND THEN WENT BACK TO WORK (V12, review round 2).
                            # Narration for a turn used to end at the first part, full stop,
                            # which silenced the whole of a long turn whenever the house opened
                            # with a line of its own ("Let me check that file.") before picking
                            # up a tool. An action arriving after a part says that text was a
                            # PREAMBLE and not the answer, so the narration reopens until the
                            # next part.
                            #
                            # AND THE PARTS SPOKEN SO FAR STOP COUNTING AS THE ANSWER. What
                            # decides whether the final answer is spoken again is whether the
                            # LAST message's parts were spoken; the preamble was already said
                            # out loud and is nothing to do with it.
                            turn.answering = False
                            if turn.spoke_parts:
                                self._log(turn, "answer-preamble",
                                          parts=len(turn.spoke_parts))
                                turn.spoke_parts = []
                    # THE CONNECTED TURN'S OPENING FILLER, AND IT IS SPOKEN ONLY INTO A REAL
                    # SILENCE (2026-09-21). This is where the V5 opener used to be said, at the
                    # top of `_ask_house`, unconditionally: with V12 the first part of the
                    # answer usually lands before the gate opens at all, and then nothing is
                    # said, which is the whole of "never chatter through a short turn". Every
                    # condition here is one the wait already uses somewhere: he has not moved
                    # on, the answer has not started (`answering`, `spoke_parts`), a real
                    # progress line is not waiting (Harbor's own activity is preferred over a
                    # canned line, exactly as it is below), and nothing has been spoken for
                    # `PROGRESS_SILENCE_AT`.
                    #
                    # A LINE THAT IS NOT WRITTEN YET BY THEN IS DROPPED rather than waited for,
                    # which is `_ask_harbor`'s rule too (`writer.join(FILLER_TIMEOUT)`, and the
                    # written table speaks instead): the filler's budget is two seconds and the
                    # gate is four, so a line that has not arrived is a line that missed the
                    # wait it was covering.
                    #
                    # AND IT IS NEVER CUT MID-WORD BY THE PART THAT FOLLOWS IT. The only thing
                    # that stops audio in flight is the generation counter, and that belongs to
                    # HIM: `_say` drops anything whose generation has moved, so bumping it for a
                    # part would drop the part's own audio too and read to the page as a
                    # barge-in. `_say` blocks for the length of the clip, so a part that lands
                    # under a filler is spoken the moment its words end, and the cost is bounded
                    # by one short rendered line.
                    if (opening_filler is not None and not turn.answering
                            and not turn.spoke_parts and waiting is None
                            and turn.generation == self.generation
                            and time.time() - turn.last_spoken_at
                            >= config.PROGRESS_SILENCE_AT):
                        first, opening_filler = (opening_filler[0] if opening_filler
                                                 else None), None
                        if first is not None and first.text:
                            already.add(first.text)
                            self._narrate(turn, "delivered", text=first.text)
                            self._log(turn, "filler", **first.as_json())
                            if repeat_every:
                                next_line = time.time() + repeat_every
                        else:
                            self._log(turn, "filler-refused",
                                      why="it was not written before the wait needed it")
                    if (waiting is not None and turn.generation == self.generation
                            and time.time() - turn.last_spoken_at
                            >= config.PROGRESS_SILENCE_AT):
                        rec, waiting = waiting, None
                        if rec:
                            p_text = str(rec.get("text") or "").strip()
                            # THE ACTION IS WHAT A HOUSE ACTIVITY LINE CARRIES (V5), and it is
                            # what the repeat rule and the `narrate` judge both speak in. A
                            # `bin/keel-voice progress` line has none, and neither the rule
                            # below nor the seat touches it: this slice narrates a house, it
                            # does not change the channel anyone else writes to.
                            action = str(rec.get("action") or "")
                            # EVERY REASON NOT TO SPEAK IT, WORKED OUT BEFORE ANYTHING IS
                            # SAID, because the `narrate` judge's rule verdict has to BE the
                            # decision this loop is about to make. Asking the judge inside one
                            # branch and not the others would log a rule that agreed with
                            # itself by construction, and the shadow log's agreement column
                            # would measure the copy instead of the decision (the same reason
                            # `rule_route` lives on this class).
                            if not p_text:
                                why = "nothing to say"
                            elif said_giveup:
                                why = "already promised text instead"
                            elif not progress_repeats_left:
                                why = "the progress budget for this turn is spent"
                            elif action and narration_repeat(last_action, action):
                                # V5: NEVER THE SAME PROGRESS LINE TWICE IN A ROW, and
                                # nothing when nothing changed. Compared by ACTION, never by
                                # the sentence: two reads render one string, so comparing
                                # strings would catch that pair by accident and miss the pair
                                # where a template is later reworded.
                                why = f"the same action twice in a row ({action})"
                            else:
                                why = filler.progress_guard(p_text, turn.said,
                                                            self.snapshot.doc)
                            if action:
                                asked = self._narrate_seat(turn, rec, not why, narrate_left)
                                narrate_left -= 1 if asked else 0
                            if why:
                                # NEVER SILENTLY DROPPED. A progress line that fails
                                # the shape guard is exactly the leak section 2's hard
                                # constraint exists to stop, so the refusal is on the
                                # record even though nothing is said.
                                if p_text:
                                    self._log(turn, "progress-refused", why=why,
                                              text=p_text, action=action)
                            else:
                                already.add(p_text)
                                last_action = action or last_action
                                self._narrate(turn, "delivered", text=p_text)
                                self._log(turn, "progress", text=p_text, action=action)
                                next_line = time.time() + repeat_every
                                progress_repeats_left -= 1
                    # THE WAIT SPEAKS AGAIN, and until 2026-09-04 this could not happen:
                    # config.FILLER_REPEAT_EVERY had existed since the filler shipped,
                    # documented as the value that held the decision, and NOTHING READ IT.
                    # Setting it did nothing, silently, which is worse than not having it.
                    #
                    # IT IS A `hold` LINE, NOT ANOTHER OPENER. "let me look into that" is
                    # right when his words land and wrong twenty seconds later, because it
                    # announces the start of something that started twenty seconds ago. The
                    # corpus writes the two stages separately for exactly this moment.
                    #
                    # AND ONLY WHILE HE IS STILL WAITING ON THIS TURN. A held turn is one he
                    # has moved on from: its answer is kept and offered rather than spoken,
                    # so speaking about its wait would be talking over the turn he is having
                    # now. `_say` would drop the audio on the generation check anyway; not
                    # generating it is the honest version of the same rule.
                    # AND IT STOPS, TWICE OVER, which the first version of this did not.
                    # It ran to TURN_MAX_SECONDS (600 s), so a ten minute wait would have
                    # heard about seventy-four lines, and it carried on talking straight
                    # through the ninety second line that says "I'm still on it, and I'll
                    # answer in text instead". Announcing that and then continuing to chat is
                    # the wait contradicting itself out loud, to a room he has probably left.
                    # Raised by review, 2026-09-04.
                    # AND NEVER OVER THE ANSWER ITSELF (2026-09-21). `turn.answering` is the
                    # latch that ends a turn's narration once the house has started speaking,
                    # and a canned hold line is narration like any other: it was only ever
                    # unreachable here because a connected turn rarely ran twenty seconds past
                    # its first part. Now that a connected wait is covered by this corpus, the
                    # rule has to be written down rather than relied on.
                    if (next_line and repeats_left and not said_giveup
                            and not turn.answering
                            and time.time() >= next_line
                            and turn.generation == self.generation):
                        next_line = time.time() + repeat_every
                        repeats_left -= 1
                        try:
                            more = self.filler.line(turn.said, self.snapshot.doc,
                                                    stage="hold", avoid=already)
                        except Exception as exc:                            # noqa: BLE001
                            # A FILLER MUST NEVER COST THE ANSWER. This loop is the only
                            # thing draining the say inbox, so an exception here would end
                            # the watch thread and Harbor's real answer would arrive to
                            # nothing. Recorded rather than swallowed, for the same reason
                            # every other guarded path in this file records.
                            self._log(turn, "filler-failed",
                                      error=f"{exc.__class__.__name__}: {exc}")
                            more = None
                        if more is not None and more.text:
                            already.add(more.text)
                            self._narrate(turn, "delivered", text=more.text)
                            self._log(turn, "filler", **more.as_json())
                    # A STREAMED HARBOR ANSWER THAT HAS STARTED IS NOT GIVEN UP ON (R2):
                    # he is hearing it, so "I'll answer in text" would be untrue.
                    if (not said_giveup and not (turn.streams and turn.spoke_parts)
                            and turn.elapsed >= _giveup_mark(turn)):
                        said_giveup = True
                        turn.gave_up = True
                        # V5: A CONNECTED TURN PROMISES THE ANSWER, NOT TEXT. It cannot
                        # promise text, because the text is already going to the card he is
                        # talking to, so what it promises is to come back when the house does.
                        if turn.tier == HOUSE:
                            kind = "giveup_house"
                        else:
                            kind = "giveup_eta" if turn.eta else "giveup"
                        self._narrate(turn, kind, speak=True)
                    if turn.elapsed >= config.TURN_MAX_SECONDS:
                        # ABANDONED MID TOOL-CALL, on a connected turn, IS SAID OUT LOUD ONCE
                        # (V5). An ordinary abandoned turn is silent because Harbor's answer
                        # may still arrive and be filed; a connected turn's `keel converse` has
                        # by now been killed with its process group and there is nothing left
                        # coming, so silence would leave him waiting on a turn that has ended.
                        # One line, and the card has the rest: the verb wrote his question, why
                        # the turn stopped, and how far it had got before it did
                        # (`converse.record_stopped`).
                        if turn.tier == HOUSE and not turn.spoken:
                            self._narrate(turn, "house_stopped", speak=self._live())
                        turn.phase = "abandoned"
                        self.bus.set_loading(False)
                        self.bus.set_turn(turn.as_json())
                        self._log(turn, "abandoned")
                        return
                time.sleep(0.4)

        self._watcher = threading.Thread(target=run, name="voice-watch", daemon=True)
        self._watcher.start()

    # -- the pin the model asked for (c-419) -------------------------------- #

    def _take_connect(self, turn: Turn) -> None:
        """Act on the directive this answer carried, once the answer has been spoken.

        THE LAST OF THE FIVE CONDITIONS IS ASKED HERE and the other four are asked
        earlier, each by construction rather than by a check: the key is only minted on a
        Harbor turn, only this turn's key matches, only the last line alone may pin, and
        only this branch is reached when the answer was actually spoken.

        NOT OVER A PIN HE ALREADY HAS. A Harbor answer cannot arrive while he is connected,
        because a pinned turn goes to the house; a LATE one from before the pin can, and
        taking the microphone away from the house he is now talking to on the strength of a
        question he asked two minutes ago is exactly the surprise the heard handoff exists
        to prevent.
        """
        self._take_answer(turn)
        card = turn.connect
        if not card:
            return
        turn.connect = ""
        pinned = self.pinned()
        if pinned:
            self._log(turn, "connect-dropped", card=card,
                      why=f"already connected to {pinned}")
            return
        self._log(turn, "connect-taking", card=card)
        try:
            self.connect_asked(card)
        except Exception as exc:                                        # noqa: BLE001
            # A CONNECT MAY NEVER COST THE TURN. The answer is already spoken and the
            # record is already written; what fails here is the switch, and it fails the
            # way every refusal does, with nothing pinned.
            self._log(turn, "connect-failed", card=card,
                      error=f"{exc.__class__.__name__}: {exc}")

    def _take_answer(self, turn: Turn) -> None:
        """His answer to one of Bosun's asks, once Harbor's answer saying it back was spoken
        (c-523). Handed to the page to record, with his own sentence as the words beside
        it, verbatim. A pick he did not hear is dropped (`_drop_connect`), never recorded."""
        picked = turn.picked
        if not picked:
            return
        turn.picked = None
        self._log(turn, "answer-taking", ask=picked[0], letter=picked[1])
        try:
            self.answer_asked(picked[0], picked[1], turn.said)
        except Exception as exc:                                        # noqa: BLE001
            self._log(turn, "answer-failed", ask=picked[0],
                      error=f"{exc.__class__.__name__}: {exc}")

    def _take_leave(self, turn: Turn) -> None:
        """End the conversation the house was asked to end, once its goodbye is spoken.

        THE SECOND NET, AND IT IS THE SAME ACT AS THE FIRST. `verbs.leave_intent` catches
        the leaving words in the gateway and never spends a turn; this catches the sentence
        that reached the house anyway, which on 2026-09-21 was "Okay, you can exit the pouse
        now" and was answered with "I can't end my own session, tap Stop on the deck". The
        house says goodbye and asks; the gateway leaves, down the one path a spoken phrase
        and a tap on the header both take.

        ONLY IF HE HEARD THE GOODBYE. `turn.spoken` is the honest record of whether the
        answer was voiced (`_finish` sets it, `_finish_silent` clears it), and a release he
        did not hear would take him out of a house with nothing anywhere saying so. The
        hold runs out by itself in that case, which is the repair that already exists.

        AND ONLY IF HE IS STILL IN THAT HOUSE. A late answer whose goodbye lands after he
        has moved on could otherwise end a conversation he has since started.
        """
        if not turn.leave:
            return
        turn.leave = False
        pinned = self.pinned()
        if not turn.spoken or not pinned or pinned != turn.card:
            self._log(turn, "leave-dropped", card=turn.card,
                      why=("the goodbye was not spoken" if not turn.spoken
                           else f"the user is in {pinned or 'no house'} now"))
            return
        self._log(turn, "leave-taking", card=turn.card)
        try:
            self.leave_asked()
        except Exception as exc:                                        # noqa: BLE001
            # A LEAVE MAY NEVER COST THE TURN. The answer is spoken and the record is
            # written; what fails here is the switch, and the hold expiring is the repair.
            self._log(turn, "leave-failed", card=turn.card,
                      error=f"{exc.__class__.__name__}: {exc}")

    def _drop_connect(self, turn: Turn, why: str) -> None:
        """A directive on a turn that will not be spoken: recorded, never acted on.

        Silence is the one thing this must not be. A pin taken about an answer he never
        heard would leave him talking to a house he was never told about, and a directive
        quietly discarded with no line anywhere is how "voice did something odd last night"
        becomes undiagnosable.
        """
        if turn.picked:
            self._log(turn, "answer-dropped", ask=turn.picked[0], why=why)
            turn.picked = None
        if not turn.connect:
            return
        self._log(turn, "connect-dropped", card=turn.connect, why=why)
        turn.connect = ""

    def _house_part(self, turn: Turn, text: str) -> bool:
        """One finished sentence of the house's answer, said while the turn runs (V12).

        THIS IS THE ANSWER, NOT NARRATION, and everything about it follows from that. It
        is spoken in the HOUSE's voice, because the house said it (V8). It is spoken at
        once rather than waiting for the four second silence gate, because the gate exists
        to keep the gateway from chattering at him and this is the thing he asked for. It
        sets `answering`, which ends this turn's narration: a line about what the house is
        doing, said over the house's answer, is the one interleaving V12 names.

        FALSE MEANS THE STREAMING IS OVER FOR THIS TURN, and the caller latches it. Two
        ways: he barged in (the generation moved, so `_say` would drop the audio anyway
        and speaking half an answer into a question he is already asking would be worse
        than silence), or nobody is listening. In both cases the whole answer is still
        coming, and `_house_answer` decides what to do with it the way it always has.
        """
        if turn.generation != self.generation or not self._live():
            self._log(turn, "answer-part-refused", text=text,
                      why="the user moved on" if turn.generation != self.generation
                          else "nobody is listening")
            return False
        if turn.typed:
            # A TYPED TURN IS TEXT (VP-3): its parts are not spoken, and refusing them here
            # latches the streaming cut, so the whole answer lands through `_finish`.
            self._log(turn, "answer-part-refused", text=text, why="typed, so text only")
            return False
        if turn.streams and turn.gave_up:
            # THE PROMISE HOLDS (c-221, lane D review item 4): "I'll answer in text
            # instead" was said out loud, so a streamed Harbor part after it is never
            # spoken; the caller latches the streaming cut and the answer is filed.
            self._log(turn, "answer-part-refused", text=text, why="it gave up out loud")
            return False
        # SET BEFORE A WORD IS SPOKEN, which is the ordering that makes the rule true
        # rather than nearly true: `_say` reads the speaker off the turn.
        turn.answering = True
        # A STREAMED HARBOR TURN'S PARTS ARE HARBOR'S (R2); only a house's are the house's.
        turn.speaker = config.SPEAKER_HOUSE if turn.tier == HOUSE else config.SPEAKER_HARBOR
        turn.spoke_parts.append(text)
        turn.last_spoken_at = time.time()
        self.bus.set_turn(turn.as_json())
        self._log(turn, "answer-part", text=text)
        self._say(turn, text)
        return True

    def _drain_parts(self, turn: Turn) -> None:
        """Every sentence that landed while an earlier one was playing (V13).

        `_say` BLOCKS FOR THE LENGTH OF THE AUDIO, and that is the whole of the fault this
        closes. While part one played, the rest of the answer arrived in the progress
        inbox and the final result arrived in the say inbox; the watch loop claims the SAY
        inbox at the top of every pass, so it took the result first, saw `spoke_parts` and
        finished the turn without ever claiming the parts it had not spoken. On his own
        transcript, 2026-09-21, that cost turn `8c5a99dae023` its second sentence and turn
        `0ecee464c5ea` four of them; each surfaced at the NEXT turn as a generic drop.

        SO THE INBOX IS DRAINED ONCE MORE BEFORE THE TURN CAN END, under exactly the
        checks a part is spoken under anywhere else: `_house_part` refuses on the
        generation and on liveness, and a refusal latches `parts_cut` the way the loop's
        own does. A narration line found here is refused rather than spoken, because the
        answer has finished and nothing may be said about the work after it.
        """
        if turn.parts_cut:
            return
        for claimed in self.progress_inbox.claim(turn.id):
            text = verbs.flat((claimed or {}).get("text"))
            if not (claimed or {}).get("part"):
                if text:
                    self._log(turn, "progress-refused",
                              why="the house has finished answering", text=text,
                              action=str((claimed or {}).get("action") or ""))
                continue
            if not text:
                continue
            if not self._house_part(turn, text):
                turn.parts_cut = True
                return

    def _house_answer(self, turn: Turn, text: str) -> None:
        """The house's answer, spoken when he can actually hear it (V5).

        Three questions, in this order, and the order is the requirement:

        1. **Is he there at all?** No, and it is not spoken. The card already carries the
           exchange, so nothing is lost and nothing is filed; `_finish_silent` is
           everything `_finish` does except the audio, which is exactly what is wanted.
        2. **Is he mid-sentence?** A DELAYED ANSWER NEVER INTERRUPTS HIM. When it lands
           while he is talking to Harbor (or to this house again), it waits for THAT turn
           to end and then speaks, once. "Is a turn over" is the same question `refine`
           asks, and it is asked the same way.
        3. **Has it been a while?** Past the give-up mark, minutes and another question
           may have passed, so a bare answer is unattributable by ear. One preface line
           naming the card, then the answer. It names the card because he asked about that
           card, which is the egress split's "a direct answer may name what he asked
           about"; the preface is not spoken on a turn that came back promptly, because
           then it is obvious what it is about.

        Waiting past `LATE_ANSWER_WAIT` is treated as him being gone: he has been talking
        for two minutes about something else, and an answer to the question before that is
        no longer a thing to say out loud.
        """
        # EVERY SENTENCE THAT LANDED WHILE THE LAST ONE PLAYED, FIRST (V13). It is part of
        # the answer and it has to be said before the turn can call itself finished, and
        # it has to be said before the comparison below, which is a claim about what he
        # has actually heard.
        self._drain_parts(turn)
        mark = f"{turn.card or 'the house'}, {turn.elapsed:.0f}s"
        if turn.parts_cut:
            # HALF AN ANSWER HEARD IS NOT AN ANSWER HEARD (V12). He barged in, or nobody
            # was listening: the parts stopped part way and the WHOLE answer is spoken once
            # he is quiet, so there is nothing to compare and nothing to take a remainder
            # from.
            left, why = text, "the streaming was cut"
        else:
            left, why = answer_left(turn.spoke_parts, text)
        if turn.spoke_parts and not left:
            # HE HAS ALREADY HEARD IT (V12), sentence by sentence, as the house wrote it,
            # and since V13 that is a CHECKED fact rather than an assumption: `covered`
            # says the comparison was made and agreed. Saying the whole answer again here
            # is the one regression V12 could cause; finishing silently without checking
            # is the one V13 found it had caused instead. The turn finishes exactly as it
            # would have: the bus, the transcript and the page all carry the answer, and
            # the card's note was written by the verb.
            self._log(turn, "answer-covered", covered=True, parts=len(turn.spoke_parts))
            self._finish_silent(turn, text, HOUSE, f"{mark} (as it streamed)",
                                "the answer was spoken as it streamed")
            # `_finish_silent` records a turn that was NOT voiced, and this one was; the
            # flag is what a later reading of the transcript uses to tell the two apart.
            turn.spoken = True
            self.bus.set_turn(turn.as_json())
            return
        if turn.spoke_parts:
            # WHAT IS STILL OWED, IN CHARACTERS, BESIDE THE REASON IT IS OWED. A turn that
            # says "spoken as it streamed" and a turn that had to finish the job out loud
            # are two different things, and his transcript had no way to tell them apart.
            self._log(turn, "answer-remainder", remainder=len(left), why=why,
                      parts=len(turn.spoke_parts))
        if left != text:
            mark = f"{mark} (the rest)"
        if not self._live():
            self._finish_silent(turn, text, HOUSE, f"{mark} (text)",
                                "nobody is listening, and the card has it")
            return
        waited = self._wait_for_quiet(turn)
        if not waited or not self._live():
            self._finish_silent(turn, text, HOUSE, f"{mark} (text)",
                                "the user was still talking, and the card has it")
            return
        if turn.gave_up or turn.held:
            # THE TURN'S GENERATION IS STALE BY NOW, and `_say` drops anything stale. It
            # is adopted into the generation he is actually in, which is what makes this
            # the one answer allowed to arrive late: it was promised out loud.
            turn.generation = self.generation
            turn.held = False
            self._narrate(turn, "house_late", speak=True, card=turn.card or "")
        self._finish(turn, text, HOUSE, mark, say=left)

    def _harbor_streamed(self, turn: Turn, text: str) -> bool:
        """A streamed Harbor answer he has already heard whole: finished silently, as
        `_house_answer` finishes a house's (V13-G7). True when that is what happened."""
        self._drain_parts(turn)
        if turn.parts_cut or not turn.spoke_parts:
            return False
        left, _why = answer_left(turn.spoke_parts, text)
        if left:
            return False
        self._log(turn, "answer-covered", covered=True, parts=len(turn.spoke_parts))
        self._finish_silent(turn, text, HARBOR, f"Harbor, {turn.elapsed:.0f}s (as it streamed)",
                            "the answer was spoken as it streamed")
        turn.spoken = True
        self.bus.set_turn(turn.as_json())
        return True

    def _harbor_left(self, turn: Turn, text: str) -> str:
        """What is still owed of a streamed Harbor answer: the remainder, or the whole
        answer when the streaming was cut (he barged in, or nobody was listening)."""
        if turn.parts_cut or not turn.spoke_parts:
            return text
        left, why = answer_left(turn.spoke_parts, text)
        self._log(turn, "answer-remainder", remainder=len(left), why=why,
                  parts=len(turn.spoke_parts))
        return left

    def _wait_for_quiet(self, turn: Turn) -> bool:
        """Block until no turn is in flight, or give up. True when it went quiet.

        A turn is over when its phase says so, which is the list `refine` already uses. A
        turn that is not `self.turn` any more cannot be in his way either.
        """
        over = ("done", "held", "abandoned", "failed", "cut")
        deadline = time.time() + LATE_ANSWER_WAIT
        while time.time() < deadline:
            current = self.turn
            if current is None or current is turn or current.phase in over:
                return True
            time.sleep(LATE_ANSWER_POLL)
        return False

    def _narrate_seat(self, turn: Turn, rec: dict, say: bool, left: int) -> bool:
        """The `narrate` judge, beside the decision this loop has just made (V10, V5).

        V10, verbatim: "narrate, per house activity event in V5: say it, or let it pass.
        The words still come from a template or the house's last_said, never from the
        judge." And: "On day one Jev decides NOTHING: it is asked beside the path that
        decides, its answer is logged, and the turn goes the way it would have gone
        without it."

        SO THIS RETURNS A BOOLEAN ABOUT WHETHER IT ASKED, AND NEVER ABOUT WHAT TO SAY.
        The caller has already decided; `say` is that decision, handed in so the rule
        verdict logged IS the decision rather than a second copy of it that could
        disagree. The seat cannot change it, because the key ships as `shadow` and because
        there is nowhere here for a verdict to go.

        THE RULE, WHICH IS THE BASELINE THE SHADOW LOG IS SCORED AGAINST. Say a house
        activity line when all of these hold, and let it pass otherwise: it is the freshest
        unclaimed line for this turn; four seconds have passed since anything was spoken;
        its ACTION differs from the last action spoken in this turn; the give-up line has
        not fired; the turn's progress budget is not spent; and `filler.progress_guard`
        clears its shape.

        WHAT IS SENT is the action key ("edit", "read", "test"), which is a word out of a
        closed set in `keel/narration.py` and never anything a tool was given. The judge is
        being asked whether an edit is worth mentioning, not what was edited, and the one
        thing that must never leave this box is the second question's answer.
        """
        ruling = judgesmod.rule("narrate", narrate=bool(say))
        action = str(rec.get("action") or "")
        try:
            if left <= 0:
                judgesmod.skipped("narrate", action, ruling, turn=turn.id, why=CAPPED)
                return False
            if judgesmod.shadow_busy():
                # THE OTHER JUDGE HAS A TURN WAITING ON IT. This one has nothing waiting
                # on it at all, so it stands down rather than racing for the one slot.
                judgesmod.skipped("narrate", action, ruling, turn=turn.id, why=CAPPED)
                return False
            judgesmod.ask("narrate", action, ruling, turn=turn.id)
            return True
        except Exception as exc:                                        # noqa: BLE001
            # THE WAIT MUST NEVER BE LOST TO SOMETHING ONLY ASKED BESIDE IT, which is the
            # same rule the preturn seat follows: this loop is the only thing draining the
            # say inbox, so an exception here would end the watch thread and the house's
            # real answer would arrive to nothing.
            self._log(turn, "narrate-seat-failed",
                      error=f"{exc.__class__.__name__}: {str(exc)[:200]}")
            return False

    def _narrate(self, turn: Turn, kind: str, speak: bool = True, text: str | None = None,
                 **fields) -> None:
        """One narration line: from the table, or `text` when a model wrote it.

        `text` is the filler and only the filler. Everything else in NARRATION is a fixed
        sentence rendered from an observed change, which is the half of plan section 5
        that was NOT reversed, and passing a written line through the same method is what
        keeps the transcript, the bus and the speaker seeing one kind of thing.
        """
        line = text or NARRATION[kind].format(**fields)
        turn.narration.append(line)
        self.bus.set_narration(line)
        self.bus.set_turn(turn.as_json())
        self._log(turn, "narration", line=line)
        if speak:
            # EVERY PATH THAT ACTUALLY SAYS SOMETHING GOES THROUGH HERE: the filler
            # that opens a wait, the giveup line, the hold repeat and the progress. One
            # update point is what makes the silence-since-last-spoken check in
            # `_watch` correct without having to be repeated at each call site.
            turn.last_spoken_at = time.time()
            self._say(turn, line)

    # -- speaking ---------------------------------------------------------- #

    def _finish(self, turn: Turn, text: str, tier: str, provenance: str,
                say: str | None = None) -> Turn:
        """Record `text` as the answer and speak it. `say` is what is SPOKEN when the two
        differ, which is one case and only one: a streamed answer he has already heard the
        first half of, where what is left to say is the remainder and what the page, the
        transcript and the card must carry is still the whole thing (V13)."""
        turn.tier = tier
        turn.answer = text
        turn.provenance = provenance
        turn.answered_at = time.time()
        turn.phase = "speaking"
        turn.spoken = not turn.typed
        self.bus.set_loading(False)
        self.bus.set_turn(turn.as_json())
        self.history.append(turn)
        del self.history[:-config.TRANSCRIPT_KEEP]
        self._log(turn, "answer")
        self._say(turn, text if say is None else say)
        turn.phase = "done"
        self.bus.set_turn(turn.as_json())
        self._over(turn)
        return turn

    def _over(self, turn: Turn) -> None:
        """Say the turn is over, and never let that cost the turn."""
        self._rest_typed(turn)
        try:
            self.turn_over(turn)
        except Exception as exc:                                        # noqa: BLE001
            self._log(turn, "turn-over-failed",
                      error=f"{exc.__class__.__name__}: {str(exc)[:200]}")

    def _finish_silent(self, turn: Turn, text: str, tier: str, provenance: str,
                       reason: str, queue: bool = False,
                       redact: bool | None = None) -> Turn:
        """Everything `_finish` does except the audio.

        THE ANSWER STILL LANDS ON THE VOICE PAGE, UNLESS `queue` SAYS OTHERWISE. The
        bus, the turn record and the transcript all carry it exactly as `_finish`
        would, so anything reading the bus or replaying the transcript sees a normal
        finished turn; the one thing missing is the one thing that would be wasted, an
        answer spoken into a room he is not in. This is what makes the presence gate
        (findings.md section 6) real, rather than words nothing checks.

        `queue` IS THE OTHER CASE, AND IT IS A DIFFERENT DESTINATION, NOT A REDACTION.
        c-221 first stopped a given-up answer from being spoken twice (the promise's
        audio half); a later revision (still c-221) also hid it from `turn.answer`
        behind a fixed placeholder, on the reasoning that showing the real text on
        THIS page anyway contradicted the promise in writing. c-229, round 3: he said
        directly that the voice page was never where he wanted to read it, so nothing
        is written here to redact any more; `turn.answer` is simply left empty (there
        is nothing new for this page to show) and the real text is filed as a card
        instead (`self.queue_answer`, see harbormsg.queue_answer). `text` still reaches
        the transcript LOG below (`_log`'s own `answer=text` override) regardless,
        because that is a file nobody reads mid-turn and losing it there would cost a
        real debugging record for nothing.

        BOTH SILENT PATHS FILE THE CARD NOW (decision D3, 2026-09-17), and only the
        give-up one redacts. The `not live` path used to leave its answer on the voice
        page alone, and the voice page is the one surface he has said he does not read
        after the fact: an answer spoken to an empty room reached nothing he looks at.
        So `queue` says whether to file and `redact` says whether to hide, and they are
        two decisions because on `not live` nobody was promised anything.

        NOTHING HERE REPLAYS ITSELF ANY MORE. There used to be a "say that again"
        gateway verb holding the last spoken line, with a fixed sentence standing in for
        a given-up answer so the promise held for the replay too. The verb went with the
        lookup tier (decision D4); asking for it again is an ordinary turn in the voice
        conversation, which already remembers what it said.
        """
        # FILING IT AND HIDING IT ARE TWO DECISIONS, and they were one for a while.
        # BOTH silent paths now file the card (decision D3): an answer he was not there
        # to hear is as lost as one he was promised in text. Only the GIVE-UP path hides
        # the text from this page, because only that path promised out loud that it
        # would not appear here; on the `not live` path the real answer is exactly what
        # should be waiting on the voice page when he next opens it.
        redact = queue if redact is None else redact
        shown = "" if redact else text
        turn.tier = tier
        turn.answer = shown
        turn.provenance = provenance
        turn.answered_at = time.time()
        turn.phase = "done"
        turn.spoken = False
        self.bus.set_loading(False)
        self.bus.set_turn(turn.as_json())
        self.history.append(turn)
        del self.history[:-config.TRANSCRIPT_KEEP]
        self._log(turn, "answer", spoken=False, reason=reason, answer=text)
        if queue:
            # ON THE BOARD, WHICH IS THE ONE PLACE HE LOOKS. See harbormsg.queue_answer
            # for why this is a card rather than a notice, and decision D3 for why an
            # answer nobody heard is worth one.
            try:
                staged = self.queue_answer(turn.said, text, turn.id)
            except Exception as exc:                                   # noqa: BLE001
                staged = False
                self._log(turn, "queue-failed",
                          error=f"{exc.__class__.__name__}: {exc}")
            else:
                self._log(turn, "queued" if staged else "queue-failed")
        if redact:
            # NOT PUSHED EITHER. There is nothing left on this page's own slot to raise
            # a browser notification FOR: the promise was that the answer would not
            # appear here, and the card is what keeps it.
            self._over(turn)
            return turn
        try:
            self.notify(turn, shown, reason)
        except Exception as exc:                                       # noqa: BLE001
            # A NOTIFICATION MUST NEVER COST THE ANSWER. It has already been written
            # to the transcript and the bus above; a broadcast that raises here would
            # otherwise turn a quietly-successful turn into a crashed one.
            self._log(turn, "notify-failed", error=f"{exc.__class__.__name__}: {exc}")
        self._over(turn)
        return turn

    def _rest_typed(self, turn: Turn) -> None:
        """A typed turn's end puts the bus back to idle itself (VP-3). A spoken turn is put
        there by the speaker's own `finally`; a typed one never calls the speaker, so
        without this the page would read "thinking" until the next turn."""
        if turn.typed and turn is self.turn:
            self.bus.set_state("idle")

    def _live(self) -> bool:
        """Is he actually there to hear an answer. A broken presence check must never
        cost the answer, so it defaults to yes: speaking to an empty room once in a
        while is a smaller failure than never speaking the answer at all."""
        try:
            return bool(self.presence())
        except Exception:                                               # noqa: BLE001
            return True

    def _attending(self) -> bool:
        """Can he see a page right now. A broken check holds the line back: unprompted
        speech is the one kind that loses nothing by not being said."""
        try:
            return bool(self.attending())
        except Exception:                                               # noqa: BLE001
            return False

    def log_event(self, kind: str, **fields) -> None:
        """One line about the SOCKET rather than about a turn (V13, fix 1).

        WHY THE SOCKET NEEDS A RECORD AT ALL. On 2026-09-21 a connect finished, the page
        showed "listening" for sixty-two seconds, and no audio arrived; the transcript for
        those sixty-two seconds is empty, so neither end could say afterwards whether the
        page never opened a microphone, opened one that heard nothing, or opened one whose
        frames never crossed the socket. `listen`, `frames`, `endpoint`, `listen-now` and
        the page's own `page` traces are that record, and the useful shape of it is an
        ABSENCE: a `listen` with no `frames` after it is a microphone that received
        nothing.

        AGAINST THE TURN IN FLIGHT, IF THERE IS ONE. A socket event usually happens between
        turns, and naming the last finished turn would file a listen under the question
        before it. So a turn is named only while it is still running.

        BEST EFFORT, LIKE EVERY OTHER WRITE TO THIS FILE. A log that could raise inside the
        socket's read loop would take the connection down and the turn he is in the middle
        of speaking with it.
        """
        turn = self.turn
        live = turn is not None and turn.phase not in ("done", "held", "abandoned",
                                                       "failed")
        try:
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            with self.transcript_path.open("a") as fh:
                fh.write(json.dumps({"at": time.time(), "kind": kind,
                                     "turn": turn.id if live else "",
                                     **fields}) + "\n")
        except OSError:
            pass

    def log_presence(self, event: str, clients: int) -> None:
        """Connect and disconnect, timestamped, into the same transcript the turns are
        in. Section 6 of findings.md: until now neither was recorded at all, so
        nobody could tell after the fact whether he was still on the line. Best
        effort, like every other write to this file: a presence log that could crash
        the socket handler would be worse than no presence log."""
        try:
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            with self.transcript_path.open("a") as fh:
                fh.write(json.dumps({"at": time.time(), "kind": "presence",
                                     "event": event, "clients": clients}) + "\n")
        except OSError:
            pass

    def _say(self, turn: Turn, text: str) -> None:
        """Speak, unless he has already moved on. The generation check is here rather
        than inside the speaker so every path through this file is covered by one line.

        AND IT IS THE ONE PLACE THE TURN'S ENGINE BECOMES A CALL (V7). The choice is the
        turn's because it arrived on the message that started the turn; the value handed
        down is per call because the chain is shared by every turn. What comes back names
        the engines that actually spoke, which is not the same as the one he chose: the
        chain demotes per sentence, so this is where provenance stops being a guess.
        """
        if turn.generation != self.generation:
            return
        # A TYPED TURN IS ANSWERED IN TEXT ONLY (VP-3). This is the one line that makes it
        # so: every path through this file that would make a sound comes through here.
        if turn.typed:
            return
        # AND THE ONE PLACE THE TURN'S SPEAKER BECOMES A CALL (V8). The engine is his and
        # the speaker is the gateway's, and both are the turn's rather than the chain's for
        # the same reason: one chain serves every turn, and a barge-in can have two calls
        # in flight. Every word a connected house says comes through here, which is what
        # makes the second voice last the whole conversation instead of one greeting.
        report = self.speak(text, turn.generation,
                            speech.Spoken(engine=turn.engine,
                                          speaker=turn.speaker)) or {}
        for name in report.get("engines") or []:
            if name not in turn.spoke_with:
                turn.spoke_with.append(name)
        # THE FIRST AUDIO, ONCE PER TURN (D-5): the stage `keel voice latency` cannot
        # read off anything else. Stamped by the speaker when its first chunk left.
        first = report.get("firstAudioAt")
        if turn.first_audio_at is None and isinstance(first, (int, float)):
            turn.first_audio_at = float(first)
            self._log(turn, "first-audio", at=float(first))

    # -- the transcript ----------------------------------------------------- #

    def _log(self, turn: Turn, kind: str, **fields) -> None:
        """One of the gateway's two writable files. Append only, best effort: a log must
        never cost the answer."""
        try:
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            with self.transcript_path.open("a") as fh:
                line = {"at": time.time(), "turn": turn.id, "kind": kind,
                        "tier": turn.tier, "mode": turn.mode, "said": turn.said,
                        "answer": turn.answer}
                # ONLY WHEN THERE IS ONE. The recorder is off by default and off again
                # once the corpus is measured, and a `"pcm": ""` on every line of a
                # 190 KB transcript is a field that says nothing on the turns that
                # matter and costs bytes on every turn that does not.
                if turn.pcm:
                    line["pcm"] = turn.pcm
                fh.write(json.dumps({**line, **fields}) + "\n")
        except OSError:
            pass


def _giveup_mark(turn: Turn) -> float:
    """When the give-up line fires: Harbor's own estimate, held to with real tolerance,
    or the flat default when it never gave one, or gave one too small to trust (c-229).

    THE FLOOR DISCARDS, IT DOES NOT CLAMP. Review round 1 caught the first cut of this
    doing `max(ETA_GIVE_UP_FLOOR, turn.eta + ETA_TOLERANCE)`, which turns a too-small
    eta into a mark of exactly the floor (15s) rather than falling back to the flat
    default (60s) the way config.py's own comment on ETA_GIVE_UP_FLOOR and the approved
    plan both describe ("an eta below this is treated as not given, the same as a
    'quick' turn"). Clamping UP shortened the backstop for a bad guess instead of
    restoring it; the floor is a trust threshold on the estimate itself, not a lower
    bound on the arithmetic.

    THE CEILING STILL CLAMPS, because that half is a bound on the arithmetic: a
    wildly high (but plausible) eta must not turn one bad guess into an absurdly long
    wait either, and there is nothing to fall back to that is shorter and still honest.
    """
    if not turn.eta or turn.eta < config.ETA_GIVE_UP_FLOOR:
        return config.NARRATE_GIVE_UP_AT
    return min(config.ETA_GIVE_UP_CEILING, turn.eta + config.ETA_TOLERANCE)


# --------------------------------------------------------------------------- #
# What counts as an observed change worth narrating.
# --------------------------------------------------------------------------- #

def _observable(doc: dict) -> dict:
    """The few things the narration table can see. Ids and counts, never bodies."""
    queue = [q for q in (doc.get("queue") or [])
             if q.get("status", "pending") == "pending"]
    return {
        "running": {str(r.get("id")): str(r.get("name") or "") for r in
                    (doc.get("running") or [])},
        "queue": {str(q.get("index")): verbs.flat(q.get("what")) for q in queue},
        "reviews": {str(r.get("key")) for r in (doc.get("reviews") or [])},
    }


def _changes(before: dict, now: dict):
    """(kind, fields) for each thing that appeared. Appearances only.

    Disappearances are not narrated, and that is a decision rather than an oversight: a
    dispatch ending while he waits is not news about the question he asked, and a queue
    entry he just resolved on the dashboard should not be announced back at him.
    """
    for did, name in now["running"].items():
        if did not in before["running"]:
            yield "spawned", {"name": name or did[:8]}
    for idx, title in now["queue"].items():
        if idx not in before["queue"]:
            yield "card", {"title": title}
    for key in now["reviews"]:
        if key not in before["reviews"]:
            yield "review", {}
