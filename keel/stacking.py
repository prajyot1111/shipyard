"""A waiting card stacked on the card it waits for, or independent of it (c-718).

A card whose `after` names another card waits for it today, and is cut from its base without
the other card's code. The owner's choice per waiting card, recorded on the card as
`options.stack`:

- **stacked**: its branch is cut from the branch of the card it waits for (its PARENT, the
  one card its `after` names) and its change aims at that branch, so it can never merge
  first and its review shows only its own commits. It may start once the parent has a
  branch pushed (`pushed`: the parent records a change, `options.pr` or `options.prs`, or
  it is at review, shipping or done). When the parent lands, the base is the card's own
  again (`base_of` answers None), and the drain moves the change's aim (`keel/stackwatch.py`).
  All of that is PER REPO (c-772): a card may name repos its parent does not, as long as the
  two share one, and the parent has no branch in those. There the card is cut from its own
  base and its change aims at it, before the parent lands and after (`base_of(card, repo)`
  answers None, `split_repos`), and the choice is read back saying which repo is which
  (`spread`), at create, at a set, at the plan's approve and at the split alike.
- **independent**: cut from the base, its change aims at the base, and its `after` holds
  nothing up: it may start at once (`views.waiting_for` reads the choice; no second record).
- **no choice** (the option absent): exactly as before c-718.

The engine stays neutral: what stacked means for a code host is the space's pack's, which
declares it can (`stacks = true` under `[capabilities]`, `packs.NEEDS`). The choice is
written only by the owner (`board.HIS_AT_CREATE`), by hand or by the owner's Approve plan of the card
it waits for (`record`), never by a house, and only in a space whose pack stacks (`problem`).

Nothing here is stored but the choice. What the parent's branch is, which repos it works in,
whether it is pushed, where it was last pushed (`options.shipping.heads`) and whether it has
landed are read off the parent's own card on every read (`derive`, `derived.stack`).
"""

from __future__ import annotations

import json
import re

from keel.planinline import CARD

OPTION = "stack"
STACKED, INDEPENDENT = "stacked", "independent"
CHOICES = (STACKED, INDEPENDENT)
# The pack's claim (`[capabilities]` in its pack.toml): its worktree verb cuts a stacked card
# from its parent's branch, its change aims there, and its `ship <id> restack` moves the aim.
CAPABILITY = "stacks"
# The plan's block the owner answers per waiting card (`record`): a batch whose rows are the
# waiting cards' ids and whose choices are the two words above.
BLOCK = "stack"
# c-718's addition: the owner's answers for the slices a plan splits its card into, kept on
# that card by the owner's Approve plan, `{slice title: choice}`, and given to each slice by `kb split`.
SPLIT_OPTION = "split_stack"
# r2.F5: the sentence a card stacked on a card that is then split is blocked with.
SPLIT_UNDER = ("{parent}, the card this one is stacked on, was split into slices and has no branch of "
               "its own now. Stack it on one of its slices (`kb set {id} after=<slice>`, which "
               "keeps it stacked), or make it independent, then unblock it.")
# A parent counts as pushed at these stages whatever it records (views.WAITABLE's).
PUSHED_STAGES = ("review", "shipping", "done")
# A card whose options say it is research opens no branch (its pack's kind; r1.F8).
RESEARCH = "research"
# c-772: the choice read back when the card names a repo its parent does not.
SPREAD = ("stacked on {parent} in {stacked}; in {apart}, which {parent} does not work in, it is cut "
          "from its own base and its change aims at that base")
# What a text with ONE base for the card adds when the card has a repo its parent does not name.
OTHER_BASE = "Another repo of this card may have a different base."


