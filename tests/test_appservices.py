"""An install's services (`keel/appservices.py`): the deck, the drain and the fetch role.

The first test is c-742's reproduction, kept: an install whose segments folder held a
segment showed "No segment is installed", because nothing ran the fetchers. The rest is
what that card added around it. `StartedTest` opens with c-747's reproduction, kept: the
drain logged "installed and started" for a service launchd had loaded and was not running.
No test here reaches a real service manager: the manager is a fake that answers as launchd
does, or the real one asked only to render.
"""

import contextlib
import io
import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import (appservices, cli, deckdigest, deckstate, doctor, drain, drainprobe, fetch,
                  readiness, restart, service)
from keel import config as config_module
from tests.test_installer import init

FETCHER = ("import json, pathlib\n"
           "pathlib.Path('summary.json').write_text(json.dumps("
           "{'tiles': [{'label': 'high tide', 'value': '04:12'}]}))\n"
           "print('1 tile')\n")


class FakeManager:
    """A service manager that answers as launchd does and runs nothing.

    `pended` holds the labels it answers for as launchd did on 2026-10-11 (c-747): a load
    succeeds and leaves the label loaded with no process (`launchctl print`: "state = not
    running", "runs = 0", "pended nondemand spawn = speculative"), and only a start, the
    kickstart, gives it one. A label in `dead` gets no process from a start either."""

    kind = service.LAUNCHD

    def __init__(self, home: Path):
        self.home, self.installed_dir = home, home / "LaunchAgents"
        self.loaded: set[str] = set()
        self.stopped: set[str] = set()
        self.pended: set[str] = set()
        self.dead: set[str] = set()
        self.runs: dict[str, int] = {}
        self.waits: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.load_code, self.load_error, self.unload_error = 0, None, None

    def files(self, item):
        return {f"{item.label}.plist": service.plist(item)}

    def primary(self, item):
        return item.label

    def write(self, item, etc):
        etc.mkdir(parents=True, exist_ok=True)
        for name, content in self.files(item).items():
            (etc / name).write_bytes(content)

    def load(self, item, etc):
        """As `service.Manager.load`: the unit is copied where the manager looks BEFORE it
        is started, so a start that fails leaves the copy behind."""
        self.installed_dir.mkdir(parents=True, exist_ok=True)
        for name in self.files(item):
            (self.installed_dir / name).write_bytes((etc / name).read_bytes())
        self.calls.append(("load", item.label))
        if self.load_error is not None:
            raise self.load_error
        if self.load_code == 0:
            self.loaded.add(item.label)
            self.stopped.discard(item.label)
            self.spawned(item.label)
        return self.load_code

    def spawned(self, label):
        """A process for a loaded label, unless launchd is holding its start back."""
        if label not in self.pended and label not in self.dead:
            self.runs[label] = self.runs.get(label, 0) + 1

    def unload(self, item, keep=False):
        """As `service.Manager.unload`: stopped, the installed copies removed, the rendered
        ones in the install's `services/` kept."""
        self.calls.append(("unload", item.label))
        if self.unload_error is not None:
            raise self.unload_error
        self.loaded.discard(item.label)
        removed = [self.installed_dir / name for name in self.files(item)]
        for path in removed:
            path.unlink(missing_ok=True)
        return removed

    def stop(self, item):
        """systemd's stop: the unit stays enabled, which `state` reads as loaded, with no pid."""
        self.stopped.add(item.label)
        self.calls.append(("stop", item.label))
        return True, "stopped"

    def resting(self, item):
        """As `service.Manager.resting` on systemd: the unit is inactive after a stop, however
        it was stopped (`systemctl --user stop` goes through no verb of Shipyard's)."""
        return item.label in self.stopped

    def start(self, item):
        """As `service.Manager.start`: a label that is not loaded is bootstrapped, and then
        kickstarted either way, which is what gives a pended one its process and leaves a
        running one alone."""
        self.calls.append(("start", item.label))
        self.loaded.add(item.label)
        self.stopped.discard(item.label)
        self.pended.discard(item.label)
        self.spawned(item.label)
        return True, f"launchctl kickstart gui/501/{item.label}"

    def running(self, label, sleep=None):
        """As `service.Manager.running`, the bounded wait for a pid, with nothing waited:
        launchd's answer here does not change between two looks."""
        self.waits.append(label)
        return self.state(label)[1]

    def state(self, label, scheduled=False):
        running = (label in self.loaded and label not in self.stopped
                   and label not in self.pended and label not in self.dead)
        return label in self.loaded, (4242 if running else None)


