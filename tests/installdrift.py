"""The install half of `make drift` (c-722 r1.F7): the words of each pack the install holds.

The Makefile's loop greps each `packs/<name>/drift-terms` of the tree against every file
outside that pack and docs/. Once an owner's pack is moved into the install, its terms are
there and not in the tree, so this reads the install's packs too, when `KEEL_CONFIG` names
an install (`packs.install_packs`, the same reading `packs.configured_drift_terms` gives the
tests): each pack's terms against every file of the tree outside docs/ and outside a pack of
the same name in the tree. A hit fails the check.

It runs as a module of the `tests` package, whose import puts up the test fence
(`tests/fence.py`), and the fence drops every `KEEL_*`. So the install is the one the CALLER
named, read from the environment as it was before the fence (`fence.caller`, c-733): read
from this process's own, it was never any install, and the check passed having read nothing.
A `~` in it is the caller's `HOME`, not the fence's (`packs.expand_home`, r1.F2).
It says which install's terms it read, or that none was named and so no install's terms were
checked. It passes with no install only when `KEEL_CONFIG` is unset, names the code's own
config, or names the demo sandbox's (its `keel.toml`, a file beside a `.keel-sandbox`
marker, r3.F3); any
other file named that is not an install's `config.toml` fails it, saying why (r1.F3). An install named whose terms cannot be read (its `config.toml` is not there, or a
`drift-terms` will not read) fails the check: it never passes for terms it could not read.

Run as `python3 -m tests.installdrift` (`make drift` does). It prints how many terms it read,
never a term, and each file a term is in with how many lines hold one: never a line's text,
and nothing grep prints but a name it was handed and a count (r1.F1, r2.F1). A file's
PATH is read too: one that holds a term is a hit even with clean contents, and a path that
holds one is printed masked, its terms as `<pack term>` where Python reads every term as
grep does and grep finds none left, else no part of it at all (r3.F1).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from keel import configpath, packs
from tests import fence, publiccheck

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 200
ANSWERED = (0, 1)                  # grep found, or found nothing; any other exit is a failure
SANDBOX_MARK = ".keel-sandbox"     # demo/sandbox/setup MARKER: what makes a directory the sandbox


def tree_files(root: Path) -> list[str]:
    done = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                          capture_output=True, text=True, check=True)
    return [name for name in done.stdout.split("\0") if name]


def hits(root: Path, files: list[str], terms: list[str]) -> list[str]:
    """`<file>: <n> hit(s)` for each of `files` under `root` holding any of `terms` (extended
    regexes, any case). Nothing grep prints is echoed but a name it was handed and a count
    of digits (r1.F1, r2.F1): a matched line holds the term, and no splitting of grep's text
    can be trusted to keep it out. grep is asked for names only (`-l`, NUL-ended), then for
    each name, alone, its count (`-c`)."""
    patterns = [arg for term in terms for arg in ("-e", term)]
    named = set(by_name(root, files, patterns))
    within, unread = matching(root, [name for name in files if (root / name).is_file()], patterns)

    def show(name: str) -> str:
        return shown(root, name, terms, patterns) if name in named else name

    found = [f"{show(name)}: could not be read" for name in unread]
    counts = {}
    for name in within:
        done = grep(root, ["-c", *patterns, "--", name])
        count = done.stdout.strip()
        if done.returncode not in ANSWERED or not count.isdigit():
            raise SystemExit(f"drift: grep did not count the install's terms in {show(name)}")
        counts[name] = int(count)
    for name in [name for name in files if name in named or name in counts]:
        said = [f"{counts[name]} hit{'' if counts[name] == 1 else 's'}"] if name in counts else []
        said += ["its path holds a term"] if name in named else []
        found.append(f"{show(name)}: {', and '.join(said)}")
    return found


def by_name(root: Path, files: list[str], patterns: list[str]) -> list[str]:
    """The names among `files` that themselves hold a term (r3.F1): a file is NAMED as well
    as written, and its name is what this check prints. Read from grep's count over the
    NUL-ended names and, when it is not 0, its exit code for each name alone: nothing grep
    prints is read but a count of digits."""
    done = grep(root, ["-zc", *patterns], b"\0".join(map(os.fsencode, files)))
    count = done.stdout.strip()
    if done.returncode not in ANSWERED or not count.isdigit():
        raise SystemExit("drift: grep did not count the install's terms in the tree's file names")
    if count == b"0":
        return []
    found = [name for name in files if holds(root, name, patterns)]
    if not found:
        raise SystemExit("drift: grep counted the install's terms in the tree's file names, "
                         "but named none")
    return found


def holds(root: Path, text: str, patterns: list[str]) -> bool:
    """Whether `text` holds any of the terms, by grep's own reading of them."""
    code = grep(root, ["-zq", *patterns], os.fsencode(text)).returncode
    if code not in ANSWERED:
        raise SystemExit("drift: grep failed on the install's terms")
    return code == 0


def shown(root: Path, name: str, terms: list[str], patterns: list[str]) -> str:
    """A name that holds a term, as it may be printed: each term masked as the public check
    masks a path (`publiccheck.shown`), where Python reads every term as grep does, and the
    result read again by grep; else no part of it at all."""
    if all(publiccheck.compiles(term) for term in terms):
        pattern = re.compile("|".join(f"(?:{term})" for term in terms), re.I)
        masked = publiccheck.shown(name, [("pack term", pattern)])[0]
        if not holds(root, masked, patterns):
            return masked
    return "<a path that holds a pack term>"


