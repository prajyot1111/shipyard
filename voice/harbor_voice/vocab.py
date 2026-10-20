"""The vocabulary this setup uses, harvested rather than typed.

c-221, item 5. `etc/dictation-vocabulary.md` (and its work-side half, kept behind
whichever `adapters/<employer>/dictation-vocabulary.md` is currently installed) has
been a hand-typed list since 2026-08-01: someone read the two spaces once and wrote
down what they saw. Segments
appear, cards are created hourly, people join, so a hand-written list is stale the week
it lands. This module reads the same live board document voice already polls
(snapshot.board_doc, the reading snapshot.py keeps warm) and pulls out what it can: Harbor's
own product vocabulary never changes so it is still a fixed list, but everything that
DOES change (segment names, room keys, room members, running dispatches) is read off
the record rather than remembered by a person. Repo and branch vocabulary was tried and
removed: voice has no repository, on purpose (`bin/keel-voice-selftest`'s authority
section greps this whole package for the version-control tool's own name followed by a
space, and fails if it finds one), so nothing here ever shells out to it.

WHAT THIS DOES NOT DO, AND WHY. speech.py already says it plainly: Parakeet cannot be
vocabulary-biased at all, so nothing this module produces feeds the speech model. The
board digest (index.py) already puts the live names in front of the model that reads the
sentence, and it was already dynamic before this file existed; this module does not touch
it. What this
module actually feeds is the STATIC reference file a person would read to know "what
does this setup call things", the same role etc/dictation-vocabulary.md has held since
it was written for a different speech engine, updated by a command instead of by hand.

THE SCOPE QUESTION WAS THE USER'S, NOT THIS MODULE'S. They chose, at the plan gate, to
include the work side's people, projects and tools alongside the personal-side and
Harbor's own vocabulary. This module honours that by not filtering anything OUT: it
reads whatever the live document hands it, from either space, exactly the way
`filler.state_vocabulary` already does for the same reason. The custody boundary that
stays untouched is the other one: none of this is ever sent anywhere, spoken, or fed to
a hosted service, and speaking-is-egress governs saying it out loud, which this module
never does.
"""
from __future__ import annotations

import re

# HARBOR'S OWN ENTITIES AND VERBS. Fixed, because this is the product's own vocabulary
# and it does not change the way a segment list or a room roster does. Copied verbatim
# from the card (c-221, item 5) rather than re-derived, since it is exactly the list a
# person would have typed by hand and typing it once here is not the thing this module
# exists to stop.
HARBOR_TERMS = (
    "dispatch", "card", "room", "conductor", "house", "gate", "segment", "drain",
    "bosun", "lavish", "promote", "reap",
)

# HELD BACK ON PURPOSE, carried forward from the hand-typed file this module replaces
# rather than dropped when its prose was. A word ending up in a written, checked-in
# vocabulary file is a different exposure than the same word passing through live state
# for a few seconds, so this list exists precisely because harvesting cannot know
# `etc/dictation-vocabulary.md`'s own documented editorial judgement: no bill-splitting
# vocabulary (money owed between named people), no mail or account identifiers, nothing
# below city level about where he lives. This can only ever be a denylist of things
# already known to be sensitive; it is not a substitute for a person reading the
# generated file before trusting it, and a new category of sensitive content needs a
# person to add it here, the same way the original list needed a person to notice it.
_BLOCKED = frozenset({"splitwise"})

