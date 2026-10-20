"""Bosun's asks (c-517 BO-3; docs/atlas/96-bosun.md): every question Bosun has for him, as a record.

Two kinds are not Bosun's: the deploy ask, which the drain raises when the integration branch
is ahead of main and which only his tap or voice answers (`keel/deployask.py`, c-526), and
the login ask, which it raises for a red row on the Logins list (`keel/loginask.py`, c-558).

An ask is a row in the board's `asks` table (`board.SCHEMA`), numbered `a-N`, and every move
on it is an `ask` event under that id and, when it is about a card, on that card too. Three
kinds: an APPROVAL (a thing on Bosun's needs-you list, a deploy), a DECISION (a real choice),
an ESCALATION (a design change, filed as a personal card only on his answer). Two to four
options, lettered A to D in the order given: A is Bosun's recommendation BY POSITION, so it
cannot be anything but first, and each option says exactly what Bosun will do (`does`).

He answers three ways and all three write the same row: a TAP on the Console page (actor
`human`), VOICE through Harbor (actor `voice`), or in Bosun's CHAT, which Bosun records
itself (`--by chat`) with his exact message saved beside its reading (decision D1, his
answer). Words instead of an option close the ask as REDIRECTED: none of its options is done.

A tap or voice answer is recorded here and DELIVERED later, always by Bosun's hook
(`kb console hook`): atop his next message, or when Bosun runs it because the Mac's drain
sent it a message naming the answers (`consolewake.wake`, only when Bosun is up and idle,
c-530). The drain's claim is a lease on pointing, not a telling; the hook takes it, prints
the words and confirms them, so an answer reaches Bosun once. A chat answer is delivered as it is recorded: his message is the
turn. What Bosun is told is built from the row alone (`told`), the same words either way.
"""

import json
import re
from datetime import datetime, timedelta

from keel.board import AUTONOMY, Board, Refused

KINDS = ("approval", "decision", "escalation")
STATES = ("open", "answered", "redirected", "withdrawn")
LETTERS = "ABCD"
OPTIONS_MIN, OPTIONS_MAX = 2, 4
QUESTION_MAX = 240
WHY_MAX = 1000
LABEL_MAX = 80
DOES_MAX = 400
WORDS_MAX = 1000
MESSAGE_MAX = 4000
TITLE_MAX = 120
BRIEF_MAX = 2000
# Who raises one: Bosun, and he himself (a scratch board, a test by hand). The drain raises
# two kinds of its own, the deploy ask through `keel/deployask.py` (c-526) and the login ask
# through `keel/loginask.py` (c-558), and only there.
RAISERS = ("bosun", "human")
# How an answer arrived, by who recorded it: the deck's tap is his, Harbor's is voice, and a
# chat answer is Bosun's reading of his message (D1). Nobody else answers an ask.
CHANNELS = {"human": "tap", "voice": "voice", "bosun": "chat"}
PERSONAL_SPACE = "personal"
ERRAND = "none"          # `--file-repo none`: the filed card is an errand on purpose (c-550)
# A filed card's brief naming an autonomy (c-584): checked against the `--file` field at raise.
AUTONOMY_WORD = re.compile(r"\b(" + "|".join(AUTONOMY) + r")\b", re.IGNORECASE)
FILE_KINDS = ("research",)   # `--file-kind`: the one kind a personal card means anything by (c-553)
# How long a claim holds before its answer counts as untold again: a wake or a hook whose
# confirm never arrived (a lost reply, a drain that died) is told once more after this.
LEASE_MINUTES = 10
# How many times the drain's wake points Bosun at one answer before it is left for the hook
# atop his next message (c-530). Counted from the ask's own `pointed` and `unpointed` moves,
# so the cap is on the board and never rolls off.
POINTS_MAX = 2
POINTS = ("(SELECT COALESCE(SUM(CASE json_extract(e.data, '$.move') WHEN 'pointed' THEN 1 "
          "WHEN 'unpointed' THEN -1 ELSE 0 END), 0) FROM events AS e "
          "WHERE e.card = asks.id AND e.kind = 'ask')")
WHO = {"human": "the user", "voice": "Harbor", "bosun": "Bosun", "drain": "the drain"}


# ----- reading -----

