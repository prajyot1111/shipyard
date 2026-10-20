"""`keel backup`: the plists, install and uninstall, status, the pass-throughs, and `env`.

The suite runs as launchd on any host (`service.platform` is pinned); the systemd shape of
the same two jobs is checked in `tests/test_service.py`. Every `launchctl` and every call into `bin/keel-backup` is patched. The tool's own
behaviour (the sets, the scope, retention, the refusals, the round trip) is not this
suite's business and is proved by `bin/keel-backup-selftest`, which runs it for real
against a fabricated tree and a directory standing in for the store. What is checked here is the seam: that
Keel writes the right agents and hands the tool the right argv, unparsed.
"""

import io
import json
import os
import plistlib
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import backup, config as config_module, service
from tests.helpers import TWO_MACHINE_TOML, make_config
from tests.test_limits import TOML, load


class Done:
    """Stands in for a CompletedProcess, with only the fields the module reads."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class BackupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.root = self.dir / "keel"
        (self.cfg.root / "etc").mkdir(parents=True)
        (self.cfg.root / "bin").mkdir()
        (self.cfg.root / "bin" / "keel-backup").write_text("#!/bin/sh\n")
        pin = mock.patch.object(service, "platform", return_value=service.LAUNCHD)
        pin.start()
        self.addCleanup(pin.stop)
        self.home = self.dir / "home"
        # THE LOADED COPIES GO IN THIS TMPDIR. The installed path used to resolve against
        # the process's real home whatever `home` said, so `--load` wrote into the live
        # `~/Library/LaunchAgents` and the uninstall test DELETED both real agents. Both
        # were gone on 2026-09-18 with both labels still loaded, which is a machine that
        # loses its backup at the next reboot.
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        self.paths = backup.paths_from(self.cfg, home=self.home)
        self.assertTrue(str(self.installed(backup.LABEL)).startswith(str(self.home)),
                        "a test must never be able to reach the real LaunchAgents directory")

    def installed(self, label):
        return self.paths.manager.installed_dir / f"{label}.plist"

    def written(self, label):
        return self.paths.etc / f"{label}.plist"

    def quiet(self, call, *args, **kwargs):
        """Run something that prints, and hand back what it printed."""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = call(*args, **kwargs)
        return code, buffer.getvalue()


class LabelTest(BackupCase):
    """c-729: a new install's backup jobs are named as its other units are (dev.shipyard.*);
    a machine whose jobs were installed under the old labels keeps them, so an installed
    and loaded backup never loses its job to a rename."""

    def labels(self):
        return [backup.service(self.paths, key).label for key in backup.LABELS]

    def test_a_new_install_names_its_jobs_as_its_other_units(self):
        self.assertEqual(self.labels(), ["dev.shipyard.backup", "dev.shipyard.backup-verify", "dev.shipyard.backup-pull"])
        self.quiet(backup.install, self.paths)
        self.assertTrue(self.written("dev.shipyard.backup").exists())
        self.assertEqual(backup.service(self.paths, backup.LABEL).description, "Shipyard backup: hourly snapshot")

    def test_jobs_installed_under_the_old_labels_keep_them(self):
        for where in (self.paths.manager.installed_dir, self.paths.etc):
            with self.subTest(where=where.name):
                (where / "dev.keel.backup.plist").write_text("an older install's job")
                self.assertEqual(self.labels(), ["dev.keel.backup", "dev.keel.backup-verify", "dev.keel.backup-pull"])
                with mock.patch.object(service.Manager, "state", return_value=(True, None)) as asked:
                    lines = backup.agent_lines(self.paths)
                self.assertEqual([call.args[0] for call in asked.call_args_list], ["dev.keel.backup", "dev.keel.backup-verify"])
                self.assertTrue(lines[0].startswith("dev.keel.backup: loaded"), lines)
                (where / "dev.keel.backup.plist").unlink()


class PlistTest(BackupCase):
    def plist(self, label):
        return plistlib.loads(backup.render_plist(self.paths, label))

    def test_the_snapshot_agent_runs_hourly_and_at_load(self):
        plist = self.plist(backup.LABEL)
        self.assertEqual(plist["ProgramArguments"],
                         [str(self.cfg.root / "bin" / "keel-backup"), "snapshot"])
        self.assertEqual(plist["StartInterval"], 3600)
        self.assertTrue(plist["RunAtLoad"])
        self.assertNotIn("StartCalendarInterval", plist)

    def test_the_verify_agent_runs_on_a_calendar_and_not_at_load(self):
        """A weekly interval counted from load drifts with every reboot; a calendar job
        launchd missed runs once on wake, which is what a sleeping laptop needs."""
        plist = self.plist(backup.VERIFY_LABEL)
        self.assertEqual(plist["ProgramArguments"],
                         [str(self.cfg.root / "bin" / "keel-backup"), "verify"])
        self.assertEqual(plist["StartCalendarInterval"], {"Weekday": 0, "Hour": 4, "Minute": 30})
        self.assertFalse(plist["RunAtLoad"])
        self.assertNotIn("StartInterval", plist)

    def test_the_logs_are_beside_the_clone_and_never_inside_state(self):
        """`state/` is in the keel set. A log an hourly job appends to, inside the tree it
        is archiving, would change the manifest on every single run."""
        for label in (backup.LABEL, backup.VERIFY_LABEL):
            plist = self.plist(label)
            for key in ("StandardOutPath", "StandardErrorPath"):
                self.assertTrue(plist[key].startswith(str(self.home / ".keel-backup")), plist[key])
                self.assertNotIn(str(self.cfg.state_dir), plist[key])

    def test_the_environment_reaches_the_tools_the_script_shells_out_to(self):
        env = self.plist(backup.LABEL)["EnvironmentVariables"]
        self.assertEqual(env["KEEL_HOME"], str(self.cfg.root))
        self.assertEqual(env["HOME"], str(self.home))
        self.assertIn("/opt/homebrew/bin", env["PATH"])   # rclone and gpg live there

    def test_the_jobs_read_the_config_they_were_installed_from(self):
        """c-622: an install's board is its config's state dir, which the checkout's own
        keel.toml does not name, so the keel set follows the config `install` was run with."""
        self.cfg.source = self.dir / "install" / "config.toml"
        self.paths = backup.paths_from(self.cfg, home=self.home)
        env = self.plist(backup.LABEL)["EnvironmentVariables"]
        self.assertEqual(env["KEEL_CONFIG"], str(self.cfg.source))
        self.assertIn(f"export KEEL_BACKUP_STATE_DIR={self.cfg.state_dir}", backup.env_lines(self.cfg))

    def test_the_pull_runs_nightly_on_a_calendar(self):
        """03:00, and a laptop asleep then runs it once on wake."""
        plist = self.plist(backup.PULL_LABEL)
        self.assertEqual(plist["ProgramArguments"],
                         [str(self.cfg.root / "bin" / "keel-backup"), "pull"])
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 3, "Minute": 0})
        self.assertFalse(plist["RunAtLoad"])
        self.assertTrue(plist["StandardOutPath"].endswith("pull.out"))


class PullUpkeepTest(BackupCase):
    """The pull run from the Mac's drain pass when it is due, because the drain only runs
    while the Mac is awake. The 03:00 job fired in a DarkWake, froze between wakes, and
    finished six hours later with a stale listing (c-440)."""

    def setUp(self):
        super().setUp()
        self.cfg.backup_pull = True
        self.cfg.home = self.home
        self.bh = self.home / ".keel-backup"
        self.bh.mkdir()   # KEEL_BACKUP_HOME is not set: the fence scrubs every KEEL_*

    def last_pull(self, hours_ago: float) -> None:
        when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        (self.bh / "state.json").write_text(json.dumps(
            {"last_pull": when.strftime("%Y-%m-%dT%H:%M:%SZ")}))

    def upkeep(self, caffeinate="/usr/bin/caffeinate"):
        with mock.patch.object(backup.subprocess, "Popen") as popen, \
                mock.patch.object(backup.shutil, "which", return_value=caffeinate):
            result = backup.pull_upkeep(self.cfg)
        return result, popen

    def test_a_pull_never_run_is_due_and_runs_detached_awake_and_logged(self):
        result, popen = self.upkeep()
        self.assertTrue(result["started"], result)
        argv = popen.call_args.args[0]
        self.assertEqual(argv, ["/usr/bin/caffeinate", "-i",
                                str(self.cfg.root / "bin" / "keel-backup"), "pull"])
        kwargs = popen.call_args.kwargs
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(Path(kwargs["stdout"].name), self.bh / "logs" / "pull.out")
        self.assertEqual(Path(kwargs["stderr"].name), self.bh / "logs" / "pull.err")
        self.assertEqual(kwargs["env"]["KEEL_BACKUP_PULL"], "1")

    def test_without_caffeinate_it_runs_the_tool_itself(self):
        result, popen = self.upkeep(caffeinate=None)
        self.assertEqual(popen.call_args.args[0],
                         [str(self.cfg.root / "bin" / "keel-backup"), "pull"])

    def test_a_recent_pull_is_not_due(self):
        self.last_pull(hours_ago=3)
        result, popen = self.upkeep()
        self.assertFalse(result["started"])
        popen.assert_not_called()

    def test_a_pull_older_than_the_due_age_runs(self):
        self.last_pull(hours_ago=backup.PULL_DUE_HOURS + 1)
        result, popen = self.upkeep()
        self.assertTrue(result["started"])

    def test_a_host_that_does_not_pull_never_does(self):
        self.cfg.backup_pull = False
        result, popen = self.upkeep()
        popen.assert_not_called()

    def test_a_pull_already_running_is_left_alone(self):
        """The pull's lock is the tool's one lock shape: a link whose target is the pid."""
        (self.bh / ".pull-lock").symlink_to(str(os.getpid()))
        result, popen = self.upkeep()
        self.assertFalse(result["started"])
        self.assertIn("running", result["reason"])
        popen.assert_not_called()

    def test_a_pull_the_old_tool_is_running_is_left_alone_too(self):
        """Its older lock, a directory with a pid file, from a run across a deploy."""
        (self.bh / ".pull-lock").mkdir()
        (self.bh / ".pull-lock" / "pid").write_text(f"{os.getpid()}\n")
        result, popen = self.upkeep()
        self.assertFalse(result["started"])
        self.assertIn("running", result["reason"])
        popen.assert_not_called()

    def test_a_failed_pull_is_not_retried_every_pass(self):
        """The drain passes every half minute; a failing pull is tried again an hour later,
        not thirty seconds later."""
        result, popen = self.upkeep()
        self.assertTrue(result["started"])
        result, popen = self.upkeep()
        self.assertFalse(result["started"])
        popen.assert_not_called()
        kicked = self.bh / backup.PULL_KICKED
        old = kicked.stat().st_mtime - backup.PULL_RETRY_SECONDS - 5
        os.utime(kicked, (old, old))
        result, popen = self.upkeep()
        self.assertTrue(result["started"])


class InstallTest(BackupCase):
    def test_install_writes_both_plists_and_loads_nothing_without_the_flag(self):
        with mock.patch.object(backup.subprocess, "run") as run:
            code, out = self.quiet(backup.install, self.paths)
        self.assertEqual(code, 0)
        run.assert_not_called()
        for label in (backup.LABEL, backup.VERIFY_LABEL):
            self.assertTrue(self.written(label).exists())
            self.assertFalse(self.installed(label).exists())
        self.assertIn("not loaded", out)

    def test_load_copies_both_into_launch_agents_and_bootstraps_them(self):
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(backup.subprocess, "run", return_value=Done()) as run:
            code, _ = self.quiet(backup.install, self.paths, load=True)
        self.assertEqual(code, 0)
        for label in (backup.LABEL, backup.VERIFY_LABEL):
            self.assertTrue(self.installed(label).exists())
        calls = [call.args[0] for call in run.call_args_list]
        # Booted out before bootstrap, so a reinstall over a loaded agent is not a refusal.
        self.assertEqual([c[1] for c in calls], ["bootout", "bootstrap", "bootout", "bootstrap"])
        self.assertEqual(calls[1][-1], str(self.installed(backup.LABEL)))
        self.assertEqual(calls[3][-1], str(self.installed(backup.VERIFY_LABEL)))

    def test_the_pull_job_is_written_only_where_the_host_pulls(self):
        with mock.patch.object(backup.subprocess, "run"):
            self.quiet(backup.install, self.paths)
        self.assertFalse(self.written(backup.PULL_LABEL).exists(), "the box does not pull")
        with mock.patch.object(backup.subprocess, "run"):
            self.quiet(backup.install, self.paths, pull=True)
        self.assertTrue(self.written(backup.PULL_LABEL).exists(), "the Mac does")

    def test_install_refuses_when_the_tool_is_not_there(self):
        (self.cfg.root / "bin" / "keel-backup").unlink()
        self.assertEqual(backup.install(self.paths), 2)

    def test_uninstall_boots_both_out_and_keeps_the_repos_copies(self):
        with mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(backup.subprocess, "run", return_value=Done()):
            self.quiet(backup.install, self.paths, load=True)
            code, _ = self.quiet(backup.uninstall, self.paths)
        self.assertEqual(code, 0)
        for label in (backup.LABEL, backup.VERIFY_LABEL):
            self.assertFalse(self.installed(label).exists())
            self.assertTrue(self.written(label).exists(), "the repo's own plist is kept")


class StatusTest(BackupCase):
    def test_a_loaded_agent_with_no_pid_reads_as_loaded_not_missing(self):
        """A scheduled agent is normally loaded and not running. Reporting that as missing
        would have every status read look like the backup was uninstalled."""
        with mock.patch.object(backup.subprocess, "run", return_value=Done(stdout='{\n\t"Label" = "x";\n}')):
            lines = backup.agent_lines(self.paths)
        self.assertTrue(all("loaded" in line and "NOT LOADED" not in line for line in lines), lines)

    def test_a_missing_agent_is_loud(self):
        with mock.patch.object(backup.subprocess, "run", return_value=Done(returncode=1)):
            lines = backup.agent_lines(self.paths)
        self.assertTrue(all("NOT LOADED" in line for line in lines), lines)

    def test_status_prints_both_agents_then_hands_status_to_the_tool(self):
        with mock.patch.object(service.Manager, "state", return_value=(True, None)), \
             mock.patch.object(backup, "tool", return_value=0) as tool:
            code, out = self.quiet(backup.status, self.paths, self.cfg, ["--json"])
        self.assertEqual(code, 0)
        self.assertIn(backup.LABEL, out)
        self.assertIn(backup.VERIFY_LABEL, out)
        tool.assert_called_once_with(self.paths, ["status", "--json"], self.cfg)


class DispatchTest(BackupCase):
    def dispatch(self, argv):
        with mock.patch.object(backup.config_module, "load", return_value=self.cfg), \
             mock.patch.object(backup, "paths_from", return_value=self.paths), \
             mock.patch.object(backup, "tool", return_value=0) as tool, \
             mock.patch.object(service.Manager, "state", return_value=(False, None)), \
             mock.patch.object(backup.subprocess, "run", return_value=Done()):
            code, _ = self.quiet(backup.main, argv)
        return code, tool

    def test_run_is_a_snapshot_and_every_flag_after_it_reaches_the_tool(self):
        """Unparsed on purpose: a parser here would have to know every flag the tool has,
        and would refuse the next one added to it."""
        _, tool = self.dispatch(["run", "--force", "--set", "keel"])
        tool.assert_called_once_with(self.paths, ["snapshot", "--force", "--set", "keel"], self.cfg)


    def test_pull_init_and_migrate_pass_through_under_the_tools_own_names(self):
        for verb, name in (("pull", "pull"), ("init", "init"), ("migrate", "migrate-from-git")):
            _, tool = self.dispatch([verb, "--clone", "/x"] if verb == "migrate" else [verb])
            expected = [name, "--clone", "/x"] if verb == "migrate" else [name]
            tool.assert_called_once_with(self.paths, expected, self.cfg)

    def test_env_prints_the_settings_as_exports_a_shell_can_eval(self):
        self.cfg.backup_store = "rclone:keel-drive:keel-backup"
        self.cfg.backup_sets = ["keel", "harbor"]
        self.cfg.host = "mac"
        buffer = io.StringIO()
        with mock.patch.object(backup.config_module, "load", return_value=self.cfg), \
             redirect_stdout(buffer):
            self.assertEqual(backup.main(["env"]), 0)
        lines = buffer.getvalue().splitlines()
        self.assertIn("export KEEL_BACKUP_STORE=rclone:keel-drive:keel-backup", lines)
        self.assertIn("export KEEL_BACKUP_SETS='keel harbor'", lines)
        self.assertIn("export KEEL_BACKUP_HOST=mac", lines)

    def test_no_store_configured_is_an_empty_store_not_a_guess(self):
        self.cfg.backup_store = None
        self.assertEqual(backup.settings(self.cfg)["KEEL_BACKUP_STORE"], "")

    def test_install_goes_through_the_parser_so_the_flag_is_keels_own(self):
        code, tool = self.dispatch(["install"])
        self.assertEqual(code, 0)
        tool.assert_not_called()
        self.assertTrue(self.written(backup.LABEL).exists())


class ToolTest(BackupCase):
    def test_the_tool_is_run_with_keel_home_set_and_its_exit_code_returned(self):
        with mock.patch.object(backup.subprocess, "run", return_value=Done(returncode=3)) as run:
            self.assertEqual(backup.tool(self.paths, ["status"]), 3)
        args, kwargs = run.call_args
        self.assertEqual(args[0], [str(self.cfg.root / "bin" / "keel-backup"), "status"])
        self.assertEqual(kwargs["env"]["KEEL_HOME"], str(self.cfg.root))

    def test_the_tool_is_handed_this_hosts_backup_settings(self):
        self.cfg.backup_store = "file:/tmp/store"
        self.cfg.backup_sets = ["keel"]
        self.cfg.host = "box"
        with mock.patch.object(backup.subprocess, "run", return_value=Done()) as run:
            backup.tool(self.paths, ["snapshot"], self.cfg)
        env = run.call_args.kwargs["env"]
        self.assertEqual((env["KEEL_BACKUP_STORE"], env["KEEL_BACKUP_SETS"], env["KEEL_BACKUP_HOST"]),
                         ("file:/tmp/store", "keel", "box"))

    def test_a_missing_tool_is_refused_rather_than_raising(self):
        (self.cfg.root / "bin" / "keel-backup").unlink()
        self.assertEqual(backup.tool(self.paths, ["status"]), 2)


class HostConfigTest(unittest.TestCase):
    """Which sets the machine writes, whether it pulls, and where the store is: keel.toml's
    `[backup]` table."""

    def test_the_backup_table_says_the_sets_and_the_pull(self):
        cfg = load(TOML + '\n[backup]\nsets = ["keel", "code"]\npull = true\n'
                          'store = "file:/tmp/store"\n')
        self.assertEqual((cfg.backup_sets, cfg.backup_pull, cfg.backup_store),
                         (["keel", "code"], True, "file:/tmp/store"))

    def test_a_two_machine_toml_still_backs_up_what_its_host_table_said(self):
        """c-622: the launchd agents that read the tracked keel.toml kept their sets under
        `[hosts.mac]`. The table is ignored now, but its backup keys are still read for
        this host while `[backup]` does not name them, so no backup stops on the upgrade."""
        with mock.patch.dict(backup.os.environ, {"KEEL_HOST": "box"}):
            mac = config_module.load(TWO_MACHINE_TOML, ensure=False)
        self.assertEqual(mac.host, "mac")
        self.assertEqual(mac.backup_sets, ["harbor", "helm"])
        self.assertTrue(mac.backup_pull)
        self.assertTrue(mac.backup_store.startswith("rclone:"))
        self.assertEqual(mac.backup_rclone_config, Path.home() / ".keel-backup" / "rclone.conf")

    def test_a_host_without_backup_keys_writes_nothing_and_there_is_no_store(self):
        mac = load(TOML)
        self.assertEqual((mac.backup_sets, mac.backup_pull, mac.backup_store), ([], False, None))

    def test_keels_own_sets_are_keel_and_code(self):
        """c-722: the default sets are Keel's own; any other is one install's, named by it."""
        self.assertEqual(config_module.BACKUP_SETS, ("keel", "code"))

    def test_an_installs_own_sets_are_named_under_extra_and_handed_to_the_tool(self):
        cfg = load(TOML + '\n[backup]\nsets = ["keel", "harbor"]\nextra = ["harbor"]\n')
        self.assertEqual((cfg.backup_sets, cfg.backup_extra), (["keel", "harbor"], ["harbor"]))
        self.assertFalse([line for line in cfg.warnings if "harbor" in line], cfg.warnings)
        self.assertEqual(backup.settings(cfg)["KEEL_BACKUP_EXTRA"], "harbor")

    def test_the_tools_two_other_sets_need_no_extra_before_the_move(self):
        """r1.F14: an install from before c-722 names harbor and helm in `sets` with no
        `extra`; it loads as it did, with no new line in the doctor."""
        cfg = load(TOML + '\n[backup]\nsets = ["harbor", "helm", "code", "keel"]\n')
        self.assertEqual(cfg.backup_sets, ["harbor", "helm", "code", "keel"])
        self.assertFalse([line for line in cfg.warnings if "backup" in line], cfg.warnings)

    def test_a_set_the_tool_has_no_facts_for_is_refused_and_never_reaches_it(self):
        """r1.F4: a typo in `sets` or in `extra` is refused where the config loads, as before
        c-722, so no backup job is ever handed a set it would die on."""
        for table in ('sets = ["kel"]\n', 'sets = ["keel"]\nextra = ["mine"]\n'):
            with self.subTest(table=table), self.assertRaises(config_module.ConfigError) as caught, \
                    mock.patch.object(backup.subprocess, "run") as run:
                cfg = load(TOML + "\n[backup]\n" + table)
                backup.tool(backup.paths_from(cfg), ["snapshot"], cfg)
            run.assert_not_called()
            self.assertIn("the sets the backup tool knows are keel, code, harbor, helm", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class PortableUnpackTest(unittest.TestCase):
    """The snapshot is a gzipped tar, and it is unpacked from a pipe (`gpg_dec ... | tar`).
    bsdtar on the Mac sniffs the compression; GNU tar on the box does not from a pipe and
    refuses ("Archive is compressed. Use -z option"), which is how the first restore on the
    box failed on a good blob (2026-09-19). The suite runs on the Mac, where a missing -z
    cannot fail, so the script's text is what is checked."""

    def test_every_unpack_of_a_decrypted_blob_names_gzip(self):
        script = (Path(__file__).resolve().parent.parent / "bin" / "keel-backup").read_text()
        unpacks = [line.strip() for line in script.splitlines()
                   if "gpg_dec" in line and "| tar" in line and not line.lstrip().startswith("#")]
        self.assertGreaterEqual(len(unpacks), 2, "the round-trip check and the restore")
        for line in unpacks:
            self.assertRegex(line, r"\| tar -x\w*z\w*f? ", line)
