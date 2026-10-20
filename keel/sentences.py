"""Cutting an answer that is still arriving into things that can be SAID (V12).

A kept-alive connected turn streams the house's answer as text deltas (`harness.Conversation`),
and the point of streaming it is that the first sentence is spoken while the rest is still
being written. Something has to decide where one spoken sentence ends, from a buffer that is
always incomplete, without ever handing the synthesiser half a word.

THIS MODULE IS PURE, AND THAT IS THE WHOLE OF ITS TESTABILITY. No process, no inbox, no
clock: text in, finished parts out. Everything about WHEN a part is spoken, and by which
voice, belongs to the gateway; everything about where it is written belongs to
`keel/narration.py`. This decides one question only, and it is the one a person hears
getting wrong.

WHY IT IS NOT "SPLIT ON A FULL STOP". A house answering by voice writes "it took 4.2
seconds", "version 2.1.278", "keel/converse.py", "e.g." and "`make test`", and each of those
has a full stop that ends nothing. A wrong cut is heard twice over: once as a sentence that
stops mid-thought, and again as the next one starting mid-word. So a stop counts only when
whitespace follows it (which is also what makes a stop at the very end of the buffer WAIT
rather than guess, since the next delta may be the "2" of "4.2"), and never inside a code
span or a fenced block, and never after a known abbreviation.

A NEWLINE IS NOT AUTOMATICALLY A BOUNDARY EITHER. Prose that happens to be wrapped would be
cut mid-sentence by that rule. What does end a part is a line that is blank, a list item, a
heading, or a line ending in a colon: those are the shapes a house's answer actually takes
when it is not one paragraph, and each of them is read aloud as its own breath.

AND NOTHING IS EVER LONGER THAN `MAX_CHARS`. A model that writes one enormous sentence must
not hold the voice silent to the end of it. Past the cap the part is cut at the last space,
so the cut falls between words and every word still reaches him.

A FENCED CODE BLOCK IS NEVER SPOKEN AND NEVER CAPPED (review round 2). The first cut of
this module let the cap fire inside a fence, which split a block at a space and read half
of it out loud; and even whole, a block read aloud is unbearable. So a fence leaves as its
own `fence` EVENT carrying the info string and the raw body, with one short spoken line in
its place (`FENCE_SAID`), at most once per answer. The event is deliberately generic: it is
the hook `<install>/history/docs/blackboard.md` will use, where a fence whose lang is `board` is something to
draw rather than something to say. Nothing downstream speaks it today.

SO `feed` AND `flush` ANSWER WITH EVENTS RATHER THAN STRINGS: `{"type": "part", "text"}`
and `{"type": "fence", "lang", "body"}`, which is the same shape they travel in over the
wire (`keel/housetier.py`).
"""

import hashlib
import re

# THE CAP, in characters of cleaned text. About two spoken sentences: long enough that an
# ordinary answer is never chopped, short enough that a run-on paragraph still starts being
# spoken within a couple of seconds of its first words.
MAX_CHARS = 200

# A stop that ends nothing. Lowercased and compared whole, including the trailing dot, so
# "e.g." matches and "eg" cannot.
ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "etc.", "vs.", "cf.", "approx.", "no.", "fig.",
    "mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "jr.", "sr.",
    "a.m.", "p.m.", "u.s.", "u.k.",
})
ENDINGS = ".!?"
TICKS = "```"
# THE KINDS OF EVENT THIS MODULE PRODUCES. A `part` is words to be spoken; a `fence` is
# a code block, which is never spoken and travels so that the page (and, next, the
# blackboard) can have it; a `leave` is the house saying it has been asked to end the
# conversation, which is not words at all.
PART = "part"
FENCE = "fence"
LEAVE = "leave"
# WHAT IS SAID IN A CODE BLOCK'S PLACE, once per answer however many blocks there are.
# Reading a block aloud is unbearable and reading half of one is worse, so the block leaves
# as its own event and this one sentence stands in for it. Written to the same budget as
# `keel/narration.py`'s lines: plain ASCII, short, no identifier, nothing to mishear.
FENCE_SAID = "There is a code block in my answer, it is on the page."
# THE ONE LANGUAGE THAT IS NOT CODE. A fence marked `board` is not something to show him,
# it is something to DRAW: its body is the blackboard's line language and `keel/converse.py`
# pushes it to the card's board as the fence closes (K3, K10 in `<install>/history/docs/blackboard.md`). It is
# a fence and not a verb because a house in a voice conversation has no shell it can run a
# command in mid-sentence, and because a block it is already writing costs it nothing.
BOARD_LANG = "board"
# THE CUTTER SAYS NOTHING ABOUT A DRAWING (C1, 2026-09-23). It used to speak "I have put
# that on the board." the moment a board fence CLOSED, before anybody knew whether the push
# landed, so a refused push was still announced as drawn. The line he hears is built from
# the push REPORT now (`keel/boardpen.py`), which is the only thing that knows, and so is
# N7's rule that nothing after a drawing is spoken: only a block that REPORTED ends speech
# (review F7), and whether it did is the pen's to know, not the cutter's.

