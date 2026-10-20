"""The deck, read over loopback, and reduced to the digest both Harbors answer from.

WHY THIS MODULE EXISTS. The deck's state document already carries everything either
Harbor is ever asked about out loud: the cards in both spaces, what is waiting, the
running houses, the review cards, the segments and the drain pill. A work pull request is
a card in `shipping` and its state rides on that card's row (lane RETIRE, RT-1: the PRs
page and the watcher behind it are gone). Until 2026-09-18 the voice gateway built its own smaller document
from two `kb` reads and hard-coded `"reviews": []`, so a question about the deck's PR
Review screen was answered "I cannot reach that", while `GET /api/state` on this machine
was serving the rows. Nothing technical was in the way. This module is what removes the
gap, and it is ONE reduction rather than two so the phone verb and the voice turn can
never drift into describing different boards.

WHO READS IT. `keel/cli.py`'s `keel deck` verb (stdlib, 3.14) and the voice gateway's
`voice/harbor_voice/snapshot.py` (its own 3.12 interpreter). That second reader is why
this file imports NOTHING from `keel` and nothing outside the standard library, and why
it stays inside the 3.10 syntax the speech stack's interpreter can parse: it is imported
across the interpreter boundary, from a package `keel/` itself may never import. The
dependency runs one way only, voice to keel, and it runs to this file alone.

THE RULE THE DIGEST KEEPS, inherited from `index.py` and unchanged by the deck being the
source: names, ids, states and counts, never values and never bodies. A review row is its
key, its title, its repo and its lane; it is never its findings. A card is its id, title,
stage and blocked reason; it is never its brief.

EVERY SECTION CARRIES ITS OWN COUNT BESIDE ITS CAPPED ROWS. The document is not small
(190 unarchived cards, 28 review rows on the night this was written), so every section is
capped. A cap that silently truncated would make the ONE thing spoken most often, the
count, wrong; so `count` is the real total and `rows` is the capped sample, and the
framing says so.
"""

from __future__ import annotations

import json
import urllib.request

DEFAULT_PORT = 8790
STATE_PATH = "/api/state"
BOARDS_PATH = "/api/boards"
FETCH_TIMEOUT = 3.0

# THE CAPS, per section, measured against the live document on 2026-09-18 (190 unarchived
# cards, 28 reviews, 13 pull requests (a section of their own until lane RETIRE), 5 segments). The whole digest measures 6,508 bytes
# with these, roughly 1,600 tokens: bigger than the 975 byte board-only digest it
# replaces, and it should be, because three of that one's sections were hard-coded empty.
# It is still a few KB riding on a turn that is already sending a model a question.
TITLE_CHARS = 44          # a title is told apart by it, never read out of it
CARD_ROWS = 30            # per space, not overall: the small space must not be crowded out
QUEUE_TOP = 8
REVIEW_ROWS = 12
SEGMENT_ROWS = 12
RUNNING_ROWS = 12
TOPIC_ROWS = 12
ASK_ROWS = 4              # Bosun's open asks: a question is read out, so a few at most
QUESTION_CHARS = 90       # an ask's question is heard whole, unlike a title
OPTION_CHARS = 40
DRAIN_CHARS = 80

LIVE_STAGES = ("planning", "building")
# The per-space routes the folded document carries: the review cards, since lane RC. The
# adapter's `reviews` provider now carries only the gear's settings, and no provider row
# reaches the digest at all.
PROVIDER_ROUTES = ("reviews",)
# What `keel deck <section>` will print as a table.
SECTIONS = ("cards", "reviews", "segments", "bosun")


# --------------------------------------------------------------------------- #
# Reading the deck.
# --------------------------------------------------------------------------- #

def state_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or DEFAULT_PORT}{STATE_PATH}"


