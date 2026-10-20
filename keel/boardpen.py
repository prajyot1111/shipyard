"""The pen: a ```board block written inside an answer, lifted out of it and drawn.

ONE READER FOR BOTH VOICES. A house answering by voice has no shell to run `keel board
push` in mid-sentence, so it writes the lines in a fenced block whose language is `board`
and this pushes them to that card's board (K3, K10, `<install>/history/docs/blackboard.md`). Harbor answers
through the gateway rather than through `keel converse`, and until 2026-09-21 that meant a
fenced block in ITS answer was read as a code block and never drawn: asked to draw on the
board, Harbor filed a card asking somebody else to do it. It uses this same pen now, with a
source of `talker`, which is what "the talker needs to call verbs the same as the house
does, by deterministic reading of the answer" means in code.

THE SOURCE IS THE ONLY DIFFERENCE. A card's pen pushes `--card <id>` as the house and notes
on that card; the talker's pushes `--talker` as the talker and has no card to note on. The
grammar, the caps, the skipped-line rule and the store are the ones `keel board push` has
always used, so a block arriving this way can do nothing its writer could not do from its
own shell. Only the door is new.

WHY IT IS READ TWICE OVER AND STILL LANDS ONCE. On a streamed turn the cutter emits the
fence the moment it CLOSES, which is what puts the picture on the board while he is still
listening; the finished answer then arrives holding that same block, because the answer is
the whole answer. So the bodies already drawn are remembered and the pass over the finished
text only draws what the stream did not, which is also the whole of the one-shot path (the
phone Harbor's question, a turn typed into the ask box).

AND THE COMPARISON IS NORMALISED, WHICH IS THE b-003 FIX. It used to be the RAW body, and
the two readings of one block are not the same string: a turn whose last delta ended with
the closing ``` and no newline leaves that ``` on the cutter's buffer and `flush` appends it
to the body. b-003 has six frames that are three, twice, 6 ms apart, and `'```' is not an
op` in its skipped log. `sentences.strip_fences` takes the mark out on the way, and
`sentences.normalise` makes the comparison about the OPS rather than about the whitespace
around them. The store holds the same rule under this one (`boards.dup_of`), because a cap
only this side holds is one another door gets past.

THE SPOKEN LINE IS BUILT FROM THE REPORT (C1, 2026-09-23). Every push answers with how many
lines were accepted and how many skipped, and why; `draw` turns that into a REPORT (drew,
partial, refused, repeat) and the one line he hears is made from the reports, never before
them. It used to be decided first: the cutter spoke "I have put that on the board." as the
fence closed, and a push that did not raise counted as drawn, so a push where 21 of 27 lines
were refused was announced as drawn (b-003), which is what B19 and B22 exist to forbid. The
model's own claim that it drew is stripped from an answer whose push did not land cleanly,
and the report, with its raw reason, is carried into the next turn so the model repairs it.

N7: A DRAWING IS NEVER EXPLAINED LIVE. An answer holding a board block is spoken as the
prose before the block (two sentences at most, where the whole answer is known) and the
report line; the rest stays in the record (`written`), on the card and in the transcript.

The pass over the finished text still catches a block the stream never delivered to the pen
(`housetalk.Listener._send` swallows anything a listener raises, on purpose), and the block
reaches the board late rather than never. A block the pen DID try is never tried again in
the same answer, whatever came of it: what he heard about it and the repair note the next
turn gets both describe that one attempt.
"""

# ONE IMPORT, AND IT IS STDLIB-ONLY UNDERNEATH. `keel/sentences.py` imports `hashlib` and
# `re` and nothing else, which is what lets the voice gateway import THIS file from its own
# 3.12 interpreter (`voice/harbor_voice/drawing.py`) and get the same reading of an answer
# that a house gets. `keel.boards` is imported LAZILY, inside `store_push`, for exactly that
# reason: the store pulls in the config, the artifact tokens and the segments, and the
# gateway must not hold any of them. It runs the verb instead.
from keel import sentences

