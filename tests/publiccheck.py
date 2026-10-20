"""The public check (c-699, c-672 step 5): what in the core tree belongs to one install.

The personal drift check (`tests/personal.py`) skips `docs/`. This one reads `docs/` too, and
lets through only the two short tables below, each entry with its reason. It takes one
install's own names and looks for them in every file git tracks (and every untracked file
that is not ignored):

- the user's **name** and **email**, from git's `user.name` and `user.email`;
- the user's **home path**, and any `/Users/<name>` or `/home/<name>` that is not a stand-in;
- this machine's **host** names, the tailnet hosts the install's config names, and any
  `<host>.ts.net` that is not an `example` one; a bare host that is a common word of a fixed
  list (`keel`, `COMMON_HOSTS`) only where it stands as a host (`as_hosts`, c-725 r2.F5, r3.F5);
- every **pack term** of every pack in the install and in the tree (`packs.drift_terms`);
- any other **email** address that is not on a reserved example domain;
- a **symlink** whose target is absolute or leaves the tree;
- and, given a range of commits (`--range A..B`), each **new image** the range adds (no
  text check can read one) and every line of each **commit message** in it.

A file's PATH is read as its text is: a name in a file name is a finding on line 0.

`make drift` RUNS IT `--strict` (c-722 landing B: one owner's things left the tree): any
finding exits 1, and so does a skipped term of the tree's own packs (a pack's terms are
written for `grep -E`, and one that is not a Python pattern is left out, said in one line; a
skipped term of the install's packs is said and fails nothing, c-726 r1.F8) and a git that
will not list the tree or the range. Without `--strict` it is a report that always exits 0.

WHAT IT LETS THROUGH, and nothing else:

- `LINES`: one line of one file, chosen by its form before any name is read, on which the
  kinds the entry names are not findings: NOTICE's copyright line (`personal.ALLOWED`), and
  a vendored library's own copyright line, which its license keeps as written.
- `WAITING`: a folder of one owner's that leaves the tree by that owner's own hand, its
  findings counted apart and never failing. An entry whose folder is gone fails the suite
  (`tests/test_publiccheck.py`), so the entry goes in the same commit as the folder and the
  table only shrinks.

It prints the path and what KIND, never the line's text and never the term: a finding may
sit beside a secret. The path itself is printed with whatever it holds masked by its kind
(`identity/about-<name>.md`), and so is the top directory the counts are grouped by. A
commit is printed as its short hash.

    python3 -m tests.publiccheck                 # the counts, by kind and by directory
    python3 -m tests.publiccheck --list          # each finding, as path:line: kind
    python3 -m tests.publiccheck --range origin/next..HEAD --strict
    python3 tests/publiccheck.py                 # the same, as a script from anywhere (c-729)

The install is `--install <dir>`, else the one `KEEL_CONFIG` names (an install's
`config.toml`, as `packs.install_packs` reads it), else none: then only git's identity, the
home path, this host and the tree's own packs are known. Whose install a house's worktree or
a public checkout should read is not settled here (c-698 found the question); this takes
what it is given.

This module lives behind the suite's fence (`tests/fence.py`), which moves `HOME` and drops
every `KEEL_*` before anything here runs. The names are the CALLER'S, so they are read from
the environment as it was before the fence (`caller`); a test never reads them at all, it
fills the seams of `install_names`.
"""

import argparse
import os
import re
import socket
import subprocess
import sys
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if not __package__:
    # run as a script (`python3 tests/publiccheck.py`, c-729): the tree it lives in is where
    # `keel` and `tests` are, as `bin/shipyard` finds them
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keel import packs  # noqa: E402
from tests import fence, personal  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# The lines a kind may stand on, each `(path, line form, kinds, why)`: the first line of that
# file whose whole text has that form, decided before any name is read.
LINES = [(path, form, ("name",), why) for path, form, why in personal.ALLOWED] + [
    ("app/vendor/highlight/core.min.js",
     re.compile(r"\(c\) \d{4}-\d{4} [A-Za-z][A-Za-z .'-]* <[^<>\s]+> and other contributors"), ("email",),
     "the vendored library's copyright line, which its BSD-3-Clause license keeps as written"),
]
# The folders whose findings wait for their owner's own removal, each `(prefix, why)`.
OWNER_STEP = ("one owner's own, moved into that owner's install (c-722); the authority guard "
              "refuses any builder's write there, so its removal is the owner's own step, "
              "with this entry taken out of tests/publiccheck.py's WAITING in the same commit")
