"""The plan page's server half: `GET /api/plan/<c-id>[?doc=plan|outcome]`.

One answer carries everything the page draws, so the page makes one request: the parsed
document (`keel/planformat.py`), the lint's findings (`keel/planlint.py`), his answers and
notes so far this round (`keel/planstate.py`), each embedded board's lines, and a token
for every picture and file the document names. Nothing in it is HTML: the page builds
every node with `textContent`, exactly as the board does, so a plan a house wrote after
reading a hostile page runs nothing in the origin the approve verbs live in.

`/plan/<c-id>` and `/outcome/<c-id>` are a page of their own (`app/plan.html`), not the
deck's shell: a document to read and answer, with a slim header and nothing of the deck's
navigation. It carries the page's cookie exactly as the deck's shell does.

Measured and returned with every answer: how long the parse and the lint took, and the
size of the source, so the page can say what it cost.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path

from keel import (actions, artifacts, boards, boardtrash, cardfiles, ciroute, commentsroute, deckstate, dropin, livestrip,
                  planexcerpt, planfacts, planformat, plangate, planlint, planoutcome, planstate, receipt, terms)
from keel.review import gate as review_gate

PLAN_API = re.compile(r"^/api/plan/(c-\d+)$")
# A page of its own per document (P2-5): `/plan/<c-id>` and `/outcome/<c-id>`, served from
# `app/plan.html`, which is not the deck's shell (no rail, no header, no dock). `/ci/<c-id>`
# (c-642, `keel/ciroute.py`) and `/comments/<c-id>` (c-643, `keel/commentsroute.py`) are drawn
# on the same shell, so the four switch to each other. `/files/<c-id>` lists the markdown files
# the card wrote, and `/file/<c-id>/<name>` reads one (c-719, `keel/cardfiles.py`).
PLAN_PAGE = re.compile(r"^/(plan|outcome|context|files|ci|comments)/(c-\d+)/?$")
FILE_PAGE = re.compile(r"^/file/(c-\d+)/(.+)$")
# The card's pages in the viewer's tab order (c-644, `K.docTabs` draws the same order)
PAGES = ("plan", "outcome", "context", "files", "comments", "ci")
# The pages drawn as plain reading: no gate, no receipt, no contract (c-644, c-719)
READ_ONLY = ("context", "file", "files")
DOCS = ("plan", "outcome")
# An outcome at these stages was written already: read as it was accepted (lane FC's old
# review shape is a warning there, never a break).
WRITTEN = ("review", "shipping", "done")


def source(cfg, card: dict, doc: str, name: str | None = None) -> tuple[str, str, Path | None, str | None]:
    """(text, file name, the directory relative paths resolve in, why it is empty). A card
    file (`doc` "file", c-719) is read only from inside the card's folder: `cardfiles.resolve`
    raises `FileRefused` for anything else."""
    if doc == "file":
        path = cardfiles.resolve(cfg, card, name or "")
        return path.read_text(errors="replace"), path.name, path.parent, None
    if doc == "files":
        return "", "", cfg.card_dir(card["id"]), None
    if doc == "outcome":
        context = cfg.card_dir(card["id"]) / "context.md"
        text = context.read_text(errors="replace") if context.is_file() else ""
        return text, "context.md", cfg.card_dir(card["id"]), None if text else "this card has no record yet"
    ref = card.get("plan_ref") or ""
    if not ref or ref.startswith("http"):
        return "", "plan.md", None, "this card has no plan file"
    path = artifacts.local_path(ref, cfg.root)
    if artifacts.kind(path) != "markdown":
        return "", path.name, path.parent, "the plan is not markdown (a lavish page); open it full screen"
    if not path.is_file():
        return "", path.name, path.parent, "no plan file at " + ref
    return path.read_text(errors="replace"), path.name, path.parent, None


def plan_stamp(cfg, card: dict | None) -> str:
    """The plan file's own change stamp: a house rewriting its plan moves no board event."""
    if not card or not card.get("plan_ref") or str(card["plan_ref"]).startswith("http"):
        return "0"
    return str(deckstate.mtime_ns(artifacts.local_path(card["plan_ref"], cfg.root)))


def resolver(cfg, card: dict):
    """C7 against the card's worktree, and each other repo's for a cross-repo card (SH-12)."""
    if not card.get("repo"):
        return None
    return planlint.card_resolver(card, dropin.cwd_of(cfg, card))