# WHAT HE HEARS, built from the reports (C1). The success line says only that it is on the
# board: the narrated walk (N7) does not exist yet, so a line promising one would be a
# claim about something that will not happen.
BOARD_DREW = "I have put that on the board."
BOARD_REFUSED = "I could not put that on the board"
BOARD_PARTIAL = "I put that on the board, but {skipped} of {total} lines did not land: {why}."
DREW_NOTE = "drew on {board} from a board block in that answer: {url}"
NOT_DREW_NOTE = "a board block in that answer could not be drawn: {why}"
# THE RECORD A TROUBLED PUSH LEAVES, which is also what the NEXT turn is told (C1). It
# starts with a fixed mark so `keel/converse.py` can find it again on the card without a
# second store: the card's own events are where it already lives.
REPORT_MARK = "board report: "
REPAIR_NOTE = (REPORT_MARK + "the last board push from your answer {what}, first because: "
               "{why}. If it still matters, draw it again correctly in this answer.")

# The four things a push can have come to.
DREW = "drew"
PARTIAL = "partial"
REFUSED = "refused"
REPEAT = "repeat"
# N7's cap on the prose before a block, where the whole answer is known.
LEAD_SENTENCES = 2
# THE REASON, SAID. A refusal's own words carry paths and identifiers he must not hear read
# out, so the common ones are said in plain words and anything else is said as written,
# minus any path, clipped.
PLAIN_REASONS = (
    ("is not a file on this machine", "a file it names is not on this machine"),
    ("is outside what may go on a board", "a file it names is outside what may go on a board"),
    ("looks like a credential", "a file it names looks like a credential"),
    ("12 nodes", "it would take the board past twelve nodes"),
    ("previous grammar", "part of it was written in the old board grammar"),
    ("frames are gone", "frames are gone from the board grammar"),
    ("text is gone", "text is gone from the board grammar, it is a note now"),
    ("timed out", "the board took too long to answer"),
    ("took too long", "the board took too long to answer"),
)
SAID_REASON_MAX = 120
# A SENTENCE CLAIMING A DRAWING, in the model's own words. Narrow on purpose: it only ever
# runs on an answer whose push did not land cleanly, and it takes whole sentences out.
CLAIM = sentences.re.compile(
    r"\b(?:on|onto|to|in)\s+(?:the|your|a|his|my)\s+board\b"
    r"|\b(?:drew|drawn|sketched)\b", sentences.re.I)
PATHLIKE = sentences.re.compile(r"\S*[/\\]\S*|\S+\.[A-Za-z0-9]{1,5}\b")


def card_source(card_id: str) -> dict:
    return {"kind": "card", "card": str(card_id)}


def talker_source() -> dict:
    return {"kind": "talker", "card": None}


def report_of(result: dict | None = None, error: str = "") -> dict:
    """One push's outcome, from the store's answer or from the refusal it raised.

    A door that does not say `accepted` (an older store, a fake) is taken at its word that
    it drew, which is the reading it has always had.
    """
    if error:
        return {"state": REFUSED, "board": None, "url": None, "accepted": 0, "skipped": 0,
                "reasons": [error]}
    result = result or {}
    skipped = int(result.get("skipped") or 0)
    accepted = result.get("accepted")
    accepted = int(accepted) if accepted is not None else 1
    if result.get("duplicate"):
        state = REPEAT
    elif not skipped:
        state = DREW
    else:
        state = PARTIAL if accepted else REFUSED
    return {"state": state, "board": result.get("board"), "url": result.get("url"),
            "accepted": accepted, "skipped": skipped,
            "reasons": [str(why) for why in result.get("reasons") or []]}


def said_reason(reason: str) -> str:
    """One refusal's reason as it may be SAID: plain words, no path, clipped."""
    text = str(reason or "").splitlines()[0] if reason else ""
    for prefix in ("keel board: ", "nothing was drawn: "):
        text = text.removeprefix(prefix)
    for needle, plain in PLAIN_REASONS:
        if needle in text:
            return plain
    text = " ".join(PATHLIKE.sub("a file", text.replace("`", "")).split())
    return text[:SAID_REASON_MAX].rstrip(" .") or "the board would not take it"