WAITING = [
]
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".heic", ".avif"}
EMAIL = re.compile(r"([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+([A-Za-z]{2,}))")
EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net", ".example", ".invalid", ".test",
                   ".local", ".localhost")
NOT_A_PERSON = {"noreply", "no-reply", "git"}      # a robot's address, and an ssh remote
TAILNET_IN_CONFIG = re.compile(r"\b((?:[A-Za-z0-9-]+\.)+ts\.net)\b")
WORD_MIN = 4                                       # a shorter name or host matches too much
KINDS = ("name", "email", "home path", "host", "pack term", "symlink", "new image")


@dataclass
class Names:
    """What one install calls its own."""
    names: list = field(default_factory=list)      # words of the user's name, the email's local part
    emails: list = field(default_factory=list)
    home: str = ""
    hosts: list = field(default_factory=list)
    common: list = field(default_factory=list)     # bare hosts that are a common word (`COMMON_HOSTS`)
    terms: list = field(default_factory=list)      # pack drift terms: regular expressions
    skipped: int = 0                               # terms `patterns` could not compile
    tree_terms: list | None = None                 # the terms of the tree's own packs; None: all are
    skipped_tree: int = 0                          # of `skipped`, the tree's own (r1.F8)

    def patterns(self) -> list[tuple[str, re.Pattern]]:
        """`(kind, pattern)` for each list that holds something, compiled once. A pack's
        terms are written for `grep -E`: one that Python cannot compile is left out and
        counted in `skipped`, never raised and never printed."""
        found = []
        for kind, words in (("name", self.names), ("email", self.emails)):
            if words:
                found.append((kind, whole_words(words)))
        if self.hosts:
            found.append(("host", as_hosts(self.hosts, self.common)))
        if self.home:
            found.append(("home path", re.compile(re.escape(self.home.rstrip("/")) + r"(?![\w.-])")))
        terms = [term for term in self.terms if compiles(term)]
        self.skipped = len(self.terms) - len(terms)
        own = self.terms if self.tree_terms is None else self.tree_terms
        self.skipped_tree = sum(1 for term in self.terms if term in own and term not in terms)
        if terms:
            found.append(("pack term", re.compile("|".join(f"(?:{term})" for term in terms), re.I)))
        return found


class Unread(Exception):
    """Git did not answer, so the tree or the range was not read. Its text says which, and
    never what git said: git's own line can carry a name."""