def matching(root: Path, files: list[str], patterns: list[str]) -> tuple[list[str], list[str]]:
    """The names among `files` grep finds `patterns` in, each checked to be one it was handed,
    and those it could not read (r2.F2): a handed name its error output names, never its
    words. `files` are regular files that are there: a tracked file deleted from the disk is
    not an error."""
    handed, found, unread = set(files), [], []
    for start in range(0, len(files), CHUNK):
        chunk = files[start:start + CHUNK]
        done = grep(root, ["-l", "--null", *patterns, "--", *chunk])
        if done.returncode not in (*ANSWERED, 2):
            raise SystemExit("drift: grep failed on the install's terms")
        names = [raw.decode("utf-8", "surrogateescape") for raw in done.stdout.split(b"\0") if raw]
        kept = [name for name in names if name in handed]
        if len(kept) < len(names) or (done.returncode == 0 and not kept):
            # r3.F2: a listing that is not the names it was handed is not read as a pass
            raise SystemExit("drift: grep's list of matching files was not the files it was "
                             "handed, so the install's terms were not checked")
        found += kept
        if done.returncode > 1:
            failed = [name for name in chunk if os.fsencode(name) in done.stderr]
            if not failed:
                raise SystemExit("drift: grep failed on the install's terms")
            unread += failed
    return found, unread


def grep(root: Path, argv: list[str], text: bytes | None = None) -> subprocess.CompletedProcess:
    """grep over the tree's files, or over `text` (names, NUL-ended under `-z`), in bytes:
    what it prints is never decoded as text here. Files that read as binary are skipped
    (`-I`); names never are."""
    skips = ["-d", "skip", "-I"] if text is None else []
    return subprocess.run(["grep", *skips, "-iE", *argv], cwd=root, capture_output=True, input=text)


def main(root: Path = ROOT, environ: dict | None = None) -> int:
    """`environ` is a test's; left out, the caller's, as it was before the fence."""
    environ = fence.caller() if environ is None else environ
    own = packs.install_packs(environ)
    if own is None:
        return not_an_install(environ.get("KEEL_CONFIG"), environ)
    terms = read_terms(own)
    if terms is None:
        return 1
    if not terms:
        print(f"drift: the install at {own.parent} has no pack with drift terms, none checked")
        return 0
    files = tree_files(root)
    failed = False
    for name, words in sorted(terms.items()):
        outside = [path for path in files if not path.startswith(("docs/", f"packs/{name}/"))]
        found = hits(root, outside, words)
        if found:
            print(f"drift: the install's {name} pack's vocabulary outside it ({own / name}):")
            print("\n".join(found))
            failed = True
    if not failed:
        count = sum(len(words) for words in terms.values())
        print(f"drift: the install at {own.parent}: {count} term{'' if count == 1 else 's'} read, none in the tree")
    return 1 if failed else 0


def not_an_install(named: str | None, environ) -> int:
    """No install is named: a pass only when `KEEL_CONFIG` is unset, names the code's own
    config (`configpath.own_configs`), or names the demo sandbox's `keel.toml`, there as a
    file beside its `.keel-sandbox` marker (r3.F3); any other file named is a
    misconfiguration whose terms were not read, so it fails, saying why (r1.F3)."""
    if not named:
        print("drift: no install named (KEEL_CONFIG), so no install's terms were checked")
        return 0
    path = packs.expand_home(named, environ).resolve()
    if path in configpath.own_configs(packs.PACKAGE):
        print(f"drift: KEEL_CONFIG names the code's own config ({path}), so no install's terms were checked")
        return 0
    if path.name == configpath.SHIPPED_CONFIG and path.is_file() and (path.parent / SANDBOX_MARK).is_file():
        # r3.F3: the demo sandbox's toml, named on purpose (`demo/sandbox/run`)
        print(f"drift: KEEL_CONFIG names the demo sandbox's config ({path}), so no install's terms were checked")
        return 0
    print(f"drift: KEEL_CONFIG names {path}, which is not an install's config.toml outside the code, "
          f"so no install's terms could be read")
    return 1


def read_terms(own: Path) -> dict[str, list[str]] | None:
    """The install's packs' terms, each pack with any; None, said in one line, when they
    cannot be read."""
    config = own.parent / "config.toml"
    if not config.is_file():
        print(f"drift: KEEL_CONFIG names {config}, which is not there, so its pack terms cannot be read")
        return None
    try:
        listed(own)
        found = packs.drift_terms(own.parent)
    except (OSError, UnicodeDecodeError) as error:
        print(f"drift: the install's pack terms under {own} cannot be read ({type(error).__name__})")
        return None
    return {name: words for name, words in found.items() if words}


def listed(own: Path) -> None:
    """List `<install>/packs` and each pack in it, raising where one cannot be: the glob
    `packs.drift_terms` reads them with skips a directory it may not list (r1.F4). An
    install with no `packs` at all has nothing to list; a link to nothing, there or for a
    pack, is not that, and each pack's `drift-terms` is stat'ed outright, so a pack that may
    be listed but not searched (`r--`) raises too (r2.F4)."""
    if not own.exists():
        if own.is_symlink():
            raise FileNotFoundError(own)
        return
    for pack in list(own.iterdir()):
        if pack.is_symlink() and not pack.exists():
            raise FileNotFoundError(pack)
        if pack.is_dir():
            list(pack.iterdir())
            terms = pack / packs.DRIFT_TERMS
            try:
                os.stat(terms)
            except FileNotFoundError:
                if terms.is_symlink():         # a link to nothing; else a pack with no terms
                    raise


if __name__ == "__main__":
    sys.exit(main())
