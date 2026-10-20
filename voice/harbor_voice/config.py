"""Every switch the voice front end has, in one file, with the reason beside it.

TWO KINDS OF SWITCH LIVE HERE and they are deliberately not separated, because a person
looking for "how do I turn X off" should find one file rather than guess which.

  1. ENGINEERING CHOICES that were measured: the speech and filler backends, the
     timeouts, the ports. Each one carries the number that justifies it.

  2. THE FOUR OPEN QUESTIONS from the UI mockup. The user has NOT answered them. Each is
     built the way the mockup RECOMMENDS, and each is one constant, so changing an
     answer is one edit here and nothing else. They are marked OPEN QUESTION so nothing
     reads them as settled.

Server-side flags are read from here. The four UI answers are ALSO needed by the page,
which is static files that cannot import Python, so `flags_for_page()` renders them and
the gateway serves them at /voice/flags.js. One source, two readers, no second copy.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# WHERE EVERYTHING IS, and it is one root. The gateway lives in Keel (`~/keel/voice/`, the
# scripts in `~/keel/bin/`), reads Keel's board, and keeps its writable state under Keel's
# `state/`. `KEEL_HOME` is the one environment variable that moves all of it; the launchd
# agent `keel voice install` writes sets it explicitly, because launchd hands a process
# almost no environment at all.
#
# THE DEFAULT IS THIS PACKAGE'S OWN CHECKOUT, NOT `~/keel` (2026-09-20). It was
# `Path.home() / "keel"`, so a gateway started from a worktree with `PYTHONPATH=<worktree>
# /voice` and no `KEEL_HOME` wrote its transcript, its filler cache, its judge log and its
# recordings straight into the LIVE `state/voice/`, whatever else the launch had isolated.
# The package knows where it is; a home directory does not know which checkout is running.
#
# AND A `KEEL_HOME` NAMING ANOTHER CHECKOUT IS NOT FOLLOWED EITHER (2026-09-20, later the
# same day). Defaulting to the package's checkout fixed the launches that set no `KEEL_HOME`;
# a house sets one, and it names the LIVE checkout, because that is what the drain puts in
# every house's environment. So `bin/keel-voice-selftest`, run from a worktree to prove a
# house's work, still reached `<live>/bin/kb` and filed its two capture checks as real cards,
# 84 of them in a day. The rule is the same one `keel/config.py` holds: the state a checkout
# may open is its own. A `KEEL_HOME` that names a directory carrying a copy of THIS FILE is
# naming another checkout's state, and this package keeps its own instead;
# `KEEL_LIVE_STATE=1` is the one way to mean it. A `KEEL_HOME` naming a scratch directory
# with no package in it is followed as before, which is what every fixture and every scratch
# launch relies on.
CHECKOUT = Path(__file__).resolve().parent.parent.parent
SELF = Path(__file__).resolve().relative_to(CHECKOUT)   # voice/harbor_voice/config.py
LIVE_STATE = os.environ.get("KEEL_LIVE_STATE", "").strip().lower() in ("1", "yes", "true", "on")


def is_checkout(path: Path) -> bool:
    """True when `path` carries this file too, so it is a Keel checkout in its own right."""
    try:
        return (path / SELF).exists()
    except OSError:
        return False


def borrows_home(asked: Path) -> bool:
    """True when `KEEL_HOME` names a checkout that is not the one this package runs from."""
    try:
        return asked.resolve() != CHECKOUT.resolve() and is_checkout(asked)
    except OSError:
        return False


ASKED_HOME = Path(os.environ.get("KEEL_HOME") or CHECKOUT)
BORROWED_HOME = borrows_home(ASKED_HOME) and not LIVE_STATE
KEEL_HOME = CHECKOUT if BORROWED_HOME else ASKED_HOME
STATE = KEEL_HOME / "state"

# THE GATEWAY'S WHOLE WRITABLE SURFACE: the say, progress and opening inboxes, the
# transcript, the TTS meter, and under cache/ the rendered filler audio. Under `state/`
# because that is the one backed-up, gitignored tree; nothing here is repository content
# and none of it belongs in the segments tree the deck serves files from.
DATA = STATE / "voice"

# THE SEGMENTS TREE, for the one cross-segment read this package makes
# (speech._cloud_spend_record, the durable TTS spend ledger). It is not this package's to
# locate: `keel voice install` writes keel.toml's `segments_dir` into the agent's
# environment, so the read follows cutover step 8 without this file learning to parse
# TOML. Absent, it is Keel's own segments directory.
SEGMENTS_DIR = Path(os.environ.get("KEEL_SEGMENTS_DIR") or (KEEL_HOME / "segments"))

# THE ADAPTERS TREE, for the one read this package makes of it: `hearing` merges each
# adapter's `hearing.json`, because a mishearing of an employer's name is employer
# vocabulary and may only live in its pack (packs/work/). Written by `keel voice install` from
# keel.toml's `adapters_dir`, the same way SEGMENTS_DIR is.
ADAPTERS_DIR = Path(os.environ.get("KEEL_ADAPTERS_DIR") or (KEEL_HOME / "adapters"))

# --------------------------------------------------------------------------- #
# The gateway's own port, and where the board it answers from lives.
# --------------------------------------------------------------------------- #

# The gateway's own port: the value it BINDS. `keel serve` proxies /voice/ to the port in
# keel.toml's [voice] table, and `keel voice install` writes that same value here through
# the agent's environment, so the two cannot disagree without the plist being stale.
PORT = int(os.environ.get("HARBOR_VOICE_PORT", "4390"))

# WHERE THE DECK IS, and it is 127.0.0.1 with no exception. The digest has been built
# from the deck's own state document since 2026-09-18 (decision V16), because the deck
# already carries everything either Harbor is asked about out loud: both spaces' cards,
# the needs-you queue, the running houses, the review cards (a pull request on its card),
# the segments and the drain pill. `keel voice install` writes this value into the
# agent's environment from keel.toml's `serve_port`, so the two cannot disagree without
# the plist being stale.
#
# THE LOOPBACK RULE IS STILL THE RULE, and it is still kept by construction rather than
# by a comment: the literal 127.0.0.1 lives in `keel/deckdigest.py` and there is no host
# setting anywhere, so voice can never be pointed at a board on another machine.
SERVE_PORT = int(os.environ.get("KEEL_SERVE_PORT", "8790"))

# WHERE THE BOARD IS when the deck does not answer: `kb`, reading the same SQLite file
# the deck reads. The fallback is the same board through a narrower window, and the
# digest says which of the two it had (`source`, "deck" or "board").
KB = KEEL_HOME / "bin" / "kb"
# A MARK ON EVERY CARD THIS PROCESS FILES, when one is given (c-417). Only
# `bin/keel-voice-selftest` sets it: every `kb create` then carries
# `--option run_nonce=<it>` (`snapshot._kb`), so the run can open the live board read-only
# afterwards and say, by a value only it knows, that nothing it filed landed there. Unset in
# the gateway, where it adds nothing.
RUN_NONCE = os.environ.get("HARBOR_VOICE_RUN_NONCE", "")

# AND THE VERB HARBOR DRAWS WITH. `keel board push --talker` is the same command a house
# runs from its own shell, and it is RUN rather than imported for the reason `KB` is: it
# resolves which board this checkout writes to (scratch or live) through `keel.toml`, and
# this package's interpreter must not hold the store to find that out. See `voice/harbor_voice/drawing.py`.
KEEL_BIN = KEEL_HOME / "bin" / "keel"

# WHICH BOARD THAT `kb` OPENS, and it is the one thing this package must say out loud
# before it accepts a word (2026-09-20). Four houses ran a scratch gateway from their
# worktree for a live-socket check, each with its own `KEEL_HOME`, port and PATH, and every
# capture they spoke into it was filed as a real card on his board, because the `kb` those
# launches reached was the live checkout's. `keel/config.py` now gives a worktree its own
# scratch board, so the board a gateway writes to is decided by WHICH CHECKOUT ITS `kb`
# BELONGS TO, and that is a path comparison this package can make for itself. The rule is
# written twice on purpose: this package runs from `.venv-voice` and never imports `keel`.
# `LIVE_STATE` is read at the top of this file, with `KEEL_HOME`, because it is the one
# thing that lets a borrowed home through.
WORKTREES = ("state", "worktrees")      # `<checkout>/state/worktrees/<card>`: keel/house.py


def is_worktree(checkout: Path) -> bool:
    """True when `checkout` is a house's worktree rather than a checkout of its own."""
    return tuple(checkout.resolve().parts[-3:-1]) == WORKTREES


