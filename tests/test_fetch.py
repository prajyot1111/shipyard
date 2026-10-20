"""fetch: fake segments under a temp dir, the lock protocol, asks to cards, the daily cap,
the card's shape and confinement, and the cli routing."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import cli, fetch, house
from keel.board import Board, Refused
from tests.helpers import ROOT, CliCase, FakeHarness, make_config

GOOD = "import pathlib\npathlib.Path('summary.json').write_text('{}')\nprint('3 items')\n"
BAD = "import sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n"
WORKER = ("---\nspace: personal\ndaily_cap: 2   # per day\n# a comment line\ntimeout: 900\n"
          "tools: Read,Write\n---\n\n# asker\n\nAnswer each ask kindly.\n")


def make_segments(root: Path) -> Path:
    """good (a fetcher that succeeds), bad (one that fails), asker (a worker with two asks)."""
    segments = root / "segments"
    (segments / "good").mkdir(parents=True)
    (segments / "good" / "fetch.py").write_text(GOOD)
    (segments / "bad").mkdir()
    (segments / "bad" / "fetch.py").write_text(BAD)
    asker = segments / "asker"
    (asker / "data" / "asks").mkdir(parents=True)
    (asker / "worker.md").write_text(WORKER)
    for number in (1, 2):
        add_ask(asker, number)
    return segments


def add_ask(segment: Path, number: int) -> Path:
    path = segment / "data" / "asks" / f"ask-{number}.json"
    path.write_text(json.dumps({"mode": "batch", "what": f"ask {number}"}))
    return path


INTERPRETER = fetch.interpreter  # the real one, captured before FetchCase patches it away


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


class FetchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.segments = make_segments(self.dir)
        self.board = Board(self.cfg.db_path)
        patch = mock.patch.object(fetch, "interpreter", lambda cfg: sys.executable)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def log_text(self) -> str:
        return (self.cfg.logs_dir / "fetch.log").read_text()

    def hold(self, segment: str, pid: int | None = None, age: float = 0) -> Path:
        lock = fetch.lock_path(self.cfg, segment)
        lock.mkdir(parents=True)
        (lock / "pid").write_text(f"{os.getpid() if pid is None else pid}\n")
        if age:
            stamp = time.time() - age
            os.utime(lock, (stamp, stamp))
        return lock


class FetcherTest(FetchCase):
    def test_every_fetcher_runs_and_one_failure_stops_nothing(self):
        results = fetch.once(self.cfg)
        self.assertEqual(results, {"bad": "failed", "good": "ok"})
        self.assertTrue((self.segments / "good" / "summary.json").exists())
        log = self.log_text()
        self.assertIn("good         ok  3 items", log)
        self.assertIn("bad          FAILED (exit 3)\nboom", log)
        for name in ("good", "bad"):
            self.assertFalse(fetch.lock_path(self.cfg, name).exists(), name)


    def test_a_held_lock_skips_with_the_message_and_is_left_alone(self):
        lock = self.hold("good")
        results = fetch.once(self.cfg)
        self.assertEqual(results["good"], "skipped")
        self.assertIn("good         skipped, another job holds its fetch lock", self.log_text())
        self.assertEqual((lock / "pid").read_text().strip(), str(os.getpid()))
        self.assertFalse((self.segments / "good" / "summary.json").exists())

    def test_a_lock_with_no_pid_yet_counts_as_held(self):
        lock = fetch.lock_path(self.cfg, "good")
        lock.mkdir(parents=True)
        self.assertEqual(fetch.take_lock(lock), "held")

    def test_a_dead_owner_or_an_ancient_lock_is_cleared(self):
        self.hold("good", pid=dead_pid())
        self.assertEqual(fetch.once(self.cfg, segment="good"), {"good": "ok"})
        self.hold("good", age=fetch.LOCK_STALE_SECONDS + 5)
        self.assertEqual(fetch.once(self.cfg, segment="good"), {"good": "ok"})
        self.assertFalse(fetch.lock_path(self.cfg, "good").exists())

    def test_an_unusable_lock_dir_is_reported_not_skipped(self):
        self.cfg.fetch_lock_dir = self.dir / "not-a-dir"
        self.cfg.fetch_lock_dir.write_text("")
        results = fetch.once(self.cfg, segment="good")
        self.assertEqual(results, {"good": "unusable"})
        self.assertIn("NOT RUN, its fetch lock", self.log_text())

    def test_interpreter_is_the_venv_only_when_it_runs(self):
        venv = self.dir / ".venv" / "bin" / "python"
        venv.parent.mkdir(parents=True)
        venv.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        venv.chmod(0o755)
        self.assertEqual(INTERPRETER(self.cfg), str(venv))
        venv.write_text("#!/bin/sh\nexit 1\n")
        self.assertEqual(INTERPRETER(self.cfg), "python3", "present but unable to start is not enough")
        venv.unlink()
        self.cfg.root = self.dir / "code"       # a checkout with no venv of its own
        self.assertEqual(INTERPRETER(self.cfg), "python3")

    def test_an_installs_fetchers_run_under_the_checkouts_venv_when_it_has_none_of_its_own(self):
        """c-742: on an install the segments tree is the install's and the venv built from
        `etc/segment-requirements.txt` is still the checkout's; the install's own wins."""
        def venv(base: Path) -> Path:
            python = base / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            python.chmod(0o755)
            return python

        self.cfg.root = self.dir / "code"
        code = venv(self.cfg.root)
        self.assertEqual(INTERPRETER(self.cfg), str(code))
        own = venv(self.dir)
        self.assertEqual(INTERPRETER(self.cfg), str(own))

    def test_changed_only_runs_a_segment_whose_inputs_moved(self):
        fetch.once(self.cfg, segment="good")
        good = self.segments / "good"
        self.assertEqual(fetch.once(self.cfg, segment="good", changed_only=True), {})
        now = time.time()
        os.utime(good / "fetch.py", (now, now))
        self.assertEqual(fetch.once(self.cfg, segment="good", changed_only=True), {"good": "ok"})
        self.assertEqual(fetch.once(self.cfg, segment="good", changed_only=True), {})
        (good / "data" / "inbox").mkdir(parents=True)
        (good / "data" / "inbox" / "drop.json").write_text("{}")
        self.assertTrue(fetch.inbox_has_work(good))
        self.assertEqual(fetch.once(self.cfg, segment="good", changed_only=True), {"good": "ok"})
        self.assertEqual(fetch.once(self.cfg, segment="bad", changed_only=True), {"bad": "failed"},
                         "a segment that never produced a summary always counts as changed")


class AskTest(FetchCase):
    def asker(self) -> Path:
        return self.segments / "asker"

    def test_asks_become_one_card_per_segment_and_are_taken_exactly_once(self):
        created = fetch.asks(self.cfg, board=self.board)
        self.assertEqual(created, {"asker": "c-001"})
        card = self.board.get("c-001")
        self.assertEqual((card["space"], card["repo"], card["autonomy"], card["stage"], card["title"]),
                         ("personal", None, "autonomous", "assigned", "asker: 2 asks"))
        self.assertEqual(card["plan_ref"], str(self.asker() / "worker.md"))
        options = card["options"]
        self.assertEqual((options["tools"], options["segment"], options["asks"], options["add_dirs"]),
                         ("Read,Write", "asker", ["ask-1.json", "ask-2.json"], [str(self.asker())]))
        self.assertEqual(self.board.events("c-001")[0]["actor"], "fetch")
        taken = self.asker() / "data" / "asks" / "taken"
        self.assertEqual(sorted(p.name for p in taken.iterdir()), ["ask-1.json", "ask-2.json"])
        self.assertEqual(fetch.pending_asks(self.asker()), [])
        self.assertEqual(fetch.asks(self.cfg, board=self.board), {})
        self.assertEqual(len(self.board.list_cards()), 1)

    def test_the_brief_carries_the_worker_body_the_asks_the_drop_and_the_finish(self):
        fetch.asks(self.cfg, board=self.board)
        card = self.board.get("c-001")
        brief = card["brief"]
        self.assertTrue(brief.startswith("# asker\n\nAnswer each ask kindly."))
        self.assertNotIn("daily_cap", brief)
        for name in ("ask-1.json", "ask-2.json"):
            self.assertIn(str(self.asker() / "data" / "asks" / "taken" / name), brief)
        drop = card["options"]["drop"]
        self.assertTrue(drop.startswith(str(self.asker() / "data" / "inbox" / "worker-")))
        self.assertIn(f"write your answers as ONE journal drop at:\n\n  {drop}", brief)
        self.assertIn('{"entries": [ {"k": "<key>", "v": <value>, "t": "<ISO8601>"}, ... ]}', brief)
        self.assertNotIn(chr(0x2014), brief, "no em-dashes, in the brief either")


    def test_daily_cap_counts_only_this_segments_cards_created_today(self):
        self.board.create("personal", "other segment", options={"segment": "other"}, actor="fetch")
        self.assertEqual(fetch.asks(self.cfg, board=self.board), {"asker": "c-002"})
        add_ask(self.asker(), 3)
        self.assertEqual(fetch.asks(self.cfg, board=self.board), {"asker": "c-003"})
        waiting = add_ask(self.asker(), 4)
        self.assertEqual(fetch.asks(self.cfg, board=self.board), {})
        self.assertTrue(waiting.exists(), "a spent cap pauses work, never discards it")
        self.assertIn("asker: daily cap reached (2/2), 1 ask(s) waiting", self.log_text())

    def test_a_bad_worker_declaration_fails_closed(self):
        worker = self.asker() / "worker.md"
        worker.write_text(WORKER.replace("daily_cap: 2", "daily_cap: lots"))
        self.assertEqual(fetch.asks(self.cfg, board=self.board), {})
        self.assertIn("daily_cap in worker.md is not a plain integer", self.log_text())
        worker.write_text(WORKER.replace("space: personal", "space: nowhere"))
        self.assertEqual(fetch.asks(self.cfg, board=self.board), {})
        self.assertIn("worker.md must name a space", self.log_text())
        self.assertEqual(len(fetch.pending_asks(self.asker())), 2)

    def test_a_segment_without_a_worker_never_becomes_a_card(self):
        good = self.segments / "good"
        (good / "data" / "asks").mkdir(parents=True)
        add_ask(good, 1)
        self.assertEqual(fetch.asks(self.cfg, segment="good", board=self.board), {})
        self.assertEqual(len(fetch.pending_asks(good)), 1)

    def test_frontmatter_defaults_and_comments(self):
        fields, body = fetch.parse_frontmatter("---\nspace: work  # why\n# note\ntools: Read\n---\nbody\n")
        self.assertEqual((fields, body), ({"space": "work", "tools": "Read"}, "body"))
        worker = fetch.read_worker(self.asker(), {"personal", "work"})
        self.assertEqual((worker.daily_cap, worker.timeout, worker.tools), (2, 900, "Read,Write"))
        (self.asker() / "worker.md").write_text("---\nspace: work\n---\n")
        worker = fetch.read_worker(self.asker(), {"personal", "work"})
        self.assertEqual((worker.daily_cap, worker.timeout, worker.tools, worker.body),
                         (fetch.DEFAULT_CAP, fetch.DEFAULT_TIMEOUT, fetch.DEFAULT_TOOLS, ""))

    def test_the_drain_starts_an_ask_card_restricted_with_the_segment_added(self):
        fake = FakeHarness()
        with mock.patch.object(house, "harness", fake):
            fetch.asks(self.cfg, board=self.board)
            house.launch(self.cfg, self.board, "c-001")
        start = fake.starts[0]
        # the segment it answers for, and the Atlas every brief tells a house to read
        self.assertEqual((start["restricted"], start["tools"], start["add_dirs"]),
                         (True, "Read,Write",
                          (self.asker().resolve(), self.cfg.root / "docs" / "atlas")))
        self.assertEqual(start["cwd"], self.cfg.state_dir / "cards" / "c-001")
        self.assertEqual(self.board.get("c-001")["stage"], "building")
        self.assertIn("Answer each ask kindly.", start["prompt"])


def write_fetch_toml(directory: Path) -> Path:
    path = directory / "keel.toml"
    path.write_text(
        "[keel]\n"
        f'state_dir = "{directory / "state"}"\n'
        f'segments_dir = "{directory / "segments"}"\n'
        f'fetch_lock_dir = "{directory / "locks"}"\n'
        "[spaces.personal]\n"
        'config_dir = "~/nowhere"\n'
        'contract = "etc/space-personal.md"\n'
    )
    return path


class FetchCliTest(CliCase):
    def setUp(self):
        super().setUp()
        make_segments(self.dir)
        os.environ["KEEL_CONFIG"] = str(write_fetch_toml(self.dir))

    def launch(self, *argv):
        return subprocess.run([sys.executable, ROOT / "bin" / "keel", *argv], cwd=ROOT,
                              capture_output=True, text=True, env=dict(os.environ))

    def test_fetch_once_runs_fetchers_then_asks_and_prints_one_line(self):
        result = self.launch("fetch", "--once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "fetch: ok=1 failed=1 skipped=0 unusable=0 cards=1")
        log = (self.dir / "state" / "logs" / "fetch.log").read_text()
        self.assertIn("(once)", log)
        self.assertTrue((self.dir / "locks").is_dir())
        self.assertEqual(self.launch("kb", "list").stdout.strip().split()[-3:], ["asker:", "2", "asks"])

    def test_fetch_once_that_could_not_file_says_so_and_exits_non_zero(self):
        """r2.F3: another fetch role holds the filing lock (a live pid: this test's), so the
        asks and the recurring cards were left to its pass. `cards=0` alone reads as
        "nothing to file", with two asks waiting."""
        lock = self.dir / "locks" / ".fetch-.filing.lock"
        lock.mkdir(parents=True)
        (lock / "pid").write_text(f"{os.getpid()}\n")
        result = self.launch("fetch", "--once")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.strip(), "fetch: ok=1 failed=1 skipped=0 unusable=0 cards=0")
        self.assertIn("keel fetch: the fetchers ran, but no card was filed: another fetch role is "
                      "filing", result.stderr)
        self.assertEqual(len(fetch.pending_asks(self.dir / "segments" / "asker")), 2, "the asks still wait")

    def test_run_roles_includes_fetch_and_serve_and_refuses_the_unknown(self):
        self.assertEqual(cli.parse_roles("drain,fetch,serve,fetch"), ["drain", "fetch", "serve"])
        with self.assertRaises(Refused):
            cli.parse_roles("drain,deck")
        args = cli.build_role_parser().parse_args(["fetch", "--once", "--segment", "good"])
        self.assertEqual((args.role, args.once, args.segment), ("fetch", True, "good"))

    def test_run_with_the_fetch_role_starts_the_loop(self):
        process = subprocess.Popen([sys.executable, ROOT / "bin" / "keel", "run", "--roles", "fetch"],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=dict(os.environ))
        log = self.dir / "state" / "logs" / "fetch.log"
        try:
            deadline = time.time() + 20
            while time.time() < deadline and not (log.exists() and "asker: c-001" in log.read_text()):
                time.sleep(0.2)
            self.assertIsNone(process.poll(), "the loop is still running")
        finally:
            process.terminate()
            _, err = process.communicate(timeout=10)
        text = log.read_text()
        self.assertIn("fetch up:", text)
        self.assertIn("good         ok  3 items", text)
        self.assertNotIn("not built", err)


FOLDER = """import pathlib, shutil
inbox = pathlib.Path("data/inbox")
applied = pathlib.Path("data/inbox-applied")
applied.mkdir(parents=True, exist_ok=True)
for f in sorted(inbox.glob("*.json")):
    f.replace(applied / f.name)
pathlib.Path("summary.json").write_text("{}")
print("folded")
"""
KEEPER = """import pathlib
pathlib.Path("summary.json").write_text("{}")
print("nothing folded")
"""


class FoldClosesTheCardTest(FetchCase):
    """An ask card's outcome gate is empty: the fold happens before anyone looks at it.

    So the fold is the approval. These pin the four states `fold_verdict` names, that a
    drop folded before any of this existed still closes its card, and that a drop the fold
    refused keeps its gate and is explained exactly once.
    """

    def setUp(self):
        super().setUp()
        self.seg = self.segments / "asker"
        (self.seg / "data" / "inbox").mkdir(parents=True, exist_ok=True)
        self.drop = self.seg / "data" / "inbox" / "worker-20260918T005708Z.json"
        self.applied = self.seg / "data" / "inbox-applied" / self.drop.name
        self.card = self.at_review(self.drop)

    def at_review(self, drop: Path) -> str:
        """An ask card the Stop hook has already filed: at review, with its drop as output."""
        card_id = self.board.create("personal", "asker: 1 ask", autonomy="autonomous",
                                    options={"segment": "asker", "drop": str(drop)}, actor="fetch",
                                    stage="assigned")
        self.board.set_fields(card_id, {"plan_ref": str(self.seg / "worker.md")}, "fetch")
        self.board.stage(card_id, "building", "drain")
        self.board.stage(card_id, "review", "hook", output_ref=str(drop))
        return card_id

    def write_drop(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": [{"k": "story:one", "v": 1, "t": "2026-09-18T10:00:00Z"}]}))

    def stage_of(self, card_id: str) -> str:
        return self.board.get(card_id)["stage"]

    def notes(self, card_id: str) -> list[str]:
        return [event["text"] for event in self.board.events(card_id)
                if event["text"] and event["kind"] in ("note", "stage")]

    def test_a_folded_drop_closes_its_card(self):
        self.write_drop(self.applied)
        closed = fetch.close_folded(self.cfg, {"asker": "ok"}, self.board)
        self.assertEqual(closed, {self.card: "folded"})
        self.assertEqual(self.stage_of(self.card), "done")
        self.assertIn(fetch.FOLDED_NOTE, self.notes(self.card))
        self.assertIn(f"{self.card}: done, {fetch.FOLDED_NOTE}", self.log_text())

    def test_a_drop_folded_before_any_of_this_existed_still_closes_now(self):
        """c-270's own case: the fetcher folded its drop hours before the card could be
        closed by one, so the check reads the disk rather than waiting for a fresh fold."""
        self.write_drop(self.applied)
        self.assertEqual(fetch.close_folded(self.cfg, {}, self.board), {self.card: "folded"})
        self.assertEqual(self.stage_of(self.card), "done")

    def test_a_drop_the_fold_would_not_take_keeps_its_gate_and_is_explained_once(self):
        self.write_drop(self.drop)
        closed = fetch.close_folded(self.cfg, {"asker": "ok"}, self.board)
        self.assertEqual(closed, {self.card: "refused"})
        self.assertEqual(self.stage_of(self.card), "review")
        said = [note for note in self.notes(self.card) if "left this drop in the inbox" in note]
        self.assertEqual(len(said), 1)
        fetch.close_folded(self.cfg, {"asker": "ok"}, self.board)
        fetch.close_folded(self.cfg, {"asker": "ok"}, self.board)
        said = [note for note in self.notes(self.card) if "left this drop in the inbox" in note]
        self.assertEqual(len(said), 1, "the check runs every minute; the note is written once")

    def test_a_drop_the_fetcher_discarded_keeps_its_gate(self):
        closed = fetch.close_folded(self.cfg, {"asker": "ok"}, self.board)
        self.assertEqual(closed, {self.card: "refused"})
        self.assertEqual(self.stage_of(self.card), "review")
        self.assertTrue(any("never reached inbox-applied/" in note for note in self.notes(self.card)))

    def test_a_drop_waiting_on_a_fetcher_that_has_not_run_is_left_alone(self):
        self.write_drop(self.drop)
        self.assertEqual(fetch.close_folded(self.cfg, {}, self.board), {})
        self.assertEqual(fetch.close_folded(self.cfg, {"asker": "failed"}, self.board), {})
        self.assertEqual(self.stage_of(self.card), "review")
        self.assertEqual(self.notes(self.card), [])


    def test_one_pass_folds_the_drop_and_closes_the_card(self):
        """End to end through `once`: the fetcher moves the drop aside and the card closes
        on the same pass, with no second command anywhere."""
        (self.seg / "fetch.py").write_text(FOLDER)
        self.write_drop(self.drop)
        results = fetch.once(self.cfg, segment="asker", changed_only=True, board=self.board)
        self.assertEqual(results, {"asker": "ok"})
        self.assertFalse(self.drop.exists())
        self.assertTrue(self.applied.is_file())
        self.assertEqual(self.stage_of(self.card), "done")

    def test_a_fetcher_that_leaves_the_drop_behind_leaves_the_card_at_review(self):
        (self.seg / "fetch.py").write_text(KEEPER)
        self.write_drop(self.drop)
        self.assertEqual(fetch.once(self.cfg, segment="asker", changed_only=True, board=self.board),
                         {"asker": "ok"})
        self.assertTrue(self.drop.is_file())
        self.assertEqual(self.stage_of(self.card), "review")

    def test_a_deck_written_drop_is_what_changed_only_triggers_on(self):
        """The decisions route writes into `data/inbox/` and an upload into `inbox/` at the
        segment root. `changed_only` picks both up with no rule of its own."""
        (self.seg / "summary.json").write_text("{}")
        self.assertFalse(fetch.inputs_changed(self.seg))
        self.write_drop(self.seg / "data" / "inbox" / "20260918T101500Z-abcd1234-decisions.json")
        self.assertTrue(fetch.inbox_has_work(self.seg))
        self.assertTrue(fetch.inputs_changed(self.seg))
        (self.seg / "data" / "inbox" / "20260918T101500Z-abcd1234-decisions.json").unlink()
        self.assertFalse(fetch.inputs_changed(self.seg))
        # `summary.json` is what the last fetch run left, so an upload is always later than
        # it. Back-dated here because Linux takes inode timestamps from a coarse clock:
        # every write this test makes lands in one tick, so `newer than the stamp` was
        # never true and this last assertion failed on the box while passing on the Mac.
        stamp = self.seg / "summary.json"
        os.utime(stamp, (stamp.stat().st_atime - 2, stamp.stat().st_mtime - 2))
        (self.seg / "inbox").mkdir(parents=True, exist_ok=True)
        (self.seg / "inbox" / "20260918T101500Z-abcd1234-bill.pdf").write_bytes(b"%PDF-")
        self.assertTrue(fetch.sources_changed(self.seg))