def as_dict(row) -> dict:
    found = {name: row[name] for name in row.keys()}
    found["options"] = json.loads(found.get("options") or "[]")
    return found


def get(board: Board, aid: str) -> dict:
    row = board.conn.execute("SELECT * FROM asks WHERE id = ?", (aid,)).fetchone()
    if row is None:
        raise Refused(f"no ask {aid}")
    return as_dict(row)


def listing(board: Board, everything: bool = False, closed: int = 0,
            since: str | None = None) -> list[dict]:
    """The open ones, newest first; `everything` adds every closed one, `closed` the newest
    that many closed ones (what the Bosun page's Now shows below the open), and `since` keeps
    only those closed at or after it (the tab shows the last day; the Journal keeps all)."""
    rows = [as_dict(row) for row in board.conn.execute(
        "SELECT * FROM asks WHERE state = 'open' ORDER BY n DESC")]
    if everything or closed:
        limit = "" if everything else f" LIMIT {int(closed)}"
        closed_rows = [as_dict(row) for row in board.conn.execute(
            f"SELECT * FROM asks WHERE state != 'open' ORDER BY n DESC{limit}")]
        if since and not everything:
            # Compared as moments: a board's stamps carry their machine's offset.
            floor = datetime.fromisoformat(since)
            closed_rows = [row for row in closed_rows
                           if datetime.fromisoformat(row["updated_at"]) >= floor]
        rows += closed_rows
    return rows


def open_count(board: Board) -> int:
    return board.conn.execute("SELECT COUNT(*) FROM asks WHERE state = 'open'").fetchone()[0]


def undelivered(board: Board, hook: bool = False) -> list[dict]:
    """Answered or redirected, not yet told to Bosun and not held by a live claim, oldest
    first. A claim older than LEASE_MINUTES that nobody confirmed is untold again. For
    Bosun's `hook`, a live WAKE claim does not hold one back: the wake only pointed at the
    answers (c-530), and the hook is how Bosun reads them. For the drain, a row a hook
    ever held is not listed: it waits for the next hook, which marks it told again; nor is
    one the wake has pointed at POINTS_MAX times."""
    rows = board.conn.execute(
        "SELECT * FROM asks WHERE state IN ('answered', 'redirected') AND delivered_at IS NULL "
        "AND (claimed_at IS NULL OR claimed_at < ? OR (? AND claimed_by = 'wake')) "
        f"AND (? OR (claimed_by IS NOT 'hook' AND {POINTS} < ?)) ORDER BY answered_at, n",
        (lease_cutoff(board), 1 if hook else 0, 1 if hook else 0, POINTS_MAX))
    return [as_dict(row) for row in rows]


def lease_cutoff(board: Board) -> str:
    return (datetime.fromisoformat(board.now()) - timedelta(minutes=LEASE_MINUTES)).isoformat()


def journal(board: Board, limit: int = 50) -> list[dict]:
    """Every move on every ask, newest first, in the shape the Journal reads. The wake's
    `pointed` and `unpointed` moves are its count (`POINTS_MAX`), not his story: they are
    left out, so a relay that keeps failing never pushes his answers out of the window. The
    Console's own history says each telling."""
    rows = board.conn.execute(
        "SELECT e.id, e.card, e.at, e.actor, e.text, e.data FROM events AS e "
        "WHERE e.kind = 'ask' AND e.card LIKE 'a-%' "
        "AND COALESCE(json_extract(e.data, '$.move'), '') NOT IN ('pointed', 'unpointed') "
        "ORDER BY e.id DESC LIMIT ?", (limit,))
    out = []
    for row in rows:
        entry = {name: row[name] for name in row.keys()}
        entry["move"] = json_of(entry.pop("data")).get("move")
        out.append(entry)
    return out


def json_of(raw) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


# ----- raising -----

def one_line(text, most: int, name: str, required: bool = True) -> str:
    text = " ".join(str(text or "").split())
    if required and not text:
        raise Refused(f"an ask needs {name}")
    if len(text) > most:
        raise Refused(f"the {name} is {len(text)} characters; at most {most}")
    return text