def board_kind() -> str:
    """`scratch` or `live`: what `KB` will open, named the way the startup line names it.

    The checkout `KB` hangs off is the one whose `keel.toml` that `kb` loads, so a worktree's
    own `kb` is a scratch board and any other checkout's is the live one.
    """
    return "scratch" if is_worktree(Path(KB).resolve().parent.parent) else "live"


def board_line() -> str:
    """The gateway's first log line: the board, the toml its `kb` loads (`KEEL_TOML`,
    c-711) and the state directory, in that order.

    A home that was named and not followed is said on the same line rather than in a second
    one, because the whole value of this line is that it is the FIRST thing in the log.
    """
    moved = (f"  (KEEL_HOME named {ASKED_HOME}, which is another checkout, so this one kept "
             f"its own)" if BORROWED_HOME else "")
    return f"voice: board {board_kind()} via {KB}  config {KEEL_TOML}  state {DATA}{moved}"
TALKER_CONFIG_DIR = KEEL_HOME / "spaces" / "harbor" / ".claude"
TALKER_CWD = KEEL_HOME / "talker"
# THE VOICE CONVERSATION'S RECORD: {uuid, turns, started_at}, which is what lets it
# rotate on either bound. It was a bare uuid in `voice-session` until 2026-09-17;
# `harbormsg.read_session` migrates that file once and removes it.
VOICE_SESSION_FILE = KEEL_HOME / "state" / "voice-session.json"
VOICE_SESSION_LEGACY = KEEL_HOME / "state" / "voice-session"


def keel_state(home: Path, env: dict | None = None) -> Path:
    """The state dir of the config the service was installed from (`KEEL_STATE_DIR`, which
    `keel voice install` writes from `state_dir`), else the home's own `state/`.

    ONLY FOR WHAT KEEL WRITES AND THIS PACKAGE READS (c-711), which is the talker's pid:
    `keel talker start` writes it under its config's state dir, and on an install that is
    not `<checkout>/state`. This package's OWN files (`STATE`, `DATA`, the voice session)
    stay under `KEEL_HOME`, so a worktree's gateway can never be sent into the live state by
    a variable it inherited; a borrowed home ignores the variable for the same reason."""
    named = (os.environ if env is None else env).get("KEEL_STATE_DIR")
    return Path(named).expanduser() if named and not BORROWED_HOME else home / "state"


KEEL_STATE = keel_state(KEEL_HOME)
TALKER_PID_FILE = KEEL_STATE / "talker.pid"

# A headless turn under the talker's rules is a real model turn: 10 to 40 s measured for
# the old pane route, and `-p` has the same shape. Narration covers the wait
# (NARRATE_ELAPSED_AT and NARRATE_GIVE_UP_AT below are unchanged).
HARBOR_TURN_TIMEOUT = float(os.environ.get("HARBOR_VOICE_TURN_TIMEOUT", "120"))

# THE MODEL EACH TURN RUNS ON (`[models]` in keel.toml, written here by `keel voice
# install`). The voice conversation and the refine share ONE session, and each `claude -p`
# names its own `--model`, so the conversation speaks on one model and the refine a
# capture gets runs on a cheaper one. Never left out: a turn with no `--model` runs on the
# account's own default. The defaults are the settled ones, for a service file written
# before these two keys existed.
CONVERSE_MODEL = os.environ.get("HARBOR_VOICE_CONVERSE_MODEL") or "opus"
REFINE_MODEL = os.environ.get("HARBOR_VOICE_REFINE_MODEL") or "sonnet"

# HARBOR'S OWN TURNS ON ONE KEPT-ALIVE, STREAMED PROCESS (R2, `[voice] harbor_kept_alive`
# in keel.toml, written here by `keel voice install`). OFF unless it says "1": off, every
# Harbor turn is today's `claude -p --resume` per utterance, byte for byte. On, the turn
# goes down one `claude --input-format stream-json` process (`harborlive.py`) and the
# answer is spoken sentence by sentence as it is written, the way a house's already is.
HARBOR_KEPT_ALIVE = os.environ.get("HARBOR_VOICE_HARBOR_KEPT_ALIVE", "0").strip() == "1"
# How long an idle kept-alive Harbor process is kept before it is closed. The next turn
# then opens a fresh one (and pays the start once), so nothing resident outlives a
# conversation by more than this.
HARBOR_LIVE_IDLE = float(os.environ.get("HARBOR_VOICE_HARBOR_LIVE_IDLE", "600"))

# --------------------------------------------------------------------------- #
# THE TWO MODES (<install>/history/docs/voice-two-modes.md). One gateway, one socket, two paths after the
# speech model: CAPTURE files what he said as an inbox card with no model in the loop,
# TALK is the conversation with Harbor. The mode rides on every `end` and `text` message;
# a message with no mode at all is TALK, because that is what every client that predates
# the modes meant (`bin/keel-voice ask`, an old cached page).
# --------------------------------------------------------------------------- #
MODE_CAPTURE = "capture"
MODE_TALK = "talk"
MODES = (MODE_CAPTURE, MODE_TALK)


def normal_mode(value, default: str = MODE_TALK) -> str:
    """`capture` or `talk`. "converse" is the plan's word for talk and is accepted."""
    word = str(value or "").strip().lower()
    if word == "converse":
        return MODE_TALK
    return word if word in MODES else default


# WHICH MODE THE PAGE OPENS IN, the first time, before he has touched the toggle (after
# that the page remembers his choice). Capture, decision D1: it is the 70 percent case
# and the mode he opens the app for. `keel voice install` writes keel.toml's
# `[voice] mode_default` into the agent's environment under this name.
MODE_DEFAULT = normal_mode(os.environ.get("HARBOR_VOICE_MODE_DEFAULT"), MODE_CAPTURE)

# WHERE A CAPTURE IS FILED when the message names no space, or one this build does not
# know. Personal, decision D2: a work idea filed personal is a private note until
# something promotes it, which is the safe direction. From `[voice] space_default`.
CAPTURE_SPACES = ("personal", "work")
CAPTURE_SPACE_DEFAULT = (os.environ.get("HARBOR_VOICE_SPACE_DEFAULT") or "personal"
                         ).strip().lower()
if CAPTURE_SPACE_DEFAULT not in CAPTURE_SPACES:
    CAPTURE_SPACE_DEFAULT = "personal"

# How much of his first sentence becomes the card's title. The refine tidies it later;
# the quote in the brief is never clipped.
CAPTURE_TITLE_CHARS = int(os.environ.get("HARBOR_VOICE_CAPTURE_TITLE_CHARS", "72"))

# HOW MANY TURNS MAY BE IN FLIGHT AT ONCE, over and above the one that is running. One
# conversation, one transcript, and he is one person with one mouth: a second utterance
# waits behind the turn lock, and a third is answered with the fixed line rather than
# queued, because answering him a minute later about something he has moved on from is
# worse than telling him to wait. Capture never takes that lock and is never bounded by
# this: it has no model turn to serialise.
HARBOR_TURN_QUEUE_MAX = int(os.environ.get("HARBOR_VOICE_TURN_QUEUE_MAX", "1"))

