"""Render every app icon from the glyphs he picked (c-518), and write them where they are served.

Run it from anywhere: `python3 app/icons/build.py`. The glyphs in `app/icons/src/` are
the canvas's own files, kept exactly as they were picked (board "Icons: round 2"), and
they are the ONLY drawing: every tile, bare glyph, maskable, PNG and favicon here is derived from
them, never redrawn. Change a mark by replacing its source and running this again.

The PNGs are COMMITTED: the server is stdlib-only and has no rasteriser, and a phone that
installs an app must get the same icon every time. They are rendered by `bin/keel-browser`
drawing each tile onto a canvas, which keeps the rounded tile's corners transparent (a
screenshot would paint them white).
"""

import base64
import json
import re
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SRC = HERE / "src"
VOICE = ROOT / "segments" / "voice" / "app" / "icons"
BROWSER = ROOT / "bin" / "keel-browser"

# Each mark: its glyph colour and the ground of its tile (the canvas README).
MARKS = {
    "keel": ("#5BD6C0", "#101418"),
    "harbor": ("#F2C879", "#0E1726"),
    "voice": ("#F2C879", "#0E1726"),
    "bosun": ("#A59BFF", "#0B0B0C"),
    "bosun-small": ("#A59BFF", "#0B0B0C"),
}
RADIUS = 14         # an app tile's corner, on the 64 grid
MASKABLE = 0.7      # the glyph's scale on a maskable tile: inside the 80% safe circle
SMALL = 24          # at this size and below Bosun drops its ring (bosun-small)

# The installable apps: which mark, where its files go, and what each file is called.
APPS = {
    "keel": (HERE, {"tile": "keel-tile.svg", "maskable": "keel-maskable.svg",
                    "192": "keel-192.png", "512": "keel-512.png",
                    "m192": "keel-maskable-192.png", "m512": "keel-maskable-512.png",
                    "180": "keel-180.png", "32": "keel-32.png", "ico": "keel.ico"}),
    "bosun": (HERE, {"tile": "bosun-tile.svg", "maskable": "bosun-maskable.svg",
                     "192": "bosun-192.png", "512": "bosun-512.png",
                     "m192": "bosun-maskable-192.png", "m512": "bosun-maskable-512.png",
                     "180": "bosun-180.png", "32": "bosun-32.png", "ico": "bosun.ico"}),
    # Voice keeps the names its manifest and page already use.
    "voice": (VOICE, {"tile": "voice-mark.svg", "maskable": "voice-mark-maskable.svg",
                      "192": "icon-192.png", "512": "icon-512.png",
                      "m192": "icon-maskable-192.png", "m512": "icon-maskable-512.png",
                      "180": "apple-touch-icon.png", "32": "favicon-32.png",
                      "ico": "favicon.ico"}),
}
# In the app a mark has NO tile (c-518, his send-back): a page paints the bare glyph in its
# own palette through a CSS mask, so each mark's alpha is all that matters. The header's
# hull and fin, the deck's Voice button, Harbor beside his name, Bosun's small mark for BO-1.
GLYPHS = {mark: f"{mark}-glyph.svg" for mark in MARKS}
SVG_NS = "http://www.w3.org/2000/svg"


def glyph(mark: str) -> str:
    """The inside of the source SVG: its drawing, without the outer element."""
    text = (SRC / f"{mark}.svg").read_text(encoding="utf-8")
    return re.sub(r"^\s*<svg[^>]*>|</svg>\s*$", "", text.strip())


def tile(mark: str, *, rounded: bool = True, scale: float = 1.0) -> str:
    """The mark on its ground: rounded for a tile, full bleed for maskable and iOS."""
    ink, ground = MARKS[mark]
    rx = f' rx="{RADIUS}"' if rounded else ""
    fit = "" if scale == 1.0 else f' transform="translate(32 32) scale({scale}) translate(-32 -32)"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<rect width="64" height="64"{rx} fill="{ground}"/>'
            f'<g color="{ink}"{fit}>{glyph(mark)}</g></svg>\n')


