"""A space's flow, proposed by a house from the owner's words and adopted by their tap (c-640).

The tier card's pattern (`keel/tiercards.py`, c-618): Propose files a personal errand (a
card with no repo) whose brief carries the owner's words verbatim, the space's current flow
as a file, and the format (Atlas 64). The house writes `state/cards/<id>/flow.toml`, checks
it with `keel flow check --space <space>`, and stages review with that file as its output.
Adopt, the owner's tap on the proposal at review, checks it again, for the same space
(`keel/flowcheck.py`), and writes it to `<install>/spaces/<space>/flow.toml`; the card goes
to done and its finished house is stopped (`onboarding.adopt_flow`); Approve outcome on the
card is the same tap (`onboarding.adopt_proposal`, a tier proposal's too, c-667). Reset sets the space's own file aside as `flow-<stamp>.toml.bak`, so the
pack's or Keel's applies again.

The brief's short form of the format is WRITTEN FROM `keel/flows.py`'s own key lists
(`format_text`, c-664), so a key the check knows is a key the house is told.

A flow is read per state build, so nothing restarts: the next state draws the new flow.

A DRAFT CARD (c-678) is the same proposal with another worker: Bosun, in conversation with
the user, in its own session (the tier draft's pattern, `keel/tiercards.py`). `open_draft`
files it by the user's tap on How work ships, at `inbox`, so nothing starts on it. Bosun
stages it `building` when it starts and `review` when the flow checks, and writes the flow
in its own card folder, `<install>/builder/cards/<id>/flow.toml` (`draft_path`). `shown` is
what the Setup report carries of a space's open proposal, the draft drawn as a flow once it
is at review, so the page can put it beside the flow the space has now.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from keel import atomicfile, bases, flowcheck, flows, pausewake, terms, tiercards
from keel.config import Config
from keel.setupconfig import SetupError

OPTION = "flow_proposal"
DRAFT = "flow_draft"         # a proposal Bosun drafts with the user, not a house's (c-678)
PROPOSAL = "flow.toml"
CURRENT = "flow-current.toml"
WORDS_MAX = 8000
BRIEF = """Propose the flow of the {space} space: how its work moves from a card's branch to
where it ends up, written as a Keel flow file.

The owner's words, verbatim (they decide: write the draft from them, and where they leave
something out, write your best reading and say what you assumed in a note on the card):

{words}

The space's flow today is the file {current} ({source}). Read it first: keep what the words
do not change.

