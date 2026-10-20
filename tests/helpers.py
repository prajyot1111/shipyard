"""Shared test scaffolding: a board in a temporary directory, a scratch keel.toml, a scratch
`Config` with a throwaway git repo, and a fake harness that never runs `claude`."""

import os
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from keel import harness, machine
from keel.board import Board
from keel.config import Config, Space

ROOT = Path(__file__).resolve().parent.parent
SESSION = "0abc1234-0000-4000-8000-000000000001"
# How often a test's server looks for `shutdown()`. The stdlib's half second was paid in
# the teardown of every test that served something (tests/test_serving_helper.py).
SERVE_POLL = 0.05


def left_out(path: str) -> bool:
    """A path the public release leaves out (`export-ignore` in `.gitattributes`, c-804),
    in a tree made from that release: NOTICE and the Atlas still name it for the repo that
    holds it, and a test that holds them to the tree lets it be absent there. Only where the
    left-out folder itself is absent: in the repo that holds it, a missing file still fails."""
    attributes = ROOT / ".gitattributes"
    ignored = [line.split()[0].rstrip("/") for line in
               (attributes.read_text(encoding="utf-8").splitlines() if attributes.is_file() else [])
               if "export-ignore" in line.split()[1:]]
    return any((path == top or path.startswith(top + "/")) and not (ROOT / top).exists()
               for top in ignored)


def serve_in_background(server) -> threading.Thread:
    """`server.serve_forever` on a daemon thread, polling fast enough that `shutdown()`
    returns at once rather than after the stdlib's default half second."""
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": SERVE_POLL},
                              daemon=True)
    thread.start()
    return thread


def own_options(card: dict) -> dict:
    """A card's options without `provenance`, which the card resolver writes on every
    create (`keel/cardspec.py`): what a test about some other option compares."""
    return {key: value for key, value in (card.get("options") or {}).items()
            if key != "provenance"}


def make_repo(path: Path) -> Path:
    """A throwaway git repo with one commit, identity passed inline (never `git config`)."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "main"], check=True)
    (path / "README").write_text("scratch\n")
    subprocess.run(["git", "-C", str(path), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@x",
                    "commit", "-q", "-m", "init"], check=True)
    return path


def make_config(directory: Path, repos: dict[str, Path] | None = None, houses_max: int = 3,
                drain_paused: bool = False, reviews_max: int = 2,
                projects_dir: Path | None = None) -> Config:
    """A Config whose state and adapters live under `directory`; contracts from the repo.

    `projects_dir` is the personal space's, as `keel.toml` gives it: a card may name a repo
    that is not listed when it is a project directory under this one.
    """
    adapters_dir = directory / "adapters"
    # `house_review` is on by default since c-633 (the schema's, as the example ships it); the
    # suite's houses do not run the pipeline unless a test turns it on.
    spaces = {
        "personal": Space(name="personal", config_dir=directory / "cfg-personal",
                          repos=dict(repos or {}), contract=ROOT / "etc" / "space-personal.md",
                          adapter=None, deny=["mcp__claude_ai_Slack", "mcp__claude-in-chrome"],
                          projects_dir=projects_dir, house_review=False),
        "work": Space(name="work", config_dir=directory / "cfg-work", repos={},
                      contract=ROOT / "etc" / "space-work.md", adapter="work",
                      adapter_dir=adapters_dir / "work", deny=["mcp__claude-in-chrome"],
                      house_review=False),
    }
    # `home` UNDER THE TEMPORARY DIRECTORY, ALWAYS. The keys a machine holds live under it
    # (`keel/voice.py`'s credentials directory, and with it the shared house key of V12
    # slice 2), so a test that mints one must have no way of writing into his real
    # `~/.config/keel/credentials`.
    config = Config(root=ROOT, state_dir=directory / "state", houses_max=houses_max,
                    reviews_max=reviews_max, poll_seconds=1, drain_paused=drain_paused,
                    segments_dir=directory / "segments", adapters_dir=adapters_dir,
                    serve_port=0, lavish_port=0, spaces=spaces, home=directory / "home")
    config.ensure_dirs()
    return config


def signed_in(cfg: Config) -> Config:
    """Every space's config dir holds a login, as a working machine's do: a drain pass checks
    the Logins list, and a dir with none reads expired and holds its houses (c-560). The
    file is empty of secrets; the probe itself stays the fake harness's."""
    for space in cfg.spaces.values():
        space.config_dir.mkdir(parents=True, exist_ok=True)
        (space.config_dir / ".credentials.json").write_text("{}")
    return cfg