def compiles(term: str) -> bool:
    """Whether Python reads `term` as grep does. A POSIX class (`[[:space:]]`) compiles with
    a warning and means something else, so a warning counts as not read."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            re.compile(f"(?:{term})", re.I)
        except (re.error, Warning):
            return False
    return True


def whole_words(words: list[str]) -> re.Pattern:
    """Any of `words` as a whole word, in any case (so `ada` is not found in `adapter`)."""
    body = "|".join(re.escape(word) for word in sorted(set(words), key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])", re.I)


# Where a host that is a common word stands as a host (c-725 r2.F5): a machine may be called
# `keel` or `harbor`, words this tree says on every page.
LOCAL_SUFFIX = r"(?:[A-Za-z0-9-]+\.)*(?:local|lan|home|internal|ts\.net)(?![A-Za-z0-9-])"


def as_hosts(hosts: list[str], common: list[str] = ()) -> re.Pattern:
    """Any of `hosts` as a whole word (`ada-mac` in prose, in a config line, in a command),
    except a bare one in `common`, a common word (`COMMON_HOSTS`): that one only where it stands
    as a host, in a URL (`//keel`), after an @, or as the first label of a local or tailnet
    name (`keel.local`)."""
    common = {host.lower() for host in common}
    plain = sorted({host for host in hosts if host.lower() not in common}, key=len, reverse=True)
    words = sorted({host for host in hosts if host.lower() in common}, key=len, reverse=True)
    parts = [rf"(?<![A-Za-z0-9])(?:{'|'.join(map(re.escape, plain))})(?![A-Za-z0-9])"] if plain else []
    if words:
        body = "|".join(map(re.escape, words))
        parts.append(rf"(?:(?<=//)|(?<=@))(?:{body})(?![A-Za-z0-9-])")
        parts.append(rf"(?<![A-Za-z0-9.-])(?:{body})\.{LOCAL_SUFFIX}")
    return re.compile("|".join(parts), re.I)


# THE WORDS A MACHINE MAY BE CALLED THAT THE TREE ITSELF SAYS (c-725 r3.F5): Keel's own product
# words and plain dictionary words for a machine. A fixed list, never read off the tree under
# check, so a machine's own name that has leaked into the tree cannot make itself common.
COMMON_HOSTS = frozenset({
    "keel", "harbor", "shipyard", "bosun", "deck", "drain", "board", "house", "talker", "voice",
    "dock", "anchor", "mast", "helm", "hull", "sail", "port", "ship", "boat",
    "mac", "macbook", "laptop", "desktop", "server", "home", "work", "office", "studio", "mini",
    "air", "pro", "box", "dev", "main", "test", "build", "linux", "ubuntu", "debian", "pi",
})


def common_words(hosts: list[str]) -> list[str]:
    """The bare hosts that are a common word (`COMMON_HOSTS`), found only where they stand as
    a host; every other host is found as a whole word anywhere."""
    return [host for host in hosts if host.lower() in COMMON_HOSTS]


def tracks(root: Path, prefix: str) -> bool:
    """Whether git tracks anything under `prefix` in `root` (c-726 r1.F8): an untracked
    leftover of a removed folder is not the folder."""
    done = subprocess.run(["git", "-C", str(root), "ls-files", "--", prefix],
                          capture_output=True, text=True)
    return done.returncode == 0 and bool(done.stdout.strip())


def caller() -> dict:
    """The environment of whoever ran this, as it was before the fence scrubbed it."""
    return fence.caller()


def git_value(root: Path, key: str) -> str:
    """The caller's git setting `key`, or nothing."""
    done = subprocess.run(["git", "-C", str(root), "config", "--get", key],
                          capture_output=True, text=True, env=caller())
    return done.stdout.strip() if done.returncode == 0 else ""


def caller_home() -> Path:
    return Path(caller().get("HOME") or Path.home())


def install_of(named: str | None, environ: dict | None = None) -> Path | None:
    """`--install`, else the install the caller's `KEEL_CONFIG` names (a `config.toml`
    outside the code), else none: `packs.install_packs` itself, so this and the install half
    of `make drift` share one reading, a `~` the caller's `HOME` (c-733 r2.F3)."""
    environ = caller() if environ is None else environ
    if named:
        return packs.expand_home(named, environ)
    own = packs.install_packs(environ)
    return own.parent if own is not None else None


def host_names(full: str) -> list[str]:
    """A machine's own name, short and whole (`ada-mac`, `ada-mac.example.ts.net`)."""
    short = full.split(".", 1)[0]
    return [short] + ([full] if "." in full and not full.endswith((".local", ".lan")) else [])


def install_names(install: Path | None, root: Path = ROOT, git=git_value,
                  home=caller_home, hostname=socket.gethostname) -> Names:
    """One install's own names. `git`, `home` and `hostname` are the seams a test fills."""
    name, email = git(root, "user.name"), git(root, "user.email")
    local = email.split("@", 1)[0] if "@" in email else ""
    words = [word for word in re.split(r"[^A-Za-z0-9]+", name) + [local] if len(word) >= WORD_MIN]
    hosts = host_names(hostname())
    terms = packs.all_drift_terms(root)
    tree_terms = list(terms)
    if install is not None:
        config = install / "config.toml"
        if config.is_file():     # an `example` host in a commented example line is no one's
            hosts += [host for host in TAILNET_IN_CONFIG.findall(config.read_text(errors="replace"))
                      if ".example." not in f".{host.lower()}"]
        terms += [term for term in packs.all_drift_terms(install) if term not in terms]
    return Names(names=sorted({word.lower() for word in words}), emails=[email] if email else [],
                 home=str(home()), terms=terms, tree_terms=tree_terms,
                 hosts=(kept := sorted({host.lower() for host in hosts
                                        if len(host) >= WORD_MIN and host != "localhost"})),
                 common=common_words(kept))


