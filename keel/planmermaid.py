"""Mermaid, read as board ops: the three diagram kinds a plan uses, drawn by the board.

The corpus used exactly three mermaid kinds (inventory, block 29: flowchart 37,
sequenceDiagram 5, stateDiagram-v2 5, nothing else). Decision B2 dropped the mermaid escape
hatch from the board because a sandboxed third-party parser is a second rendering path on
the origin the approve verbs live in. So a plan's ```mermaid block is TRANSLATED here into
the board's own line language, and the deck draws it with the board's ELK renderer: one
renderer, one theme, the same pan-free static drawing on the phone.

What is translated, and what is dropped (said in `problems`, never silently):

- flowchart / graph: nodes with any bracket shape (a cylinder becomes the database icon),
  edges `-->`, `---`, `-.->`, `==>`, `<-->`, with `|label|` or `-- label -->`, chains
  `A --> B --> C`, `A & B --> C`, and `subgraph ... end` as a group. Styling lines
  (`classDef`, `class`, `style`, `linkStyle`, `click`) are dropped.
- sequenceDiagram: each participant or actor is a node; each message is an edge labelled
  with its number and text, and a numbered step on its sender, so the board's walk view
  plays the sequence in order. `note`, `loop`, `alt`, `activate` are dropped.
- stateDiagram-v2: states are nodes, `[*]` is a start or an end node, transitions are
  edges labelled with their event, `state X { }` is a group.

The board's caps hold: past twelve nodes the diagram is refused with the reason, as a push
would be.
"""

from __future__ import annotations

import re

MAX_NODES = 12
LABEL_MAX = 120
ICON_WORDS = (("database", ("db", "database", "sqlite", "postgres", "store", "table")),
              ("phone", ("phone", "mobile", "ios", "android")),
              ("user", ("user", "human", "him", "his", "person")),
              ("server", ("server", "service", "api", "backend", "daemon")),
              ("bot", ("house", "agent", "claude", "model", "llm", "bot")),
              ("cloud", ("cloud", "box", "vps")),
              ("laptop", ("mac", "laptop", "desk")),
              ("file", ("file", "log", "plan.md", "context.md")),
              ("clock", ("timer", "cron", "schedule", "clock")),
              ("mic", ("voice", "mic", "speech")))
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,47}$")
SHAPES = re.compile(r"""^(?P<id>[A-Za-z0-9_][\w.-]*)\s*
    (?P<open>\(\[|\[\(|\(\(|\[\[|\[/|\[\\|\{\{|\[|\(|\{|>)
    (?P<label>.*?)
    (?P<close>\]\)|\)\]|\)\)|\]\]|/\]|\\\]|\}\}|\]|\)|\})\s*$""", re.X)
FLOW_EDGE = re.compile(r"\s*(?P<arrow><-->|<==>|<-.->|-->|---|-\.->|-\.-|==>|===|--o|--x)\s*(?:\|(?P<label>[^|]*)\|)?\s*")
TEXT_EDGE = re.compile(r"\s*(?:--|==|-\.)\s+(?P<label>[^-=.][^>]*?)\s+(?P<arrow>-->|==>|\.->|---)\s*")
SKIP_FLOW = ("classDef", "class ", "style ", "linkStyle", "click ", "direction ")
SEQ_MSG = re.compile(r"^(?P<a>[^\s-][^-:>]*?)\s*(?P<arrow>-->>|->>|-->|->|--x|-x|--\)|-\))\s*(?P<b>[^:]+?)\s*:\s*(?P<text>.*)$")
SEQ_PART = re.compile(r"^(?P<kind>participant|actor)\s+(?P<id>\S+)(?:\s+as\s+(?P<label>.+))?$")
SEQ_SKIP = ("note ", "loop", "alt", "else", "opt", "par", "and", "end", "activate",
            "deactivate", "autonumber", "rect", "critical", "break", "box")
STATE_EDGE = re.compile(r"^(?P<a>\[\*\]|[\w.-]+)\s*-->\s*(?P<b>\[\*\]|[\w.-]+)\s*(?::\s*(?P<label>.*))?$")
STATE_AS = re.compile(r'^state\s+"(?P<label>[^"]+)"\s+as\s+(?P<id>[\w.-]+)\s*$')
STATE_GROUP = re.compile(r"^state\s+(?:\"(?P<label>[^\"]+)\"\s+as\s+)?(?P<id>[\w.-]+)\s*\{\s*$")
STATE_DESC = re.compile(r"^(?P<id>[\w.-]+)\s*:\s*(?P<text>.+)$")