def fetch_state(port: int | None = None, timeout: float = FETCH_TIMEOUT,
                base: str | None = None) -> dict:
    """`GET /api/state` on loopback, or on `base` (the board's deck, for a machine whose
    board is elsewhere). Raises when the deck does not answer.

    LOOPBACK AND NO TOKEN, deliberately: the deck serves its state document to anything
    that can already reach 127.0.0.1, which on this machine is the same trust boundary
    the gateway and the board CLI already sit inside. `base` is the tailnet address the
    board's own `kb` calls already use.
    """
    url = base.rstrip("/") + STATE_PATH if base else state_url(port)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def fetch_boards(port: int | None = None, timeout: float = FETCH_TIMEOUT) -> list:
    """`GET /api/boards` on loopback: every board's row (`keel/boardlist.py`), newest first.

    The same read as `fetch_state`, open and tokenless for the same reason. The voice
    gateway asks it at the end of a connected turn for the boards the house drew (VP-8),
    because a house pushes from its own shell and the gateway never sees the push.
    """
    url = f"http://127.0.0.1:{port or DEFAULT_PORT}{BOARDS_PATH}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return list(json.load(response).get("rows") or [])


# --------------------------------------------------------------------------- #
# The deck's document, folded into the one the digest is built from.
# --------------------------------------------------------------------------- #

def clip(text, limit: int = TITLE_CHARS) -> str:
    return " ".join(str(text or "").split())[:limit]


