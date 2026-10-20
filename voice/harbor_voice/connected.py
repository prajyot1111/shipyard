"""Talking to the house that did the work: `keel converse` from the gateway's side (V4, V6).

One module, three calls, and none of them decides anything: `keel converse` owns the hold,
the guards and the record (`keel/converse.py`), so this is the wire and not a second copy
of the rules. The gateway calls it because V6 says both Harbors go through one verb: the
phone Harbor runs the same command, so only the ANSWER enters that conversation and never
the plan.

EVERY FAILURE IS A SENTENCE. A refusal, a timeout, a verb that is not there: each comes
back as `{"ok": False, "say": "..."}` and the turn speaks it, because the caller is holding
a microphone open and what it needs is words. That is the same rule the instant answer
follows, in the other direction: this one never raises.

THE TIMEOUT IS THE TURN'S, NOT THE VERB'S. A connected turn takes as long as the house
takes (about seven seconds for a question, a minute or more when it edits something), and
the give-up narration is the dispatcher's business, not this module's.

THE NARRATION GOES THE OTHER WAY DOWN THE SAME CALL (V5). The verb is told this gateway's
progress inbox and the turn id, and the house's real activity arrives there as sentences
while this call is still blocked. So the module that runs the turn is not also the module
that waits for it: `Dispatcher._watch` reads the inbox, and this stays the wire.

AND SO DOES THE ANSWER, NOW (V12). While he is pinned the verb takes the turn into ONE
kept-alive `claude` that the local `keel serve` owns, and cuts the answer into sentences as
the house writes them: each finished one lands in that same inbox marked `part: true` and
is spoken at once, in the house's voice, while the turn is still running. This module did
not have to change for that, which is the point of it being the wire: the verb's `say` is
still the whole answer, and `_watch` is still the one thing reading the inbox.
"""
from __future__ import annotations

import json
import os
import subprocess

from . import config

# The verb, by absolute path: the gateway's PATH has `bin` on it, but a service that is
# started another way should not fall back to whatever `keel` happens to be first.
KEEL = os.path.join(str(config.KEEL_HOME), "bin", "keel")
VERB = "converse"
# Long enough for a turn that edits a file (the house's own work), short enough that a
# wedged turn cannot hold the pin forever. The gateway gives up speaking long before this.
TURN_TIMEOUT = 600
# A call that only touches the board: no model, so it is quick or it is broken.
BOARD_TIMEOUT = 60
NO_VERB = "I cannot reach the board from here."
BROKE = "That did not come back: {why}"


def _run(argv: list[str], timeout: int) -> dict:
    """`keel converse ... --json`, decoded. Never raises."""
    try:
        done = subprocess.run([KEEL, VERB, *argv, "--json"], capture_output=True, text=True,
                              timeout=timeout, env=dict(os.environ))
    except FileNotFoundError:
        return {"ok": False, "say": NO_VERB}
    except subprocess.TimeoutExpired:
        return {"ok": False, "say": BROKE.format(why="it took too long")}
    except Exception as exc:                                            # noqa: BLE001
        return {"ok": False, "say": BROKE.format(why=exc.__class__.__name__)}
    try:
        payload = json.loads(done.stdout or "{}")
    except ValueError:
        line = (done.stderr or done.stdout or "").strip().splitlines()
        return {"ok": False, "say": BROKE.format(why=line[-1] if line else "no answer")}
    payload.setdefault("ok", False)
    payload.setdefault("say", BROKE.format(why="it said nothing"))
    return payload


def connect(card: str) -> dict:
    """Pin to a card: the hold, no turn, no tokens.

    `{ok, say, card, stage, title, space, held_until}`. The title is what line 2 reads out
    (cut to a few words by `verbs.short_title`) and the space is what the header takes its
    colour from, both of them V8's.
    """
    return _run([card, "--connect"], BOARD_TIMEOUT)


def ask(card: str, said: str, timeout: int = TURN_TIMEOUT, pinned: bool = True,
        turn: str = "", progress: str = "") -> dict:
    """One turn into that card's house; `say` is what to speak back.

    `pinned` is the gateway's ordinary case and it asks one question the gateway cannot
    answer for itself: is the hold this conversation was holding still there? He can stop
    the house from the deck, answer its gate, or walk away long enough for the drain to
    clear the hold, and then the reply carries `unpin` and the pin is dropped.

    `turn` AND `progress` TURN THE NARRATION ON (V5): the verb streams the house's real
    activity into that directory while the turn runs, each line stamped with that id.

    THE CALLER NAMES THE DIRECTORY, and it is the DISPATCHER'S own progress inbox rather
    than `harbormsg.PROGRESS_DIR`. The two are the same path in the running gateway and
    are deliberately not the same under test, and the one that matters is the one the
    watch loop is actually claiming: a narrator writing to a module global that nothing is
    reading would be silent in exactly the place a test would not notice. Passing it also
    keeps the path off `keel/`, which never imports this package.

    With neither, nothing is written and the turn is the plain one it has always been,
    which is the phone Harbor asking its single question.
    """
    argv = [card, said, "--timeout", str(timeout)] + (["--pinned"] if pinned else [])
    if turn and progress:
        argv += ["--progress", str(progress), "--turn", turn]
    return _run(argv, timeout + 30)


def release(card: str) -> dict:
    """Back to Harbor: the hold goes and the house is woken."""
    return _run([card, "--release"], BOARD_TIMEOUT)