def line_for(report: dict) -> str:
    """The sentence one report earns, or "" when it is not news (a repeat)."""
    state = report["state"]
    why = said_reason((report.get("reasons") or [""])[0])
    if state == DREW:
        return BOARD_DREW
    if state == PARTIAL:
        total = report["accepted"] + report["skipped"]
        return BOARD_PARTIAL.format(skipped=report["skipped"], total=total, why=why)
    if state == REFUSED:
        return f"{BOARD_REFUSED}: {why}."
    return ""


def lines_for(reports: list[dict]) -> list[str]:
    """The sentences a turn's reports earn, in order: the first report's line, and after it
    only the first line saying something did NOT land. Once per answer, as B19 says, and
    never at the price of hiding a failure behind an earlier success."""
    out: list[str] = []
    failed = False
    for report in reports:
        line = line_for(report)
        if not line:
            continue
        trouble = report["state"] in (PARTIAL, REFUSED)
        if not out or (trouble and not failed):
            out.append(line)
            failed = failed or trouble
    return out


def ends_speech(report: dict) -> bool:
    """N7 with review F7: a block ends what is spoken only when its push REPORTED something
    (drawn, in part, or refused); a repeat the store already had is not news."""
    return report["state"] != REPEAT


def strip_claims(text: str) -> str:
    """`text` without any sentence claiming a drawing."""
    return " ".join(one for one in sentences.sentences_of(text) if not CLAIM.search(one))


