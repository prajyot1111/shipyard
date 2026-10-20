"""The fence the whole suite runs behind: a scrubbed environment, and refusing stand-ins
for the programs that change this machine.

On 2026-09-20 a house on the box ran `python3 -m unittest discover -s tests -t .` in its
worktree and the suite rewrote the LIVE `~/.config/systemd/user/dev.keel.service` to
`ExecStart=.../bin/keel run --roles serve` and restarted it, killing the drain and the
fetchers, and ran `sudo iptables` against the host firewall. Two tests reached past their
temp directories:

- `tests/test_restore.py` ran `bin/keel-restore-seed` for real. On macOS the seed refuses
  ("not the Mac") and the test passes; on Linux nothing refuses it, so it ran apt through
  sudo and handed over to `bin/keel-bootstrap`, which is what wrote the unit;
- `tests/test_door.py` made a house brief, which runs `bin/kb help` (keel/prompts.py), and
  `kb` with no `KEEL_CONFIG` loads the repo's own `keel.toml`, whose `state_dir` is
  `~/keel/state`. That created (and on a real machine would open) the live board.

Neither showed on macOS, where the suite had only ever run. So the suite no longer trusts
a test to remember. `install()` runs once, at the import of `tests/__init__.py`, before any
test module is imported, and does two things on every platform:

- **the environment**: every `KEEL_*` variable the caller had is removed, and `HOME` and
  `XDG_CONFIG_HOME` point at a throwaway directory. A test that forgets an argument then
  resolves `~/keel/state` and `~/.claude` inside the throwaway instead of the real home.
  Tests build their subprocess environments from `os.environ`, so children inherit this;
- **the PATH**: a directory first on `PATH` holds a refusing stand-in for each name in
  `FENCED`. Each one appends its argv, its cwd and its parent's command line to a log and
  exits 97, so the call cannot succeed by accident, and it is recorded even where the
  caller swallows the error (keel/prompts.py swallows `kb help`, keel/service.py reads a
  return code). A test that legitimately needs one of these names puts its own fake
  earlier on `PATH`; the stand-in is only what nobody asked for.

`recorded()` reads the log back. `tests/__init__.py` turns it into an ordinary test at the
end of the run (`FenceCase`), which is what `make test` and a bare
`python3 -m unittest discover -s tests -t .` both show. The `atexit` guard below covers the
entry points that have no package to hook: a single module (`python3 -m unittest
tests.test_door`) and the adapters suite, which discovery imports file by file.
"""

import atexit
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# The programs that change this machine, or ask another one to. `sudo` is here for what it
# would grant, not for itself: the box gives the user passwordless sudo.
FENCED = ("systemctl", "launchctl", "sudo", "loginctl", "iptables", "apt-get", "tailscale")
LOG_VAR = "KEEL_TEST_FENCE_LOG"
REFUSED = 97            # not 1: a refusal must not read like the program's own "no"
GIT_NAME, GIT_EMAIL = "keel tests", "tests@keel.invalid"

# The stand-in is written with the running interpreter in its shebang rather than
# `/usr/bin/env python3`, so it works where python3 is not on the (rewritten) PATH.
STAND_IN = '''#!{python}
"""Refuses, and records. Written by tests/fence.py; see that file for why."""
import os
import sys

NAME = {name!r}


def parent() -> str:
    try:
        if sys.platform.startswith("linux"):
            with open(f"/proc/{{os.getppid()}}/cmdline", "rb") as handle:
                return handle.read().replace(b"\\0", b" ").decode("utf-8", "replace").strip()
        import subprocess
        done = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(os.getppid())],
                              capture_output=True, text=True)
        return done.stdout.strip()
    except OSError:
        return "?"


line = "{{}}\\tcwd={{}}\\tparent={{}}\\n".format(
    " ".join([NAME] + sys.argv[1:]), os.getcwd(), parent())
path = os.environ.get({log_var!r})
if path:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
sys.stderr.write("the test suite's fence refused: " + line)
sys.exit({refused})
'''

_root: Path | None = None
_reported = False
real_home: Path | None = None       # the caller's HOME, kept only so a test can say so
# The caller's whole environment as it was before the scrub. Its readers: the parallel
# runner (`tests/parallel.py`), which starts the adapters suite and the voice selftest beside
# this one exactly as the Makefile would, each behind its own fence; the selector
# (`tests/selector.py`), which runs what it chose the same way; and `caller()` below, which
# `make drift`'s checks (`tests/installdrift.py`, `tests/publiccheck.py`) read it through.
caller_env: dict[str, str] = {}


