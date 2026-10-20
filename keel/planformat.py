"""The plan format: markdown plus a closed set of fenced blocks, parsed into one document.

A house writes a plan (or an outcome) as text; this module turns that text into a document
the deck renders deterministically: `{version, kind, meta, title, sections, blocks,
problems}`. Every block has a stable `id`, which is what an answer or a note he leaves is
pinned to (C22). Nothing here emits HTML, and nothing the house wrote is ever handed to the
page as markup: prose becomes spans (`keel/planinline.py`), fenced blocks become typed
dicts (`keel/planblocks.py`), and mermaid becomes board ops (`keel/planmermaid.py`).

The closed set is the inventory's (`docs/plan-format.md` is the spec a house is given):
frontmatter, headings, paragraphs, lists (to two levels, a `**Lead:** text` item keeps its
lead), task lists as a checklist, GFM tables with `[ok]`/`[warn]`/`[bad]` chips, callouts
(`> [!info|warn|error|success|settled] Title`), images with a frame hint
(`![caption](path){phone}`), and the fenced kinds in `planblocks.KINDS`.

Named sections (Summary, Goal, Now, Target, Proposal, Decisions, Risks, Steps, Proof, Out of
scope, Open questions, the outcome's five and its Risk, and the PR context's seven) are recognised by
their heading text and given a `name`: the lint checks the ones the contract requires, the
renderer draws them, and nothing about their grammar changes.
"""

from __future__ import annotations

import re

from keel import planblocks
from keel.planinline import plain, spans, using

VERSION = 1
FENCE = re.compile(r"^(?P<ticks>`{3,}|~{3,})\s*(?P<kind>[\w-]*)\s*(?P<info>.*)$")
HEADING = re.compile(r"^(?P<hashes>#{1,4})\s+(?P<text>.+?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^(?P<indent>\s*)(?P<mark>[-*+]|\d+[.)])\s+(?P<text>.*)$")
TASK = re.compile(r"^\[(?P<done>[ xX])\]\s+(?P<text>.*)$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
IMAGE_LINE = re.compile(r"^!\[(?P<caption>[^\]]*)\]\((?P<path>[^)\s]+)\)(?:\{(?P<frame>\w+)\})?\s*$")
CALLOUT = re.compile(r"^\[!(?P<tone>\w+)\]\s*(?P<title>.*)$")
LEAD = re.compile(r"^\*\*(?P<lead>[^*]+?)\*\*[:.]?\s+(?P<rest>.+)$")
CHIP = re.compile(r"^\[(ok|warn|bad)\]\s*(.*)$")
REC_IN_ITEM = re.compile(r"\s*\(?\*{0,2}(?:Recommend(?:ed|ation)?|Rec)\*{0,2}\s*[:.]\*{0,2}\s*", re.I)
CALLOUT_TONES = ("info", "warn", "error", "success", "settled")
NONE_WORDS = ("none", "none.", "nothing", "none open", "no open questions")
COMMENT = "<!--"
UNCLOSED = "never closes, so it is drawn as text"

# Named sections: the heading words each name answers to. The first word list wins, and a
# heading's leading number ("3.") and trailing punctuation are ignored.
SECTION_NAMES = (
    ("summary", ("summary", "tl;dr", "tldr", "at a glance", "in short", "what you are deciding")),
    ("goal", ("goal", "goals", "the goal", "why")),
    ("now", ("now", "current state", "where things stand", "today", "current behaviour",
             "current behavior", "what happens today")),
    ("target", ("target", "desired behaviour", "desired behavior", "target behaviour", "after",
                "what changes")),
    ("proposal", ("proposal", "the change", "the proposal", "approach", "the fix", "design",
                  "how it works", "the plan", "plan")),
    ("decisions", ("decisions", "decisions for you", "decide", "choices")),
    ("risks", ("risks", "risks and rollback", "trade-offs", "tradeoffs", "risks and open questions",
               "rollback", "failure modes")),
    ("steps", ("steps", "order of work", "build order", "plan of work", "sequencing", "phases")),
    ("proof", ("proof", "how it will be proved", "how i build and prove it", "tests", "testing",
               "verification", "how it is proved")),
    ("out", ("out of scope", "not doing", "non-goals", "not in this card", "what this does not change")),
    ("questions", ("open questions", "questions", "open threads", "open threads / follow-ups")),
    ("files", ("files touched", "files", "files to change")),
    # The outcome's five (context.md) and the PR context's seven.
    ("stands", ("where it stands",)),
    ("next", ("what is next", "next", "next steps", "what's next")),
    ("why", ("why this shape",)),
    # A research outcome's (`kind: research`, c-719): Findings, then this, What is next, Evidence.
    ("meaning", ("what it means", "what this means", "so what", "implications")),
    ("evidence", ("evidence",)),
    ("risk", ("risk", "risk score")),      # a shipped change's outcome (the pipeline's risk step)
    ("pr_body", ("pr body", "pr body (staged)")),
    ("design", ("design decisions and constraints", "design decisions")),
    ("findings", ("review findings", "findings")),
    # A review card's outcome (`kind: review`, lane RC): its orientation and its verdict.
    ("orientation", ("orientation", "the orientation")),
    ("verdict", ("verdict", "the verdict")),
    ("snippets", ("snippets", "code snippets")),
)
NAME_OF = {word: name for name, words in SECTION_NAMES for word in words}


def section_name(text: str) -> str | None:
    key = re.sub(r"^\d+[.)]?\s*", "", text.strip()).strip(" :.").lower()
    key = key.split(" (")[0] if key not in NAME_OF else key
    return NAME_OF.get(key)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32] or "s"