class BoardPen:
    """One turn's board blocks: pushed as they close, never pushed twice, and REPORTED.

    `source` is a card's or the talker's (`card_source`, `talker_source`). `note` is what
    records the push where somebody will read it later, and it is optional because the
    talker has no card to write on. `push` is the door: the store in this process by
    default, and something else for a caller that is not in this process at all (the voice
    gateway runs the verb, so that the board it writes to is the one its config resolves,
    local or remote, exactly as a house's shell would).
    """

    def __init__(self, cfg, source: dict, *, note=None, push=None, actor: str = "") -> None:
        self.cfg = cfg
        self.source = source
        self.note = note
        self.push = push or self.store_push
        self.actor = actor or ("talker" if source.get("kind") == "talker" else "house")
        self.drawn: list[list[str]] = []   # the op sequences pushed, to push none of them twice
        self.reports: list[dict] = []      # every push's outcome, in order
        self.failed = ""                   # the first refusal's own words
        self.live = False                  # a block was drawn as the stream closed it
        self.silenced = False              # a block REPORTED: nothing after it is spoken (N7)
        self.by_ops: dict = {}             # each block's report, by its normalised ops
        self.said: list[str] = []          # the lines already spoken as it streamed
        self.written = ""                  # the answer as the record keeps it
        self.carried = ""                  # the last turn's report, for this turn's framing
        self.grammar = False               # this turn carries the board's grammar card (C4)

    # -- the door ------------------------------------------------------- #

    def store_push(self, body: str) -> dict:
        """The default: `boards.push` in this process, with the writer as the caller."""
        from keel import boards                 # lazy: see the import note at the top
        talker = self.source.get("kind") == "talker"
        card = self.source.get("card")
        return boards.push(self.cfg, body, card=card, talker=talker, actor=self.actor,
                           caller={"actor": self.actor, "card": card},
                           card_title=boards.card_title(self.cfg, card))

    # -- the calls ------------------------------------------------------ #

    def draw(self, body: str) -> dict | None:
        """Push one block; its report, or None when there was nothing in it or it was a
        block this pen has already pushed."""
        ops = sentences.normalise(body)
        if not ops or ops in self.drawn:
            return None
        # AT MOST ONCE PER ANSWER, WHATEVER THE FIRST ATTEMPT CAME TO (follow-up N1). It was
        # recorded only on success, so a streamed push that raised was pushed again by the
        # pass over the finished text and landed, while he had heard that it could not be
        # drawn and the repair note asked the next turn to draw it again.
        self.drawn.append(ops)
        try:
            result = self.push(body)
        except Exception as error:  # noqa: BLE001 - a board that will not take it is not a lost turn
            why = str(error).splitlines()[0] if str(error) else error.__class__.__name__
            self.failed = self.failed or why
            report = report_of(error=why)
            self.reports.append(report)
            self.by_ops[tuple(ops)] = report
            self.say(NOT_DREW_NOTE.format(why=why))
            return report
        report = report_of(result)
        self.reports.append(report)
        self.by_ops[tuple(ops)] = report
        if report["state"] == REFUSED:
            self.failed = self.failed or (report["reasons"] or ["nothing landed"])[0]
        if report["state"] in (DREW, PARTIAL):
            self.say(DREW_NOTE.format(board=report["board"], url=report["url"]))
        return report

    def on_fence(self, body: str) -> str:
        """A block the STREAM closed: drawn now, and the line it earns, if any, to be spoken
        in its place. "" when there is nothing new to say."""
        self.live = True
        report = self.draw(body)
        if report is None:
            return ""
        if ends_speech(report):
            self.silenced = True
        lines = lines_for(self.reports)
        fresh = lines[len(self.said):]
        self.said.extend(fresh)
        return " ".join(fresh)

    def take(self, raw: str) -> str:
        """The finished answer as he should hear it, with its board blocks drawn.

        The RAW text rather than a collapsed one, because a collapse takes the newlines
        away and a block with its newlines gone is no longer a block. An answer with no
        block is only collapsed. One WITH a block is spoken as its lead and the report
        line (N7); on a streamed turn the lead is not capped, because it has already been
        heard and the gateway checks the final text against what was spoken.
        """
        pieces, bodies = sentences.split_boards(raw)
        if not bodies:
            self.written = " ".join(sentences.clean(raw).split())
            return self.written
        lead, ended = [pieces[0]], False
        for body, after in zip(bodies, pieces[1:]):
            report = self.draw(body) or self.by_ops.get(tuple(sentences.normalise(body)))
            ended = ended or bool(report and ends_speech(report))
            if not ended:
                lead.append(after)
        spoken = sentences.clean("".join(lead))
        if ended and not self.live:
            spoken = sentences.first_sentences(spoken, LEAD_SENTENCES)
        kept = sentences.clean("".join(pieces))
        if self.troubled():
            # THE RECORD IS ALWAYS STRIPPED; SPEECH ONLY WHERE IT HAS NOT BEEN HEARD (F1).
            # On a streamed turn the lead was spoken as it arrived, so taking the claim out
            # of the final text would make the gateway say the whole answer again.
            kept = strip_claims(kept)
            if not self.live:
                spoken = strip_claims(spoken)
        line = " ".join(lines_for(self.reports))
        self.written = f"{kept} {line}".strip()
        return f"{spoken} {line}".strip()

    def troubled(self) -> bool:
        return any(report["state"] in (PARTIAL, REFUSED) for report in self.reports)

    def summary(self) -> dict | None:
        """The turn's reports as one record: the worst state, the counts, the reasons."""
        if not self.reports:
            return None
        order = (REFUSED, PARTIAL, DREW, REPEAT)
        state = min((report["state"] for report in self.reports), key=order.index)
        reasons = [why for report in self.reports for why in report["reasons"]]
        boards = [report["board"] for report in self.reports if report["board"]]
        return {"state": state, "blocks": len(self.reports),
                "accepted": sum(report["accepted"] for report in self.reports),
                "skipped": sum(report["skipped"] for report in self.reports),
                "reasons": reasons[:5], "board": boards[-1] if boards else None}

    def repair_note(self) -> str:
        """What the NEXT turn is told when this one's drawing did not land cleanly, with the
        raw reason, so the model can repair it; "" when it did."""
        summary = self.summary()
        if not summary or summary["state"] not in (PARTIAL, REFUSED):
            return ""
        total = summary["accepted"] + summary["skipped"]
        if summary["skipped"]:
            what = f"had {summary['skipped']} of {total} lines refused"
        else:
            what = "was refused whole and nothing was drawn"
        return REPAIR_NOTE.format(what=what, why=(summary["reasons"] or ["no reason"])[0])

    def say(self, text: str) -> None:
        if self.note is None:
            return
        try:
            self.note(text)
        except Exception:  # noqa: BLE001 - the record is not worth the turn
            return

    @property
    def count(self) -> int:
        """How many blocks reached a board: drawn whole, in part, or already there."""
        return sum(1 for report in self.reports if report["state"] != REFUSED)
