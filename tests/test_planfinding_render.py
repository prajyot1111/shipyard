"""Lane FC, FC-2 and FC-3 (the page's half), run under node against the DOM stand-in.

A review outcome draws ONE card per finding: its head (severity, the member on a feature
card, `path:line` linked, the claim), the code the server pulled from the worktree with the
finding's own lines marked, why it holds, the comment in a field he can rewrite, and the
choice. The desk puts the code left and the comment right; the phone stacks them and folds
a low finding to its head. Keeping his words is the edit mark Approve posts.

Every code block the plan pages draw is coloured by highlight.js, vendored and loaded only
when a page has code: a document without any never asks for it. The payload is built by the
same parser, lint and excerpt reader the route uses; every pull request is invented.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import planexcerpt, planformat, planlint, planstate, serve

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SAMPLE = (FIXTURES / "review-sample.md").read_text()
FEATURE = (FIXTURES / "review-feature-sample.md").read_text()
PLAN = (FIXTURES / "plan-sample.md").read_text()
LOADER = ["import settings", "", "def page(rows):", "    list = []", "    for row in rows:",
          "        list.append(row)", "    return list", "", "CAP = settings.page_size()  # read at import"]


def lines_for(block: dict) -> dict:
    """An excerpt as the server answers one, with invented code around the finding."""
    first = max(1, block["start"] - 4)
    count = block["end"] + 4 - first + 1
    body = [LOADER[(n + first) % (len(LOADER) - 1)] for n in range(count)]
    body[block["start"] - first] = LOADER[-1]          # the finding's own line
    lang = planexcerpt.lang_of(block["path"])
    return {"first": first, "start": block["start"], "end": block["end"], "lines": body, "lang": lang,
            "total": 200}


def payload(text: str, kind: str = "review", space: str = "work") -> dict:
    doc = planformat.parse(text, "context.md" if kind == "review" else "plan.md")
    planexcerpt.attach(doc, {b["id"]: lines_for(b) for b in planformat.all_blocks(doc["blocks"])
                             if b["type"] == "finding"})
    state = planstate.state_of([], "outcome")
    return {"card": {"id": "c-900", "title": "t", "space": space, "stage": "review", "repo": "api",
                     "plan_ref": "/x/p.md", "prs": {"api#4150": "https://example.invalid/api/pr/4150",
                                                     "web#2200": "https://example.invalid/web/pr/2200",
                                                     "pr": "https://example.invalid/api/pr/4150"}},
            "gate": "outcome", "doc_name": "outcome", "doc": doc, "lint": planlint.lint(doc),
            "state": state, "round": planstate.summary(doc, state), "docs": ["outcome"], "empty": None,
            "cost": {"bytes": len(text)}}


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class FindingRenderTest(unittest.TestCase):
    def run_node(self, payloads: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payloads.json"
            path.write_text(json.dumps(payloads))
            done = subprocess.run(["node", str(FIXTURES / "plan-finding.js"), str(ROOT / "app"), str(path)],
                                  capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_one_card_per_finding_its_code_pulled_and_marked_its_comment_his_to_edit(self):
        plain = "---\nkind: plan\n---\n# t\n\nNothing here but words.\n\n## Goal\n\nWords.\n"
        got = self.run_node({"review": payload(SAMPLE), "feature": payload(FEATURE),
                             "plan": payload(PLAN, "plan", "personal"), "words": payload(plain, "plan")})
        self.assertEqual(got, {"ok": True}, json.dumps(got, indent=1))


class ThemeContrastTest(unittest.TestCase):
    """FC-3: every syntax colour reads at 4.5:1 or better on the code background, and on
    both diff tints, in BOTH space palettes."""

    SCOPES = ("kw", "str", "com", "num", "fn", "attr")

    def palette(self, space: str) -> dict:
        css = (ROOT / "app" / "ui.css").read_text()
        block = re.sub(r"/\*.*?\*/", "", css.split(f'html[data-mode="{space}"]{{', 1)[1].split("}", 1)[0], flags=re.S)
        out = {}
        for part in block.split(";"):
            if ":" in part and part.strip().startswith("--"):
                name, value = part.split(":", 1)
                out[name.strip()] = value.strip()
        return out

    def rule(self, selector: str) -> str:
        css = (ROOT / "app" / "ui.plan.css").read_text()
        return css.split(selector + "{", 1)[1].split("}", 1)[0]

    def token(self, text: str, palette: dict) -> str:
        name = text.split("color:var(", 1)[1].split(")", 1)[0].split(",")[0].strip()
        return palette[name]


    def test_every_colour_meets_four_and_a_half_to_one_in_both_palettes(self):
        for space in ("work", "personal"):
            palette = self.palette(space)
            base = hex_rgb(palette["--s2"])
            grounds = {"code": base,
                       "added": mix(hex_rgb(palette["--good"]), base, self.tint("add")),
                       "removed": mix(hex_rgb(palette["--crit"]), base, self.tint("del")),
                       "marked": mix(hex_rgb(palette["--accent"]), base, self.tint("mark"))}
            for scope in self.SCOPES + ("plain",):
                colour = hex_rgb(self.token(self.rule(f".hl-{scope}") if scope != "plain" else
                                            self.rule(".pcode-pre"), palette))
                for ground, rgb in grounds.items():
                    ratio = contrast(colour, rgb)
                    self.assertGreaterEqual(ratio, 4.5, f"{space} {scope} on {ground}: {ratio:.2f}")

    def tint(self, kind: str) -> float:
        """The percentage a diff or marked line mixes its tone into the code background."""
        text = self.rule({"add": ".pcode .cl.add", "del": ".pcode .cl.del", "mark": ".pcode .cl.hit"}[kind])
        return float(text.split("in srgb,", 1)[1].split("%", 1)[0].split()[-1]) / 100


def hex_rgb(value: str) -> tuple:
    value = value.strip().lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(tone: tuple, base: tuple, share: float) -> tuple:
    return tuple(round(t * share + b * (1 - share)) for t, b in zip(tone, base))


def luminance(rgb: tuple) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple, b: tuple) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ServedTest(unittest.TestCase):
    """highlight.js is vendored and served, never fetched from a CDN, and never on a page's
    first load: the plan page's shell does not name it."""

    def test_the_vendored_files_are_served_and_named_in_the_readme(self):

        readme = (ROOT / "app" / "vendor" / "README.md").read_text()
        for name in ("core.min.js", "python.min.js", "javascript.min.js", "xml.min.js", "sql.min.js",
                     "yaml.min.js", "json.min.js", "bash.min.js"):
            paths = [p for p in serve.APP_FILES if p.endswith("/" + name) and "/vendor/highlight/" in p]
            self.assertEqual(len(paths), 1, name)
            self.assertTrue((ROOT / "app" / serve.APP_FILES[paths[0]]).is_file(), name)
        self.assertIn("highlight.js 11.11.1", readme)
        self.assertIn("BSD-3-Clause", readme)


if __name__ == "__main__":
    unittest.main()