def parse_option(text: str) -> dict:
    """`label|does`: what the button says, and exactly what Bosun will do."""
    label, sep, does = str(text or "").partition("|")
    if not sep:
        raise Refused(f"an option is \"label|what it does\": {text!r}")
    return {"label": one_line(label, LABEL_MAX, "a label on each option"),
            "does": one_line(does, DOES_MAX, "what each option does")}


def parse_file(text: str, count: int) -> tuple[str, dict]:
    """`letter|title|brief[|autonomy]`: the personal card an escalation's option files on his
    answer. The autonomy is the last field, read only when it is one of `AUTONOMY`, so a
    brief may still hold a `|`. A brief that names an autonomy the field does not say is
    refused: c-575 was filed with "Attended: plan first" in its brief and the default in its
    field, and its house had to set the field itself (the words are checked, never parsed
    to decide)."""
    parts = str(text or "").split("|", 2)
    if len(parts) != 3:
        raise Refused(f"--file is \"letter|title|brief|autonomy\": {text!r}")
    letter = parts[0].strip().upper()
    if letter not in LETTERS[:count]:
        raise Refused(f"--file names option {letter!r}; this ask has {LETTERS[:count]}")
    brief, autonomy = split_autonomy(parts[2])
    card = {"title": one_line(parts[1], TITLE_MAX, "a title for the card it files"),
            "brief": one_line(brief, BRIEF_MAX, "a brief for the card it files")}
    refuse_named_autonomy(card["brief"], autonomy)
    if autonomy:
        card["autonomy"] = autonomy
    return letter, card


def split_autonomy(rest: str) -> tuple[str, str | None]:
    """The brief and the autonomy field, when the text after the last `|` is one."""
    brief, sep, last = rest.rpartition("|")
    word = last.strip().lower()
    if sep and word in AUTONOMY:
        return brief, word
    return rest, None


def refuse_named_autonomy(brief: str, autonomy: str | None) -> None:
    named = sorted({word.lower() for word in AUTONOMY_WORD.findall(brief)})
    wrong = [word for word in named if word != autonomy]
    if wrong:
        said = f"says {autonomy}" if autonomy else "is not given"
        raise Refused(f"the filed card's brief names {' and '.join(wrong)} but its autonomy "
                      f"{said}: put it in the field, --file \"letter|title|brief|"
                      f"{wrong[0]}\", and keep the brief to the work")


def build_options(options: list[str], kind: str, files: str | None,
                  file_repo: str | None = None, file_kind: str | None = None) -> list[dict]:
    if not OPTIONS_MIN <= len(options or ()) <= OPTIONS_MAX:
        raise Refused(f"an ask has {OPTIONS_MIN} to {OPTIONS_MAX} options, Bosun's "
                      f"recommendation first; this one has {len(options or ())}")
    built = [dict(parse_option(text), letter=LETTERS[i]) for i, text in enumerate(options)]
    if kind == "escalation":
        if not files:
            raise Refused("an escalation names the personal card its filing option files: "
                          "--file \"letter|title|brief|autonomy\"")
        letter, card = parse_file(files, len(built))
        if file_kind:
            card["kind"] = file_kind
        built[LETTERS.index(letter)]["files"] = card
    elif files:
        raise Refused(f"only an escalation files a card on the user's answer; this is a {kind}")
    elif file_repo is not None:
        raise Refused(f"--file-repo names where an escalation's filed card builds; this is a {kind}")
    elif file_kind is not None:
        raise Refused(f"--file-kind marks an escalation's filed card; this is a {kind}")
    return built


def settle_repo(built: list[dict], file_repo: str | None, about: dict | None,
                check_repo=None) -> None:
    """The repo the filing option's card builds in, settled at raise so he sees it before he
    taps (c-550, r-21): `--file-repo`, else the `--card`'s, else refused. `none` is an errand
    on purpose, kept as `""`. `repo_from` says where it came from, for the surfaces."""
    option = next((o for o in built if o.get("files")), None)
    if option is None:
        return
    stated = " ".join(str(file_repo or "").split())
    if stated.lower() == ERRAND:
        repo, came = "", "stated"
    elif stated:
        repo, came = stated, "stated"
    elif about is not None and about.get("repo"):
        repo, came = about["repo"], about["id"]
    else:
        raise Refused("an escalation's filing option names the repo its card builds in: "
                      "--file-repo <key> (`kb repos --space personal` lists them), or "
                      f"--file-repo {ERRAND} for an errand")
    if repo and check_repo is not None:
        check_repo(repo)
    option["files"].update(repo=repo, repo_from=came)


