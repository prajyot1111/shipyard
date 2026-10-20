"""The deploy ask: his one Yes that moves main to the integration branch (c-526, his D3).

An outcome approved on a repo with an integration branch (`[integration]`, `next` for Keel)
lands there and goes live only when he says so. The box's drain raises that question as an
ask (`keel/asks.py`), raiser `drain`, when the integration branch is ahead of main: option A
is Deploy, B is Not yet, and option A carries the facts (`deploy`: the repo, the sha it
pins, the cards it carries). One ask per sha: a `next` that moves while it is open
withdraws it and raises another; an answered one is not raised again until `next` moves.

Only his tap or his voice answers it: a chat answer, which Bosun records, is refused, so
Bosun's reading of the chat can never become a deploy. His A is not delivered to Bosun to
carry out: it is the drain's to act on (`keel/deploy.py` runs the worker), and the ask's
own events record what happened (`deploying`, `deployed`, `refused`). The `kb` that records
his Deploy kicks this machine's drain (`kick.after_deploy`), which starts it at once; until
a worker takes it the ask reads `starting` (waiting for the drain once that has lasted two
drain polls), and each phase after (`steps_of`: merge, suite, live, then deployed or
refused) is on its record with the time it began (c-636).

`kb console deploy [--preview]` is the same Yes from a terminal or Harbor: it answers the
open deploy ask with A, raising it first when `next` moved past the last one.
"""

from __future__ import annotations

import json
from datetime import datetime

from keel import asks, kick
from keel.board import Board, Refused

RAISER = "drain"
DEPLOYERS = ("human", "voice")
DEPLOY_KEY = "deploy"
# The moves on an ask's own record once he said Deploy.
DEPLOYING, DEPLOYED, REFUSED = "deploying", "deployed", "refused"
# After `deployed`: a running process now runs code that carries the deploy (c-557). Since
# c-622 nothing reports another machine's loaded head, so no `running` is written; one
# recorded before is still read.
RUNNING = "running"
# His Yes that no worker has taken yet (c-636): not a move on the record, the ask's own state
# (`untaken`, what `to_start` reads), so the page says so the instant he taps.
STARTING = "starting"
# The phases a `deploying` move names, each recorded as it begins (c-636): the drain took
# it, the tree is built (the trunk merged in when it moved), the suite runs, main moved.
START, MERGE, SUITE, LIVE_PHASE = "start", "merge", "suite", "live"
CARDS_SHOWN = 12


def facts_of(row: dict) -> dict | None:
    """The deploy facts option A carries, or None for any other ask."""
    options = row.get("options") or []
    if isinstance(options, str):
        options = json.loads(options or "[]")
    first = options[0] if options else {}
    return first.get(DEPLOY_KEY) if isinstance(first, dict) else None


def is_deploy(row: dict) -> bool:
    return facts_of(row) is not None


def cards_text(cards: list[str]) -> str:
    if not cards:
        return "no card merges (only the user's own commits)"
    shown = ", ".join(cards[:CARDS_SHOWN])
    return shown + (f" and {len(cards) - CARDS_SHOWN} more" if len(cards) > CARDS_SHOWN else "")


def question(found: dict) -> str:
    return (f"Deploy {found['target']} to {found['trunk']}? It carries "
            f"{cards_text(found['cards'])}")[:asks.QUESTION_MAX]


def options_for(found: dict) -> list[dict]:
    facts = {key: found[key] for key in ("repo", "space", "target", "trunk", "sha", "cards")}
    return [{"letter": "A", "label": "Deploy",
             "does": (f"Shipyard runs the full suite (every module, voice included) on "
                      f"{found['target']} at {found['sha'][:8]}, unless a full run already "
                      f"proved that exact tree green (c-544, c-646), then fast-forwards {found['trunk']} to it; then Shipyard "
                      f"restarts on it once no conversation or house call is open. Bosun "
                      f"does nothing."),
             DEPLOY_KEY: facts},
            {"letter": "B", "label": "Not yet",
             "does": (f"Nothing moves. {found['target']} keeps landing outcomes, and a new ask "
                      f"comes when it moves again.")}]


