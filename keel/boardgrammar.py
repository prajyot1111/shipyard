"""The board's grammar, said once: its version, the card every copy embeds, and the
translator for the grammar before it (C4, 2026-09-23, card c-425).

WHY THIS EXISTS. A house started before a grammar change draws the OLD grammar. c-302's
house was spawned on 2026-09-19 with the frames grammar in its brief; two days later it
wrote `step "<text>"` and `frame` lines, and 21 of 27 of b-003's lines were refused. The
grammar reached a house and the talker through three copies kept by hand (the house
contract, the talker's memory, the Atlas), and nothing said which version any of them was.

SO THERE IS ONE SOURCE. `grammar_card()` is generated from the parser's own tables in
`keel/boards.py` (the ops, the icons, the marks, the arrows, the caps, the retired ops), and
each copy embeds it in a fenced block whose language is `grammar`. `tests/test_boardgrammar.py`
fails when a copy has drifted, and `python3 -m keel.boardgrammar --write` rewrites every
copy. A house's brief carries it in its board section (`brief_block`, c-603). The card rides
on a voice conversation's first sentence (`prompts.converse`) and on a later one whenever
the card says the house has not been given this version.

AND THE PREVIOUS GRAMMAR IS TRANSLATED, NOT REFUSED. `translate` is asked only about a line
the current grammar refused: a bare `step`, `note` or `text` hangs on the board, a bare
`path` too, a `frame table` or `frame code` opens that attachment on the board, and any other
`frame` line is dropped with a skipped-log row saying so. The store does it
(`boards.plan_push`), so every door gets it once: the pen, the verb, and a push over HTTP.

`keel.boards` is imported lazily inside the functions that need its tables, because
`keel/boards.py` imports this module for the translator.
"""

import re
import sys
from pathlib import Path

# THE VERSION. 1 was the frames grammar (stages one and two, until 2026-09-21); 2 is one
# model with attachments, where the title is the topic. Bump it with any change to what a
# line may say, and the card, every copy and every house's next conversation follow.
GRAMMAR_VERSION = 2
FENCE_LANG = "grammar"
# Every file in the tree that embeds the card, relative to the checkout; `copies` adds the
# talker's drawing entry wherever its memory is read from (c-722, `keel/memoryroot.py`).
COPIES = ("docs/atlas/45-board.md",)
TALKER_COPY = "drawing-on-the-board.md"
ROOT = Path(__file__).resolve().parent.parent

# One line per op, in the order of `boards.OPS`. The test holds these keys to that tuple,
# so a new op cannot land without its line on the card.
SIGNATURES = {
    "board": 'board "<title>"          the TOPIC: a new title starts a new board',
    "group": 'group <id> "<label>"         an id no node has',
    "node": 'node <id> <icon> "<label>" [in <group>] ["<sub>"]',
    "edge": 'edge <a> -> <b> ["<label>"]     also {arrows}',
    "mark": "mark <node> {marks}",
    "note": 'note <node|board> "<text>"',
    "step": 'step <node|board> "<text>"',
    "table": 'table <node|board> "<title>"',
    "cols": "cols A | B | C            after a table",
    "row": "row a | b | c             after its cols",
    "code": 'code <node|board> "<title>"',
    "lang": "lang <name>               after a code",
    "line": 'line "<text>"             after a code, kept exactly',
    "path": 'path <node|board> "<path>" size "<size>" from <who>',
}
# HOW A STEP IS WRITTEN (Z2, lane Z, c-453). The walk is visual and read on demand: he steps
# through it when it suits him, with the step shown as a callout from its lit node. So a step
# has to read on its own, in order, rather than repeat the label the node already shows.
STEP_RULE = ("Write each step as one or two plain sentences meant to be read in order, "
             "like a walk: what happens here and why it matters, not the node's label "
             "said again.")
