"""His answers and notes on a plan: stored on the card as events, composed into the resume.

ONE STORE. Every tap he makes on a plan page (an option picked, a batch row flipped, a reply
to an open question, a note pinned to a block or to a piece of selected text) is a `mark`
event on the card, written through `kb mark` by the deck with his token. Nothing lives in a
tool's state file, nothing is polled, and the deck's event stream already says `card <id>`
when one lands, so a second screen shows it at once.

A ROUND is everything since the last `sent` mark for that document. `plan.send` composes
the round into ONE text, and the existing gate verbs carry it: Approve quotes it as his
words (`kb approve --said`), Send back uses it as the reason. The composition keeps the
ANCHOR (the block, the text he selected) apart from HIS WORDS, typed differently, because
c-175 relayed the selection in place of what he said.

Every decision is listed, his picks and the recommendations he left standing alike, and
the two are marked apart: "Approve means my recommendation stands" is the contract, and the
house has to be able to tell which answers were his.
"""

from __future__ import annotations

import json

from keel.planinline import plain

WHATS = ("answer", "comment", "drop", "sent", "ask")
# `shipping` (c-600): his post, edit or drop on a shipping card's standing batch of replies
DOCS = ("plan", "outcome", "shipping")
MODES = ("approve", "sendback")
MAX_TEXT = 4000
MAX_QUOTE = 500
MAX_ID = 96
# A batch row's choice that carries his own words (RC-3): a reply or a review comment he
# rewrote. The words are the mark's `other`, and Approve uses them.
EDIT = "edit"


def short(value, cap: int, what: str) -> str:
    text = str(value or "").strip()
    if len(text) > cap:
        raise ValueError(f"{what} is longer than {cap} characters")
    return text


def check_mark(data) -> dict:
    """The one shape a mark may have; a ValueError says what is wrong with it."""
    if not isinstance(data, dict):
        raise ValueError("a mark is an object")
    what = data.get("what")
    if what not in WHATS:
        raise ValueError(f"a mark is one of {', '.join(WHATS)}")
    doc = data.get("doc") or "plan"
    if doc not in DOCS:
        raise ValueError(f"a mark is on the plan, the outcome or the shipping replies, not {doc!r}")
    out = {"what": what, "doc": doc}
    if what == "drop":
        target = data.get("target")
        if not isinstance(target, int) or target < 1:
            raise ValueError("a drop names the event id of the note it takes back")
        out["target"] = target
        return out
    if what == "sent":
        mode = data.get("mode")
        if mode not in MODES:
            raise ValueError(f"a send is one of {', '.join(MODES)}")
        out.update(mode=mode, decisions=[short(d, MAX_ID, "a decision id") for d in data.get("decisions") or []])
        return out
    block = short(data.get("block"), MAX_ID, "a block id")
    if what == "answer":
        if not block:
            raise ValueError("an answer names its block")
        out["block"] = block
        for key in ("option", "row", "choice"):
            if data.get(key) not in (None, ""):
                out[key] = short(data[key], MAX_ID, key)
        if data.get("item") is not None:
            out["item"] = int(data["item"])
        if data.get("other") not in (None, ""):
            out["other"] = short(data["other"], MAX_TEXT, "the user's words")
        return out
    text = short(data.get("text"), MAX_TEXT, "a note" if what == "comment" else "a question")
    if not text:
        raise ValueError("a note says something" if what == "comment" else "a question asks something")
    out.update(block=block or None, text=text, quote=short(data.get("quote"), MAX_QUOTE, "the quote") or None)
    return out


def marks_of(events: list[dict], doc: str = "plan") -> list[dict]:
    """His marks on that document, oldest first, each with its event id and time."""
    out = []
    for event in events:
        if event.get("kind") != "mark" or event.get("actor") != "human":
            continue
        data = event.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict) or data.get("doc", "plan") != doc:
            continue
        out.append(dict(data, event=event.get("id"), at=event.get("at")))
    return out


def state_of(events: list[dict], doc: str = "plan") -> dict:
    """The round in progress, and what earlier rounds sent."""
    marks = marks_of(events, doc)
    last_sent = max((i for i, m in enumerate(marks) if m["what"] == "sent"), default=-1)
    state = {"answers": {}, "rows": {}, "edits": {}, "replies": {}, "comments": [], "sent": [],
             "answered": set(), "asks": asks_of(events, doc, marks[last_sent + 1:])}
    for mark in marks[:last_sent + 1]:
        if mark["what"] == "sent":
            state["sent"].append({"at": mark["at"], "mode": mark["mode"], "decisions": mark["decisions"]})
            if mark["mode"] == "sendback":
                state["answered"].update(mark["decisions"])
    dropped = {m["target"] for m in marks[last_sent + 1:] if m["what"] == "drop"}
    for mark in marks[last_sent + 1:]:
        fold(state, mark, dropped)
    state["answered"] = sorted(state["answered"])
    return state


