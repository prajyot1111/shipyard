"""`keel/service.py`: one Service rendered for launchd and for systemd, and the manager's
load, unload, state and restart on each, with every `launchctl` and `systemctl` patched.

The rendered units are also checked by the real `systemd-analyze verify` and started for
real in a throwaway systemd container; that run is recorded on card c-283, since no
suite here can boot a service manager.
"""

import io
import os
import plistlib
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from keel import backup, install, service, talker
from tests.helpers import make_config


def done(returncode=0, stdout="", stderr="", args=("x",)):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr, args=list(args))


def daemon(**overrides) -> service.Service:
    fields = dict(label="dev.keel.x", description="x", argv=["/k/bin/keel", "run"], cwd=Path("/k"),
                  env={"KEEL_HOME": "/k"}, stdout=Path("/k/state/logs/x.out"),
                  stderr=Path("/k/state/logs/x.err"))
    fields.update(overrides)
    return service.Service(**fields)


class CaseWithHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.etc = self.dir / "etc"

    def daemon(self, **overrides):
        """A service whose log directory is in the tmpdir, since `write` makes it."""
        logs = self.dir / "logs"
        return daemon(stdout=logs / "x.out", stderr=logs / "x.err", **overrides)

    def manager(self, kind):
        manager = service.Manager(self.home, kind)
        self.assertTrue(str(manager.installed_dir).startswith(str(self.home)),
                        "a test must never be able to reach a real service directory")
        return manager

    def quiet(self, call, *args, **kwargs):
        with redirect_stdout(io.StringIO()) as out:
            code = call(*args, **kwargs)
        return code, out.getvalue()


class PlatformTest(unittest.TestCase):
    def test_linux_is_systemd_and_everything_else_launchd(self):
        with mock.patch.object(service.sys, "platform", "linux"):
            self.assertEqual(service.platform(), service.SYSTEMD)
            self.assertEqual(service.Manager(Path("/h")).kind, service.SYSTEMD)
        with mock.patch.object(service.sys, "platform", "darwin"):
            self.assertEqual(service.Manager(Path("/h")).kind, service.LAUNCHD)

    def test_wsl_is_told_by_its_kernel_or_its_distro_variable(self):
        """c-804: WSL is Linux to Keel, and the setup check asks only there."""
        wsl = "Linux version 6.6.87.2-microsoft-standard-WSL2 (root@host) (gcc 11.2.0) #1 SMP"
        plain = "Linux version 6.8.0-45-generic (buildd@lcy02) (gcc 13.2.0) #45-Ubuntu SMP"
        self.assertTrue(service.on_wsl(wsl, env={}))
        self.assertFalse(service.on_wsl(plain, env={}))
        self.assertTrue(service.on_wsl(plain, env={"WSL_DISTRO_NAME": "Ubuntu"}))