class InstallCase(unittest.TestCase):
    """A scratch install with one segment, `tides`, whose fetcher has never run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        self.home = Path(self.tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        self.cfg = config_module.load(self.home / "config.toml")
        self.segment = self.cfg.segments_dir / "tides"
        self.segment.mkdir(parents=True)
        (self.segment / "fetch.py").write_text(FETCHER)
        self.manager = FakeManager(Path(self.tmp.name) / "home")
        # Neither probe asks this machine: no other drain, and the fetch roles a test names.
        self.fetch_pids: list[int] = []
        for probe in (mock.patch("keel.drainprobe.refusal", return_value=None),
                      mock.patch("keel.drainprobe.fetch_pids", lambda config: list(self.fetch_pids))):
            probe.start()
            self.addCleanup(probe.stop)

    def services(self) -> dict:
        return {item.label: item for item in appservices.services(self.cfg, self.manager.home)}

    def run_service(self, verb: str, which: str | None = None) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = appservices.run(self.cfg, verb, only=which, manager=self.manager)
        return code, out.getvalue()

    def listed(self) -> dict:
        return {entry["name"]: entry for entry in deckstate.segments(self.cfg)
                if entry["name"] == "tides"}


class ReproductionTest(InstallCase):
    def test_an_installs_services_run_its_fetchers_so_its_segments_page_fills(self):
        """c-742, end to end: the install's own services, as rendered, are what run the
        segment's fetcher, and the state document the Segments page draws lists it."""
        fetching = [item for item in self.services().values()
                    if "fetch" in cli.parse_roles(item.argv[-1])]
        self.assertEqual([item.label for item in fetching], ["dev.shipyard.fetch"],
                         "no service of the install runs the fetch role")
        self.assertEqual(fetching[0].argv[-3:], ["run", "--roles", "fetch"])
        # Before its first pass the segment is listed, as not fetched: never an empty page.
        self.assertEqual({name: entry["fetched"] for name, entry in self.listed().items()},
                         {"tides": False})
        self.assertTrue(readiness.segments_row(self.cfg)["ready"])
        # One pass of that role, the one the service makes when it starts.
        self.assertEqual(fetch.once(self.cfg)["tides"], "ok")
        entry = self.listed()["tides"]
        self.assertTrue(entry["fetched"])
        self.assertEqual(entry["summary"]["tiles"], [{"label": "high tide", "value": "04:12"}])


class RenderTest(InstallCase):
    def test_the_fetch_unit_is_rendered_for_macos_and_for_linux(self):
        item = self.services()["dev.shipyard.fetch"]
        config = str(self.home / "config.toml")
        mac = service.Manager(self.manager.home, kind=service.LAUNCHD).files(item)
        self.assertEqual(list(mac), ["dev.shipyard.fetch.plist"])
        doc = plistlib.loads(mac["dev.shipyard.fetch.plist"])
        self.assertEqual(doc["ProgramArguments"][-3:], ["run", "--roles", "fetch"])
        self.assertEqual((doc["Label"], doc["KeepAlive"], doc["EnvironmentVariables"]["KEEL_CONFIG"]),
                         ("dev.shipyard.fetch", True, config))
        self.assertEqual(doc["StandardErrorPath"], str(self.home / "state" / "logs" / "fetch.err.log"))
        linux = service.Manager(self.manager.home, kind=service.SYSTEMD).files(item)
        self.assertEqual(list(linux), ["dev.shipyard.fetch.service"])
        unit = linux["dev.shipyard.fetch.service"].decode().splitlines()
        self.assertTrue(any(line.startswith("ExecStart=") and line.endswith(" run --roles fetch")
                            for line in unit), unit)
        self.assertIn(f'Environment="KEEL_CONFIG={config}"', unit)
        self.assertIn("Restart=always", unit)

    def test_only_the_services_that_start_houses_keep_their_children_on_a_stop(self):
        """A stop of the fetch role ends the fetcher it was running; a stop of the deck or
        the drain must leave the harness's daemon, and so every house, alive."""
        kills = {label: item.kill_mode for label, item in self.services().items()}
        self.assertEqual(kills, {"dev.shipyard.deck": "process", "dev.shipyard.drain": "process",
                                 "dev.shipyard.fetch": None})


