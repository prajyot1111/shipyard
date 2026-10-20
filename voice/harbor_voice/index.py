"""The trimmed digest a turn carries, and the rule that keeps it small.

WHAT IT IS FOR. Every converse turn carries this with it, which is what removed the two
`kb` reads that used to be the first two tool calls of every turn
(`<install>/history/docs/voice-two-modes.md`, 1.1 item 2): the model answers from the digest instead of
shelling out for the board. It was built for the deleted lookup tier and outlived it,
unchanged, because the rule below is what made it worth having.

    THE RULE: the digest carries names, ids, states and counts. Never values.
    If code will read it to answer, nothing else needs to see it.

WHERE THE REDUCTION ACTUALLY LIVES NOW (2026-09-18, decision V16). `keel/deckdigest.py`,
which is stdlib only, imports nothing from `keel`, and is read by BOTH Harbors: this
package on its 3.12 interpreter, and the `keel deck` verb on Keel's 3.14 one. One
reduction rather than two, so the phone verb and the voice turn can never drift into
describing different boards. This module is the voice side's name for it and the place
the rule is written down; `build`, `as_json` and `measure` are the same functions
`keel deck --digest` prints.

WHAT THE DIGEST CARRIES NOW THE DECK IS ITS SOURCE: both spaces' cards (id, title, stage,
blocked reason) with a per-stage tally beside the capped sample, the needs-you queue, the
running houses, the review cards (title, state, repo and id, never a body; a work pull
request is a card in `shipping` and its state rides on that card's row), the segments and
their headlines, the
drain pill, and the topics each space uses (the refine reads those). It also says
`source`, "deck" or "board", so the framing can say which record it had.

AN UNPLANNED BENEFIT, MEASURED: because it carries the real NAMES, it repairs what the
speech model garbles. Parakeet cannot be vocabulary-biased, so it hears "read me the Q";
ten deliberately mangled transcripts scored 7 of 8 right with zero false positives. The
jargon problem is solved one layer up rather than in the STT, which is the whole reason
the fast speech model can be taken without a vocabulary hit.

THE SIZE, MEASURED. The board-only digest was about 975 bytes (roughly 243 tokens) and
three of its sections were hard-coded empty. Against the live deck on 2026-09-18 (190
unarchived cards, 28 review rows, 13 pull requests, 5 segments) the deck digest measures
about 6.5 KB, roughly 1,600 tokens, with every section capped and every count real.
"""
from __future__ import annotations

import sys
from pathlib import Path

# THE ONE IMPORT THAT CROSSES THE INTERPRETER BOUNDARY, and it is one file deep on
# purpose. `keel/deckdigest.py` imports nothing from `keel` and nothing outside the
# standard library, so importing it from this 3.12 process pulls in no 3.14 syntax and no
# engine state. The dependency runs one way only: `keel/` still never imports this
# package, which is what `keel/voice.py`'s own docstring promises.
#
# IT IS THE CHECKOUT THIS FILE IS IN, NOT `config.KEEL_HOME`. KEEL_HOME says where the
# board and the state live and a test points it at a throwaway directory; the reduction
# has to be the one that belongs to THIS code, or a worktree's selftest would exercise
# the main checkout's copy and pass on code it is not running.
CHECKOUT = Path(__file__).resolve().parents[2]
if str(CHECKOUT) not in sys.path:
    sys.path.append(str(CHECKOUT))

from keel import deckdigest                                             # noqa: E402

TITLE_CHARS = deckdigest.TITLE_CHARS
QUEUE_TOP = deckdigest.QUEUE_TOP
CARD_ROWS = deckdigest.CARD_ROWS
REVIEW_ROWS = deckdigest.REVIEW_ROWS

build = deckdigest.build
as_json = deckdigest.as_json
measure = deckdigest.measure