# CARD IDS ARE A SHAPE, NOT A LIST. c-NNN ids number in the hundreds and a new one is
# created hourly, so enumerating them into a vocabulary file would make this the exact
# thing item 5 exists to stop: a list stale the week it lands, except worse, because it
# would also grow without bound. The shape is worth a person knowing; no individual id
# is worth harvesting, so it is prose in the generated file's own header, never a term
# mixed into the comma-joined list (see bin/keel-voice-vocab's `_terms_block`).
CARD_ID_NOTE = "card ids follow the shape c-123 (not enumerated; the shape is the vocabulary)"
# MOST ROOMS ARE KEYED BY THE CARD THEY BELONG TO ("c-221"), so a room key is exactly
# where an individual id would otherwise sneak into the harvest one room at a time,
# defeating CARD_ID_NOTE's whole point the moment this ran against the real live state
# rather than the fixture (measured: it did, before this filter existed).
_CARD_ID_SHAPE = re.compile(r"^c-?\d+$", re.I)


def _identifiers(values: list[str]) -> list[str]:
    """Verbatim structured names (a room key, a dispatch's tmux name), lower-cased and
    deduplicated. No prose here, and deliberately so: a field that only ever holds a
    name (a room key, a segment, a member) is trustworthy by construction, but a queue
    title or a review summary is ordinary written English, and pulling "names" out of
    prose with a regex produces mostly ordinary capitalised words ("Approve", "Audit",
    "Build") rather than names. That was tried, measured against the real live state
    document rather than the fixture, and it was noise: this module would rather under-
    harvest than hand a person a vocabulary file half full of verbs. Item 5's own scope
    names segments, card ids, repo/branch vocabulary and personal-side NAMES, and every
    one of those lives in a structured field already."""
    seen: dict[str, None] = {}
    for v in values:
        v = str(v or "").strip()
        if v and v.lower() not in _BLOCKED and not _CARD_ID_SHAPE.match(v):
            seen.setdefault(v.lower(), None)
    return sorted(seen)


def harvest(doc: dict) -> dict:
    """Categorised terms, read off the live document. Never filtered by space: that
    choice belongs to whoever calls this, at the plan gate rather than in code."""
    segments = [str(s.get("name") or "") for s in (doc.get("segments") or [])]

    identifiers: list[str] = list(segments)
    for row in (doc.get("running") or []):
        identifiers += [str(row.get(k) or "") for k in ("room", "tmux")]
    for room in (doc.get("rooms") or []):
        identifiers.append(str(room.get("key") or ""))
        identifiers += [str(m.get("name") or "") for m in (room.get("members") or [])]

    return {
        "harbor": list(HARBOR_TERMS),
        "card_id_note": CARD_ID_NOTE,
        # THROUGH THE SAME FILTER AS EVERYTHING ELSE, not a parallel one. This used to
        # be `sorted({s for s in segments if s})`, built straight from the document
        # with no denylist and no case-fold, so a segment matching `_BLOCKED` only by
        # a different capitalisation (or by being the exact spelling nobody thought
        # to test) would have reached the checked-in file untouched. Raised by
        # review: the selftest that was meant to catch this tested a capitalised
        # spelling against a lower-cased denylist and passed for the wrong reason.
        "segments": _identifiers(segments),
        # ONE CATEGORY, NOT TWO. The live document does not reliably tag every row by
        # space (a queue entry does on this machine today; a room member does not), so
        # splitting "names" into personal/work buckets here would be a false precision
        # this module cannot actually deliver. The user's own choice was to include both
        # rather than to filter, which is exactly what one unfiltered category does.
        "names": _identifiers(identifiers),
        # NO REPO OR BRANCH VOCABULARY. It was in the card's own list of what to
        # harvest, and it was built once, calling the version-control tool's own
        # "for-each-ref" directly, and removed: `bin/keel-voice-selftest`'s
        # authority section greps every file under `voice/harbor_voice/` (and the
        # voice CLIs beside it) for that tool's own name followed by a space, and
        # fails if it finds one, because voice reads state and never acts, and a
        # package that shells out to a version-control tool is a package with a
        # repository of its own. That guard is right and this module does not get
        # an exception from it. If branch vocabulary matters enough to rebuild, it
        # has to come from something already in the state document
        # (`doc.get("worktrees")`, not fetched by voice today), never a subprocess.
        "repo": [],
    }