class VerbTest(InstallCase):
    def test_install_brings_up_all_three_and_a_second_install_restarts_none(self):
        code, _ = self.run_service("install")
        self.assertEqual(code, 0)
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.deck"), ("load", "dev.shipyard.drain"),
                                              ("load", "dev.shipyard.fetch")])
        self.manager.calls.clear()
        code, said = self.run_service("install")
        self.assertEqual((code, self.manager.calls), (0, []))
        self.assertIn("dev.shipyard.drain: already installed and running as pid 4242, left running", said)

    def test_an_install_made_before_the_fetch_service_gets_it_and_nothing_else_is_restarted(self):
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.calls.clear()
        self.run_service("install")
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.fetch")])

    def test_a_changed_unit_is_written_and_loaded_again(self):
        self.run_service("install")
        self.manager.calls.clear()
        (self.manager.installed_dir / "dev.shipyard.deck.plist").write_bytes(b"an older render")
        self.run_service("install")
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.deck")])

    def test_status_names_a_fetch_role_that_is_not_running_while_segments_are_installed(self):
        for which in ("deck", "drain"):
            self.run_service("install", which)
        _, said = self.run_service("status")
        self.assertIn("dev.shipyard.fetch: not installed\n"
                      "  nothing fetches 1 installed segment (tides): `shipyard service install fetch`", said)
        self.run_service("install", "fetch")
        _, said = self.run_service("status")
        self.assertIn("dev.shipyard.fetch: installed, running as pid 4242", said)
        self.assertNotIn("nothing fetches", said)

    def test_the_command_status_names_for_a_loaded_service_that_is_not_running_works(self):
        """r2.F1: `status` names `install`, which starts whatever is not running whether
        its unit is missing or loaded with no pid, as the doctor does."""
        self.run_service("install")
        self.manager.stopped.add("dev.shipyard.fetch")          # loaded, and no pid
        _, said = self.run_service("status")
        self.assertIn("dev.shipyard.fetch: installed, not running\n"
                      "  nothing fetches 1 installed segment (tides): `shipyard service install fetch`", said)
        self.assertEqual(self.run_service("install", "fetch")[0], 0)
        self.assertEqual(self.manager.state("dev.shipyard.fetch"), (True, 4242))

    def test_an_enabled_but_stopped_unit_is_started_by_install(self):
        """r1.F4: on systemd a stopped unit stays enabled, which the manager reads as loaded
        (`service.Manager.state`), with no pid. `install` is the command the doctor names
        for a fetch role that is not running, so it must start it, and say what is true."""
        self.run_service("install")
        self.run_service("stop", "fetch")
        self.assertEqual(self.manager.state("dev.shipyard.fetch"), (True, None))
        self.manager.calls.clear()
        _, said = self.run_service("install", "fetch")
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.fetch")])
        self.assertNotIn("left running", said)
        self.assertEqual(self.manager.state("dev.shipyard.fetch"), (True, 4242))
        _, said = self.run_service("install", "fetch")
        self.assertIn("dev.shipyard.fetch: already installed and running as pid 4242, left running", said)

    def test_a_fetch_role_already_running_by_hand_refuses_the_service(self):
        """r1.F3: two fetch roles on one install would each file what a pass files."""
        self.fetch_pids = [777]
        code, said = self.run_service("install")
        self.assertEqual(code, 1)
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.deck"), ("load", "dev.shipyard.drain")])
        self.assertIn("dev.shipyard.fetch: refused: the fetch role already runs for this install "
                      "as pid 777", said)
        self.assertIn("`kill 777`", said)
        code, said = self.run_service("start", "fetch")
        self.assertEqual((code, self.manager.calls[2:]), (1, []), said)

    def test_the_services_own_process_is_not_another_fetch_role(self):
        self.run_service("install")
        self.fetch_pids = [4242]                    # the pid the manager reports for it
        (self.manager.installed_dir / "dev.shipyard.fetch.plist").write_bytes(b"an older render")
        self.manager.calls.clear()
        self.assertEqual(self.run_service("install", "fetch")[0], 0)
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.fetch")])


