"""What a house's brief says about the plan and the outcome, and the record it starts with.

With `[keel] plan_pages` on (the default, and the shipped example), every NEW plan and outcome in
both spaces is written in the plan format and read on its own page. The brief carries the
format card generated from the parser (`keel/plancard.py`), the lint to run before a stage,
the board rule (flows are boards pushed and embedded by id, drawn as rich as the house's
context allows), and Ask. With it off, the plan styles apply exactly as before: that text
is here too, moved out of the house contract so the switch is the one place that decides.

The lavish lines of the brief (`prompts.LAVISH_SEES`) are left out while it is on: a format
plan has no surface to open and nothing to poll, because his round arrives through the gate
verbs and his questions through Ask.
"""

from __future__ import annotations

from keel import merging, plancard
from keel.review.gate import ships_a_change

HEADING = "### How you write the plan and the outcome"

PLAN_PAGES = """\
{heading}

Both are pages the user reads and answers on the deck, `/plan/<card>` and `/outcome/<card>`, each
drawn from ONE markdown file in the plan format: the card below, and the whole spec with
examples in `$KEEL_HOME/docs/plan-format.md`. You write content, never HTML. Every plan and
outcome is this format, whatever `options.plan_style` says.

- **The plan** is `$KEEL_CARD_DIR/plan.md`, opening with the frontmatter
  (`kind: plan`, `card:`, `title:`, `repo:`, and `at:` the commit you planned against,
  `git rev-parse HEAD` in each worktree, so its refs to today's code still resolve after
  the change moves them). Run `kb lint $KEEL_CARD --file <plan.md>` until
  it says the contract holds, then `kb stage $KEEL_CARD planning --plan <plan.md>`: the stage
  refuses a plan that breaks the contract, one line per finding.
- **The outcome** is `context.md` beside it, your running record, which already opens in the
  format (`kind: outcome`). Keep it that way; `kb lint $KEEL_CARD --outcome` before
  `kb stage $KEEL_CARD review`, which refuses it the same way. A repo card's outcome also
  carries `## Risk`, the pipeline's last step (its section below says how).
- **The outcome explains what was actually done.** Its five sections (Where it stands,
  What is next, Why this shape, Open questions, Evidence) are a short frame, a few lines
  each, not the whole record. Between them, add sections of your own (`## <what it is
  about>`) that explain the work to someone who was not there: what you found, how it works
  now, what you tried and dropped, and why. Explain in prose first, with tables where there
  are numbers or cases to set side by side. Use a diagram or a board only where it explains
  better than prose, and give each one in the outcome a sentence or two saying what it
  shows. This asks for no board beyond the ones this brief already names.
- **A research card's outcome IS the research** (`kind: research`, which its record already
  opens with): the findings themselves, explained, in that one outcome file, with no
  separate report file and no link to one. Its sections are Findings, What it means, What
  is next and Evidence (where each fact came from), with your own between them as needed;
  no Risk and no PR body. A research card whose record opened as `kind: outcome` switches
  its kind line and headings to these.
- **Flows are boards**, pushed and embedded by id. First `keel board list --card $KEEL_CARD`:
  a board the card already has is extended (push to it under its own title) or embedded as
  it is. For new ones, write the ops into a file and run
  `keel board push --card $KEEL_CARD --new --file <ops file>`: every `board "<title>"` line
  in that file becomes a board of its own, and it prints each id. Embed each in a ```board
  block whose one line is that id. Draw them as rich as your context allows: when you
  already know the flow, draw the whole walk now (steps and notes on the nodes, a table
  where the numbers are); when you do not yet, a lean board (titles, a detail line per node,
  icons, groups) is fine, and the full walk comes with the outcome.
{outcome_boards}- **The user's answers arrive through the gates.** Approve and Send back carry the whole round (the
  picks, the recommendations left standing, the notes with the words the user selected) in the
  prompt that resumes you. There is nothing to poll and nothing to open.
- **Ask.** The user can ask a question on the page without sending the plan back. You are resumed
  with it: answer with `kb reply $KEEL_CARD --ask <id> --text "..."`. On an Ask, do NOT
  revise the plan and do NOT move the card.

````
{card}
````
"""

