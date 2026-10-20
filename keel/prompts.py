"""Every sentence Keel says to a house that is not the contract: the resume prompts for
the plan gate, and the generated "What you can do" block of the brief.

The prompts live here, in one place, because they are a contract of their own: the deck's
approve and send back taps, the drain's resume, and the house's own loop all have to agree
on what the house was told. Two facts shape them:

- Annotations on a lavish surface are queued by lavish and come back only through
  `lavish-axi poll <html>`, which long-polls in the foreground. A house must never sit in a
  poll just in case (waiting is the drain's job), so the plan-gate prompts collect them on
  resume, bounded by `timeout`, and a poll that is killed loses nothing: lavish keeps the
  queue.
- A discussion is the one deliberate exception. The human asked to talk, so the house holds
  its slot and stays in the loop until the session ends or the surface goes quiet.

The "What you can do" block is generated at brief time rather than written into
`etc/house-contract.md`: the board's verbs are `kb help`'s to list, and the contract stays
under 60 lines.
"""

import re
import subprocess
from datetime import datetime
from pathlib import Path

from keel import planbrief, stacking

COLLECT_SECONDS = 20
IDLE_SECONDS = 1200
SURFACE_SUFFIXES = (".html", ".htm")

# `kb help` lists every verb; these are never a house's to run. Approvals are the human's,
# `stop` ends a session (only a human tap does that), `claim` is a drain's, and the rest are
# the operator's roles.
FORBIDDEN_VERBS = ("approve", "ship", "mark", "rereview", "import-harbor", "claim", "relay", "carried", "land", "drain", "serve", "fetch", "run", "install")
FORBIDDEN_SUBSTRING = "stop"
VERB_LINE = re.compile(r"^([a-z][a-z0-9-]*)\b(.*?): (.+)$")

HELP_ARGV = ("help",)
HELP_TIMEOUT = 20


# ----- the plan surface -----

def is_surface(plan_ref: str | None) -> bool:
    """True when the card's plan is a lavish HTML surface rather than a markdown file."""
    ref = str(plan_ref or "").split("?")[0].split("#")[0]
    return ref.lower().endswith(SURFACE_SUFFIXES)


def collect_block(plan_ref: str | None, seconds: int = COLLECT_SECONDS) -> str:
    """The bounded one-shot poll, or an empty string when the plan is not a surface."""
    if not is_surface(plan_ref):
        return ""
    return (
        "The plan is a lavish surface, so the human may have annotated it. Before anything "
        "else, collect the annotations with ONE bounded poll:\n\n"
        f"    timeout {seconds} lavish-axi poll {plan_ref}\n\n"
        "Whatever it prints is the human's annotations; read them as part of what they said. "
        "If it prints nothing there are none, and nothing is lost: queued feedback keeps "
        "until the next poll. If lavish answers that there is no session for that file, "
        "there is nothing queued either. Never run the poll unbounded here, and never run "
        "it twice.")