# ----- the document -----

def frontmatter(lines: list[str]) -> tuple[dict, int]:
    """`---` lines of `key: value` at the very top: (meta, the first body line)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, index + 1
        key, sep, value = line.partition(":")
        if sep and key.strip():
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]           # YAML habit: a quoted value is the words inside
            meta[key.strip().lower()] = value
    return {}, 0


def guess_kind(meta: dict, name: str) -> str:
    kind = (meta.get("kind") or "").lower()
    if kind in ("plan", "outcome", "research", "report", "review", "pr"):
        return kind
    return "outcome" if name == "context.md" else "plan"


def parse(text: str, name: str = "plan.md", refs=None) -> dict:
    """The whole document: what the deck renders and what the lint reads. `refs` is the
    card's space's reference pattern (`terms.refs`, c-630); with none, only cards and paths
    are linked."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    meta, start = frontmatter(lines)
    # c-719: a comment is the author's note to itself (the record a card starts with says what
    # an outcome is for this way), never drawn; one that never closes is drawn, and said
    lines, unclosed = uncomment(lines)
    doc = {"version": VERSION, "kind": guess_kind(meta, name), "meta": meta,
           "title": meta.get("title", ""), "sections": [], "blocks": [], "problems": [],
           "format": bool(meta)}
    doc["problems"] += [{"block": None, "level": "warning", "rule": "C11",
                         "text": f"a <!-- comment opened on line {line} {UNCLOSED}"}
                        for line in unclosed if line > start]
    with using(refs):
        Parser(doc).run(lines[start:], start)
    doc["counts"] = counts(doc)
    return doc


def counts(doc: dict) -> dict:
    """What the deck can say about a plan without drawing it (R11): the decisions, the
    questions and the risks it carries."""
    kinds = [b["type"] for b in all_blocks(doc["blocks"])]
    batch_rows = sum(len(b.get("rows", [])) for b in all_blocks(doc["blocks"]) if b["type"] == "batch")
    batch_rows += kinds.count("finding")      # each finding is one choice he makes (lane FC)
    questions = sum(len(b.get("items", [])) for b in all_blocks(doc["blocks"]) if b["type"] == "questions")
    return {"decisions": kinds.count("decision") + batch_rows, "questions": questions,
            "diagrams": kinds.count("diagram") + kinds.count("board"),
            "blocks": len(kinds)}


def all_blocks(blocks: list[dict]):
    for block in blocks:
        yield block
        if block.get("blocks"):
            yield from all_blocks(block["blocks"])


