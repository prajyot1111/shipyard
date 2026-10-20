"""`keel backup slim`: what an old snapshot loses, and the proof it lost nothing else (c-724).

The tool is `bin/keel-backup`, in bash, and so is the slim: it fetches, decrypts, scans,
encrypts and writes the store with the tool's own functions. What lives here is the part
that is sets and sums rather than `tar` and `gpg`, which the tool calls as
`python3 -m keel.backupslim <verb>`:

    members           the archive's own member list against the tree it unpacked to
    approve, approved, check       the approval file (`keel/backupslimapproval.py`)
    plan              what the scan left out of an unpacked snapshot, by rule
    prove             the rewritten archive, unpacked, is the old one minus exactly that
    candidates, journal, latest, unlatest, purge, vouched
                      the set's `slim.json`: what is still to do, the journal's own
                      verbs, a `latest.json` put right after a rewrite and after a
                      restore, which kept old archives a purge takes, and which
                      snapshots the journal vouches a kept archive for
                      (`keel/backupslimjournal.py`)
    record, summary                what a run says (`keel/backupslimreport.py`)

NOTHING HERE DECIDES WHAT IS DROPPED. The one definition is the set's own file list in the
tool (`keel_find` and its siblings), run over the unpacked snapshot exactly as a snapshot
runs it over the live tree; `plan` only subtracts that list from what the archive holds.
The rule names it prints are read out of the same function's text (`rules`), so a rule
added there is named here with no second list to forget.

A PATH UNDER NONE OF TODAY'S ROOTS IS KEPT. The scan walks roots, and its exclusions name
paths under them; something an old archive carries from outside them is named by no rule,
so it stays and is counted (`outside`).
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from keel.backupslimapproval import cmd_approve, cmd_approved, cmd_check
from keel.backupslimjournal import (
    cmd_candidates, cmd_journal, cmd_latest, cmd_purge, cmd_unlatest, cmd_vouched)
from keel.backupslimreport import STATES, cmd_record, cmd_summary

UNNAMED = "(a rule the scan applies and this could not name)"


# ----- the tree an archive unpacks to -----

def refuse(error: OSError):
    raise error


def walk(tree: Path) -> tuple[dict, set, set]:
    """({file: bytes}, {directory}, {anything else}) under `tree`, by relative path. A
    directory that cannot be listed raises: os.walk's own habit is to skip it, and a
    skipped directory would read as one the archive never held (r1.F3)."""
    files, dirs, others = {}, set(), set()
    for here, dirnames, filenames in os.walk(tree, onerror=refuse):
        rel = os.path.relpath(here, tree)
        prefix = "" if rel == "." else rel + "/"
        for name in list(dirnames):
            if os.path.islink(os.path.join(here, name)):
                dirnames.remove(name)
                others.add(prefix + name)
            else:
                dirs.add(prefix + name)
        for name in filenames:
            status = os.lstat(os.path.join(here, name))
            if stat.S_ISREG(status.st_mode):
                files[prefix + name] = status.st_size
            else:
                others.add(prefix + name)
    return files, dirs, others


APPLEDOUBLE = bytes.fromhex("00051607")


def members(archive: Path) -> tuple[dict, set]:
    """({path: file|dir|other}, {AppleDouble members}) as the archive itself names its
    members, read as a stream. A hard link is a file. The second is every `._name` member
    whose first four bytes are the AppleDouble magic: macOS tar writes a file's extended
    attributes that way, beside the file (r2.F7)."""
    named, doubles = {}, set()
    with tarfile.open(archive, "r|gz") as tar:
        for item in tar:
            path = item.name.removeprefix("./").rstrip("/")
            if not path or path == ".":
                continue
            named[path] = "dir" if item.isdir() else "file" if item.isreg() or item.islnk() else "other"
            if item.isreg() and os.path.basename(path).startswith("._"):
                if tar.extractfile(item).read(len(APPLEDOUBLE)) == APPLEDOUBLE:
                    doubles.add(path)
    return named, doubles


def folded(named: dict, doubles: set, tree: Path) -> dict:
    """The members that are paths of their own. An AppleDouble `._name` is not one only
    when its `name` is a member too and the unpacked tree does not hold it: tar folded it
    back into the file. One the tree holds is a file like any other, and a `._name` that
    is not AppleDouble is somebody's file whatever unpacking did with it, so if the tree
    lacks it the snapshot is not whole (r2.F7: it was once ignored on its name alone)."""
    own = dict(named)
    for path in doubles:
        head, _, name = path.rpartition("/")
        beside = (head + "/" if head else "") + name[2:]
        if beside in named and not os.path.lexists(os.path.join(tree, path)):
            del own[path]
    return own


def unpacked_whole(named: dict, files: dict, dirs: set, others: set) -> list[str]:
    """What differs between the paths an archive names and the tree it unpacked to; empty
    when they are the same paths (r1.F3). The proof further on compares two unpacked
    trees, so anything unpacking lost (two names a volume folds into one, a name it
    cannot hold) has to be caught here, where tar itself says nothing. A directory the
    archive does not name is fine when something it does name sits under it."""
    problems = []
    for kind, held in (("file", set(files)), ("other", others)):
        want = {path for path, is_a in named.items() if is_a == kind}
        if want - held:
            problems += shown(f"the archive names {some(len(want - held), 'path')} the unpacked tree does not hold", want - held)
        if held - want:
            problems += shown(f"the unpacked tree holds {some(len(held - want), 'path')} the archive does not name", held - want)
    want = {path for path, is_a in named.items() if is_a == "dir"}
    implied = {above for path in named for above in ancestors(path)}
    if want - dirs:
        problems += shown(f"the archive names {some(len(want - dirs), 'directory')} the unpacked tree does not hold", want - dirs)
    if dirs - want - implied:
        problems += shown("the unpacked tree holds directories the archive does not name", dirs - want - implied)
    return problems


def some(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun[:-1] + 'ies' if noun.endswith('y') else noun + 's'}"


def ancestors(path: str):
    while "/" in path:
        path = path.rsplit("/", 1)[0]
        yield path


def read_names(path: Path) -> list[str]:
    """A NUL-separated list, as `find -print0` writes one."""
    return [os.fsdecode(name) for name in Path(path).read_bytes().split(b"\0") if name]


def write_names(path: Path, names) -> None:
    Path(path).write_bytes(b"".join(os.fsencode(name) + b"\0" for name in names))


# ----- the rules, read from the scan itself -----

@dataclass(frozen=True)
class Rule:
    kind: str           # path, name or iname: find's own test
    pattern: str


TEST = re.compile(r"(!\s+)?-(path|name|iname)\s+'([^']*)'")


def rules(source: str) -> list[Rule]:
    """Every test a set's find drops something by, from the function's own text. Before
    `-prune` a test names a tree to drop and a negated one only narrows its neighbour;
    after it only the negated tests drop."""
    head, _prune, tail = source.partition("-prune")
    found = []
    for text, pruning in ((head, True), (tail, False)):
        for match in TEST.finditer(text):
            if bool(match.group(1)) != pruning:
                found.append(Rule(match.group(2), match.group(3)))
    return found


def rule_of(path: str, known: list[Rule]) -> str:
    """The rule that names a dropped path: a name before a path, since a path rule may
    also cover what a name rule drops inside it."""
    name = os.path.basename(path)
    for rule in known:
        if rule.kind == "name" and fnmatch.fnmatchcase(name, rule.pattern):
            return rule.pattern
        if rule.kind == "iname" and fnmatch.fnmatchcase(name.lower(), rule.pattern.lower()):
            return rule.pattern
    for rule in known:
        if rule.kind == "path" and fnmatch.fnmatchcase(path, rule.pattern):
            return rule.pattern
    return UNNAMED


# ----- the plan: the archive minus what the scan listed -----

@dataclass
class Plan:
    drop_files: set
    drop_dirs: set
    members: list           # what the rewritten archive is packed from, in the tool's order
    summary: dict
    others: set = field(default_factory=set)


def plan(tree: Path, kept: set, roots: list[str], staged: set, known: list[Rule]) -> Plan:
    """`kept` is the scan's own listing of the unpacked snapshot (directories and files).
    `staged` is every path the set stages rather than scans (the board, each repo's
    bundle: the tool's set_staged), so each is kept by name, wherever it sits (r2.F12).
    Dropped is what is left under a root; a dropped directory holds nothing kept, so the
    top of each dropped tree stands for everything under it."""
    files, dirs, others = walk(tree)

    def under(path: str) -> bool:
        return any(path == root or path.startswith(root + "/") for root in roots)

    keep_files = {p for p in files if p in kept or p in staged or not under(p)}
    keep_dirs = {d for d in dirs if d in kept or not under(d)}
    for path in list(keep_files) + list(keep_dirs):
        keep_dirs.update(ancestors(path))
    drop_files, drop_dirs = set(files) - keep_files, dirs - keep_dirs
    nodes: dict = {}

    def node(path: str, is_dir: bool) -> dict:
        while os.path.dirname(path) in drop_dirs:
            path, is_dir = os.path.dirname(path), True
        if path not in nodes:
            nodes[path] = {"path": path + ("/" if is_dir else ""), "rule": rule_of(path, known),
                           "files": 0, "bytes": 0}
        return nodes[path]

    for path in drop_dirs:
        node(path, True)
    for path in drop_files:
        top = node(path, False)
        top["files"] += 1
        top["bytes"] += files[path]
    listed = sorted(nodes.values(), key=lambda n: (-n["bytes"], n["path"]))
    outside = [p for p in files if not under(p) and p not in staged]
    summary = {
        "files": len(files), "bytes": sum(files.values()),
        "kept_files": len(keep_files),
        "dropped_files": len(drop_files), "dropped_dirs": len(drop_dirs),
        "dropped_bytes": sum(files[p] for p in drop_files),
        "rules": by_rule(listed), "nodes": listed,
        "outside": {"files": len(outside), "bytes": sum(files[p] for p in outside)},
        "others": len(others),
    }
    members = sorted(keep_dirs | keep_files, key=os.fsencode)
    return Plan(drop_files, drop_dirs, members, summary, others)


def by_rule(nodes: list[dict]) -> list[dict]:
    """The dropped trees and files summed under the rule that names each."""
    rows: dict = {}
    for item in nodes:
        row = rows.setdefault(item["rule"], {"rule": item["rule"], "files": 0, "bytes": 0, "trees": 0})
        row["files"] += item["files"]
        row["bytes"] += item["bytes"]
        row["trees"] += 1
    return sorted(rows.values(), key=lambda r: (-r["bytes"], r["rule"]))


# ----- the proof -----

def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def shown(label: str, paths) -> list[str]:
    paths = sorted(paths)
    lines = [f"  {label}: {len(paths)}"] + [f"    {p}" for p in paths[:25]]
    return lines + ([f"    ... and {len(paths) - 25} more"] if len(paths) > 25 else [])


def same_meta(was: os.stat_result, now: os.stat_result, whole_seconds: bool) -> bool:
    scale = 10**9 if whole_seconds else 1
    return (stat.S_IMODE(was.st_mode) == stat.S_IMODE(now.st_mode)
            and was.st_mtime_ns // scale == now.st_mtime_ns // scale)


def prove(old: Path, new: Path, drop_files: set, drop_dirs: set,
          whole_seconds: bool = False) -> tuple[list[str], list[str]]:
    """The rewritten archive, unpacked into `new`, against the old one in `old`: the same
    files with the same content, mode and time, and the same directories with the same
    mode and time (r1.F10), minus exactly what was dropped. Returns (what differs, the new
    archive's manifest lines); an empty first list is the proof.

    Times are compared to the nanosecond unless `whole_seconds`: the tool says so where
    its tar is not bsdtar, whose archives carry the fraction; GNU tar's default format
    carries whole seconds, so there a fraction is lost by the format and is not a fault."""
    old_files, old_dirs, _ = walk(old)
    new_files, new_dirs, new_others = walk(new)
    want_files, want_dirs = set(old_files) - drop_files, old_dirs - drop_dirs
    problems, manifest = [], []
    if not want_files:
        problems.append("  nothing would be left in the archive")
    for label, paths in (("kept by the rules but missing", want_files - set(new_files)),
                         ("in the new archive but not the old one", set(new_files) - want_files),
                         ("a directory kept by the rules but missing", want_dirs - new_dirs),
                         ("a directory in the new archive but not the old one", new_dirs - want_dirs),
                         ("neither a file nor a directory", new_others)):
        if paths:
            problems += shown(label, paths)
    changed = []
    for path in sorted(want_files & set(new_files), key=os.fsencode):
        was, now = os.stat(os.path.join(old, path)), os.stat(os.path.join(new, path))
        sha = digest(os.path.join(new, path))
        same = (was.st_size == now.st_size and same_meta(was, now, whole_seconds)
                and digest(os.path.join(old, path)) == sha)
        if not same:
            changed.append(path)
        manifest.append(f"{sha}  {path}")
    if changed:
        problems += shown("present in both but not the same (content, mode or time)", changed)
    moved = [path for path in want_dirs & new_dirs
             if not same_meta(os.stat(os.path.join(old, path)), os.stat(os.path.join(new, path)), whole_seconds)]
    if moved:
        problems += shown("a directory present in both but not the same (mode or time)", moved)
    return problems, manifest


# ----- the verbs the tool calls -----

def cmd_members(args) -> int:
    """The archive's own member list against the tree it was unpacked to. 1, with what
    differs, when they are not the same paths or the tree cannot be read."""
    try:
        named, doubles = members(Path(args.archive))
        problems = unpacked_whole(folded(named, doubles, Path(args.tree)), *walk(Path(args.tree)))
    except (OSError, tarfile.TarError) as error:
        print(f"could not be read: {error}", file=sys.stderr)
        return 1
    if problems:
        print("\n".join(problems), file=sys.stderr)
    return 1 if problems else 0


def cmd_plan(args) -> int:
    """Reads `kept`, `roots`, `staged` and `rules` from the plan directory the tool filled;
    writes `plan.json`, `members` and `dropped.json` beside them. Prints how many paths go."""
    where = Path(args.plan)
    found = plan(Path(args.tree), set(read_names(where / "kept")),
                 (where / "roots").read_text().splitlines(),
                 {line for line in (where / "staged").read_text().splitlines() if line},
                 rules((where / "rules").read_text()))
    (where / "plan.json").write_text(json.dumps(found.summary))
    (where / "dropped.json").write_text(json.dumps({"files": sorted(found.drop_files),
                                                    "dirs": sorted(found.drop_dirs)}))
    write_names(where / "members", found.members)
    if found.others:
        print(f"holds {len(found.others)} entries that are neither files nor directories", file=sys.stderr)
        return 4
    if not found.summary["kept_files"]:
        print("nothing would be left in the archive", file=sys.stderr)
        return 4
    print(len(found.drop_files) + len(found.drop_dirs))
    return 0


def cmd_prove(args) -> int:
    dropped = json.loads((Path(args.plan) / "dropped.json").read_text())
    problems, manifest = prove(Path(args.old), Path(args.new), set(dropped["files"]), set(dropped["dirs"]),
                               whole_seconds=args.whole_seconds)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    Path(args.manifest).write_text("".join(line + "\n" for line in manifest))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m keel.backupslim",
                                     description="the sums behind `keel backup slim`; bin/keel-backup calls it")
    subs = parser.add_subparsers(dest="verb", required=True)

    def verb(name, call, *flags, **typed):
        sub = subs.add_parser(name)
        for flag in flags:
            sub.add_argument("--" + flag, type=typed.get(flag, str), default=None)
        sub.set_defaults(call=call)
        return sub

    verb("members", cmd_members, "archive", "tree")
    verb("approve", cmd_approve, "file", "set", "id", "md5", "bytes", "rules", "plan", "dropped", "roots", "at",
         bytes=int).add_argument("--forget", action="store_true")
    verb("approved", cmd_approved, "file", "set", "id", "md5", "rules")
    verb("check", cmd_check, "file", "set", "id", "plan", "dropped", "roots")
    verb("plan", cmd_plan, "tree", "plan")
    verb("prove", cmd_prove, "old", "new", "plan", "manifest").add_argument("--whole-seconds", action="store_true")
    verb("candidates", cmd_candidates, "rows", "journal", "set", "stats", "rules")
    journal = verb("journal", cmd_journal, "set", "id", "key", "was-md5", "md5", "was-bytes", "bytes",
                   "at", "manifest", "files", "archive-bytes", "plan", "old-key", "rules",
                   **{"was-bytes": int, "bytes": int, "files": int, "archive-bytes": int})
    journal.add_argument("what", choices=("show", "was", "init", "replacing", "nothing", "done", "drop", "forget"))
    journal.add_argument("file")
    verb("latest", cmd_latest, "file", "journal", "out")
    verb("unlatest", cmd_unlatest, "file", "journal", "id", "out")
    verb("purge", cmd_purge, "old", "rows", "journal", "set", "retired")
    verb("vouched", cmd_vouched, "old", "journal", "set")
    record = verb("record", cmd_record, "run", "log", "set", "id", "was-bytes", "now-bytes",
                  "seconds", "note", "plan", "at",
                  **{"was-bytes": int, "now-bytes": int, "seconds": int})
    record.add_argument("--state", choices=STATES, required=True)
    summary = verb("summary", cmd_summary, "run")
    summary.add_argument("--stats", action="append", default=[])
    summary.add_argument("--old", action="append", default=[])
    summary.add_argument("--dry", action="store_true")
    summary.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.call(args)


if __name__ == "__main__":
    raise SystemExit(main())
