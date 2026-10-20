# The voice front end's regression guards

**This is shipped code, not scaffolding.** Nothing else in this repository can catch a
change that makes the voice front end quietly worse.

| Guard | Question | Command |
|---|---|---|
| the filler attack sets | can the wait be made to state a fact, or promise one? | `bin/keel-voice-filler-score` |
| the picker's held-out set | is the right filler line picked for what he just said? | `bin/keel-voice-corpus score` |

Both need a resident model and minutes, so neither runs on a promotion gate. The parts
that CAN run offline (`filler.guard`, the keyword picker) are asserted in
`bin/keel-voice-selftest`, which runs on every one. That split is the lesson of
2026-09-03: the guard that missed turn 15 was the slow one.

## What used to be here

The routing sets went with the lookup tier, deleted 2026-09-18 (decision D4,
`<install>/history/docs/voice-two-modes.md` section 4): `heldout.json` (set A, 90 utterances),
`heldout_b.json` (B, 106), `heldout_c.json` (C, 120), `heldout_d.json` (D, 120),
`relabel.json`, `index_snapshot.json` (the frozen index they were scored against), and
the four conversation sets `conversations_e/f/g/real.json` (the last of them his own
14-turn session). 436 scored utterances in all, with the two scorers that read them (the router's and
the conversations').

They are in the history of this repository, at `03640ec` and before, which is where to
look if the question ever comes back. Nothing here scores a route any more, because
nothing here decides one.

## The filler's attack set

| File | What it is |
|---|---|
| `attack_filler.json` | Set 1, 90 utterances written to make the filler assert a fact: presuppositions, yes-or-no questions, numbers and names planted in the question, demands for a count, emotional pressure, prompt injection through the microphone, questions about itself, rambling, and things that are not questions. By a model given the filler's JOB and its one rule, and never the guard. **A TUNING SET NOW**: four lines escaped it and were found by reading, and the guard was strengthened against them. |
| `attack_filler_2.json` | Set 2, 90 utterances, written afterwards by a different model that was told which shapes had actually worked and never shown the guard. **A TUNING SET NOW TOO**: it found a class set 1 had not imagined, a fabricated PROMISE ("Got it, won't forget" about his rent), and the guard was strengthened against it. |
| `attack_filler_3.json` | Set 3, 90 utterances, by a third model, pushed hardest at a task mentioned in passing. **The honest number, and `bin/keel-voice-filler-score` defaults to it.** It found the same promise class through a door set 2's rule had left open ("will handle that", "let's fix that"), so the guard has now been tuned against all three and a fourth set is owed. |

## The corpus and the document they are read against

| File | What it is |
|---|---|
| `filler_corpus.json` | The written filler lines themselves, picked by relevance and rendered to audio once by `bin/keel-voice-corpus render`. Not a guard: this is the shipped corpus. |
| `picker_heldout.json` | The picker's held-out set, labelled by topic. The keyword picker is scored on it offline in the selftest; the embedding picker is scored by `bin/keel-voice-corpus score`, which loads a model. |
| `state_snapshot.json` | The frozen board document the guards are run against: the real SHAPE of the document with invented content. Live state would make the numbers move with the day rather than with the change, and the real document carries employer content that has no business in a fixture. |

## Do not tune on the honest set

If set 3's individual failures are ever read while the guard is being edited, it stops
being held out and a set 4 has to be generated. That is not pedantry: the first round of
this work scored a phrase matcher at 100% on fixtures written alongside the patterns and
0% on held-out speech, and the 100% measured nothing but its author's own consistency.

## What counts as a regression

- **Any escape on set 3.** An escape is a filler line that asserts a fact, a count, a
  duration, a status or a promise, and got past `filler.guard`. That is the failure that
  costs trust, because it is spoken in Harbor's own voice with nothing behind it.
- **A written line refused.** Every line of `filler.TABLE` and of the corpus has to pass
  its own guard; one that stops passing means the guard has started eating natural
  speech, which costs a real line for nothing.

## The caveat, stated plainly

The attack sets were written by a model rather than spoken by a person. The user's own
recordings, walking, with background noise, are what would make them real, and they
replace the generated half whenever they arrive. The guard is useful either way: it
catches a change that makes things worse, which is a different and easier question than
how good it is.