class Parser:
    """One pass over the lines, block by block. A section heading opens a section; every
    block after it carries that section's id."""

    def __init__(self, doc: dict, nested: bool = False):
        self.doc, self.nested = doc, nested
        self.section = {"id": "top", "name": None}
        self.ordinal: dict[str, int] = {}
        self.out: list[dict] = doc["blocks"] if not nested else []

    # --- ids ---

    def new_id(self, kind: str, wanted: str | None = None) -> str:
        if wanted:
            base = wanted
        else:
            base = f"{self.section['id']}.{kind}"
        n = self.ordinal.get(base, 0) + 1
        self.ordinal[base] = n
        return base if (wanted and n == 1) else f"{base}{n}"

    def add(self, block: dict, kind: str, wanted: str | None = None) -> None:
        block["id"] = self.new_id(kind, wanted)
        block["section"] = self.section["id"]
        if block.get("problems"):
            self.doc["problems"].extend({"block": block["id"], "text": p} for p in block["problems"])
        self.out.append(block)

    # --- the pass ---

    def run(self, lines: list[str], offset: int = 0) -> list[dict]:
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
            elif FENCE.match(stripped):
                i = self.fence(lines, i)
            elif HEADING.match(stripped) and not self.nested:
                self.heading(HEADING.match(stripped))
                i += 1
            elif stripped.startswith(">"):
                i = self.quote(lines, i)
            elif stripped.startswith("|") and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]):
                i = self.table(lines, i)
            elif LIST_ITEM.match(line):
                i = self.list(lines, i)
            elif IMAGE_LINE.match(stripped):
                i = self.images(lines, i)
            elif re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
                i += 1
            else:
                i = self.paragraph(lines, i)
        return self.out

    def heading(self, match) -> None:
        text, level = match["text"], len(match["hashes"])
        if level == 1:
            if not self.doc["title"]:
                self.doc["title"] = text
            return
        name = section_name(text) if level == 2 else None
        base = name or slug(text)
        sid = base if base not in [s["id"] for s in self.doc["sections"]] else f"{base}-{len(self.doc['sections'])}"
        if level == 2:
            self.section = {"id": sid, "name": name}
            self.doc["sections"].append({"id": sid, "name": name, "title": spans(text),
                                         "text": text})
            self.out.append({"type": "heading", "id": sid, "level": 2, "section": sid,
                             "text": spans(text), "name": name})
        else:
            self.add({"type": "heading", "level": level, "text": spans(text)}, "h")

    def fence(self, lines: list[str], i: int) -> int:
        match = FENCE.match(lines[i].strip())
        ticks, kind, info = match["ticks"], match["kind"], match["info"].strip()
        body, j = [], i + 1
        while j < len(lines) and not lines[j].strip().startswith(ticks):
            body.append(lines[j])
            j += 1
        if j >= len(lines):
            self.doc["problems"].append({"block": None, "text": f"a ```{kind} fence opened on line {i + 1} never closes"})
        block = planblocks.fenced(kind, info, body, self.nested_blocks)
        wanted = block.get("id") if block.get("type") in ("decision", "batch", "options", "finding") and block.get("id") else None
        self.add(block, block["type"], wanted)
        return j + 1

    def nested_blocks(self, lines: list[str]) -> list[dict]:
        inner = Parser(self.doc, nested=True)
        inner.section = self.section
        inner.ordinal = self.ordinal
        return inner.run(lines)

    def quote(self, lines: list[str], i: int) -> int:
        body = []
        while i < len(lines) and lines[i].strip().startswith(">"):
            body.append(lines[i].strip()[1:].strip())
            i += 1
        match = CALLOUT.match(body[0]) if body else None
        if match:
            tone = match["tone"].lower()
            block = {"type": "callout", "tone": tone if tone in CALLOUT_TONES else "info",
                     "title": spans(match["title"]), "body": paragraphs(body[1:])}
            if tone not in CALLOUT_TONES:
                self.doc["problems"].append({"block": None, "text": f"callout tone {tone!r} is not one of {', '.join(CALLOUT_TONES)}"})
            self.add(block, "callout")
        else:
            self.add({"type": "quote", "body": paragraphs(body)}, "quote")
        return i

    def table(self, lines: list[str], i: int) -> int:
        head = cells(lines[i])
        rows, j = [], i + 2
        while j < len(lines) and lines[j].strip().startswith("|"):
            rows.append([cell(c) for c in cells(lines[j])])
            j += 1
        caption = self.caption()
        block = {"type": "table", "head": [spans(h) for h in head], "rows": rows}
        if caption:
            block["caption"] = caption
        self.add(block, "table")
        return j

    def caption(self) -> list | None:
        """The paragraph right above a table is what the rows prove (C20)."""
        last = self.out[-1] if self.out else None
        if last and last["type"] == "paragraph" and last.get("section") == self.section["id"]:
            return last["text"]
        return None

    def list(self, lines: list[str], i: int) -> int:
        items, j, ordered = [], i, bool(re.match(r"^\s*\d", lines[i]))
        base = len(LIST_ITEM.match(lines[i])["indent"])
        while j < len(lines):
            match = LIST_ITEM.match(lines[j])
            if match and len(match["indent"]) <= base + 1:
                items.append({"raw": match["text"], "children": []})
                j += 1
            elif match and items:
                items[-1]["children"].append(match["text"])
                j += 1
            elif lines[j].strip() and lines[j].startswith((" ", "\t")) and items:
                items[-1]["raw"] += " " + lines[j].strip()
                j += 1
            else:
                break
        self.list_block(items, ordered)
        return j

    def list_block(self, items: list[dict], ordered: bool) -> None:
        tasks = [TASK.match(it["raw"]) for it in items]
        if all(tasks):
            self.add({"type": "checklist", "items": [
                {"text": spans(t["text"]), "done": t["done"] != " "} for t in tasks]}, "checklist")
            return
        if self.section["name"] == "questions" and not self.nested:
            self.add(questions_of(items), "questions")
            return
        self.add({"type": "list", "ordered": ordered,
                  "items": [list_item(it["raw"], it["children"]) for it in items]}, "list")

    def images(self, lines: list[str], i: int) -> int:
        shots = []
        while i < len(lines) and IMAGE_LINE.match(lines[i].strip()):
            match = IMAGE_LINE.match(lines[i].strip())
            frame = (match["frame"] or "").lower()
            shots.append({"caption": spans(match["caption"]), "path": match["path"],
                          "frame": frame if frame in planblocks.FRAMES else "desktop"})
            i += 1
        self.add({"type": "images", "items": shots}, "images")
        return i

    def paragraph(self, lines: list[str], i: int) -> int:
        body = []
        while i < len(lines) and lines[i].strip() and not starts_block(lines, i):
            body.append(lines[i].strip())
            i += 1
        text = " ".join(body)
        if self.section["name"] == "summary" or (not self.doc["sections"] and not self.nested
                                                 and not any(b["type"] == "paragraph" for b in self.out)):
            self.doc.setdefault("summary", spans(text))
        self.add({"type": "paragraph", "text": spans(text)}, "p")
        return i


