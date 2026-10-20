"""The neutral templates (c-699, c-672 step 3): what a new install's builder and talker start
with, and its identity file. Each is the lesson, never the story: no person, no machine, no
card, no date, and short enough to be read on every start."""

import re
import unittest
from pathlib import Path

from keel import packs
from tests import owner_words, publiccheck, test_machine_words

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
BUILDER = ("MEMORY.md", "identity.md", "needs-you.md", "authority.md", "builder.md", "requests.md",
           "asks.md", "runbook.md")
TALKER = ("MEMORY.md", "the-engine.md", "cards.md", "needs-the-user.md", "voice.md", "drawing.md",
          "the-deck.md", "CLAUDE.md")
EXPECTED = ([f"memory/bosun/{name}" for name in BUILDER] + [f"memory/talker/{name}" for name in TALKER]
            + ["identity/about-you.md"])
LINES_MAX = 80
# What one install's story looks like in text: a card, request or ask id, a date, a port, an
# address on this machine, a home path, a dash this repo never writes.
STORY = {
    "a card, request, ask or board id": re.compile(r"\b[carb]-\d+\b"),
    "a date": re.compile(r"\b20\d\d-\d\d-\d\d\b"),
    "a port or a local address": re.compile(r"127\.0\.0\.1|localhost|:\d{4}\b"),
    "a home path": re.compile(r"~/|/Users/|/home/"),
    "a long dash": re.compile("[" + chr(0x2014) + chr(0x2013) + "]"),
}
POINTER = re.compile(r'`(docs/atlas/[0-9a-z-]+\.md)`(?:,\s+"([^"]+)")?')
LINKED = re.compile(r"\]\(([a-z-]+\.md)\)")
# Every file a template names in backticks: an Atlas page by its path or by its bare name
# (`96-bosun.md`), a sibling (`asks.md`), or a file of another template folder
# (`identity/about-you.md`).
NAMED_FILE = re.compile(r"`((?:[\w-]+/)*[\w-]+\.md)`")
BARE_PAGE = re.compile(r"\d\d-[a-z0-9-]+\.md")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
LEAD_IN = re.compile(r"(?:^|\n)(?:[-*]\s+|\d+\.\s+|\|\s*)?\*\*(.+?)\*\*", re.S)


TAG = re.compile(r"\s*\([^()]*\)\s*$")     # a heading's closing tag: the card or decision it came from


def plain(text: str) -> str:
    """A title as it is compared: one line, no backticks, no closing mark, and without the
    tag a heading ends on (a template names no card, so it cannot quote one)."""
    return TAG.sub("", " ".join(text.replace("`", "").split())).rstrip(".:,;")


def titles(page: str) -> set[str]:
    """What a page can be pointed at by: each heading, and each bold lead-in that opens a
    paragraph, a list item or a table row. A phrase in running prose is not a title: it
    moves or goes when the paragraph is edited, and the pointer would still pass."""
    return {plain(found) for pattern in (HEADING, LEAD_IN) for found in pattern.findall(page)}


def resolve(name: str, template: Path) -> Path:
    """The file a backticked name in `template` means."""
    if name.startswith("docs/"):
        return ROOT / name
    if BARE_PAGE.fullmatch(name):
        return ROOT / "docs" / "atlas" / name
    if "/" in name:
        return TEMPLATES / name
    return template.parent / name


# The deck's controls a template names, each `(template, label)`: the label must be one the
# deck draws, word for word (review r2.F7), so a user told to tap it finds it.
CONTROLS = [
    ("memory/talker/the-deck.md", "Approve"), ("memory/talker/the-deck.md", "Send back"),
    ("memory/talker/the-deck.md", "Ask"), ("memory/talker/the-deck.md", "Resume house"),
    ("memory/talker/the-deck.md", "Drop in"), ("memory/talker/the-deck.md", "Open in Claude app"),
    ("memory/talker/the-deck.md", "Needs you"), ("memory/talker/the-deck.md", "Settings"),
    ("memory/talker/the-deck.md", "Setup"), ("memory/bosun/builder.md", "Approve outcome"),
]
# A phrase shaped like an "open it there" control, wherever a template says one.
OPEN_IN = re.compile(r"\bOpen in (?:the |Claude )?[A-Za-z]*\s?app\b")


def deck_labels() -> set[str]:
    from tests import nouns     # noqa: PLC0415
    return {" ".join(text.split()) for path in sorted((ROOT / "app").glob("*.js"))
            for _, text in nouns.js_literals(path.read_text(encoding="utf-8"))}


def templates() -> list[Path]:
    return sorted(path for path in TEMPLATES.rglob("*") if path.is_file())