def _count(n, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def pr_words(card: dict, terms: dict | None = None) -> str:
    """A card's pull request as the shipping watcher last saw it (`options.shipping.facts`,
    `keel/shipwatch.py`): its state and its counts, never a comment's words. Empty for a
    card the watcher has not looked at. This is how a work pull request reaches a Harbor
    since the PRs page went (lane RETIRE, RT-1). A card with a pull request in each of its
    repos is said as how many and where they stand, then the sums (SH-10). `terms` is the
    card's space's words from the state's space entry (c-630); without them, "changes"."""
    facts = (((card.get("options") or {}).get("shipping") or {}).get("facts")) or {}
    if not isinstance(facts, dict) or not facts.get("state"):
        return ""
    parts = [several(facts["prs"], terms) if len(facts.get("prs") or []) > 1 else str(facts["state"])]
    for key, word in (("comments", "comment"), ("approvals", "approval")):
        if facts.get(key):
            parts.append(_count(int(facts[key]), word))
    if facts.get("ci") and facts["ci"] != "none":
        parts.append(f"checks {facts['ci']}")
    for key in ("behind", "waiting"):
        if facts.get(key):
            parts.append(f"{int(facts[key])} {key}")
    # c-655: what his hand-over would give the house, as the card's button counts it
    # (`derived.ship_handover`); nothing once he has asked
    hand = (card.get("derived") or {}).get("ship_handover") or {}
    unhanded = 0 if hand.get("asked") else int(hand.get("comments") or 0) + int(hand.get("checks") or 0)
    if unhanded:
        parts.append(f"{unhanded} not handed over")
    return ", ".join(parts)


def several(prs: list, terms: dict | None = None) -> str:
    """A card's pull requests in one phrase (SH-10): how many, and how many stand where."""
    counts = {}
    for pr in prs:
        state = str((pr or {}).get("state") or "open")
        counts[state] = counts.get(state, 0) + 1
    said = ", ".join(f"{n} {state}" for state, n in sorted(counts.items()))
    return f"{len(prs)} {(terms or {}).get('changes') or 'changes'} ({said})"


def card_row(card: dict, terms: dict | None = None) -> dict:
    derived = card.get("derived") or {}
    row = {"id": card.get("id"), "title": card.get("title") or "",
           "space": card.get("space") or "", "stage": card.get("stage") or "",
           "blocked": card.get("blocked_reason") or "",
           "needsYou": bool(derived.get("needs_you"))}
    pr = pr_words(card, terms)
    if pr:
        row["pr"] = pr
    return row


def order_cards(cards: list) -> list:
    """Needs-you first, then a live house, then the most recently touched.

    THE CAP IS WHY THIS ORDER EXISTS. Thirty rows of a hundred and fifty-nine have to be
    the thirty he would ask about, and the honest order is the deck's own: what wants him,
    then what is moving, then what he touched last. Two passes rather than one key,
    because the last part sorts DESCENDING and the first two ascending, and Python's sort
    is stable.
    """
    ordered = sorted(cards, key=lambda card: card.get("updated_at") or "", reverse=True)
    ordered.sort(key=lambda card: (0 if (card.get("derived") or {}).get("needs_you") else 1,
                                   0 if card.get("stage") in LIVE_STAGES else 1))
    return ordered


def _queue_row(card: dict) -> dict:
    """One needs-you card in the shape the shared queue fold reads.

    `by_hand` RATHER THAN `on_approve`, for the reason `snapshot._queue_row` records at
    length: `kb approve` refuses without the deck's human token, so a gate is something
    only his own hands answer, and the fold reads what a row CARRIES rather than its
    `kind` label.
    """
    derived = card.get("derived") or {}
    gate = bool(derived.get("plan_gate") or derived.get("outcome_gate"))
    row = {"id": card.get("id"), "status": "pending",
           "kind": "approval" if gate else "notice",
           "what": (f"{card.get('title')}: {card['blocked_reason']}"
                    if card.get("blocked_reason") else (card.get("title") or "")),
           "at": card.get("updated_at") or ""}
    if gate:
        row["by_hand"] = ("approve it on the deck" if derived.get("outcome_gate")
                          else "answer the plan gate on the deck")
    return row


def _review_rows(cards: list, space: str) -> list:
    """The review cards of a space (lane RC): what the deck's Reviews list shows, one row
    each, identity, title, repo and where the review stands (`derived.review`). The old
    scanner's rows are no longer read, so what a Harbor says is what the deck shows."""
    return [{"id": card.get("id") or "", "title": card.get("title") or "", "repo": card.get("repo") or "",
             "state": (card.get("derived") or {}).get("review") or ""}
            for card in cards if card.get("space") == space and (card.get("derived") or {}).get("review")]


def _space_routes(cards: list, space: str) -> dict:
    """The space's review cards under `reviews`. No provider's rows are read: the adapter's
    old review rows went with lane RC and its pull request rows with lane RETIRE."""
    reviews = _review_rows(cards, space)
    return {"reviews": reviews} if reviews else {}


def _segment_rows(state: dict) -> list:
    """Name and headline. The headline is the segment's own first tile, label and value,
    which is what the deck's card shows at a glance; for a segment never fetched, the
    state's own words for that (`deckstate.segment_entry`, c-742)."""
    rows = []
    for entry in state.get("segments") or []:
        tiles = ((entry.get("summary") or {}).get("tiles")) or []
        first = tiles[0] if tiles else {}
        headline = " ".join(str(part) for part in (first.get("label"), first.get("value")) if part)
        headline = headline or entry.get("fetch_said") or ""
        rows.append({"name": entry.get("name") or "", "headline": headline})
    return rows


def _bosun(console) -> dict | None:
    """Bosun as the deck's `console` entry has it (c-523, BO-5): its state word, whether
    voice holds it, its open asks with their option labels (Harbor reads those to him), and
    the real counts. Never an option's `does` nor a request's text: those are bodies, and
    `kb console show` reads one when he asks. None where there is no console at all."""
    if not isinstance(console, dict):
        return None
    asks = [row for row in console.get("asks") or [] if row.get("state") == "open"]
    counts = console.get("counts") or {}
    return {"state": "on voice" if console.get("voice") else str(console.get("state") or ""),
            "lastTurn": console.get("last_turn") or "",
            "asks": [{"id": row.get("id"), "kind": row.get("kind"), "card": row.get("card") or "",
                      "question": row.get("question") or "",
                      "options": [f'{opt.get("letter")} {opt.get("label")}'
                                  for opt in row.get("options") or []],
                      "files": _files_line(row)} for row in asks],
            "asksOpen": int(counts.get("asks") or len(asks)),
            "requestsOpen": int(counts.get("requests") or 0)}


def _files_line(row: dict) -> str:
    """"B files a personal card in keel": where an escalation's filed card builds, so the
    voice says it before he picks (c-550). The words are `asks.where`'s, kept here because
    this file imports nothing from `keel`. Empty when no option files a card."""
    opt = next((o for o in row.get("options") or [] if isinstance(o, dict) and o.get("files")), None)
    if opt is None:
        return ""
    files = opt["files"]
    if "repo" not in files:
        where = "repo from its card"
    elif not files["repo"]:
        where = "as an errand, no repo"
    else:
        came = files.get("repo_from")
        where = f'in {files["repo"]}' + (f" (from {came})" if came and came != "stated" else "")
    if files.get("kind"):
        where += f', marked {files["kind"]}'
    return f'{opt.get("letter")} files a personal card {where}'


def fold(state: dict, harbor_running: bool = False) -> dict:
    """The deck's state document, folded into the gateway's document.

    `harbor_running` is passed in rather than read: the deck does not know whether the
    phone talker is up (a Remote Control session is not a kind the harness lists), so
    whoever calls this answers that from the pid file.
    """
    # Only the spaces the deck serves: a card of one no longer configured (the retired
    # console space, c-593) is not his to hear about.
    known = set((state.get("spaces") or {}).keys())
    cards = [card for card in (state.get("cards") or [])
             if not (card.get("derived") or {}).get("archived")
             and (not known or card.get("space") in known)]
    by_id = {card.get("id"): card for card in state.get("cards") or []}
    spaces = sorted(known) or sorted({card.get("space") or "" for card in cards} - {""})
    houses = set(state.get("houses") or [])
    running = [{"id": card.get("id"), "name": card.get("title"), "space": card.get("space"),
                "state": "blocked" if card.get("blocked_reason") else card.get("stage"),
                "at": card.get("updated_at")}
               for card in cards if card.get("id") in houses]
    queue = [_queue_row(by_id[cid]) for cid in state.get("needs_you") or [] if cid in by_id]
    drain = state.get("drain") or {}
    return {
        "source": "deck",
        "at": state.get("now") or "",
        "counts": {"running": len(running), "notices": len(queue), "cards": len(cards)},
        "harbor": {"running": bool(harbor_running)},
        "running": running,
        "queue": queue,
        "cards": [card_row(card, (state.get("spaces") or {}).get(card.get("space"), {}).get("terms"))
                  for card in order_cards(cards)],
        "providers": {space: _space_routes(cards, space) for space in spaces},
        "segments": _segment_rows(state),
        "drain": {"text": drain.get("text") or "", "alive": bool(drain.get("alive"))},
        "topics": {space: list((state.get("spaces") or {}).get(space, {}).get("topics") or [])
                   for space in spaces},
        "spaceCounts": {space: dict((state.get("spaces") or {}).get(space, {}).get("counts") or {})
                        for space in spaces},
        "bosun": _bosun(state.get("console")),
    }


# --------------------------------------------------------------------------- #
# The digest a turn carries.
# --------------------------------------------------------------------------- #

def _card_line(row: dict) -> str:
    parts = [str(row.get("id") or ""), clip(row.get("title"))]
    tail = [bit for bit in (row.get("stage"), row.get("pr") and f"pr: {row['pr']}",
                            row.get("blocked") and f"blocked: {clip(row['blocked'], 40)}") if bit]
    return f"{' '.join(parts)} ({', '.join(tail)})" if tail else " ".join(parts)


def _ask_line(row: dict) -> str:
    """"a-31 approval on c-540: Deploy next to main? A Yes, deploy / B Not yet"."""
    head = " ".join(bit for bit in (str(row.get("id") or ""), str(row.get("kind") or ""),
                                    row.get("card") and f'on {row["card"]}') if bit)
    options = " / ".join(clip(option, OPTION_CHARS) for option in row.get("options") or [])
    files = f'; {row["files"]}' if row.get("files") else ""
    return f'{head}: {clip(row.get("question"), QUESTION_CHARS)} {options}{files}'.strip()


def _bosun_digest(block) -> dict | None:
    if not isinstance(block, dict):
        return None
    asks = block.get("asks") or []
    return {"state": block.get("state") or "", "asksOpen": block.get("asksOpen", len(asks)),
            "requestsOpen": block.get("requestsOpen", 0),
            "asks": [_ask_line(row) for row in asks[:ASK_ROWS]]}


def _provider_line(row: dict) -> str:
    bits = [bit for bit in (row.get("id"), clip(row.get("title")), row.get("repo"),
                            row.get("state")) if bit]
    return " | ".join(str(bit) for bit in bits)


def _tally(rows: list, key: str) -> dict:
    """How many rows sit in each value of `key`, over EVERY row rather than the sample.

    THE CAP MUST NEVER REACH A COUNT, and a per-lane count is still a count. The first
    live turn after the deck digest landed said "three open and the rest behind" about
    thirteen pull requests, because four were open and only three of them survived the
    twelve row sample. The section's total was right and its breakdown was not, which is
    the same failure one level down. So the breakdown is tallied here, off all of them.
    """
    out: dict = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def _section(rows: list, cap: int, line, by: str = "") -> dict:
    """A real count, a real breakdown, and a capped sample: the honesty of this file."""
    out = {"count": len(rows), "rows": [line(row) for row in rows[:cap]]}
    if by:
        out["states"] = _tally(rows, by)
    return out


def provider_rows(doc: dict, route: str, space: str = "") -> list:
    """One route's rows out of a folded document, for one space or across all of them.

    Only a space with an adapter has provider routes at all, so in practice this is the
    work space; it is written per space rather than hard-coded so a second adapter needs
    no change here.
    """
    providers = doc.get("providers") or {}
    names = [space] if space else sorted(providers)
    rows = []
    for name in names:
        rows.extend((providers.get(name) or {}).get(route) or [])
    return rows


def build(doc: dict) -> dict:
    """Names, ids, states and counts. Nothing a model could paraphrase into a value."""
    cards = doc.get("cards") or []
    spaces = sorted({str(row.get("space") or "") for row in cards} - {""}) or \
        sorted((doc.get("topics") or {}).keys())
    queue = [row for row in (doc.get("queue") or []) if row.get("status", "pending") == "pending"]
    per_space = {}
    for space in spaces:
        rows = [row for row in cards if row.get("space") == space]
        counts = (doc.get("spaceCounts") or {}).get(space) or {}
        # PER STAGE, BECAUSE THE CAP WOULD OTHERWISE MAKE COUNTING WRONG. "How many cards
        # are in the work inbox" is a counting question, and counting the capped sample
        # answers it wrong the moment a space has more than CARD_ROWS cards. The tally is
        # over every unarchived card in the space, the rows under it are the sample.
        stages = _tally(rows, "stage")
        # COUNTED OFF THE ROWS, not off the deck's own `counts` block, so the count and
        # the sample under it can never disagree: they are the same list, and the board
        # fallback has no `counts` block to read anyway. `backlog` is the one number that
        # is not derivable here (it is a subset of these rows, dated by the board), so it
        # is taken from the deck when the deck said it.
        per_space[space] = {"count": len(rows),
                            "needsYou": sum(1 for row in rows if row.get("needsYou")),
                            "backlog": counts.get("backlog", 0),
                            "stages": stages,
                            "rows": [_card_line(row) for row in rows[:CARD_ROWS]]}
    return {
        "source": doc.get("source") or "board",
        "counts": dict(doc.get("counts") or {}),
        "harborUp": bool((doc.get("harbor") or {}).get("running")),
        "drain": clip((doc.get("drain") or {}).get("text"), DRAIN_CHARS),
        "running": [f'{str(row.get("id") or "")} {clip(row.get("name"))} ({row.get("state")})'
                    for row in (doc.get("running") or [])[:RUNNING_ROWS]],
        "queuePending": len(queue),
        "queueTop": [clip(row.get("what")) for row in queue[:QUEUE_TOP]],
        "cards": per_space,
        "reviews": _section(provider_rows(doc, "reviews"), REVIEW_ROWS, _provider_line, "state"),
        "segments": [f'{row.get("name")}: {row.get("headline")}'.strip().rstrip(":")
                     for row in (doc.get("segments") or [])[:SEGMENT_ROWS]],
        "topics": {space: list(topics)[:TOPIC_ROWS]
                   for space, topics in (doc.get("topics") or {}).items()},
        "bosun": _bosun_digest(doc.get("bosun")),
    }


def as_json(doc: dict) -> str:
    return json.dumps(build(doc), indent=1)


def measure(doc: dict) -> tuple[int, int]:
    """(bytes, approximate tokens). Four bytes a token, the ratio the whole design was
    budgeted against; it is a rule of thumb and it is used as one."""
    blob = as_json(doc)
    return len(blob), len(blob) // 4


# --------------------------------------------------------------------------- #
# One section as a table, for `keel deck <section>`.
# --------------------------------------------------------------------------- #

# The columns each section prints, as (heading, key). A section prints the WHOLE list, not
# the digest's capped sample: he is reading it on a screen, not hearing it in a sentence.
COLUMNS = {
    "cards": (("id", "id"), ("stage", "stage"), ("space", "space"), ("title", "title"),
              ("pr", "pr"), ("blocked", "blocked")),
    "reviews": (("id", "id"), ("state", "state"), ("repo", "repo"), ("title", "title")),
    "segments": (("segment", "name"), ("headline", "headline")),
    "bosun": (("ask", "id"), ("kind", "kind"), ("card", "card"), ("question", "question"),
              ("options", "choices"), ("files", "files")),
}
CELL_CHARS = 60


def section_rows(doc: dict, section: str, space: str = "") -> list:
    """One folded section's rows, filtered by space where a space means anything."""
    if section == "cards":
        rows = doc.get("cards") or []
        return [row for row in rows if not space or row.get("space") == space]
    if section in PROVIDER_ROUTES:
        return provider_rows(doc, section, space)
    if section == "segments":
        return list(doc.get("segments") or [])
    if section == "bosun":
        return [dict(row, choices=" / ".join(row.get("options") or []))
                for row in (doc.get("bosun") or {}).get("asks") or []]
    raise ValueError(f"unknown section {section!r}; one of {', '.join(SECTIONS)}")


def table(rows: list, columns) -> str:
    """Plain columns, sized to what is in them, with a rule under the headings. No box
    drawing: this is read in a terminal and piped into `grep` as often as it is read."""
    cells = [[clip(row.get(key), CELL_CHARS) for _, key in columns] for row in rows]
    widths = [max([len(head)] + [len(cell[i]) for cell in cells])
              for i, (head, _) in enumerate(columns)]
    lines = ["  ".join(head.ljust(widths[i]) for i, (head, _) in enumerate(columns)).rstrip(),
             "  ".join("-" * width for width in widths).rstrip()]
    for cell in cells:
        lines.append("  ".join(value.ljust(widths[i]) for i, value in enumerate(cell)).rstrip())
    return "\n".join(lines)


def bosun_line(doc: dict) -> str:
    block = doc.get("bosun")
    if not isinstance(block, dict):
        return "bosun: no console on this deck"
    return (f'bosun: {block.get("state") or "unknown"}, {block.get("asksOpen", 0)} open asks, '
            f'{block.get("requestsOpen", 0)} open requests')


def render_section(doc: dict, section: str, space: str = "") -> str:
    rows = section_rows(doc, section, space)
    if section == "bosun":
        head = bosun_line(doc)
        return f"{head}\n\n{table(rows, COLUMNS[section])}" if rows else head
    where = f" in {space}" if space else ""
    if not rows:
        return f"no {section}{where}"
    return f"{table(rows, COLUMNS[section])}\n\n{len(rows)} {section}{where}"


def overview(doc: dict) -> str:
    """What `keel deck` alone prints: one line per section, and where it was read from."""
    digest = build(doc)
    lines = [f"source: {digest['source']}"]
    for space, block in sorted((digest.get("cards") or {}).items()):
        stages = ", ".join(f"{stage} {count}" for stage, count in block["stages"].items())
        lines.append(f"cards ({space}): {block['count']}" + (f"  [{stages}]" if stages else ""))
    lines += [f"needs you: {digest['queuePending']}",
              f"running: {len(digest['running'])}",
              f"reviews: {digest['reviews']['count']}",
              f"segments: {len(digest['segments'])}",
              bosun_line(doc),
              f"drain: {digest['drain'] or 'no line'}"]
    return "\n".join(lines)