# WHEN THE VOICE CONVERSATION IS RETIRED AND A FRESH ONE STARTED. Every `-p --resume`
# re-reads the whole transcript, so latency grows with age and nothing else resets it.
# Turns bound a busy day; age bounds a thin conversation left open for a week, which is
# still an expensive prefix to re-read. The first turn of the new one carries a one line
# handover, so nothing is lost that was worth carrying.
VOICE_SESSION_MAX_TURNS = int(os.environ.get("HARBOR_VOICE_SESSION_MAX_TURNS", "40"))
VOICE_SESSION_MAX_AGE = float(os.environ.get("HARBOR_VOICE_SESSION_MAX_AGE", "86400"))

# THE REFINE (refine.py): one bounded model turn per capture, a while later, that nobody
# is waiting for. ON since it was built, because a capture without it is an honest card
# that is unreadable a week later; `HARBOR_VOICE_REFINE=0` turns it off and the capture
# path does not change by one line when it is off.
REFINE_ENABLED = (os.environ.get("HARBOR_VOICE_REFINE", "1").strip().lower()
                  not in ("0", "false", "no", "off"))

# HOW LONG HE HAS TO BE QUIET before the queue drains. Measured from the LAST capture,
# not from each one: dumping ideas comes in runs, and refining each card twenty seconds
# after itself would put four model turns on top of the run he is still in the middle of.
REFINE_DELAY_SECONDS = float(os.environ.get("HARBOR_VOICE_REFINE_DELAY", "20"))

# --------------------------------------------------------------------------- #
# What used to be here: the router.
#
# THE LOOKUP TIER IS GONE, deleted 2026-09-18 on the user's decision (D4 in
# `<install>/history/docs/voice-two-modes.md` section 4, V13 in `<install>/history/docs/decisions.md`). It had been off
# since 2026-09-04 (`HARBOR_VOICE_ROUTER=none`) and neither of the two modes needs it:
# converse sends every turn to the model, and capture asks nothing. `ROUTER_BACKEND`,
# `ROUTER_MODEL`, `ROUTER_URL`, `ROUTER_TIMEOUT`, `ROUTER_WARM_EVERY`,
# `ROUTER_KEEP_ALIVE`, `ROUTER_MAX_TOKENS`, `ROUTER_CONTEXT_TURNS`,
# `ROUTER_CONTEXT_MODE` and `CONTEXT_MEMORY` went with it, and so did the environment
# variables behind them: setting `HARBOR_VOICE_ROUTER` now does nothing at all.
#
# WHAT IS LEFT OF IT is one code-rendered answer with no model and no classifier, the
# exact-phrase table in verbs.py ("what's waiting on me"). Everything else a lookup verb
# answered goes through converse and comes back in about ten seconds with the board
# digest attached, which is the price of never being confidently wrong.
#
# THERE IS STILL NO PAID API PATH FOR ANY MODEL IN THIS PACKAGE. Not commented out, not
# behind a flag, not "if a key is present". Findings 11 to 15 rejected hosted routing on
# custody grounds, and the only vendor this package reaches is the VOICE: it is handed
# finished text and hands back audio (speech.py), never a decision and never the index.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# The filler: qwen's second job, speaking about the WAIT while Harbor thinks.
#
# THIS REVERSES A LOCKED RULE, ON PURPOSE AND ON HIS INSTRUCTION. Plan section 5 said
# "the wait narrates real state, never filler". That rule produced a wait that says one
# sentence and then nothing for ten to twenty-nine seconds, to a man walking with the
# phone in his pocket where the on-screen thinking indicator it leaned on is not visible.
# The user reversed it on 2026-09-04. The decision is recorded in design-source.md as a
# decision rather than a drift, and what is NOT reversed is written at the top of
# filler.py: a line is still spoken only when something really happened, and no line ever
# carries a timer.
# --------------------------------------------------------------------------- #

# WHICH BACKEND WRITES THE WAIT'S LINE.
#
#   corpus   THE ONE THAT SHIPS, as of 2026-09-04. A few hundred lines written by a
#            person, picked by relevance to what he just asked, and spoken from a WAV
#            rendered once. No model call and no TTS call.
#   table    the twelve fixed lines in filler.TABLE. Kept as the floor: it needs no
#            corpus file and no rendered audio, so it is what a fresh checkout speaks.
#   ollama   qwen writes the line and filler.guard refuses it if it asserts anything.
#            Kept behind the flag, not deleted, because it is measured by
#            bin/keel-voice-filler-score the moment it is switched on.
#
# WHY THE MODEL STOPPED WRITING IT, and it is not about cost. Findings 26 and 27 attacked
# the guard with 810 samples across three adversarial sets: break rates 14%, 36% and 37%,
# NOT converging, and each set found a class of escape the one before had not imagined.
# The worst was not a fabricated fact, it was a PROMISE about his ordinary life ("Got it,
# won't forget", said about his rent, recorded nowhere). Finding 27 says why the guard
# will never close that class: every escape was found by a person READING the lines,
# because if a counter could recognise one the guard would already have refused it.
#
# A WRITTEN CORPUS REMOVES THE CLASS RATHER THAN BOUNDING IT. Nothing is generated, so
# nothing can escape; the guard still runs, but once, at build time, over a set somebody
# can read in full. See corpus.py.
FILLER_BACKEND = os.environ.get("HARBOR_VOICE_FILLER", "corpus")

# HOW A LINE IS CHOSEN, and both answers were measured rather than assumed. He asked for
# semantic search; the question was whether it earns its keep, because the whole point of
# switching the lookup tier off was to stop holding a model.
#
#   embed    cosine over static embeddings from `minishlab/potion-base-8M` through
#            model2vec. Deliberately the SAME model csr's thread search uses, so this
#            machine holds one static embedding model rather than two. 123 MB on disk,
#            no torch, and 10 ms to encode a sentence: it is a lookup table, not a
#            network, which is why it does not reopen the resident-cost question.
#   keyword  a keyword mapping over the same six topics. No model at all.
#
# The comparison is in bin/keel-voice-corpus score and the number is in
# artifacts/voice-harbor/findings.md finding 29.
FILLER_PICKER = os.environ.get("HARBOR_VOICE_FILLER_PICKER", "embed")

# THE MODEL NAME THE ROUTER LEFT BEHIND, and it is only read when `HARBOR_VOICE_FILLER`
# is switched to `ollama`: qwen2.5:7b was measured by `plan` at 350 ms median on this
# machine, and it is what `ollama` means here. The shipped filler is the written corpus
# and holds nothing.
FILLER_MODEL = os.environ.get("HARBOR_VOICE_FILLER_MODEL", "qwen2.5:7b")

# WHERE THAT ONE OPTIONAL LOCAL CALL GOES, and how long ollama is asked to hold the
# weights for. Both moved here from the deleted lookup tier, because the filler behind
# `HARBOR_VOICE_FILLER=ollama` is now the only thing in this package that would make it.
# Long, because the whole point of a filler is that it arrives inside the delivery hop,
# and a cold call after an eviction pays the model load.
OLLAMA_URL = os.environ.get("HARBOR_VOICE_OLLAMA", "http://127.0.0.1:11434/api/chat")
FILLER_KEEP_ALIVE = os.environ.get("HARBOR_VOICE_KEEP_ALIVE", "60m")

# HOW OFTEN THE GATEWAY RE-WARMS A RESIDENT FILLER's prompt cache, in seconds. It is only
# read when something actually holds a model (see Gateway._warm_filler), which the
# shipped corpus filler does not.
FILLER_WARM_EVERY = float(os.environ.get("HARBOR_VOICE_WARM_EVERY", "300"))

# BUDGETED AGAINST THE DELIVERY HOP, not against the model. The filler is generated on
# its own thread WHILE the utterance is being typed into Harbor's pane (measured 1.65 to
# 3.16 s), and it is spoken the moment delivery is verified, so anything arriving inside
# that window costs nothing at all. Anything slower is dropped for the table, because a
# filler that lands late lands on top of Harbor's real answer.
# MEASURED across 540 adversarial samples, back to back, which is a LOADED ollama rather
# than a quiet one: median 0.95 s, p90 1.49 s, max 5.1 s. 1.5 s sat exactly on the p90, so
# roughly one filler in ten fell back to the written table for no reason but arithmetic.
# 2.0 s is inside the measured delivery hop's median and it still cannot delay the answer:
# the worst case is that the acknowledgement is spoken half a second after the line landed
# in the pane, and beyond it the table speaks instead.
FILLER_TIMEOUT = float(os.environ.get("HARBOR_VOICE_FILLER_TIMEOUT", "2.0"))