# ----- what a line says -----

def other_email(line: str) -> bool:
    """An address on the line that is a person's: not a reserved example domain, not a
    robot's, and not a file name such as `icon@2x.png`."""
    for match in EMAIL.finditer(line):
        local, domain, top = match.group(1).lower(), match.group(2).lower(), match.group(3).lower()
        if local in NOT_A_PERSON or f".{top}" in IMAGES or top in ("py", "js", "md", "json"):
            continue
        if not any(domain == known.lstrip(".") or domain.endswith(known) for known in EXAMPLE_DOMAINS):
            return True
    return False


def kinds_in(line: str, patterns: list) -> list[str]:
    """Each kind of finding on one line, once: the install's own names first, then the rules
    that need no install."""
    found = [kind for kind, pattern in patterns if pattern.search(line)]
    if "home path" not in found and any(match.group(1) not in personal.PLACEHOLDERS
                                        for match in personal.HOME_PATH.finditer(line)):
        found.append("home path")
    if "host" not in found and any("example." not in match.group(1).lower()
                                   for match in personal.TAILNET.finditer(line)):
        found.append("host")
    if "email" not in found and "@" in line and other_email(line):
        found.append("email")
    return found


def let_through(where: str, text: str) -> dict[int, set[str]]:
    """`{line: kinds}` the `LINES` entries of `where` let through: for each, the first line of
    its form, whatever it carries, chosen before any name is read."""
    lines, let = text.splitlines(), {}
    for path, form, kinds, _ in LINES:
        if path != where:
            continue
        number = next((n for n, line in enumerate(lines, 1) if form.fullmatch(line.strip())), None)
        if number is not None:
            let.setdefault(number, set()).update(kinds)
    return let


def text_findings(where: str, text: str, patterns: list) -> list[tuple[str, int, str]]:
    """Each finding of the text, by line and kind, less what `LINES` lets through: on its one
    line only the kinds it names pass, and every other kind there is still a finding."""
    found, let = [], let_through(where, text)
    for number, line in enumerate(text.splitlines(), 1):
        for kind in kinds_in(line, patterns):
            if kind not in let.get(number, ()):
                found.append((where, number, kind))
    return found


def shown(rel: str, patterns: list) -> tuple[str, list[str]]:
    """A path as it may be printed, and each kind of finding the path itself holds: what a
    file is NAMED can be one install's own, and the path is what this check prints."""
    kinds = kinds_in(rel, patterns)
    masked = rel
    for kind, pattern in patterns:
        masked = pattern.sub(f"<{kind}>", masked)
    for kind, pattern in (("home path", personal.HOME_PATH), ("host", personal.TAILNET), ("email", EMAIL)):
        if kind in kinds:
            masked = pattern.sub(f"<{kind}>", masked)
    return masked, kinds


# ----- the tree, and a range of commits -----

def leaves(root: Path, rel: str) -> bool:
    """Whether the tracked symlink `rel` points at an absolute path or out of the tree."""
    target = os.readlink(root / rel)
    if os.path.isabs(target):
        return True
    there = os.path.normpath(os.path.join(os.path.dirname(rel), target))
    return there == ".." or there.startswith("../")


def tree_findings(root: Path, names: Names) -> list[tuple[str, int, str]]:
    patterns, found = names.patterns(), []
    try:
        listed = personal.tracked(root)
    except (subprocess.CalledProcessError, OSError) as failed:
        raise Unread("git could not list the tree") from failed
    for rel in listed:
        path = root / rel
        where, in_path = shown(rel, patterns)
        found += [(where, 0, kind) for kind in in_path]
        if path.is_symlink():
            found += [(where, 0, "symlink")] if leaves(root, rel) else []
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue     # a binary, or a file listed but gone from the work tree
        found += text_findings(where, text, patterns)
    return found


