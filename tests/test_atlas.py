"""The Atlas drift test: it fails when the Atlas and the code disagree.

The Atlas (`docs/atlas/`) is the source of truth for how Keel works, which is only true if
a rename cannot land without it. These tests are the mechanism behind that claim, and they
are written to be trusted rather than merely strict: every rule below fires on a NAME the
code actually defines, never on prose.

The rules, in the order they are checked:

1. **Every module and script is named.** Each `keel/*.py` (except `__init__.py`) must
   appear somewhere in the Atlas as `keel/<name>.py`, and each executable in `bin/` as
   `bin/<name>`. A module nobody documented is a module nobody can find.
2. **Every verb is named.** Each verb of `cli.VERBS` must appear as `kb <verb>`, and each
   deck action verb (`actions.KB_VERBS`, `HOUSE_VERBS`, `GATE_VERBS`, `BOARD_VERBS`, `SETUP_VERBS`) as its own name in
   backticks. Both tables are the single definition of their verb set, so the check reads
   the code rather than a list kept here.
3. **Every config key is named.** Each key of `[keel]` in `keel.toml` must appear
   somewhere in the Atlas, and every setting of the schema (`keel/settings.py`) in backticks.
4. **Every repo path in backticks exists.** A backticked span counts as a repo path only
   when it is unambiguous: no whitespace, no shell or placeholder character
   (`$ * < > ? | " '`), no leading `~`, `/` or `.`, and it either starts with a real
   top-level directory of the repo or IS a real top-level file. `state/` is deliberately
   left out: it is gitignored runtime state, so it exists on a live machine and not in a
   fresh clone. Anything else in backticks is a command, an identifier or prose and is not
   the test's business.
5. **The index and the files agree.** Every page in `index.json` has a file and every file
   is in the index, and each page's own `# Title` is the title the index gives it, so a
   half-done rename cannot hide.
6. **No page renders a link the deck will not serve.** The renderer says so with an
   `unserved` span, which in a card's context file is honest and in the Atlas is a broken
   link nobody wrote on purpose.
7. **A code block is fenced.** The renderer has no indented-code-block rule, so an
   indented block would render as a run-on paragraph.
8. **The Atlas carries no employer vocabulary.** `make test` exempts `docs/` from that
   grep, as history. The Atlas is not history, so it is checked here instead, against the
   same term lists the grep uses (every pack's `drift-terms`).

9. **A page that ships calls the user "the user"** (c-699). No "he", "his" or "him" in a
   page's prose, in the summaries of `index.json`, or in a title. Code is not prose: a fenced
   block and a backticked span are skipped, and so is a word quoted as a word (`"he"`).
   The pages about one user's own machine (`PERSONAL`) are not held to it: they leave the
   tree with what they describe, and an entry that names no page fails.

A rule that starts firing on prose is a bug in the rule, not a reason to loosen the page.
"""

import json
import re
import tomllib
import unittest
from pathlib import Path

from keel import actions, atlas, cli, packs, settings
from tests import owner_words
from tests.helpers import left_out

ROOT = Path(__file__).resolve().parent.parent
ATLAS = ROOT / "docs" / "atlas"

# Backtick spans only: a repo path in prose is not the test's business.
BACKTICKED = re.compile(r"`([^`\n]+)`")
PLACEHOLDER = re.compile(r"""[\s$*<>?|"']""")
SKIP_TREES = ("state",)     # gitignored runtime state: present on a machine, absent in a clone
SPAN = re.compile(r"`[^`\n]*`")
AS_A_WORD = re.compile(r'"(?:he|his|him)"', re.I)


def pages() -> list[Path]:
    return sorted(ATLAS.glob("*.md"))


def prose() -> str:
    return "\n".join(path.read_text() for path in pages())


def top_level() -> tuple[set[str], set[str]]:
    """The repo's own top-level directories and files, minus the runtime ones."""
    dirs, files = set(), set()
    for entry in ROOT.iterdir():
        if entry.name.startswith(".") or entry.name in SKIP_TREES:
            continue
        (dirs if entry.is_dir() else files).add(entry.name)
    return dirs, files


def looks_like_a_path(text: str, dirs: set[str], files: set[str]) -> bool:
    if PLACEHOLDER.search(text) or text[:1] in ("~", "/", "."):
        return False
    if text in files:
        return True
    head = text.split("/", 1)[0]
    return "/" in text and head in dirs


class AtlasCase(unittest.TestCase):
    def setUp(self):
        self.text = prose()

    def missing(self, wanted: list[str]) -> list[str]:
        return [item for item in wanted if item not in self.text]


