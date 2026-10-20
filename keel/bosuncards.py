"""A Keel card on his personal board (c-592): who filed it, where Bosun has it, and whether
the board shows it.

A personal card with a repo is Bosun's to build (`derived.bosun`, builder mode). The deck
labels it and says Bosun's state; whether it shows on his personal board goes by WHO FILED
IT, read from the card's own `create` event, never a field:

- a card he filed (an actor that is him: the deck and his CLI sign as `human`, then
  `voice` and the talker) shows until it is live, attended or autonomous;
- a card any other actor filed (Bosun, a house, the drain, the cli, the doctor) shows only
  while it needs him, and otherwise lives on the Bosun page;
- a card that needs him always shows.

On `next` against live is read from git, where the drain reads what a deploy ask carries
(`deploy.repos`, `deploy.carried`): a done card whose landing merge is on the integration
branch and not on the trunk is on next, and live otherwise. A repo not checked out on this
machine falls back to the deploy asks (`deployask.places`). The only thing kept is an
in-process memo keyed on the two shas, which cannot disagree with the board.
docs/atlas/96-bosun.md, "Keel cards on the user's board".
"""

from __future__ import annotations

from pathlib import Path

from keel import deploy, deployask, merging

HIS_ACTORS = ("human", "voice", "talker")
HIM, BOSUNS = "him", "bosun"
PLAN, QUEUED, BUILDING, NEXT, LIVE = "plan", "queued", "building", deployask.NEXT, deployask.LIVE
QUEUED_STAGES = ("inbox", "assigned")
MEMO_MAX = 32
# (repo path, trunk sha, next sha) -> the cards on next and not on the trunk
_carried: dict[tuple[str, str, str], frozenset[str]] = {}


def filers(board, ids: list[str]) -> dict[str, str]:
    """`{card: actor}` of each card's create event."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = board.conn.execute(f"SELECT card, actor FROM events WHERE kind = 'create' AND card IN ({marks})",
                              ids)
    return {row["card"]: row["actor"] for row in rows}


def done_at(board, ids: list[str]) -> dict[str, str]:
    """`{card: when}` of each card's newest move to done."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = board.conn.execute(
        f"SELECT card, MAX(at) AS at FROM events WHERE kind = 'stage' AND card IN ({marks}) "
        f"AND json_extract(data, '$.to') = 'done' GROUP BY card", ids)
    return {row["card"]: row["at"] for row in rows}


def carried_of(one: dict) -> frozenset[str]:
    """The cards whose landing merges are on this repo's integration branch and not on its
    trunk, memoised on both shas. Raises `MergeRefused` when git cannot answer."""
    path = Path(one["path"])
    trunk = merging.trunk_of(path)
    trunk_sha = merging.git(path, "rev-parse", trunk)
    sha = merging.ref_head(path, one["target"])
    if sha is None:
        return frozenset()
    key = (str(path.resolve()), trunk_sha, sha)
    if key not in _carried:
        if len(_carried) >= MEMO_MAX:
            _carried.clear()
        _carried[key] = frozenset(deploy.carried(path, trunk_sha, sha))
    return _carried[key]


def on_next(cfg, strict: bool = False) -> dict[str, frozenset[str]]:
    """`{resolved repo path: cards on next}` for each integration repo this machine owns.
    A repo git cannot answer for is left out, so its cards take the fallback; with `strict`
    it raises instead, so the deck's kept reading keeps its last good one (c-638)."""
    out = {}
    for one in deploy.repos(cfg):
        try:
            out[str(Path(one["path"]).resolve())] = carried_of(one)
        except (merging.MergeRefused, OSError):
            if strict:
                raise
            continue
    return out


def repo_key(card: dict) -> str:
    return str(card.get("repo") or "").split(",")[0].strip()


def is_integrated(cfg, card: dict) -> bool:
    return (card["space"], repo_key(card)) in cfg.integrated


def checkout_of(cfg, card: dict) -> str | None:
    space = cfg.spaces.get(card["space"])
    path = space.repo_path(repo_key(card)) if space is not None else None
    try:
        return str(path.resolve()) if path is not None else None
    except OSError:
        return None


class Places:
    """Where each done card stands, `next` or `live`, read once per state build."""

    def __init__(self, cfg, board, done: list[dict], on_next_of=None):
        self.cfg, self.board = cfg, board
        self.git = (on_next_of or on_next)(cfg) if done else {}
        self.asks = None
        self.dones = None
        self.done = done

    def of(self, card: dict) -> str:
        if not is_integrated(self.cfg, card):
            return LIVE
        cards = self.git.get(checkout_of(self.cfg, card) or "")
        if cards is not None:
            return NEXT if card["id"] in cards else LIVE
        return self.fallback(card)

    def fallback(self, card: dict) -> str:
        """No checkout here: the deploy asks. A card an ask carries goes by that ask; one no
        recent ask names is on next when it was done after its repo's newest ask was raised
        (the drain raises the next one on its pass), and live before that."""
        if self.asks is None:
            self.asks = deployask.places(self.board)
            self.dones = done_at(self.board, [c["id"] for c in self.done])
        places, newest = self.asks
        if card["id"] in places:
            return places[card["id"]]
        raised = newest.get(repo_key(card))
        done = self.dones.get(card["id"]) or card.get("updated_at") or ""
        return NEXT if raised is None or done > raised else LIVE


def state(card: dict, done_place: str | None) -> str:
    derived = card["derived"]
    if derived.get("plan_gate"):
        return PLAN
    stage = derived.get("parent_stage") or card["stage"]
    if stage in QUEUED_STAGES:
        return QUEUED
    if stage == "done":
        return done_place or LIVE
    return BUILDING


def shown(derived: dict, filed_by: str, where: str) -> bool:
    if derived.get("needs_you"):
        return True
    return filed_by == HIM and where != LIVE


def is_done(card: dict) -> bool:
    return (card["derived"].get("parent_stage") or card["stage"]) == "done"


def annotate(cfg, board, cards: list[dict], on_next_of=None) -> None:
    """Set `derived.keel_card = {filed_by, state, shown}` on each of Bosun's cards in
    `cards` (the board's own dicts), in place. Only a done card that is not archived asks
    where it landed; an archived one reads as live. `on_next_of(cfg)` is the deck's kept git
    reading (c-638), `on_next` itself when none is given."""
    mine = [card for card in cards if card["derived"].get("bosun")]
    if not mine:
        return
    actors = filers(board, [card["id"] for card in mine])
    done = [card for card in mine if is_done(card) and not card["derived"].get("archived")]
    places = Places(cfg, board, done, on_next_of)
    asking = {card["id"] for card in done}
    for card in mine:
        filed_by = HIM if actors.get(card["id"]) in HIS_ACTORS else BOSUNS
        where = state(card, places.of(card) if card["id"] in asking else None)
        card["derived"]["keel_card"] = {"filed_by": filed_by, "state": where,
                                        "shown": shown(card["derived"], filed_by, where)}