def git_out(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except OSError as failed:
        raise Unread("git could not read the range") from failed
    if done.returncode != 0:
        raise Unread("git could not read the range")
    return done.stdout


def range_findings(root: Path, names: Names, commits: str) -> list[tuple[str, int, str]]:
    """What a range of commits adds that no file read shows: its new images, its messages."""
    added = git_out(root, "diff", "--name-only", "--diff-filter=A", commits).splitlines()
    patterns = names.patterns()
    found = [(shown(rel, patterns)[0], 0, "new image") for rel in added if Path(rel).suffix.lower() in IMAGES]
    for entry in git_out(root, "log", "--format=%H%x00%B%x1e", commits).split("\x1e"):
        sha, _, message = entry.strip().partition("\x00")
        if sha:
            found += text_findings(f"commit {sha[:12]}", message, patterns)
    return found


def check(root: Path, names: Names, commits: str | None = None) -> list[tuple[str, int, str]]:
    return tree_findings(root, names) + (range_findings(root, names, commits) if commits else [])


def waiting_of(found: list) -> tuple[list, list]:
    """`(findings, waiting)`: the findings under a `WAITING` folder, set apart."""
    held = [item for item in found if any(item[0].startswith(prefix) for prefix, _ in WAITING)]
    return [item for item in found if item not in held], held



# ----- saying it -----

def mode_of(strict: bool) -> str:
    return "strict" if strict else "report only, nothing fails on it"


def skipped_line(count: int) -> str:
    """One line for the terms left out, with their number and never one of them."""
    what = "pack term could not be read as a pattern and was" if count == 1 else \
        "pack terms could not be read as patterns and were"
    return f"public check: {count} {what} skipped, so the tree was not checked for {'it' if count == 1 else 'them'}"


COMMIT = re.compile(r"commit [0-9a-f]{7,40}")      # how `range_findings` names a message


def top_of(where: str) -> str:
    """What a finding is counted under: `commit` for a commit's message, else the path's
    first part whole (a masked name such as `<pack term>.md` holds a space, as a file name
    may)."""
    return "commit" if COMMIT.fullmatch(where) else where.split("/", 1)[0]


def summary(found: list, strict: bool) -> str:
    """The counts, never a term: by kind, and by the tree's top directory (masked, as every
    path here is)."""
    mode = mode_of(strict)
    if not found:
        return f"public check ({mode}): nothing of one install's in the tree"
    files = {where for where, _, _ in found}
    by_kind = Counter(kind for _, _, kind in found)
    tops = Counter(top_of(where) for where, _, _ in found)
    return (f"public check ({mode}): {len(found)} findings in {len(files)} files\n"
            f"  by kind: {', '.join(f'{kind} {by_kind[kind]}' for kind in KINDS if by_kind[kind])}\n"
            f"  by directory: {', '.join(f'{top} {count}' for top, count in tops.most_common())}")


def main(argv: list[str] | None = None, names: Names | None = None) -> int:
    """`names` is a test's: left out, they are read from the caller (`install_names`)."""
    parser = argparse.ArgumentParser(prog="python3 -m tests.publiccheck", description=__doc__.split("\n")[0])
    parser.add_argument("--install", help="the install whose names to look for")
    parser.add_argument("--root", default=str(ROOT), help="the tree to read (default: this checkout)")
    parser.add_argument("--range", dest="commits", metavar="A..B", help="also read these commits")
    parser.add_argument("--list", action="store_true", help="print each finding as path:line: kind")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any finding")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    names = install_names(install_of(args.install), root) if names is None else names
    try:
        found = check(root, names, args.commits)
    except Unread as unread:
        print(f"public check ({mode_of(args.strict)}): {unread}, so nothing was read")
        return 1 if args.strict else 0
    found, held = waiting_of(found)
    if args.list and found:
        print("\n".join(f"{where}:{line}: {kind}" for where, line, kind in found))
    print(summary(found, args.strict))
    for prefix, why in WAITING:
        count = sum(1 for where, _, _ in held if where.startswith(prefix))
        if count:
            print(f"public check: {count} findings wait in {prefix}: {why}")
    if names.skipped:
        print(skipped_line(names.skipped))
    return 1 if args.strict and (found or names.skipped_tree) else 0


if __name__ == "__main__":
    sys.exit(main())
