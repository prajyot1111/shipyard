"""What a move of main refreshes, and the stamps each long-lived piece checks (c-538, r-14).

The drain and the deck restart when HEAD moves (their code-moved check), once nothing they
hold would be cut (`keel/restart.py`). Three other pieces
run for days and carry what they started with, so each notes a STAMP of the paths it runs on
and acts at its own safe moment once the stamp moved:

- the voice gateway (`voice/harbor_voice/codewatch.py`): `GATEWAY_PATHS` (`voice/`, its
  script, `keel/configpath.py` and `keel/childenv.py`), restarted when it
  is quiet;
- the voice conversation (`harbormsg.rotation_due`): `memory_stamp`, retired at the start of
  its next Harbor turn;
- the phone talker (`talker.upkeep`): `memory_stamp`, rotated at its next turn boundary.

`memory_stamp` is the install's memory repo's `talker/` once the install holds it (c-722),
its rulebook included (landing B), with the code's shipped rulebook while the install has
none of its own and its memory was seeded from the template (c-726 r1.F5); `MEMORY_PATHS`
in the checkout until then.

A stamp is what `git ls-tree HEAD` says of those paths: the tree and blob ids, so it moves
only when their committed content does. Harbor's own memory writes are not committed and
move nothing; a deploy or his own commit to main does. It is read from HEAD, never from the
diff of one deploy, so a checkout that moved some other way refreshes the same way. The deploy worker only DESCRIBES, with `effects`, what those
checks will do; it restarts nothing itself.

Stdlib only and 3.10-clean: the voice gateway imports it on its own interpreter.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from keel import memoryroot

# `voice/`, the gateway's script, and the two `keel/` modules it holds a RULE from for as
# long as it runs (c-711): which toml to read (`configpath`, asked once at import) and what a
# child may inherit (`childenv`). Its `kb` children load both afresh, so a gateway left on
# the old copy would disagree with them.
# `memoryroot` (c-722) is where it reads the talker's memory from, for the same reason.
GATEWAY_PATHS = ("voice", "bin/keel-voice-gateway", "keel/configpath.py", "keel/childenv.py",
                 "keel/memoryroot.py")
# Harbor's durable memory and its rulebook. Once the install holds the memory (c-722) it is
# stamped there instead (`memory_stamp`), the rulebook beside it (`memory/talker/CLAUDE.md`,
# landing B); the code's shipped rulebook is read only while the install has none of its
# own and its memory was seeded from the template (`memory_stamp`). `talker/memory` is where a checkout kept the memory before the move.
RULEBOOK = (memoryroot.TEMPLATE[memoryroot.TALKER] / memoryroot.RULEBOOK).as_posix()
MEMORY_PATHS = ("talker/memory", RULEBOOK)
GIT_SECONDS = 10

# The drain and the deck restart by the same check (c-557), worded for one machine (c-634).
ENGINE = ("the drain and the deck restart between passes, once no conversation or house call "
          "is open")
GATEWAY = "the voice gateway restarts once it is quiet"
MEMORY = ("Harbor's memory changed: the voice conversation retires at its next Harbor turn, "
          "and the phone talker rotates at its next turn boundary")


def stamp(root: str | Path, paths: tuple[str, ...]) -> str | None:
    """The committed ids of `paths` at HEAD, one `mode type id\\tpath` line each, or None when
    git cannot say (not a checkout, a timeout). None is UNKNOWN, and unknown never refreshes
    anything: the same rule as the drain's code-moved check."""
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-tree", "HEAD", "--", *paths],
                              capture_output=True, text=True, timeout=GIT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return "\n".join(sorted(done.stdout.strip().splitlines()))


def memory_stamp(root: str | Path, install: str | Path | None = None) -> str | None:
    """The talker's memory stamp (c-722): the install's memory repo once it holds the
    talker's memory (`keel/memoryroot.py`), its rulebook among it; the checkout's
    `MEMORY_PATHS` until then. Unknown when either half is.

    The rulebook half follows the same rule as `talker.Paths.rules_src` (c-726 r1.F5): once
    the install has a rulebook of its own, on disk (what the talker links, r2.F5) or at the
    memory repo's HEAD, the template is no part of the stamp, and the own one moves it as the
    rest of the memory does, by its commits; else the code's shipped one, but only for a
    memory seeded from the template (`memoryroot.seeded`); else none, so a template commit
    never rotates a talker that does not read it."""
    home = Path(install) if install else None
    if not memoryroot.in_install(memoryroot.TALKER, home):
        return stamp(root, MEMORY_PATHS)
    own = stamp(memoryroot.root(home), (memoryroot.TALKER,))
    if (memoryroot.install_dir(memoryroot.TALKER, home) / memoryroot.RULEBOOK).is_file() \
            or stamp(memoryroot.root(home), (f"{memoryroot.TALKER}/{memoryroot.RULEBOOK}",)) \
            or not memoryroot.seeded(memoryroot.TALKER, home):
        return own
    rules = stamp(root, (RULEBOOK,))
    return None if own is None or rules is None else f"{own}\n{rules}"


def touches(changed: list[str], paths: tuple[str, ...]) -> bool:
    """Whether any changed file is one of `paths` or under one."""
    return any(name == path or name.startswith(path.rstrip("/") + "/")
               for name in changed for path in paths)


def effects(changed: list[str]) -> list[str]:
    """What a move of main over these changed files refreshes, in words, in the order it
    happens. Nothing when nothing changed."""
    if not changed:
        return []
    said = [ENGINE]
    if touches(changed, GATEWAY_PATHS):
        said.append(GATEWAY)
    if touches(changed, MEMORY_PATHS):
        said.append(MEMORY)
    return said
