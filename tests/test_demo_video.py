"""The demo's edit (c-571): the Remotion project under `demo/video/`, its music and
`demo/build`.

The edit's own logic is JavaScript, held by `node --test` over `demo/video/test/`: the cut
resolving against a take (and failing on a name with no box), the bed's ducking, the word
timing, the subtitles and the loudness meter. This module runs that suite, and holds what
Python can: the music's credits, what the repo must never carry (node_modules, rendered
media), and `demo/build`'s refusals, which never start a sandbox, a browser or a render.

What it covers, by file: `demo/build`; `demo/video/src/cut.js`, `shorts.js`, `mix.js`;
`demo/video/tools/edl.mjs`, `words.mjs`, `audio.mjs`, `cache.mjs`; `demo/video/src/camera.js`, `curve.js`;
`demo/video/prepare.mjs` (its `--check`, c-807); `demo/video/evidence.mjs`;
`demo/music/CREDITS.md`.

The public release leaves `demo/video/` and `demo/music/` out (`.gitattributes`, c-804), so
in that tree every test of theirs skips, and `demo/build` refuses before its other refusals
can be reached: only the live-state switch and the dry run are asked there.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "demo" / "video"
BUILD = ROOT / "demo" / "build"
NODE = shutil.which("node")
EXPORTED = "not in this tree: the public release leaves demo/video and demo/music out"
HAS_VIDEO = VIDEO.is_dir()
HAS_MUSIC = (ROOT / "demo" / "music").is_dir()


@unittest.skipUnless(HAS_VIDEO, EXPORTED)
@unittest.skipUnless(NODE, "no node on this machine")
class EditLogicTest(unittest.TestCase):
    def test_the_edit_suite_passes_under_node(self):
        done = subprocess.run([NODE, "--test", "--test-reporter=tap", "test/edit.test.mjs", "test/short.test.mjs"], cwd=VIDEO, capture_output=True,
                              text=True, timeout=120, env={**os.environ, "NO_COLOR": "1"})
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-2000:])
        self.assertIn("# fail 0", done.stdout)


@unittest.skipUnless(HAS_VIDEO and HAS_MUSIC, EXPORTED)
class MusicTest(unittest.TestCase):
    def test_the_bed_is_committed_with_its_track_source_and_licence(self):
        credits = (ROOT / "demo" / "music" / "CREDITS.md").read_text()
        self.assertTrue((ROOT / "demo" / "music" / "the-space-is-big.mp3").is_file())
        for needed in ("The space is big", "Komiku", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/",
                       "https://archive.org/details/"):
            self.assertIn(needed, credits)

    def test_the_cut_plays_the_file_the_credits_name(self):
        mix = (VIDEO / "src" / "mix.js").read_text()
        self.assertIn('file: "music/the-space-is-big.mp3"', mix)


@unittest.skipUnless(HAS_VIDEO, EXPORTED)
class RepoContentTest(unittest.TestCase):
    def test_dependencies_and_rendered_media_stay_out_of_git(self):
        ignored = (VIDEO / ".gitignore").read_text().split()
        for path in ("node_modules/", "public/", "out/"):
            self.assertIn(path, ignored)
        lock = json.loads((VIDEO / "package-lock.json").read_text())
        self.assertEqual(lock["packages"][""]["dependencies"]["remotion"], "4.0.529")


class BuildRefusalTest(unittest.TestCase):
    def run_build(self, *argv, env=None):
        return subprocess.run([sys.executable, str(BUILD), *argv], capture_output=True, text=True,
                              env={**os.environ, **(env or {})}, timeout=60)

    def test_refuses_the_live_state_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_build("--out", tmp, "--home", tmp, env={"KEEL_LIVE_STATE": "1"})
        self.assertEqual(done.returncode, 2)
        self.assertIn("never runs against the live board", done.stderr)

    @unittest.skipUnless(HAS_VIDEO, EXPORTED)
    def test_refuses_a_sandbox_recorded_halfway(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".keel-sandbox").write_text("")
            (home / "recordings").mkdir()
            (home / "recordings" / "index.json").write_text(json.dumps({"version": 1, "scenes": {
                "01-opening": {"takes": [], "kept": "take-1"}, "02-checkin": {"takes": [], "kept": None}}}))
            done = self.run_build("--out", str(home / "out"), "--home", str(home))
        self.assertEqual(done.returncode, 1)
        self.assertIn("scenes 01 are kept and the rest are not", done.stderr)

    @unittest.skipUnless(HAS_VIDEO, EXPORTED)
    def test_recording_needs_the_users_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".keel-sandbox").write_text("")
            done = self.run_build("--out", str(home / "out"), "--home", str(home))
        self.assertEqual(done.returncode, 1)
        self.assertIn("recording needs the user's lines", done.stderr)

    def test_a_dry_run_plays_the_day_in_the_scripts_order_and_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "sandbox"
            voice = Path(tmp) / "voice"
            voice.mkdir()
            for n in range(1, 5):
                (voice / f"line-{n}.wav").write_bytes(b"")
            done = self.run_build("--out", str(Path(tmp) / "out"), "--home", str(home), "--voice", str(voice), "--dry-run")
            self.assertFalse(home.exists(), "a dry run builds nothing")
        self.assertEqual(done.returncode, 0, done.stderr)
        order = [line.split("demo/scenes/record ")[1].split()[0] for line in done.stdout.splitlines()
                 if "demo/scenes/record " in line and "--sweep" not in line]
        self.assertEqual(order, ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11"])
        seeds = [line.split("demo/seed ")[1] for line in done.stdout.splitlines() if "demo/seed " in line]
        self.assertEqual(seeds, ["morning", "breaks", "evening"])
        self.assertIn("card=c-DRYRUN", done.stdout)
        self.assertIn("node render.mjs --out", done.stdout)

    def test_a_short_cut_reaches_every_edit_step_and_the_help_names_its_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_build("--out", str(Path(tmp) / "out"), "--home", str(Path(tmp) / "sb"), "--voice", tmp,
                                  "--edit-only", "--dry-run", "--cut", "short-01")
        self.assertEqual(done.returncode, 0, done.stderr)
        edits = [line for line in done.stdout.splitlines() if "node " in line]
        self.assertEqual([line.split("node ")[1].split()[0] for line in edits], ["prepare.mjs", "render.mjs", "evidence.mjs"])
        self.assertTrue(all(line.endswith("--cut short-01") for line in edits), edits)
        helped = self.run_build("--help").stdout
        self.assertIn("`short-01` reuses the film's line-1.wav", helped)

    def test_an_unknown_cut_is_refused_before_anything_is_set_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "sb"
            done = self.run_build("--out", str(Path(tmp) / "out"), "--home", str(home), "--cut", "short-1")
            self.assertFalse(home.exists())
        self.assertEqual(done.returncode, 2)
        self.assertIn("invalid choice: 'short-1'", done.stderr)

    @unittest.skipUnless(HAS_VIDEO, EXPORTED)
    def test_the_builds_cuts_are_the_edits(self):
        shorts = re.findall(r'^  "(short-\d+)": \{', (VIDEO / "src" / "shorts.js").read_text(), re.M)
        build = re.search(r"^CUTS = \((.*)\)$", BUILD.read_text(), re.M).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', build), ["film", *shorts])

    @unittest.skipUnless(HAS_VIDEO, EXPORTED)
    def test_the_edit_and_the_seed_agree_on_the_day(self):
        seeded = re.search(r"^DAY_VERSION = (\d+)$", (ROOT / "demo" / "seeding" / "day.py").read_text(), re.M).group(1)
        cut = re.search(r"^export const DAY = (\d+);$", (VIDEO / "src" / "cut.js").read_text(), re.M).group(1)
        self.assertEqual(seeded, cut)


if __name__ == "__main__":
    unittest.main()
