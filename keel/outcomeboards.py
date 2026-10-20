"""`bin/keel-outcome-boards`: the backfill for C33 (c-602), a board-only turn for each card
whose outcome is already at his gate without boards drawn at the built head.

C33 holds a NEW outcome at `kb stage review`. An outcome written before it (c-573's
re-embedded b-156 and b-157) is only warned about on its page. This verb finds those cards and
asks each house, once, to draw what the brief now asks for: every plan board redrawn, one Code
flow board, the numbered reading order. The prompt is `PROMPT` here, around the brief's own
text (`planbrief.OUTCOME_BOARDS`), so the backfill asks for exactly what a new card is told;
the bulk regenerate before it (`bin/keel-plan-install`, LP-20) ran from a prompt that was never
in the repo.

It picks a card that a house built (`housed`: not archived, not done, not Bosun's: a Keel
card or any personal repo card in builder mode has no house and no outcome page), that is
at review or shipping, ships a change (`review.gate.ships_a_change`),
has an outcome in the format, and either breaks C33 (error or warning) or has a plan board last
drawn before his plan approval. The documents are read where they live (`planroute.read`).

Without `--run` it changes nothing: it prints each card it would pick, why, and the prompt.
With `--run` it records ONE `resume` relay per card, addressed to the house's machine, exactly
as a held tap is (`actions.hold_here`): that machine's drain tells an idle house in its own
session, holds it while the house works, and resumes an exited one. Nothing is stopped. Each
card it asked carries `options.outcome_boards_sent`, and a card whose house has not ended a
turn since is skipped by the next run (`pending`) unless `--force`.
"""

from __future__ import annotations

import argparse
import json
import sys

from keel import builder, config as config_module, planbrief, planformat, plangate, planoutcome, planroute
from keel.review import gate as review_gate

STAGES = ("review", "shipping")
# The board's record that a backfill was sent (c-602 review): `options.outcome_boards_sent`,
# `{at}`. While the house has not ended a turn since, the backfill is unanswered and a second
# `--run` skips the card rather than queue the same prompt twice; `--force` sends again.
SENT_OPTION = "outcome_boards_sent"
TURN_ENDS = ("Stop", "SessionEnd")
KEEL_REPO = "keel"          # Keel's own repo: its cards are Bosun's, never a house's

PROMPT = """\
Keel, c-602: a board-only turn on {card}. Your outcome is at the user's gate, and its boards are
the plan's drawing, not the code you built: {reasons}.

Do ONLY this, at your branch's current head. You are past Verify: draw the boards yourself
(or through one subagent you wait for), and write the result into context.md yourself:

{outcome_boards}
The plan's boards: {plan_boards}.

Change nothing else: no code, no commit, no push, and do NOT move the card (it stays at
{stage}). Edit only the outcome's board embeds and its `### Read it in this order`. Run
`kb lint {card} --outcome` until it prints no C33 finding, then end your turn.
"""


def plan_boards(cfg, card: dict) -> list[str]:
    """The board ids the card's plan embeds, when its plan is in the format and readable."""
    try:
        got = planroute.read(cfg, card, "plan")
    except Exception:  # noqa: BLE001 - a plan that cannot be read names no boards
        return []
    if not got.get("text"):
        return []
    return [b["ref"] for b in planoutcome.embedded(planformat.parse(got["text"], got["name"]))]


def housed(card: dict) -> bool:
    """A card a HOUSE built and still answers for: not archived, not done, and not Bosun's
    (a personal repo card in builder mode, `derived.bosun`, or a Keel card: Bosun builds
    those, with no house and no outcome page). Work cards and personal non-Keel repo cards."""
    derived = card.get("derived") or {}
    options = card.get("options") or {}
    if derived.get("archived") or options.get("archived") is True or card.get("stage") == "done":
        return False
    if derived.get("bosun"):
        return False
    repos = [r.strip() for r in str(card.get("repo") or "").split(",") if r.strip()]
    return not (card.get("space") == "personal" and KEEL_REPO in repos)


def check(cfg, card: dict, events: list[dict]) -> dict | None:
    """What is wrong with one card's outcome boards, or None when nothing is (or it is not
    a card this verb is for)."""
    if card.get("stage") not in STAGES or not housed(card) or not review_gate.ships_a_change(card):
        return None
    got = planroute.read(cfg, card, "outcome")
    if not got.get("text"):
        return None
    doc = planformat.parse(got["text"], got["name"])
    if doc["kind"] != "outcome":
        return None
    board_of, since = plangate.board_resolver(cfg), planoutcome.approved_at(events)
    findings = planoutcome.rules(doc, board_of, since)
    planned = plan_boards(cfg, card)
    stale = [ref for ref in planned if planoutcome.carried(planoutcome.pushed_of(board_of, ref), since)]
    embedded = {b["ref"] for b in planoutcome.embedded(doc)}
    reasons = [f["text"] for f in findings]
    reasons += [f"`{ref}` is the plan's board and the outcome does not embed it"
                for ref in stale if ref not in embedded]
    if not reasons:
        return None
    return {"card": card["id"], "stage": card["stage"], "title": card.get("title") or "",
            "host": cfg.host, "reasons": reasons, "plan_boards": planned,
            "folder": str(cfg.card_dir(card["id"]))}


