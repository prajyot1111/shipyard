"""The icons (c-518): the picked glyphs, what is derived from them, and where each is served.

The PNGs are committed, so the risk is not a broken build but a drift: a manifest naming a
file that is not there or is not the size it claims, a served path that is not on the
server's list, or a derived tile that no longer matches its source. Each test reads the
files themselves.
"""

import base64
import json
import struct
import unittest
from pathlib import Path

from keel import serve
from app.icons import build
from tests import test_serve

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
VOICE = ROOT / "segments" / "voice" / "app"


def png_size(path: Path) -> tuple[int, int]:
    """The width and height from a PNG's IHDR, the one place a PNG says its size."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


class Derived(unittest.TestCase):
    """What build.py writes as SVG is exactly what it would write now: nothing hand-edited."""

    def test_every_committed_tile_is_what_the_build_derives(self):
        for mark, (where, names) in build.APPS.items():
            self.assertEqual((where / names["tile"]).read_text(), build.tile(mark), mark)
            self.assertEqual((where / names["maskable"]).read_text(),
                             build.tile(mark, rounded=False, scale=build.MASKABLE), mark)
        for mark, name in build.GLYPHS.items():
            self.assertEqual((APP / "icons" / name).read_text(), build.bare(mark), name)


    def test_every_png_the_build_names_exists_at_its_size(self):
        for mark, (where, names) in build.APPS.items():
            for key, size in (("192", 192), ("512", 512), ("m192", 192), ("m512", 512), ("180", 180), ("32", 32)):
                self.assertEqual(png_size(where / names[key]), (size, size), f"{mark} {key}")


class Build(unittest.TestCase):
    """The build's own path: a browser that fails, or answers garbage, writes nothing."""

    def outputs(self) -> dict[Path, bytes]:
        paths = [where / name for where, names in build.APPS.values() for name in names.values()]
        paths += [build.HERE / name for name in build.GLYPHS.values()]
        return {path: path.read_bytes() for path in paths}

    def run_with(self, script: str) -> int:
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "keel-browser"
            fake.write_text("#!/bin/sh\n" + script + "\n")
            fake.chmod(0o755)
            with mock.patch.object(build, "BROWSER", fake), mock.patch("sys.stderr"):
                return build.main()

    def test_a_source_the_build_cannot_cut_writes_nothing(self):
        """A ground-coloured shape below the top level is refused before any file is touched."""
        from unittest import mock
        before = self.outputs()
        nested = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><g>'
                  '<rect width="4" height="4" fill="#0E1726"/></g></svg>')
        real = Path.read_text
        with mock.patch.object(Path, "read_text", lambda path, *a, **k: nested if path.name == "harbor.svg" else real(path, *a, **k)):
            self.assertEqual(self.run_with(self.echo_pngs()), 1)
        self.assertEqual(self.outputs(), before)

    def echo_pngs(self) -> str:
        """A fake browser that answers with a valid PNG for every icon the build asks for."""
        one = "data:image/png;base64," + base64.b64encode((build.APPS["keel"][0] / "keel-32.png").read_bytes()).decode()
        return "echo '" + json.dumps([one] * len(build.jobs())) + "'"

    def test_a_failed_or_garbled_render_writes_nothing(self):
        before = self.outputs()
        for script in ("echo broken >&2; exit 3", "echo not-json", "echo '[\"data:image/png;base64,AAAA\"]'"):
            self.assertEqual(self.run_with(script), 1, script)
            self.assertEqual(self.outputs(), before, script)

    def test_an_ico_header_names_each_png_at_its_offset(self):
        blob = build.ico([(16, b"a" * 5), (32, b"b" * 7)])
        self.assertEqual(blob[:6], struct.pack("<HHH", 0, 1, 2))
        self.assertEqual(blob[6:22], struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, 5, 38))
        self.assertEqual(blob[22:38], struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, 7, 43))
        self.assertEqual(blob[38:], b"a" * 5 + b"b" * 7)


class Manifests(unittest.TestCase):
    def check(self, manifest: Path, base: Path, url_root: str):
        doc = json.loads(manifest.read_text())
        purposes = set()
        for icon in doc["icons"]:
            src = icon["src"]
            path = base / (src[len(url_root):] if src.startswith(url_root) else src)
            self.assertTrue(path.is_file(), f"{manifest.name}: {src}")
            if icon["type"] == "image/png":
                w, h = png_size(path)
                self.assertEqual(icon["sizes"], f"{w}x{h}", src)
                purposes.add((icon["purpose"], w))
        self.assertTrue({("any", 192), ("any", 512), ("maskable", 192), ("maskable", 512)} <= purposes,
                        manifest.name)
        return doc

    def test_the_deck_manifest_has_real_icons(self):
        doc = self.check(APP / "manifest.json", APP, "/")
        for icon in doc["icons"]:
            self.assertIn(icon["src"], serve.APP_FILES, icon["src"])

    def test_bosuns_manifest_is_scoped_to_the_console_and_served(self):
        doc = self.check(APP / "console.webmanifest", APP, "/")
        self.assertEqual((doc["scope"], doc["start_url"]), ("/console", "/console"))
        self.assertEqual(serve.APP_FILES["/console.webmanifest"], "console.webmanifest")
        for icon in doc["icons"]:
            self.assertIn(icon["src"], serve.APP_FILES, icon["src"])


class Serving(unittest.TestCase):
    def test_every_icon_file_is_served_and_every_served_icon_exists(self):
        on_disk = {p.name for p in (APP / "icons").iterdir() if p.is_file() and p.suffix != ".py"}
        self.assertEqual(set(serve.ICONS), on_disk)
        for route, name in serve.APP_FILES.items():
            if route.startswith("/icons/") or route == "/favicon.ico":
                self.assertTrue((APP / name).is_file(), route)


class Served(test_serve.ServerCase):
    """The icons over HTTP, as a browser asks for them."""

    def test_the_favicon_icons_and_bosuns_manifest_answer_with_their_types(self):
        for path, kind in (("/favicon.ico", "image/vnd.microsoft.icon"), ("/icons/keel-192.png", "image/png"),
                           ("/icons/keel-glyph.svg", "image/svg+xml"),
                           ("/console.webmanifest", "application/manifest+json")):
            status, ctype, body = self.fetch(path)
            self.assertEqual((status, ctype.split(";")[0]), (200, kind), path)
            self.assertTrue(body, path)


if __name__ == "__main__":
    unittest.main()