def joined(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


# ----- the plan gate -----

# What a plain Approve means, said rather than left to be inferred. The contract asks a
# house to recommend an answer to every open question it leaves him
# (`etc/house-contract.md`), so a tap with nothing typed beside it IS those recommendations
# taken, and a house that stops to ask again costs him a whole round trip.
RECOMMENDED = ("Any open question in the plan the user did not answer takes the answer the plan "
               "recommended; do not stop to ask again.")


def approve(plan_ref: str | None, said: str | None = None,
            seconds: int = COLLECT_SECONDS) -> str:
    """The prompt that resumes a house whose plan the human just approved.

    `said` is what he typed beside the tap. A markdown plan has no surface to annotate, so
    this is the only way his answers to its open questions reach the house: without it,
    answering them cost a send back (the house revises, the card stays at planning) and then
    a second approve. It composes with `collect_block`: on a surface the annotations and his
    words are read together, as one answer.
    """
    words = str(said or "").strip()
    head = "The plan is approved and the card is at building now."
    if words:
        head += " The user said:\n\n" + quoted(words)
    sources = [name for name, present in (("the annotations", is_surface(plan_ref)),
                                          ("the user's answers", bool(words))) if present]
    apply_first = (f"Apply {' and '.join(sources)} where they change the work, and say in "
                   "`context.md` what you changed and why. " if sources else "")
    return joined(
        head,
        collect_block(plan_ref, seconds),
        RECOMMENDED,
        apply_first + ("Then build" if apply_first else "Build")
        + ": run to the outcome gate the contract names, and end your turn there. Do not ask "
        "whether to start.")


def sendback_plan(plan_ref: str | None, reason: str, seconds: int = COLLECT_SECONDS) -> str:
    """The prompt for a plan the human sent back, with his typed reason."""
    what = ("Take the annotations and the reason together, revise" if is_surface(plan_ref)
            else "Revise")
    return joined(
        "The plan is not approved yet. The human sent it back and said:\n\n" + quoted(reason),
        collect_block(plan_ref, seconds),
        f"{what} the plan in place at "
        f"{plan_ref or 'its file'} (a different file needs `kb stage $KEEL_CARD planning "
        "--plan <path>`), and end your turn. The card stays at planning and the human looks "
        "again. Do not start building.",
        "" if is_surface(plan_ref) else planbrief.FOLD_IN)


def plan_ask(card_id: str, asks: list[dict], doc: str = "plan") -> str:
    """The prompt for his questions on the plan page (Ask, P2-9): answer, and nothing else.

    It is NOT a send back: the plan stays as it is and the gate stays open, and his other
    answers and notes wait for his Send. Each question names the block it is on and the
    words he selected, apart from what he asked (c-175)."""
    lines = []
    for ask in asks:
        where = f" (on {ask['block']})" if ask.get("block") else ""
        lines.append(f"Question {ask['event']}{where}:")
        if ask.get("quote"):
            lines.append("  about the words: " + quoted(ask["quote"]).replace("\n", "\n  "))
        lines.append("  the user asks: " + quoted(ask["text"]).replace("\n", "\n  "))
    first = asks[0]["event"] if asks else "<id>"
    # c-600: an outcome's question says outcome (the e2e run's outcome Ask said "plan")
    page, kept = ("outcome", "the record (context.md) and the code") if doc == "outcome" else ("plan", "the plan file")
    return joined(
        f"The user has a question about your {page} for {card_id}, asked on the {page} page. Answer "
        "it; this is not a send back.",
        "\n".join(lines),
        f"- do NOT revise {kept}: it stays exactly as it is until the user sends their round.\n"
        f"- do NOT move the card: no `kb stage`, no `kb approve`; the {page} gate stays open.\n"
        f"- Answer each question with `kb reply {card_id} --ask {first} --text \"<your answer>\"` "
        "(its own id each time, in order); the reply shows under the user's question on the page, "
        "and it hands you the next one if they asked again meanwhile.\n"
        "- Read the code if you need to, then end your turn.")


# ----- a blocked house -----

# The plain resume: what Resume, the drain's own resume and a relayed resume send.
RESUME = "continue from where you stopped; the card is still at {stage}"


# c-654: what a house started in place of one whose conversation the harness no longer holds
# is told between its brief and the prompt the resume would have carried. The card's own
# record is all that is left of what the lost conversation knew, so it is named, path by path.
AFRESH = """\
## You take this card over where it stands (Keel)

The house that worked this card before you is gone: the harness kept its conversation
(session {old}) only for its retention period, so you start with none of what it knew. The
card is at `{stage}`, not at its start. Do not plan it or build it again: the work is done as
far as that stage says, and it is in your worktree and on the card's own record. Read the
record before anything else:

{record}

Then do what follows, which is what that house would have been told now."""


# c-787: what a session the user opens with Drop in on a DONE card is told when the card's
# conversation is gone. They want to discuss the finished work, so it reads the record and
# waits; a worktree is its own call, made only once the discussion needs a code change.
REOPEN = """\
## Card {id} is done; the user wants to discuss it (Keel)

{id}, "{title}", is done. {lost} Read its record before anything else:

{record}

Then say in a few lines where the card stands, and end your turn. Change nothing until the
user says what they want. No worktree is open: if the discussion comes to a code change,
make one yourself from the card's branch or its base, and say where."""


HANDOFF_FILE = "handoff.md"        # a rotation's checkpoint (`keel/rotate.py`)
# What a house started afresh for his Drop in, or his Resume and open in app, is told in
# place of a resume prompt: he is about to be in the session himself, so it reads the record
# and waits for him.
JOIN_AFRESH = ("The user is about to join this session in person (Drop in at a terminal, or the Claude "
               "app). Read the record above so you can answer them, say in a few lines where the "
               "card stands, and end your turn. Change nothing until the user says what they want.")


def afresh(card: dict, card_dir, prompt: str, old: str, change: str = "change", cfg=None) -> str:
    """The brief's tail for a house started afresh (`afresh.start`): the record the
    lost conversation left on the card, then `prompt`. With `cfg`, the base is read by the
    integration rule (c-732 r2.F1, `merging.card_base`, then the repo's integration branch)."""
    record = "\n".join(record_lines(card, card_dir, change, cfg))
    return joined(AFRESH.format(old=old, stage=card["stage"], record=record), prompt)


def reopen(card: dict, card_dir, old: str | None, change: str = "change", cfg=None) -> str:
    """What a session opened on a DONE card whose conversation is gone, or that never had
    one (`old` None), is told (c-787): the card's record, path by path, and that no worktree
    is open."""
    lost = (f"Its own conversation (session {old}) is gone, so you start with none of what it knew."
            if old else "It had no conversation of its own.")
    record = "\n".join(record_lines(card, card_dir, change, cfg, worktree=False))
    return REOPEN.format(id=card["id"], title=card.get("title") or "", lost=lost, record=record)


def record_lines(card: dict, card_dir, change: str = "change", cfg=None, worktree: bool = True) -> list[str]:
    """The card's record a session that lost its conversation reads, one line per path.
    `worktree`: the session runs in the card's worktree, so its branch's commits are there."""
    options = card.get("options") or {}
    if cfg is not None:
        from keel import merging      # noqa: PLC0415 - prompts is read by modules merging reads
        own = merging.card_base(cfg, card) or cfg.integration_of(card.get("space"), card.get("repo"))
    else:
        own = options.get("base")
    base = stacking.base_of(card) or own or (options.get("shipping") or {}).get("base")
    into = f", which merges into `{base}`" if base else ""
    if stacking.split_repos(card)[1]:
        # c-772: stacked in only some of its repos, so a base per repo: each by the one rule
        # when the config is at hand, else what the stack itself says
        each = {key: merging.base_in(cfg, card, key) if cfg is not None else stacking.base_of(card, key)
                for key in stacking.repos_of(card.get("repo"))}
        if len(set(each.values())) > 1:
            into = ", which merges into " + " and ".join(
                f"`{one}` in {key}" if one else f"its own base in {key}" for key, one in each.items())
    lines = [f"- `{card_dir}/context.md`: the outcome record (where it stands, why this shape, "
             f"the evidence)."]
    if card.get("plan_ref"):
        lines.append(f"- The plan the user approved: `{card['plan_ref']}` (a relative path is under `{card_dir}`).")
    if (Path(card_dir) / HANDOFF_FILE).is_file():
        lines.append(f"- `{card_dir}/{HANDOFF_FILE}`: the checkpoint that house wrote for whoever "
                     f"carries the card on (what is done, what is left).")
    if card.get("output_ref"):
        lines.append(f"- The outcome, its {change} when it has one: {card['output_ref']}")
    if options.get("branch"):
        where = "its commits are in your worktree (`git log`)" if worktree else "no worktree of it is open"
        lines.append(f"- The branch `{options['branch']}`" + into + f": {where}.")
    lines.append(f"- Everything else the card kept is under `{card_dir}/`.")
    return lines


def answer_resume(stage: str, said: str) -> str:
    """The resume a blocked house gets when he ANSWERED it (F1): his words quoted, then the
    plain resume. Before this the deck's Resume sent the plain line alone, so a house that
    had stopped to ask him something was woken with no answer, and his only way to give
    one was voice or dropping in at the desk. A blank answer is the plain resume."""
    words = str(said or "").strip()
    plain = RESUME.format(stage=stage)
    if not words:
        return plain
    return joined(
        "You were blocked, and the human answered from the deck. They said:\n\n" + quoted(words),
        REDIRECTED,
        "Take that answer into the work where it changes it, then " + plain + ".")


# RQ-1 (c-512): his words can change what the card IS; the card must then say so, since the
# deck, the gate and the history read the card, not the conversation. (The reviewer gets his
# words anyway: `requirements.md` carries them, `keel/review/gate.py`.)
REDIRECTED = ("If what the user said changes what this card is (a test or a report becomes a change to "
              "ship, another repo, another base), first make "
              "the card say so: `kb set $KEEL_CARD title=\"...\" brief=\"...\"`, the brief keeping "
              "what it had and adding the user's words, quoted, with what they change.")


def sendback_outcome(reason: str) -> str:
    """The prompt for work the human sent back from the outcome gate."""
    return joined(
        "The outcome was sent back. The human said:\n\n" + quoted(reason),
        REDIRECTED,
        "The card is at building again. Address that; when your brief has a pre-gate "
        "pipeline, run it on the changed branch (one full review for this trip, then a delta "
        "check of your fixes; verify, preship, risk). Then "
        "`kb stage $KEEL_CARD review --output <ref>` and end your turn.")


def discussion(plan_ref: str, reason: str, idle_seconds: int = IDLE_SECONDS) -> str:
    """The discussion loop: the house holds its slot and talks on the surface."""
    return joined(
        "The human wants to talk the plan through on the surface before you build. They said:"
        "\n\n" + quoted(reason),
        "The card stays at planning with its gate open for the whole discussion. Do not "
        "stage the card, do not start building, and do not approve anything yourself.",
        "Run the discussion loop:\n\n"
        f"1. `timeout {idle_seconds} lavish-axi poll {plan_ref}` and leave it in the "
        "foreground. It is silent until the user sends something; that silence is the discussion, "
        "not a hang.\n"
        "2. When it returns the user's feedback, act on it: update the plan file in place when the "
        "discussion changes the plan, and answer the user in the surface with the next poll:\n"
        f"   `timeout {idle_seconds} lavish-axi poll {plan_ref} --agent-reply \"<your "
        "answer, or what you just changed>\"`.\n"
        "3. Repeat. Each poll is one turn of the conversation.",
        "If the first poll comes back at once with an error instead of waiting, the surface "
        f"is not open: run `lavish-axi --no-open {plan_ref}` and poll again. If that fails too, say so "
        "with `kb note $KEEL_CARD` and end your turn rather than spinning.",
        "End the discussion, and your turn, when the poll reports the session ended (the user's "
        "Send & End, or `lavish-axi end` run from the deck), or when a poll returns nothing "
        f"at all: that is the {idle_seconds} second idle timeout and it means the user has gone "
        "quiet. Before you end the turn, leave the plan file saying what you both settled, "
        "and `kb note $KEEL_CARD` one line with where it stands. The user approves or sends back "
        "from the deck.")


# ----- a connected turn (V4) -----

# What a house is told when he is TALKING to it (`keel converse`). Three things it cannot
# work out for itself, and one it must never get wrong:
#
# - the answer is going to be SPOKEN, so it is sentences and not a screen of markdown;
# - his words arrived through speech recognition, so a name or a number may be wrong;
# - and the house has its real tools, its real worktree and no permission prompts. A
#   misheard sentence must not be able to delete, push, merge, stage the card, spend money
#   or send anything outward without him hearing it back first. Reading, explaining and
#   editing its own plan or its own worktree need no confirmation: that is the whole point
#   of talking to it.
SPOKEN = ("You are being spoken to out loud, through the voice gateway, about this card. "
          "Answer in one to three spoken sentences, plain words, no markdown, no file paths "
          "and no identifiers the user did not ask about. Give the answer itself and nothing "
          "before it: what you are doing while you work is already being said for you, so "
          "a line announcing what you are about to do is one the user hears instead of the "
          "answer. "
          # THE HOUSE'S OWN WAY OUT (2026-09-21). He said "Okay, you can exit the pouse
          # now" and the house answered "I can't end my own session, tap Stop on the
          # deck", which was true and is what this line changes. It is the SECOND net: the
          # gateway matches the leaving words itself and never asks a model, and this
          # catches the wording the matcher does not, because the house hears the whole
          # sentence in context. `keel converse` strips the token from what is spoken and
          # reports it, and the gateway then leaves exactly as it does for a spoken phrase.
          "If the user is asking you to leave, to exit, to go back to Harbor, or to end this "
          "conversation, do not explain that you cannot: reply with one short sentence of "
          "goodbye and write <<keel-leave>> on its own line at the end of your answer. "
          "That is what ends it, and nothing may follow it.")
MISHEARD = ("The user's words reached you through speech recognition and may be misheard. Before "
            "anything destructive or hard to reverse (deleting, force-pushing, merging, "
            "staging or approving this card, spending money, or sending anything outward) "
            "say back what you understood and wait for a spoken yes. Reading, explaining, "
            "and editing your own plan or your own worktree need no confirmation.")
STILL_YOURS = ("Your own brief still governs what you may do, and the card's gates are "
               "unchanged: this is a conversation inside your turn, not a new instruction "
               "from the board.")
# A done card's house has no worktree left (it was reaped on the merge), so it can account
# for what it did and nothing else. V4 names this case.
NO_WORKTREE = ("This card is done and its worktree is gone, so you can explain what you did "
               "but you cannot change anything. If the user is asking for a change, say so and "
               "offer to put it on a new card.")


def report_block(report: str) -> str:
    """The last turn's board report (C1), said to the house so it repairs it now."""
    return report.strip()


# THE BOARD'S CURRENT RULES (C4). A house spawned before a grammar change carries the old
# one in its brief, so the card generated from the parser rides on a conversation's first
# sentence, and on a later one when the card says this house has not been given it.
GRAMMAR_INTRO = ("If the answer is a shape, draw it on your card's board. These are the "
                 "board's current rules, and they replace any older ones in your brief:")


def grammar_block() -> str:
    from keel import boardgrammar               # noqa: PLC0415 - boards is heavy; say it only here
    return f"{GRAMMAR_INTRO}\n\n```\n{boardgrammar.grammar_card()}\n```"


def converse(said: str, worktree: bool = True, report: str = "") -> str:
    """The FIRST sentence of a connected conversation: the rules, then his words.

    Every sentence carried these three paragraphs while a connected turn was one process
    per sentence, because each of those processes arrived knowing nothing. A kept-alive
    conversation (V12) is one process for the whole conversation, so the rules are in its
    transcript after the first sentence and repeating them is tokens spent saying something
    it has already been told. `converse_more` is what every later sentence carries.
    """
    return joined(SPOKEN, MISHEARD, STILL_YOURS if worktree else NO_WORKTREE,
                  grammar_block(), report_block(report), "The user said:\n\n" + quoted(said))


def converse_more(said: str, report: str = "", grammar: bool = False) -> str:
    """A later sentence of the same conversation: his words, and nothing else.

    STILL QUOTED, for the reason the first one is: what arrives is speech recognition's
    best guess at a person talking, and a multi-line guess that was not quoted could read
    as an instruction of its own.
    """
    return joined(grammar_block() if grammar else "", report_block(report),
                  "The user said:\n\n" + quoted(said))


def merge_main(target: str, branch: str) -> str:
    """The outcome was approved but `target` moved past the branch and the merge conflicts:
    the house brings its branch up to date, the human approves again. `target` may name
    several refs, comma separated (an integration branch, then the trunk his own commits are
    on, c-526): the house merges each in turn."""
    refs = [ref for ref in target.split(",") if ref]
    if not refs:        # the refusal named no branch (c-665): said as that, never a guessed name
        return joined(
            f"Your outcome was approved, but its target branch has moved since you branched and "
            f"merging `{branch}` into it conflicts. In your worktree: merge its target branch "
            f"in (the branch this card lands on; `git merge <that branch>`), resolve every "
            f"conflict by intent (keep both sides' purpose, never pick lines blindly), run the "
            f"tests, commit the merge, update context.md's Where it stands (and, when your brief "
            f"has a pre-gate pipeline, review again if resolving the conflict changed your "
            f"change), then `kb stage $KEEL_CARD review --output \"{branch} @ <sha>\"` and end "
            f"your turn. The human approves again and the merge is then clean.")
    target = refs[0]
    merges = ", then ".join(f"`git merge {ref}`" for ref in refs)
    return joined(
        f"Your outcome was approved, but `{target}` has moved since you branched and merging "
        f"`{branch}` into it conflicts. In your worktree: {merges}, resolve every "
        f"conflict by intent (keep both sides' purpose, never pick lines blindly), run the tests, "
        f"commit the merge, update context.md's Where it stands (and, when your brief has a "
        f"pre-gate pipeline, review again if resolving the conflict changed your change), "
        f"then `kb stage $KEEL_CARD review "
        f"--output \"{branch} @ <sha>\"` and end your turn. The human approves again and the "
        f"merge into `{target}` is then clean.")


def quoted(reason: str) -> str:
    """The human's words, quoted so a multi-line reason cannot read as an instruction."""
    return "\n".join("> " + line for line in str(reason).strip().splitlines() or ["(no reason given)"])


# ----- what a house can do -----

ATLAS = """\
### When you do not understand something

`$KEEL_HOME/docs/atlas/` is how this whole setup works, one page per part: the board and
its gates, houses, the drain, the deck, the adapters, the segments, the worktrees and the
dev stack, the memory system, the skills. Read the page before you read the code. It is
faster, and it carries the reasons and the recorded facts the code cannot state. Start at
`00-start-here.md`, whose "Where to look for what" table is the index. {tail}
"""

ATLAS_WRITE = ("If your card changes any part of Keel itself, the change includes that part's "
               "Atlas page in the same commit: a drift test fails when the two disagree.")
# A confined house is given the directory so it can READ it, and the editing tools are
# denied there (`house.atlas_deny`), so the brief says what it may do with it rather than
# leaving it to find out one refusal at a time.
ATLAS_READ = ("That directory is open to you for reading and no more: Write and Edit are "
              "refused there, because a page is changed by a card with a repo and a "
              "worktree, not from a house that has neither. Something the Atlas gets wrong "
              "is worth a line through `kb note $KEEL_CARD`.")

KEEL_TESTS = ("Iterate with `make test-changed`, which runs only the tests your change can "
              "reach and says why, and falls back to every test when it cannot tell. It is "
              "also what you run before review (the pipeline's Verify step below): `make test`, "
              "the core suite and what the change reaches, runs once per change, on the merged "
              "tree where it lands (c-544, c-646). `make test-core` is the core suite alone; "
              "`make test-all` is every test, voice included, and what every deploy runs "
              "before main moves.")

NEW_PROJECT = """\
### This card opens a new project

`{path}` is a fresh repository. Keel created it when your house started (`main`, one
commit, a README naming this card) and cut your worktree from it, so everything in it
after that README is yours to shape and nothing depends on it yet.

The plan comes first, before any code: what this project is, what it is made of, how it
is run and tested, and what the first slice actually builds. Say what you are NOT building
yet as plainly as what you are. Then build it in your worktree and commit there as usual;
the outcome gate merges your branch into `main` the way it does for any repo card.
"""

SURFACE = """\
### What a surface you write looks like

The deck is this project's design system, and your space's palette is already beside your
card: Keel copied `$KEEL_HOME/app/theme-{space}.css` to
`$KEEL_CARD_DIR/theme.css` when you started. Write the plan, the report
or the mockup in plain semantic HTML and link it as the first thing in the file:

    <link rel="stylesheet" href="theme.css">

- The stylesheet sits in the SAME directory as the HTML and the path is relative with no
  leading slash: that is what lavish requires of a local asset. Writing the surface
  somewhere else? Copy the theme next to it first:
  `cp $KEEL_HOME/app/theme-{space}.css <that directory>/theme.css`.
- Use its tokens and NO other design system. This overrides lavish's "decide the design
  direction" priority list: this theme is step 2 of that list, so stop there. Do not load
  Tailwind or DaisyUI and do not invent a second palette. Headings, paragraphs, tables,
  lists, code and quotes are already styled; `.panel`, `.tile`, `.pill` (`.accent`,
  `.good`, `.warn`, `.crit`), `.grid`, `.label`, `.mono` and `.muted` are there when you
  want them. It is dark, it paints the page surface itself, and it holds the deck's
  budgets: four type sizes, two weights, a 4px grid, square boxes, soft pills.
- Nothing you run opens a browser at the user's desk. Open a surface with
  `lavish-axi --no-open <file>`: the user reads it from the deck, on a phone as often as at
  the desk, and a tab opened on this machine is a tab nobody may be sitting in front of.
  A house's `open` opens nothing either: it writes the URL to
  `$KEEL_CARD_DIR/opens.log` and notes it on the card.
- To LOOK at a page yourself (did this HTML render, is that CSS bug real, what does it do at
  phone width), `keel-browser` is the only browser tool and it is already on your PATH:
  `keel-browser shot <url> <out.png> [--width 390 --height 844]`, with `dom`, `eval` and
  `requests` beside it. It takes a fresh context every run, so it can see a page and can
  never be the user on one, and it tears the browser down however the run ends. Do not build your
  own and do not reach for another. A card that drives a browser carries `options.browser`;
  if yours does not, say so on the card rather than starting one anyway.
"""

# A repo the install copied (c-678): what its adopted CLAUDE.md says about running its app.
# Until it says how, the session runs tests only; the board holds the part that is a
# mechanism, since a card on such a repo cannot carry `options.browser`.
TESTS_ONLY = """\
### Running the app

Run this repo's tests only. Its CLAUDE.md does not say how to run the app yet, so
do not start the app, a dev server or anything that listens on a port, and do not use a
browser: a card on this repo cannot carry `options.browser`. If the work cannot be checked
without running the app, say so on the card and stage review with what the tests show.
The file is {tier}.
"""
RUNS_APP = """\
### Running the app

This repo's CLAUDE.md says how to run its app: `{command}`. Run it that way and no other,
so the owner's own running copy is never touched. The file is {tier}.
"""


def app_block(tier: str, command: str | None) -> str:
    """The "Running the app" section for a repo the install copied: the command its file
    names, or tests only."""
    return RUNS_APP.format(tier=tier, command=command) if command else TESTS_ONLY.format(tier=tier)


# Only a house whose repo IS Keel gets this: only a worktree of this checkout reads the shipped
# example config, so only there is a scratch board the default.
SCRATCH = """\
### Running a deck or a voice gateway from your worktree

Your worktree has a board of its OWN, and you cannot reach the user's by accident. With no
config of its own, your worktree reads the shipped example (`etc/shipyard.example.toml`),
whose `state_dir` is anchored to a home and not to your worktree, so the load gives the
worktree its own `state/` and `segments/` instead, and `bin/kb` here,
`bin/keel serve` here and a voice gateway here all open a scratch board that did not exist
before, and each one says `scratch` in its first line. Nothing you start here can file a
card on the user's board.

- **A scratch deck**:
  `bin/keel serve --port <a port nothing else uses>` from your worktree, its pid in a file
  of your own, stopped with `kill <pid>` and never by pattern. Seed it with `bin/kb` from
  the same worktree; both open the same scratch board.
- **A scratch voice gateway**: `KEEL_HOME=<your worktree>` plus a port of your own, so its
  `kb`, its transcript, its recordings, its filler cache and its judge log are all your
  worktree's. It prints the board and the state directory before it binds, and it refuses
  to start when its own code is a worktree's and the `kb` it would call is the live
  checkout's.
- **The live board** is reached only through the live checkout's `kb`, by the absolute path
  the card block below names. `KEEL_LIVE_STATE=1` is the override and is not yours to set.
"""

HUMAN_SEES = """\
### What the human can see

- Every markdown file under `$KEEL_CARD_DIR/` is listed on the card and opens in the deck's
  rich viewer (`/file/<card>/<name>`), the plan's own renderer: boards, tables, callouts,
  mermaid and every fenced block of the plan format draw there. A link from your outcome to
  one (`[the appendix](appendix.md)`) opens it there too. Other files open by a link from a
  markdown file: HTML, PNG, PDF and plain text.
- Nothing in your worktree is visible to the user, and neither is your terminal. If it matters,
  it goes in the card directory or through `kb note`.
- A screenshot is evidence only once `context.md` embeds it:
  `![what it shows](assets/<file>)`. A file sitting in `assets/` that nothing embeds is a
  file the user will never look at.
"""

# The two bullets that only make sense where lavish can be run. A fenced house's Bash
# reaches the board and nothing else, so promising it a surface promises a command it will
# be refused.
LAVISH_SEES = """\
- A plan that is a lavish surface must be opened before you end the turn
  (`lavish-axi --no-open <file>`), or the user has nothing to annotate.
- On resume you get one bounded poll for the user's annotations; the prompt that resumes you says
  so. In a discussion you stay in the poll loop instead, and that is the only time a house
  waits on a human.
"""

FENCED_SURFACE = """\
### What you write, and in what form

`lavish-axi` is not one of the two commands your Bash allows, so you cannot open a surface
for the user to annotate. Write the plan, and anything else the user reads, as markdown under
`$KEEL_CARD_DIR/`, even where `options.plan_style` says `auto`: the deck
renders markdown with the images it embeds. HTML renders there too and this space's palette
is already beside your card (`<link rel="stylesheet" href="theme.css">`), but nothing can
annotate it, so the page is the form unless the card asks otherwise.
"""

CHILD_CARDS = """\
### Splitting the work outward

Two different things, and the board treats them differently.

**A follow-up, or work someone else will do.** Anything you are not doing on this card: a
bug you found on the way, a second repo's half, a question for later. File it with
`--from`, which records where it came from and leaves YOUR card and its gates exactly as
they are:

    kb create --space <your space> --title "..." --brief "..." --repo <name> --from $KEEL_CARD

**A real split of your own card's work into slices.** At the plan gate, when the work is
too big for one house:

    kb split $KEEL_CARD --slice "title|brief[|after-title|...][|repo=key[,key]]" ...

That turns your card into a tracking card: its stage follows its children, it has no gate
of its own, and you can no longer stage it or reach review. So it is the deliberate way to
cut up your own work and never the way to file a follow-up. `kb create --parent` is the
same thing by hand and is refused on a card a house is working, which is why `--from` is
above. `|after-title` makes one slice wait for an earlier one; name several
(`|a|b`) and it waits for all of them. A slice takes every repo your card names. When
your card names several and a slice needs fewer, say which in the plan and state them on
the slice (`|repo=<key[,key]>`), so it is never held for a worktree in a repo it does not
touch.

A card that must change code needs `--repo <name>`. Without one it is an errand: no
worktree and no checkout, so it cannot change a line whatever its title says. Inward
parallelism is different again: that is subagents inside your own house, and it needs no
card at all.
"""

FALLBACK_VERBS = """\
- `kb show <id> [--json]`: the card and its recent events, including your own
- `kb list [--stage S] [--space S]`: the board
- `kb stage <id> <stage> [--plan REF] [--output REF] [--note ...]`: move the card
- `kb set <id> field=value ...`: a card field (`options.k=v` is one too)
- `kb note <id> "text"`: one short line for the human
- `kb block <id> "reason"` / `kb unblock <id>`: stop and ask, or take it back
- `kb block <id> --keel "what Keel did"`: Keel itself is in the way; files it with Bosun
- `kb console ask "what Keel did"`: tell Bosun Keel got in the way, and carry on
- `kb create --space S --title T [--parent <id>] [--after <id> ...]`: another card
"""

BASH_TOOL = "Bash"
WEB_TOOLS = ("WebSearch", "WebFetch")
WEB = """\
### The web

{tools} are yours:
search and read public pages for what the card needs. Reading only: no sign-in, no form,
nothing posted anywhere. Say in what you write which pages a claim came from.
"""
# The fence's own refusal, quoted in the brief so a house recognises the line when it sees
# it. `bin/keel-board-fence` prints it; `tests/test_prompts.py` holds the two together.
FENCE_LINE = "this house is confined to the board: kb, keel deck and keel board only"

# c-730 r2.F3: what a fork's review house is told, after the fence it shares with an errand
FORK_REVIEW = """\
### A fork's code is read here, never run

This card reviews a change from a fork: code from outside the team. Your house runs in
its checkout, confined, and the repo's own settings are not loaded. Read the code with Read,
Grep and Glob, and never run any of it: no build, no test, no script, no package install.
Besides the board, your Bash runs Keel's two review steps by absolute path, `{review} prep`
and `{review} draft`, exactly as the review section gives them; everything else is refused.
Write your record in your card directory, as your ending says."""

FENCE = """\
### What your Bash may run

This house runs in its card directory and its shell reaches the board, nothing else. Three
commands are allowed, by ABSOLUTE path, one plain command per call:

    {kb} <verb> ...
    {keel} deck ...
    {keel} board push --card $KEEL_CARD --file <ops file>

The third one draws on the blackboard, and `keel board list`, `find` and `show` are yours
too, and so is `keel board delete <b-id>` for YOUR card's boards only (it goes to a trash
the user can restore from for 30 days). `open`, `new`, `close` and `restore` are not: they decide
whose board is live, end a sitting or undo the user's trash, and they are the user's or the talker's. `push` normally reads its ops on stdin, which you cannot
give it here, so write the lines into a file in your card directory with Write and name
that file.

Everything else is refused before it runs, by a hook, with this line and the reason:

    {line}

A chain (`;`, `&&`, `||`, a pipe), a redirect, a backtick, a `$(...)`, an env-var prefix, a
`cd` first, and `kb` by its bare name are all refused too: write the absolute path above,
one command per call. Read, Write, Edit, Glob and Grep are how you do everything else, and
they reach your card directory and the directories this card opened for you. If the work
genuinely needs a shell, say so with `kb block $KEEL_CARD "<what it needs>"`: it wants a
repo card, not this one.
"""

DROP = """\
### Your output is the file you write

This house has no shell, so there is no board command here and nothing for you to run. What
you produce is one file:

    {where}

Write it, then end your turn. Keel reads that file when your turn ends and files the card
itself, with the file as the card's output, so you never stage the card and never approve
anything. If the file is not there, you are sent back with its path. Nothing else is yours
to write.
"""

NO_SHELL_SEES = """\
### What the human can see

Every file under `$KEEL_CARD_DIR/` is the user's to open from the deck, and
nothing else you touch is. You cannot leave the user a note through the board from this house,
so anything the user has to know goes in the file you write. If something cannot be answered, say
that IN the file rather than leaving it out: a missing answer reads as a missing run.
"""

VERBS_HEADING = "### The board, through `kb`"
APPROVALS_LINE = ("Approvals are the human's alone: no verb here approves a gate, and a house "
                  "never ends a session, its own or another's.")
FALLBACK_NOTE = ("(`kb help` was not available when this brief was written, so this list is the "
                 "short one. `kb <verb> --help` still works.)")


def tool_names(tools: str | None) -> list[str] | None:
    """The names in a `--tools` list, or None for a repo card, which has everything."""
    if tools is None:
        return None
    return [name.strip() for name in tools.split(",") if name.strip()]


def has_bash(tools: str | None) -> bool:
    """True when this tool list carries Bash; None is a repo card, which has everything.

    The rule lives here because it decides what the brief may PROMISE. A brief that names
    a command the tool set denies is the whole of c-270 and c-271 (2026-09-18).
    """
    names = tool_names(tools)
    return names is None or BASH_TOOL in names


def web_tools(tools: str | None) -> list[str]:
    """The web tools a confined house's list carries, in `WEB_TOOLS` order.

    A repo card (None) gets none named: it has the full set and its brief says nothing
    about tools it was never denied."""
    names = tool_names(tools) or []
    return [name for name in WEB_TOOLS if name in names]


def web_block(tools: str | None) -> str:
    """The sentence that says the web is there, read off the same list `--tools` gets, so
    it appears exactly when the tools do (c-291 had no web and could only say so)."""
    found = web_tools(tools)
    if not found:
        return ""
    return WEB.format(tools=" and ".join(f"`{name}`" for name in found))


def allowed_verb(verb: str) -> bool:
    return verb not in FORBIDDEN_VERBS and FORBIDDEN_SUBSTRING not in verb


def verb_lines(help_text: str) -> list[str]:
    """`kb help`'s `<verb> <usage>: <sentence>` lines as bullets, the forbidden ones gone."""
    lines = []
    for raw in help_text.splitlines():
        match = VERB_LINE.match(raw.strip())
        if not match or not allowed_verb(match.group(1)):
            continue
        usage = (match.group(1) + match.group(2)).strip()
        lines.append(f"- `kb {usage}`: {match.group(3).strip()}")
    return lines


def board_verbs(cfg, env: dict, run=subprocess.run) -> tuple[str, str | None]:
    """The verb bullets from `kb help`, or the hand-written fallback and why it was used."""
    kb = cfg.root / "bin" / "kb"
    try:
        result = run([str(kb), *HELP_ARGV], capture_output=True, text=True, env=env,
                     timeout=HELP_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        return FALLBACK_VERBS.strip(), f"kb help could not run ({error})"
    if result.returncode != 0:
        reason = (result.stderr or result.stdout or "").strip().splitlines()
        return FALLBACK_VERBS.strip(), f"kb help exited {result.returncode}" + (
            f": {reason[-1]}" if reason else "")
    lines = verb_lines(result.stdout)
    if not lines:
        return FALLBACK_VERBS.strip(), "kb help printed no verb lines"
    return "\n".join(lines), None


def surface_block(space: str, plan_pages: bool = False) -> str:
    """The theme section, with the space's own theme file named in it.

    The copy is a mechanism (`house.ensure_theme` puts `theme.css` beside the card before
    the house reads this), so the section's job is the link tag, the rule that this theme
    is the only design system, and the no-browser rule that goes with opening a surface.
    With the plan pages on, the plan and the outcome are the plan format and never HTML,
    so the section is about a report or a mockup only."""
    text = SURFACE.format(space=space)
    if plan_pages:
        text = text.replace(planbrief.PLAN_AS_HTML, planbrief.REPORT_AS_HTML)
    return text


def fence_block(cfg) -> str:
    """What a fenced house may run, in the words of the hook that enforces it.

    A confined house's Bash exists so it can reach the board; `bin/keel-board-fence` is
    what keeps it to that. The brief says so because the alternative is a house learning
    the rule one refusal at a time, which is exactly the cost the fence is meant to avoid.
    """
    return FENCE.format(kb=cfg.root / "bin" / "kb", keel=cfg.root / "bin" / "keel",
                        line=FENCE_LINE)


def board_block(cfg=None, restricted: bool = False) -> str:
    """The board section: its verbs and the current grammar card, generated here rather than
    written into the contract, so a new brief always carries the grammar the parser reads.
    A fenced house is given the form its fence lets through (`bin/keel-board-fence`)."""
    from keel import boardgrammar               # noqa: PLC0415 - boards is heavy; say it only here
    return boardgrammar.brief_block(str(cfg.root / "bin" / "keel") if restricted and cfg else None)


def atlas_block(restricted: bool = False) -> str:
    """The Atlas section, ending in what this house may do with the pages.

    A repo card can change a page and has to; a confined house is handed the directory as
    an add-dir with the editing tools denied on it, so it is told that instead.
    """
    return ATLAS.format(tail=ATLAS_READ if restricted else ATLAS_WRITE)


def new_project_block(path: str | None) -> str:
    """The section a card that opens a new repository gets: the path, and plan first."""
    return NEW_PROJECT.format(path=path)


def drop_block(drop: str | None) -> str:
    """The brief for a house with no shell: its output is a file, and Keel files the card.

    A brief that ends in a command a house has no tool for is the defect this block exists
    to close (c-270, 2026-09-18). Nothing here names a verb, because none is reachable.
    """
    where = drop or "the file the brief below names"
    return DROP.format(where=where)


def abilities(cfg, env: dict, run=subprocess.run, space: str = "personal",
              tools: str | None = None, restricted: bool = False,
              drop: str | None = None, new_project: str | None = None,
              keel_repo: bool = False, review: str | None = None,
              plan_pages: bool = False, app: str | None = None,
              waiting: list[dict] | None = None) -> tuple[str, str | None]:
    """The whole "What you can do" block, and the warning to log when `kb help` was missing.

    Three shapes, one per placement ([houses](docs/atlas/20-houses.md)): a repo card gets
    the board and the surface; a fenced errand gets the board and the fence's own rule; a
    house with no Bash gets neither, because it can run neither, and is told that its
    output is the file it writes. A confined house whose list carries the web tools is told
    so, in either confined shape (`web_block`).

    `keel_repo` adds the scratch-board section, and only for a card whose repo is Keel
    itself: a worktree of any other repo has no Keel config to resolve the live board from,
    so the section would be about something that house cannot do.
    """
    if not has_bash(tools):
        return joined("## What you can do", drop_block(drop), web_block(tools),
                      NO_SHELL_SEES) + "\n", None
    verbs, warning = board_verbs(cfg, env, run=run)
    parts = ["## What you can do", VERBS_HEADING, verbs]
    if warning:
        parts.append(FALLBACK_NOTE)
    parts.append(APPROVALS_LINE)
    parts.append(CHILD_CARDS)
    own = cfg.spaces.get(space) if getattr(cfg, "spaces", None) else None
    parts.append(planbrief.plan_block(plan_pages, getattr(own, "plan_style", None),
                                      stacks=space in getattr(cfg, "stacking", ()),
                                      change=space_change(cfg, space), waiting=waiting))
    if restricted:
        parts += [fence_block(cfg), web_block(tools),
                  planbrief.FENCED_FORMAT if plan_pages else FENCED_SURFACE, HUMAN_SEES]
    else:
        parts += [surface_block(space, plan_pages), HUMAN_SEES]
        if not plan_pages:
            parts.append(LAVISH_SEES)
        if keel_repo:
            parts += [SCRATCH, KEEL_TESTS]
    parts.append(board_block(cfg, restricted))
    if new_project:
        parts.append(new_project_block(new_project))
    if app:
        parts.append(app)         # tests only, or how to run the app (c-678, `app_block`)
    if review:
        parts.append(review)      # the pre-gate pipeline (keel/review/brief.py)
    parts.append(atlas_block(restricted))
    return literal_board_push(joined(*parts) + "\n", env), warning


# A board push's ops-file placeholder, as the brief sections write it
OPS_FILE = re.compile(r"--file <(?:ops file|ops|your ops file)>")


def literal_board_push(text: str, env: dict) -> str:
    """Every `board push` line of the brief with the card and its folder filled in (r-56,
    c-723). The house guard reads a `push` word beside a word the shell fills in as git run
    through a variable, so `keel board push --card $KEEL_CARD` as the brief wrote it was
    refused; the brief knows both when it is written. Unchanged without a card (a test)."""
    card, folder = env.get("KEEL_CARD"), env.get("KEEL_CARD_DIR")
    if not card or not folder:
        return text

    def filled(line: str) -> str:
        if "board push" not in line:
            return line
        line = line.replace("$KEEL_CARD_DIR", folder).replace("$KEEL_CARD", card)
        return OPS_FILE.sub(f"--file {folder}/<ops file>", line)
    return "\n".join(filled(line) for line in text.split("\n"))


def space_change(cfg, space: str) -> str:
    """What the space calls a change (c-630), the core's word when it cannot be read."""
    try:
        from keel import terms     # noqa: PLC0415 - terms reads the packs
        return terms.of(cfg, space)["change"]
    except Exception:  # noqa: BLE001 - a brief is never held up by a word
        return "change"


def note_in_log(cfg, text: str) -> None:
    """One stamped line in the drain's log: a brief is assembled inside a drain pass, so
    that is where the operator looks for what happened while it was written."""
    try:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(cfg.logs_dir / "drain.log", "a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {text}\n")
    except OSError:
        pass
