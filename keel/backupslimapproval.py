"""`keel backup slim`'s approval file: what the dry run showed is all the rewrite may do.

A rewrite is permanent, and the plan says it runs only after the dry run has been read. So
the dry run writes down what it showed, per snapshot, in `slim-approved.json` in the backup
home (local, never in the store), and `slim --approved` does nothing to a snapshot that
file does not cover exactly (r1.F2):

- the object the store holds is the one the dry run read (its md5);
- what decides a drop is what decided it then: a digest of the text the tool's
  set_decides prints (the find, the roots and list functions, the staged paths, the
  canary's name);
- what the rewrite is about to drop is what it showed: the same paths (a digest of the
  sorted dropped files and directories, r2.F2: equal sums are not the same files), under
  the same roots, with the same totals by the same rules. More, less or different is
  refused, which is also the bound on a scan that went wrong (r1.F11).

AN ENTRY THAT NAMES TREES ON THE LIVE TREE'S WORD IS REFUSED (c-752). Until c-752 a dry run
could ask the live tree which directories were checkouts and record them here (`live`) for
the rewrite to mark. Nothing marks them now, so a rewrite could not do what that dry run
showed: `approved` refuses such an entry and says to run the dry run again. An empty
`live` list said nothing then and is not read now.

The verbs are `python3 -m keel.backupslim approve | approved | check`, called by
`bin/keel-backup`. An approval file that is missing approves nothing. One that is there
and does not parse is damage, not an empty file: `approved` says so (4) and the rewrite
stops (r2.F8).
"""

import hashlib
import json
import os
import sys
from pathlib import Path

from keel.backupslimjournal import file_digest, load, save

AGAIN = "run the dry run again"


rules_digest = file_digest      # the same digest the journal keeps for each rewrite (r2.F6)


def what(summary: dict) -> dict:
    """What a plan drops, in the terms a person approved: totals, and by rule."""
    return {"dropped_files": summary.get("dropped_files", 0),
            "dropped_dirs": summary.get("dropped_dirs", 0),
            "dropped_bytes": summary.get("dropped_bytes", 0),
            "rules": summary.get("rules", [])}


def lines_digest(lines) -> str:
    return hashlib.sha256("".join(line + "\n" for line in lines).encode("utf-8", "surrogateescape")).hexdigest()


def proof(args) -> dict:
    """What a plan drops, path by path, and the roots it found: `dropped.json` and `roots`
    of the plan directory, each as one digest."""
    dropped = json.loads(Path(args.dropped).read_text())
    paths = [f"f {p}" for p in sorted(dropped["files"])] + [f"d {p}" for p in sorted(dropped["dirs"])]
    # Sorted by their bytes (r3.F7): the roots come from a glob, whose order is the locale's.
    roots = sorted(Path(args.roots).read_text(errors="surrogateescape").splitlines(),
                   key=lambda line: line.encode("utf-8", "surrogateescape"))
    return {"paths_digest": lines_digest(paths), "roots_digest": lines_digest(roots)}


def entry_of(data: dict, name: str, sid: str) -> dict | None:
    snapshots = (data.get("sets") or {}).get(name)
    return snapshots.get(sid) if isinstance(snapshots, dict) else None


def cmd_approve(args) -> int:
    """The dry run's record of one snapshot; `--forget` when it could not be read, or once
    it has been rewritten."""
    path = Path(args.file)
    data = load(path)
    snapshots = data.setdefault("sets", {}).setdefault(args.set, {})
    if args.forget:
        snapshots.pop(args.id, None)
    else:
        dropped = dict(what(load(Path(args.plan))), **proof(args))
        snapshots[args.id] = dict(dropped, md5=args.md5, bytes=args.bytes, at=args.at,
                                  rules_digest=rules_digest(args.rules),
                                  state="would-slim" if dropped["dropped_files"] or dropped["dropped_dirs"] else "nothing")
    save(path, data)
    os.chmod(path, 0o600)
    return 0


def cmd_approved(args) -> int:
    """Before a snapshot is fetched for a rewrite. 0 and its approved state (`would-slim`,
    or `nothing` when the dry run found nothing to drop); 3 and why not, when the file
    does not cover the object the store holds now, or names trees to drop on the live
    tree's word (see above); 4 and why, when the file is there and does not parse."""
    if Path(args.file).exists():
        try:
            if not isinstance(json.loads(Path(args.file).read_text()), dict):
                raise ValueError("it is not an object")
        except (OSError, ValueError) as error:
            print(error)
            return 4
    entry = entry_of(load(Path(args.file)), args.set, args.id)
    if not entry:
        print(f"the dry run has not shown it; {AGAIN}")
        return 3
    if entry.get("md5") != args.md5:
        print(f"the store holds another object than the dry run read; {AGAIN}")
        return 3
    if entry.get("rules_digest") != rules_digest(args.rules):
        print(f"the scan's rules have changed since the dry run; {AGAIN}")
        return 3
    if entry.get("live"):
        print(f"the dry run named trees to drop on the live tree's word, which is no longer asked; {AGAIN}")
        return 3
    print(entry.get("state") or "would-slim")
    return 0


def cmd_check(args) -> int:
    """After the scan, before anything is packed: the plan is the approved one, or 1 and
    how it differs."""
    entry = entry_of(load(Path(args.file)), args.set, args.id) or {}
    plan = dict(what(load(Path(args.plan))), **proof(args))
    differs = [key for key, value in plan.items() if entry.get(key) != value]
    if differs:
        print(f"what it would drop is not what the dry run showed ({', '.join(differs)}: "
              f"{plan['dropped_files']} files and {plan['dropped_bytes']} bytes now, "
              f"{entry.get('dropped_files')} and {entry.get('dropped_bytes')} then); {AGAIN}", file=sys.stderr)
    return 1 if differs else 0