# THE HOUSE'S OWN WAY OUT (2026-09-21). Inside c-302 he asked the house to leave and it
# answered "I can't end my own session, tap Stop on the deck", which was true: a house can
# say anything and end nothing. `prompts.SPOKEN` now asks for one short goodbye ending in
# this token, and it travels the only way a house's words travel, which is the answer.
#
# SO IT IS HELD BACK EXACTLY AS A FENCE IS, and for the same reason: read aloud it is
# gibberish, however it got into the answer. It is stripped by SHAPE wherever it sits and
# acted on only at the very END, which is the c-419 connect directive's rule and is what
# lets an answer that QUOTES the form ("you would end with <<keel-leave>>") be an ordinary
# answer rather than a goodbye.
LEAVE_MARK = "keel-leave"
# WHAT IS NEVER SPOKEN: anything of that shape, wherever it sits.
LEAVE_SHAPE = re.compile(r"<<[^<>\n]{0,80}?" + LEAVE_MARK + r"[^<>\n]{0,80}?>>", re.I)
# WHAT ACTUALLY ENDS THE CONVERSATION: the bare directive, with nothing after it, not even
# a full stop. There is no key on this one and there does not need to be: only the house
# he is already talking to can produce it, and the worst a stray one can do is end a
# conversation he can reopen with a sentence. The connect directive moves him somewhere he
# did not ask to be, which is why that one is keyed.
LEAVE_AT_END = re.compile(r"<<\s*" + LEAVE_MARK + r"\s*>>\s*\Z", re.I)

# ----- what a part looks like once the markdown is off it -----

FENCE_LINE = re.compile(r"^[ \t]*```[^\n]*$", re.M)
QUOTE = re.compile(r"^[ \t]*>[ \t]?", re.M)
BULLET = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", re.M)
HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.M)
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
STARS = re.compile(r"\*+")
UNDERLINES = re.compile(r"__")


def clean(text: str) -> str:
    """One part, as it should be heard: no markdown, whitespace collapsed.

    THE WHITESPACE HALF IS THE SAME RULE THE FINAL ANSWER HAS ALWAYS HAD
    (`harness.turn_answer` collapses the answer to one line), because the two are the same
    words and a second rule would make them differ by accident. The markdown half is added
    here: `prompts.converse` asks for plain words, but a house that reaches for a bullet or
    a bold run would otherwise have its asterisks and backticks read out loud, one syllable
    each. `turn_answer` is left as it was, because the card's own record of the exchange is
    read with the eyes and markdown does no harm there.
    """
    out = str(text or "")
    out = FENCE_LINE.sub(" ", out)
    out = LINK.sub(r"\1", out)
    out = QUOTE.sub("", out)
    out = HEADING.sub("", out)
    out = BULLET.sub("", out)
    out = out.replace("`", "")
    out = UNDERLINES.sub("", out)
    out = STARS.sub("", out)
    return " ".join(out.split())


# ----- where one part ends -----

def is_fence(line: str) -> bool:
    return line.strip().startswith(TICKS)


def fence_lang(line: str) -> str:
    """The info string of an opening fence: `python` out of ```` ```python ````."""
    return line.strip()[len(TICKS):].strip().split()[0] if line.strip()[len(TICKS):].strip() else ""


def strip_fences(body: str) -> str:
    """A block's body with every fence MARK taken out of it, wherever one survived.

    THE b-003 BUG, at its root. A turn whose last delta ended with the closing ``` and no
    newline left that ``` on `Cutter.rest`, and `flush` appends `rest` to the body it is
    closing, so the streamed reading of one block carried a trailing "```" that the pass
    over the finished text did not. The pen compared the raw bodies, saw two different
    strings, and drew the same six ops onto b-003 twice, 6 ms apart, with `'```' is not an
    op` in the skipped log to show where the difference was.

    So a body leaves here with no fence marks in it, from either reading. It costs a line
    that a board block could never legally hold anyway: ``` is not an op in the board
    grammar, and a code block's body cannot contain one, because the first one closes it.
    """
    return "".join(line for line in str(body or "").splitlines(keepends=True)
                   if not line.strip().startswith(TICKS))