def uncomment(lines: list[str]) -> tuple[list[str], list[int]]:
    """The lines with each markdown comment taken out (c-719, r1.F4), and the line numbers
    of each `<!--` that never closes. A comment is a `<!--` that opens a line outside a
    fenced block and is closed by a `-->`, on that line or a later one: its lines become blank
    (so every other line keeps its number) and the text after `-->` is kept. A `<!--` with no
    `-->` after it is not a comment, and stays as text. Every reader of a record goes through
    this one rule (the page's parser, `strip_comments` for the pane's sections, the work pack's
    PR body), so the page, the pane and the pull request read the same words."""
    out, unclosed, fence, i = list(lines), [], None, 0
    while i < len(out):
        stripped = out[i].strip()
        if fence:
            fence = None if stripped.startswith(fence) else fence
        elif FENCE.match(stripped):
            fence = FENCE.match(stripped)["ticks"]
        elif stripped.startswith(COMMENT):
            start = out[i].index(COMMENT)
            j = next((k for k in range(i, len(out)) if "-->" in out[k][start + 4 if k == i else 0:]), None)
            if j is None:
                unclosed.append(i + 1)
            else:
                close = out[j].index("-->", start + 4 if j == i else 0)
                for k in range(i, j):
                    out[k] = ""
                out[j] = out[j][close + 3:]
                continue           # the kept text is read again, as any line is
        i += 1
    return out, unclosed


