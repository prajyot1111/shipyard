# Dictation vocabulary

The neutral half of a speech-to-text vocabulary hint. Feeds OpenSuperWhisper's
**initial prompt** field. Harvested, not hand-typed: run `bin/harbor-voice-vocab
generate` to refresh it from the live state document rather than editing the term
list below by hand (c-221, item 5). Everything else on this page is prose a person
still owns.

## Important: which engine this works on

`initialPrompt` is wired only into the Whisper engine (`Whis/`, `Engines/WhisperEngine.swift`).
`Engines/FluidAudioEngine.swift`, which drives Parakeet, has no prompt, vocab, hint or
bias parameter. **On Parakeet v2 this text is accepted and silently ignored.**

Real keyword boosting is tracked upstream at
<https://github.com/Starmel/OpenSuperWhisper/issues/19>. When that ships, this list
becomes usable on Parakeet too, which is the point of keeping it.

## The prompt

The employer's own product and stack jargon lives in
`adapters/<employer>/dictation-vocabulary.md`, for the reason everything employer
specific does: when the job changes that directory is deleted and this file is still
correct. Paste this half first, then the adapter's, because whisper.cpp caps the prompt
at 224 tokens and truncates from the FRONT, so the terms worth keeping have to sit last.

It is a soft bias, not a dictionary: overstuffing makes the model hallucinate these
words into audio that did not contain them, so this list is capped rather than left to
grow without bound.

<!-- harvested:begin, written by bin/keel-voice-vocab, do not hand-edit -->

**Harvested** (28 terms harvested):

```
dispatch, card, room, conductor, house, gate, segment, drain, bosun, lavish, promote, reap, atlas, cloud-spend, daybook, fathom, instamart, oci, voice, board-truth, contract-drift, room-view-desktop, selftest-audit, smoke-manifest, sweep-dummy, unified-structure, voice-front-end, voice-speak-first
```

card ids follow the shape c-123 (not enumerated; the shape is the vocabulary)

<!-- harvested:end -->

## Held back on purpose

`bin/harbor_voice/vocab.py`'s own denylist excludes Splitwise and the flatmate
bill-splitting vocabulary (money owed between named people). That is a DENYLIST, not a
substitute for reading the generated block above before trusting it: mail and account
identifiers, and anything below city level about where he lives, are excluded only
because nothing in the live state document currently produces them, not because
anything actively filters them. Add a new category to the denylist the moment one shows
up, the same way this line exists because the original hand-typed list once needed a
person to notice one.
