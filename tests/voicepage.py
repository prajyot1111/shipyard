"""The voice page's files, read the way the browser loads them, for the voice page's tests.

The page is several scripts sharing one namespace (`window.Voice`), loaded in the order
`segments/voice/app/index.html` lists them (VP-6). A grep that is about the page's behaviour
reads all of them as one text, so moving a function between files does not silently turn a
rule into a test that finds nothing; `tests/fixtures/voice-listen.js` is handed the same
list, in the same order.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "segments" / "voice" / "app"
COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
COMMENT_LINE = re.compile(r"^\s*//.*$", re.M)


def markup() -> str:
    return (APP / "index.html").read_text(encoding="utf-8")


def scripts() -> list[Path]:
    """The page's own scripts, in load order. `/voice/flags.js` is the gateway's, not a file
    here, so an absolute src is left out."""
    found = re.findall(r'<script src="([^"]+)"', markup())
    return [APP / src for src in found if not src.startswith("/")]


def raw_script() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in scripts())


def script() -> str:
    """Every page script with its comments stripped: the comments quote the code the greps
    look for."""
    return COMMENT_LINE.sub("", COMMENT_BLOCK.sub("", raw_script()))


def css() -> str:
    return COMMENT_BLOCK.sub("", (APP / "app.css").read_text(encoding="utf-8"))


def function_body(name: str, args: str = r"[^)]*") -> str | None:
    """The body of `function name(...) { ... }`, braces counted, or None."""
    text = script()
    found = re.search(r"function %s\(%s\)\s*\{" % (re.escape(name), args), text)
    if not found:
        return None
    depth, i = 1, found.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[found.end():i - 1]
