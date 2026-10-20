"""The card tree: a tracking card's outline, assigning a whole tree, and the queue.

Three questions, one module, because they read the same two links (`parent`, `after`):

- THE OUTLINE (`outline`, `render`). A tracking card's slices in STEPS: a slice's step is
  one more than the longest chain of waits inside the tree above it, so a slice that waits
  on two siblings has one place to stand, which indenting under a single sibling cannot
  give it. Each slice says what it still waits for, whether it is NEXT (it could start now:
  not started, not blocked, nothing left to wait for) and how many unfinished cards of the
  tree sit downstream of it (`unblocks`). `views.derived` attaches it as `derived.tree`, so
  `kb tree`, the deck and voice all read this one computation.
- ASSIGN THE TREE (`assign`). Every unassigned slice of a tracking card to `assigned` in one
  write, and what that does: which start now and which wait. The drain then follows the
  tree by itself, since a card whose `after` is unfinished is not startable.
- THE QUEUE (`queue_key`, `queue`, `to_front`). The order the drain takes startable cards.
  A card's place is its tree's place, then its own place inside that tree, each one its
  `rank` when he has moved it and its creation time otherwise. Nothing but `to_front` writes
  a rank, and only to put a card ahead of its peers (a slice among its siblings, anything
  else among the top-level cards). A place never beats a dependency: the queue orders the
  STARTABLE cards, and a card still waiting is not one.
"""

from keel import views
from keel.board import Refused

# The stages a slice is at before anything has started on it: what `next` and `assign` read.
NOT_STARTED = ("inbox", "assigned")
UNFINISHED = ("inbox", "assigned", "planning", "building")
# Who may reorder the queue or assign a whole tree: him, by hand or by voice. A house (or a
# plain `kb` with no token) spends houses and reorders everyone's work, so it may not.
ORDER_ACTORS = ("human", "voice")


def refuse_actor(actor: str, verb: str) -> None:
    if actor not in ORDER_ACTORS:
        raise Refused(f"{verb} is the user's to run (actor human or voice), not {actor}'s")


# ----- the outline -----

def node_of(board, row) -> dict:
    """One slice as the outline carries it, before its step and its downstream count."""
    kids = views.tracked(row, board.children(row["id"]))
    stage = views.parent_stage(kids) or row["stage"]
    waiting = views.waiting_for(board, row)
    return {
        "id": row["id"], "title": row["title"], "stage": stage,
        "after": views.afters(row["after"]), "waiting_for": waiting,
        "blocked": row["blocked_reason"] is not None, "tracking": bool(kids),
        "attended": row["autonomy"] == "attended",
        "next": (row["stage"] in NOT_STARTED and not kids and not waiting
                 and row["blocked_reason"] is None),
    }


def steps_of(nodes: dict) -> dict:
    """Each slice's step: 1 + the longest chain of in-tree waits above it. A wait on a card
    outside the tree is shown on the slice and counts no step. The board refuses a cycle,
    and a card met twice on one walk is treated as the top, so a hand-edited file cannot
    hang a read."""
    steps: dict[str, int] = {}

    def step(card_id: str, walking: frozenset) -> int:
        if card_id in steps:
            return steps[card_id]
        inside = [a for a in nodes[card_id]["after"] if a in nodes and a not in walking]
        found = 1 + max((step(a, walking | {card_id}) for a in inside), default=0)
        steps[card_id] = found
        return found

    for card_id in nodes:
        step(card_id, frozenset())
    return steps


def downstream(nodes: dict) -> dict:
    """How many unfinished slices wait on each one, directly or through others."""
    waiters: dict[str, set] = {card_id: set() for card_id in nodes}
    for card_id, node in nodes.items():
        for after in node["after"]:
            if after in waiters:
                waiters[after].add(card_id)
    counts = {}
    for card_id in nodes:
        seen, todo = set(), list(waiters[card_id])
        while todo:
            other = todo.pop()
            if other not in seen and other != card_id:
                seen.add(other)
                todo.extend(waiters[other])
        counts[card_id] = sum(nodes[other]["stage"] in UNFINISHED for other in seen)
    return counts


def outline(board, row, children: list) -> dict | None:
    """The tree of a tracking card: its slices by step, in queue order within a step, and
    the follow-ups filed out of it, listed apart. None for a card with no slices."""
    if not children:
        return None
    nodes = {child["id"]: node_of(board, child) for child in children}
    steps, unblocks = steps_of(nodes), downstream(nodes)
    order = {child["id"]: index for index, child in
             enumerate(sorted(children, key=lambda child: place(child)))}
    by_step: dict[int, list] = {}
    for card_id, node in nodes.items():
        node.update(step=steps[card_id], unblocks=unblocks[card_id])
        by_step.setdefault(steps[card_id], []).append(node)
    return {
        "steps": [{"step": number, "cards": sorted(by_step[number], key=lambda n: order[n["id"]])}
                  for number in sorted(by_step)],
        "next": [n["id"] for n in sorted(nodes.values(), key=lambda n: order[n["id"]]) if n["next"]],
        # The very set `assign` would move, grandchildren included, so the button's count
        # and what it does agree on a nested tree.
        "unassigned": len(slices_to_assign(board, row["id"])),
        "follow_ups": board.follow_ups(row["id"]),
    }