def ends_part(line: str) -> bool:
    """Does the newline after `line` end a spoken part.

    A blank line, a list item, a heading and a line ending in a colon each do; an ordinary
    line of prose does not, because prose is wrapped and a wrapped sentence cut at the wrap
    is the mistake this rule exists to avoid.
    """
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.endswith(":"):
        return True
    return bool(BULLET.match(line) or HEADING.match(line) or QUOTE.match(line))


def word_before(text: str, index: int) -> str:
    """The token ending at `index` (a stop), lowercased, dots and all."""
    start = index
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "."):
        start -= 1
    return text[start:index + 1].lower()


def stops_in(line: str, *, to_the_end: bool) -> list[int]:
    """Every index in `line` where a sentence really ends.

    `to_the_end` says whether a stop at the last character counts: it does on a line that
    has its newline already (the newline is the whitespace that follows it) and it does not
    on the unfinished tail of the buffer, where the next delta may turn "4." into "4.2".
    """
    found: list[int] = []
    code = False
    for index, char in enumerate(line):
        if char == "`":
            code = not code
            continue
        if code or char not in ENDINGS:
            continue
        after = line[index + 1:index + 2]
        if after:
            if not after.isspace():
                continue
        elif not to_the_end:
            continue
        if char == "." and word_before(line, index) in ABBREVIATIONS:
            continue
        found.append(index)
    return found