def local_paths(doc: dict) -> list[str]:
    """Every picture, compare image and relative link the document names, once each: what
    a machine that has the document's directory turns into artifact URLs."""
    found = []
    for block in planformat.all_blocks(doc["blocks"]):
        if block["type"] == "images":
            found += [item["path"] for item in block["items"]]
        elif block["type"] == "compare":
            found += [p for row in block["rows"] if row.get("image") for p in (row["left"], row["right"])]
    found += [link.get("href") or "" for link in links_in(doc["blocks"])
              if not re.match(r"^https?://", link.get("href") or "")]
    return list(dict.fromkeys(p for p in found if p))


def decorate(cfg, doc: dict, base: Path | None, approved: str | None = None, card: dict | None = None) -> None:
    """Tokens for pictures and relative links, lines for embedded boards.

    `approved` is when his plan was approved (c-604 review). A PLAN's embed is pinned to the
    board as it stood then (`boards.lines_at`, and `upto` for its links), so a redraw at the
    built head never changes what he approved; an OUTCOME's shows the board now, and a board
    redrawn since carries `planned_upto`, the plan's picture to compare with. A relative link
    to a markdown file in `card`'s folder opens it in the viewer (c-719), not as an artifact."""
    def target(raw):
        return artifacts.target(cfg, base, raw)
    for block in planformat.all_blocks(doc["blocks"]):
        if block["type"] == "images":
            for item in block["items"]:
                item["src"], item["why"] = target(item["path"])
        elif block["type"] == "board":
            try:
                record = boards.read_record(cfg, block["ref"])
                block["ops"] = boards.ops_lines(cfg, block["ref"])
                pin_board(block, doc["kind"], approved)
                block["board_title"] = record.get("title") or block["ref"]
            except boards.BoardError as error:
                # A BOARD HE DELETED IS A PLACEHOLDER, not an error (BD-2): the embed says
                # so and offers him Restore; an id that never existed is still missing.
                deleted = boardtrash.deleted_block(cfg, block["ref"])
                if deleted is not None:
                    block["deleted"] = deleted
                else:
                    block["missing"] = str(error)
        elif block["type"] == "compare":
            for row in block["rows"]:
                if row.get("image"):
                    row["left_src"], _ = target(row["left"])
                    row["right_src"], _ = target(row["right"])
    for link in links_in(doc["blocks"]):
        href = link.get("href") or ""
        if not re.match(r"^https?://", href):
            page = cardfiles.link_page(cfg, card, base, href) if card else None
            link["href"], link["why"] = (page, "") if page else target(href)


def pin_board(block: dict, kind: str, approved: str | None) -> None:
    lines = block["ops"]
    upto = boards.lines_at(lines, approved) if approved else len(lines)
    if not 0 < upto < len(lines):
        return
    if kind == "plan":
        block["ops"], block["upto"] = lines[:upto], upto
    elif any(line.startswith(boards.REDRAW_MARK) for line in lines[upto:]):
        block["planned_upto"] = upto