def superuser_builder(cfg: Config) -> Config:
    """Builder mode as the superuser over Keel's repo, the box's own (`keel/builder.py`)."""
    cfg.bosun_builder = True
    cfg.builder = {"superuser": True, "repos": ["keel"]}
    return cfg


class FakeHarness:
    """Stands in for `keel.harness` in house and drain tests; records every call."""

    HarnessError = harness.HarnessError

    def __init__(self):
        self.rows: list[dict] = []
        self.starts: list[dict] = []
        self.resumes: list[dict] = []
        self.fail: str | None = None
        self.logs_text = ""
        self.said = ""
        self.on_start = None
        self.app_link = "https://claude.ai/code/session_01Q7n8exxgqsxNsR3b2Fwi8J"
        self.links_asked: list[str] = []
        self.streamed = False
        # a resume that mints a new session answers with this id (c-651 review); None keeps it
        self.resumed_as: str | None = None
        # a start answers with this id rather than SESSION, for a card that already holds it
        self.started_as: str | None = None
        # c-654: sessions whose conversation the harness no longer holds (their transcript
        # passed its retention). `conversation_gone` says so; a resume of one still launches
        # normally, keeps its id, and the session then fails (`failed`) with no turn.
        self.gone: set[str] = set()
        self.failed: list[str] = []

    def start_bg(self, cwd, prompt, **kwargs):
        if self.fail:
            raise harness.HarnessError(self.fail)
        self.starts.append(dict(kwargs, cwd=cwd, prompt=prompt))
        if self.on_start:
            self.on_start(kwargs["name"])
        minted = self.started_as or SESSION
        return {"bg_id": minted[:8], "session_id": minted}

    def conversation_gone(self, session_id, *, cwd, config_dir):
        # every question, with where it was asked: the cwd and config dir the resume would use
        self.gone_asked = getattr(self, "gone_asked", []) + [(session_id, str(cwd), str(config_dir))]
        return session_id in self.gone

    def resume_bg(self, session_id, prompt, **kwargs):
        self.resumes.append(dict(kwargs, session_id=session_id, prompt=prompt))
        if session_id in self.gone:
            self.failed.append(session_id)
            return {"bg_id": session_id[:8], "session_id": session_id}
        minted = self.resumed_as or session_id
        return {"bg_id": minted[:8], "session_id": minted}

    # The two a connected turn uses (`keel/converse.py`): one synchronous turn into a
    # stopped session, and the flagless wake that puts it back.
    TURN_TIMEOUT = harness.TURN_TIMEOUT

    def turn(self, session_id, prompt, **kwargs):
        self.turns = getattr(self, "turns", []) + [dict(kwargs, session_id=session_id,
                                                        prompt=prompt)]
        if getattr(self, "turn_fails", None):
            raise harness.HarnessError(self.turn_fails)
        return {"is_error": False, "result": getattr(self, "answer", "I did, yes.")}

    def turn_answer(self, payload):
        return harness.turn_answer(payload)

    def stream_text(self, record):
        return harness.stream_text(record)

    def turn_streamed(self, session_id, prompt, *, on_record=None, **kwargs):
        """The same turn with a listener on it (V5). `records` is what it streams."""
        self.streamed = True
        for record in getattr(self, "records", ()):
            if on_record is not None:
                on_record(record)
        return self.turn(session_id, prompt, **kwargs)

    def open_conversation(self, session_id, **kwargs):
        """A kept-alive conversation (V12). A test that wants one replaces this name;
        the default refuses loudly, so a fake can never quietly start a real process."""
        raise harness.HarnessError("this fake was not given a conversation")

    def wake(self, session_id, *, cwd, config_dir, name=None):
        self.wakes = getattr(self, "wakes", []) + [session_id]
        if getattr(self, "on_wake", None):
            self.on_wake()
        if getattr(self, "wake_fails", False):
            raise harness.HarnessError("claude --resume --bg failed")
        return {"bg_id": session_id[:8], "session_id": getattr(self, "woken", None) or session_id}

    # A message into a live house (`keel/tellhouse.py`, c-598) runs its relay through this.
    # Unarmed it refuses, so a test that never meant to tell a house falls back to the resume
    # it expected and never runs a real `claude`; `relay_answer` arms it: "sent" (a stream
    # `relay.relayed` accepts), "failed" (certainly not delivered) or "unclear" (no result).
    relay_answer = None

    def run(self, argv, *, cwd=None, env=None, timeout=120):
        self.relays = getattr(self, "relays", []) + [dict(argv=list(argv), cwd=str(cwd), env=env)]
        if self.relay_answer is None:
            raise harness.HarnessError("this fake was not given a relay")
        head, _, message = argv[-1].partition("\nmessage:\n")
        send = {"type": "tool_use", "id": "t1", "name": "SendMessage",
                "input": {"to": head.removeprefix("to: "), "message": message}}
        text = ('{"success":%s,"message":"-> (another Claude session on this machine)"}'
                % ("true" if self.relay_answer == "sent" else "false"))
        lines = [{"type": "assistant", "message": {"content": [send]}}]
        if self.relay_answer != "unclear":
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": text}]}]}})
        lines.append({"type": "result", "result": "SENT"})
        stdout = "\n".join(__import__("json").dumps(line) for line in lines)
        return subprocess.CompletedProcess(["claude", *argv], 0, stdout, "")

    def remote_link(self, bg_id, config_dir=None):
        self.links_asked.append(bg_id)
        return self.app_link

    # `listing_fails`: `claude agents` itself fails, which the plain listing answers with an
    # empty list and a strict one with an error (`harness.agents`).
    listing_fails = False

    def agents(self, config_dir=None, all_sessions=False, strict=False):
        if self.listing_fails:
            if strict:
                raise harness.HarnessError("claude agents exited 1")
            return []
        return list(self.rows)

    # The login probe (`keel/login.py`): a login that works unless a test says otherwise
    # (`login_answer`, what the probe prints and its exit code). Every probe is recorded.
    login_answer = ("ok", 0)

    def login_probe(self, config_dir, *, cwd, timeout):
        self.probes = getattr(self, "probes", []) + [str(config_dir)]
        out, code = self.login_answer
        return subprocess.CompletedProcess(["-p"], code, out + "\n", "")

    # The two a drop-in command is written with (`keel/dropin.py`).
    is_default_config_dir = staticmethod(harness.is_default_config_dir)

    @staticmethod
    def claude_bin():
        return "claude"

    def agents_across(self, config_dirs):
        self.listed_dirs = [str(d) for d in config_dirs]
        return list(self.rows)

    def find(self, session_id, rows=None):
        return harness.find(session_id, self.rows if rows is None else rows)

    def logs(self, bg_id, config_dir=None):
        self.logs_dir_asked = config_dir
        return self.logs_text

    def stop(self, bg_id, config_dir=None):
        self.stops = getattr(self, "stops", []) + [bg_id]
        if getattr(self, "stop_fails", False):
            raise harness.HarnessError("claude stop failed")
        # A stopped session leaves the listing, which is what every caller reads next.
        self.rows = [row for row in self.rows if row.get("id") != bg_id]

    def last_said(self, transcript_path, n=40):
        return self.said


