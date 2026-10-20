"""The Atlas: this repo's own documentation, read by the deck and by an agent.

`docs/atlas/` is one markdown file per page and an `index.json` that gives the order and
the titles. The index is authoritative: a page it does not list is not served, and a page
it lists that has no file is reported rather than silently dropped, so a half-done rename
shows up instead of hiding. Because the only strings that ever reach the filesystem came
out of the index, a slug can never become a path fragment.

A page is rendered through `artifacts.markdown_html`, the same renderer a card's context
file goes through. That renderer resolves a relative path against the document's directory
and mints a token for it, but only inside the trees the deck serves, and `docs/` is not one
of them: a link from one Atlas page to the next would render as its words with "outside the
trees the deck serves" as the reason. So a link between two pages is rewritten BEFORE the
render to an absolute sentinel URL (which the renderer passes through untouched) and back
AFTER it to the deck's own Atlas route, so the reader stays on the page he is reading.
A page that wants a picture needs its directory in `artifact_roots`; none does today.

The renderer returns a whole HTML document and the deck wants a fragment to put inside its
own page, so `body_of` takes what is between the body tags. Nothing else here knows HTML.
"""

import json
import re
from pathlib import Path

from keel import artifacts
from keel.config import Config

DIRNAME = ("docs", "atlas")
INDEX = "index.json"
SUFFIX = ".md"
BODY_OPEN = "<body>"
BODY_CLOSE = "</body>"
ROUTE = "?view=atlas&amp;page="

# A host no document can legitimately name, used only between the two rewrites below.
SENTINEL = "http://atlas.invalid/"
PAGE_LINK = re.compile(r"\]\(([0-9a-z][0-9a-z-]*)\.md(?:#[\w-]*)?\)")
SENTINEL_HREF = re.compile(r'href="' + re.escape(SENTINEL) + r'([0-9a-z][0-9a-z-]*)"')


class AtlasError(Exception):
    """A slug that is not a page, or an index that cannot be read."""


def directory(cfg: Config) -> Path:
    return cfg.root.joinpath(*DIRNAME)


def index(cfg: Config) -> list[dict]:
    """The page list in its given order: slug, title, summary, order, present.

    Every entry carries `present`. The deck draws a missing page as an unreadable row
    rather than pretending it was never listed, and `tests/test_atlas.py` fails on one.
    """
    path = directory(cfg) / INDEX
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise AtlasError(f"the atlas index could not be read: {error}") from None
    if not isinstance(entries, list):
        raise AtlasError("the atlas index must be a list of pages")
    pages = []
    for order, entry in enumerate(entries):
        slug = str((entry or {}).get("slug") or "")
        if not slug:
            continue
        pages.append({"slug": slug, "title": str(entry.get("title") or slug),
                      "summary": str(entry.get("summary") or ""), "order": order,
                      "present": (directory(cfg) / (slug + SUFFIX)).is_file()})
    return pages


def page_path(cfg: Config, slug: str) -> Path:
    """The file a slug names, refusing anything the index does not list."""
    listed = {entry["slug"] for entry in index(cfg)}
    if slug not in listed:
        raise AtlasError(f"no atlas page called {slug!r}")
    path = directory(cfg) / (slug + SUFFIX)
    if not path.is_file():
        raise AtlasError(f"the atlas lists {slug!r} but the file is missing")
    return path


def body_of(document: str) -> str:
    """The fragment inside a rendered page's body, or the document when it has no body."""
    start = document.find(BODY_OPEN)
    end = document.rfind(BODY_CLOSE)
    if start < 0 or end < start:
        return document
    return document[start + len(BODY_OPEN):end]


def render(text: str, title: str, base_dir: Path, cfg: Config) -> str:
    """One page as a fragment, with its links to sibling pages pointing at the deck.

    Each table is wrapped in its own scroller: a table too wide for a phone has to scroll
    sideways by itself, or it takes the whole page with it and the deck's overflow audit
    fires on every column.
    """
    marked = PAGE_LINK.sub(lambda m: "](" + SENTINEL + m.group(1) + ")", text)
    rendered = body_of(artifacts.markdown_html(marked, title, base_dir=base_dir, cfg=cfg))
    rendered = rendered.replace("<table>", '<div class="tablewrap"><table>')
    rendered = rendered.replace("</table>", "</table></div>")
    return SENTINEL_HREF.sub(lambda m: 'href="' + ROUTE + m.group(1) + '"', rendered)


def page(cfg: Config, slug: str) -> dict:
    """`{slug, title, html}` for one page, rendered the way a card's context file is."""
    path = page_path(cfg, slug)
    entry = next(item for item in index(cfg) if item["slug"] == slug)
    return {"slug": slug, "title": entry["title"],
            "html": render(path.read_text(errors="replace"), entry["title"], path.parent, cfg)}