def word(node: dict) -> str:
    """The one word the outline puts in front of a slice."""
    if node["blocked"]:
        return "blocked"
    if node["tracking"]:
        return "tracking"
    if node["stage"] == "inbox":
        return "next, not assigned" if node["next"] else "not assigned"
    if node["stage"] == "assigned":
        return "next" if node["next"] else "waits"
    if node["stage"] == "planning" and node["attended"]:
        return "plan gate"
    return node["stage"]


def slice_line(node: dict) -> str:
    tail = []
    if node["after"]:
        tail.append("after " + ", ".join(
            a + (" (met)" if a not in node["waiting_for"] else "") for a in node["after"]))
    if node["unblocks"]:
        tail.append(f"unblocks {node['unblocks']}")
    return f"  {word(node):<19} {node['id']}  {node['title']}" + (
        "   " + "   ".join(tail) if tail else "")


def render(card: dict) -> str:
    """`kb tree`: the card's line, then its slices by step, then its follow-ups. Plain lines
    in words the talker and voice can read out as they stand."""
    tree = card["derived"].get("tree")
    lines = [f"{card['id']}  {card['title']}"]
    if tree is None:
        lines.append("  no slices: this card is not a tree"
                     + (f" (slice of {card['parent']})" if card.get("parent") else ""))
    else:
        lines[0] += f"  [tracking: {card['derived']['tracking_tally']}]"
        for group in tree["steps"]:
            lines.append(f"step {group['step']}")
            lines.extend(slice_line(node) for node in group["cards"])
    follow = card["derived"].get("follow_ups") or []
    if follow:
        lines.append("follow-ups: " + ", ".join(follow))
    return "\n".join(lines)


# ----- assign the tree -----

def slices_to_assign(board, card_id: str) -> list:
    """Every unassigned working slice under a card, grandchildren included (a slice that is
    itself a tree is not a card that runs, its own slices are)."""
    found = []
    for child in views.tracked(board._row(card_id), board.children(card_id)):
        if views.tracked(child, board.children(child["id"])):
            found.extend(slices_to_assign(board, child["id"]))
        elif child["stage"] == "inbox":
            found.append(child)
    return found


def what_assigning_does(board, rows: list) -> dict:
    """Which of these cards would start at once when assigned, which would wait (and on
    what), and which of them stop at a plan gate first. Read before the write, so a dry run
    and the real one say the same thing."""
    start, wait = [], []
    for row in rows:
        waiting = views.waiting_for(board, row)
        if waiting or row["blocked_reason"] is not None:
            wait.append({"id": row["id"], "waiting_for": waiting,
                         "blocked": row["blocked_reason"] is not None})
        else:
            start.append(row["id"])
    return {"assigned": [row["id"] for row in rows], "start_now": start, "wait": wait,
            "plan_gate": [row["id"] for row in rows if row["autonomy"] == "attended"]}


def refuse_changed(card_id: str, rows: list, expected: list | None) -> None:
    """The confirm assigns exactly what the preview showed him, or nothing."""
    if expected is None:
        return
    now = {row["id"] for row in rows}
    if now != set(expected):
        raise Refused(f"the slices of {card_id} to assign changed since the preview "
                      f"({len(expected)} then, {len(now)} now); preview again")


def assign(board, card_id: str, actor: str, dry_run: bool = False,
           expected: list | None = None) -> dict:
    """Assign a card, or every unassigned slice of a tracking card, in one transaction.

    A plain card moves from inbox to assigned exactly as `kb stage` would. A tracking card
    never moves itself (it is never startable); its inbox slices do. Slices filed later are
    not included: a later child is a new decision, and the outline marks it not assigned.
    `expected` is the ids a preview showed; when given, any other set is refused.
    """
    refuse_actor(actor, "kb assign")
    with board.tx():
        row = board._row(card_id)
        if views.archived(row):
            raise Refused(f"{card_id} is archived")
        tracking = bool(views.tracked(row, board.children(card_id)))
        if tracking:
            rows = slices_to_assign(board, card_id)
        elif row["stage"] == "inbox":
            rows = [row]
        else:
            raise Refused(f"{card_id} is at {row['stage']}, not inbox; nothing to assign")
        refuse_changed(card_id, rows, expected)
        result = dict(what_assigning_does(board, rows), id=card_id, tree=tracking,
                      dry_run=dry_run)
        if not dry_run:
            for each in rows:
                board._move(each, "assigned", actor, {},
                            f"assigned with the tree of {card_id}" if tracking else None)
    return result