DRAWING_RULE = ("In a spoken answer the lines go in a fenced block whose language is "
                "`board`. Put one or two sentences before the block; nothing after it is "
                "spoken, and what he hears in its place is what the push reported.")


def grammar_card() -> str:
    """The grammar as one card, generated from the parser's own tables."""
    from keel import boards                     # lazy: `boards` imports this module
    arrows = " and ".join(arrow for arrow in boards.ARROWS if arrow != "->")
    marks = "|".join(boards.MARKS)
    lines = [f"Board grammar v{GRAMMAR_VERSION}: one op per line. A line that does not "
             f"parse is skipped with its reason and the rest still lands.", ""]
    for op in boards.OPS:
        lines.append(SIGNATURES[op].format(arrows=arrows, marks=marks))
    lines += ['board new "<title>"      another board, even under the same title',
              'board rename "<title>"   rename this board, start nothing', "",
              "Attachments (" + ", ".join(boards.ATTACH_KINDS) + ") hang on a node or on "
              "the board; one on a node nobody declared is skipped.",
              f"Icons ({len(boards.ICONS)}; anything else becomes {boards.FALLBACK_ICON}): "
              + ", ".join(boards.ICONS) + ".",
              f"Caps: {boards.MAX_NODES} nodes per board (a push past it draws nothing), "
              f"{boards.MAX_ATTACH} attachments per board, {boards.MAX_TEXT} characters per "
              f"quoted string, {boards.MAX_PUSH_LINES} lines per push.",
              "Gone: " + "; ".join(f"{op} ({why})" for op, why in boards.RETIRED.items())
              + ".", "", STEP_RULE, DRAWING_RULE]
    return "\n".join(lines)


# ----- the copies -----

# THE BOARD SECTION OF A HOUSE'S BRIEF (c-603). The card used to be embedded in the house
# contract with a page of drawing rules around it, which put the contract four times over its
# 60-line cap. A house with a shell is now given this section, generated at brief time
# (`prompts.abilities`), so it always carries the current card and the contract keeps one
# paragraph saying when to draw. The rules behind each sentence are `docs/atlas/45-board.md`.
# A house with a shell pipes its ops on stdin; a fenced one can give no stdin and must name
# `keel` by its absolute path (`bin/keel-board-fence`), so its verbs say exactly that.
VERBS = """\
    keel board find "<a few words>"      # is there already a board about this? offer it
    keel board push --card $KEEL_CARD    # the ops on stdin, or --file <path>; prints the link
    keel board list --card $KEEL_CARD    # your card's boards
    keel board delete <b-id>             # YOUR card's boards only; the user can restore it
"""
FENCED_VERBS = """\
    {keel} board find "<a few words>"
    {keel} board push --card $KEEL_CARD --file <ops file>   # no stdin here: Write the ops to a file in $KEEL_CARD_DIR
    {keel} board list --card $KEEL_CARD
    {keel} board delete <b-id>
"""
BRIEF = """\
### Drawing on your card's board

{verbs}
A board is ONE diagram: groups, nodes and edges, with the detail (a note, a step, a table,
a snippet, a file) hanging on the node it is about. One topic per board: the `board` line
is the topic, and a second picture is a second board, never more nodes on this one. You
may push only to your own card. There is no erase: declare a node id again to change its
label, and a correction is a new note or a new board; a push with no `board` line adds to
the live board. A `path` line hands the user a file from your card directory or worktree (under
{cap}); a file the user puts on the board lands in `$KEEL_CARD_DIR/inbox/` with a
note on your card. When you answer the user's voice or the board's ask box, write the ops in a
fenced `board` block in the answer instead. A turn that starts with a `board report:` line
means your last drawing did not land: draw it again.

```
{card}
```
"""


def brief_block(keel: str | None = None) -> str:
    """The board section of a house's brief, with the current card in it. `keel` is the
    absolute path a fenced house must name; None for a house with a shell."""
    from keel import boardfiles                 # noqa: PLC0415 - only the cap, only here
    verbs = FENCED_VERBS.replace("{keel}", keel) if keel else VERBS
    return (BRIEF.replace("{verbs}", verbs).replace("{cap}", boardfiles.CAP_SAID)
            .replace("{card}", grammar_card()))