class NamesTest(AtlasCase):
    def test_every_module_is_named(self):
        modules = sorted(p.stem for p in (ROOT / "keel").glob("*.py") if p.stem != "__init__")
        self.assertTrue(modules, "no modules found; the test is looking in the wrong place")
        gone = self.missing([f"keel/{name}.py" for name in modules])
        self.assertEqual(gone, [], f"modules the Atlas does not name: {gone}")

    def test_the_module_map_has_the_pack_kit_s_rows(self):
        """r1.F9: c-735's parts each have a row in the start page's module map, and the
        scaffold's row names `--kit`."""
        text = (ROOT / "docs" / "atlas" / "00-start-here.md").read_text()
        rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| `")}
        for name in ("`keel/packcheck.py`", "`keel/scaffoldkit.py`", "`keel/packkit/`", "`packs/gitea/`"):
            self.assertIn(name, rows, name)
        self.assertIn("--kit", rows["`keel/scaffold.py`"])

    def test_every_script_is_named(self):
        scripts = sorted(p.name for p in (ROOT / "bin").iterdir() if p.is_file())
        self.assertTrue(scripts)
        gone = self.missing([f"bin/{name}" for name in scripts])
        self.assertEqual(gone, [], f"scripts the Atlas does not name: {gone}")

    def test_every_kb_verb_is_named(self):
        gone = self.missing([f"kb {verb.name}" for verb in cli.VERBS])
        self.assertEqual(gone, [], f"kb verbs the Atlas does not name: {gone}")

    def test_every_action_verb_is_named(self):
        verbs = (set(actions.KB_VERBS) | set(actions.HOUSE_VERBS) | set(actions.GATE_VERBS)
                 | set(actions.BOARD_VERBS) | set(actions.SETUP_VERBS))
        gone = self.missing([f"`{verb}`" for verb in sorted(verbs)])
        self.assertEqual(gone, [], f"deck action verbs the Atlas does not name: {gone}")

    def test_every_config_key_is_named(self):
        keys = tomllib.loads((ROOT / "etc" / "shipyard.example.toml").read_text())["keel"]
        gone = self.missing(sorted(keys))
        self.assertEqual(gone, [], f"[keel] keys the Atlas does not name: {gone}")

    def test_every_setting_is_named(self):
        """c-633: every key of the settings schema, in backticks."""
        gone = self.missing(sorted({f"`{s.key}`" for s in settings.SETTINGS}))
        self.assertEqual(gone, [], f"settings the Atlas does not name: {gone}")


class PathsTest(AtlasCase):
    def test_every_repo_path_in_backticks_exists(self):
        dirs, files = top_level()
        broken = []
        for path in pages():
            for span in BACKTICKED.findall(path.read_text()):
                text = span.rstrip("/")
                if not text or not looks_like_a_path(text, dirs, files):
                    continue
                if not (ROOT / text).exists() and not left_out(text):
                    broken.append(f"{path.name}: `{span}`")
        self.assertEqual(broken, [], f"paths the Atlas names that do not exist: {broken}")

    def test_the_rule_recognises_a_path_and_leaves_prose_alone(self):
        dirs, files = top_level()
        for text in ("keel/board.py", "bin/kb", "docs/layout.md", "Makefile"):
            self.assertTrue(looks_like_a_path(text, dirs, files), text)
        for text in ("kb list --json", "state/cards/<id>/", "~/.claude/skills", "and/or",
                     "options.json", "/api/state", "claude agents --json", "s.behind"):
            self.assertFalse(looks_like_a_path(text, dirs, files), text)


class IndexTest(unittest.TestCase):
    def test_the_index_and_the_files_agree(self):
        listed = [entry["slug"] for entry in json.loads((ATLAS / "index.json").read_text())]
        self.assertEqual(len(listed), len(set(listed)), "a slug is listed twice")
        on_disk = [path.stem for path in pages()]
        self.assertEqual(sorted(listed), sorted(on_disk),
                         "index.json and the files in docs/atlas disagree")

    def test_every_page_opens_with_one_title(self):
        for path in pages():
            first = path.read_text().splitlines()[0]
            self.assertTrue(first.startswith("# "), f"{path.name} does not open with a title")

    def test_the_title_matches_the_page(self):
        listed = {entry["slug"]: entry["title"]
                  for entry in json.loads((ATLAS / "index.json").read_text())}
        wrong = []
        for path in pages():
            heading = path.read_text().splitlines()[0].removeprefix("# ").strip()
            if listed.get(path.stem) != heading:
                wrong.append(f"{path.name}: index says {listed.get(path.stem)!r}, the page says {heading!r}")
        self.assertEqual(wrong, [], f"the index and the pages disagree about a title: {wrong}")

    def test_a_code_block_is_fenced(self):
        """`markdown_html` has no indented-code-block rule, so an indented block renders as
        a run-on paragraph. Fence it."""
        guilty = []
        for path in pages():
            fence, blank = False, True
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if line.startswith("```"):
                    fence = not fence
                elif not fence and blank and line.startswith("    ") and line.strip():
                    guilty.append(f"{path.name}:{number}")
                blank = not line.strip()
        self.assertEqual(guilty, [], f"indented blocks that must be fenced: {guilty}")

    def test_no_em_dashes(self):
        dash = chr(0x2014)      # spelled rather than typed, so this file obeys its own rule
        guilty = [path.name for path in pages() if dash in path.read_text()]
        self.assertEqual(guilty, [], f"em-dashes in {guilty}; use commas, colons or parentheses")


