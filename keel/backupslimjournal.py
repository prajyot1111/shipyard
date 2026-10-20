"""`keel backup slim`'s journal: which snapshots of a set are slim, and the one mid-replace.

The journal is `sets/<set>/slim.json` in the store, fetched and put back by
`bin/keel-backup`; this module reads and rewrites the local copy the tool hands it, as verbs
of `python3 -m keel.backupslim` (docs/atlas/85-backup.md, "Slimming the old snapshots").
A snapshot is slim when the journal names the object the store holds now, by its md5, and
records that it was slimmed under today's rules, by their digest (`candidates`). The tool
keeps the journal's previous state beside it as `slim.json.prev`, which only a restore reads.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

BLOB = ".tar.gz.gpg"


def load(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def save(path: Path, data: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def journal_of(path: Path, name: str = "") -> dict:
    """The journal at `path`; an empty one when the store holds none. A journal that is
    there and does not read STOPS (r1.F4): read as empty, it would say no replace was under
    way, and the temporary object of one that was would be removed as a stray."""
    data = {}
    if Path(path).exists():
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError) as error:
            raise SystemExit(f"slim.json does not read as a journal ({error}); nothing is done on a guess")
        if not (isinstance(data, dict) and isinstance(data.get("done", {}), dict)
                and isinstance(data.get("replacing"), (dict, type(None)))):
            raise SystemExit("slim.json is not shaped as a journal; nothing is done on a guess")
    data.setdefault("set", name)
    data.setdefault("done", {})
    data.setdefault("replacing", None)
    return data


def file_digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def entry_from(args, summary: dict) -> dict:
    return {"id": args.id, "key": args.key, "was_md5": args.was_md5, "md5": args.md5,
            "old_key": args.old_key, "rules_digest": file_digest(args.rules),
            "was_bytes": args.was_bytes, "bytes": args.bytes, "at": args.at,
            "manifest": args.manifest, "files": args.files, "archive_bytes": args.archive_bytes,
            "dropped_files": summary.get("dropped_files", 0),
            "dropped_bytes": summary.get("dropped_bytes", 0),
            "rules": summary.get("rules", [])}


def candidates(rows: Path, journal: dict, name: str, digest: str) -> tuple[list[tuple], dict, list[str]]:
    """The set's snapshots the journal does not call slim, oldest first, as (id, key, bytes,
    md5), with the counts the summary prints. A snapshot is slim when the journal names the
    object the store holds now (its md5) AND the rules it was slimmed under are today's
    (`digest`, r2.F6): one slimmed under older rules is looked at again, and counted. A
    name two objects share is left alone and said."""
    prefix, seen = f"sets/{name}/snapshots/", {}
    for line in Path(rows).read_text().splitlines():
        key, _, rest = line.partition("\t")
        size, _, md5 = rest.partition("\t")
        if key.startswith(prefix) and key.endswith(BLOB):
            seen.setdefault(key, []).append((int(size or 0), md5))
    todo, shared, slim, older = [], [], 0, 0
    for key in sorted(seen, key=os.path.basename):
        sid = os.path.basename(key)[: -len(BLOB)]
        if len(seen[key]) > 1:
            shared.append(key)
            continue
        size, md5 = seen[key][0]
        entry = journal["done"].get(sid) or {}
        if entry.get("md5") == md5 and entry.get("rules_digest") == digest:
            slim += 1
        else:
            todo.append((sid, key, size, md5))
            older += entry.get("md5") == md5
    stats = {"snapshots": len(seen), "slim_before": slim, "pending": len(todo), "older_rules": older,
             "pending_bytes": sum(row[2] for row in todo)}
    return todo, stats, shared


def cmd_candidates(args) -> int:
    todo, stats, shared = candidates(Path(args.rows), journal_of(Path(args.journal), args.set), args.set,
                                     file_digest(args.rules))
    Path(args.stats).write_text(json.dumps(stats))
    for key in shared:
        print(f"{key}: two objects share this name, so it is left alone", file=sys.stderr)
    for row in todo:
        print("\t".join(str(part) for part in row))
    return 0


def cmd_journal(args) -> int:
    path = Path(args.file)
    data = journal_of(path, args.set)
    if args.what == "show":
        mid = data["replacing"]
        if mid:
            print("\t".join(str(mid[key]) for key in ("id", "key", "was_md5", "md5")))
        return 0
    if args.what == "was":
        # The md5 the journal recorded for the archive a rewrite of this snapshot replaced
        # (an unfinished replace, or a done one); nothing when it records no rewrite. It is
        # what vouches for the object kept under slim-old/ (r2.F1).
        mid = data["replacing"] or {}
        entry = mid if mid.get("id") == args.id else data["done"].get(args.id) or {}
        print(entry.get("was_md5") or "")
        return 0
    if args.what == "init":                 # the set's first journal: nothing done, nothing mid-replace
        save(path, data)
        return 0
    if args.what == "replacing":
        data["replacing"] = entry_from(args, load(Path(args.plan)) if args.plan else {})
    elif args.what == "nothing":
        # One slimmed before, under other rules, and found slim under today's too, keeps
        # its entry (what vouches for its kept old archive) and takes today's digest.
        was = data["done"].get(args.id) or {}
        fresh = {"md5": args.md5, "bytes": args.bytes, "dropped_files": 0, "dropped_bytes": 0}
        data["done"][args.id] = dict(was if was.get("md5") == args.md5 else fresh,
                                     at=args.at, rules_digest=file_digest(args.rules))
    elif args.what == "done":
        mid = data["replacing"] or {}
        if mid.get("id"):
            data["done"][mid["id"]] = {k: v for k, v in mid.items() if k not in ("id", "key")}
        data["replacing"] = None
    elif args.what == "forget":             # restored: the snapshot is the old archive again
        data["done"].pop(args.id, None)
    else:                                   # drop: the replace never happened
        data["replacing"] = None
    save(path, data)
    return 0


def cmd_latest(args) -> int:
    """A `latest.json` that names the snapshot being replaced is made to describe what the
    store now holds under that name. 3: it names another snapshot, or already says so."""
    latest, mid = load(Path(args.file)), journal_of(Path(args.journal))["replacing"] or {}
    if not mid.get("manifest") or latest.get("snapshot") != mid.get("id"):
        return 3
    now = {"manifest": mid["manifest"], "files": int(mid["files"]),
           "archive_bytes": int(mid["archive_bytes"]), "encrypted_bytes": int(mid["bytes"])}
    if all(latest.get(key) == value for key, value in now.items()):
        return 3
    new = dict(latest, slimmed_at=mid["at"], **now)
    Path(args.out).write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
    # What it said before, kept with the entry so a restore can say it again.
    data = journal_of(Path(args.journal))
    data["replacing"]["latest_was"] = latest
    save(Path(args.journal), data)
    return 0


def cmd_unlatest(args) -> int:
    """A restore's half of `latest`: a `latest.json` that names the restored snapshot says
    again what it said before the rewrite. Where that was not kept, its manifest is blanked,
    so the next hourly run takes a snapshot instead of trusting a digest that is not the
    archive's. 3: it names another snapshot."""
    latest = load(Path(args.file))
    done = journal_of(Path(args.journal))["done"].get(args.id) or {}
    if latest.get("snapshot") != args.id:
        return 3
    new = done.get("latest_was") or dict(latest, manifest="")
    new.pop("slimmed_at", None)
    Path(args.out).write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
    return 0


