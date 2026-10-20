"""The voice page's desk layout: every child has a place, and nothing else gets one.

On 2026-09-20 the voice page showed a solid white block down its left column at the desk,
from the header to the Capture and Talk control (c-310, from c-307). It reproduces in no
clean browser: headless Chromium at 1440x900 with no extensions places every element the
page writes, and the left column's free cell paints the page's own `#161412`. The block was
a node injected at body level by something in the browser. A body child with no place of
its own is auto-placed into the first free cell of the desk grid, which is the left column,
and stretched to fill it: measured at 0,61 by 420 by 535, which is that cell exactly.

The fix is structural and lives in `segments/voice/app/app.css`: the free cell is a null
cell rather than a named area nothing claims, the warn bar has a row of its own instead of
sharing the status line's, and a catch-all takes any child the page did not write out of
flow and down to zero size.

These tests hold the rules that reproduction produced. They are greps, deliberately, in the
style of `tests/test_deck_css.py`: a stdlib suite cannot lay out CSS, and a test that
pretended to would be worse than one that says plainly what it checks for. The render is
still the proof. What these do is fail in `make test` when a later child forgets its place,
rather than six weeks later on his desk.

The rules, in the order they are checked:

1. The desk's `@media (min-width:900px)` block exists at all. Every rule below reads it, so
   an empty match is the real failure.
2. Every top-level element of `index.html` either has a `grid-area` inside that block or is
   one of the two that are out of flow at every width (`.sheet`, a closed `dialog`, and
   `script`).
3. Every class the page's scripts insert at body level has a `grid-area`. A body-level insertion the
   test cannot read the class of is a failure, not a pass.
4. Every name in `grid-template-areas` is claimed by exactly one rule, and every `grid-area`
   names an area the template has. A null cell is `.` and claims nothing.
5. The catch-all's `:not(...)` list is exactly the placed set plus the out-of-flow set.
   Those are two enumerations of the same thing, and drift between them is the next version
   of this bug.
6. The catch-all carries no `!important`. That absence is load-bearing: an inline style
   beats a stylesheet rule, so an extension that positions its own widget survives, and
   only an unstyled node is taken out. A later tidy-up that adds `!important` would change
   behaviour, so it fails here.

Reproducing it again needs a browser. On the box: `npm i playwright-core && npx
playwright-core install chromium`, then `apt-get download` the libraries `ldd` reports
missing (plus `fonts-dejavu-core`), `dpkg-deb -x` them into a local sysroot and point
`LD_LIBRARY_PATH` and `FONTCONFIG_FILE` at it. The box's own browser tool supersedes this
recipe once it lands, and then this paragraph is the bug.
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.voicepage import raw_script

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "segments" / "voice" / "app"
DESK = re.compile(r"@media\s*\(\s*min-width\s*:\s*900px\s*\)\s*\{")

COMMENT = re.compile(r"/\*.*?\*/", re.S)

# The two top-level elements that never take a cell: a closed `dialog` is `display:none`
# and an open one is in the top layer, and a `<script>` is `display:none` at every width.
# Anything else in this set would be a page element nobody can see, so it stays this short.
OUT_OF_FLOW = {".v-sheet", "script"}

# What the page's scripts put at body level. The test proves this list is the whole list.
# Empty since the rebuild (VP-1): the reason line that was the warn bar lives in the dock.
INSERTED: set[str] = set()

# Every `document.body.<this>` that can add a child. `dataset` and `classList` are not here
# because they change the body, not its children.
MUTATORS = ("appendChild", "insertBefore", "prepend", "append", "replaceChildren",
            "insertAdjacentHTML", "insertAdjacentElement")


def css() -> str:
    """`app.css` with its comments stripped.

    The comments here quote the rules they explain, `!important` and braces and all, so a
    grep over the raw file finds the rule it is looking for inside the paragraph saying why
    it exists. `tests/test_deck_css.py` caught itself doing exactly that.
    """
    return COMMENT.sub("", (APP / "app.css").read_text(encoding="utf-8"))


def desk_block(text: str) -> str:
    """The body of the `@media (min-width:900px)` block. Braces are balanced by counting
    rather than by a regex, which cannot."""
    out = []
    for start in (m.end() for m in DESK.finditer(text)):
        depth, i = 1, start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        out.append(text[start:i - 1])
    return "\n".join(out)


def rules(block: str) -> list[tuple[str, str]]:
    """Every `selector { declarations }` in a block, as pairs, nested blocks aside."""
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", block)]


def placed(block: str) -> dict[str, list[str]]:
    """Area name -> the selectors that claim it with `grid-area`."""
    claims: dict[str, list[str]] = {}
    for selector, body in rules(block):
        found = re.search(r"grid-area\s*:\s*([A-Za-z_][\w-]*)", body)
        if found:
            claims.setdefault(found.group(1), []).append(selector)
    return claims


def template_names(block: str) -> list[str]:
    """The named areas of `grid-template-areas`, in order, null cells left out."""
    found = re.search(r"grid-template-areas\s*:([^;]+);", block)
    if not found:
        return []
    names = []
    for row in re.findall(r'"([^"]*)"', found.group(1)):
        names += [token for token in row.split() if set(token) != {"."}]
    return names


def allowlist(text: str) -> list[str]:
    """The `:not(...)` list of the catch-all, as written."""
    found = re.search(r"body\s*>\s*\*\s*:not\(([^)]*)\)", text)
    return [] if not found else [part.strip() for part in found.group(1).split(",")]


def catch_all(text: str) -> str | None:
    """The catch-all's declarations."""
    found = re.search(r"body\s*>\s*\*\s*:not\([^)]*\)\s*\{([^{}]*)\}", text)
    return None if not found else found.group(1)