# ----- Ask (P2-9): a question he wants cleared without sending the plan back -----

def replies_of(events: list[dict]) -> dict:
    """The house's answers (`kb reply`), keyed by the event id of the question each answers."""
    out = {}
    for event in events:
        if event.get("kind") != "reply":
            continue
        data = event.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict) and isinstance(data.get("ask"), int):
            out.setdefault(data["ask"], {"event": event.get("id"), "at": event.get("at"),
                                         "text": data.get("text") or event.get("text") or ""})
    return out


def asks_of(events: list[dict], doc: str = "plan", marks: list[dict] | None = None) -> list[dict]:
    """His questions this round, oldest first, each with the house's reply or None. An ask
    is not part of what Send composes: it has had its answer already."""
    replies = replies_of(events)
    marks = marks_of(events, doc) if marks is None else marks
    return [dict({k: m.get(k) for k in ("event", "at", "block", "quote", "text")},
                 reply=replies.get(m["event"]))
            for m in marks if m["what"] == "ask"]


def open_asks(events: list[dict], doc: str = "plan") -> list[dict]:
    """The questions still waiting on the house, in the order he asked them."""
    return [a for a in asks_of(events, doc) if a["reply"] is None]


def fold(state: dict, mark: dict, dropped: set) -> None:
    if mark["what"] == "comment" and mark["event"] not in dropped:
        state["comments"].append({k: mark.get(k) for k in ("event", "at", "block", "quote", "text")})
    elif mark["what"] == "answer" and "row" in mark:
        state["rows"].setdefault(mark["block"], {})[mark["row"]] = mark.get("choice")
        if mark.get("choice") == EDIT and mark.get("other"):
            # RC-3: his words for a row he chose to edit ride in the same mark, and the
            # newest wins; Approve sends them in place of the house's draft.
            state["edits"].setdefault(mark["block"], {})[mark["row"]] = mark["other"]
    elif mark["what"] == "answer" and "item" in mark:
        state["replies"].setdefault(mark["block"], {})[str(mark["item"])] = mark.get("other") or ""
    elif mark["what"] == "answer":
        if mark.get("option") or mark.get("other"):
            state["answers"][mark["block"]] = {"option": mark.get("option"), "other": mark.get("other")}
        else:
            state["answers"].pop(mark["block"], None)      # back to the recommendation


# ----- the composition -----

def label_of(block: dict, option_id: str | None) -> str:
    for option in block.get("options", []):
        if option["id"] == option_id:
            return f"{option_id} ({plain(option['label'])})"
    return str(option_id)


def decision_lines(block: dict, state: dict) -> list[str]:
    ask = plain(block.get("q", [])) or block["id"]
    rec = block.get("rec")
    picked = state["answers"].get(block["id"])
    if not picked:
        return [f"- {block['id']}: {ask} -> {label_of(block, rec)}, your recommendation, left standing."]
    option, other = picked.get("option"), picked.get("other")
    if option == rec and not other:
        return [f"- {block['id']}: {ask} -> {label_of(block, rec)}, your recommendation, which the user confirmed."]
    head = f"- {block['id']}: {ask} -> "
    head += (f"THE USER CHOSE {label_of(block, option)}" if option else "THE USER CHOSE something else")
    head += f" (you recommended {label_of(block, rec)})." if option != rec else "."
    lines = [head]
    if other:
        lines.append(f"  The user's words: {quote(other)}")
    return lines


def batch_lines(block: dict, state: dict) -> list[str]:
    picks = state["rows"].get(block["id"], {})
    changed = [(r, picks[r["id"]]) for r in block.get("rows", [])
               if picks.get(r["id"]) and picks[r["id"]] != r.get("rec")]
    head = f"- {block['id']}: {plain(block.get('q', [])) or 'each row'} -> "
    if not changed:
        return [head + f"every row takes your recommendation ({len(block.get('rows', []))} rows)."]
    lines = [head + f"your recommendation on every row except {len(changed)}:"]
    edits = state.get("edits", {}).get(block["id"], {})
    for row, choice in changed:
        lines.append(f"  - {row['id']} ({plain(row['text'])[:80]}): THE USER CHOSE {choice}, you recommended {row.get('rec')}.")
        if choice == EDIT and edits.get(row["id"]):
            lines.append(f"    The user's words: {quote(edits[row['id']])}")
    return lines


def finding_lines(block: dict, state: dict) -> list[str]:
    """A review finding (lane FC): his pick is a row mark on the block itself."""
    choice = state["rows"].get(block["id"], {}).get(block["id"])
    claim = plain(block.get("claim") or [])[:80]
    if not choice or choice == block.get("rec"):
        return [f"- {block['id']} ({claim}): {block.get('rec')}, your recommendation, left standing."]
    lines = [f"- {block['id']} ({claim}): THE USER CHOSE {choice}, you recommended {block.get('rec')}."]
    words = state.get("edits", {}).get(block["id"], {}).get(block["id"])
    if choice == EDIT and words:
        lines.append(f"  The user's words: {quote(words)}")
    return lines


