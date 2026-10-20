"""`shipyard import <dir>` (keel/stateimport.py): his board and cards brought from a snapshot
into a fresh install. The promises, one test each, through `stateimport.main` as the command
runs it: a dry run writes nothing and names every change; a real import moves only values
under an old root, clears what two machines needed, keeps a work card's session and paths and
blocks the cards whose session or branch stayed on the box; a second run refuses and
`--replace` keeps the previous state aside; verify catches a leftover root; the config carries
no two-machine table; uncommitted memory refuses. docs/atlas/87-import.md.
"""

import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from keel import config as config_module
from keel import appservices, drainprobe, importboard, importverify, installer, packs, stateimport
from keel.board import Board
from tests.helpers import make_repo

BOX = "/home/ubuntu/keel/state/"
MAC = "/Users/him/keel/state/"
NOW = "2026-10-01T10:00:00+00:00"
GONE = importboard.BOX_HOME + "nobody-c620/notes"   # a box home this machine lacks
SESSION = "11111111-0000-4000-8000-000000000001"
WORK_SESSION = "33333333-0000-4000-8000-000000000003"


def git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *argv],
                   check=True, capture_output=True)


def card(conn, cid, space, stage, *, session=None, plan=None, options=None, repo=None):
    conn.execute("INSERT INTO cards (id, space, title, stage, session_id, plan_ref, options, repo, "
                 "model, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (cid, space, f"card {cid}", stage, session, plan, json.dumps(options or {}), repo,
                  "opus", NOW, NOW))
    conn.execute("INSERT INTO events (card, at, kind, actor, text, data) VALUES (?,?,?,?,?,?)",
                 (cid, NOW, "set", "human", f"plan at {plan}", json.dumps({"plan_ref": plan})))


def snapshot(source: Path, work_tree: str) -> None:
    """Both machines' roots, both spaces, a claimed and a pinned card, a claimed ask, a box
    session on an open personal card, a work worktree and a board file."""
    state = source / "state"
    with Board(state / "board.db"):
        pass
    conn = sqlite3.connect(state / "board.db")
    card(conn, "c-1", "personal", "building", session=SESSION, plan=BOX + "cards/c-1/plan.md",
         options={"claim": {"host": "box", "at": NOW}, "add_dirs": [BOX + "cards/c-4", GONE],
                  "landing": {"host": "box"}}, repo="keel")
    card(conn, "c-2", "personal", "review", plan=MAC + "cards/c-2/plan.md",
         options={"host": "mac", "tier_reads": [MAC + "cards/c-2/plan.md"]}, repo="keel")
    card(conn, "c-3", "work", "building", session=WORK_SESSION, plan=BOX + "cards/c-3/plan.md",
         options={"worktree": work_tree, "claim": {"host": "mac", "at": NOW}})
    card(conn, "c-4", "personal", "done", session="22222222-0000-4000-8000-000000000002",
         plan=BOX + "cards/c-4/plan.md")
    conn.execute("INSERT INTO asks (id, n, kind, actor, card, question, why, options, state, "
                 "claimed_at, claimed_by, created_at, updated_at) VALUES "
                 "('a-1', 1, 'choice', 'c-1', 'c-1', 'which?', 'because', '[]', 'open', ?, 'wake', ?, ?)",
                 (NOW, NOW, NOW))
    conn.execute("INSERT INTO events (card, at, kind, actor, text, data) VALUES "
                 "('c-1', ?, 'relay', 'human', 'resume', ?)", (NOW, json.dumps({"what": "resume", "to": "box"})))
    conn.execute("INSERT INTO requests (id, n, actor, card, what, first_seen, last_seen, state, "
                 "taken_by, created_at, updated_at) VALUES ('r-1', 1, 'c-1', 'c-1', 'a login', ?, ?, "
                 "'taken', 'bosun', ?, ?)", (NOW, NOW, NOW, NOW))
    conn.commit()
    conn.close()
    for cid in ("c-1", "c-2", "c-3", "c-4"):
        (state / "cards" / cid).mkdir(parents=True)
        (state / "cards" / cid / "plan.md").write_text(f"# {cid}\n\nnotes in {BOX}cards/{cid}/\n")
    (state / "boards" / "b-001").mkdir(parents=True)
    (state / "boards" / "b-001" / "board.json").write_text(json.dumps({"file": BOX + "cards/c-1/plan.md"}))
    for name in ("logs", "worktrees/c-1", "console"):
        (state / name).mkdir(parents=True)
    (state / "login.json").write_text("{}")


class ImportCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        self.tmp = Path(scratch.name).resolve()
        self.home = self.tmp / "install"
        with mock.patch.object(installer.prereqs, "gather", return_value=[]), \
             mock.patch.object(installer.Init, "doctor"):
            installer.Init(self.home, services="none", probe_login=False, open_deck=False,
                           say=lambda line: None).run()
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        self.repo = make_repo(self.tmp / "keel")
        # A work path with a `state/` in it is not an old root: only `<checkout>/state/` is.
        self.work_tree = str(self.tmp / "workspace" / "state" / "c-3")
        self.source = self.tmp / "snapshot"
        snapshot(self.source, self.work_tree)
        self.old = self.repo / "keel.toml"      # in a checkout called keel, as his is
        self.old.write_text(OLD.format(repo=self.repo))
        self.procs, self.labels, self.configs = [], [], {}
        for seam in (mock.patch.object(stateimport, "checkouts", lambda cfg, path: [path.parent]),
                     mock.patch.object(importverify, "doctor_lines", lambda cfg: []),
                     mock.patch.object(drainprobe, "processes", lambda: self.procs),
                     mock.patch.object(drainprobe, "labels", lambda: self.labels),
                     mock.patch.object(drainprobe, "config_of", lambda pid: self.configs.get(pid))):
            seam.start()
            self.addCleanup(seam.stop)
        # The old config's work space runs a pack called work: one in the install's own packs
        # (c-722: written here, so no pack of anyone's own is needed).
        work = self.home / "packs" / "work"
        work.mkdir(parents=True, exist_ok=True)
        (work / "pack.toml").write_text('name = "work"\nversion = "1"\ndescription = "a work pack"\n'
                                        '[adapter]\nspaces = ["work"]\n'
                                        '[provides]\nconfig_example = "config.example.toml"\n')
        (work / "config.example.toml").write_text('[spaces.work]\npack = "work"\nconfig_dir = "~/.claude"\n'
                                                  'contract = "etc/space-work.md"\n')
        packs.forget()
        self.addCleanup(packs.forget)

    def shipyard(self, *argv: str) -> tuple[int, str]:
        said = []
        code = stateimport.main([str(self.source), "--old-config", str(self.old), *argv], say=said.append)
        return code, "\n".join(said)

    def board(self) -> dict:
        cfg = config_module.load(self.home / "config.toml")
        with Board(cfg.db_path) as board:
            return {c["id"]: c for c in board.list_cards()}


OLD = """
[keel]
houses_max = 2
board_url = "https://deck.example.ts.net"

[hosts.box]
ssh = "box"
spaces = ["personal"]

[spaces.personal]
config_dir = "~/old/.claude"
model = "sonnet"
[spaces.personal.repos]
keel = "{repo}"
gone = "/nowhere/gone"

[spaces.work]
host = "mac"
adapter = "work"
config_dir = "~/.claude"
model = "opus"

[tests]
keel = "make test"

[builder]
superuser = true

[console]
host = "box"

[recurring.restore-rehearsal]
every_days = 91
"""


