---
name: voice
space: personal
cadence: none
---

# voice

A voice front end onto Harbor. Hold a button, ask, hear the answer.

**This is the first SERVICE segment**, and the distinction is the whole reason it looks
different from every other directory here. A segment is static files, which is what makes
adding one unable to break the agent. A microphone, a socket and a speech model are not
files. So the split is:

- **`segments/voice/` is the segment**, and it is still only files: this note,
  `card.html`, `service.json`, the app under `app/`, and `data/`. Nothing here runs.
- **`bin/harbor-voice-gateway` is the service**, a launchd agent called
  `dev.harbor.voice` on 127.0.0.1:4390 with its own log. Not a tmux session: a service
  needs a restart on crash, a start at login and a log file, and tmux gives none of the
  three.

`service.json` is how the two meet. The view scans `segments/*/service.json` at startup,
adds `/voice/` to what it owns, relays it to port 4390, and splices a websocket upgrade
through to the same place. That is a generic tier with one entry, so the next service
segment is a file rather than a change to the view.

## The two tiers

**The fast tier answers from the record.** Thirteen named verbs, each a function over the
document `GET /api/state` already serves. A local model picks WHICH verb and never writes
a word of the answer, so it cannot be wrong about a fact: the sentence is rendered in
code from the document, and anything quoted out of a queue entry is a string copied by
code. About a second, out loud.

**Everything else is Harbor's.** The utterance is typed into Harbor's pane through
`bin/harbor-message send harbor`. Harbor speaks an immediate one-line opener with
`bin/harbor-voice opening`, then narrates the wait with `bin/harbor-voice progress` if it
runs long, then ends the turn by running `bin/harbor-voice say` exactly once with the real
answer. The wait is otherwise narrated from observed state changes, never filler. Ten to
seventeen seconds.

The boundary is checkable rather than a matter of confidence: no verb, no fast answer.
And the fast tier may state what the document states and may count, but may never derive
a judgement. "Twelve pending, the top one is X" is allowed; "nothing needs you" is not.

## What it may do, in full

Read `/api/state` over loopback, call a local model, write inside this directory, and
type one verified line into Harbor's pane. **Its page reaches `/api/action` for one thing
only:** his answer to one of Bosun's asks, said back and confirmed first, with `voice: true`,
which the deck refuses on any other body (c-523). Otherwise voice reads state and never
acts: a misheard word cannot merge anything, and an approval stays a tap on the dashboard
where the entry is on screen while the thumb moves.

## Where things are

    voice/harbor_voice/        the package: the turn machine, capture, the digest, the bus
    voice/harbor_voice/fixtures/ the filler's attack sets and the written corpus
    bin/keel-voice             opening / say / progress / ask / state / health
    bin/keel-voice-gateway     the service
    bin/keel-voice-selftest    what runs on every `make test`
    bin/keel-voice-filler-score  what to run when the filler's guard changes
    etc/voice-requirements.txt the speech model, in its OWN venv and not Keel's

## Turning it on

    bin/keel voice venv                 build .venv-voice (reaches PyPI, once)
    bin/keel voice install --load       write and load the launchd agent
    bin/keel voice status               is it loaded, is it answering

Then `https://<this machine>/segments/voice/app/` on the phone. It is a home-screen app
rather than a tab on the dashboard: voice is a posture, opened deliberately and put away,
and one tap from the lock screen beats any route inside the dashboard.

## What leaves this machine, and the decision that made it so

**The user decided this on 2026-09-04, with the tradeoff put to them in three named shapes.
It is recorded here because it is the one thing about voice that a reader has to be told
rather than allowed to assume.**

> The voice is `en-IN-Chirp3-HD-Charon` through Google Cloud Text-to-Speech, and **the
> text of every spoken answer is sent there to be turned into audio.**

Plainly, and not softened:

- Not a hash and not a summary: the sentence itself, on every spoken turn.
- **That includes the queue read aloud.** The queue verbs render entries verbatim, and
  the rendered sentence is what is sent.
- **The queue carries work content.** Cards about work items are on it, and they are the
  literal things he is being asked to decide.
- It also includes whatever Harbor writes with `harbor-voice say`, `harbor-voice opening`
  or `harbor-voice progress`, and the briefing. `say` and `opening` are Harbor's own
  composed sentences and are not shape-guarded, trusted the same way the briefing already
  is; only `progress`, which narrates from the live state document rather than from what
  Harbor composed, is filtered before it is spoken.

**It is the same line this project refused hosted ROUTING over** (findings 11 to 15), and
what goes to the synthesiser is more than that index rather than less: the index was built
to carry names and counts and never values, and a finished sentence is values and nothing
else. Two things make it a different decision rather than an inconsistent one, and neither
makes it a smaller one. It is a paid API on a **personal** account with a key restricted
to Text-to-Speech, which is the form finding 15 itself named as the honest one; and the
vendor makes no decision, being handed finished text and handing back audio. The routing
half of this package still cannot reach a vendor at all.

What bounds it: kokoro is directly beneath and the chain degrades at speaking time, so a
failure reaches a local voice rather than silence; a character meter counts every
character sent and reports it on `/voice/health` against the free allowance; the filler is
355 written lines rendered once and never goes out at all; and the key lives in the login
keychain, travels in a header rather than a URL, and is in no file, log, fixture or
commit.

The full decision, with the three shapes he chose between, is
`artifacts/voice-harbor/design-source.md` section 8a. That directory is deliberately not
tracked, which is why the decision is summarised here: it should be readable from the
repository by whoever is approving a change to this segment.

## What it does when a piece is missing

Every one of these is a state it reports rather than a state it crashes in.

| Missing | What happens |
|---|---|
| the speech model | the gateway starts and `/voice/health` says the model is not installed |
| ollama | nothing. The lookup tier was deleted on 2026-09-18, so no model is loaded here and every turn but one goes to Harbor |
| the Google key or the network | the voice degrades per sentence to Kokoro, then `say`, then the page's own synthesiser. Never to silence |
| the rendered filler audio | each line is synthesised when it is spoken instead. Run `bin/keel-voice-corpus render` to make it free again |
| `model2vec` | the filler picks its line by keyword instead, and `/voice/health` says which answered |
| Kokoro | the voice falls down the chain to macOS `say`, which is local and offline |
| the gateway | the card says voice is down, the app disables the control, and the transcript stays |