class BodyChildren(HTMLParser):
    """The top-level elements of `index.html`, as `.firstclass` or the bare tag name.

    A real parser rather than a regex: the page's comments carry markup-shaped prose, and
    the depth count has to be right for the answer to mean anything.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_body = False
        self.found: list[str] = []
        # `<br>` and friends never open a level, so the depth count must know them.
        self.void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                     "meta", "param", "source", "track", "wbr"}

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
            return
        if tag in self.void:
            return
        if self.in_body:
            if self.depth == 0:
                classes = dict(attrs).get("class", "").split()
                self.found.append("." + classes[0] if classes else tag)
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
        elif self.in_body and tag not in self.void:
            self.depth = max(0, self.depth - 1)


def top_level() -> list[str]:
    parser = BodyChildren()
    parser.feed((APP / "index.html").read_text(encoding="utf-8"))
    return parser.found


def body_inserts() -> list[tuple[int, str | None]]:
    """Every body-level insertion in `app.js`, as (line number, the class it inserts).

    The class is read from the variable the call is handed, which is exact, and failing
    that from a `class="..."` in a string literal argument. A `None` means the call is
    there and the test could not read a class for it, which is a failure with its own
    message rather than a silent pass.
    """
    text = raw_script()
    call = re.compile(r"document\.body\.(?:%s)\s*\(\s*([^,)]*)" % "|".join(MUTATORS))
    out = []
    for match in call.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        argument = match.group(1).strip()
        found = None
        name = re.fullmatch(r"[A-Za-z_$][\w$]*", argument)
        if name:
            said = re.search(r"\b%s\.className\s*=\s*[\"']([^\"']+)" % re.escape(argument),
                             text)
            if not said:
                said = re.search(
                    r"\b%s\.setAttribute\(\s*[\"']class[\"']\s*,\s*[\"']([^\"']+)"
                    % re.escape(argument), text)
            if said:
                found = "." + said.group(1).split()[0]
        else:
            said = re.search(r"class=\\?[\"']([^\"'\\]+)", argument)
            if said:
                found = "." + said.group(1).split()[0]
        out.append((line, found))
    return out



class EveryChildHasAPlace(unittest.TestCase):
    def setUp(self):
        self.block = desk_block(css())
        self.claims = placed(self.block)
        self.selectors = {s for names in self.claims.values() for s in names}


    def test_every_top_level_element_is_placed_or_out_of_flow(self):
        for child in top_level():
            with self.subTest(child=child):
                if child in OUT_OF_FLOW:
                    continue
                self.assertIn(
                    child, self.selectors,
                    f"{child} is a top-level element of index.html with no grid-area at "
                    f"the desk. Give it one, or add it to OUT_OF_FLOW and say why.")

    def test_every_class_app_js_inserts_at_body_level_is_placed(self):
        for line, found in body_inserts():
            with self.subTest(line=line):
                self.assertIsNotNone(
                    found,
                    f"app.js inserts at body level at line {line} and this test cannot "
                    f"read the class it inserts. Name it in INSERTED.")
                self.assertIn(
                    found, INSERTED,
                    f"app.js inserts {found} at body level (line {line}) and INSERTED does "
                    f"not know about it.")
                self.assertIn(
                    found, self.selectors,
                    f"{found} is inserted at body level with no grid-area at the desk.")

    def test_inserted_is_the_whole_list(self):
        """A class that leaves `app.js` should leave `INSERTED` with it."""
        self.assertEqual({found for _, found in body_inserts()}, INSERTED)


class TheGridClaimsItsOwnCells(unittest.TestCase):
    def setUp(self):
        self.block = desk_block(css())
        self.claims = placed(self.block)


    def test_every_name_is_claimed_by_exactly_one_rule(self):
        for name in set(template_names(self.block)):
            with self.subTest(area=name):
                who = self.claims.get(name, [])
                self.assertEqual(
                    len(who), 1,
                    f"grid-template-areas names `{name}` and {len(who)} rules claim it "
                    f"({', '.join(who) or 'none'}). An unclaimed cell is where an injected "
                    f"node lands; two rules on one cell is the warn bar over the status "
                    f"line.")

    def test_every_grid_area_names_an_area_the_template_has(self):
        names = set(template_names(self.block))
        for name, who in self.claims.items():
            with self.subTest(area=name):
                self.assertIn(name, names,
                              f"{', '.join(who)} claims `{name}`, which the template "
                              f"does not have")

    def test_a_free_cell_is_a_null_cell_and_never_a_named_one(self):
        """`spacer` was a name no rule claimed, which is what the white block sat in. The
        studio's grid (VP-1) has no free cell at all; if one comes back it must be `.`."""
        self.assertNotIn("spacer", template_names(self.block))
        found = re.search(r"grid-template-areas\s*:([^;]+);", self.block)
        claimed = set(placed(self.block))
        for row in re.findall(r'"([^"]*)"', found.group(1)):
            for token in row.split():
                self.assertTrue(token in claimed or set(token) == {"."},
                                f"`{token}` is a cell nothing claims and it is not `.`")


class NothingUnrecognisedIsLaidOut(unittest.TestCase):
    def setUp(self):
        self.text = css()
        self.block = desk_block(self.text)

    def test_the_allowlist_is_the_placed_set_plus_the_out_of_flow_set(self):
        """The `:not()` and the `grid-area` rules are two enumerations of one list."""
        selectors = {s for names in placed(self.block).values() for s in names}
        self.assertEqual(
            set(allowlist(self.text)), selectors | OUT_OF_FLOW,
            "the catch-all's :not(...) and the desk's grid-area rules have drifted. "
            "A name in one and not the other is either an element that vanishes or an "
            "element that takes the left column.")

    def test_it_takes_the_node_out_of_flow_and_down_to_nothing(self):
        body = catch_all(self.text).replace(" ", "")
        self.assertIn("position:absolute", body,
                      "an unrecognised child is still a grid item")
        self.assertIn("width:0", body)
        self.assertIn("height:0", body,
                      "out of flow alone leaves a bare iframe painting its 300x150 default")


if __name__ == "__main__":
    unittest.main()