def options_of(row) -> dict:
    raw = row["options"] if not isinstance(row, dict) else row.get("options")
    if isinstance(raw, dict):
        return raw
    try:
        found = json.loads(raw or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def choice(row) -> str | None:
    """The card's recorded choice, or None (no choice, or a value that is not one)."""
    value = options_of(row).get(OPTION)
    return value if value in CHOICES else None


def afters_of(row) -> list[str]:
    text = row["after"] if not isinstance(row, dict) else row.get("after")
    if isinstance(text, list):
        return [str(one) for one in text]
    return list(dict.fromkeys(part.strip() for part in str(text or "").split(",") if part.strip()))


def problem(value, after_ids: list[str], space: str, stacks, parent: dict | None = None,
            child: dict | None = None) -> str | None:
    """Why `options.stack=value` cannot be recorded on a card of `space` waiting for
    `after_ids`, or None. `stacks`: the spaces whose pack stacks (`Config.stacking`).
    For `stacked`, `parent` is what the board knows of the card it would stack on
    (`parent_facts`) and `child` the card's own `{repo, base}`: the parent must be an
    ordinary card (not tracking, not research) working in at least one repo the child does
    (c-772), and the two must merge into the same base (r1.F8, r1.F12)."""
    if value is None:
        return None
    if value not in CHOICES:
        return f"options.{OPTION} is {STACKED} or {INDEPENDENT} (or null to clear it), not {value!r}"
    if space not in stacks:
        return (f"the {space} space's pack does not stack cards (`{CAPABILITY} = true` under "
                f"[capabilities] in its pack.toml), so options.{OPTION} means nothing there")
    if not after_ids:
        return (f"options.{OPTION} says how a card stands to the card it waits for, and this one "
                f"waits for none (`after`)")
    if value == STACKED and len(after_ids) != 1:
        return (f"a stacked card is cut from the branch of the ONE card it waits for, and this one "
                f"waits for {len(after_ids)} ({', '.join(after_ids)})")
    if value == STACKED and parent is not None:
        return parent_problem(after_ids[0], parent, child or {})
    return None


def parent_problem(parent_id: str, parent: dict, child: dict) -> str | None:
    """Why a card cannot be stacked on `parent_id`, from `parent_facts`; None when it can."""
    if not parent.get("exists"):
        return f"{parent_id} is not on the board, so there is no branch to stack on"
    if parent.get("tracking"):
        return f"{parent_id} is a tracking card: it has no branch of its own to stack on (stack on a slice)"
    if parent.get("research"):
        return f"{parent_id} is a research card: it opens no branch to stack on"
    mine = repos_of(child.get("repo"))
    if not any(repo in parent.get("repos", []) for repo in mine):
        # c-772: one repo in common is enough; in the others the card keeps its own base
        return (f"{parent_id} works in {', '.join(parent.get('repos') or ['no repo'])}, not in "
                f"{', '.join(mine or ['this card'])}, so it has no branch there to stack on")
    mine, theirs = child.get("base"), parent.get("base")
    if mine and mine != theirs:
        return (f"this card merges into {mine} and {parent_id} into {theirs or 'its space default'}: "
                f"a stacked card merges into its parent's base, so clear options.base or match it")
    return None


def repos_of(text) -> list[str]:
    return [one.strip() for one in str(text or "").split(",") if one.strip()]


def spread(parent_id: str, child_repos: list[str], parent_repos: list[str]) -> str | None:
    """c-772: the stacked choice read back per repo, for a card that names a repo its parent
    does not; None when every repo of the card is the parent's too, where nothing is to say."""
    apart = [repo for repo in child_repos if repo not in parent_repos]
    stacked = [repo for repo in child_repos if repo in parent_repos]
    if not apart or not stacked:
        return None
    return SPREAD.format(parent=parent_id, stacked=", ".join(stacked), apart=", ".join(apart))


def parent_facts(board, parent_id: str) -> dict:
    """What `problem` needs of the card a stacked card would stack on, read off its row."""
    from keel import views    # noqa: PLC0415 - views reads this module's rules
    row = board.conn.execute("SELECT * FROM cards WHERE id = ?", (parent_id,)).fetchone()
    if row is None:
        return {"exists": False}
    options = options_of(row)
    return {"exists": True, "tracking": bool(views.tracked(row, board.children(parent_id))),
            "research": str(options.get("kind") or "").lower() == RESEARCH,
            "repos": repos_of(row["repo"]), "base": options.get("base") or None}


def pushed(board, parent) -> bool:
    """Has the parent a branch on the remote: it names its branch (`options.branch`), and it
    records a change (the draft its house opens once its branch is pushed) or it is past
    building (r1.F8: a stage alone, with no branch, is nothing to cut from)."""
    from keel import views    # noqa: PLC0415 - views reads this module's rules
    options = options_of(parent)
    if not options.get("branch"):
        return False
    if views.tracked(parent, board.children(parent["id"])):
        return False        # r2.F5: a card split into slices is no branch to cut from
    if options.get("pr") or options.get("prs"):
        return True
    return views.effective_stage(board, parent) in PUSHED_STAGES


def heads(options: dict) -> dict:
    """Where the parent's branch was last pushed, per repo: what its Approve published and
    each Ship pushed since (`options.shipping.heads`)."""
    found = (options.get("shipping") or {}).get("heads") if isinstance(options.get("shipping"), dict) else None
    return {str(repo): str(sha) for repo, sha in (found or {}).items()} if isinstance(found, dict) else {}


def derive(board, row) -> dict | None:
    """`derived.stack`: None with no choice. Else `{choice, on}`, `on` the card it waits for
    (the first its `after` names), and for a stacked card what is known of that parent: its
    `branch`, the `repos` it works in (c-772: the card is stacked in those alone; None for a
    parent gone from the board, whose repos nothing says), whether it is `pushed`, its pushed
    `heads`, whether it has `landed` (done), whether it was `dropped` (archived, or gone from
    the board) and the `base` it merges into."""
    value = choice(row)
    if value is None:
        return None
    ids = afters_of(row)
    out = {"choice": value, "on": ids[0] if ids else None}
    if value != STACKED or not ids:
        return out
    parent = board.conn.execute("SELECT * FROM cards WHERE id = ?", (ids[0],)).fetchone()
    if parent is None:
        return dict(out, branch=None, repos=None, pushed=False, heads={}, landed=False, dropped=True,
                    base=None)
    options = options_of(parent)
    landed = parent["stage"] == "done"
    # r1.F5: a parent that merged and was archived later is landed, never dropped
    return dict(out, branch=options.get("branch") or None, repos=repos_of(parent["repo"]),
                pushed=pushed(board, parent), heads=heads(options), landed=landed,
                dropped=options.get("archived") is True and not landed,
                base=options.get("base") or None)


def of(card: dict) -> dict | None:
    """A card dict's `derived.stack`."""
    return (card.get("derived") or {}).get("stack")


def stacked_on(card: dict) -> dict | None:
    """The card's stack while it is stacked on a parent that has not landed, else None."""
    found = of(card)
    if found and found.get("choice") == STACKED and found.get("on") and not found.get("landed"):
        return found
    return None


def stacked_in(card: dict, repo: str | None = None) -> bool:
    """c-772: is `repo` (the card's first when none is asked about) one the card is stacked
    in: one its parent names too. A stack that carries no repo list holds in every repo."""
    named = (of(card) or {}).get("repos")
    repo = repo or next(iter(repos_of(card.get("repo"))), None)
    return named is None or repo is None or repo in named


def split_repos(card: dict) -> tuple[list[str], list[str]]:
    """c-772: `(stacked, apart)` over a stacked card's repos: the ones its parent names too,
    and the ones it is cut from its own base in. Two empty lists for any other card."""
    found = of(card) or {}
    if found.get("choice") != STACKED or not found.get("on"):
        return [], []
    mine = repos_of(card.get("repo"))
    return [r for r in mine if stacked_in(card, r)], [r for r in mine if not stacked_in(card, r)]


def spread_of(card: dict) -> str | None:
    """`spread` for a card dict, from its `derived.stack`; None for a card with nothing to say."""
    found = of(card) or {}
    if found.get("choice") != STACKED or not found.get("on") or found.get("repos") is None:
        return None
    return spread(found["on"], repos_of(card.get("repo")), found["repos"])


def other_base(card: dict) -> str:
    """`OTHER_BASE` for a stacked card that names a repo its parent does not, else ""."""
    return OTHER_BASE if split_repos(card)[1] else ""


def base_of(card: dict, repo: str | None = None) -> str | None:
    """The branch a stacked card's change is taken against in `repo` (the card's first when
    none is asked about) while its parent has not landed: the parent's branch. Once it has
    landed, the base the parent merged into when the card names none of its own (r1.F12).
    None otherwise, and the card's own base answers (`options.base`, else the space's own
    rule). c-772: None too, before the parent lands and after, in a repo the parent does not
    name: the parent has no branch there and merged nothing there, so the card's own base
    answers in that repo throughout."""
    if not stacked_in(card, repo):
        return None
    found = stacked_on(card)
    if found:
        return str(found["branch"]) if found.get("branch") else None
    landed = of(card) or {}
    if landed.get("choice") == STACKED and landed.get("landed") and not options_of(card).get("base"):
        return landed.get("base") or None    # r1.F12: it merges where its parent merged
    return None


# ----- the plan gate: the owner's Approve records the choice on each waiting card -----

def waiting_cards(board, card_id: str) -> list[dict]:
    """The cards that wait for this one and are not done or archived: the children whose
    choice the plan proposes."""
    rows = board.conn.execute("SELECT * FROM cards WHERE \"after\" IS NOT NULL AND stage != 'done'")
    return [board.get(row["id"]) for row in rows
            if card_id in afters_of(row) and options_of(row).get("archived") is not True]


# A slice row says which slice it waits for (r2.F1): `s2: <its title> (after <that slice's
# title>) | stacked | <why>`, so the owner approves the slice it stacks on, not the house's split.
AFTER = re.compile(r"^(?P<title>.*?)\s*\(after\s+(?P<on>.+?)\)\s*$")
CARD_ROW = re.compile(rf"^{CARD}$")


def title_key(text) -> str:
    """A slice title as both sides compare it (r2.F1): words joined by one space."""
    return " ".join(str(text or "").split())


def rows_of(doc: dict, state: dict) -> list[dict]:
    """The plan's `stack` batch, one `{id, title, on, value, flipped}` per row: `value` the
    owner's pick this round (`state`, the round's marks, `keel/planstate.py`), else the
    house's recommendation; `flipped` whether the owner picked it (r1.F13); `on` the slice a
    slice row waits for, from its `(after <title>)`."""
    from keel import planstate    # noqa: PLC0415 - plan parsing is not needed on every read
    from keel.planinline import plain    # noqa: PLC0415
    out = []
    for block in planstate.doc_blocks(doc):
        if block.get("type") != "batch" or block.get("id") != BLOCK:
            continue
        picks = state.get("rows", {}).get(BLOCK, {})
        for row in block.get("rows") or []:
            value = picks.get(row["id"]) or row.get("rec")
            if value not in CHOICES:
                continue
            text = title_key(plain(row.get("text") or []))
            found = AFTER.match(text)
            out.append({"id": row["id"], "title": title_key(found["title"]) if found else text,
                        "on": title_key(found["on"]) if found else None,
                        "value": value, "flipped": row["id"] in picks})
    return out


def record(board, card_id: str, doc: dict, state: dict, actor: str = "human") -> list[str]:
    """The owner's Approve plan, over the plan's `stack` batch.

    A row whose id has a card's shape (`c-NNN`, r2.F8) is a CARD row: written on that card
    as `options.stack`, by the owner, when it waits for `card_id`, and said as skipped when it
    does not. A card that already holds a choice keeps it unless the owner flipped its row
    this round (r1.F13). When the plan also carries slice rows it splits this card, which then
    has no branch of its own, so a card row may not be stacked on it (r2.F5): said as skipped.
    Every other row is a SLICE (c-718's addition): kept on this card as
    `options.split_stack`, `{title: {choice, on}}`, the owner's, so the house's `kb split`
    after the Approve gives each slice the answer for its title AND the slice it waits for
    (`split_answer`, r2.F1). What was recorded, and what was not, is said in one note each."""
    from keel.board import Refused    # noqa: PLC0415 - the board imports this module
    rows = rows_of(doc, state)
    if not rows:
        return []
    waiting = {card["id"]: card for card in waiting_cards(board, card_id)}
    parent_repos = repos_of(board.get(card_id).get("repo"))
    cards = [row for row in rows if CARD_ROW.match(row["id"])]
    slices = {row["title"]: {"choice": row["value"], "on": row["on"]}
              for row in rows if not CARD_ROW.match(row["id"]) and row["title"]}
    said, skipped = [], []
    for row in cards:
        card = waiting.get(row["id"])
        if card is None:
            skipped.append(f"{row['id']}: it does not wait for {card_id}")
            continue
        if slices and row["value"] == STACKED:
            skipped.append(f"{row['id']}: this plan splits {card_id} into slices, so it has no branch to "
                           f"stack on; stack {row['id']} on one of its slices once they exist")
            continue
        held = options_of(card).get(OPTION)
        if held in CHOICES and (held == row["value"] or not row["flipped"]):
            said.append(f"{row['id']} {held}" + ("" if held == row["value"] else " (kept)"))
            continue
        try:
            board.set_fields(row["id"], {"options": {OPTION: row["value"]}}, actor)
        except Refused as error:
            skipped.append(f"{row['id']}: {error}")
            continue
        apart = spread(card_id, repos_of(card.get("repo")), parent_repos) if row["value"] == STACKED else None
        said.append(f"{row['id']} {apart}" if apart else f"{row['id']} {row['value']}")
    if slices:
        board.set_fields(card_id, {"options": {SPLIT_OPTION: slices}}, actor)
        said += [f"slice '{title}' {one['choice']}" + (f" on '{one['on']}'" if one["on"] else "")
                 for title, one in slices.items()]
    if said:
        board.note(card_id, "stacking recorded at plan approval: " + ", ".join(said), actor)
    if skipped:
        board.note(card_id, "stacking not recorded for " + "; ".join(skipped), actor)
    return said


# ----- the split: each slice's answer from the start (c-718's addition) -----

def approved(parent_options: dict) -> dict:
    """The owner's approved slice answers, by `title_key`, each `{choice, on}`."""
    found = parent_options.get(SPLIT_OPTION)
    if not isinstance(found, dict):
        return {}
    out = {}
    for title, one in found.items():
        one = one if isinstance(one, dict) else {"choice": one, "on": None}
        out[title_key(title)] = {"choice": one.get("choice"), "on": title_key(one.get("on")) or None}
    return out


def split_answer(answers: dict, title: str, after_titles: list[str]) -> tuple[str | None, str | None]:
    """`(choice, why not)` for one slice from the approved answers (r2.F1): its answer only
    when the slice waits for exactly the slice the owner approved it on; else no choice and
    the sentence saying why. `(None, None)` when no answer names the title."""
    one = answers.get(title_key(title))
    if one is None:
        return None, None
    after = [title_key(t) for t in after_titles]
    if not after:
        return None, f"'{title}' waits for nothing, so it starts at once"
    if one["on"] is None:
        if one["choice"] == INDEPENDENT:
            return INDEPENDENT, None
        return None, f"'{title}' was approved {one['choice']} with no slice named to stack on"
    if after != [one["on"]]:
        return None, (f"'{title}' was approved {one['choice']} on '{one['on']}', and the split has it "
                      f"after {', '.join(repr(a) for a in after)}")
    return one["choice"], None