class Cutter:
    """One turn's answer, cut into parts as it arrives.

    Held for the length of one connected turn and thrown away with it. `feed` takes a text
    delta and answers with the parts that are now finished (usually none); `flush` takes
    whatever is left when the turn ends, so the last sentence, which has no whitespace after
    it, is never lost. Both answer with CLEANED text, so nothing downstream has to know that
    the house wrote a bullet.
    """

    def __init__(self):
        self.pending = ""      # raw text belonging to the part being built
        self.rest = ""         # the unfinished last line, not yet decided
        self.in_fence = False
        self.fence_lang = ""   # the info string of the block being collected
        self.fence_body = ""   # its raw lines, exactly as written
        # The stand-in line is said once per answer, and the two KINDS are counted apart:
        # an answer with a diagram and a snippet in it has one sentence for each, because
        # they are two different things to tell him.
        self.said_fence = False
        # THE LEAVE DIRECTIVE, IN TWO FACTS. `saw_leave` is that the token was in the
        # answer at all, which is what the strip is; `leave_ends` is that nothing has been
        # said since, which is what the goodbye is. They are two because a quoted directive
        # is stripped and ends nothing, and the only way to know which it was is to see
        # whether more words follow it.
        self.saw_leave = False
        self.leave_ends = False
        self.sent_leave = False

    # -- the two calls -------------------------------------------------- #

    def feed(self, delta: str) -> list[dict]:
        """One text delta; the events it finished, in order."""
        out: list[dict] = []
        self.rest += str(delta or "")
        while "\n" in self.rest:
            line, self.rest = self.rest.split("\n", 1)
            out.extend(self._line(line))
        out.extend(self._tail())
        out.extend(self._capped())
        return out

    def flush(self) -> list[dict]:
        """Whatever is left. Says nothing the second time it is called.

        AN UNCLOSED BLOCK IS STILL A BLOCK. A turn that ends mid-fence (the model stopped,
        the turn was cut) has a body and no closing ticks, and reading its last half-line
        aloud would be the exact mistake the fence rule exists to prevent. It leaves the
        same way a closed one does.
        """
        out = self.feed("")
        if self.in_fence:
            self.fence_body += self.rest
            self.rest = ""
            out.extend(self._close_fence())
        self.pending += self.rest
        self.rest = ""
        out.extend(self._emit())
        # THE GOODBYE IS ONLY KNOWN AT THE END, which is what "it must end the answer"
        # means for something read as it arrives: any part after the token takes it back
        # to being text. Once, because `flush` says nothing the second time it is called.
        if self.saw_leave and self.leave_ends and not self.sent_leave:
            self.sent_leave = True
            out.append({"type": LEAVE})
        return out

    # -- the machinery --------------------------------------------------- #

    def _emit(self) -> list[dict]:
        part, self.pending = clean(self.pending), ""
        if LEAVE_SHAPE.search(part):
            # STRIPPED BY SHAPE, wherever it sits, because the token read aloud is
            # gibberish however it got there. Whether it is a goodbye is the other
            # question, and it is answered by what follows it.
            self.saw_leave = True
            self.leave_ends = not LEAVE_SHAPE.split(part)[-1].strip()
            part = " ".join(LEAVE_SHAPE.sub(" ", part).split())
        elif part and self.saw_leave:
            self.leave_ends = False
        return [{"type": PART, "text": part}] if part else []

    def _close_fence(self) -> list[dict]:
        """End the block being collected: its event, and the stand-in line if it is due.

        A CODE block is on the page for him to read, so it gets `FENCE_SAID`. A `board`
        block gets NO line from here: whether it was drawn is the push's to say, and the
        pen speaks that from the report once the push has answered (C1). Whether the block
        also ends what is spoken (N7) is the pen's call too, because only a block whose push
        REPORTED does (review F7): an empty block or a repeat silences nothing.
        """
        board = self.fence_lang.strip().lower() == BOARD_LANG
        out = [{"type": FENCE, "lang": self.fence_lang,
                "body": strip_fences(self.fence_body)}]
        self.in_fence = False
        self.fence_lang, self.fence_body = "", ""
        if not board and not self.said_fence:
            self.said_fence = True
            out.append({"type": PART, "text": FENCE_SAID})
        return out

    def _line(self, line: str) -> list[dict]:
        """One line that has its newline: the events it finishes."""
        if self.in_fence:
            if is_fence(line):
                return self._close_fence()
            self.fence_body += line + "\n"
            return []
        if is_fence(line):
            # WHATEVER WAS BEING BUILT IS FINISHED FIRST, so the sentence introducing the
            # block ("Here is the fix:") is spoken before the line standing in for it.
            out = self._emit()
            self.in_fence = True
            self.fence_lang = fence_lang(line)
            return out
        out = self._sentences(line, to_the_end=True)
        if ends_part(line):
            out.extend(self._emit())
        else:
            self.pending += " "              # a wrapped line is one sentence, not two
        return out

    def _sentences(self, line: str, *, to_the_end: bool) -> list[str]:
        """Cut `line` at its real sentence ends; the remainder goes on `pending`."""
        out: list[str] = []
        at = 0
        for stop in stops_in(line, to_the_end=to_the_end):
            if stop < at:
                continue
            self.pending += line[at:stop + 1]
            out.extend(self._emit())
            at = stop + 1
        self.pending += line[at:]
        return out

    def _tail(self) -> list[str]:
        """The unfinished last line: its finished sentences only, the rest left waiting."""
        if self.in_fence or not self.rest:
            return []
        stops = stops_in(self.rest, to_the_end=False)
        if not stops:
            return []
        cut = stops[-1] + 1
        line, self.rest = self.rest[:cut], self.rest[cut:]
        return self._sentences(line, to_the_end=True)

    def _capped(self) -> list[dict]:
        """Force a cut when nothing has ended for `MAX_CHARS`, at the last space.

        NEVER INSIDE A FENCE, which is the bug review round 2 found: a block fed in small
        pieces grew past the cap and was cut at a space, so half of it was spoken and the
        rest arrived as a second part. A block has no sentences to find and is not spoken
        at all, so there is nothing for the cap to protect.
        """
        out: list[dict] = []
        while not self.in_fence and len(self.pending) + len(self.rest) > MAX_CHARS:
            whole = self.pending + self.rest
            cut = whole.rfind(" ", 0, MAX_CHARS + 1)
            cut = cut if cut > 0 else MAX_CHARS
            self.pending, self.rest = whole[:cut], whole[cut:].lstrip()
            out.extend(self._emit())
        return out


# ----- the same grammar, read off a finished answer -----

def board_blocks(text: str) -> tuple[str, list[str]]:
    """Take every ```board block out of a whole answer; (what is left, their bodies).

    THE ONE-SHOT PATH'S HALF OF THE SAME RULE. A streamed turn has the cutter, which sees
    each fence close and emits it as an event; a one-shot turn (the phone Harbor's one
    question, a turn typed into the ask box) has no stream at all, only the finished text,
    so its blocks are found here instead. Same language, same closing rule, and a block the
    turn ended in the middle of is still a block.

    Everything that is NOT a board block comes back exactly as it was written, code fences
    and all: a snippet is part of what he was told, and the only lines this takes away are
    the ones that were meant to be drawn rather than said.
    """
    kept: list[str] = []
    bodies: list[str] = []
    opened: str | None = None        # the opening fence line, while a block is open
    body: list[str] = []
    lang = ""
    for line in str(text or "").splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if opened is None:
            if is_fence(bare):
                opened, lang, body = line, fence_lang(bare).strip().lower(), []
            else:
                kept.append(line)
        elif is_fence(bare):
            if lang == BOARD_LANG:
                bodies.append(strip_fences("".join(body)))
            else:
                kept.extend([opened, *body, line])
            opened, lang, body = None, "", []
        else:
            body.append(line)
    if opened is not None:           # an unclosed block is still a block
        if lang == BOARD_LANG:
            bodies.append(strip_fences("".join(body)))
        else:
            kept.extend([opened, *body])
    return "".join(kept), bodies