class TemplatesTest(unittest.TestCase):
    def test_every_template_is_there_and_nothing_else(self):
        self.assertEqual(sorted(path.relative_to(TEMPLATES).as_posix() for path in templates()),
                         sorted(EXPECTED))

    def test_each_is_short_enough_to_read_on_every_start(self):
        long = {path.name: len(path.read_text().splitlines()) for path in templates()
                if len(path.read_text().splitlines()) > LINES_MAX}
        self.assertEqual(long, {}, f"a template over {LINES_MAX} lines: {long}")

    def test_none_tells_one_installs_story(self):
        said = [f"{path.relative_to(ROOT)}:{number}: {what}"
                for path in templates() for number, line in enumerate(path.read_text().splitlines(), 1)
                for what, pattern in STORY.items() if pattern.search(line)]
        self.assertEqual(said, [], "\n".join(said))

    def test_none_says_he_or_names_a_machine(self):
        said = [f"{path.relative_to(ROOT)}:{number}"
                for path in templates() for number, line in enumerate(path.read_text().splitlines(), 1)
                if owner_words.WORDS.search(line) or test_machine_words.WORDS.search(line)]
        self.assertEqual(said, [], f"he, his, him or a machine word in: {said}")

    def test_none_says_a_packs_own_words(self):
        terms = packs.all_drift_terms(ROOT)
        pattern = re.compile("|".join(terms), re.I) if terms else None
        said = [path.relative_to(ROOT).as_posix() for path in templates()
                if pattern and pattern.search(path.read_text())]
        self.assertEqual(said, [], f"a pack's own vocabulary in: {said}")

    def test_the_public_check_finds_nothing_of_one_install_in_them(self):
        """The check of c-672 step 5, with every pack's terms and the rules that need no
        install: a template is read against it before it ships (`make drift` reads it with the
        install's own names too)."""
        names = publiccheck.Names(terms=packs.all_drift_terms(ROOT))
        found = [finding for path in templates()
                 for finding in publiccheck.text_findings(path.relative_to(ROOT).as_posix(),
                                                          path.read_text(), names.patterns())]
        self.assertEqual(found, [])

    def test_the_owner_words_guard_reads_them(self):
        read = {path for path, _ in owner_words.sources()}
        self.assertEqual([path.name for path in templates() if path not in read], [])

    def test_each_index_lists_its_files_and_each_link_is_a_file(self):
        for folder, names in (("bosun", BUILDER), ("talker", TALKER)):
            index = (TEMPLATES / "memory" / folder / "MEMORY.md").read_text()
            self.assertEqual(sorted(LINKED.findall(index)), sorted(set(names) - {"MEMORY.md", "CLAUDE.md"}), folder)

    def test_every_atlas_pointer_names_a_page_and_a_title_it_holds(self):
        """A lesson a mechanism enforces points at its Atlas page: the pointer must land."""
        lost = []
        for path in templates():
            for page, title in POINTER.findall(" ".join(path.read_text().split())):
                target = ROOT / page
                if not target.is_file():
                    lost.append(f"{path.name}: {page} is not a page")
                elif title and plain(title) not in titles(target.read_text()):
                    lost.append(f"{path.name}: {page} has no heading or bold lead-in {title!r}")
        self.assertEqual(lost, [], "\n".join(lost))

    def test_every_file_a_template_names_is_there(self):
        """Review F6: a bare page name, a sibling and another folder's file must resolve."""
        lost = [f"{path.relative_to(TEMPLATES)}: {name}" for path in templates()
                for name in NAMED_FILE.findall(path.read_text()) if not resolve(name, path).is_file()]
        self.assertEqual(lost, [], "\n".join(lost))

    def test_a_title_is_a_heading_or_a_bold_lead_in_never_a_phrase_in_prose(self):
        page = ("# The page\n\nIt says the review core in passing, and \"Asks\" too.\n\n"
                "## Who works a card\n\n**Deploy: the ask, and the user's Yes.** The drain raises it.\n\n"
                "- **Only the user orders** a tree.\n\n| **The `kb` verbs** | a row |\n")
        self.assertEqual(titles(page), {"The page", "Who works a card", "Deploy: the ask, and the user's Yes",
                                        "Only the user orders", "The kb verbs"})
        self.assertEqual(titles("### Who works a card (c-645)\n"), {"Who works a card"})

    def test_every_control_a_template_names_is_a_label_the_deck_draws(self):
        labels = deck_labels()
        missing = [f"{name}: {label}" for name, label in CONTROLS
                   if label not in " ".join((TEMPLATES / name).read_text().split()) or label not in labels]
        self.assertEqual(missing, [], "\n".join(missing))
        said = [f"{path.relative_to(TEMPLATES)}: {found}" for path in templates()
                for found in OPEN_IN.findall(" ".join(path.read_text().split())) if found not in labels]
        self.assertEqual(said, [], "an open-in control the deck does not draw:\n" + "\n".join(said))

    def test_a_name_resolves_by_its_kind(self):
        here = TEMPLATES / "memory" / "bosun" / "identity.md"
        self.assertEqual([resolve(name, here).relative_to(ROOT).as_posix() for name in
                          ("docs/atlas/96-bosun.md", "96-bosun.md", "asks.md", "identity/about-you.md")],
                         ["docs/atlas/96-bosun.md", "docs/atlas/96-bosun.md", "templates/memory/bosun/asks.md",
                          "templates/identity/about-you.md"])

    def test_the_story_rules_catch_a_story(self):
        told = "On 2026-01-02 c-12 failed on ~/keel at 127.0.0.1:8800."
        self.assertEqual([what for what, pattern in STORY.items() if pattern.search(told)],
                         ["a card, request, ask or board id", "a date", "a port or a local address",
                          "a home path"])
        self.assertFalse(any(pattern.search("Reproduce a bug before you fix it (`kb show <id>`).")
                             for pattern in STORY.values()))

    def test_the_builder_builds_through_sub_agents_and_stays_free_to_talk(self):
        """c-734 point 10: a Bosun that built a long card in its own session could not talk
        with the user meanwhile; the shipped memory says to build through a builder sub-agent
        with a self-contained brief, and what Bosun keeps."""
        text = " ".join((TEMPLATES / "memory" / "bosun" / "builder.md").read_text().split())
        for said in ("builder sub-agent in its own isolated worktree", "stay free to talk with the user",
                     "Its brief is self-contained: the plan's path, the rules restated",
                     "the test policy, and the report it must return",
                     "You keep the plan, the review order, the answers to the user and the landing",
                     "sized to the machine (`runbook.md`)"):
            self.assertIn(said, text)


if __name__ == "__main__":
    unittest.main()