def raise_deploy(board: Board, found: dict, actor: str = RAISER) -> dict:
    """Raise the deploy ask for what `found` (`deploy.ahead`) says is waiting."""
    why = (f"{found['target']} is {len(found['cards'])} card(s) ahead of {found['trunk']}, "
           f"each tested on its merged tree; main moves only on your Yes.")
    with board.tx():
        aid, n = asks.next_id(board)
        at = board.now()
        board.conn.execute(
            "INSERT INTO asks (id, n, kind, actor, card, question, why, options, state, "
            "created_at, updated_at) VALUES (?, ?, 'approval', ?, NULL, ?, ?, ?, 'open', ?, ?)",
            (aid, n, actor, question(found), why, json.dumps(options_for(found)), at, at))
        asks.record(board, aid, None, "raised", actor, f"asked (deploy): {question(found)}",
                    sha=found["sha"])
    return asks.get(board, aid)


RECENT = 20


def rows_for(board: Board, repo: str) -> list[dict]:
    """This repo's newest deploy asks, newest first. Only the drain raises one and only the
    newest few can still matter (the open one, the one answered for the current sha), so a
    pass reads a bounded window, never the whole history (review F7). The window is of
    deploy asks only: the drain's login asks (c-558) must not push them out of it."""
    rows = board.conn.execute("SELECT * FROM asks WHERE actor = ? AND options LIKE ? "
                              "ORDER BY n DESC LIMIT ?",
                              (RAISER, f'%"{DEPLOY_KEY}": {{%', RECENT)).fetchall()
    return [one for one in (asks.as_dict(row) for row in rows)
            if (facts_of(one) or {}).get("repo") == repo]


def withdraw(board: Board, row: dict, why: str) -> None:
    """The drain takes back a deploy ask that no longer stands: `next` moved, or main has it."""
    with board.tx():
        found = asks.get(board, row["id"])
        if found["state"] != "open":
            return
        board.conn.execute("UPDATE asks SET state = 'withdrawn', words = ?, updated_at = ? "
                           "WHERE id = ?", (why, board.now(), row["id"]))
        asks.record(board, row["id"], None, "withdrawn", RAISER, f"withdrawn: {why}")


def moves(board: Board, aid: str) -> list[str]:
    return [(event.get("data") or {}).get("move") for event in board.events(aid)
            if event.get("kind") == "ask"]


def record(board: Board, aid: str, move: str, text: str, **data) -> None:
    with board.tx():
        asks.record(board, aid, None, move, RAISER, text, **data)


def deploying(board: Board, aid: str) -> dict | None:
    """The newest `deploying` record of an ask with no end after it: a worker's run."""
    events = [e for e in board.events(aid) if e.get("kind") == "ask"]
    for event in reversed(events):
        move = (event.get("data") or {}).get("move")
        if move in (DEPLOYED, REFUSED):
            return None
        if move == DEPLOYING:
            return event
    return None


def untaken(board: Board, row: dict) -> bool:
    """He said Deploy and no worker has taken it: no deploy move on its record yet."""
    return (row["state"] == "answered" and row.get("answer") == "A"
            and not any(m in (DEPLOYING, DEPLOYED, REFUSED) for m in moves(board, row["id"])))


def claim(board: Board, row: dict, text: str, **data) -> bool:
    """Take his Deploy for a worker (review F2): in one write transaction (`BEGIN
    IMMEDIATE`), re-read that it is still untaken and record its `start` phase, so two
    drains (a pass and the kick thread, or `keel drain --once` in another process) never
    both take it. True only for the one that wrote it."""
    with board.tx():
        if not untaken(board, asks.get(board, row["id"])):
            return False
        asks.record(board, row["id"], None, DEPLOYING, RAISER, text, phase=START, **data)
    return True


def to_start(board: Board, repo: str) -> dict | None:
    """The deploy he said Yes to that no worker has taken yet (the newest, for this repo)."""
    for row in rows_for(board, repo):
        if row["state"] == "answered" and row["answer"] == "A":
            return row if untaken(board, row) else None
    return None


def refuse_chat(found: dict, channel: str) -> None:
    """A deploy is his tap or his voice (his D3): Bosun's record of a chat answer is refused."""
    if is_deploy(found) and channel == "chat":
        raise Refused(f"{found['id']} is a deploy ask: only the user's tap or voice answers it, "
                      f"never a chat answer Bosun records")


