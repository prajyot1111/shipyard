"""Harbor's voice front end: the gateway, its two modes, and one instant answer.

WHY THIS IS A PACKAGE UNDER voice/, NOT IN segments/voice/ AND NOT IN keel/.

`segments/voice/` is a SEGMENT, and a segment is static files. That boundary is what
makes adding one unable to break the agent, and the voice service is the first thing
that would have quietly dissolved it: an AudioWorklet, a socket and a model runner are
not static files. So the segment holds only the page that talks to the service.

`keel/` is Python 3.14 and the standard library, on purpose, and this package needs its
own interpreter: kokoro pins Python below 3.13 and parakeet pulls MLX and forty-odd
packages behind it. So the service lives beside `keel/` rather than inside it, runs from
`.venv-voice` (built by `keel voice venv`), and nothing under `keel/` ever imports it;
`bin/keel-voice-gateway` is the one script that does, and it re-execs into the venv first.

The package keeps its Harbor-era name: it is IMPORTED (a dash is not a legal module
name), every script and the selftest know it by this name, and a rename is a change of
its own, worth making when something else in here changes shape.

WHAT IS IN HERE, in the order a turn moves through it:

    hearing.py    what the speech model heard, repaired against observed mistakes
    capture.py    a capture: the words become a card, no model and no wait
    refine.py     the second half of a capture, one turn later, that nobody waits for
    snapshot.py   a warm copy of the board, refreshed off the hot path
    index.py      the digest every turn carries: names, ids, states, counts
    verbs.py      the one code-rendered answer, "what's waiting on me", and its table
    speech.py     transcribe(pcm) -> text and synthesize(text) -> chunks
    dispatcher.py the turn machine, the generation counter, the narration table
    filler.py     who speaks about the WAIT, and the guard that stops it stating a fact
    corpus.py     the written filler lines and their rendered audio
    bus.py        GET /voice/state, one writer, no POST
    harbormsg.py  how a turn reaches Harbor, and how Harbor's answer comes back
    server.py     HTTP plus WebSocket, loopback only, behind the deck's proxy
    config.py     every switch, including the four the mockup left open

THE LOOKUP TIER IS GONE (2026-09-18, decision D4). `router.py`, `args.py`, the thirteen
verbs and the 436 scored fixtures were deleted: converse sends every turn to the model
and capture asks nothing, so there was nothing left for a classifier to decide. What
survives is one exact-phrase answer in verbs.py, read off the board by code.

THE ONE RULE THAT OUTRANKS THE REST: the safe failure is "ask Harbor", and it is the
only failure direction. `kb` refusing, a fold that raises, a sentence that renders empty:
all of them go to the model. Nothing here ever guesses an answer.
"""