def links_in(value):
    """Every link span anywhere in the document, nested blocks included, once each."""
    if isinstance(value, dict):
        if value.get("t") == "link":
            yield value
        for inner in value.values():
            yield from links_in(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from links_in(inner)


def read(cfg, card: dict, doc_name: str, file: str | None = None) -> dict:
    """The document and what the lint needs about where it lives."""
    text, name, base, why = source(cfg, card, doc_name, file)
    return {"text": text, "name": name, "base": base, "why": why, "resolve": resolver(cfg, card),
            "docs": format_docs(cfg, card)}


def format_docs(cfg, card: dict) -> list[str]:
    """Which of the card's documents the page links to each other: the plan and the outcome
    in the plan format (P4-2), and `context` for a `context.md` that is not (c-644: drawn
    as plain markdown on the same shell, so it switches to the others too)."""
    out = []
    for doc in DOCS:
        path = outcome_path(cfg, card) if doc == "outcome" else local_plan(cfg, card)
        if path is not None and planfacts.is_format(path):
            out.append(doc)
        elif doc == "outcome" and path is not None and path.is_file():
            out.append("context")
    return out


def outcome_path(cfg, card: dict) -> Path | None:
    path = cfg.cards_dir / card["id"] / "context.md"
    return path if path.is_file() else None


def local_plan(cfg, card: dict) -> Path | None:
    ref = str(card.get("plan_ref") or "")
    if not ref or ref.startswith("http"):
        return None
    path = artifacts.local_path(ref, cfg.root)
    return path if artifacts.kind(path) == "markdown" else None


def payload(cfg, board, card_id: str, doc_name: str, strip=None, file: str | None = None,
            files: list | None = None) -> dict:
    """The plan page's answer for `plan`, `outcome`, or `context`: a `context.md` that is not
    in the plan format, read as the outcome is and drawn as plain markdown, with no gate
    (c-644). `file` is one markdown file the card wrote (`file`, c-719), read the same way:
    the same parse and blocks, no gate; `files` is their list alone."""
    card = board.get(card_id)
    events = board.events(card_id)
    shown = doc_name
    plain = doc_name in READ_ONLY
    context = doc_name == "context"
    if context:
        doc_name = "outcome"
    got = read(cfg, card, doc_name, file)
    text, name, base, why = got["text"], got["name"], got["base"], got["why"]
    if context and planfacts_format(text):
        # a record in the plan format is the Outcome page, never the plain one (r1.F1): the
        # deck cannot always tell (`links.formats` is read at the live stages only), so the
        # page asks and is sent on
        return {"redirect": "outcome", "card": {"id": card_id}}
    if context and why:
        why = why.replace("outcome", "record")
    started = time.perf_counter()
    words = terms.of(cfg, card.get("space"))
    doc = planformat.parse(text, name, terms.refs(words))     # the card's own refs (c-630)
    # c-719 r1.F1: the record is held to the card's contract, whatever kind it says
    mismatch = (planlint.follow_card(doc, card, name, planlint.RECORD) if doc_name == "outcome"
                else planlint.follow_card(doc, card, name, planlint.PLAN) if doc_name == "plan" else [])
    parsed = time.perf_counter()
    state = planstate.state_of(events, doc_name)
    board_of = plangate.board_resolver(cfg)
    since = planoutcome.approved_at(events)
    result = planlint.lint(doc, repo_card=bool(card.get("repo")), resolve=got["resolve"],
                           answered=state["answered"] if doc_name == "plan" else (),
                           board_of=board_of, card_id=card_id,
                           ships=review_gate.started_with_pipeline(card),
                           legacy=doc_name == "outcome" and card.get("stage") in WRITTEN,
                           since=since, written=planoutcome.written(card))
    result = planlint.with_findings(result, mismatch)
    if plain:
        # a plain record or a card file is read, not held to the outcome's contract (r1.F5)
        result = dict(result, ok=True, findings=[])
    linted = time.perf_counter()
    decorate(cfg, doc, base, since, card)
    if doc["kind"] == "outcome":
        # c-602: a board the outcome carried over from the plan unchanged says so in its head
        planoutcome.mark_carried(doc, board_of, since)
    # FC-2: each finding's lines, read from the worktree now
    excerpts = planexcerpt.card_excerpts(cfg, card, doc)
    planexcerpt.attach(doc, excerpts)
    state["answered"] = list(state["answered"])
    # c-537: once the gate is answered the page draws this in place of its buttons
    answer = None if shown in ("file", "files") else receipt.receipt(cfg, card, events, doc_name)
    # c-551 and c-565: the adapter's links, read once, for the outcome page's line and its PRs
    links = (deckstate.adapter_links_of(cfg, card)
             if doc_name == "outcome" and not plain and card.get("stage") in deckstate.OUTCOME_STAGES else {})
    files = cardfiles.listed(cfg, card) if files is None else files
    return {"card": dict({k: card.get(k) for k in ("id", "title", "space", "stage", "repo", "autonomy",
                                                   "plan_ref", "session_id")}, prs=prs_of(card),
                         # c-719: the card's kind, so the page knows research on either side
                         kind=(card.get("options") or {}).get("kind"),
                         terms=terms.public(words),
                         unpublished=deckstate.unpublished_of(cfg, card, links) if doc_name == "outcome" else None,
                         pulls=deckstate.pulls_of(links)),
            "gate": None if plain else actions.gate_of(card), "doc_name": shown,
            "receipt": None if plain else answer,
            "answerable": False if plain else receipt.answerable(card, answer, doc_name), "doc": doc,
            "moves": moves_of(cfg, card),
            "lint": result, "state": state, "round": planstate.summary(doc, state),
            "docs": in_order(list(got["docs"]) + more_pages(cfg, card, files)),
            "files": files, "file": file if shown == "file" else None,
            "empty": why if not text and shown != "files" else None,
            # c-599: what the house is doing now, as the deck's live strip holds it (the
            # stream's `live` lines move it after this), and the newest Notification of its turn
            "live": strip.of_session(card) if strip is not None else None,
            "notice": livestrip.notice(card, events) if card.get("session_id") else None,
            "cost": {"bytes": len(text.encode()), "parse_ms": round((parsed - started) * 1000, 3),
                     "lint_ms": round((linted - parsed) * 1000, 3)}}


def planfacts_format(text: str) -> bool:
    """The text opens with frontmatter, the plan format's mark (`planfacts.is_format` reads a
    file's first bytes the same way)."""
    return text.startswith("---")


def flow_stamp(cfg, card: dict) -> str:
    """The space's flow files' change stamps: the moves in the answer come from them, and an
    edited flow moves neither the card nor the plan (r1.F4)."""
    from keel import flows      # noqa: PLC0415 - as moves_of
    space = cfg.spaces.get(card.get("space") or "")
    if space is None:
        return ""
    out = []
    for path in (flows.space_file(cfg, space.name), flows.pack_file(space)):
        try:
            out.append(str(path.stat().st_mtime_ns) if path is not None else "-")
        except OSError:
            out.append("-")
    return ".".join(out)


def moves_of(cfg, card: dict) -> list[dict]:
    """The flow's moves he may make on this card now, for the viewer's header (c-644): the
    pane's (`K.flowMoves`), each with the group its flow names. A card with no session has
    no house to tell, so none."""
    from keel import flows      # noqa: PLC0415 - flows reads config this module also imports
    space = cfg.spaces.get(card.get("space") or "")
    if space is None or not card.get("session_id"):
        return []
    return [{"id": one.id, "label": one.label, "group": one.group or "Flow", "about": one.about}
            for one in flows.offered(flows.of(cfg, space), card, cfg)]


def in_order(docs: list[str]) -> list[str]:
    """The card's pages in the tabs' order (`PAGES`, which `TAB_ORDER` in app/ui.plan.js
    repeats; tests/test_viewer.py holds them equal)."""
    return [doc for doc in PAGES if doc in docs]


def more_pages(cfg, card: dict, files: list | None = None) -> list[str]:
    """The card's pages beyond its plan and outcome: its CI page where its space reads
    builds (c-642), its review comments page once it has any (c-643), its Files once it
    wrote a markdown file beyond them (c-719). `in_order` sorts them."""
    files = cardfiles.listed(cfg, card) if files is None else files
    return ((["ci"] if ciroute.offered(cfg, card) else []) + (["comments"] if commentsroute.offered(card) else [])
            + (["files"] if files else []))


def prs_of(card: dict) -> dict:
    """The pull requests a review card's findings link to (lane FC): `pr`, the card's own,
    and each feature member's by its label."""
    options = card.get("options") or {}
    out = {"pr": (options.get("review_pr") or {}).get("url")} if (options.get("review_pr") or {}).get("url") else {}
    out.update({m["label"]: m.get("url") for m in options.get("review_members") or [] if m.get("label") and m.get("url")})
    return out


class PlanRoute:
    """Mixed into the deck's request handler, the way the voice tier is."""

    def get_plan(self, card_id: str) -> None:
        asked = urllib.parse.parse_qs(self.query())
        doc = (asked.get("doc") or ["plan"])[0]
        doc = doc if doc in ("outcome", "context", "file", "files") else "plan"
        file = (asked.get("name") or [""])[0] if doc == "file" else None
        board = self.deck.board_factory()
        try:
            card = board.get(card_id)
            rev = self.deck.card_rev(card_id)
            # THE TRASH'S STAMP TOO (lane BD): a delete or a restore changes what an embed
            # draws without touching the card or the plan file.
            # `docs` lists CI by readiness, which the card's rev does not move (c-642 r2.F5)
            offered = int(ciroute.offered(self.cfg, card))
            # and the flow's files: the answer carries its moves (c-644 r1.F4)
            flow = flow_stamp(self.cfg, card)
            # and the card's files (c-719): every page lists them, and a file page is one
            files = cardfiles.listed(self.cfg, card)       # once per request (r1.F11)
            tag = self.json_tag(f"{rev}-{plan_stamp(self.cfg, card)}-{boardtrash.stamp(self.cfg)}-{doc}-{offered}-{flow}"
                                f"-{cardfiles.stamp_of(files)}-{cardfiles.file_stamp(self.cfg, card, file)}")
            if self.if_none_match() == tag:
                return self.not_modified(tag, vary=True)
            self.reply_json_tagged(200, payload(self.cfg, board, card_id, doc,
                                                getattr(self.deck, "strip", None), file, files), tag)
        except cardfiles.FileRefused as error:
            self.reply_json(404, {"ok": False, "error": str(error)})
        except Exception as error:  # noqa: BLE001 - an unknown id is the common case
            self.reply_json(404, {"ok": False, "error": str(error).splitlines()[0]})
        finally:
            board.close()