# The plan styles as the house contract said them before the plan pages, word for word: the
# switch turned off is the brief as it was.
# What an outcome that ships a change draws (C33, c-602): the plan's boards were drawn
# before the code existed, so the outcome redraws them at the built head and adds the one
# board he reads the code by. One text: the brief carries it, and the backfill's prompt
# (`keel/outcomeboards.py`) quotes it, so a card fixed later is asked for the same thing.
OUTCOME_BOARDS = """\
- **The outcome redraws the flow at the built head** (a repo card that ships a change;
  `kb lint --outcome` refuses it otherwise, C33). At Verify, hand it to ONE background
  subagent (run in the background), so it costs nothing on the path to review; it needs
  only the built head:
  1. Every board the plan embeds, redrawn as THE SAME board so it shows what was built:
     `keel board push --card $KEEL_CARD --board <its id> --file <ops>` with the whole
     picture. A push that names its board REPLACES what it shows (same id, the plan's
     lines kept in its log), so the page shows one board, not two drawings side by side.
     One left as it was is tagged "from the plan, not updated" on the page, and the lint
     warns about it.
  2. ONE new board, `keel board push --card $KEEL_CARD --new`, titled `Code flow: <what it
     does>`, drawn so the user can read the code by it: a node per unit (function, class,
     module) with its `path` as the detail and groups per module or service (a group's id
     is never a node's); edges in CALL ORDER, each labelled with the call; a `note board`
     saying to follow the numbered steps; one `step` per node, in order, carrying ONE
     worked example with its real values through the code; a `code` block where the lines
     matter; a `note` naming the tests that pin that unit.
  3. The subagent never edits `context.md`: it writes the board blocks (each id in a
     ```board block) and `### Read it in this order`, a NUMBERED list of `path:line`s, one
     per step of the Code flow board, into
     `$KEEL_CARD_DIR/outcome-boards.md`, and hands that back.
  You JOIN it before `kb stage review` (wait for its result; never stage with it running),
  merge its text into `## Why this shape` yourself, and, once the review's fixes are in,
  check every reading order line against the final head (`kb lint --outcome` runs C7 on
  them). A card with nothing to land says `change: none` in the outcome's frontmatter and
  draws none of this; a docs-only change says `change: docs` and gives the reading order
  (the pages, in order) without a Code flow board.
"""

# c-718: a stacking space (its pack declares `stacks`). ONE bullet, "Stacked or
# independent", and everything in it is conditional (r2.F9): the split half applies only if
# the plan splits this card, and carries no example row, only the row's shape; the waiting
# half is there only when cards wait for this one, names them, and gives their rows
# (r1.F14). The board sentence asks for the breakdown only in those two cases. Nothing else
# here asks for a board, and no lint rule holds any of it.
STACK_BLOCK = """\
      ```batch stack
      q: Stack each one on the card it waits for, or keep it independent?
      choices: stacked, independent
{rows}
      ```
"""
STACK_WHAT = ("STACKED (cut from the branch of the card it waits for, its {change} aimed at that "
              "branch, so it builds on that code and merges after it) or INDEPENDENT (cut from the "
              "base, its {change} to the base, starting at once), with one line of why: it shares "
              "files with that card, or uses its new code")
SPLIT_ROWS = ("ONLY IF your plan splits this card (`kb split`, after the Approve): each slice that "
              "waits for another gets a row in one ```` ```batch stack ```` block, `s<n>: <its exact "
              "title> (after <the exact title of the slice it waits for>) | stacked | <why>` "
              "(`choices: stacked, independent`), and your `kb split` then gives each slice the answer "
              "the user approved, but only when its after is the slice named there. A slice that needs "
              "fewer repos than this card names says which in the plan, and your `kb split` states them "
              "on it (`|repo=<key[,key]>`); a stacked slice shares at least one repo with the slice it "
              "is stacked on, and in a repo that slice does not work in it is cut from its own base.")
WAITING_ROWS = ("These cards wait for this one, and need a row each in that same block, its id as the "
                "row: {cards}. If this plan also splits this card, none of them can be stacked on it "
                "(it will have no branch of its own): answer independent, or stack it on a slice later.")
STACK_BOARD = ("Only if {when}, show the breakdown once on a board: "
               "each card a node, the stacked ones marked, the branch each is cut from and the branch "
               "its {change} aims at, on a board the plan already embeds when it fits there, else one "
               "small board of its own. The user confirms or flips each row, and the Approve records it; "
               "you never set it yourself.")
STACKING = """\
- **Stacked or independent.** Each answer is {what}. {split}
{waiting}  {board}
"""


def stacking_block(change: str, waiting: list[dict] | None) -> str:
    """The plan's stacking bullet for a stacking space: the split half (conditional, no
    example row), and the waiting cards, named with a row each, only when there are some."""
    rows = ""
    if waiting:
        cards = ", ".join(f"{card['id']} ({one_line(card.get('title'))})" for card in waiting)
        lines = "\n".join(f"      {card['id']}: {one_line(card.get('title'))} | <stacked or independent> | <why>"
                          for card in waiting)
        rows = "  " + WAITING_ROWS.format(cards=cards) + "\n\n" + STACK_BLOCK.format(rows=lines) + "\n"
    return STACKING.format(what=STACK_WHAT.format(change=change), split=SPLIT_ROWS, waiting=rows,
                           board=STACK_BOARD.format(change=change, when="you split, or for the cards named above"
                                                    if waiting else "you split"))