class UnitTest(unittest.TestCase):
    def test_a_daemon_restarts_forever_and_appends_to_its_logs(self):
        text = service.unit(daemon(throttle=7))
        self.assertIn("Type=simple", text)
        self.assertIn("ExecStart=/k/bin/keel run", text)
        self.assertIn("Restart=always\nRestartSec=7", text)
        self.assertIn("StartLimitIntervalSec=0", text)
        self.assertIn("StandardOutput=append:/k/state/logs/x.out", text)
        self.assertIn("StandardError=append:/k/state/logs/x.err", text)
        self.assertIn('Environment="KEEL_HOME=/k"', text)
        self.assertIn("[Install]\nWantedBy=default.target", text)
        self.assertNotIn("KillMode", text)

    def test_quoting_survives_spaces_percent_dollar_and_quotes(self):
        self.assertEqual(service.quote("/a/b"), "/a/b")
        self.assertEqual(service.quote("a b"), '"a b"')
        self.assertEqual(service.quote("100%"), '"100%%"')
        self.assertEqual(service.quote("$HOME"), '"$$HOME"')
        self.assertEqual(service.quote('say "hi"'), '"say \\"hi\\""')
        self.assertEqual(service.env_line("P", 'a"%b'), 'Environment="P=a\\"%%b"')

    def test_the_engine_keeps_its_houses_on_a_restart(self):
        """The houses' daemon lives in the engine's cgroup, and systemd's default stop kills
        the whole cgroup: that would be something automatic ending live sessions."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            cfg.root = Path("/k")
            text = service.unit(install.service(cfg, "drain,serve", home=Path("/home/u")))
        self.assertIn("KillMode=process", text)
        self.assertIn("CPUWeight=100", text)
        self.assertIn("ExecStart=/k/bin/keel run --roles drain,serve", text)
        self.assertIn("Environment=\"PATH=/home/u/.local/bin:", text)

    def test_the_engine_and_the_talker_name_the_config_of_an_install(self):
        """c-711: a service started with `KEEL_HOME` alone loads the checkout's own toml,
        which is not the board of the install it was rendered for."""
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.realpath(tmp)        # written out below, so no link may be in it
            cfg = make_config(Path(real))
            self.assertNotIn("KEEL_CONFIG", install.service(cfg, "drain").env)
            self.assertNotIn("KEEL_CONFIG", talker.service(talker.paths_from(cfg)).env)
            cfg.source = Path(f"{real}/install/config.toml")
            named = f"{real}/install/config.toml"
            self.assertEqual(install.service(cfg, "drain").env["KEEL_CONFIG"], named)
            self.assertEqual(talker.service(talker.paths_from(cfg)).env["KEEL_CONFIG"], named)
            # A scratch config (a worktree handed its own board) names nothing: a named toml
            # is taken at its word, and that would send the service to the refused board.
            cfg.scratch = True
            self.assertNotIn("KEEL_CONFIG", install.service(cfg, "drain").env)
            self.assertNotIn("KEEL_CONFIG", talker.service(talker.paths_from(cfg)).env)

    def test_each_install_says_which_config_its_service_will_read(self):
        """c-711 review: `keel install` and `keel talker install` say it as the voice one does."""
        from keel import cli
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.realpath(tmp)
            cfg = make_config(Path(real))
            cfg.root = Path(f"{real}/keel")
            (cfg.root / "etc").mkdir(parents=True)
            manager = service.Manager(Path(f"{real}/home"))
            for source, line in (
                    (Path(f"{real}/install/config.toml"), f"the service reads {real}/install/config.toml\n"),
                    (None, f"the service reads {real}/keel/etc/shipyard.example.toml, the checkout's own "
                           f"(no other config was named)\n")):
                cfg.source = source
                out = io.StringIO()
                paths = talker.paths_from(cfg)
                paths.home = manager.home
                with mock.patch.object(install.service_module, "Manager", return_value=manager), \
                     mock.patch.object(talker, "seed_claude_json"), \
                     mock.patch.object(talker, "link_memory"), redirect_stdout(out):
                    cli.role_install(cfg, mock.Mock(roles="drain", load=False))
                    talker.install(paths, load=False)
                self.assertEqual(out.getvalue().count(line), 2, out.getvalue())

    def test_the_talker_runs_under_tmux_and_its_log_is_the_reading(self):
        paths = talker.Paths(root=Path("/k"), state_dir=Path("/k/state"), home=Path("/home/u"))
        text = service.unit(talker.service(paths))
        self.assertIn("Type=forking", text)
        self.assertIn('ExecStart=/usr/bin/tmux -L keel-talker new-session -d -s keel-talker '
                      '"/k/bin/keel talker start 2>&1 | tee -a /k/state/logs/talker.log"', text)
        self.assertIn("ExecStop=/usr/bin/tmux -L keel-talker kill-server", text)
        self.assertIn('Environment="CLAUDE_CONFIG_DIR=/k/spaces/harbor/.claude"', text)
        self.assertIn("Restart=always", text)
        self.assertNotIn("StandardOutput", text, "tmux daemonizes; the tee is the log")

    def test_the_talker_plist_ignores_tmux(self):
        paths = talker.Paths(root=Path("/k"), state_dir=Path("/k/state"))
        doc = plistlib.loads(talker.render_plist(paths, home=Path("/Users/me")))
        self.assertEqual(doc["ProgramArguments"], ["/k/bin/keel", "talker", "start"])

    def test_the_backup_jobs_are_oneshots_on_timers(self):
        paths = backup.Paths(root=Path("/k"), home=Path("/home/u"))
        manager = service.Manager(Path("/home/u"), service.SYSTEMD)
        hourly = manager.files(backup.service(paths, backup.LABEL))
        self.assertEqual(list(hourly), ["dev.shipyard.backup.service", "dev.shipyard.backup.timer"])
        unit, timer = (content.decode() for content in hourly.values())
        self.assertIn("Type=oneshot", unit)
        self.assertNotIn("Restart=", unit)
        self.assertNotIn("[Install]", unit, "the timer is what is enabled, not the job")
        self.assertIn("OnActiveSec=0\nOnUnitActiveSec=3600s", timer)
        self.assertIn("WantedBy=timers.target", timer)
        weekly = manager.files(backup.service(paths, backup.VERIFY_LABEL))
        timer = weekly["dev.shipyard.backup-verify.timer"].decode()
        self.assertIn("OnCalendar=Sun *-*-* 04:30:00\nPersistent=true", timer)
        self.assertNotIn("OnActiveSec", timer, "the proof does not run at load, as on launchd")
        nightly = manager.files(backup.service(paths, backup.PULL_LABEL))
        timer = nightly["dev.shipyard.backup-pull.timer"].decode()
        self.assertIn("OnCalendar=*-*-* 03:00:00\nPersistent=true", timer)

    def test_launchd_weekday_seven_is_sunday_too(self):
        self.assertEqual(service.on_calendar({"Weekday": 7, "Hour": 1, "Minute": 5}), "Sun *-*-* 01:05:00")
        self.assertEqual(service.on_calendar({"Hour": 23, "Minute": 0}), "*-*-* 23:00:00")


class LaunchdTest(CaseWithHome):
    def test_load_copies_into_launch_agents_and_bootstraps_after_the_bootout(self):
        manager = self.manager(service.LAUNCHD)
        manager.write(self.daemon(), self.etc)
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(service.subprocess, "run", return_value=done()) as run:
            code, _ = self.quiet(manager.load, self.daemon(), self.etc)
        self.assertEqual(code, 0)
        target = self.home / "Library" / "LaunchAgents" / "dev.keel.x.plist"
        self.assertTrue(target.is_file())
        verbs = [call.args[0][1] for call in run.call_args_list]
        self.assertEqual(verbs, ["bootout", "bootstrap", "kickstart"])
        self.assertEqual(run.call_args_list[1].args[0][-1], str(target))

    def verbs_of(self, run) -> list[str]:
        return [call.args[0][1] for call in run.call_args_list]

    def test_a_load_ends_with_a_real_start_that_restarts_nothing(self):
        """c-747: a bootstrap is not a start. launchd loaded `dev.shipyard.fetch` on
        2026-10-11 and held its start back ("pended nondemand spawn = speculative", runs 0)
        though the plist has RunAtLoad and KeepAlive; a kickstart started it at once. No
        `-k`: that one kills a running service, and this must leave it running."""
        manager = self.manager(service.LAUNCHD)
        manager.write(self.daemon(), self.etc)
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(service.subprocess, "run", return_value=done()) as run:
            self.quiet(manager.load, self.daemon(), self.etc)
        self.assertEqual(run.call_args_list[-1].args[0],
                         ["launchctl", "kickstart", f"gui/{os.getuid()}/dev.keel.x"])

    def test_a_bootstrap_that_failed_is_not_kickstarted(self):
        manager = self.manager(service.LAUNCHD)
        manager.write(self.daemon(), self.etc)
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(service.subprocess, "run",
                               return_value=done(5, stderr="Bootstrap failed: 5")) as run:
            code, _ = self.quiet(manager.load, self.daemon(), self.etc)
        self.assertEqual((code, self.verbs_of(run)), (5, ["bootout", "bootstrap"]))

    def test_a_kickstart_that_failed_is_the_loads_code_and_is_said(self):
        manager = self.manager(service.LAUNCHD)
        manager.write(self.daemon(), self.etc)

        def answers(argv, **kwargs):
            return done(3, stderr="Could not find service") if argv[1] == "kickstart" else done()

        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(service.subprocess, "run", side_effect=answers):
            code, out = self.quiet(manager.load, self.daemon(), self.etc)
        self.assertEqual(code, 3)
        self.assertIn("Could not find service", out)

    def complaining(self, argv, **kwargs):
        return done(37, stderr="Operation already in progress") if argv[1] == "kickstart" else done()

    def test_a_kickstart_that_complains_about_a_running_service_is_a_good_load(self):
        """r1.F1: the pid decides, not the kickstart's exit code. The bootstrap may have
        started it already (RunAtLoad), and a load that then failed on the kickstart's word
        would have the drain's bring-up boot a running service out."""
        manager = self.manager(service.LAUNCHD)
        manager.write(self.daemon(), self.etc)
        states = [(False, None), (True, 11114)]         # booted out, then running
        with mock.patch.object(service.Manager, "state", side_effect=states), \
             mock.patch.object(service.subprocess, "run", side_effect=self.complaining) as run:
            code, _ = self.quiet(manager.load, self.daemon(), self.etc)
        self.assertEqual((code, self.verbs_of(run)), (0, ["bootout", "bootstrap", "kickstart"]),
                         "good, and nothing was booted out after it")

    def test_a_start_whose_kickstart_complains_about_a_running_service_is_ok(self):
        manager = self.manager(service.LAUNCHD)
        with mock.patch.object(service.Manager, "state", return_value=(True, 11114)), \
             mock.patch.object(service.subprocess, "run", side_effect=self.complaining):
            self.assertTrue(manager.start(self.daemon())[0])
        with mock.patch.object(service.Manager, "state", return_value=(True, None)), \
             mock.patch.object(service.subprocess, "run", side_effect=self.complaining):
            self.assertEqual(manager.start(self.daemon()), (False, "Operation already in progress"))

    def test_a_scheduled_job_is_loaded_and_not_run_now(self):
        """A job runs on its schedule (and at load only where its plist says RunAtLoad): a
        kickstart would run a backup at every install."""
        manager = self.manager(service.LAUNCHD)
        job = self.daemon(keep_alive=False, run_at_load=False, calendar={"Hour": 3, "Minute": 0})
        manager.write(job, self.etc)
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(service.subprocess, "run", return_value=done()) as run:
            self.quiet(manager.load, job, self.etc)
        self.assertEqual(self.verbs_of(run), ["bootout", "bootstrap"])

    def test_start_bootstraps_what_is_not_loaded_and_kickstarts_either_way(self):
        """A stopped service is booted out, so a start bootstraps it; one that is loaded
        with no process (c-747) is only kickstarted, where a bootstrap is a complaint."""
        manager = self.manager(service.LAUNCHD)
        for loaded, verbs in ((False, ["bootstrap", "kickstart"]), (True, ["kickstart"])):
            with mock.patch.object(service.Manager, "state", return_value=(loaded, None)), \
                 mock.patch.object(service.subprocess, "run", return_value=done()) as run:
                ok, _ = manager.start(self.daemon())
            self.assertEqual((ok, self.verbs_of(run)), (True, verbs))
            self.assertNotIn("-k", run.call_args_list[-1].args[0])

    def test_start_never_runs_a_scheduled_job_now_loaded_or_not(self):
        """r1.F2: a job runs on its schedule. Not loaded, it is bootstrapped; loaded, there
        is nothing to do, and no `launchctl` is run at all."""
        manager = self.manager(service.LAUNCHD)
        job = self.daemon(keep_alive=False, run_at_load=False, calendar={"Hour": 3, "Minute": 0})
        for loaded, verbs in ((False, ["bootstrap"]), (True, [])):
            with mock.patch.object(service.Manager, "state", return_value=(loaded, None)), \
                 mock.patch.object(service.subprocess, "run", return_value=done()) as run:
                ok, text = manager.start(job)
            self.assertEqual((ok, self.verbs_of(run)), (True, verbs), text)
        self.assertEqual(text, "dev.keel.x is loaded and runs on its schedule")

    def test_a_start_whose_bootstrap_failed_says_so_and_kickstarts_nothing(self):
        manager = self.manager(service.LAUNCHD)
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(service.subprocess, "run",
                               return_value=done(5, stderr="Bootstrap failed: 5")) as run:
            ok, said = manager.start(self.daemon())
        self.assertEqual((ok, said, run.call_count), (False, "Bootstrap failed: 5", 1))

    def test_the_wait_for_a_process_is_bounded_and_returns_the_pid_it_sees(self):
        """No clock and no real sleep: the wait is a count of looks, and the pause between
        them is handed in."""
        manager = self.manager(service.LAUNCHD)
        naps = []
        with mock.patch.object(service.Manager, "state",
                               side_effect=[(True, None), (True, None), (True, 77)]):
            self.assertEqual(manager.running("dev.keel.x", sleep=naps.append), 77)
        self.assertEqual(naps, [service.START_WAIT] * 2)
        naps.clear()
        with mock.patch.object(service.Manager, "state", return_value=(True, None)) as looked:
            self.assertIsNone(manager.running("dev.keel.x", sleep=naps.append))
        self.assertEqual((looked.call_count, len(naps)), (service.START_TRIES, service.START_TRIES - 1))

    def test_the_bootstrap_waits_for_the_bootout_to_actually_finish(self):
        """`bootout` returns before launchd has let go, and bootstrapping while it still
        holds the label fails with an I/O error that leaves the agent unloaded. Seen for
        real on 2026-09-17 and twice on 2026-09-18."""
        manager = self.manager(service.LAUNCHD)
        manager.write(self.daemon(), self.etc)
        states = [(True, 900), (True, 900), (False, None)]
        with mock.patch.object(service.Manager, "state", side_effect=states) as looked, \
             mock.patch.object(service.time, "sleep") as slept, \
             mock.patch.object(service.subprocess, "run", return_value=done()):
            self.quiet(manager.load, self.daemon(), self.etc)
        self.assertEqual(looked.call_count, 3)
        self.assertEqual(slept.call_count, 2)

    def test_it_gives_up_waiting_rather_than_hanging(self):
        manager = self.manager(service.LAUNCHD)
        manager.write(self.daemon(), self.etc)
        with mock.patch.object(service.Manager, "state", return_value=(True, 900)), \
             mock.patch.object(service.time, "sleep") as slept, \
             mock.patch.object(service.subprocess, "run",
                               return_value=done(5, stderr="Bootstrap failed: 5")):
            code, out = self.quiet(manager.load, self.daemon(), self.etc)
        self.assertEqual(code, 5)
        self.assertEqual(slept.call_count, service.BOOTOUT_TRIES)
        self.assertIn("Bootstrap failed", out)

    def test_state_parses_launchctl_list(self):
        manager = self.manager(service.LAUNCHD)
        listing = '{\n\t"PID" = 4242;\n\t"Label" = "dev.keel.x";\n};\n'
        with mock.patch.object(service.subprocess, "run", return_value=done(stdout=listing)):
            self.assertEqual(manager.state("dev.keel.x"), (True, 4242))
        with mock.patch.object(service.subprocess, "run", return_value=done(stdout='{\n\t"Label" = "x";\n}')):
            self.assertEqual(manager.state("dev.keel.x"), (True, None))
        with mock.patch.object(service.subprocess, "run", return_value=done(113)):
            self.assertEqual(manager.state("dev.keel.x"), (False, None))

    def test_restart_is_a_kickstart(self):
        manager = self.manager(service.LAUNCHD)
        with mock.patch.object(service.subprocess, "run", return_value=done()) as run:
            ok, _ = manager.restart("dev.keel.talker")
        self.assertTrue(ok)
        self.assertEqual(run.call_args.args[0][:3], ["launchctl", "kickstart", "-k"])