def quote(text: str) -> str:
    text = " ".join(str(text).replace('"', "'").split())
    return '"' + text[:LABEL_MAX] + '"'


def clean_label(text: str) -> str:
    text = text.strip().strip('"').strip()
    text = re.sub(r"<br\s*/?>", " ", text)
    return re.sub(r"</?\w+>", "", text)


def icon_for(label: str, shape: str = "") -> str:
    if shape in ("[(", ")]"):
        return "database"
    found = set(re.findall(r"[a-z0-9.]+", label.lower()))
    for icon, words in ICON_WORDS:
        if any(word.strip() in found for word in words):
            return icon
    return "box"


class Graph:
    """The ops a translation writes, in the order the board wants them: groups first,
    then nodes (in their group), then edges and attachments."""

    def __init__(self):
        self.ids: dict[str, str] = {}
        self.nodes: dict[str, dict] = {}
        self.groups: list[tuple[str, str]] = []
        self.edges: list[str] = []
        self.steps: list[str] = []
        self.problems: list[str] = []
        self.group_stack: list[str] = []

    def name(self, raw: str) -> str:
        if raw in self.ids:
            return self.ids[raw]
        base = re.sub(r"[^A-Za-z0-9_.:-]", "_", raw).strip("_") or "n"
        if not base[0].isalnum():
            base = "n" + base
        name, n = base[:40], 2
        while name in self.nodes and self.nodes[name]["raw"] != raw:
            name, n = f"{base[:36]}_{n}", n + 1
        self.ids[raw] = name
        return name

    def node(self, raw: str, label: str | None = None, icon: str | None = None) -> str:
        name = self.name(raw)
        known = self.nodes.get(name)
        if known is None:
            self.nodes[name] = {"raw": raw, "label": clean_label(label or raw),
                                "icon": icon or icon_for(label or raw),
                                "group": self.group_stack[-1] if self.group_stack else None}
        elif label:
            known["label"] = clean_label(label)
            known["icon"] = icon or icon_for(label)
        return name

    def open_group(self, raw: str, label: str) -> None:
        name = "g_" + self.name("group:" + raw)[:40]
        self.groups.append((name, clean_label(label or raw)))
        self.group_stack.append(name)

    def close_group(self) -> None:
        if self.group_stack:
            self.group_stack.pop()

    def edge(self, a: str, b: str, arrow: str = "->", label: str = "") -> None:
        tail = f" {quote(clean_label(label))}" if label and clean_label(label) else ""
        self.edges.append(f"edge {a} {arrow} {b}{tail}")

    def ops(self) -> list[str]:
        if len(self.nodes) > MAX_NODES:
            self.problems.append(f"the diagram has {len(self.nodes)} nodes and a board holds "
                                 f"{MAX_NODES}: split it into two diagrams")
        out = [f"group {gid} {quote(label)}" for gid, label in self.groups]
        for name, node in self.nodes.items():
            where = f" in {node['group']}" if node["group"] else ""
            out.append(f"node {name} {node['icon']} {quote(node['label'])}{where}")
        return out + self.edges + self.steps