def lead_of(text) -> str:
    """The answer up to its first ```board block: what a drawing turn may SAY (N7).

    Everything before the opening fence, code blocks and all, exactly as written. With no
    board block the whole text is the lead.
    """
    kept: list[str] = []
    opened = False
    for line in str(text or "").splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if is_fence(bare):
            if not opened and fence_lang(bare).strip().lower() == BOARD_LANG:
                return "".join(kept)
            opened = not opened
        kept.append(line)
    return "".join(kept)


def split_boards(text) -> tuple[list[str], list[str]]:
    """(the prose pieces, the ```board bodies), interleaved: piece 0, body 0, piece 1, ...

    `board_blocks` with the positions kept, because what a drawing turn may say depends on
    WHICH block reported (review F7): the prose after an empty block is still speech.
    """
    pieces, bodies, current, body = [], [], [], []
    opened, lang = False, ""
    for line in str(text or "").splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if not opened:
            if is_fence(bare):
                opened, lang = True, fence_lang(bare).strip().lower()
                if lang == BOARD_LANG:
                    pieces.append("".join(current))
                    current, body = [], []
                    continue
            current.append(line)
        elif is_fence(bare):
            opened = False
            if lang == BOARD_LANG:
                bodies.append(strip_fences("".join(body)))
            else:
                current.append(line)
        elif lang == BOARD_LANG:
            body.append(line)
        else:
            current.append(line)
    if opened and lang == BOARD_LANG:
        bodies.append(strip_fences("".join(body)))
    pieces.append("".join(current))
    return pieces, bodies


def sentences_of(text) -> list[str]:
    """One cleaned text as its sentences, cut by the same rule the cutter uses."""
    line = clean(text)
    out: list[str] = []
    at = 0
    for stop in stops_in(line, to_the_end=True):
        piece = line[at:stop + 1].strip()
        if piece:
            out.append(piece)
        at = stop + 1
    tail = line[at:].strip()
    if tail:
        out.append(tail)
    return out


def first_sentences(text, count: int) -> str:
    """The first `count` sentences of `text`, cleaned: the cap on a drawing turn's lead."""
    return " ".join(sentences_of(text)[:max(0, count)])


# ----- one block, read the same way twice -----

def normalise(text) -> list[str]:
    """One block as the sequence of ops it really is: blanks, comments and fence marks
    gone, whitespace collapsed.

    THIS IS THE COMPARISON that stops one block being drawn twice, and it lives here
    because it is about reading a block rather than about the board. A block written in a
    spoken answer is read TWICE: once by the `Cutter` as the fence closes, once by
    `board_blocks` over the finished text. Comparing the RAW bodies made those two
    different strings the moment one of them carried a stray "```" (which is exactly what
    b-003 did), and the same six ops landed on the board twice, 6 ms apart. Two readings of
    one block normalise to one sequence.

    `keel/boardpen.py` compares these, and `keel/boards.py` holds the same rule under it.
    """
    out = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line or line.startswith("#") or line.startswith(TICKS):
            continue
        out.append(line)
    return out


def signature(text) -> str:
    """A block's normalised ops as one short key, for the store's own duplicate rule."""
    return hashlib.sha256("\n".join(normalise(text)).encode()).hexdigest()[:32]


def leave_directive(text) -> tuple[str, bool]:
    """(the answer with the token taken out, whether the house asked to leave).

    THE ONE-SHOT PATH'S HALF OF THE CUTTER'S RULE, exactly as `board_blocks` is: the phone
    Harbor's single question and a turn typed into the ask box have no stream, so the
    directive comes off the finished text instead. It is also the second pass over a
    STREAMED answer, whose final text carries the token as well, and that costs nothing
    because what it produces is a boolean.

    THE TEXT IS RETURNED UNTOUCHED unless the shape is really in it, so an ordinary answer
    keeps its own whitespace and its own fences, and nothing about the common case changes.
    """
    raw = str(text or "")
    if not LEAVE_SHAPE.search(raw):
        return raw, False
    return LEAVE_SHAPE.sub(" ", raw), bool(LEAVE_AT_END.search(raw))