def next_id(board: Board) -> tuple[str, int]:
    n = (board.conn.execute("SELECT MAX(n) FROM asks").fetchone()[0] or 0) + 1
    return f"a-{n}", n


def record(board: Board, aid: str, card: str | None, move: str, actor: str, text: str,
           **data) -> None:
    """One move, under the ask and on the card it is about, so both histories show it."""
    board.record_event(aid, "ask", actor, text=text, data={"move": move, **data})
    if card and board.exists(card):
        board.record_event(card, "ask", actor, text=f"{aid} {text}", data={"move": move, "ask": aid})


def raise_ask(board: Board, actor: str, kind: str, question: str, why: str,
              options: list[str], card: str | None = None, files: str | None = None,
              file_repo: str | None = None, check_repo=None,
              file_kind: str | None = None) -> dict:
    if actor not in RAISERS:
        raise Refused(f"an ask is Bosun's to raise; not {actor}'s")
    if kind not in KINDS:
        raise Refused(f"an ask is {', '.join(KINDS)}; not {kind!r}")
    question = one_line(question, QUESTION_MAX, "a question")
    why = one_line(why, WHY_MAX, "a why (--why)")
    if file_kind is not None and file_kind not in FILE_KINDS:
        raise Refused(f"--file-kind is {', '.join(FILE_KINDS)}; not {file_kind!r}")
    built = build_options(options, kind, files, file_repo, file_kind)
    with board.tx():
        about = dict(board._row(card)) if card is not None else None
        settle_repo(built, file_repo, about, check_repo)
        aid, n = next_id(board)
        at = board.now()
        board.conn.execute(
            "INSERT INTO asks (id, n, kind, actor, card, question, why, options, state, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (aid, n, kind, actor, card, question, why, json.dumps(built), at, at))
        record(board, aid, card, "raised", actor, f"asked ({kind}): {question}")
    return get(board, aid)


# ----- answering -----

def channel_of(actor: str, by: str | None) -> str:
    channel = CHANNELS.get(actor)
    if channel is None:
        raise Refused(f"an ask is the user's to answer: by tap, by voice, or in Bosun's chat; not "
                      f"{actor}'s")
    if by is not None and by != channel:
        raise Refused(f"an answer by {by} is recorded by "
                      f"{next(a for a, c in CHANNELS.items() if c == by) if by in CHANNELS.values() else 'nobody'}"
                      f"; {actor} records {channel}")
    if channel == "chat" and by != "chat":
        raise Refused("Bosun records the user's chat answer with --by chat and the user's exact message "
                      "(--message)")
    return channel


def check_answer(found: dict, letter: str | None, words: str, message: str,
                 channel: str) -> str | None:
    if found["state"] != "open":
        raise Refused(f"{found['id']} is {found['state']}; only an open ask is answered")
    if channel == "chat" and not message:
        raise Refused("a chat answer keeps the user's exact message beside it: --message")
    if letter is None:
        if not words:
            raise Refused("an answer is an option's letter, or the user's own words (--words), "
                          "which redirect it")
        return None
    letter = letter.strip().upper()
    letters = [option["letter"] for option in found["options"]]
    if letter not in letters:
        raise Refused(f"{found['id']} has options {', '.join(letters)}; not {letter!r}")
    return letter


def answer(board: Board, aid: str, actor: str, letter: str | None = None, words: str = "",
           by: str | None = None, message: str = "") -> dict:
    """Record his answer: an option, with his words beside it, or his words alone (a
    redirect). A chat answer is delivered as it is recorded; a tap or voice one waits for
    the wake or the hook. An escalation's filing option files its personal card here."""
    channel = channel_of(actor, by)
    words = one_line(words, WORDS_MAX, "words", required=False)
    message = str(message or "").strip()
    if len(message) > MESSAGE_MAX:
        raise Refused(f"the message is {len(message)} characters; at most {MESSAGE_MAX}")
    with board.tx():
        found = get(board, aid)
        from keel import deployask, loginask      # they build on this module
        deployask.refuse_chat(found, channel)
        letter = check_answer(found, letter, words, message, channel)
        at = board.now()
        state = "answered" if letter else "redirected"
        filed = file_card(board, found, letter, actor)
        # A deploy ask's answer is the drain's to act on, never Bosun's to carry out (c-526),
        # and a login ask's needs nobody to act (c-558): each is delivered as it is recorded,
        # so no wake tells Bosun to do it.
        told_as = ("deploy" if deployask.is_deploy(found)
                   else "login" if loginask.is_login(found)
                   else "chat" if channel == "chat" else None)
        board.conn.execute(
            "UPDATE asks SET state = ?, answer = ?, words = ?, message = ?, channel = ?, "
            "answered_by = ?, answered_at = ?, filed_as = ?, delivered_at = ?, delivered_by = ?, "
            "updated_at = ? WHERE id = ?",
            (state, letter, words or None, message or None, channel, actor, at, filed,
             at if told_as else None, told_as, at, aid))
        record(board, aid, found["card"], state, actor, said_answer(dict(
            found, state=state, answer=letter, words=words, channel=channel, filed_as=filed)),
            answer=letter, channel=channel)
    return dict(get(board, aid), told=told([get(board, aid)]))


def file_card(board: Board, found: dict, letter: str | None, actor: str) -> str | None:
    """The personal inbox card an escalation's option files, only on his picking it, inside
    the answer's own write (`Board.create_in_tx`: create's own rules, no second write)."""
    option = pick(found, letter)
    if not option or not option.get("files"):
        return None
    files = option["files"]
    source = found["card"] if found["card"] and board.exists(found["card"]) else None
    # An ask raised before c-550 has no `repo` on its option: it files from its card, as then.
    repo = files.get("repo") or None
    # `kind` is his to set after create (`board.HUMAN_ONLY_OPTIONS`); here it is set at
    # create, by his answer to the option that showed it (c-553).
    marked = {"kind": files["kind"]} if files.get("kind") else None
    # c-584: an ask raised before the autonomy field has none, and files at the default.
    card = board.create_in_tx(PERSONAL_SPACE, files["title"], brief=files["brief"],
                              autonomy=files.get("autonomy"), actor=actor, from_card=source, repo=repo,
                              errand="repo" in files and not repo, options=marked)
    board.record_event(card, "note", actor,
                       text=f"filed on the user's answer to {found['id']} ({found['question']})")
    return card


def pick(found: dict, letter: str | None) -> dict | None:
    return next((o for o in found["options"] if o["letter"] == letter), None) if letter else None


def withdraw(board: Board, aid: str, actor: str, why: str) -> dict:
    if actor != "bosun":
        raise Refused(f"withdrawing an ask is Bosun's (the question no longer stands); not "
                      f"{actor}'s. Answer it instead")
    why = one_line(why, WHY_MAX, "a reason (--why)")
    with board.tx():
        found = get(board, aid)
        if found["state"] != "open":
            raise Refused(f"{aid} is {found['state']}; only an open ask is withdrawn")
        from keel import deployask, loginask
        if deployask.is_deploy(found):
            raise Refused(f"{aid} is the drain's deploy ask: it withdraws it itself when "
                          f"the branch moves")
        if loginask.is_login(found):
            raise Refused(f"{aid} is the drain's login ask: it withdraws it itself when "
                          f"the login answers again")
        board.conn.execute("UPDATE asks SET state = 'withdrawn', words = ?, updated_at = ? "
                           "WHERE id = ?", (why, board.now(), aid))
        record(board, aid, found["card"], "withdrawn", actor, f"withdrawn: {why}")
    return get(board, aid)


# ----- delivering -----

def claim(board: Board, ids: list[str], via: str) -> list[dict]:
    """Hold these answers for telling Bosun by `via` (wake or hook): each only if it is still
    untold and no live claim holds it, except that the hook takes a wake's claim (the wake
    only pointed at them, c-530). A LEASE, not the delivery: `confirm` records the delivery
    once Bosun has them, and a claim nobody confirms runs out (`undelivered`), so a lost
    reply or a drain that died costs a repeat, never a lost answer. A row the HOOK claimed
    before comes back with `again`, and Bosun is told it may have had it already; a wake's
    claim never printed the words, so it does not count. So that mark is never lost, the
    wake never takes a row a hook has held: that one waits for the next hook, marked. Each
    wake claim is a `pointed` move on the ask, and the wake stops at POINTS_MAX of them."""
    claimed = []
    with board.tx():
        at, cutoff = board.now(), lease_cutoff(board)
        for aid in ids:
            before = board.conn.execute("SELECT claimed_at, claimed_by FROM asks WHERE id = ?",
                                        (aid,)).fetchone()
            cur = board.conn.execute(
                "UPDATE asks SET claimed_at = ?, claimed_by = ?, updated_at = ? WHERE id = ? "
                "AND delivered_at IS NULL AND state IN ('answered', 'redirected') "
                "AND (claimed_at IS NULL OR claimed_at < ? OR (? = 'hook' AND claimed_by = 'wake')) "
                f"AND NOT (? = 'wake' AND (claimed_by IS 'hook' OR {POINTS} >= ?))",
                (at, via, at, aid, cutoff, via, via, POINTS_MAX))
            if cur.rowcount and via == "wake":
                board.record_event(aid, "ask", "drain", text="pointed at by the drain's wake",
                                   data={"move": "pointed"})
            if cur.rowcount:
                again = bool(before and before[0]) and before[1] == "hook"
                claimed.append(dict(get(board, aid), again=again))
    return claimed


def confirm(board: Board, ids: list[str], via: str) -> list[dict]:
    """Bosun has these answers: the wake returned, or the hook printed them."""
    with board.tx():
        at = board.now()
        for aid in ids:
            board.conn.execute(
                "UPDATE asks SET delivered_at = ?, delivered_by = ?, updated_at = ? WHERE id = ? "
                "AND delivered_at IS NULL AND claimed_by = ?", (at, via, at, aid, via))
    return [get(board, aid) for aid in ids]


def unclaim(board: Board, ids: list[str], via: str = "wake") -> None:
    """A wake that did not happen: its answers are untold again at once, and its `pointed`
    move is taken back (`unpointed`), so it does not count toward POINTS_MAX."""
    with board.tx():
        at = board.now()
        for aid in ids:
            cur = board.conn.execute("UPDATE asks SET claimed_at = NULL, claimed_by = NULL, "
                                     "updated_at = ? WHERE id = ? AND delivered_at IS NULL "
                                     "AND claimed_by = ?", (at, aid, via))
            if cur.rowcount and via == "wake":
                board.record_event(aid, "ask", "drain", text="handed back: the wake sent nothing",
                                   data={"move": "unpointed"})


# ----- saying it -----

def who(row: dict) -> str:
    return {"tap": "by tap", "voice": "by voice", "chat": "in the chat"}.get(row.get("channel"), "")


def quoted(text: str) -> str:
    return '"' + str(text).replace('"', "'") + '"'


def said_answer(row: dict) -> str:
    """The event line: what was answered, how, and a card it filed."""
    if row["state"] == "redirected":
        head = f"redirected {who(row)}: {quoted(row['words'])}"
    else:
        head = f"answered {who(row)}: {row['answer']}, {pick(row, row['answer'])['label']}"
        head += f" (the user's words: {quoted(row['words'])})" if row.get("words") else ""
    return head + (f"; filed {row['filed_as']}" if row.get("filed_as") else "")


def told_one(row: dict) -> str:
    """What Bosun is told about one answer, from the row alone."""
    if row["state"] == "redirected":
        return (f"The user redirected {row['id']} ({row['question']}) {who(row)}: none of its options "
                f"is to be done. The user's words: {quoted(row['words'])}. Work out what they change, "
                f"and raise a new ask if you need one." + again(row))
    option = pick(row, row["answer"])
    out = (f"The user answered {row['id']} ({row['question']}) {who(row)}: {option['letter']}, "
           f"{option['label']}. What {option['letter']} does, and all you do for it: "
           f"{option['does'].rstrip('.')}.")
    if row.get("filed_as"):
        out += f" The answer filed {row['filed_as']}, a personal card."
    if row.get("words"):
        out += f" The user's words beside it: {quoted(row['words'])}."
    return out + again(row)


def again(row: dict) -> str:
    return (" (Told again: an earlier telling was never confirmed, so it may have reached "
            "you already. Do not do it twice.)" if row.get("again") else "")


def told(rows: list[dict]) -> str:
    """The wake's prompt and the hook's lines: the same words for the same answers."""
    if not rows:
        return ""
    lines = [told_one(row) for row in rows]
    return "\n".join(["Answers to your asks, recorded on the board:", *lines,
                      "For an answer, do only what the option the user picked lists; for a redirect, "
                      "none of its options."])


def where(option: dict) -> str:
    """Where the card an option files builds, as every surface says it (c-550)."""
    files = option.get("files") or {}
    if "repo" not in files:
        return "repo from its card"
    if not files["repo"]:
        return "as an errand, no repo"
    came = files.get("repo_from")
    return f"in {files['repo']}" + (f" (from {came})" if came and came != "stated" else "")


def where_marked(option: dict) -> str:
    """`where`, the kind the filed card is marked with (c-553) and its autonomy (c-584):
    "in keel, marked research, attended"."""
    files = option.get("files") or {}
    kind, autonomy = files.get("kind"), files.get("autonomy")
    return where(option) + (f", marked {kind}" if kind else "") + (f", {autonomy}" if autonomy else "")


def row_line(row: dict, now: str | None = None) -> str:
    card = f" about {row['card']}" if row.get("card") else ""
    head = f"{row['id']} [{row['kind']}, {row['state']}]{card}: {row['question']}"
    filing = next((o for o in row.get("options") or [] if o.get("files")), None)
    if filing and row["state"] == "open":
        head += f" ({filing['letter']} files a personal card {where_marked(filing)})"
    if row["state"] in ("answered", "redirected"):
        head += f" ({said_answer(row)})"
    return head


def hook_lines(rows: list[dict]) -> str:
    """The open asks, for the top of his message: so Bosun knows what is waiting on him."""
    if not rows:
        return ""
    return "\n".join(["Your open asks, waiting on the user:",
                      *(f"- {row['id']} ({row['kind']}): {quoted(row['question'])}" for row in rows)])


def show_text(row: dict, events: list[dict]) -> str:
    lines = [row_line(row), f"Why: {row['why']}"]
    for option in row["options"]:
        mark = " (recommended)" if option["letter"] == "A" else ""
        files = f" [files, {where_marked(option)}: {option['files']['title']}]" if option.get("files") else ""
        lines.append(f"  {option['letter']}. {option['label']}{mark}: {option['does']}{files}")
    if row.get("message"):
        lines.append(f"The user's message: {quoted(row['message'])}")
    lines += [f"  {e['at']}  {e['actor']:<7} {e['text'] or ''}" for e in events]
    return "\n".join(lines)


def said_raise(row: dict) -> str:
    return (f"raised {row['id']}: it waits in the user's Needs you; do nothing it lists until the user's "
            f"answer arrives")


def said_recorded(row: dict) -> str:
    """What `answer` prints: for Bosun's chat record, the one line it says before acting."""
    head = f"recorded {row['id']} {said_answer(row)}"
    if row.get("channel") == "chat":
        return head + "\n" + row["told"]
    return head + "; Bosun is told on the drain's next pass, or atop the user's next message"


# ----- the `kb console` sub-verbs -----

SUBS = ("raise", "asks", "answer", "withdraw", "pending", "claim", "confirm", "unclaim")
# Who tells Bosun: the drain's wake, and Bosun's own hook confirming what it printed (the hook
# claims inside `kb console hook`, and only as `bosun`: `requests.hook`).
DELIVERERS = {"claim": ("drain",), "unclaim": ("drain",), "confirm": ("drain", "bosun")}
VIAS = ("wake", "hook")
USAGE = ('raise "<question>" --kind approval|decision|escalation --why <text> --option "label|does" '
         '... [--card <id>] [--file "letter|title|brief|autonomy" --file-repo <key>|none [--file-kind research]] | asks [--all] | show a-N | '
         'answer a-N [<letter>|--pick <letter>] [--words <text>] [--by chat --message <their message>] | '
         'withdraw a-N --why <text> | pending | claim --ids <a-N,...> --via wake|hook | '
         'confirm --ids <a-N,...> --via wake|hook | unclaim --ids <a-N,...>')
ARGUMENTS = ((("choice",), {"nargs": "?", "metavar": "letter",
                            "help": "answer: the option's letter"}),
             (("--pick",), {"metavar": "letter", "help": "answer: the same as the letter"}),
             (("--kind",), {"choices": KINDS}),
             (("--why",), {"metavar": "text", "help": "raise: why it is asked; withdraw: why "
                                                     "it no longer stands; resume, retry: "
                                                     "what broke (a repair)"}),
             (("--option",), {"action": "append", "metavar": "label|does",
                              "help": "raise: 2 to 4, Bosun's recommendation first"}),
             (("--file",), {"metavar": "letter|title|brief|autonomy",
                            "help": "raise, an escalation: the personal card that option files, "
                                    "and its autonomy (attended or autonomous)"}),
             (("--file-repo",), {"metavar": "key|none",
                                 "help": "raise, an escalation: the repo that card builds in "
                                         "(kb repos --space personal), or none for an errand; "
                                         "without it, the --card's"}),
             (("--file-kind",), {"choices": FILE_KINDS,
                                 "help": "raise, an escalation: the kind that card is marked "
                                         "(research closes on Approve outcome with nothing landed)"}),
             (("--words",), {"metavar": "text", "help": "answer: the user's words beside the option, "
                                                       "or alone to redirect"}),
             (("--by",), {"choices": tuple(CHANNELS.values()),
                          "help": "answer: chat, when Bosun records the user's chat answer"}),
             (("--message",), {"metavar": "text", "help": "answer --by chat: the user's exact message"}),
             (("--ids",), {"metavar": "a-N,...", "help": "claim, unclaim: the answers"}),
             (("--via",), {"choices": VIAS, "help": "claim: how Bosun is told"}))
# The fields the wire carries for these sub-verbs (`requests.argv`, `remote.BODIES`).
WIRE = ("kind", "why", "file", "file_repo", "file_kind", "words", "by", "message", "pick", "choice", "ids", "via")


def command(board: Board, args, actor: str, target, check_repo=None) -> dict:
    sub = args.sub
    if sub == "raise":
        if not args.kind:
            raise Refused("raise needs --kind: approval, decision or escalation")
        return raise_ask(board, actor, args.kind, target('"<question>"'), args.why or "",
                         args.option or [], card=args.card, files=args.file,
                         file_repo=getattr(args, "file_repo", None), check_repo=check_repo,
                         file_kind=getattr(args, "file_kind", None))
    if sub == "asks":
        return {"asks": listing(board, args.all)}
    if sub == "answer":
        return answer(board, target("a-N"), actor, args.choice or args.pick, args.words or "",
                      by=args.by, message=args.message or "")
    if sub == "withdraw":
        return withdraw(board, target("a-N"), actor, args.why or "")
    if sub == "pending":
        return {"asks": undelivered(board)}
    if actor not in DELIVERERS[sub]:
        raise Refused(f"{sub} is for what tells Bosun the user's answers ({', '.join(DELIVERERS[sub])}); "
                      f"not {actor}'s")
    ids = [aid.strip() for aid in str(args.ids or "").split(",") if aid.strip()]
    via = args.via or "wake"
    if sub == "claim":
        return {"asks": claim(board, ids, via)}
    if sub == "confirm":
        return {"asks": confirm(board, ids, via)}
    unclaim(board, ids, via)
    return {"asks": []}


def render(args, payload) -> str:
    sub = args.sub
    if sub == "raise":
        return said_raise(payload)
    if sub == "asks":
        return "\n".join(row_line(row) for row in payload["asks"]) or "no open asks"
    if sub == "answer":
        return said_recorded(payload)
    if sub == "withdraw":
        return f"withdrew {payload['id']}"
    return "\n".join(row_line(row) for row in payload["asks"]) or "none"


# ----- on whichever board the caller holds -----

def call(board, actor: str, sub: str, **fields):
    """A sub-verb on the board."""
    if sub == "pending":
        return undelivered(board)
    if sub == "claim":
        return claim(board, fields["ids"], fields["via"])
    if sub == "confirm":
        return confirm(board, fields["ids"], fields["via"])
    unclaim(board, fields["ids"], fields.get("via", "wake"))
    return []
