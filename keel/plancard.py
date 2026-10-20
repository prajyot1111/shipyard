"""The plan format as one card, generated from the parser and the lint (P4-1).

`docs/plan-format.md` is the spec a person reads; this is the card every house's brief
carries, the way `keel/boardgrammar.py` carries the board's grammar. It is GENERATED from
the tables that decide what a plan may say (`keel/planformat.py`, `keel/planblocks.py`,
`keel/planlint.py`), so a block kind, a section or a rule added to one of them without its
line here fails `tests/test_plancard.py` rather than reaching a house as a card that lies.

`docs/plan-format.md` embeds the same card in a fenced block whose language is `plancard`;
the test holds the copy equal and `python3 -m keel.plancard --write` rewrites it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from keel import boardgrammar, boards, planblocks, planfinding, planformat, planlint, planreview

VERSION = 1
FENCE_LANG = "plancard"
COPIES = ("docs/plan-format.md",)
ROOT = Path(__file__).resolve().parent.parent

# One line per fenced kind, in `planblocks.KINDS` order. The test holds the keys to that
# tuple, so a new kind cannot land without its line on the card.
SIGNATURES = {
    "decision": ("decision <id>", "q:, why:, 2 to {max_options} `option <id>: <label>` each with "
                 "indented `gets:` and `cost:`, `rec: <option id>`, `because:`, optional "
                 "`other: no`, `after: <decision id>`"),
    "batch": ("batch <id>", "q:, `choices: a, b, c`, then one row per item: "
              "`<row id>: <text> | <recommended choice> | <why>`"),
    "options": ("options <id>", "`option <id>: <label>` with indented summary:, pro:, con:; "
                "`rec: <id>`; `decision: <id>` it feeds"),
    "compare": ("compare <title>", "`left: Today`, `right: After`, rows `aspect | left | right` "
                "(aspect `image` takes two picture paths)"),
    "questions": ("questions", "`q:` then `rec:` (and `why:`) per question; same as a list "
                  "under Open questions with `Recommend:` in each item"),
    "steps": ("steps <title>", "one per line: `[{states}] Title | detail`"),
    "stats": ("stats", "one to six lines `label | value | sub | {tones}`"),
    "copy": ("copy <title>", "text kept exactly: a PR body, a commit message"),
    "diff": ("diff <path> | why", "a unified diff"),
    "mermaid": ("mermaid <title>", "flowchart, sequenceDiagram or stateDiagram-v2, at most "
                "{max_nodes} nodes: a SMALL picture beside the flow, never the flow"),
    "board": ("board <title>", "ONE line, the id `keel board push` printed (b-NNN): the flow"),
    "finding": ("finding <id>", "a review finding, whole: `severity: {severities}`, `member: <repo>#<n>` "
                "(a feature), `at: path:line`, claim:, evidence:, `verifier: {verifier}` (disputed: "
                "indented for: and against:), suggestion:, `comment:` (indented lines, posted as "
                "written), `choice: post|edit|drop`, because:"),
    "details": ("details <summary>", "markdown folded away: long evidence, logs"),
    "code": ("<lang> <path[:lines]> | why", "a snippet; the path and the why are required"),
}

# One line per rule a MECHANISM holds (`planlint.ENFORCED` M or M~). The test holds the keys
# to that set, so a rule the lint starts refusing is on the card the day it does.
RULES = {
    "C1": "a summary paragraph comes first, at most {summary} words",
    "C2": "Goal, Now and Target present, and every section in order",
    "C3": "a compare names both sides and every row fills both",
    "C4": "a repo card embeds its flow as a board BY ID; every embedded id resolves",
    "C7": "every `path:line` exists at HEAD of your worktree (any of them, for a cross-repo card; a plan's at its `at:`, an outcome's at the card's branch tip); a dependency's (node_modules/, site-packages/) is not checked",
    "C8": "a code block carries `| why`, and a path unless it is a shell",
    "C9": "Proposal is there and says something",
    "C11": "a decision block, a `> [!settled]` callout for one the user answered, or `None: <why>` under Decisions; 2 or more options, each with a cost",
    "C12": "every decision has `rec:` naming an option and `because:`; every open question a recommendation",
    "C14": "`after:` names a decision on this plan",
    "C16": "a decision the user answered last round is folded in and its block taken out",
    "C17": "Risks lists one, or `None: <why>`",
    "C18": "a repo card's Steps and Proof are there and filled",
    "C19": "Out of scope is there and filled",
    "C20": "the line above a table says what its rows prove",
    "C21": "no paragraph over {prose} words (a warning)",
    "C24": "no em-dashes anywhere",
    "C26": "an outcome has its sections (a research or report outcome its four), and Evidence names an artifact",
    "C27": "an outcome that ships a change has `## Risk`: low, medium or high, and why",
    "C28": "a review opens with Orientation: what it does, the code path as a board by id, a reading order of `path:line`s",
    "C29": "a review's Findings is one ```finding block per finding, each with a valid severity, `at: path:line`, a claim, a `comment:` draft and a `choice:`",
    "C30": "a review has exactly one ```decision verdict (comment, changes, approve) with `other: no`",
    "C31": "a re-review raises nothing the user posted or dropped last round on lines that did not change",
    "C32": "a feature review names each finding's `member:` (its path:line resolves there) and has ONE ```decision verdict-<repo>-<number> per member",
    "C33": "an outcome that ships a change embeds a board pushed after the plan was approved (the plan's boards redrawn, one Code flow board) and a numbered reading order of `path:line`s under Why this shape; a board left as the plan drew it is a warning; frontmatter `change: none` (nothing to land) is exempt, `change: docs` needs only the reading order",
}


def titles(names) -> str:
    return ", ".join(planlint.TITLE_OF[name] for name in names)


def enforced() -> list[str]:
    return [rule for rule, how in planlint.ENFORCED.items() if how.startswith("M")]


def format_card() -> str:
    """The format as one card, from the parser's and the lint's own tables."""
    lines = [f"Plan format v{planformat.VERSION}, card v{VERSION}: ONE markdown file, "
             "frontmatter first, a few fenced blocks. Never HTML: the deck draws every pixel.",
             "",
             "---",
             "kind: plan        (or outcome; context.md is always an outcome, research on a research",
             "                  card, or review on a review card)",
             "card: c-NNN",
             "title: one line",
             "repo: <name>      any other key (branch, base, a ticket) is a meta line",
             "at: <sha>         a plan: the commit it was planned against (`git rev-parse HEAD`, one",
             "                  per repo, comma separated); its path:line refs resolve there",
             "---",
             "",
             "A plan: `# <title>`, a summary paragraph, then `## ` sections in this order: "
             + titles(planlint.PLAN_ORDER) + ", and optionally Open questions. Steps and "
             "Proof are for a repo card. A compare block may stand in for Now and Target.",
             "An outcome (context.md): " + titles(planlint.OUTCOME_SECTIONS)
             + ", then Risk for a change that ships (low, medium or high, and why), and "
             "PR body where there is one (the body in a ```copy block, one per change). "
             "A finished change also says, as `###` under Why this shape, What changed from "
             "the plan and Review findings (what review found and what was done), and may end "
             "with Links. The five are a short frame: an outcome explains what was actually done "
             "in sections of your own between them, in prose and tables, with a board or diagram "
             "only where it explains better than prose and a sentence or two saying what it shows. "
             "A change that ships also redraws the plan's boards at the built head, "
             "adds ONE `Code flow: <what>` board, and under Why this shape gives `### Read it in "
             "this order`, a numbered list of `path:line`s.",
             "A research outcome (a research card's context.md, `kind: research`; a `kind: report` "
             "is held the same): " + ", ".join(planlint.RESEARCH_TITLES[n] for n in planlint.RESEARCH_SECTIONS)
             + ". It IS the research: the findings themselves, explained, in this one file, with no "
             "separate report file and no link to one; no Risk, no PR body.",
             "A review (a review card's context.md, `kind: review`): the summary, then "
             + titles(planreview.ORDER) + ": one ```finding block per finding, its code drawn "
             "from the worktree by the deck (no Snippets).",
             "",
             "Fenced blocks (the fence's language is the kind, the rest of its line the id "
             "or title, the body is `key: value` lines; an indented line belongs to the one "
             "above):"]
    fill = {"max_options": planblocks.MAX_OPTIONS, "states": "|".join(planblocks.STEP_STATES),
            "tones": "|".join(planblocks.TONES), "max_nodes": boards.MAX_NODES,
            "severities": "|".join(planfinding.SEVERITIES), "verifier": "|".join(planfinding.VERIFIER_WORDS)}
    for kind in planblocks.KINDS:
        head, body = SIGNATURES[kind]
        lines.append(f"  {head:<28} {body.format(**fill)}")
    lines += ["", "A board's steps: " + boardgrammar.STEP_RULE,
              "",
              "Markdown: lists (two levels), `- [ ]` tasks, GFM tables (a caption line above; "
              "a cell may open with [ok], [warn] or [bad]), callouts `> [!tone] Title` with "
              "tone " + "|".join(planformat.CALLOUT_TONES) + ", pictures "
              "`![caption](assets/x.png){" + "|".join(planblocks.FRAMES) + "}`. c-NNN, "
              "path/to/file.py:40, and the card's space's ticket and change refs link "
              "themselves.",
              "",
              "What `kb lint` and `kb stage` refuse:"]
    fill = {"summary": planlint.SUMMARY_WORDS, "prose": planlint.PROSE_WORDS}
    for rule in enforced():
        lines.append(f"  {rule:<4} {RULES[rule].format(**fill)}")
    lines += ["", "The whole spec, with examples: $KEEL_HOME/docs/plan-format.md"]
    return "\n".join(lines)


# ----- the copies -----

BLOCK = re.compile(r"^```" + FENCE_LANG + r"[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)


def embedded(text: str) -> str | None:
    found = BLOCK.search(text or "")
    return found.group(1).rstrip("\n") if found else None


def write_copy(path: Path) -> bool:
    """Rewrite the card one copy embeds; True when it changed. A copy with no block is left
    alone and reported, because where the card goes in a page is the page's call."""
    text = Path(path).read_text()
    card = format_card()
    found = BLOCK.search(text)
    if found is None or found.group(1).rstrip("\n") == card:
        return False
    Path(path).write_text(text[:found.start(1)] + card + "\n" + text[found.end(1):])
    return True


def main(argv: list[str]) -> int:
    if argv[:1] == ["--write"]:
        for relative in COPIES:
            if write_copy(ROOT / relative):
                print(f"rewrote {relative}")
        return 0
    print(format_card())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