def listed(rows: Path) -> dict:
    """{key: [md5, ...]} of a store listing the tool wrote (key, bytes, md5 per line)."""
    seen: dict = {}
    for line in Path(rows).read_text().splitlines():
        key, _, rest = line.partition("\t")
        seen.setdefault(key, []).append(rest.partition("\t")[2])
    return seen


def purgeable(old_rows: Path, rows: Path, journal: dict, name: str, retired=frozenset()) -> tuple[list[tuple], list[tuple]]:
    """Which kept old archives (`slim-old/<set>/<id>`) a purge removes, and which it leaves,
    each with why (r1.F7). Removed: one whose rewrite the journal marks done, while the
    store holds the slimmed snapshot the journal recorded, or holds no snapshot of that id
    any more and `retired` names its key (retention's own rule says the snapshot goes,
    r3.F2: an empty name alone is not proof retention emptied it); and one whose
    snapshot's name still holds that very archive, so it is a second copy of what is there.
    Everything else stays: an unfinished replace, a rewrite the journal does not know, a
    name that holds something else."""
    names, mid = listed(rows), journal["replacing"] or {}
    remove, keep = [], []
    for key, md5s in sorted(listed(old_rows).items()):
        sid = os.path.basename(key)[: -len(BLOB)]
        own = f"sets/{name}/snapshots/{sid[:4]}/{sid[4:6]}/{sid}{BLOB}"
        held = names.get(own, [])
        done = journal["done"].get(sid) or {}
        if mid.get("id") == sid:
            keep.append((key, "its replace is not finished"))
        elif len(md5s) > 1 or len(held) > 1:
            keep.append((key, "two objects share a name"))
        elif done.get("was_md5") == md5s[0] and held == [done.get("md5")]:
            remove.append((key, "its rewrite is done"))
        elif done.get("was_md5") == md5s[0] and not held and own in retired:
            remove.append((key, "its rewrite is done and retention has removed the snapshot"))
        elif done.get("was_md5") == md5s[0] and not held:
            keep.append((key, f"the store no longer lists {sid} and retention would keep it, so this is its only "
                              f"copy: bin/keel backup slim --restore {sid} --set {name} puts it back"))
        elif held == md5s:
            remove.append((key, "the snapshot's own name holds this same archive"))
        else:
            keep.append((key, "the journal does not mark its rewrite done as the store holds it"))
    return remove, keep


def cmd_vouched(args) -> int:
    """The snapshot keys the journal vouches a kept old archive for: a rewrite marked done
    whose recorded old md5 is the one object under that id in `slim-old/<set>/`. These are
    the snapshots known to have been in the set, which retention is asked about along with
    the ones still listed; a stray object under `slim-old/` is nobody's snapshot."""
    journal = journal_of(Path(args.journal), args.set)
    for key, md5s in sorted(listed(Path(args.old)).items()):
        sid = os.path.basename(key)[: -len(BLOB)]
        if md5s == [(journal["done"].get(sid) or {}).get("was_md5")]:
            print(f"sets/{args.set}/snapshots/{sid[:4]}/{sid[4:6]}/{sid}{BLOB}")
    return 0


def cmd_purge(args) -> int:
    retired = set(Path(args.retired).read_text().splitlines()) if args.retired else set()
    remove, keep = purgeable(Path(args.old), Path(args.rows), journal_of(Path(args.journal), args.set), args.set,
                             retired)
    for key, why in keep:
        print(f"{key} is kept: {why}", file=sys.stderr)
    for key, why in remove:
        print(f"{key}\t{why}")
    return 0


