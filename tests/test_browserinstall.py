"""The browser step's install (keel/browserinstall.py, c-678): whether Node is new enough,
the one background download with its progress read from the folder it fills, the sentence a
download that stopped says, and the readiness row. The tool is a fake script in a temp
directory and the browser's home is a temp folder (`KEEL_BROWSER_HOME`): nothing is
downloaded, no real `node` or `npm` is run, and each check waits for the fake to exit
before it reads, so nothing depends on timing."""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from keel import actions, browser, browserinstall, firstrun, firstrunsteps, packs, readiness

WORKS = """#!/bin/sh
mkdir -p "$KEEL_BROWSER_HOME/node_modules/playwright-core" "$KEEL_BROWSER_HOME/browsers/chromium-1"
echo "keel-browser: ready at $KEEL_BROWSER_HOME"
"""
STOPS = """#!/bin/sh
mkdir -p "$KEEL_BROWSER_HOME/browsers"
head -c 3145728 /dev/zero > "$KEEL_BROWSER_HOME/browsers/part.zip"
echo "keel-browser: the chromium download failed" >&2
exit 2
"""


# a download that is still going: it says it began, then waits to be told to end
HOLDS = """#!/bin/sh
touch "$KEEL_BROWSER_HOME/began"
while [ ! -f "$KEEL_BROWSER_HOME/go" ]; do sleep 0.05; done
mkdir -p "$KEEL_BROWSER_HOME/node_modules/playwright-core" "$KEEL_BROWSER_HOME/browsers/chromium-1"
"""


def bar(percent: int, of: str) -> str:
    """One progress line as the pinned Playwright prints it where there is no terminal
    (`getBasicDownloadProgress`: a row of ten, one line per row reached)."""
    row = percent // 10
    return f"|{chr(0x25A0) * (row * 8)}{' ' * ((10 - row) * 8)}| {percent:>3}% of {of}"


def lines(*percents: int, of: str = "151.2 MiB") -> str:
    return "\n".join(f'echo "{bar(percent, of)}"' for percent in percents)


# THE REAL DOWNLOAD, STOOD IN FOR (c-757). What `bin/keel-browser install` does, in its
# order and with its own output, stopping where the test looks: the package first (13 MB in
# the browser's folder, npm's part), then Chromium's archive, which Playwright writes to
# the system's temp folder, NOT the browser's folder, printing a line per tenth; then the
# archive is unpacked into the folder in a few seconds and FFMPEG follows.
PACKAGE = """#!/bin/sh
home="$KEEL_BROWSER_HOME"
stop() { touch "$home/at-$1"; while [ ! -f "$home/go-$1" ]; do sleep 0.05; done; }
mkdir -p "$home/node_modules/playwright-core"
head -c 13631488 /dev/zero > "$home/node_modules/playwright-core/coreBundle.js"
stop package
"""
REAL = PACKAGE + f"""echo "Downloading Chromium 141.0.7390.37 (playwright build v1194) from https://cdn.example/chromium-mac-arm64.zip"
{lines(0, 10, 20, 30, 40, 50)}
stop half
{lines(60, 70, 80, 90, 100)}
stop unpacking
echo "Chromium 141.0.7390.37 (playwright build v1194) downloaded to $home/browsers/chromium-1194"
echo "Downloading FFMPEG playwright build v1011 from https://cdn.example/ffmpeg-mac-arm64.zip"
{lines(0, 100, of="1.1 MiB")}
stop last
mkdir -p "$home/browsers/chromium-1194"
echo "keel-browser: ready at $home"
"""