class BringUpTest(InstallCase):
    """What the drain does as it starts (`appservices.upkeep`), which is what a deploy
    restarts: a missing service is brought up, and nothing that is installed is touched."""

    def upkeep(self) -> list[str]:
        """The drain's one call, with the drain's own log and failed-step path."""
        with contextlib.redirect_stdout(io.StringIO()):
            return appservices.upkeep(self.cfg, lambda text: drain.log(self.cfg, text),
                                      lambda name: drain.failed_step(self.cfg, None, name),
                                      manager=self.manager)

    def test_the_drain_brings_up_the_one_service_that_is_missing(self):
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.calls.clear()
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"])
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.fetch")])
        self.assertTrue((self.home / "services" / "dev.shipyard.fetch.plist").is_file())
        self.assertIn("service dev.shipyard.fetch was missing: installed and started",
                      (self.cfg.logs_dir / drain.LOG_NAME).read_text())
        self.manager.calls.clear()
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []), "the next start finds nothing missing")

    def test_an_install_that_runs_by_hand_gets_no_service(self):
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []))

    def drain_log(self) -> str:
        return (self.cfg.logs_dir / drain.LOG_NAME).read_text()

    def units(self) -> list[Path]:
        """The fetch unit where the manager looks, and as rendered in the install."""
        return [folder / "dev.shipyard.fetch.plist"
                for folder in (self.manager.installed_dir, self.home / "services")]

    def test_a_bring_up_that_fails_is_said_and_tried_again_at_the_next_start(self):
        """r1.F2: launchd's "Bootstrap failed: 5" and systemd's "Failed to connect to bus"
        return a code and raise nothing, after the unit was copied into place."""
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.calls.clear()
        self.manager.load_code = 5
        self.assertEqual(self.upkeep(), [])
        said = self.drain_log()
        self.assertIn("service upkeep failed:", said)
        self.assertIn("service dev.shipyard.fetch was missing and could not be installed and started "
                      "(exit 5); the next drain start tries again", said)
        self.assertNotIn("installed and started\n", said)
        self.assertEqual([path.exists() for path in self.units()], [False, False])
        self.manager.load_code = 0
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"])
        self.assertEqual([verb for verb, _ in self.manager.calls], ["load", "unload", "load"], "once per start")

    def start_drain(self) -> None:
        """`drain.run`, as `keel run --roles drain` calls it, for one pass: only the pass
        itself, the wait after it and the manager are stood in for."""
        summary = {"houses": 0, "reviews": 0, "resumed": 0, "blocked": 0, "started": 0, "paused": False}
        self.addCleanup(restart.started, None)      # the head this "process" loaded

        def rest(cfg, inbox):
            raise KeyboardInterrupt

        with mock.patch("keel.service.Manager", return_value=self.manager), \
                mock.patch.object(drain, "once", return_value=summary), \
                mock.patch.object(drain, "rest", rest), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            drain.run(self.cfg)

    def test_a_drain_that_starts_brings_the_fetch_service_up_and_then_runs_its_pass(self):
        """r1.F7: plan point 3, no hand step, is this one line of `drain.run`."""
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.calls.clear()
        self.start_drain()
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.fetch")])
        said = self.drain_log()
        self.assertIn("service dev.shipyard.fetch was missing: installed and started", said)
        self.assertLess(said.index("was missing: installed and started"), said.index("drain: houses=0"))
        self.manager.calls.clear()
        self.start_drain()
        self.assertEqual(self.manager.calls, [], "the next start, a deploy or a config save, loads nothing")

    def test_a_manager_that_raises_never_stops_the_drain_and_leaves_nothing_behind(self):
        """r1.F7: a service manager that is not there (no `launchctl`, no `systemctl`)."""
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.load_error = OSError("launchctl: not found")
        self.start_drain()
        said = self.drain_log()
        self.assertIn("service upkeep failed:", said)
        self.assertIn("OSError: launchctl: not found", said)
        self.assertIn("drain: houses=0", said, "the drain ran its pass all the same")
        self.assertEqual([path.exists() for path in self.units()], [False, False])
        self.manager.load_error = None
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"], "the next start tries again")

    def test_a_take_back_whose_uninstall_raises_still_leaves_nothing_behind(self):
        """r2.F2: with no service manager at all, the load raises and so does the uninstall
        that takes it back. A copy left then would read as a service the install has."""
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.load_error = OSError("launchctl: not found")
        self.manager.unload_error = OSError("launchctl: not found")
        self.assertEqual(self.upkeep(), [])
        self.assertEqual([path.exists() for path in self.units()], [False, False])
        self.assertIn("service upkeep failed:", self.drain_log())
        self.manager.load_error = self.manager.unload_error = None
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"], "the next start tries again")

    def test_a_fetch_role_run_by_hand_holds_the_bring_up_until_it_is_gone(self):
        """r1.F3: an owner who worked around the bug with `shipyard fetch` must not get a
        second loop at the next deploy."""
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.calls.clear()
        self.fetch_pids = [777]
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []))
        self.assertIn("service dev.shipyard.fetch not brought up: the fetch role already runs for "
                      "this install as pid 777", self.drain_log())
        self.assertEqual([path.exists() for path in self.units()], [False, False])
        self.fetch_pids = []
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"])

    def test_a_service_the_owner_uninstalled_is_never_brought_back(self):
        """r1.F1: a drain start is every deploy, every config save and every packs move, so
        it must not fight an uninstall. `uninstall` keeps the rendered unit in the install's
        own `services/`, which is the record that the install had it."""
        self.run_service("install")
        for which in ("fetch", "deck"):
            self.run_service("uninstall", which)
            self.manager.calls.clear()
            self.assertEqual((self.upkeep(), self.manager.calls), ([], []), which)

    def test_the_deck_and_the_drain_are_never_brought_up_by_the_drain(self):
        """Only a service added since installs were first made (the fetch role): an install
        whose deck was never a service is one its owner runs that way."""
        self.run_service("install", "drain")
        self.manager.calls.clear()
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"])
        self.assertEqual(self.manager.calls, [("load", "dev.shipyard.fetch")])

    def test_another_installs_services_are_never_added_to(self):
        self.run_service("install", "drain")
        unit = self.manager.installed_dir / "dev.shipyard.drain.plist"
        unit.write_text(unit.read_text().replace(str(self.home / "config.toml"), "/elsewhere/config.toml"))
        self.manager.calls.clear()
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []))