# Twelve words is the prompt's ceiling and filler.MAX_WORDS is fourteen, so 48 tokens is
# generous. It is a stop, not a budget: a model still writing at 48 tokens has started
# explaining itself, and the guard would refuse the result anyway.
FILLER_MAX_TOKENS = 48

# THE ONE PLACE THIS PACKAGE ASKS FOR VARIETY. A filler said in identical words every
# time is a recording, and the fixed table already is one.
FILLER_TEMPERATURE = float(os.environ.get("HARBOR_VOICE_FILLER_TEMP", "0.8"))

# HOW OFTEN SOMETHING SPEAKS AGAIN DURING THE SAME WAIT, in seconds. 0 means once only.
#
# THIS CONSTANT EXISTED AND NOTHING READ IT. It has been in this file since the filler
# shipped, documented as the value that holds the decision, and no line of code anywhere
# looked at it: setting it did nothing, silently, which is worse than not having it. It
# is read now, in dispatcher._watch.
#
# WHY THE ANSWER CHANGED FROM ZERO. Findings 25 set it to zero for two reasons and one of
# them has gone. The reason that has gone is the important one: the model filler's escape
# risk was PER UTTERANCE, so speaking k times multiplied the single risk the whole guard
# existed to bound. With the corpus there is no per-utterance risk to multiply, because
# the lines are written and fixed. The reason that stands is that there is nothing NEW to
# say, and the corpus answers that with `hold` lines, which are written to sound like
# continuing rather than like starting.
#
# CUT BACK, 2026-09-15, c-221. The testing phase measured what it needed to (repeats are
# safe, the corpus's `hold` lines read as continuing rather than starting) and then kept
# running past the point that measurement justified: six repeats every eight seconds was
# up to seven spoken lines on one long wait, which is bombardment rather than company.
# Approved shape, from the plan gate: the opener, a hold line at 20 s, a second at 40 s,
# then nothing until the 60 s give-up (NARRATE_GIVE_UP_AT below) takes over. Twenty
# because it matches what the corpus's own `hold` lines were written for ("twenty seconds
# later", see corpus.py), not the eight-second number that had drifted from it.
FILLER_REPEAT_EVERY = float(os.environ.get("HARBOR_VOICE_FILLER_REPEAT", "20"))

# TWO, evenly spaced inside the shorter 60 s give-up window (20 s, 40 s), then silence.
# Six was argued against a measured maximum wait that the give-up line has since made
# moot: past NARRATE_GIVE_UP_AT nothing scripted speaks again regardless of this number,
# so the two together are what decide the whole shape of a long wait's sound.
FILLER_REPEAT_LIMIT = int(os.environ.get("HARBOR_VOICE_FILLER_REPEAT_MAX", "2"))

# --------------------------------------------------------------------------- #
# Speech.
# --------------------------------------------------------------------------- #

# Measured 114 to 186 ms for 1.5 to 5.3 seconds of audio on the Neural Engine.
STT_BACKEND = os.environ.get("HARBOR_VOICE_STT", "auto")
STT_MODEL = os.environ.get("HARBOR_VOICE_STT_MODEL", "mlx-community/parakeet-tdt-0.6b-v2")

# THE BOX'S SPEECH MODELS, which are files rather than packages (onnx.py). The directory
# is where the 2026-09-18 benchmark left them.
# `HARBOR_VOICE_STT=sherpa` selects sherpa-onnx; the model is an alias from
# onnx.SHERPA_MODELS or a path. parakeet-110m: a 2 s utterance in 0.067 s on the box's
# two cores, 251 MB; parakeet-0.6b: 0.25 s, 1015 MB. Two threads because the box has two
# cores and the voice unit's CPU weight puts a spoken turn ahead of the houses.
MODELS_DIR = Path(os.environ.get("HARBOR_VOICE_MODELS") or (Path.home() / "voice-bench" / "models"))
SHERPA_MODEL = os.environ.get("HARBOR_VOICE_SHERPA_MODEL", "parakeet-110m")
SHERPA_THREADS = int(os.environ.get("HARBOR_VOICE_SHERPA_THREADS", "2"))
KOKORO_ONNX_MODEL = os.environ.get("HARBOR_VOICE_KOKORO_ONNX_MODEL", "kokoro-v1.0.onnx")
KOKORO_ONNX_VOICES = os.environ.get("HARBOR_VOICE_KOKORO_ONNX_VOICES", "voices-v1.0.bin")

# THE CHAIN, and it is a chain rather than a choice because degrade-never-mute needs a
# floor that works with no network and no extra install. Tried in order, first one that
# is actually available wins, and /voice/health reports which one answered so a degraded
# voice is visible rather than merely different.
#
#   google    THE VOICE, chosen by the user on 2026-09-04 from rendered samples:
#             en-IN-Chirp3-HD-Charon through Google Cloud Text-to-Speech.
#   kokoro    directly beneath it, and it stays there. Local, 24 kHz, voice bm_lewis.
#             A network failure, an expired key or a quota stop degrades to a local
#             voice, never to silence, and the demotion happens per SENTENCE at speaking
#             time rather than once at construction: see speech.TTSChain.
#   kokoro-onnx the same voice through onnxruntime, for Linux (onnx.py); the box's
#             chain is google,kokoro-onnx,browser, written by `keel voice install`.
#   elevenlabs his own key from the Keychain, if he has set one. Never a file.
#   say       macOS's own synthesiser, local and offline.
#   browser   the page's speechSynthesis, which costs one line and mutes nothing.
TTS_CHAIN = [s for s in os.environ.get(
    "HARBOR_VOICE_TTS", "google,kokoro,elevenlabs,say,browser").split(",") if s.strip()]
TTS_VOICE = os.environ.get("HARBOR_VOICE_TTS_VOICE", "bm_lewis")
TTS_SAY_VOICE = os.environ.get("HARBOR_VOICE_SAY_VOICE", "Daniel")
TTS_RATE = 24000

# THE VOICE HE PICKED, and the language code that goes with it. Chirp 3 HD voices are
# named `<languageCode>-Chirp3-HD-<name>` and the API refuses a name whose language code
# does not match, so these two travel together and are one decision rather than two.
GOOGLE_TTS_VOICE = os.environ.get("HARBOR_VOICE_GOOGLE_VOICE",
                                  "en-IN-Chirp3-HD-Charon")
GOOGLE_TTS_LANGUAGE = os.environ.get("HARBOR_VOICE_GOOGLE_LANGUAGE", "en-IN")

# WHERE THE KEY LIVES: one place per machine, read at construction and held in memory for
# the life of the process. On macOS, the login keychain, service `harbor-voice-google`. On
# Linux, which has no keychain, a systemd credential (c-299): the voice unit's
# `LoadCredential=google-tts-key:~/.config/keel/credentials/google-tts-key` puts a copy in
# `$CREDENTIALS_DIRECTORY`, and `keel voice key set` writes the source. Never an
# environment variable, never a file in the repo or under state/, never a backup, never a
# log line, never a fixture, and never a URL: the key travels in the X-Goog-Api-Key header
# precisely so that no string this package might print can contain it. It is restricted to
# the Text-to-Speech API and belongs to a PERSONAL Google project; the ambient gcloud
# credentials on this machine are a work account with a work quota project and must never
# be used for this.
GOOGLE_TTS_KEYCHAIN = os.environ.get("HARBOR_VOICE_GOOGLE_KEYCHAIN",
                                     "harbor-voice-google")
GOOGLE_TTS_CREDENTIAL = "google-tts-key"