def statements(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.split("%%", 1)[0].strip()
        if line:
            out.extend(part.strip() for part in line.split(";") if part.strip())
    return out


def translate(text: str) -> dict:
    """`{kind, ops, problems}` for one mermaid source."""
    lines = statements(text)
    if not lines:
        return {"kind": "empty", "ops": [], "problems": ["the mermaid block is empty"]}
    head = lines[0].split()[0]
    if head in ("flowchart", "graph"):
        graph, kind = flowchart(lines[1:]), "flowchart"
    elif head == "sequenceDiagram":
        graph, kind = sequence(lines[1:]), "sequence"
    elif head in ("stateDiagram-v2", "stateDiagram"):
        graph, kind = state(lines[1:]), "state"
    else:
        return {"kind": head, "ops": [], "problems": [
            f"mermaid {head!r} is not one of the three kinds a plan draws (flowchart, "
            f"sequenceDiagram, stateDiagram-v2); use a board block"]}
    return {"kind": kind, "ops": graph.ops(), "problems": graph.problems}


# ----- flowchart -----

def flow_node(graph: Graph, token: str) -> str | None:
    token = token.strip()
    if not token:
        return None
    match = SHAPES.match(token)
    if match:
        return graph.node(match["id"], match["label"], icon_for(clean_label(match["label"]), match["open"]))
    if re.match(r"^[A-Za-z0-9_][\w.-]*$", token):
        return graph.node(token)
    graph.problems.append(f"flowchart: could not read the node {token[:40]!r}")
    return None


def flow_arrow(arrow: str) -> str:
    return "<->" if arrow.startswith("<") else "--" if arrow in ("---", "===", "-.-") else "->"


def split_edges(line: str) -> list:
    """`A -->|x| B --> C` as [A, (arrow, label), B, (arrow, label), C]."""
    parts, rest = [], line
    while True:
        match = FLOW_EDGE.search(rest) or TEXT_EDGE.search(rest)
        both = [m for m in (FLOW_EDGE.search(rest), TEXT_EDGE.search(rest)) if m]
        if both:
            match = min(both, key=lambda m: m.start())
        if not match:
            parts.append(rest)
            return parts
        parts.append(rest[:match.start()])
        parts.append((match["arrow"], (match["label"] or "").strip()))
        rest = rest[match.end():]


def flowchart(lines: list[str]) -> Graph:
    graph = Graph()
    for line in lines:
        if line.startswith(SKIP_FLOW):
            continue
        if line.startswith("subgraph"):
            rest = line[len("subgraph"):].strip()
            match = re.match(r"^([\w.-]+)\s*\[(.*)\]\s*$", rest)
            raw, label = (match.group(1), match.group(2)) if match else (rest, rest)
            graph.open_group(raw, label)
            continue
        if line == "end":
            graph.close_group()
            continue
        parts = split_edges(line)
        previous = None
        for index in range(0, len(parts), 2):
            names = [flow_node(graph, t) for t in parts[index].split("&")]
            names = [n for n in names if n]
            if previous is not None and index >= 2:
                arrow, label = parts[index - 1]
                for a in previous:
                    for b in names:
                        graph.edge(a, b, flow_arrow(arrow), label)
            previous = names
    return graph


# ----- sequence -----

def sequence(lines: list[str]) -> Graph:
    graph, number = Graph(), 0
    for line in lines:
        part = SEQ_PART.match(line)
        if part:
            icon = "user" if part["kind"] == "actor" else None
            graph.node(part["id"], part["label"] or part["id"], icon)
            continue
        if line.split()[0] in SEQ_SKIP or line.startswith(SEQ_SKIP):
            continue
        message = SEQ_MSG.match(line)
        if not message:
            graph.problems.append(f"sequence: could not read {line[:40]!r}")
            continue
        number += 1
        a, b = graph.node(message["a"].strip()), graph.node(message["b"].strip().lstrip("+-"))
        text = clean_label(message["text"])
        graph.edge(a, b, "->", f"{number}. {text}")
        graph.steps.append(f"step {a} {quote(f'{number}. {text}')}")
    return graph


# ----- state -----

def state(lines: list[str]) -> Graph:
    graph = Graph()
    for line in lines:
        if line.startswith(("direction", "note ", "classDef", "class ")):
            continue
        match = STATE_GROUP.match(line)
        if match:
            graph.open_group(match["id"], match["label"] or match["id"])
            continue
        if line == "}":
            graph.close_group()
            continue
        match = STATE_AS.match(line)
        if match:
            graph.node(match["id"], match["label"])
            continue
        match = STATE_EDGE.match(line)
        if match:
            a = start_or(graph, match["a"], "start")
            b = start_or(graph, match["b"], "end")
            graph.edge(a, b, "->", match["label"] or "")
            continue
        match = STATE_DESC.match(line)
        if match:
            graph.node(match["id"])
            continue
        graph.problems.append(f"state: could not read {line[:40]!r}")
    return graph


def start_or(graph: Graph, raw: str, which: str) -> str:
    if raw != "[*]":
        return graph.node(raw)
    return graph.node(f"[*]{which}", which, "zap" if which == "start" else "box")