WHAT A FLOW IS, AND IS NOT. Only a move by `{you}` does anything: it is a button on the
card, and the tap tells the card's house the move's `prompt`. Every other move (by
{others}) is a PICTURE of what the space's pack and Keel already do, and writing it
differently changes the drawing, not what happens. So when the words ask for something only
such a move could say (who merges, a squash or a rebase, a condition like "after one
approval"), draw it as it really happens here and say on the card, in a note, that the flow
shows it and Keel will not carry it out.

{bases}

THE FORMAT is Atlas page 64 ({atlas}). In short:

{format}

Write the flow to {out}, then run `keel flow check {out} --space {space}` and fix whatever it
names: it refuses a move this space cannot run. When it passes, run
`kb stage {card} review --output {out}` and end your turn. Nothing changes until the owner
adopts it, from Settings or by approving this card's outcome; they may send it back with
what to change instead, and you then revise the same file.
"""


DRAFT_BRIEF = """Draft the flow of the {space} space with the user, in conversation, in Bosun's own
session: how its work moves from a card's branch to where it ends up, as a Keel flow file.

This card is Bosun's. No session is started on it: it waits at inbox until Bosun takes it.

ASK the user how their team ships, one question at a time, in everyday words, each with its
example (the setup page shows the user the same questions, and answers the first itself):

{asks}

{bases}

Whatever you cannot place from their answers, ask it back rather than guess: the drawing is
read by someone who has never seen Shipyard, and it must show what they said. The space's flow
today is the file {current} ({source}). Read it first: keep what the user does not change.

WHAT A FLOW IS, AND IS NOT. Only a move by `{you}` does anything: it is a button on the
card, and the tap tells the card's house the move's `prompt`. Every other move (by
{others}) is a PICTURE of what the space's pack and Keel already do, and writing it
differently changes the drawing, not what happens. When the user asks for something only
such a move could say (who merges, a squash or a rebase, a condition like "after one
approval"), draw it as it really happens here and tell the user, in your session, that the
flow shows it and Keel will not carry it out.

THE FORMAT is Atlas page 64 ({atlas}). In short:

{format}

Write the flow to {out}. Its `description` is what the setup page shows as "What you told
Bosun", beside the drawing: one or two plain sentences of what the user said, in their words.
Give every move an `about`, one line of what happens on that arrow ("Every Friday, a teammate
merges staging into main."): the page draws it on the arrow and reads the arrows back as a
sentence under the drawing, so the user can see the two match. Run
`keel flow check {out} --space {space}` and fix whatever it names: it refuses a move this
space cannot run, and a draft that does not check is not shown to the user.

Run `kb stage {card} building` when you start, and `kb stage {card} review --output {out}`
when it checks. The user sees it on the setup page beside the flow the space has now and
presses Adopt, or keeps the one they have; nothing changes before that. When the user asks
for a change, edit {out}: the page shows the file as it is now.
"""


def asks_text() -> str:
    """How work ships' questions (`bases.ASKS`), numbered, each with its example and where it
    is answered, for Bosun's brief: the page shows the user the same list."""
    return "\n".join(f"{n}. {one['ask']} For example: \"{one['example']}\"."
                     + (" (The page asks this one and stores the answer as the space's bases.)"
                        if one["where"] == "page" else "")
                     for n, one in enumerate(bases.ASKS, 1))


def listed(names) -> str:
    return ", ".join(f"`{name}`" for name in names)


def format_text(t=None) -> str:
    """The format in short, from the schema's own lists (`flows.TOP_KEYS` and the rest), so
    it cannot name a key the check does not know or leave one out. `t`: the space's terms."""
    steps = "; ".join(f"{who}: {', '.join(names)}" for who, names in flows.STEPS.items())
    housed = ", ".join(stage for stage in flows.STAGES if stage not in flowcheck.HOUSELESS)
    fields = ", ".join("{" + name + "}" for name in flows.FIELDS)
    change = (terms.BASE if t is None else t)["change"]
    lines = [
        f"- Top level: {listed(key for key in flows.TOP_KEYS if key not in ('branch', 'move'))}, one "
        f"`[[branch]]` per branch or environment, one `[[move]]` per move.",
        f"- `[[branch]]`: {listed(flows.BRANCH_KEYS)}. `kind` is one of {', '.join(flows.BRANCH_KINDS)}; "
        f"exactly one branch, the card's own, has kind card. An id is at most {flows.ID_MAX} "
        f"characters, a label {flows.LABEL_MAX}.",
        "- A LABEL IS THE BRANCH'S GIT NAME when it holds no space: `{base}` (the card's base) and "
        "`{branch}` (the card's own branch) in it are filled per card. A label in words names no "
        "branch, so no move can push it or open anything to it.",
        f"- `[[move]]`: {listed(flows.MOVE_REQUIRED)}, and optionally {listed(flows.MOVE_OPTIONAL)}. "
        f"`from` and `to` are two different branch ids.",
        f"- `by` is who makes it: {', '.join(flows.WHO)}. `step` is the existing step a drawn move "
        f"names ({steps}); a keel move must name one.",
        f"- A move by `{flows.YOU}` must say `stages` (when it is offered: {housed}, the stages a "
        f"card has a house at) and `prompt` (what the house is told to do, in full, as if you were "
        f"telling it yourself: the house resolves conflicts itself and says what it did; it may "
        f"name {fields}). Give it a `group`, the name of the button group it sits in on the card.",
        f"- `pushes` lists the branches that move may push to, and `opens` the branches it may open "
        f"a {change} to (only where the space's pack declares `{flowcheck.FLOW_PR}`): both name "
        f"branches whose label is a git name, never the card's own. Nothing pushes to a shared "
        f"branch except a move by `{flows.YOU}`.",
        "- `bases` limits a move to cards whose base is one of the names it lists; `about` is one "
        "line for the board and the button.",
        f"- Text a person reads may say `{{change}}` or `{{Change}}`, which is filled with the "
        f"space's own word for it (here: {change}).",
    ]
    return "\n".join(lines)


def proposals(board) -> dict[str, dict]:
    """The newest open proposal per space."""
    return proposals_in(board.list_cards(include_archived=False))


def proposals_in(cards: list[dict]) -> dict[str, dict]:
    """The same, from cards a caller already read (the state build's)."""
    found = {}
    for card in cards:
        if (card.get("derived") or {}).get("archived"):
            continue
        space = (card.get("options") or {}).get(OPTION)
        if space and card.get("stage") != "done":
            found[space] = {"card": card["id"], "stage": card["stage"], "waiting": bool(card.get("blocked_reason")),
                            "draft": bool((card.get("options") or {}).get(DRAFT))}
    return found


def adopted_in(cards: list[dict]) -> set[str]:
    """The spaces with a proposal card that is done: a draft of the flow was adopted there
    (c-678 review). A flow of the space's own with none was written another way."""
    return {space for card in cards
            if (space := (card.get("options") or {}).get(OPTION)) and card.get("stage") == "done"}


def propose(cfg: Config, board, space: str, words: str) -> dict:
    """File the card that proposes `space`'s flow from the owner's `words`."""
    if space not in cfg.spaces:
        raise SetupError(f"there is no space {space!r}")
    words = (words or "").strip()
    if not words:
        raise SetupError("say how the space ships: the branches, the moves, who makes each")
    if len(words) > WORDS_MAX:
        raise SetupError(f"keep it under {WORDS_MAX // 1000}k characters")
    open_one = proposals(board).get(space)
    if open_one:
        raise SetupError(f"{open_one['card']} is already proposing the {space} flow ({open_one['stage']})")
    current = flows.of(cfg, cfg.spaces[space])
    card = board.create(tiercards.errand_space(cfg), f"Propose the {space} flow", brief="",
                        autonomy="autonomous", options={OPTION: space}, actor="human")
    folder = cfg.card_dir(card)
    folder.mkdir(parents=True, exist_ok=True)
    now = folder / CURRENT
    atomicfile.write_text(now, current.path.read_text(encoding="utf-8") if current.path else "")
    atlas = cfg.root / "docs" / "atlas" / "64-flows.md"
    out = folder / PROPOSAL
    brief = BRIEF.format(space=space, words=words, current=now, source=current.source, bases=bases.said(cfg, space),
                         atlas=atlas, out=out, card=card, you=flows.YOU,
                         others=", ".join(who for who in flows.WHO if who != flows.YOU),
                         format=format_text(terms.of(cfg, space)))
    # Atlas 64 is its plan, as the template is a tier card's: review needs a plan_ref, and an
    # errand has no plan of its own to write.
    board.set_fields(card, {"brief": brief, "plan_ref": str(atlas)}, "human")
    board.stage(card, "assigned", "human")
    return {"card": card, "space": space}


def open_draft(cfg: Config, board, space: str) -> dict:
    """`setup.flow.draft` (c-678): file the card on which Bosun drafts `space`'s flow with the
    user. At `inbox`, so the drain starts nothing on it; filed as the human, who alone may
    make a proposal card."""
    if space not in cfg.spaces:
        raise SetupError(f"there is no space {space!r}")
    open_one = proposals(board).get(space)
    if open_one:
        raise SetupError(f"{open_one['card']} is already proposing the {space} flow ({open_one['stage']})")
    if tiercards.bosun_folder(cfg, "x") is None:
        raise SetupError("a draft is Bosun's to write with you, in an install: this config is not an install's")
    current = flows.of(cfg, cfg.spaces[space])
    card = board.create(tiercards.errand_space(cfg), f"Draft the {space} flow", brief="",
                        autonomy="autonomous", options={OPTION: space, DRAFT: True}, actor="human")
    folder = cfg.card_dir(card)
    folder.mkdir(parents=True, exist_ok=True)
    now = folder / CURRENT
    atomicfile.write_text(now, current.path.read_text(encoding="utf-8") if current.path else "")
    atlas = cfg.root / "docs" / "atlas" / "64-flows.md"
    out = tiercards.bosun_folder(cfg, card) / PROPOSAL
    brief = DRAFT_BRIEF.format(space=space, current=now, source=current.source, atlas=atlas, out=out,
                               asks=asks_text(), bases=bases.said(cfg, space),
                               card=card, you=flows.YOU,
                               others=", ".join(who for who in flows.WHO if who != flows.YOU),
                               format=format_text(terms.of(cfg, space)))
    board.set_fields(card, {"brief": brief, "plan_ref": str(atlas)}, "human")
    pausewake.tell(board, card, "filed", cfg=cfg)   # c-734: asks the drain for one pass, whose wake tells Bosun
    return {"card": card, "space": space, "note": f"{card} is open for Bosun to draft the {space} flow. {pausewake.TOLD}."}


def draft_path(cfg: Config, card_id: str) -> Path:
    """Where a card's proposal is: the card's own directory (a house's), else Bosun's folder
    for the card (a draft Bosun wrote, c-678). Two fixed places and nothing a card names, so
    no card can point Adopt at a file of its choosing (as `tiercards.draft_path`)."""
    mine = cfg.card_dir(card_id) / PROPOSAL
    bosun = tiercards.bosun_folder(cfg, card_id)
    if not mine.is_file() and bosun is not None and (bosun / PROPOSAL).is_file():
        return bosun / PROPOSAL
    return mine


def shown(cfg: Config, board, space: str) -> dict | None:
    """A space's open proposal for the Setup report (c-678): `{card, stage, draft, flow,
    error}`, or None with none open. `flow` is the proposal drawn as the deck draws a flow
    (`flows.public`), once the card is at review and its file checks for the space; a file
    that does not check is `error`, in the check's words, and no flow."""
    open_one = proposals(board).get(space)
    if not open_one or space not in cfg.spaces:
        return None
    out = {"card": open_one["card"], "stage": open_one["stage"], "draft": open_one["draft"], "flow": None, "error": None}
    if open_one["stage"] != "review":
        return out
    proposal = draft_path(cfg, open_one["card"])
    try:
        found = flows.parse_text(flows.read(proposal), str(proposal), "space")
        flowcheck.check(found, cfg, cfg.spaces[space], where=str(proposal))
        out["flow"] = flows.public(flows.worded(found, terms.of(cfg, space)))
    except flows.FlowError as error:
        out["error"] = str(error)
    return out


def adopt(cfg: Config, board, card_id: str) -> dict:
    """The proposal, checked again for its space, written as the space's own flow."""
    card = board.get(card_id)
    space = (card.get("options") or {}).get(OPTION)
    if not space:
        raise SetupError(f"{card_id} does not propose a flow")
    if space not in cfg.spaces:
        raise SetupError(f"{card_id} proposes a flow for {space!r}, which is not a space here")
    if card.get("stage") != "review":
        raise SetupError(f"{card_id} is at {card.get('stage')}; a proposal is adopted at review")
    target = flows.space_file(cfg, space)
    if target is None:
        raise SetupError("a space's own flow is kept in the install's spaces/ folder; this config is not an install's")
    proposal = draft_path(cfg, card_id)
    try:
        # read ONCE: what is written is exactly what was checked (c-640 review)
        text = flows.read(proposal)
        found = flows.parse_text(text, str(proposal), "space", target)
        flowcheck.check(found, cfg, cfg.spaces[space], where=str(proposal))
    except flows.FlowError as error:
        raise SetupError(f"the proposal does not check, so nothing was adopted: {error}") from None
    target.parent.mkdir(parents=True, exist_ok=True)
    atomicfile.write_text(target, text)
    return {"adopted": space, "flow": found.name, "path": str(target), "digest": tiercards.digest(text)}


def draft(cfg: Config, card_id: str) -> str:
    """The proposal a card holds now, read as Adopt reads it, or "" when it has none."""
    try:
        return flows.read(draft_path(cfg, card_id))
    except flows.FlowError:
        return ""


def reset(cfg: Config, space: str) -> dict:
    """The space's own file set aside as `flow-<stamp>.toml.bak`, so its pack's or Keel's applies."""
    if space not in cfg.spaces:
        raise SetupError(f"there is no space {space!r}")
    target = flows.space_file(cfg, space)
    if target is None or not target.is_file():
        return {"space": space, "note": f"{space} already uses the {flows.of(cfg, cfg.spaces[space]).source} flow"}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = target.with_name(f"flow-{stamp}.toml.bak")       # never over an earlier one
    target.replace(kept)
    return {"space": space, "note": f"{space} uses its pack's or Shipyard's flow again; the old one is {kept.name}",
            "kept": str(kept)}


def proposal_of(cfg: Config, card_id: str) -> Path:
    return draft_path(cfg, card_id)