# TAKEN OUT OF THE ENVIRONMENT THE MOMENT THIS PACKAGE LOADS, so nothing the gateway starts
# (a `claude` talker turn, `kb`) inherits the pointer to the key. Every module imports this
# one first, so this runs before any child exists. It hides the path, not the permission:
# a child running as the same user could still open the directory if it knew the unit's
# name, which is the same reach a same-user process has into the Mac's keychain.
CREDENTIALS_DIRECTORY = os.environ.pop("CREDENTIALS_DIRECTORY", "")

# ----- the judges, and the classifier they ask (V10, c-313) -----

# WHERE THE JEV KEY LIVES: exactly where the Google key lives on each machine, and nowhere
# else. The login keychain on the Mac, the voice unit's systemd credential on the box,
# whose source `keel voice key set --name jev` writes 0600 in a 0700 directory outside the
# checkout and outside state/. It is read once and held for the life of the process, it
# travels in an Authorization header, and no string this package prints can contain it.
JEV_KEYCHAIN = os.environ.get("HARBOR_VOICE_JEV_KEYCHAIN", "harbor-voice-jev")
JEV_CREDENTIAL = "jev-key"

# THE ROUTE HIS TEXT GOES OUT UNDER, declared by him in a file rather than sent as a
# request flag, because the direct API has no such flag (c-295 found that the hard way and
# c-300 records the correction). The client refuses to send anything until this says
# something true, so the declaration is a fact on the machine and not a memory.
JEV_RETENTION_FILE = Path(os.environ.get("HARBOR_VOICE_JEV_RETENTION")
                          or (Path.home() / ".config" / "jev" / "retention"))
JEV_RETENTION_OK = ("zdr", "accept-default-retention")

# PINNED, because a confidence floor tuned against one model means nothing against another
# (c-300's guard). A model change is then a visible edit here rather than a silent drift.
JEV_HOST = os.environ.get("HARBOR_VOICE_JEV_HOST", "api.typesafe.ai")
JEV_PATH = "/v1/systemone"
JEV_MODEL = os.environ.get("HARBOR_VOICE_JEV_MODEL", "jev-1.13.0")

# V10's budget per call. Past it the rule's verdict stands and the call is a counted miss:
# never a stall, never a spoken error. The number is V10's own and is not tuned here; B0
# from this machine is what says whether a cold connection can ever meet it.
JEV_BUDGET = float(os.environ.get("HARBOR_VOICE_JEV_BUDGET", "0.6"))

# HOW LONG AN IDLE CONNECTION IS TRUSTED. V10 says one long-lived connection from the
# gateway, and the whole point is the warm call (about 350 ms) against the fresh one (about
# 850 ms from the Mac). A connection the far end has quietly closed costs a retry inside
# the same budget, so past this age the next call opens a new one on purpose rather than
# discovering a dead socket.
JEV_CONNECTION_MAX_AGE = float(os.environ.get("HARBOR_VOICE_JEV_CONN_AGE", "240"))

# THE SWITCH, IN TWO HALVES, and `keel/judges.py` holds the whole reasoning. The shipped
# defaults are `[voice.judges]` in keel.toml, which is the one config line V10 asked for;
# the live override is a file under state/ that only `keel voice judge` writes, because
# keel.toml is tracked and the box's checkout is the one the Mac pushes to. Both are read
# on their mtime at the start of each turn, so a flip needs no restart and no deploy.
#
# This is THE ONE PLACE the gateway reads keel.toml, against the rule that its environment
# is its configuration. A plist is a snapshot and a snapshot cannot carry a flip that takes
# effect without a restart. Stated in docs/atlas/50-talker-and-voice.md as the exception it
# is, with the reason, so nobody later reads the old rule as still absolute.
#
# WHICH FILE IS NOT DECIDED HERE (c-711). `keel/configpath.py` is the one answer every Keel
# process gives: `KEEL_CONFIG` when the service file carries it (`keel voice install` writes
# it for an install), else the home's own `config.toml`, else its `keel.toml`. The `kb` and
# `keel` this gateway runs inherit the same variable and ask the same function, so the
# judges are read from the file whose board the captures are filed on.
if str(CHECKOUT) not in sys.path:
    sys.path.append(str(CHECKOUT))
from keel import configpath                                            # noqa: E402


# THE PACKS, for the same read as ADAPTERS_DIR (c-722 landing B): a pack's `hearing.json` is
# read where the pack is, and an install's own packs (its work pack among them) are not in
# this checkout. The install's `packs/` first (the install `KEEL_CONFIG` names, as
# `configpath.install_of` reads it), then the checkout's own.
PACK_ROOTS = [home / "packs" for home in (configpath.install_of(os.environ.get("KEEL_CONFIG"), KEEL_HOME),
                                          KEEL_HOME) if home is not None]


def keel_toml(home: Path, env: dict | None = None) -> Path:
    """The toml this gateway reads, for the home it runs against (`configpath.config_path`)."""
    return configpath.config_path(home, env)


KEEL_TOML = keel_toml(KEEL_HOME)
JUDGES_SWITCH = DATA / "judges.json"
JUDGES_LOG = DATA / "judges.jsonl"

# HOW LONG A HELD PARTIAL WAITS before the turn goes ahead anyway. V10: "a held partial
# expires into a normal turn after a few seconds of nothing, so a wrong verdict costs a
# pause, never a lost sentence". The held path is slice 2's to build; the number lives here
# so both sides read one value.
JUDGE_HOLD_SECONDS = float(os.environ.get("HARBOR_VOICE_JUDGE_HOLD", "4.0"))

# Measured 2026-09-04 over 24 calls: a whole answer takes 1.47 s median to come back and
# its first sentence alone takes 0.53 s. That is the same shape finding 16 found in
# kokoro, where handing the synthesiser the whole answer cost 1.14 s of silence on every
# turn, so the chain splits and this is the per-call ceiling rather than a per-answer
# one. Past it the sentence is spoken by the next engine down, which is local.
GOOGLE_TTS_TIMEOUT = float(os.environ.get("HARBOR_VOICE_GOOGLE_TIMEOUT", "8.0"))

# HOW LONG A DEMOTED ENGINE STAYS DEMOTED. A quota stop lasts until the month turns and
# a network blip lasts seconds, and the code cannot tell which it is holding, so it
# treats both the same way: stop asking for five minutes, then try once more. The cost
# of being wrong in the quota direction is one refused call every five minutes, which
# comes back fast and falls straight through to kokoro; the cost of being wrong in the
# other direction would be a local voice for the rest of the day after one dropped
# packet. /voice/health names the demoted engine, why, and when it is next tried.
TTS_RETRY_AFTER = float(os.environ.get("HARBOR_VOICE_TTS_RETRY_AFTER", "300"))

# HOW LONG A LOCAL FALLBACK VOICE MAY SIT UNUSED BEFORE IT IS LET GO. Only an engine that
# declares `unload_after` is dropped (kokoro-onnx: 556 MB on a 12 GB box, for a voice that
# speaks only when Google fails), and the next failure builds it again lazily. Ten
# minutes, <install>/history/docs/vps-plan.md "Limits on the box". Zero keeps every engine for life.
TTS_UNLOAD_AFTER = float(os.environ.get("HARBOR_VOICE_TTS_UNLOAD_AFTER", "600"))

# --------------------------------------------------------------------------- #
# WHICH SYNTHESISER SPEAKS, AND WHO IS SPEAKING (V7, card c-312; V8, card c-316).
#
# TWO SEPARATE QUESTIONS, and keeping them separate is the whole point of this section.
# The ENGINE is his, chosen per session on the voice page and carried on the `end`
# message beside the mode. The SPEAKER is the gateway's: Harbor, or the house he is
# connected to, which is a different voice on every engine in the chain and changes
# between turns. Because they are separate, V8 added a column to the table below and
# changed no call site.
#
# THE PAGE NAMES A FAMILY, NOT A BACKEND. "kokoro" is the torch build on the Mac and the
# ONNX build on the box, so a control that named the backend would be a different control
# per machine. `resolve_engine` maps his word onto whatever this machine's chain has,
# which is what makes the control host-independent (V7's last line).
# --------------------------------------------------------------------------- #