def prose_lines(text: str) -> list[tuple[int, str]]:
    """`(line, text)` for each line of a page outside its code fences, its backticked spans
    and its words quoted as words taken out."""
    out, fence = [], False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            out.append((number, AS_A_WORD.sub(" ", SPAN.sub(" ", line))))
    return out


class UserWordsTest(unittest.TestCase):
    """Rule 9 (c-699): a page that ships says "the user", never "he"."""

    def test_no_page_that_ships_says_he_for_the_user(self):
        hits = [f"{path.name}:{number}: {line.strip()[:120]}"
                for path in pages()
                for number, line in prose_lines(path.read_text())
                if owner_words.WORDS.search(line)]
        self.assertEqual(hits, [], "say the user, you or they:\n" + "\n".join(hits))

    def test_no_summary_in_the_index_says_he(self):
        said = [entry["slug"] for entry in json.loads((ATLAS / "index.json").read_text())
                if owner_words.WORDS.search(entry["title"] + " " + entry["summary"])]
        self.assertEqual(said, [], f"index.json says he, his or him for: {said}")

    def test_code_and_a_quoted_word_are_not_prose(self):
        text = 'The kind is `his`, spelled `by = "him"`.\n```\nwhat he hears\n```\nNever "he".\nOnly his tap.\n'
        said = [number for number, line in prose_lines(text) if owner_words.WORDS.search(line)]
        self.assertEqual(said, [6])


class VocabularyTest(AtlasCase):
    """`make test` exempts `docs/` from the employer grep, as history. The Atlas is not
    history, so it is held to the same term list here."""

    def test_the_atlas_names_no_employer(self):
        terms = packs.configured_drift_terms(ROOT)     # the install's too (r1.F7)
        if not terms:
            self.skipTest("no pack here carries a drift-terms list: none in the tree, and no "
                          "install named whose packs carry one")
        pattern = re.compile("|".join(terms), re.I)
        hits = []
        for path in pages():
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(hits, [], f"employer vocabulary in the Atlas: {hits}")


class RenderTest(unittest.TestCase):
    """The deck's half: the index, one rendered page, and the refusals."""

    def setUp(self):
        from tests.helpers import make_config
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))

    def test_index_carries_every_page_in_order(self):
        entries = atlas.index(self.cfg)
        self.assertEqual([e["order"] for e in entries], list(range(len(entries))))
        self.assertTrue(all(e["present"] for e in entries),
                        "a page the index lists has no file")

    def test_a_page_renders_to_a_fragment(self):
        page = atlas.page(self.cfg, "00-start-here")
        self.assertEqual(page["title"], "Start here")
        self.assertIn("<h1>", page["html"])
        self.assertNotIn("<body>", page["html"])
        self.assertNotIn("<!doctype", page["html"].lower())

    def test_a_link_to_a_sibling_page_stays_on_the_deck(self):
        page = atlas.page(self.cfg, "00-start-here")
        self.assertIn('href="?view=atlas&amp;page=10-cards-and-gates"', page["html"])
        self.assertNotIn(atlas.SENTINEL, page["html"])
        self.assertNotIn("unserved", page["html"])

    def test_no_page_renders_a_link_the_deck_will_not_serve(self):
        """An `unserved` span is the renderer saying it refused a path. In a card's context
        file that is honest; in the Atlas it is a broken link nobody wrote on purpose."""
        broken = [entry["slug"] for entry in atlas.index(self.cfg)
                  if "unserved" in atlas.page(self.cfg, entry["slug"])["html"]]
        self.assertEqual(broken, [], f"pages with a path the deck will not serve: {broken}")

    def test_an_unlisted_slug_is_refused(self):
        for slug in ("nope", "../keel.toml", "index"):
            with self.assertRaises(atlas.AtlasError):
                atlas.page(self.cfg, slug)


if __name__ == "__main__":
    unittest.main()