class FakeMachine:
    """Stands in for `keel.machine` in drain tests: memory and the process table are what
    the test says, and a renice is recorded rather than done."""

    def __init__(self):
        self.memory: int | None = 16384
        self.table: dict[int, tuple[int, int]] | None = {}
        self.reniced: list[tuple[list[int], int]] = []

    def available_mb(self):
        return self.memory

    def process_table(self):
        return self.table

    def tree(self, table, root):
        return machine.tree(table, root)

    def tree_mb(self, table, root):
        return machine.tree_mb(table, root)

    def renice(self, pids, nice):
        self.reniced.append((list(pids), nice))
        return len(pids)


def aged(board, card_id: str, days: int) -> None:
    """Every event the card has so far happened `days` days ago: a house last used that long
    ago, which is the only kind whose conversation the harness can have let go (c-654)."""
    for event in board.events(card_id):
        at = datetime.fromisoformat(event["at"]) - timedelta(days=days)
        board.conn.execute("UPDATE events SET at = ? WHERE id = ?", (at.isoformat(timespec="seconds"), event["id"]))
    board.conn.commit()


def background_row(name: str, session_id: str, status: str = "idle") -> dict:
    return {"pid": 1, "id": session_id[:8], "cwd": "/x", "kind": "background",
            "startedAt": 0, "sessionId": session_id, "name": name, "status": status,
            "state": "working" if status == "busy" else "done"}


class BoardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.board = Board(self.dir / "board.db")

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def card(self, space="personal", title="a card", **kwargs) -> str:
        return self.board.create(space, title, **kwargs)

    def at_building(self, autonomy="autonomous") -> str:
        card_id = self.card(autonomy=autonomy, repo="keel")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        return card_id

    def at_review(self) -> str:
        card_id = self.at_building()
        self.board.stage(card_id, "review", "house", plan_ref="plan.md", output_ref="out.md")
        return card_id


def write_toml(directory: Path) -> Path:
    """A keel.toml whose state_dir is inside `directory`."""
    path = directory / "keel.toml"
    path.write_text(
        "[keel]\n"
        f'state_dir = "{directory / "state"}"\n'
        f'adapters_dir = "{directory / "adapters"}"\n'
        "drain_paused = false\n"
        "[spaces.personal]\n"
        'config_dir = "~/nowhere"\n'
        'contract = "etc/space-personal.md"\n'
        "[spaces.personal.repos]\n"
        'keel = "~/keel"\n'
        'other = "~/nowhere-other"\n'
        'r = "~/nowhere-r"\n'
        "[spaces.work]\n"
        'config_dir = "~/.claude"\n'
        'adapter = "work"\n'
        "[spaces.work.repos]\n"
        'api = "~/nowhere-cloud"\n'
        'r = "~/nowhere-r"\n'
    )
    return path


def give_bosun_key(home: Path) -> str:
    """A shared key under `home`, as both machines hold one, and Bosun's key derived from it
    (`keel/authority.py`): what `KEEL_BOSUN` must hold for a `kb` to be actor bosun."""
    from keel import authority, voice
    path = voice.credentials_dir(home) / "house-key"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("scratch-shared-key-" + home.as_posix() + "\n")
    return authority.key_of(path.read_text())


class CliCase(unittest.TestCase):
    """Runs kb through `keel.cli.main` against a scratch state dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in ("KEEL_CONFIG", "KEEL_TOKEN", "KEEL_CARD", "KEEL_HOME",
                                                     "KEEL_BOSUN", "HOME")}
        for key in self.saved:
            os.environ.pop(key, None)
        os.environ["KEEL_CONFIG"] = str(write_toml(self.dir))
        # A home under the scratch directory (c-522): the shared key, and so Bosun's key, is
        # read from `~/.config/keel/credentials`, never his real one.
        os.environ["HOME"] = str(self.dir / "home")
        self.bosun = give_bosun_key(self.dir / "home")

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    @property
    def token(self) -> str:
        return (self.dir / "state" / "human.token").read_text().strip()


# What the tracked keel.toml was while Keel ran on two machines (before c-610 S1). Kept so
# a test can prove such a config still loads on one machine (c-622).
TWO_MACHINE_TOML = ROOT / "tests" / "fixtures" / "two-machine.toml"



def no_real_tools(test) -> None:
    """Stand in for the two programs a first-run report reaches that the fence does not
    cover (c-678 review F18): `node --version` (the browser step, `browserinstall.probe`,
    which the fence already stands in for in every test) and the harness's listing
    (`harness.agents`, which Meet Bosun's `console.view` asks). Called from a test base's
    `setUp`; a test that needs another answer patches over it."""
    from unittest import mock     # noqa: PLC0415 - only the bases that call this need it
    for name, value in (("keel.browserinstall.probe", {"ok": True, "said": "v22.0.0"}),
                        ("keel.harness.agents", [])):
        patched = mock.patch(name, return_value=value)
        patched.start()
        test.addCleanup(patched.stop)