def question_lines(block: dict, state: dict) -> list[str]:
    replies = state["replies"].get(block["id"], {})
    lines = []
    for index, item in enumerate(block.get("items", [])):
        said = replies.get(str(index))
        ask = item.get("q_text") or plain(item.get("q", []))
        if said:
            lines.append(f"- Open question {quote(ask[:120])}: the user's answer {quote(said)}")
        elif item.get("rec"):
            lines.append(f"- Open question {quote(ask[:120])}: your recommendation stands ({plain(item['rec'])[:120]}).")
        else:
            lines.append(f"- Open question {quote(ask[:120])}: the user did not answer and you gave no recommendation.")
    return lines


def quote(text: str) -> str:
    return '"' + " ".join(str(text).split()).replace('"', "'") + '"'


def comment_lines(doc: dict, state: dict) -> list[str]:
    names = {b["id"]: where_of(doc, b) for b in doc_blocks(doc)}
    lines = []
    for n, note in enumerate(state["comments"], start=1):
        place = names.get(note.get("block"), "the page as a whole") if note.get("block") else "the page as a whole"
        lines.append(f"{n}. On {place}" + (f", at the words {quote(note['quote'])}" if note.get("quote") else "") + ":")
        lines.append(f"   The user wrote: {quote(note['text'])}")
    return lines


def doc_blocks(doc: dict):
    stack = list(doc.get("blocks", []))
    while stack:
        block = stack.pop(0)
        yield block
        stack[0:0] = block.get("blocks", []) or []


def where_of(doc: dict, block: dict) -> str:
    section = next((s for s in doc.get("sections", []) if s["id"] == block.get("section")), None)
    head = f"`{block['id']}`"
    return head + (f" under {quote(section['text'])}" if section else "")


def compose(doc: dict, state: dict, mode: str, card_id: str, doc_name: str = "plan") -> str:
    """The one text a send carries: his answers, then his notes, anchors apart from words.
    `doc_name` says which page it came from: an outcome sent back is not a plan (c-600)."""
    blocks = list(doc_blocks(doc))
    answers = []
    for block in blocks:
        if block["type"] == "decision":
            answers += decision_lines(block, state)
        elif block["type"] == "batch":
            answers += batch_lines(block, state)
        elif block["type"] == "finding":
            answers += finding_lines(block, state)
        elif block["type"] == "questions":
            answers += question_lines(block, state)
    notes = comment_lines(doc, state)
    page = "outcome" if doc_name == "outcome" else "plan"
    verb = f"approved the {page}" if mode == "approve" else f"sent the {page} back"
    out = [f"The user {verb} from the {page} page of {card_id}."]
    if answers:
        out += ["", "The user's answers, one per decision (a recommendation left standing is marked so):", *answers]
    if notes:
        out += ["", f"The user's notes ({len(notes) // 2}), each pinned to where it was left. The quote is the "
                    "text the user selected; the user's words are what they want done:", *notes]
    if not answers and not notes:
        out.append("The user left no answers or notes beyond the tap.")
    return "\n".join(out)


def decision_ids(doc: dict) -> list[str]:
    return [b["id"] for b in doc_blocks(doc) if b["type"] in ("decision", "batch", "finding")]


def summary(doc: dict, state: dict) -> dict:
    """What the deck says about the round: counts the page and the card row both read."""
    blocks = list(doc_blocks(doc))
    decisions = [b for b in blocks if b["type"] == "decision"]
    changed = sum(1 for b in decisions if (state["answers"].get(b["id"]) or {}).get("option") not in (None, b.get("rec"))
                  or (state["answers"].get(b["id"]) or {}).get("other"))
    changed += sum(1 for b in blocks if b["type"] == "batch"
                   for r in b.get("rows", []) if state["rows"].get(b["id"], {}).get(r["id"]) not in (None, r.get("rec")))
    found = [b for b in blocks if b["type"] == "finding"]
    changed += sum(1 for b in found if state["rows"].get(b["id"], {}).get(b["id"]) not in (None, b.get("rec")))
    return {"decisions": len(decisions) + len(found) + sum(len(b.get("rows", [])) for b in blocks if b["type"] == "batch"),
            "changed": changed, "notes": len(state["comments"]),
            "replies": sum(len(v) for v in state["replies"].values())}


def has_words(state: dict) -> bool:
    """Did he say anything a send back could carry: a note, a changed answer, a changed row,
    or a reply to an open question (c-600: an empty send back from the page went out with
    no reason at all)."""
    return bool(state["comments"] or state["answers"] or state["rows"] or state["edits"]
                or any(state["replies"].values()))