class SystemdTest(CaseWithHome):
    def run_load(self, svc, linger=True, results=None):
        manager = self.manager(service.SYSTEMD)
        manager.write(svc, self.etc)
        with mock.patch.object(service.subprocess, "run",
                               side_effect=results or (lambda *a, **k: done())) as run, \
             mock.patch.object(service, "lingering", return_value=linger):
            code, out = self.quiet(manager.load, svc, self.etc)
        return code, out, [call.args[0] for call in run.call_args_list]

    def test_load_copies_reloads_enables_and_restarts(self):
        """Restart rather than start, so a reinstall over a running unit picks up the new
        file, the way launchd's bootout and bootstrap do."""
        code, out, calls = self.run_load(self.daemon())
        self.assertEqual(code, 0)
        self.assertTrue((self.home / ".config" / "systemd" / "user" / "dev.keel.x.service").is_file())
        self.assertEqual(calls, [["systemctl", "--user", "daemon-reload"],
                                 ["systemctl", "--user", "enable", "dev.keel.x.service"],
                                 ["systemctl", "--user", "restart", "dev.keel.x.service"]])
        self.assertNotIn("lingering", out)

    def test_a_scheduled_job_enables_its_timer(self):
        code, _, calls = self.run_load(self.daemon(keep_alive=False, interval=60))
        self.assertEqual(code, 0)
        self.assertEqual(calls[1], ["systemctl", "--user", "enable", "dev.keel.x.timer"])
        self.assertTrue((self.home / ".config" / "systemd" / "user" / "dev.keel.x.timer").is_file())

    def test_no_lingering_is_said_out_loud(self):
        code, out, _ = self.run_load(self.daemon(), linger=False)
        self.assertEqual(code, 0, "the units are loaded; lingering is the human's step")
        self.assertIn("lingering is OFF", out)
        self.assertIn("loginctl enable-linger", out)

    def test_a_failed_step_stops_and_returns_its_code(self):
        results = [done(), done(1, stderr="Failed to enable unit")]
        code, out, calls = self.run_load(self.daemon(), results=results)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("Failed to enable unit", out)

    def test_no_user_manager_without_lingering_names_the_cause(self):
        """Seen in the systemd container on 2026-09-19: with lingering off and no login
        session the first systemctl fails with "Failed to connect to bus", which says
        nothing about lingering unless this does."""
        code, out, _ = self.run_load(self.daemon(), linger=False,
                                     results=[done(1, stderr="Failed to connect to bus")])
        self.assertEqual(code, 1)
        self.assertIn("Failed to connect to bus", out)
        self.assertIn("lingering is OFF", out)

    def test_unload_disables_removes_and_reloads(self):
        manager = self.manager(service.SYSTEMD)
        job = self.daemon(keep_alive=False, interval=60)
        self.run_load(job)
        with mock.patch.object(service.subprocess, "run", return_value=done()) as run:
            removed = manager.unload(job)
        calls = [call.args[0][2:] for call in run.call_args_list]
        self.assertEqual(calls, [["disable", "--now", "dev.keel.x.timer"], ["stop", "dev.keel.x.service"],
                                 ["daemon-reload"]])
        self.assertTrue(all(not path.exists() for path in removed))
        self.assertTrue((self.etc / "dev.keel.x.timer").is_file(), "the checkout's copy is kept")

    def test_state_reads_enablement_and_main_pid(self):
        manager = self.manager(service.SYSTEMD)
        answers = {"UnitFileState": "UnitFileState=enabled\n", "MainPID": "MainPID=321\n"}

        def show(argv, **kwargs):
            return done(stdout=answers[argv[-1].split("=")[1]])
        with mock.patch.object(service.subprocess, "run", side_effect=show) as run:
            self.assertEqual(manager.state("dev.keel.x"), (True, 321))
        self.assertEqual(run.call_args_list[0].args[0][3], "dev.keel.x.service")
        answers["MainPID"] = "MainPID=0\n"
        with mock.patch.object(service.subprocess, "run", side_effect=show) as run:
            self.assertEqual(manager.state("dev.keel.x", scheduled=True), (True, None))
        self.assertEqual(run.call_args_list[0].args[0][3], "dev.keel.x.timer")
        answers["UnitFileState"] = "UnitFileState=disabled\n"
        with mock.patch.object(service.subprocess, "run", side_effect=show):
            self.assertEqual(manager.state("dev.keel.x"), (False, None))

    def test_a_keep_alive_unit_is_at_rest_only_when_systemd_says_inactive(self):
        """r1.F4: `Restart=always` with no start limit keeps a crashing unit `activating`
        between runs, so `inactive` is a stop. launchd has no such state (a stop is a
        bootout, which is not loaded) and is never asked."""
        manager = self.manager(service.SYSTEMD)
        for active, resting in (("inactive", True), ("activating", False), ("active", False),
                                ("failed", False)):
            with mock.patch.object(service.subprocess, "run",
                                   return_value=done(stdout=f"ActiveState={active}\n")) as run:
                self.assertEqual(manager.resting(self.daemon()), resting, active)
            self.assertEqual(run.call_args.args[0][2:], ["show", "dev.keel.x.service", "--property=ActiveState"])
        with mock.patch.object(service.subprocess, "run", return_value=done(stdout="ActiveState=inactive\n")) as run:
            self.assertFalse(manager.resting(self.daemon(keep_alive=False)), "a job rests between runs")
            self.assertFalse(self.manager(service.LAUNCHD).resting(self.daemon()))
        run.assert_not_called()

    def test_restart_is_systemctl_restart(self):
        manager = self.manager(service.SYSTEMD)
        with mock.patch.object(service.subprocess, "run", return_value=done(1, stderr="not loaded")):
            self.assertEqual(manager.restart("dev.keel.talker"), (False, "not loaded"))

    def test_lingering_is_the_flag_file(self):
        (self.dir / "linger").mkdir()
        self.assertFalse(service.lingering("ubuntu", self.dir / "linger"))
        (self.dir / "linger" / "ubuntu").touch()
        self.assertTrue(service.lingering("ubuntu", self.dir / "linger"))


if __name__ == "__main__":
    unittest.main()