PLAN_STYLES = """\
### How you write the plan

The card's `options.plan_style` decides the form: `lavish` is a surface (load the `lavish`
and `html-artifacts` skills, and open it with `lavish-axi --no-open <file>` before your turn
ends); `markdown` is a page; `auto` (or absent) means you choose: a surface when there is a
design choice or several shapes to compare, a page when it fits in one. Any HTML you write
links the theme already beside your card (`<link rel="stylesheet" href="theme.css">`) and
uses its tokens, not another design system.
"""

PLAN_AS_HTML = "Write the plan, the report\nor the mockup in plain semantic HTML"
REPORT_AS_HTML = ("Write a report or a mockup (never\nthe plan or the outcome: they are "
                  "the plan format) in plain semantic HTML")

# What a fenced house is told about its documents while the plan pages are on: the plan and
# the outcome are the format (its section says how), and everything else is markdown too.
FENCED_FORMAT = """\
### What you write, and in what form

`lavish-axi` is not one of the commands your Bash allows, and you do not need it: the plan
and the outcome are the plan format (the section on them says how), and anything else the user
reads is markdown under `$KEEL_CARD_DIR/`, which the deck renders with
the images it embeds.
"""

# A plan in the format: each decision he answered goes into the plan as settled and its block
# comes out, because the lint refuses one still standing (C16), and the stage lints first.
FOLD_IN = ("Fold each decision the user answered into the plan as settled and take its block out "
           "(the lint refuses one left standing): under `## Decisions`, a `> [!settled] <the "
           "choice>` callout per answered decision, saying what the user chose and why, and run `kb lint $KEEL_CARD` until the "
           "contract holds before you end your turn.")


CONTEXT_SECTIONS = ("Where it stands", "What is next", "Why this shape", "Open questions",
                    "Evidence", "PR body")
# A research card's record (c-719): the research itself, in `planlint.RESEARCH_SECTIONS`.
RESEARCH_SECTIONS = ("Findings", "What it means", "What is next", "Evidence")
# A card that ships a change also carries the pipeline's risk step in its record (HP-2, C27).
RISK_SECTION = "Risk"


SPACE_STYLE = ("A card that names no plan style takes this space's: `{style}` "
               "(`[spaces.<name>] plan_style`).\n")


def plan_block(plan_pages: bool, space_style: str | None = None, stacks: bool = False,
               change: str = "change", waiting: list[dict] | None = None) -> str:
    """The brief's plan section: the format and its card, or the plan styles, with the
    space's own plan style as the fallback when it is not `auto` (c-633). `stacks`: the
    space's pack stacks waiting cards (c-718), so the plan proposes how each stands;
    `waiting`, the cards that wait for this one (`stacking.waiting_cards`), named in it."""
    if not plan_pages:
        return PLAN_STYLES + (SPACE_STYLE.format(style=space_style)
                              if space_style and space_style != "auto" else "")
    extra = OUTCOME_BOARDS + (stacking_block(change, waiting) if stacks else "")
    return PLAN_PAGES.format(heading=HEADING, card=plancard.format_card(), outcome_boards=extra)


def one_line(text) -> str:
    return " ".join(str(text or "").split())


# What the record a card starts with tells its house, as a markdown comment the page never
# draws (`planformat.uncomment`), so a house that forgets to take it out shows the user
# nothing (c-719).
RESEARCH_NOTE = ("<!-- This record IS the research: the findings themselves, explained, in these\n"
                 "sections and your own between them, with no separate report file and no link to one.\n"
                 "Prose first, tables for numbers and cases, a board only where it explains better than\n"
                 "prose, with a sentence or two saying what it shows. -->\n\n")
SKELETON_NOTE = ("<!-- The five sections below are a short frame, a few lines each. Explain what was\n"
                 "actually done in sections of your own between them: prose first, tables for numbers\n"
                 "and cases, a board or diagram only where it explains better than prose, with a\n"
                 "sentence or two saying what it shows. -->\n\n")


def context_skeleton(card: dict, plan_pages: bool) -> str:
    """The record a new card starts with: the six headings, and with the plan pages on, the
    frontmatter that makes it an outcome in the format (so `kb stage review` lints it) and
    the note that says what an outcome is for (`SKELETON_NOTE`). A card that ships a change
    gets a Risk heading after Evidence."""
    research = bool(card) and merging.is_research(card)
    headings = list(RESEARCH_SECTIONS if research else CONTEXT_SECTIONS)
    if card and not research and ships_a_change(card):
        headings.insert(headings.index("Evidence") + 1, RISK_SECTION)
    body = "".join(f"## {heading}\n\n" for heading in headings)
    if not plan_pages or not card:
        return body
    title = one_line(card.get("title")) or card["id"]
    head = (f"---\nkind: {'research' if research else 'outcome'}\ncard: {card['id']}\ntitle: {title}\n"
            + (f"repo: {one_line(card['repo'])}\n" if card.get("repo") else "")
            + f"---\n# {card['id']} {title}\n\n" + (RESEARCH_NOTE if research else SKELETON_NOTE))
    return head + body