# ----- what the Bosun page's Shipped section reads (c-591) -----

LIVE_SHOWN = 5
RESULTS = (DEPLOYING, DEPLOYED, REFUSED, RUNNING)


def recent(board: Board) -> list[dict]:
    """Every repo's newest deploy asks, newest first (the same bounded window as `rows_for`)."""
    rows = board.conn.execute("SELECT * FROM asks WHERE actor = ? AND options LIKE ? "
                              "ORDER BY n DESC LIMIT ?",
                              (RAISER, f'%"{DEPLOY_KEY}": {{%', RECENT)).fetchall()
    return [asks.as_dict(row) for row in rows]


def seconds_between(earlier: str | None, later: str) -> float:
    try:
        return (datetime.fromisoformat(later) - datetime.fromisoformat(earlier or "")).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def worker_busy(board: Board, row: dict) -> bool:
    """Whether another Deploy of this repo still has a worker on it: the drain holds this one
    back on purpose until it ends, which is not the drain being away."""
    repo = (facts_of(row) or {}).get("repo")
    return bool(repo) and any(other["id"] != row["id"] and live(deploying(board, other["id"]))
                              for other in rows_for(board, repo))


def live(record: dict | None) -> bool:
    """A `deploying` record whose worker is still there, as `landing.dead` judges one (with
    no drain running, nothing answers a dead worker's record, so it must not count)."""
    from keel import landing                     # noqa: PLC0415 - landing imports the board
    data = (record or {}).get("data") or {}
    if not record:
        return False
    if data.get("pid"):
        return landing.alive(data["pid"])
    return landing.age_seconds(data.get("at")) <= landing.UNSTARTED_SECONDS


def starting(board: Board, row: dict, wait: float | None) -> dict:
    """His answer as the first step. Nothing here knows the drain heard it (`kb` tells his
    tap that), so it promises no "now"; untaken for longer than `wait` (two drain polls), it
    is waiting for the drain (review F3)."""
    step = {"move": STARTING, "phase": STARTING, "at": row.get("answered_at"), "sha": None,
            "text": "you said Deploy; it starts when the drain takes it", "waiting": False}
    held = seconds_between(row.get("answered_at"), board.now())
    if wait and held > wait and untaken(board, row) and not worker_busy(board, row):
        step.update(waiting=True, text=f"you said Deploy; waiting for the drain, which has not "
                                       f"taken it in {int(held)} s")
    return step


def steps_of(board: Board, row: dict, wait: float | None = None) -> list[dict]:
    """The phases a Deploy he said has passed, oldest first, each {move, phase, text, at,
    sha} as it began (c-636): his answer (`starting`), then each `deploying` phase
    (repeated records of one phase, such as the worker's pid, are that phase), then its end,
    whose `deck` says whether a deploy of Keel's own checkout saw the deck come up on it.
    A record from before the phases were named is the phase `deploying`."""
    steps = [starting(board, row, wait)]
    for event in board.events(row["id"]):
        data = event.get("data") or {}
        move = data.get("move")
        if event.get("kind") != "ask" or move not in RESULTS:
            continue
        phase = (data.get("phase") or DEPLOYING) if move == DEPLOYING else move
        if move == DEPLOYING and steps[-1]["move"] == DEPLOYING and steps[-1]["phase"] == phase:
            continue
        steps.append({"move": move, "phase": phase, "text": event.get("text") or "",
                      "at": event.get("at"), "sha": data.get("sha"), "deck": data.get("deck")})
    return steps


def result_of(board: Board, row: dict, wait: float | None = None) -> dict | None:
    """Where a Deploy he said stands: its newest phase {move, phase, text, at, sha} with every
    phase so far (`steps`), or None for an ask he did not say Deploy to. Answered and not yet
    taken by a worker is `starting` (`untaken`), so his tap reads true before the drain runs;
    `wait` is how long that may last before it is said to be waiting for the drain."""
    if row.get("state") != "answered" or row.get("answer") != "A":
        return None
    steps = steps_of(board, row, wait)
    return dict(steps[-1], steps=steps)