def assign_line(result: dict) -> str:
    """`4 assigned: 1 starts now, 3 wait` (or `would be assigned` on a dry run)."""
    count = len(result["assigned"])
    if not count:
        return f"{result['id']}: nothing to assign, every slice is already assigned or further on"
    verb = "would be assigned" if result["dry_run"] else "assigned"
    start, wait, gate = (len(result[k]) for k in ("start_now", "wait", "plan_gate"))
    line = (f"{count} {verb}: {start} {'starts' if start == 1 else 'start'} now, "
            f"{wait} {'waits' if wait == 1 else 'wait'}")
    if gate:
        line += f"; {gate} {'stops' if gate == 1 else 'stop'} at a plan gate first"
    return line


# ----- the queue -----

def place(card) -> tuple:
    """A card's place among its peers: a rank he gave it first (lowest first), then the
    order it was filed in. Works on a row and on a read card alike, and on a card read from
    a board older than the rank column, which has no `rank` at all."""
    rank = card.get("rank") if isinstance(card, dict) else card["rank"]
    return (rank is None, rank if rank is not None else 0.0, card["created_at"], card["id"])


def queue_key(card: dict, by_id: dict) -> list:
    """The card's place in the drain's queue: its top-level tree's place, then each level's
    down to its own. A card whose parent is not in `by_id` stands on its own."""
    chain, seen, walk = [], set(), card
    while walk is not None and walk["id"] not in seen:
        seen.add(walk["id"])
        chain.append(place(walk))
        walk = by_id.get(walk.get("parent")) if walk.get("parent") else None
    return list(reversed(chain))


def in_order(cards: list, all_cards: list | None = None) -> list:
    """`cards` in queue order; `all_cards` supplies the parents their keys walk through."""
    by_id = {card["id"]: card for card in (all_cards if all_cards is not None else cards)}
    return sorted(cards, key=lambda card: queue_key(card, by_id))


def queued(card: dict) -> bool:
    """A card the queue orders: assigned, not a tracking card, not archived."""
    return (card["stage"] == "assigned" and not card["derived"]["tracking"]
            and not card["derived"]["archived"])


def queue(cards: list) -> list[str]:
    """The ids of every queued card, in the order the drain would take them when startable."""
    return [card["id"] for card in in_order([c for c in cards if queued(c)], cards)]


def queue_rows(cards: list, space: str | None = None) -> list[dict]:
    """`kb queue`: each queued card with its position and why it is not starting, if not."""
    rows = []
    for position, card_id in enumerate(queue(cards), start=1):
        card = next(c for c in cards if c["id"] == card_id)
        if space and card["space"] != space:
            continue
        rows.append({"position": position, "id": card_id, "title": card["title"],
                     "space": card["space"], "parent": card.get("parent"),
                     "startable": card["derived"]["startable"],
                     "waiting_for": card["derived"]["waiting_for"],
                     "blocked": card["blocked_reason"] is not None,
                     "claimed": views.claim_host(card)})
    return rows


def queue_line(row: dict) -> str:
    why = ("starts next" if row["startable"] else
           "blocked" if row["blocked"] else
           f"claimed by {row['claimed']}" if row["claimed"] else
           "waits for " + ", ".join(row["waiting_for"]) if row["waiting_for"] else "")
    slice_of = f"  (slice of {row['parent']})" if row["parent"] else ""
    return f"{row['position']:>3}  {row['id']}  {row['title']}{slice_of}" + (f"   {why}" if why else "")


def peers(board, row) -> list:
    """The cards a card is placed among: its siblings, or every top-level card."""
    if row["parent"]:
        return board.children(row["parent"])
    return board.conn.execute("SELECT * FROM cards WHERE parent IS NULL").fetchall()


def to_front(board, card_id: str, actor: str, clear: bool = False) -> dict:
    """Put a card ahead of its peers (a slice within its tree, anything else in the whole
    queue), or with `clear` hand it back to the order it was filed in. One `set` event."""
    refuse_actor(actor, "kb next")
    with board.tx():
        row = board._row(card_id)
        if views.archived(row):
            raise Refused(f"{card_id} is archived; it has no place in the queue")
        if views.effective_stage(board, row) == "done":
            raise Refused(f"{card_id} is done; it has no place in the queue")
        if clear:
            rank = None
        else:
            ranks = [p["rank"] for p in peers(board, row) if p["rank"] is not None
                     and p["id"] != card_id]
            rank = min(ranks, default=0.0) - 1.0
            if row["rank"] is not None and row["rank"] <= min(ranks, default=0.0) - 1.0:
                rank = row["rank"]          # already in front: a second tap changes nothing
        if row["rank"] != rank:
            board._update(card_id, {"rank": rank})
            board.record_event(card_id, "set", actor, text="moved to the front" if rank is not None
                               else "back to the order it was filed in", data={"rank": rank})
    return board.get(card_id)