def version(said: str):
    return lambda argv: subprocess.CompletedProcess(argv, 0, said, "")


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.home = self.dir / "browser"
        patch = mock.patch.dict(os.environ, {browser.HOME_VAR: str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(browserinstall.wait)
        readiness.forget()
        self.addCleanup(readiness.forget)
        self.cfg = SimpleNamespace(root=self.dir)
        self.which = mock.patch("keel.browserinstall.shutil.which", return_value="/fake/node")
        self.which.start()
        self.addCleanup(self.which.stop)
        # the real probe, which the fence stands in for everywhere else; its node is the fake below
        real = mock.patch.object(browserinstall, "probe", browserinstall.node)
        real.start()
        self.addCleanup(real.stop)
        self.ran = mock.patch("keel.browserinstall.prereqs.run", side_effect=version("v22.3.0\n"))
        self.ran.start()
        self.addCleanup(self.ran.stop)

    def tool(self, text: str) -> Path:
        path = self.dir / "bin" / "keel-browser"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)
        return path


class NodeTest(Case):
    def test_node_twenty_or_newer_passes_and_says_its_version(self):
        self.assertEqual(browserinstall.node(), {"ok": True, "said": "v22.3.0"})

    def test_an_older_node_is_named(self):
        with mock.patch("keel.browserinstall.prereqs.run", side_effect=version("v18.19.1\n")):
            found = browserinstall.node()
        self.assertFalse(found["ok"])
        self.assertEqual(found["said"], "Node.js v18.19.1 is installed, and Shipyard's browser needs 20 or newer.")
        self.assertIn("Install Node.js 20 or newer", found["fix"])

    def test_no_node_is_named(self):
        with mock.patch("keel.browserinstall.shutil.which", return_value=None):
            found = browserinstall.node()
        self.assertEqual((found["ok"], found["said"]), (False, "Node.js is not installed on this computer."))


class InstallTest(Case):
    def test_nothing_installed_and_nothing_asked_is_waiting(self):
        found = browserinstall.status(self.cfg)
        self.assertEqual((found["state"], found["percent"], found["of_mb"]), ("waiting", 0, None))

    def test_install_runs_the_tool_once_and_ends_ready(self):
        self.tool(WORKS)
        started = browserinstall.start(self.cfg)
        self.assertEqual(started["install"]["state"], "downloading")
        browserinstall.wait()
        found = browserinstall.status(self.cfg)
        self.assertEqual((found["state"], found["percent"]), ("ready", 100))
        self.assertEqual(found["said"], "Shipyard's browser is installed.")

    def test_a_download_that_stopped_says_what_and_how_much_arrived(self):
        self.tool(STOPS)
        browserinstall.start(self.cfg)
        browserinstall.wait()
        found = browserinstall.status(self.cfg)
        self.assertEqual(found["state"], "failed")
        self.assertEqual(found["said"], "The download stopped: the chromium download failed.")
        self.assertEqual((found["received_mb"], found["percent"]), (0, None), "the log named no size: none is made up")

    def test_try_again_runs_it_again(self):
        self.tool(STOPS)
        browserinstall.start(self.cfg)
        browserinstall.wait()
        self.tool(WORKS)
        browserinstall.start(self.cfg)
        browserinstall.wait()
        self.assertEqual(browserinstall.status(self.cfg)["state"], "ready")

    def held(self):
        """A download in flight, and the way to let it end."""
        self.tool(HOLDS)
        browserinstall.start(self.cfg)
        self.addCleanup(lambda: (self.home / "go").write_text(""))
        while not (self.home / "began").exists():       # the tool runs only after the shell wrote its pid
            time.sleep(0.01)

    def test_a_download_in_flight_is_not_started_twice(self):
        self.held()
        with self.assertRaisesRegex(browserinstall.SetupError, "already downloading"):
            browserinstall.start(self.cfg)
        self.assertEqual(browserinstall.status(self.cfg)["said"], "Getting the installer. The download starts in a moment.")

    def test_a_deck_that_restarted_still_sees_the_download_by_its_pid_file(self):
        """The shell wrote its own pid before the tool ran; another process (the deck after a
        restart) finds the download by that pid AND its command line (review F7)."""
        self.held()
        mine = list(browserinstall._procs)
        browserinstall._procs.clear()                   # as a new deck process: no child of its own
        self.addCleanup(lambda: browserinstall._procs.extend(mine))
        self.assertEqual(int(browserinstall.pid_path().read_text()), mine[0].pid)
        self.assertTrue(browserinstall.running())
        self.assertEqual(browserinstall.status(self.cfg)["state"], "downloading")

    def test_a_stale_pid_file_naming_a_live_foreign_process_is_no_download(self):
        """A reboot or a kill mid-download leaves the file behind, and its pid is reused by
        some other process: that is not the installer, and Install is not pinned shut."""
        self.tool(WORKS)
        self.home.mkdir(parents=True)
        browserinstall.pid_path().write_text(str(os.getpid()))      # a live process that is not the installer
        self.assertEqual(browserinstall.status(self.cfg)["state"], "waiting")
        self.assertFalse(browserinstall.pid_path().exists(), "the stale file is cleared")
        browserinstall.pid_path().write_text(str(os.getpid()))
        browserinstall.start(self.cfg)                              # not refused
        browserinstall.wait()
        self.assertEqual(browserinstall.status(self.cfg)["state"], "ready")

    def test_a_tool_that_ends_at_once_leaves_no_pid_file_behind(self):
        """The file was once written after the shell had already removed it."""
        self.tool(STOPS)
        browserinstall.start(self.cfg)
        browserinstall.wait()
        self.assertFalse(browserinstall.pid_path().exists())
        self.assertEqual(browserinstall.status(self.cfg)["state"], "failed")

    def test_a_download_whose_process_is_gone_is_not_in_flight(self):
        self.home.mkdir(parents=True)
        browserinstall.pid_path().write_text("not a pid")
        self.assertEqual(browserinstall.status(self.cfg)["state"], "waiting")

    def test_without_node_nothing_is_started(self):
        self.tool(WORKS)
        with mock.patch("keel.browserinstall.shutil.which", return_value=None):
            with self.assertRaisesRegex(browserinstall.SetupError, "Node.js is not installed"):
                browserinstall.start(self.cfg)
        self.assertFalse(browserinstall.log_path().exists())

    def test_an_archive_is_named_by_the_words_before_its_version(self):
        self.assertEqual(browserinstall.name_of("Chromium 141.0.7390.37 (playwright build v1194)"), "Chromium")
        self.assertEqual(browserinstall.name_of("Chromium Headless Shell 141.0.7390.37 (playwright build v1194)"),
                         "Chromium Headless Shell")
        self.assertEqual(browserinstall.name_of("FFMPEG playwright build v1011"), "FFMPEG")

    def test_an_archive_the_installer_began_again_counts_from_its_start(self):
        """Playwright tries a failed archive again from another address, from nothing."""
        again = ["Downloading Chromium 141 (playwright build v1) from https://a.example/c.zip", bar(70, "151.2 MiB"),
                 "Downloading Chromium 141 (playwright build v1) from https://b.example/c.zip", bar(10, "151.2 MiB")]
        self.assertEqual(browserinstall.progress(again)["percent"], 10)


class ProgressTest(Case):
    """c-757: on the first teammate's setup the download read 0, then 3, then done. The
    percent was the browser's folder against 400 MB, and the archive is not downloaded into
    that folder: the 13 MB package is 3%, and it stayed 3% for the whole download."""

    def at(self, point: str) -> dict:
        """The status once the stand-in has reached `point`; it goes on when the test ends
        or asks for the next point."""
        while not (self.home / f"at-{point}").exists():
            time.sleep(0.01)
        found = browserinstall.status(self.cfg)
        (self.home / f"go-{point}").write_text("")
        return found

    def test_the_percent_follows_the_download_and_never_jumps_or_passes_its_end(self):
        self.tool(REAL)
        browserinstall.start(self.cfg)
        package, half, unpacking, last = (self.at(point) for point in ("package", "half", "unpacking", "last"))
        browserinstall.wait()
        done = browserinstall.status(self.cfg)
        self.assertEqual([found["state"] for found in (package, half, unpacking, last, done)],
                         ["downloading"] * 4 + ["ready"])
        self.assertEqual([found["percent"] for found in (package, half, unpacking, last, done)],
                         [None, 50, 99, 99, 100], "the package is not 3% of anything")
        self.assertEqual(package["said"], "Getting the installer. The download starts in a moment.")
        self.assertEqual(half["said"], "Downloading Chromium: 50% of 151.2 MiB")
        self.assertEqual(unpacking["said"], "Unpacking Chromium")
        self.assertEqual((half["received_mb"], half["of_mb"]), (75, 151))

    def test_a_download_that_stopped_part_way_says_how_far_it_was(self):
        self.tool(REAL.split("stop half")[0] + 'echo "keel-browser: the chromium download failed" >&2\nexit 2\n')
        browserinstall.start(self.cfg)
        self.at("package")
        browserinstall.wait()
        found = browserinstall.status(self.cfg)
        self.assertEqual(found["said"], "The download stopped: the chromium download failed. "
                                        "Chromium had reached 50% of 151.2 MiB.")
        self.assertEqual((found["state"], found["percent"]), ("failed", 50))

    def test_a_log_with_no_size_in_it_says_downloading_and_no_percent(self):
        """A downloader that prints no progress this can read: what is known, never a guess."""
        self.tool(PACKAGE + 'echo "Downloading Chromium 141 from https://cdn.example/c.zip"\nstop half\n')
        browserinstall.start(self.cfg)
        self.at("package")
        found = self.at("half")
        self.assertEqual((found["percent"], found["said"]), (None, "Downloading Chromium"))


class WiringTest(Case):
    def test_the_step_is_optional_and_sits_after_how_work_ships(self):
        ids = [step.id for step in firstrun.STEPS]
        self.assertEqual(ids[ids.index("defaults") + 1], "browser")
        step = firstrun.BY_ID["browser"]
        self.assertTrue(step.optional)
        self.assertEqual(step.headline, "Give sessions a browser to look with")
        self.assertIn("browser", packs.SETUP_AFTER)

    def test_the_step_reads_done_from_the_folder_and_carries_the_install(self):
        done, why, extra = firstrunsteps.browser_state(self.cfg, {}, None)
        self.assertEqual((done, why), (False, "Shipyard's browser is not installed"))
        self.assertEqual(extra["install"]["state"], "waiting")
        self.assertEqual(extra["node"], {"ok": True, "said": "v22.3.0"})
        self.tool(WORKS)
        browserinstall.start(self.cfg)
        browserinstall.wait()
        done, why, extra = firstrunsteps.browser_state(self.cfg, {}, None)
        self.assertEqual((done, why), (True, "Shipyard's browser is installed"))

    def test_the_readiness_row_says_whether_it_is_there(self):
        self.assertEqual(readiness.browser_row(), {"ready": False, "why": "Shipyard's browser is not installed", "step": "browser"})
        self.tool(WORKS)
        browserinstall.start(self.cfg)
        browserinstall.wait()
        self.assertTrue(readiness.browser_row()["ready"])

    def test_the_pages_verb_starts_the_download_and_refuses_without_node(self):
        """Sent as the page sends it, with the refusals the page would show."""
        self.tool(WORKS)
        loose = SimpleNamespace(root=self.dir, source=self.dir / "keel.toml")
        with self.assertRaisesRegex(actions.ActionError, "Setup edits an install only"):
            actions.act(loose, None, {"verb": "firstrun.browser.install"})
        cfg = SimpleNamespace(root=self.dir, source=self.dir / "install" / "config.toml")
        with mock.patch("keel.browserinstall.shutil.which", return_value=None):
            with self.assertRaisesRegex(actions.ActionError, "Node.js is not installed on this computer. Install Node.js 20"):
                actions.act(cfg, None, {"verb": "firstrun.browser.install"})
        self.assertFalse(browserinstall.log_path().exists(), "nothing was started")
        done = actions.act(cfg, None, {"verb": "firstrun.browser.install"})
        self.assertEqual(done["install"]["state"], "downloading")
        browserinstall.wait()
        self.assertEqual(browserinstall.status(self.cfg)["state"], "ready")


if __name__ == "__main__":
    unittest.main()