def brief_of(row: dict, result: dict | None = None) -> dict:
    facts = facts_of(row) or {}
    return {"ask": row["id"], "repo": facts.get("repo"), "target": facts.get("target"),
            "trunk": facts.get("trunk"), "sha": facts.get("sha"), "cards": facts.get("cards") or [],
            "at": row.get("updated_at"), "result": result}


def shipped(board: Board, wait: float | None = None) -> dict:
    """What is on the integration branch and not live (the open deploy ask), the last deploy's
    result, and the deploys that went live lately, all read from the deploy asks and their
    own moves: nothing is kept for it. The page's Deploy button answers `pending.ask` with A.
    `wait` is how long his Deploy may sit untaken before it reads waiting for the drain."""
    pending, last, live = None, None, []
    for row in recent(board):
        if row["state"] == "open":
            pending = pending or brief_of(row)
            continue
        result = result_of(board, row, wait)
        if result is None:
            continue
        last = last or brief_of(row, result)
        if result["move"] in (DEPLOYED, RUNNING) and len(live) < LIVE_SHOWN:
            live.append(brief_of(row, result))
    return {"pending": pending, "last": last, "live": live}


NEXT, LIVE = "next", "live"


def places(board: Board) -> tuple[dict[str, str], dict[str, str]]:
    """Where each card the recent deploy asks carry stands, `next` or `live`, and when each
    repo's newest standing ask was raised (c-592). The fallback of `bosuncards` for a repo
    not checked out on this machine; git decides everywhere else. The same asks and moves
    `shipped` reads: an open ask, or one he answered and that has not deployed, carries
    cards on `next`; a deployed one carries them live. Newest first, so a card's newest ask
    decides it; a withdrawn ask is superseded by the one raised after it and says nothing."""
    out: dict[str, str] = {}
    newest: dict[str, str] = {}
    for row in recent(board):
        if row["state"] == "withdrawn":
            continue
        facts = facts_of(row) or {}
        if facts.get("repo") and row.get("created_at"):
            newest.setdefault(facts["repo"], row["created_at"])
        where = NEXT
        result = result_of(board, row)
        if result is not None and result["move"] in (DEPLOYED, RUNNING):
            where = LIVE
        for card in facts.get("cards") or []:
            out.setdefault(card, where)
    return out, newest


# ----- kb console deploy -----

def command(cfg, board: Board, args, actor: str) -> dict:
    """`kb console deploy [--preview]`, run where the board and the repo live."""
    from keel import deploy
    if actor not in DEPLOYERS:
        raise Refused(f"a deploy is the user's alone (a tap or the user's voice); not {actor}'s")
    if not hasattr(board, "conn"):
        raise Refused("kb console deploy runs where the board lives")
    waiting = [found for found in (deploy.ahead(cfg, one) for one in deploy.repos(cfg)) if found]
    if getattr(args, "preview", False) or not waiting:
        return {"deploy": waiting, "preview": True}
    answered = []
    for found in waiting:
        row = next((r for r in rows_for(board, found["repo"])
                    if r["state"] == "open" and facts_of(r)["sha"] == found["sha"]), None)
        if row is None:
            for stale in rows_for(board, found["repo"]):
                if stale["state"] == "open":
                    withdraw(board, stale, f"{found['target']} moved to {found['sha'][:8]}")
            row = raise_deploy(board, found)
        answered.append(asks.answer(board, row["id"], actor, "A"))
    return {"deploy": waiting, "answered": [row["id"] for row in answered]}


def render(payload: dict) -> str:
    if not payload["deploy"]:
        return "nothing to deploy: every integration branch is at its trunk"
    lines = [f"{found['repo']}: {found['target']} at {found['sha'][:8]} is ahead of "
             f"{found['trunk']}, carrying {cards_text(found['cards'])}" for found in payload["deploy"]]
    if payload.get("answered"):
        when = ("it starts at once" if payload.get("kick") != kick.NOBODY else
                "no drain is listening here, so it starts when the drain next runs")
        lines.append(f"deploy asked of the drain ({', '.join(payload['answered'])}): {when}, "
                     f"and main moves only if the suite is green")
    return "\n".join(lines)