class ImportTest(ImportCase):
    def test_a_dry_run_writes_nothing_and_names_every_change(self):
        before = (self.home / "config.toml").read_text()
        code, said = self.shipyard("--dry-run")
        self.assertEqual(code, 0, said)
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertEqual(self.board(), {})
        self.assertFalse((self.home / "state" / "import").exists())
        for line in (f"cards/c-1 plan_ref: {BOX}cards/c-1/plan.md -> {self.home}/state/cards/c-1/plan.md",
                     "cards/c-1 options.claim:", f"cards/c-1 session_id: {SESSION} -> (cleared)",
                     "cards/c-2 options.host: mac -> (cleared)", "asks/a-1 claimed_by: wake -> (cleared)",
                     "state/login.json", "state/console/", "+[spaces.work]"):
            self.assertIn(line, said)

    def test_the_import_moves_old_roots_clears_two_machine_fields_and_blocks_the_right_cards(self):
        git(self.repo, "branch", "keel/c-2-card-c-2")
        code, said = self.shipyard()
        self.assertEqual(code, 0, said)
        cards = self.board()
        state = f"{self.home}/state/"
        self.assertEqual(cards["c-1"]["plan_ref"], state + "cards/c-1/plan.md")
        self.assertEqual(cards["c-2"]["plan_ref"], state + "cards/c-2/plan.md")
        self.assertEqual(cards["c-1"]["options"], {"add_dirs": [state + "cards/c-4", GONE]})
        self.assertEqual(cards["c-1"]["derived"]["relays"], [], "the box's relay is dropped")
        self.assertEqual(cards["c-2"]["options"], {"tier_reads": [state + "cards/c-2/plan.md"]})
        # The work card keeps its session and its worktree; only the claim goes.
        self.assertEqual(cards["c-3"]["session_id"], WORK_SESSION)
        self.assertEqual(cards["c-3"]["options"], {"worktree": self.work_tree})
        self.assertIsNone(cards["c-3"]["blocked_reason"])
        # The box's session on an open personal card is cleared and the card blocked; a closed
        # card keeps its id; the branch that is here is cut again, the one that is not blocks.
        self.assertIsNone(cards["c-1"]["session_id"])
        self.assertIn("session stayed on the source", cards["c-1"]["blocked_reason"])
        self.assertIn("branch keel/c-1-* is on the source", cards["c-1"]["blocked_reason"])
        self.assertIsNone(cards["c-2"]["blocked_reason"])
        self.assertTrue((self.home / "state" / "worktrees" / "c-2" / ".git").exists())
        self.assertEqual(cards["c-4"]["session_id"], "22222222-0000-4000-8000-000000000002")
        board_file = json.loads((self.home / "state/boards/b-001/board.json").read_text())
        self.assertEqual(board_file, {"file": state + "cards/c-1/plan.md"})
        # Free text is copied as it was; the source is untouched.
        self.assertIn(BOX, (self.home / "state/cards/c-1/plan.md").read_text())
        with sqlite3.connect(self.source / "state" / "board.db") as conn:
            self.assertEqual(conn.execute("SELECT session_id FROM cards WHERE id = 'c-1'").fetchone()[0], SESSION)
        with sqlite3.connect(self.home / "state" / "board.db") as conn:
            self.assertEqual(conn.execute("SELECT claimed_by, claimed_at FROM asks").fetchone(), (None, None))
            self.assertEqual(conn.execute("SELECT state, taken_by FROM requests").fetchone(), ("open", None))
        report = (self.home / "state/import/report.md").read_text()
        self.assertIn(f"options.add_dirs[1]: {GONE} is not on this machine", report)
        self.assertIn("c-1 relay", report)
        self.assertFalse((self.home / "state" / "login.json").exists())

    def test_a_second_run_refuses_and_replace_keeps_the_previous_state(self):
        self.assertEqual(self.shipyard()[0], 0)
        code, _ = self.shipyard()
        self.assertEqual(code, 1)
        self.assertEqual(self.shipyard("--replace")[0], 0)
        aside = list((self.home / "state").glob("pre-import-*"))
        self.assertEqual(len(aside), 1)
        self.assertTrue((aside[0] / "board.db").is_file())
        self.assertTrue((aside[0] / "import" / "record.json").is_file())
        self.assertEqual(set(self.board()), {"c-1", "c-2", "c-3", "c-4"})

    def test_an_old_space_is_refused_until_mapped_and_then_verifies(self):
        """2026-10-03, the real move: 24 cards in the retired `console` space refused the
        import with no way through. `--map-space console=personal` carries them."""
        conn = sqlite3.connect(self.source / "state" / "board.db")
        card(conn, "c-9", "console", "done")
        conn.commit()
        conn.close()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code, _ = self.shipyard("--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("--map-space console=personal", err.getvalue())
        self.assertEqual(self.shipyard("--map-space", "console=personal")[0], 0)
        with sqlite3.connect(self.home / "state" / "board.db") as conn:
            self.assertEqual(conn.execute("SELECT space FROM cards WHERE id = 'c-9'").fetchone()[0], "personal")
        self.assertEqual(stateimport.main(["--verify"], say=lambda line: None), 0)

    def test_verify_fails_on_a_value_left_under_an_old_root(self):
        self.assertEqual(self.shipyard()[0], 0)
        self.assertEqual(stateimport.main(["--verify"], say=lambda line: None), 0)
        with sqlite3.connect(self.home / "state" / "board.db") as conn:
            conn.execute("UPDATE cards SET output_ref = ? WHERE id = 'c-4'", (MAC + "cards/c-4/out.md",))
        self.assertEqual(stateimport.main(["--verify"], say=lambda line: None), 1)
        self.assertIn("## Leftovers\n\n- cards/c-4", (self.home / "state/import/report.md").read_text())

    def test_the_config_carries_choices_and_no_two_machine_table(self):
        self.assertEqual(self.shipyard()[0], 0)
        carried = tomllib.loads((self.home / "config.toml").read_text())
        self.assertNotIn("hosts", carried)
        self.assertNotIn("console", carried)
        self.assertNotIn("board_url", carried["keel"])
        self.assertNotIn("restore-rehearsal", carried.get("recurring", {}))
        self.assertEqual(carried["keel"]["houses_max"], 2)
        personal = carried["spaces"]["personal"]
        self.assertEqual((personal["model"], personal["repos"]["keel"]), ("sonnet", str(self.repo)))
        self.assertNotIn("gone", personal["repos"])
        self.assertEqual(personal["config_dir"], str(self.home / "claude"))
        work = carried["spaces"]["work"]
        self.assertEqual((work["pack"], work["config_dir"]), ("work", "~/.claude"))
        self.assertNotIn("host", work)
        # The old superuser's repos stay Bosun's, so no house starts on his cards (2026-10-03).
        self.assertIn("keel", carried["builder"]["repos"])
        self.assertFalse(carried["builder"]["superuser"])

    def test_a_run_that_stopped_part_way_is_resumed(self):
        self.assertEqual(self.shipyard()[0], 0)
        record = self.home / "state/import/record.json"
        record.write_text(json.dumps(dict(json.loads(record.read_text()), status="in-progress")))
        code, said = self.shipyard()
        self.assertEqual(code, 0, said)
        self.assertEqual(json.loads(record.read_text())["status"], "done")
        self.assertEqual(len(self.board()), 4)

    def test_another_drain_or_this_installs_own_refuses_the_import_and_a_service_start(self):
        self.procs = [(4242, "python3 /x/bin/keel run --roles drain,serve")]
        self.labels = ["dev.keel"]
        code, _ = self.shipyard()
        self.assertEqual(code, 1)
        why = drainprobe.refusal(self.home / "config.toml")
        self.assertIn("pid 4242", why)
        self.assertIn("service dev.keel: unload it with", why)
        cfg = config_module.load(self.home / "config.toml")
        self.assertEqual(appservices.run(cfg, "start", manager=mock.Mock()), 1)
        self.procs, self.labels = [(77, "python3 /x/bin/shipyard drain")], []
        self.configs = {77: str(self.home / "config.toml")}
        self.assertIsNone(drainprobe.refusal(self.home / "config.toml"))
        self.assertEqual(self.shipyard()[0], 1, "this install's own drain refuses it too")
        self.assertEqual(self.board(), {})

    def test_uncommitted_memory_refuses_the_import(self):
        shutil.rmtree(self.home / "identity", ignore_errors=True)   # an install from before c-722
        (self.old.parent / "identity").mkdir()
        (self.old.parent / "identity" / "who.md").write_text("me\n")
        code, _ = self.shipyard()
        self.assertEqual(code, 1)
        self.assertEqual(self.board(), {})

    def test_memory_the_install_holds_is_not_read_from_the_checkout(self):
        """c-722: once the install has its own identity profile, the checkout's uncommitted
        one is not what any reader takes, so it holds nothing up."""
        (self.old.parent / "identity").mkdir()
        (self.old.parent / "identity" / "who.md").write_text("me\n")
        shutil.rmtree(self.home / "memory", ignore_errors=True)    # Bosun's and the talker's not moved yet
        (self.home / "identity").mkdir(exist_ok=True)
        (self.home / "identity" / "about-me.md").write_text("me\n")
        self.assertEqual(stateimport.memory_paths(self.home), [p for p in stateimport.MEMORY if p != "identity"])
        self.assertEqual(stateimport.dirty_memory([self.old.parent], stateimport.memory_paths(self.home)), [])
        self.assertTrue(stateimport.dirty_memory([self.old.parent], stateimport.MEMORY))


if __name__ == "__main__":
    unittest.main()