BLOCK = re.compile(r"^```" + FENCE_LANG + r"[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)


def embedded(text: str) -> str | None:
    """The card a copy embeds, or None when it embeds none."""
    found = BLOCK.search(text or "")
    return found.group(1).rstrip("\n") if found else None


def write_copy(path: Path) -> bool:
    """Rewrite the card embedded in one copy; True when it changed."""
    text = Path(path).read_text()
    card = grammar_card()
    if embedded(text) == card:
        return False
    if embedded(text) is None:
        raise ValueError(f"{path} has no ```{FENCE_LANG} block to rewrite")
    fresh = BLOCK.sub(lambda _m: f"```{FENCE_LANG}\n{card}\n```", text, count=1)
    Path(path).write_text(fresh)
    return True


def copies(root: Path = ROOT, install: Path | None = None) -> list[Path]:
    """Every file that embeds the card: the tree's, then the talker's drawing entry where its
    memory is read from (the install's once it holds the talker's memory, else the
    checkout's), when that entry is there. `install` defaults to the one the config names."""
    from keel import configpath, memoryroot     # noqa: PLC0415 - only here
    root = Path(root)
    if install is None:
        install = configpath.install_of(configpath.config_path(root), root)
    found = [root / relative for relative in COPIES]
    talker = memoryroot.dir_of(memoryroot.TALKER, install, root) / TALKER_COPY
    return found + ([talker] if talker.is_file() else [])


def write_all(root: Path = ROOT) -> list[str]:
    """Rewrite every copy; the ones that changed."""
    return [str(path) for path in copies(root) if write_copy(path)]


# ----- the previous grammar -----

TOKEN = re.compile(r'"([^"]*)"|(\S+)')
BARE_ATTACHED = {"step": "step", "note": "note", "text": "note"}
FRAME_OPENS = ("table", "code")
DROPPED = "{why} (dropped: written for the previous grammar)"


def translate(raw: str) -> dict | None:
    """A line the current grammar refused, read as the previous grammar.

    `{"line": <the line in this grammar>, "why": ""}` when it translates, `{"line": None,
    "why": <the reason>}` when it is a previous-grammar line with nothing left to draw (a
    frame), and None when it is not a previous-grammar line at all, which leaves the
    current grammar's own refusal standing.
    """
    from keel import boards                     # lazy: `boards` imports this module
    text = str(raw or "").strip()
    if text.count('"') % 2:
        return None
    tokens = [(m.group(1), True) if m.group(1) is not None else (m.group(2), False)
              for m in TOKEN.finditer(text)]
    if not tokens or tokens[0][1]:
        return None
    head = tokens[0][0]
    if head in BARE_ATTACHED and len(tokens) == 2 and tokens[1][1]:
        return {"line": f'{BARE_ATTACHED[head]} board "{tokens[1][0]}"', "why": ""}
    if head == "frame":
        kind = tokens[1][0] if len(tokens) > 1 and not tokens[1][1] else ""
        if kind in FRAME_OPENS and len(tokens) == 3 and tokens[2][1]:
            return {"line": f'{kind} board "{tokens[2][0]}"', "why": ""}
        return {"line": None, "why": DROPPED.format(why=boards.RETIRED["frame"])}
    if head == "path" and len(tokens) == 6 and tokens[1][1]:
        rest = text[len("path"):].strip()
        return {"line": f"path board {rest}", "why": ""}
    return None


def main(argv: list[str]) -> int:
    """`python3 -m keel.boardgrammar [--write]`: print the card, or rewrite every copy."""
    if "--write" in argv:
        changed = write_all()
        print("rewrote: " + ", ".join(changed) if changed else "every copy is current")
        return 0
    print(grammar_card())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