ENGINE_GOOGLE = "google"
ENGINE_KOKORO = "kokoro"
# family -> the backends in TTS_BACKENDS that count as that family, best first.
ENGINE_FAMILIES = {
    ENGINE_GOOGLE: ("google",),
    ENGINE_KOKORO: ("kokoro", "kokoro-onnx"),
}

# WHO IS SPEAKING: THE RECORD OF WHOSE WORDS THEY ARE, and since V13 that is all it is.
# The page's header and the transcript still have to say which house said a thing, so the
# role travels on every turn and every `speak` call exactly as it did.
#
# IT NO LONGER PICKS A VOICE (V13, 2026-09-21, and it reverses V8's second voice). In his
# words: "the way we should play this out is Harbor entering and exiting a house so that
# we keep the same Harbor voice; the usual flow: hey can you enter this house, I need to
# check some things; Harbor enters, the house responds, but it feels like Harbor is the
# one speaking; similarly it exits." V8 gave a connected house `en-IN-Chirp3-HD-Leda` so
# that "who am I talking to right now" was answerable by ear; what he found when he lived
# with it is that a second voice reads as a second PRODUCT, and that the thing he is
# talking to should stay the thing he is talking to wherever it goes. The lines say where
# he is instead ("Entering card 272", "Leaving card 272"), which is the same fact in words
# that cannot be mistaken for a different assistant.
#
# `voice_speaker` BELOW IS THE WHOLE OF THAT DECISION, in one function, so the two
# questions ("whose words" and "whose voice") are separated by something a reader can find
# rather than by a convention everybody has to remember.
SPEAKER_HARBOR = "harbor"
SPEAKER_HOUSE = "house"
SPEAKERS = (SPEAKER_HARBOR, SPEAKER_HOUSE)


def voice_speaker(speaker: str = SPEAKER_HARBOR) -> str:
    """Whose VOICE says a line, whatever the record says about whose words they are.

    Harbor's, always (V13). It takes the speaker and ignores it rather than not taking one,
    because every call site genuinely has a speaker to hand and the argument is what makes
    the discard visible at each of them: a reader following `turn.speaker` down to the
    synthesiser arrives here and is told, once, that this is where the two part company.
    """
    return SPEAKER_HARBOR

# WHICH ENGINE THE PAGE OPENS WITH, before he has touched the control (after that the page
# remembers his choice, exactly as it remembers the mode). Google, because it is the voice
# he chose on 2026-09-04 from rendered samples. `keel voice install` writes keel.toml's
# `[voice] engine_default` into the agent's environment under this name.
ENGINE_DEFAULT = str(os.environ.get("HARBOR_VOICE_ENGINE_DEFAULT")
                     or ENGINE_GOOGLE).strip().lower()


def engine_family(backend: str) -> str:
    """Which family a built backend belongs to, or "" for one that is nobody's choice
    (`browser` and `elevenlabs` are floors and extras, not things he picks)."""
    for family, names in ENGINE_FAMILIES.items():
        if backend in names:
            return family
    return ""


def resolve_engine(choice, chain=None) -> str:
    """His word ("google", "kokoro") as a backend name this machine's chain actually has.

    Empty when he named nothing, named something this build does not know, or named a
    family this machine cannot speak with. Every caller treats empty as "no preference",
    so an unhonourable choice degrades to the configured order and never to silence.
    """
    family = str(choice or "").strip().lower()
    names = ENGINE_FAMILIES.get(family)
    if not names:
        return ""
    chain = list(TTS_CHAIN if chain is None else chain)
    for name in chain:
        if name.strip() in names:
            return name.strip()
    return ""


# THE VOICE TABLE: backend -> the voice id to synthesise with. THIS IS THE ONE READER OF
# THE GLOBALS ABOVE from here on, which is what the brief for c-312 asked for: TTSChain
# takes the engine per call rather than reading GOOGLE_TTS_VOICE and TTS_VOICE at
# construction and being that voice forever.
#
# IT HAD A SECOND COLUMN AND V13 TOOK IT OUT. V8 (c-316) gave a house its own voice per
# engine (`Leda` on Google, `af_nova` on Kokoro, `Veena` on `say`), and the three settings
# behind them are gone with it. What is left is one voice per engine, which is what
# "Harbor enters and leaves a house" means at the synthesiser: there is one speaker in
# this conversation and it goes places. `speaker` is still taken, and it is still
# DISCARDED through `voice_speaker` rather than ignored here, so the one place the
# decision lives is the one place a reader looks.
#
# `browser` AND `elevenlabs` HAVE NO VOICE HERE, and that is unchanged: the page speaks
# with its own synthesiser on the floor, and the ElevenLabs backend raises unconditionally
# and has never spoken a word on either machine. The floor is told `voice_speaker`'s
# answer on the `speak` message, so its own "a house gets a second system voice" branch
# can never fire, and the page needed no change for that.
def voice_id(backend: str, speaker: str = SPEAKER_HARBOR) -> str:
    """The voice id `backend` should synthesise with. One voice per engine (V13).

    `speaker` is taken and resolved through `voice_speaker`, which answers Harbor for all
    of them. Keeping the parameter is not politeness to the callers: the cache key is
    built from (text, voice) at the render side and at the playback side, and a signature
    that lost the speaker would let those two drift apart the day a second voice is ever
    wanted again.
    """
    table = {
        "google": {SPEAKER_HARBOR: GOOGLE_TTS_VOICE},
        "kokoro": {SPEAKER_HARBOR: TTS_VOICE},
        "kokoro-onnx": {SPEAKER_HARBOR: TTS_VOICE},
        "say": {SPEAKER_HARBOR: TTS_SAY_VOICE},
    }.get(str(backend or "").strip(), {})
    if not table:
        return ""                       # browser and elevenlabs have no voice of their own
    return table[voice_speaker(speaker)]


# WHAT THE CONTROL MAY HONESTLY SAY ABOUT EACH ENGINE, and the reason this is a table
# rather than a word in app.js. THE BOX BENCHMARK OF 2026-09-18: kokoro-onnx takes 4.97 s
# for 12 words and 14.8 s for 44 on the box's two Neoverse-N1 cores, with no streaming
# advantage. So V7's "Kokoro is faster" is true on Apple silicon and FALSE here, and a
# control that promised speed on this machine would be selling something it is not.
def kokoro_note(platform: str = "") -> str:
    """Taken as an argument so both branches can be read by a test on either machine."""
    if (platform or sys.platform) == "darwin":
        return "local, and faster than the cloud round trip"
    return "local, about real time on this machine: 4.97 s for 12 words"


ENGINE_NOTES = {
    ENGINE_GOOGLE: "cloud, metered against the free allowance",
    ENGINE_KOKORO: kokoro_note(),
}
ENGINE_LABELS = {ENGINE_GOOGLE: "Google", ENGINE_KOKORO: "Kokoro"}


def engines_for_page(chain=None) -> list[dict]:
    """The engines this machine can actually offer, in the configured chain's own order.

    A control that offered Google on a box with no key, or Kokoro on a machine with no
    local model in its chain, would be a control that does nothing. The page hides it
    entirely when this is shorter than two.
    """
    chain = list(TTS_CHAIN if chain is None else chain)
    out, seen = [], set()
    for name in chain:
        family = engine_family(name.strip())
        if not family or family in seen:
            continue
        seen.add(family)
        out.append({"id": family, "label": ENGINE_LABELS.get(family, family),
                    "note": ENGINE_NOTES.get(family, ""), "backend": name.strip()})
    return out

# THE FREE ALLOWANCE, so the count on /voice/health means something without a second
# lookup. Google's free tier for Chirp 3 HD is 1,000,000 characters a month; past it the
# calls are billed. Nothing here enforces it: the meter counts and reports, and a real
# quota stop arrives as a refused call that the chain degrades past. A gateway that
# stopped speaking because it had counted to a number would be inventing an outage.
TTS_FREE_ALLOWANCE = int(os.environ.get("HARBOR_VOICE_TTS_ALLOWANCE", "1000000"))