def prompt_for(pick: dict) -> str:
    """The backfill's words, its board pushes naming the card and its folder literally
    (`prompts.literal_board_push`, c-723): the house guard refuses one with `$KEEL_CARD`."""
    from keel import prompts      # noqa: PLC0415 - the brief's module, for this one fill
    boards = ", ".join(f"`{ref}`" for ref in pick["plan_boards"]) or "none embedded; draw the Code flow board"
    text = PROMPT.format(card=pick["card"], stage=pick["stage"], plan_boards=boards,
                         reasons="; ".join(pick["reasons"]),
                         outcome_boards=planbrief.OUTCOME_BOARDS)
    return prompts.literal_board_push(text, {"KEEL_CARD": pick["card"], "KEEL_CARD_DIR": pick.get("folder") or ""})


def pending(card: dict, events: list[dict]) -> bool:
    """A backfill was sent and the house has not ended a turn since: it is still answering."""
    sent = ((card.get("options") or {}).get(SENT_OPTION) or {}).get("at")
    if not sent:
        return False
    since = planoutcome.when(sent)
    return not any(e["kind"] == "hook" and (e.get("data") or {}).get("hook") in TURN_ENDS
                   and since is not None and (planoutcome.when(e.get("at")) or since) > since
                   for e in events)


def select(cfg, board, only: list[str] | None = None, force: bool = False) -> list[dict]:
    """Every card the backfill would ask, oldest first; one it already asked and that has
    not answered is left out unless `force`."""
    cards = [board.get(cid) for cid in only] if only else \
        [c for stage in STAGES for c in board.list_cards(stage=stage)]
    picks = []
    for card in cards:
        if card.get("session_id"):
            events = board.events(card["id"])
            if not force and pending(card, events):
                continue
            pick = check(cfg, card, events)
            if pick:
                picks.append(pick)
    return sorted(picks, key=lambda p: int(p["card"].split("-")[1]))


def send(cfg, board, pick: dict, relay=None) -> dict:
    """ONE `resume` relay, as a held tap is; the drain carries it."""
    sent = (relay or resume_relay)(cfg, board.get(pick["card"]), pick["host"], "resume", prompt_for(pick))
    board.set_fields(pick["card"], {"options": {SENT_OPTION: {"at": board.now()}}}, "human")
    return sent


def resume_relay(cfg, card: dict, host: str, what: str, prompt: str) -> dict:
    """The relay as the deck writes one, through `kb` as him. `--bulk`: this pass asks many
    cards at once, so its relay never restarts a card's backlog clock (c-673)."""
    from keel import actions  # noqa: PLC0415 - the deck's verbs, loaded only for a real run
    actions.run_kb(cfg, ["relay", card["id"], what, "--to", host, "--bulk", "--prompt", prompt])
    return {"relayed": what, "to": host}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel-outcome-boards", description=__doc__.split("\n\n")[0])
    parser.add_argument("--card", action="append", metavar="c-NNN", help="only this card (repeatable)")
    parser.add_argument("--run", action="store_true",
                        help="relay the board-only prompt to each house (default: print what it would do)")
    parser.add_argument("--force", action="store_true",
                        help="ask a card again although its last backfill is unanswered")
    parser.add_argument("--json", action="store_true", help="the picks as JSON")
    return parser


def main(argv: list[str], cfg=None, board=None, relay=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = cfg or config_module.load(ensure=False)
    if board is None:
        from keel.board import Board  # noqa: PLC0415 - opened only when the caller gave none
        board = Board(cfg.db_path, switches=cfg.switches,   # builder mode decides `derived.bosun`
                      builds=builder.repos(cfg))
    picks = select(cfg, board, args.card, args.force)
    if args.json and not args.run:
        print(json.dumps(picks, indent=2))
        return 0
    for pick in picks:
        print(f"{pick['card']} ({pick['stage']}, on {pick['host']}): {pick['title']}")
        for reason in pick["reasons"]:
            print(f"  - {reason}")
        if args.run:
            print("  " + str(send(cfg, board, pick, relay).get("note") or "relayed"))
    if not args.run:
        print(f"dry run, nothing sent: {len(picks)} card(s) would be asked" +
              ("; the prompt for the first:\n\n" + prompt_for(picks[0]) if picks else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