class StartedTest(InstallCase):
    """c-747: "started" is said only of a service that has a process."""

    def upkeep(self) -> list[str]:
        with contextlib.redirect_stdout(io.StringIO()):
            return appservices.upkeep(self.cfg, lambda text: drain.log(self.cfg, text),
                                      lambda name: drain.failed_step(self.cfg, None, name),
                                      manager=self.manager)

    def drain_log(self) -> str:
        return (self.cfg.logs_dir / drain.LOG_NAME).read_text()

    def test_a_service_launchd_loads_and_does_not_run_is_not_logged_as_started(self):
        """The reproduction, as it happened on 2026-10-11: the drain's bring-up loaded the
        fetch service, launchd held its start back (loaded, no pid, runs 0), and the
        drain's log said "installed and started" over a service that was not running."""
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.pended.add("dev.shipyard.fetch")
        brought = self.upkeep()
        self.assertEqual(self.manager.state("dev.shipyard.fetch"), (True, None))
        self.assertEqual(self.manager.runs.get("dev.shipyard.fetch", 0), 0)
        self.assertNotIn("installed and started", self.drain_log())
        self.assertEqual(brought, [])

    def pend(self) -> None:
        """An install whose fetch service the drain's bring-up loaded and launchd holds."""
        for which in ("deck", "drain"):
            self.run_service("install", which)
        self.manager.pended.add("dev.shipyard.fetch")
        self.assertEqual(self.upkeep(), [])
        self.manager.calls.clear()

    def units(self) -> list[bool]:
        return [(folder / "dev.shipyard.fetch.plist").exists()
                for folder in (self.manager.installed_dir, self.home / "services")]

    def test_a_service_loaded_with_no_process_is_the_drains_failed_step_and_stays_installed(self):
        self.pend()
        said = self.drain_log()
        self.assertIn("service upkeep failed:", said)
        self.assertIn("service dev.shipyard.fetch was missing and is installed, but not started: launchd "
                      "loaded it and no process was running after 5 seconds", said)
        self.assertIn("the next drain start starts it", said)
        self.assertEqual(self.manager.waits, ["dev.shipyard.deck", "dev.shipyard.drain", "dev.shipyard.fetch"],
                         "a process was waited for before anything was said")
        self.assertEqual(self.units(), [True, True], "loaded is not a failed install: nothing is taken back")

    def test_the_next_drain_start_starts_the_loaded_service_and_does_not_reinstall_it(self):
        self.pend()
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"])
        self.assertEqual(self.manager.calls, [("start", "dev.shipyard.fetch")])
        self.assertEqual(self.manager.state("dev.shipyard.fetch"), (True, 4242))
        self.assertIn("service dev.shipyard.fetch was loaded and not running: started", self.drain_log())
        self.manager.calls.clear()
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []), "started once, then left alone")

    def test_the_owed_start_is_made_at_three_drain_starts_and_then_given_up(self):
        """r1.F5: a service that never holds a process would otherwise cost every drain
        start (each deploy, each config save) the whole wait and a failed step, for ever."""
        self.pend()
        self.manager.dead.add("dev.shipyard.fetch")
        self.assertEqual(self.upkeep(), [])
        self.assertIn("service dev.shipyard.fetch is loaded and still has no process: launchd loaded it "
                      "and no process was running after 5 seconds", self.drain_log())
        self.assertIn("the next drain start tries again (1 of 3)", self.drain_log())
        self.assertNotIn("started\n", self.drain_log())
        self.assertEqual(self.upkeep(), [])
        self.assertEqual(self.manager.calls, [("start", "dev.shipyard.fetch")] * 2,
                         "one start per drain start, and never a load")
        self.assertTrue(self.note().is_file())
        self.assertNotIn("the drain stops trying", self.drain_log())
        self.assertEqual(self.upkeep(), [])
        self.assertIn("service dev.shipyard.fetch is loaded and had no process at 3 drain starts", self.drain_log())
        self.assertIn("the drain stops trying: `shipyard service start fetch` starts it", self.drain_log())
        self.assertFalse(self.note().exists())
        self.assertEqual(self.upkeep(), [])
        self.assertEqual(self.manager.calls, [("start", "dev.shipyard.fetch")] * 3, "a fourth start makes none")
        self.assertEqual(self.drain_log().count("the drain stops trying"), 1, "said once")
        self.assertEqual(self.units(), [True, True], "given up on, not taken out")

    def test_a_service_that_came_up_by_itself_since_is_not_started_again(self):
        """launchd ran the pended spawn after all (or a login did): nothing is restarted."""
        self.pend()
        self.manager.pended.clear()
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []))

    def test_a_stop_or_an_uninstall_by_the_owner_ends_the_retry(self):
        """The retry is only for a service this bring-up loaded and nobody has touched since:
        a drain start is every deploy and every config save, and must not fight a stop."""
        self.pend()
        self.run_service("stop", "fetch")
        self.manager.calls.clear()
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []), "stopped stays stopped")
        self.run_service("uninstall", "fetch")
        self.manager.calls.clear()
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []), "uninstalled stays uninstalled")

    def test_each_verb_that_has_the_manager_act_removes_the_note(self):
        """r1.F7: the note itself, after each of the four, from the same owed state (loaded,
        no process, the note there). The drain's silence afterwards does not show it: a
        service that is no longer loaded, or that runs, is left alone with or without it."""
        self.pend()
        for verb in ("stop", "uninstall", "start", "install"):
            with self.subTest(verb):
                self.note().write_text(appservices.NOTE.format(tried=0))
                self.manager.loaded.add("dev.shipyard.fetch")
                self.manager.pended.add("dev.shipyard.fetch")
                self.manager.calls.clear()
                self.run_service(verb, "fetch")
                self.assertEqual([call[1] for call in self.manager.calls], ["dev.shipyard.fetch"],
                                 "the manager was asked to act")
                self.assertFalse(self.note().exists(), f"the note outlived a {verb}")

    def note(self) -> Path:
        """The bring-up's note that it loaded the fetch service and saw no process."""
        return self.home / "services" / "dev.shipyard.fetch.unstarted"

    def test_a_refused_verb_leaves_the_owed_start_owed(self):
        """r1.F3: a `start` or an `install` refused beside a fetch role run by hand asked
        the manager for nothing, so the drain still owes the start once that role is gone."""
        self.pend()
        self.fetch_pids = [777]
        for verb in ("start", "install"):
            code, said = self.run_service(verb, "fetch")
            self.assertEqual((code, self.manager.calls), (1, []), said)
            self.assertTrue(self.note().is_file(), f"a refused {verb} dropped the note")
        self.fetch_pids = []
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"])
        self.assertEqual(self.manager.calls, [("start", "dev.shipyard.fetch")])

    def test_a_unit_stopped_with_the_managers_own_command_is_not_started_again(self):
        """r1.F4: on systemd `systemctl --user stop` leaves the unit enabled with no pid,
        which is what an owed start looks like, and it went through no `shipyard service`
        verb. The manager says the unit is at rest, and a stopped service stays stopped."""
        self.pend()
        self.manager.stopped.add("dev.shipyard.fetch")          # by hand, not `shipyard service stop`
        self.assertEqual(self.manager.state("dev.shipyard.fetch"), (True, None))
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []))
        self.assertFalse(self.note().exists(), "and nothing is owed any more")

    def test_a_fetch_role_run_by_hand_holds_the_retry_too(self):
        self.pend()
        self.fetch_pids = [777]
        self.assertEqual((self.upkeep(), self.manager.calls), ([], []))
        self.assertIn("service dev.shipyard.fetch not started: the fetch role already runs for this "
                      "install as pid 777", self.drain_log())
        self.fetch_pids = []
        self.assertEqual(self.upkeep(), ["dev.shipyard.fetch"])

    def test_install_says_started_only_with_a_process_and_exits_non_zero_without_one(self):
        self.manager.pended.add("dev.shipyard.fetch")
        code, said = self.run_service("install")
        self.assertEqual(code, 1)
        self.assertIn("dev.shipyard.drain: started, running as pid 4242", said)
        self.assertIn("dev.shipyard.fetch: not running: launchd loaded it and no process was running after "
                      "5 seconds", said)
        self.assertIn("`shipyard service start fetch` tries again", said)
        self.assertNotIn("dev.shipyard.fetch: started", said)

    def test_start_starts_a_loaded_service_that_has_no_process_and_says_its_pid(self):
        self.manager.pended.add("dev.shipyard.fetch")
        self.run_service("install")
        self.manager.calls.clear()
        code, said = self.run_service("start", "fetch")
        self.assertEqual((code, self.manager.calls), (0, [("start", "dev.shipyard.fetch")]))
        self.assertIn("dev.shipyard.fetch: started, running as pid 4242", said)

    def test_start_with_no_process_says_so_plainly_and_exits_non_zero(self):
        self.manager.dead.add("dev.shipyard.fetch")
        self.run_service("install")
        code, said = self.run_service("start", "fetch")
        self.assertEqual(code, 1)
        self.assertEqual(said.splitlines()[-1].split(" (")[0],
                         "dev.shipyard.fetch: not running: launchd loaded it and no process was running "
                         "after 5 seconds")
        self.assertIn(str(self.home / "state" / "logs" / "fetch.err.log"), said)