def bare(mark: str) -> str:
    """The glyph with no ground: what the source cuts in its ground colour (the lighthouse's
    band) becomes a real hole, through an SVG mask, so it reads on any page."""
    ground = MARKS[mark][1].lower()
    ET.register_namespace("", SVG_NS)
    root = ET.fromstring((SRC / f"{mark}.svg").read_text(encoding="utf-8"))
    cuts = [child for child in root if (child.get("fill") or "").lower() == ground]
    if any((el.get("fill") or "").lower() == ground for el in root.iter() if el not in cuts):
        raise ValueError(f"{mark}: a ground-coloured shape below the top level is not a cut this knows")
    for cut in cuts:
        root.remove(cut)
        cut.set("fill", "black")
    body = "".join(ET.tostring(child, encoding="unicode") for child in root).replace(f' xmlns="{SVG_NS}"', "")
    if not cuts:
        return f'<svg xmlns="{SVG_NS}" viewBox="0 0 64 64">{body}</svg>\n'
    holes = "".join(ET.tostring(cut, encoding="unicode") for cut in cuts).replace(f' xmlns="{SVG_NS}"', "")
    return (f'<svg xmlns="{SVG_NS}" viewBox="0 0 64 64"><defs><mask id="cut">'
            f'<rect width="64" height="64" fill="white"/>{holes}</mask></defs>'
            f'<g mask="url(#cut)">{body}</g></svg>\n')


def small(mark: str) -> str:
    """The mark a size of 24px or below draws: Bosun without its ring."""
    return f"{mark}-small" if f"{mark}-small" in MARKS else mark


def jobs() -> list[tuple[Path, str, int]]:
    """Every PNG to render: (where it goes, the SVG it is drawn from, its size)."""
    out = []
    for mark, (where, names) in APPS.items():
        full, mask, square = tile(mark), tile(mark, rounded=False, scale=MASKABLE), tile(mark, rounded=False)
        out += [(where / names["192"], full, 192), (where / names["512"], full, 512),
                (where / names["m192"], mask, 192), (where / names["m512"], mask, 512),
                # iOS masks and rounds this itself, so it is full bleed and not maskable
                (where / names["180"], square, 180), (where / names["32"], full, 32),
                (where / f"{mark}.ico-16.png", tile(small(mark)), 16)]
    return out


def render(items: list[tuple[str, int]]) -> list[bytes]:
    """Draw each SVG onto a canvas of its size in one browser run; the PNG bytes."""
    script = ("(async () => { const out = []; for (const [svg, n] of %s) {"
              " const c = document.createElement('canvas'); c.width = n; c.height = n;"
              " const img = new Image(); img.src = 'data:image/svg+xml,' + encodeURIComponent(svg);"
              " await img.decode(); c.getContext('2d').drawImage(img, 0, 0, n, n);"
              " out.push(c.toDataURL('image/png')); } return out; })()") % json.dumps(items)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "blank.html"
        page.write_text("<!doctype html><title>icons</title>", encoding="utf-8")
        run = subprocess.run([str(BROWSER), "eval", page.as_uri(), script, "--settle", "0"],
                             capture_output=True, text=True, check=True)
    urls = json.loads(run.stdout)
    if len(urls) != len(items) or not all(u.startswith("data:image/png;base64,") for u in urls):
        raise ValueError(f"{len(urls)} answers for {len(items)} icons, or not PNG data")
    return [base64.b64decode(u.split(",", 1)[1], validate=True) for u in urls]


def ico(pngs: list[tuple[int, bytes]]) -> bytes:
    """A favicon.ico holding PNGs, so a browser that asks before reading the page is answered."""
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset, entries, blobs = 6 + 16 * len(pngs), b"", b""
    for size, png in pngs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        blobs += png
    return head + entries + blobs


def outputs() -> dict[Path, bytes]:
    """Every file the build writes, made in memory: the SVGs, the bare glyphs, the PNGs
    (one browser run) and the icos. Raises before anything is on disk."""
    todo = jobs()
    pngs = dict(zip((path for path, _, _ in todo), render([(svg, n) for _, svg, n in todo])))
    out = {}
    for mark, (where, names) in APPS.items():
        out[where / names["tile"]] = tile(mark).encode()
        out[where / names["maskable"]] = tile(mark, rounded=False, scale=MASKABLE).encode()
        sixteen = pngs.pop(where / f"{mark}.ico-16.png")
        out[where / names["ico"]] = ico([(16, sixteen), (32, pngs[where / names["32"]])])
    for mark, name in GLYPHS.items():
        out[HERE / name] = bare(mark).encode()
    return out | pngs


def main() -> int:
    # EVERYTHING FIRST, then the writes: a browser that fails, or a source this cannot
    # derive, leaves every committed file as it was, never new SVGs beside old PNGs.
    try:
        files = outputs()
    except subprocess.CalledProcessError as failed:
        print(f"build.py: keel-browser failed, nothing written:\n{failed.stderr}", file=sys.stderr)
        return 1
    except (ValueError, IndexError) as failed:     # a garbled render, or a source it cannot cut
        print(f"build.py: nothing written: {failed}", file=sys.stderr)
        return 1
    for path, data in files.items():
        path.write_bytes(data)
        print(f"  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