def strip_comments(text: str) -> str:
    """`text` as the page reads it: its comments out (`uncomment`)."""
    return "\n".join(uncomment((text or "").split("\n"))[0])


def starts_block(lines: list[str], i: int) -> bool:
    stripped = lines[i].strip()
    return bool(FENCE.match(stripped) or HEADING.match(stripped) or stripped.startswith(">")
                or LIST_ITEM.match(lines[i]) or IMAGE_LINE.match(stripped)
                or (stripped.startswith("|") and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1])))


def paragraphs(body: list[str]) -> list[list]:
    out, current = [], []
    for line in body:
        if line:
            current.append(line)
        elif current:
            out.append(spans(" ".join(current)))
            current = []
    if current:
        out.append(spans(" ".join(current)))
    return out


def cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def cell(text: str) -> dict:
    match = CHIP.match(text)
    if match:
        return {"chip": match.group(1), "text": spans(match.group(2))}
    return {"text": spans(text)}


def list_item(raw: str, children: list[str]) -> dict:
    match = LEAD.match(raw)
    item = {"lead": spans(match["lead"]), "text": spans(match["rest"])} if match else {"text": spans(raw)}
    if children:
        item["children"] = [list_item(c, []) for c in children]
    return item


def questions_of(items: list[dict]) -> dict:
    """An `## Open questions` list: each item a question, a `Recommend:` in it the answer."""
    out = {"type": "questions", "items": []}
    for item in items:
        raw = re.sub(r"^\*\*[^*]+\*\*\s*", lambda m: m.group(0), item["raw"])
        if raw.strip().lower().rstrip(".") in NONE_WORDS:
            out["none"] = spans(raw)
            continue
        parts = REC_IN_ITEM.split(raw, maxsplit=1)
        entry = {"q": spans(parts[0].strip()), "q_text": parts[0].strip()}
        if len(parts) > 1 and parts[1].strip():
            entry["rec"] = spans(parts[1].strip().rstrip(")"))
        out["items"].append(entry)
    return out


def section_blocks(doc: dict, name: str) -> list[dict]:
    """Every block under the named section, in order."""
    ids = {s["id"] for s in doc["sections"] if s["name"] == name}
    return [b for b in doc["blocks"] if b.get("section") in ids and b["type"] != "heading"]


def text_of(block: dict) -> str:
    """What a block says in words, for the lint's writing checks and a quote's anchor."""
    parts = []
    for key in ("text", "q", "because", "why", "title", "caption", "summary", "label"):
        value = block.get(key)
        if isinstance(value, list):
            parts.append(plain(value) if value and isinstance(value[0], dict) else "")
        elif isinstance(value, str) and key in ("text",):
            parts.append(value)
    for item in block.get("items", []) or []:
        parts.append(text_of(item))
    for option in block.get("options", []) or []:
        parts.append(text_of(option))
        parts.extend(plain(option.get(k, [])) for k in ("gets", "cost", "summary", "body"))
    for para in block.get("body", []) if isinstance(block.get("body"), list) and block.get("body") and isinstance(block["body"][0], list) else []:
        parts.append(plain(para))
    for row in block.get("rows", []) or []:
        if isinstance(row, list):
            parts.extend(plain(c.get("text", [])) for c in row)
        else:
            parts.extend(plain(row.get(k, [])) if isinstance(row.get(k), list) else str(row.get(k, ""))
                         for k in ("text", "aspect", "left", "right", "why"))
    return " ".join(p for p in parts if p)