class DoctorTest(InstallCase):
    def report(self, running: list[str]) -> dict:
        with mock.patch.object(doctor.drainprobe, "drains", return_value=([], [])), \
                mock.patch.object(doctor.drainprobe, "fetching", return_value=running), \
                mock.patch.object(doctor.service, "linger_report", return_value={"applicable": False}):
            return doctor.gather(self.home / "config.toml", probe_logins=False)

    def test_the_doctor_names_a_fetch_role_that_is_not_running_while_segments_are_installed(self):
        report = self.report([])
        self.assertIn("fetch: nothing runs the fetch role, so 1 installed segment (tides) never refresh: "
                      "`shipyard service install fetch` (or `shipyard fetch` by hand)", doctor.problems(report))
        self.assertIn("fetch         NOT RUNNING", doctor.render(report).splitlines())

    def test_a_running_fetch_role_is_a_line_and_no_problem(self):
        report = self.report(["running as pid 77"])
        self.assertFalse([line for line in doctor.problems(report) if line.startswith("fetch:")])
        lines = doctor.render(report).splitlines()
        self.assertIn("fetch         running as pid 77", lines)
        self.assertIn("segment       tides        never fetched", lines)

    def test_no_fetcher_installed_is_no_problem(self):
        (self.segment / "fetch.py").unlink()
        self.assertFalse([line for line in doctor.problems(self.report([])) if line.startswith("fetch:")])