# Up from the phone. 16 kHz mono PCM16 is what the STT wants and it is half the bytes of
# 24 kHz for no accuracy the model can use.
MIC_RATE = 16000

# --------------------------------------------------------------------------- #
# End of utterance (V1), and the corpus that tunes it.
# --------------------------------------------------------------------------- #

# THE DETECTOR, and `off` is the one line back to the twenty second backstop. `auto`
# finds Silero through sherpa-onnx if the wheel and the model are both here and degrades
# to vad.NullVAD if either is missing, so the Mac keeps today's behaviour until its venv
# is next built. Written into the unit by `keel voice install` from `[voice] vad`.
VAD_BACKEND = os.environ.get("HARBOR_VOICE_VAD", "auto")

# 629 KB, from sherpa-onnx's own `asr-models` release, kept beside the Parakeet models and
# checked by sha256.
VAD_MODEL = os.environ.get("HARBOR_VOICE_VAD_MODEL", "silero_vad.onnx")

# HOW LONG A SILENCE MEANS HE HAS FINISHED, and 2.5 s is NOT V1's 700 ms target. It is
# the number shipped on day one (his call, c-311's plan gate): 3.5x the target, chosen
# from the safe side, so that no plausible measurement of the recorded corpus could move
# it UP. Within-turn pauses in ordinary speech sit well under half a second. It replaces
# a 20 second backstop with about 3 seconds, and `bin/keel-voice-vad-measure` over the
# corpus is what lowers it toward 700 ms once there is evidence about how he pauses.
#
# 2.0 s SINCE 2026-09-24 (lane H, H6), approved on the measured corpus: a plain 2.0 s cut him
# mid-sentence 2 times of 27, the two-stage rule 11 of 32. It is `[voice] vad_hangover` in
# keel.toml, carried here by `keel voice install`; this default is for a unit written before
# that key existed.
VAD_HANGOVER = float(os.environ.get("HARBOR_VOICE_VAD_HANGOVER", "2.0"))

# HOW MUCH REAL SPEECH BEFORE A SILENCE COUNTS. Without this a cough or the first frames
# of room noise arm the hangover and end a turn nobody has spoken into, which the gateway
# answers with "nothing was heard".
VAD_MIN_SPEECH = float(os.environ.get("HARBOR_VOICE_VAD_MIN_SPEECH", "0.3"))

# Silero's own two: the probability above which a window is speech, and the window it
# insists on (512 samples at 16 kHz, 32 ms). Neither is a number to tune casually.
VAD_THRESHOLD = float(os.environ.get("HARBOR_VOICE_VAD_THRESHOLD", "0.5"))
VAD_WINDOW = 512

# --------------------------------------------------------------------------- #
# The conversation (V2, V3).
# --------------------------------------------------------------------------- #

# HOW LONG A LISTEN THAT HEARS NOTHING AT ALL STAYS OPEN. The hangover above ends an
# utterance he actually spoke; this ends one he never started, which the hangover cannot
# see because it never arms without `VAD_MIN_SPEECH` of real speech first. Twenty
# seconds is today's page backstop moved to the side that has the audio, so the number
# he is used to is the number that ships.
VAD_QUIET = float(os.environ.get("HARBOR_VOICE_VAD_QUIET", "20"))

# HOW MANY OF THOSE IN A ROW END A CONVERSATION. Three times twenty seconds is V2's
# "a minute of silence ends it", expressed as ONE number rather than two that have to
# agree with each other. It is also the runaway guard: a page that reopened a microphone
# forever in his pocket is the worst failure this slice could have, and this is the cap
# that makes that impossible rather than unlikely.
CONVERSATION_QUIET_LIMIT = int(
    os.environ.get("HARBOR_VOICE_CONVERSATION_QUIET_LIMIT", "3"))

# THE CORPUS. Off in this file, ON in the unit for the two or three days he agreed to at
# c-277's plan gate, and turned off again by the follow-up card that writes the measured
# numbers down. It is his voice: never backed up (bin/keel-backup prunes this directory
# the way it prunes the TTS cache), capped, expired, and visible on /voice/health.
RECORD_ENABLED = (os.environ.get("HARBOR_VOICE_RECORD", "0").strip().lower()
                  not in ("", "0", "no", "off", "false"))
RECORD_DIR = Path(os.environ.get("HARBOR_VOICE_RECORD_DIR") or (DATA / "pcm"))
RECORD_KEEP_DAYS = float(os.environ.get("HARBOR_VOICE_RECORD_KEEP_DAYS", "14"))
RECORD_MAX_MB = float(os.environ.get("HARBOR_VOICE_RECORD_MAX_MB", "500"))

# --------------------------------------------------------------------------- #
# The turn machine.
# --------------------------------------------------------------------------- #

# From the narration table (plan section 5). Both are "with no change observed", not
# "since the turn started": a turn that is visibly spawning things is not silent.
#
# THE FIRST ONE NO LONGER SPEAKS A TIMER. It used to fire "still working, twelve seconds"
# at this mark, which was said out loud twice on 2026-09-03 and named as wrong: a
# stopwatch read to a person is not narration, it is the opposite of it. What happens at
# this mark now is one cheap question (harbor-session-state, measured at 30 ms) and
# silence unless the answer is `blocked`, which is a real change and worth hearing.
# The number is kept because the question still wants asking at about that point; it is
# no longer a number anybody hears.
NARRATE_ELAPSED_AT = 12.0
# CUT FROM 90 TO 60, 2026-09-15, c-221, at the plan gate. Item 3 moved the decision
# earlier: Harbor now judges at the START of a turn whether it will run long and says so
# in the opening line, so this backstop exists for the turn Harbor called wrong rather
# than as the normal ending. A shorter ceiling is truer to that: he asked for it directly,
# on the reasoning that the upfront prediction should be MADE against this number, not
# against the old 90 s. The two filler repeats above (20 s, 40 s) both land before it.
NARRATE_GIVE_UP_AT = 60.0

# c-229, THE FLAT NUMBER ABOVE IS NOW A FALLBACK, NOT THE WHOLE STORY. Harbor states its
# own estimate at the opener (`bin/keel-voice opening ... --eta SECONDS`), and when it
# does, the give-up mark tracks THAT rather than the fixed 60s. A turn that never sends
# an eta (a "quick" turn, or an older client) keeps NARRATE_GIVE_UP_AT unchanged.
#
# TOLERANCE IS HIS OWN NUMBER, from the plan gate: "if you think you can make it, +/- 10
# seconds of the time limit is also fine, then just keep the other side open." So the
# mark is eta + this, not the instant the estimate passes.
ETA_TOLERANCE = float(os.environ.get("HARBOR_VOICE_ETA_TOLERANCE", "10.0"))

# AN ETA BELOW THIS IS TREATED AS NOT GIVEN, the same as a turn that opened with no
# estimate at all. Without a floor a near-zero eta ("--eta 1") would make the wait
# absurdly short, tighter than the time it takes to even hear the opener.
ETA_GIVE_UP_FLOOR = float(os.environ.get("HARBOR_VOICE_ETA_FLOOR", "15.0"))

# AN ETA ABOVE THIS IS CAPPED, so a wildly high estimate still gives up well inside the
# TURN_MAX_SECONDS narration cutoff below, rather than turning one bad guess into ten
# minutes of silence about whether the promise still holds.
ETA_GIVE_UP_CEILING = float(os.environ.get("HARBOR_VOICE_ETA_CEILING", "180.0"))

# How long a Harbor turn may stay outstanding before the gateway stops waiting for a
# spoken line. Well past the 45 s worst case in the latency table, because the turn is
# not cancelled at this point: it stops being NARRATED. Harbor's answer still lands in
# the transcript if it arrives.
TURN_MAX_SECONDS = 600.0

