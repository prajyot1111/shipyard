"""What his Ship checks at publish time, on the machine that holds the card's house (c-600
review): the worktree as it is NOW, never the drain's last pass.

Ship pushes whatever the worktrees hold. So, right before the adapter runs:

- **A worktree that has DIVERGED from its pull request's branch** is refused, always
  (c-653): it is ahead of that branch and behind it (the branch was rewritten outside
  Keel), so the push cannot succeed, and the push goes before any reply. The refusal is the
  record's own sentence (`options.shipping.local.said`) with the command that brings each
  worktree in line by hand (`keel/shipstep.py`, on one line here). A worktree that is only
  BEHIND is not refused: it has nothing to push, the adapter skips a push of a branch the
  remote already holds, and a kept reply or a draft still goes.
- **Nothing to ship** is refused, always: no commit the pull request lacks, no draft to mark
  ready, no kept reply not yet posted.
- **The house is in a turn** (`housejobs.working` on the harness's own row): what it is
  doing is not on the branch yet, or is half on it. Held.
- **The receipt does not cover HEAD** (`shipping.local_facts`: commits the pull request lacks
  and no review stamp, the receipt `keel check` writes, covers every worktree's head). Held.

A held Ship says why in one line starting `Ship held:` (the deck reads that and asks "Ship
anyway?"; `kb ship --anyway` is the terminal's answer). `anyway` is his explicit override
of a HOLD; it never ships nothing, and never a push that cannot succeed.
"""

from __future__ import annotations

from keel import terms

HELD = "Ship held: "
ANYWAY = "; Ship anyway to send it as it is"


class ShipRefused(ValueError):
    """Nothing is pushed or posted; the message says why in one line."""


def check(cfg, card: dict, answer: dict, anyway: bool = False) -> dict:
    """The worktrees' facts now; ShipRefused when this Ship must not run as asked."""
    from keel import shipping    # noqa: PLC0415 - shipping imports the adapters module that calls this
    try:
        facts = shipping.local_facts(cfg, card)
    except Exception as error:  # noqa: BLE001 - an unreadable worktree is a hold, never a guess
        facts = {"unreadable": str(error).splitlines()[0] if str(error) else type(error).__name__}
    t = terms.of(cfg, card.get("space"))
    empty = diverged(facts) or empty_ship(card, answer, facts, t)
    if empty:
        raise ShipRefused(empty)
    if anyway:
        return facts
    why = held(cfg, card, facts)
    if why:
        raise ShipRefused(HELD + why + ANYWAY)
    return facts


def diverged(facts: dict) -> str | None:
    """The record's sentence for a diverged worktree and, on the same line, the command that
    brings each worktree in line by hand (the very text the deck's block holds); None when no
    worktree has diverged."""
    if not facts.get("diverged"):
        return None
    chains = [one["command"] for one in facts.get("by_hand") or [] if one.get("command")]
    return facts.get("said", "") + "".join(f" `{chain}`" for chain in chains)


def empty_ship(card: dict, answer: dict, facts: dict, t=None) -> str | None:
    shipped = (card.get("options") or {}).get("shipping") or {}
    draft = bool((shipped.get("facts") or {}).get("draft"))
    if facts.get("ahead") or draft or answer.get("replies") or facts.get("unreadable"):
        return None
    return (f"nothing to ship on {card['id']}: no commit the {(t or terms.BASE)['change']} lacks, no draft, and "
            f"no kept reply that is not posted")


def held(cfg, card: dict, facts: dict) -> str | None:
    busy = working(cfg, card)
    if busy:
        return (f"{card['id']}'s {busy}, so what it is doing is not on the branch yet")
    if facts.get("unreadable"):
        return f"{card['id']}'s worktrees cannot be read ({facts['unreadable']})"
    if facts.get("unchecked"):
        return (f"{facts.get('ahead')} commit(s) on {card['id']} that no review receipt covers "
                f"(the house runs keel check)")
    return None


def working(cfg, card: dict) -> str | None:
    """`house is working (turn 4m)` when the harness says the card's house is in a turn;
    else None. Plain words (c-604): the held confirm printed the row's uuid and pid, which
    say nothing he can act on. The turn's age is the transcript's (`livetail`), as the live
    strip reads it; without one the words stand alone."""
    from keel import adapters, harness, house, housejobs    # noqa: PLC0415
    if not card.get("session_id"):
        return None
    space = adapters.space_of(cfg, card)
    try:
        # through `house.harness`, the one handle every caller (and every test) shares
        row = house.harness.find(card["session_id"], house.harness.agents(space.config_dir))
    except harness.HarnessError as error:
        return f"the harness cannot say: {str(error).splitlines()[0] if str(error) else 'no listing'}"
    if not housejobs.working(row):
        return None
    turn = turn_age(space.config_dir, card, row)
    return f"house is working (turn {turn})" if turn else "house is working"


def turn_age(config_dir, card: dict, row: dict) -> str | None:
    """How long the house's current turn has run, `4m` or `1h 5m`, from its transcript."""
    from datetime import datetime, timezone    # noqa: PLC0415
    from keel import livetail    # noqa: PLC0415
    try:
        record = livetail.job(config_dir, row.get("id") or "")
        path = livetail.transcript_path(config_dir, card.get("session_id") or "", row.get("cwd"),
                                        record.get("transcript"))
        began = livetail.tail(path).get("turn_at")
        seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(began)).total_seconds()
    except (TypeError, ValueError, OSError):
        return None
    minutes = max(0, int(seconds // 60))
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"