class ProbeTest(unittest.TestCase):
    def test_the_fetch_role_is_a_loop_naming_it_never_a_one_shot(self):
        py = "/usr/bin/python3 /code/bin/keel "
        self.assertEqual([drainprobe.is_fetch(py + rest) for rest in (
            "run --roles fetch", "run --roles drain,serve,fetch", "fetch",
            "run --roles drain", "run", "fetch --once", "fetch --preview", "serve",
            "fetch --segment oci", "fetch --segment=oci")],
            [True, True, True, False, False, False, False, False, False, False])

    def test_a_loop_narrowed_to_one_segment_is_not_the_installs_fetch_role(self):
        """r2.F4: `fetch --segment oci` fetches one segment and files no recurring card, so
        it neither holds the service back nor counts as the role for the doctor, which still
        names the segments nothing fetches. The filing lock keeps the two from filing twice."""
        procs = [(21, "python3 /code/bin/shipyard fetch --segment oci")]
        with mock.patch.object(drainprobe, "processes", lambda: procs), \
                mock.patch.object(drainprobe, "config_of", lambda pid: "/a/config.toml"):
            self.assertEqual(drainprobe.fetch_pids(Path("/a/config.toml")), [])
            self.assertEqual(drainprobe.fetching(Path("/a/config.toml")), [])
        self.assertEqual(doctor.fetch_role_problems({"running": [], "segments": ["daybook", "oci"]}),
                         ["fetch: nothing runs the fetch role, so 2 installed segments (daybook, oci) never "
                          "refresh: `shipyard service install fetch` (or `shipyard fetch` by hand)"])

    def test_only_this_installs_fetch_role_counts(self):
        procs = [(11, "python3 /code/bin/keel run --roles fetch"), (12, "python3 /code/bin/shipyard fetch")]
        with mock.patch.object(drainprobe, "processes", lambda: procs), \
                mock.patch.object(drainprobe, "config_of", {11: "/a/config.toml", 12: "/b/config.toml"}.get):
            self.assertEqual(drainprobe.fetching(Path("/a/config.toml")), ["running as pid 11"])
            self.assertEqual(drainprobe.fetching(Path("/c/config.toml")), [])


class PageTest(InstallCase):
    def test_a_segment_whose_first_fetch_failed_says_so_and_is_still_listed(self):
        (self.segment / "fetch.py").write_text("raise SystemExit(3)\n")
        self.assertEqual(self.listed()["tides"]["fetch_said"], "not fetched yet")
        self.assertEqual(fetch.once(self.cfg)["tides"], "failed")
        entry = self.listed()["tides"]
        self.assertEqual((entry["fetched"], entry["summary"]["tiles"]), (False, []))
        self.assertIn("its fetcher failed", entry["fetch_said"])

    def test_the_digest_says_not_fetched_yet_for_its_headline(self):
        rows = deckdigest._segment_rows({"segments": deckstate.segments(self.cfg)})
        self.assertIn({"name": "tides", "headline": "not fetched yet"}, rows)


if __name__ == "__main__":
    unittest.main()