def caller() -> dict:
    """The environment of whoever ran this, as it was before the scrub: what a check run as
    a module of this package (`make drift`'s `tests.installdrift` and `tests.publiccheck`)
    reads the caller's install and names from. A test never reads it; it hands its own in.
    A copy on both branches, so no reader changes what the runner and the selector start
    their children with (r2.F7)."""
    return dict(caller_env) if caller_env else dict(os.environ)


def install() -> Path:
    """Scrub the environment and put the stand-ins first on PATH. Idempotent: the adapters
    suite asks for the fence from every one of its test modules."""
    global _root
    if _root is not None:
        return _root
    _root = Path(tempfile.mkdtemp(prefix="keel-test-fence-"))
    caller_env.update(os.environ)
    scrub(os.environ, _root)
    write_stand_ins(_root / "bin")
    os.environ["PATH"] = os.pathsep.join([str(_root / "bin"), os.environ.get("PATH", "")])
    os.environ[LOG_VAR] = str(_root / "calls.log")
    stand_in_probes()
    atexit.register(_at_exit)
    return _root


# What the browser step's probe answers in a test (`keel/browserinstall.py` `probe`).
NODE = {"ok": True, "said": "v22.0.0"}


def stand_in_probes() -> None:
    """The probes the PATH stand-ins cannot cover, replaced at their seam (c-678 review F18).
    `node` cannot be fenced by name: the deck's fixture tests run the real one. So the one
    place the app asks node for its version, the browser step, asks through
    `browserinstall.probe`, and a test gets this answer unless it puts the real probe back
    (`tests/test_browserinstall.py`). A suite with no `keel` on its path has no such step."""
    try:
        from keel import browserinstall     # noqa: PLC0415 - after the scrub, never before
    except ImportError:
        return
    browserinstall.probe = lambda: dict(NODE)


def scrub(environ, root: Path) -> None:
    """Drop the caller's `KEEL_*` and point `HOME` at a throwaway directory.

    A house on the box runs with `KEEL_HOME` naming the LIVE checkout, plus `KEEL_HOST`,
    `KEEL_CARD` and sometimes `KEEL_CONFIG` and `KEEL_TOKEN`. Inherited, they decide which
    board a test's subprocess opens. `HOME` matters as much: the repo's own `keel.toml`
    says `state_dir = "~/keel/state"`, so a child that falls back to it lands on the live
    state directory however well the `KEEL_*` names were handled.
    """
    for key in [key for key in environ if key.startswith("KEEL_")]:
        environ.pop(key)
    home = root / "home"
    (home / ".config").mkdir(parents=True, exist_ok=True)
    global real_home
    real_home = Path(environ.get("HOME") or Path("~").expanduser())
    environ["HOME"] = str(home)
    environ["XDG_CONFIG_HOME"] = str(home / ".config")
    # A commit needs an author, and with `HOME` moved there is no `~/.gitconfig` to read.
    # Given here rather than written with `git config`, which in a worktree goes through to
    # the shared `.git/config` and would stamp this name on the human's own commits.
    environ.update(GIT_AUTHOR_NAME=GIT_NAME, GIT_AUTHOR_EMAIL=GIT_EMAIL,
                   GIT_COMMITTER_NAME=GIT_NAME, GIT_COMMITTER_EMAIL=GIT_EMAIL)


def write_stand_ins(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in FENCED:
        path = directory / name
        path.write_text(STAND_IN.format(python=sys.executable, name=name, log_var=LOG_VAR,
                                        refused=REFUSED))
        path.chmod(0o755)


def recorded() -> list[str]:
    """The calls the stand-ins refused, one line each, oldest first."""
    path = os.environ.get(LOG_VAR)
    if not path or not Path(path).exists():
        return []
    return [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def report(lines: list[str]) -> str:
    return ("the test suite reached for programs that change this machine:\n  "
            + "\n  ".join(lines)
            + "\n\nEach line is a test running the real program. Give that test its own "
              "fake manager, fake runner or fake on PATH; see tests/fence.py.")


def _at_exit() -> None:
    """The last word for the entry points with no package to hook. `FenceCase` has already
    said it under `discover -s tests`, so this only speaks when nothing else did."""
    lines = recorded()
    if _root is not None:
        shutil.rmtree(_root, ignore_errors=True)
    if lines and not _reported:
        sys.stdout.flush()
        sys.stderr.write("\n" + report(lines) + "\n")
        sys.stderr.flush()
        os._exit(1)


class FenceCase(unittest.TestCase):
    """Appended after every other test by `tests/__init__.py`'s `load_tests`."""

    def test_nothing_reached_the_machine(self):
        global _reported
        _reported = True
        lines = recorded()
        self.assertEqual(lines, [], report(lines))