# The state bus, published at ~15 Hz while there is audio. The contract in
# artifacts/fsa-review/findings.md section 5, kept exactly so any face built against
# ai-visualizer runs against this unmodified.
BUS_HZ = 15
BUS_SAMPLES = 64
BUS_WAVE_FRESH = 0.6      # a waveform younger than this OVERRIDES the state word
BUS_LEVEL_DIVISOR = 3000.0

# How many turns the transcript keeps, and whether it survives a relaunch. The mockup
# left this to the build deliberately ("nothing on this page depends on the answer").
# Kept, because a phone backgrounds an app constantly and losing the last answer to a
# lock screen is the kind of small betrayal that stops something being used.
TRANSCRIPT_KEEP = 40

# --------------------------------------------------------------------------- #
# The wait, narrated from real state: Harbor's own progress, and whether he is there.
# --------------------------------------------------------------------------- #

# HOW LONG THE WAIT MAY GO WITHOUT A SPOKEN WORD BEFORE HARBOR'S OWN PROGRESS SPEAKS,
# or, lacking that, the filler falls back to its own cadence below. Narrower than
# FILLER_REPEAT_EVERY on purpose: Harbor's real narration is preferred over the canned
# repeat and should not have to wait a full filler cycle to be heard. This is the
# number findings.md asked for ("about 4 seconds"), not one probed on a live session,
# and it is one constant to retune once his own recordings replace the generated sets.
PROGRESS_SILENCE_AT = float(os.environ.get("HARBOR_VOICE_PROGRESS_SILENCE", "4.0"))

# HOW MANY TIMES HARBOR'S OWN PROGRESS MAY SPEAK, IN ONE WAIT, AND WHY IT IS NOT
# FILLER_REPEAT_LIMIT. The two used to share one counter, on the reasoning that both
# are "something else spoken during the wait". They compete for the same seconds but
# not for the same trust: the filler is a canned line spoken on a timer whether or not
# anything happened, and real progress is spoken only when Harbor actually called
# `bin/keel-voice progress`, which is self-limiting in a way a timer is not. Sharing
# the budget meant the canned repeat could spend it before Harbor ever got a word in,
# silencing the one thing this feature exists to prefer. Raised by review, 2026-09-07.
# Twenty is generous against the silence gate just above (4 s) and NARRATE_GIVE_UP_AT
# (90 s): past the giveup mark nothing is spoken anyway, so this is a ceiling on a wait
# that has not yet reached it, not a number tuned against a measured maximum.
PROGRESS_REPEAT_LIMIT = int(os.environ.get("HARBOR_VOICE_PROGRESS_REPEAT_MAX", "20"))

# HOW LONG A CLIENT MAY GO WITHOUT A MESSAGE BEFORE IT COUNTS AS GONE RATHER THAN
# BACKGROUNDED. The page pings every 25 s (app.js), so reading "not live" the instant
# a socket drops would call a locked phone absent between pings. Long enough to survive
# one missed ping and some jitter, short enough that a real walk-away reads as gone
# well before the median Harbor wait (findings.md: 16.8 s) ends.
PRESENCE_RECENT_SECONDS = float(os.environ.get("HARBOR_VOICE_PRESENCE_RECENT", "45"))

# --------------------------------------------------------------------------- #
# THE FOUR OPEN QUESTIONS. Not answered by the user. Built as the mockup recommends.
# One constant each; changing an answer is one edit and no restructuring.
# --------------------------------------------------------------------------- #

# OPEN QUESTION 1: where does voice live?
# Built: "own_app". Its own app at /segments/voice/app/, launched from the home screen,
# with a segment card carrying liveness on the dashboard and nothing else changed.
# Rejected on the mockup: "sixth_tab" (drops every tab from 78px to 65px and breaks the
# five-destination budget) and "control_above_bar" (costs 72px of every screen forever
# and puts the microphone and the socket on the dashboard's own page rather than inside
# a segment). Neither is implemented, on purpose: the recommendation is what was built.
Q1_WHERE_VOICE_LIVES = "own_app"

# OPEN QUESTION 2: does the tier show?
# Built: "every_answer". One 11px provenance line under every answer, "ledger, 1.2s" or
# "Harbor, 14s", with the seconds MEASURED per turn rather than fixed. Alternatives:
# "while_waiting" (only during the wait, so an answer scrolled back says nothing about
# where it came from) and "never".
Q2_SHOW_TIER = "every_answer"

# OPEN QUESTION 3: what does a press during speaking do?
# Built: "cut_and_listen". One gesture: it cuts the speech and starts listening in the
# same motion. Alternative: "cut_only", where a first press stops and a second press
# starts listening, which is two deliberate gestures where a conversation wants one.
Q3_PRESS_WHILE_SPEAKING = "cut_and_listen"

# OPEN QUESTION 4: the alert, at rest.
# Built: "static_bar". A bar that is visible the moment the app opens, links out to the
# dashboard, never acts, and is never spoken unless asked. Alternatives: "spoken_once"
# (every turn opens with an interruption) and "none" (the one thing worth knowing while
# walking is the thing the app then hides).
Q4_ALERT_AT_REST = "static_bar"


def flags_for_page() -> dict:
    """What the static page needs to know, so the four answers have ONE home.

    The page is static files under segments/voice/app/ and cannot import this module, so
    the gateway serves these at /voice/flags.js. Copying them into app.js would make the
    promise above ("one edit") false the first time somebody changed one.
    """
    # IMPORTED HERE, NOT AT THE TOP. `verbs` reaches `snapshot`, which reads this
    # module, so a module-level import would be a cycle. This function runs once per
    # page load.
    from . import verbs

    return {
        "whereVoiceLives": Q1_WHERE_VOICE_LIVES,
        "showTier": Q2_SHOW_TIER,
        "pressWhileSpeaking": Q3_PRESS_WHILE_SPEAKING,
        "alertAtRest": Q4_ALERT_AT_REST,
        "transcriptKeep": TRANSCRIPT_KEEP,
        "busSamples": BUS_SAMPLES,
        "micRate": MIC_RATE,
        "ttsRate": TTS_RATE,
        # THE PAGE'S TWO DEFAULTS, served here for the same reason the four answers are:
        # one home. The page remembers his own choice after the first touch.
        "modeDefault": MODE_DEFAULT,
        "captureDefaultSpace": CAPTURE_SPACE_DEFAULT,
        # WHICH SYNTHESISER SPEAKS (V7). The same one home as the two above: the default
        # comes from `[voice] engine_default` and the list is what this machine's chain
        # can honour, so the page never offers an engine that is not there and never
        # invents a claim about one. See ENGINE_NOTES for why the note is served rather
        # than written in app.js.
        "engineDefault": ENGINE_DEFAULT,
        "engines": engines_for_page(),
        # THE CONVERSATION WORDS (V2, V3), SERVED RATHER THAN COPIED. The gateway matches
        # them before a turn is dispatched and the page matches the transcript it is
        # sent, so both need the table and there may only be one of it. Sorted, because
        # a set renders in whatever order it hashes in and a flags file that changes
        # without anything changing is a diff nobody can read.
        "endPhrases": sorted(verbs.END_CONVERSATION),
        "pausePhrases": sorted(verbs.PAUSE_CONVERSATION),
        # HOW MANY LISTENS THAT HEAR NOTHING END A CONVERSATION, and it is here rather
        # than in app.js for the same reason the two defaults above are. Three windows
        # of `VAD_QUIET` is V2's "a minute of silence", as one number rather than two
        # that have to agree.
        "quietLimit": CONVERSATION_QUIET_LIMIT,
    }


def flags_js() -> bytes:
    """The same object as a script the page loads before app.js."""
    return (b"// Generated by voice/harbor_voice/config.py. Do not edit here: the four\n"
            b"// open questions have one home, and it is that file.\n"
            b"window.VOICE_FLAGS = " + json.dumps(flags_for_page(), indent=2).encode()
            + b";\n")
