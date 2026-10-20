"""`keel backup slim`'s report: one line a snapshot, then the totals and the estimate.

`bin/keel-backup` appends a line per snapshot to the run's file through `record` and prints
`summary` at the end, both verbs of `python3 -m keel.backupslim`. Nothing here decides or
proves anything; it adds up what `keel/backupslim.py` planned.
"""

import json
import os
from pathlib import Path

from keel.backupslimjournal import load

# left: the store moved on while it was read. refused: it is not what the dry run showed.
# unapproved: the dry run has not shown it, so it was not even fetched.
STATES = ("slimmed", "would-slim", "nothing", "left", "failed", "refused", "unapproved")
# What the rewrite costs beyond the dry run's fetch, decrypt, unpack and scan: packing,
# encrypting and unpacking the slim archive once more (small beside the old one), and the
# store's own calls for one replace. Rough on purpose, and said to be.
REWRITE_FACTOR, REPLACE_SECONDS = 1.5, 15


def add_rules(total: list[dict], more: list[dict]) -> list[dict]:
    rows = {row["rule"]: dict(row) for row in total}
    for row in more:
        into = rows.setdefault(row["rule"], {"rule": row["rule"], "files": 0, "bytes": 0, "trees": 0})
        for key in ("files", "bytes", "trees"):
            into[key] += row.get(key, 0)
    return sorted(rows.values(), key=lambda r: (-r["bytes"], r["rule"]))


# ----- what a run says -----

def size(count: float) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if count >= scale:
            return f"{count / scale:.1f}{unit}"
    return f"{int(count)}B"


def span(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    return f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def line_of(row: dict) -> str:
    """One snapshot, in words."""
    head = f"[{row['set']}] {row['id']}  {size(row['was_bytes'])}"
    if row["state"] in ("slimmed", "would-slim"):
        verb = "drops" if row["state"] == "slimmed" else "would drop"
        about = "" if row["state"] == "slimmed" else "about "
        rules_said = ", ".join(f"{r['rule']} {size(r['bytes'])}" for r in row["rules"][:6])
        more = f", and {len(row['rules']) - 6} more rules" if len(row["rules"]) > 6 else ""
        return (f"{head} -> {about}{size(row['now_bytes'])}  {verb} {row['dropped_files']} files, "
                f"{size(row['dropped_bytes'])} unpacked ({rules_said}{more})")
    if row["state"] == "nothing":
        return f"{head}  nothing to drop"
    return f"{head}  {row['state']}: {row.get('note') or 'see above'}"


def collect(run: Path, stats: dict) -> dict:
    """The run file's lines, per set, with each set's totals."""
    sets: dict = {}
    for name, counted in stats.items():
        sets[name] = dict(counted, examined=0, rules=[], dropped_files=0, dropped_bytes=0,
                          was_bytes=0, now_bytes=0, seconds=0, rewrites=0, failed=0, unapproved=0, run=[])
    for text in Path(run).read_text().splitlines():
        row = json.loads(text)
        into = sets[row["set"]]
        into["run"].append(row)
        into["examined"] += row["state"] != "unapproved"
        into["seconds"] += row["seconds"]
        into["failed"] += row["state"] in ("failed", "refused")
        into["unapproved"] += row["state"] == "unapproved"
        if row["state"] in ("slimmed", "would-slim"):
            into["rewrites"] += 1
            into["rules"] = add_rules(into["rules"], row["rules"])
            for key in ("dropped_files", "dropped_bytes", "was_bytes", "now_bytes"):
                into[key] += row[key]
    for into in sets.values():
        into["left"] = max(into["pending"] - into["examined"] - into["unapproved"], 0)
        into["left_bytes"] = max(into["pending_bytes"] - sum(r["was_bytes"] for r in into["run"]), 0)
    return sets


def estimate(sets: dict) -> dict:
    """How long the rewrite would take, from what this dry run measured: the snapshots it
    examined, and the ones it did not reach projected by their size in the store."""
    seconds = rest = saved_rest = 0.0
    for into in sets.values():
        examined_bytes = sum(r["was_bytes"] for r in into["run"])
        seconds += into["seconds"] * REWRITE_FACTOR + REPLACE_SECONDS * into["rewrites"]
        if into["left"] and examined_bytes and into["examined"]:
            share = into["left_bytes"] / examined_bytes
            rest += (into["seconds"] * REWRITE_FACTOR * share
                     + REPLACE_SECONDS * into["left"] * into["rewrites"] / into["examined"])
            saved_rest += (into["was_bytes"] - into["now_bytes"]) * share
    return {"seconds": max(int(seconds), 1), "rest_seconds": int(rest), "rest_saved_bytes": int(saved_rest)}


def some(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def words(sets: dict, dry: bool, guess: dict) -> list[str]:
    lines = []
    for name, into in sets.items():
        lines.append(f"{name}: {into['examined']} of {some(into['snapshots'], 'snapshot')} examined, "
                     f"{into['slim_before']} already slim before this run")
        if into.get("older_rules"):
            lines.append(f"  {into['older_rules']} slimmed under older rules: what decides a drop has changed "
                         "since, so each is looked at again")
        if into["rules"]:
            wide = max(len(r["rule"]) for r in into["rules"]) + 2
            lines.append(f"  {'rule':<{wide}}{'files':>10}{'unpacked':>12}")
            lines += [f"  {r['rule']:<{wide}}{r['files']:>10}{size(r['bytes']):>12}" for r in into["rules"]]
            lines.append(f"  {'dropped':<{wide}}{into['dropped_files']:>10}{size(into['dropped_bytes']):>12}")
            less = size(into["was_bytes"] - into["now_bytes"])
            lines.append(f"  in the store: {size(into['was_bytes'])} would become about {size(into['now_bytes'])}, about {less} less"
                         if dry else
                         f"  in the store: {size(into['was_bytes'])} became {size(into['now_bytes'])}, {less} less")
        elif into["examined"]:
            lines.append("  nothing to drop in what was examined")
        if into["left"]:
            lines.append(f"  not examined: {some(into['left'], 'snapshot')}, {size(into['left_bytes'])} in the store")
        if into["failed"]:
            lines.append(f"  {into['failed']} could not be read or proven, or were not what the dry run showed, and were left as they are")
        if into["unapproved"]:
            lines.append(f"  {some(into['unapproved'], 'snapshot')} the dry run has not shown, so not looked at: "
                         f"slim --dry-run --set {name}")
        kept = into.get("slim_old") or {}
        if kept.get("count"):
            lines.append(f"  old archives kept in the store: {kept['count']}, {size(kept['bytes'])} "
                         f"(slim --purge --set {name} removes them)")
    lines.append("the way back: a rewrite keeps the archive it replaces in the store, under slim-old/<set>/. "
                 "slim --restore <id> puts one back over its name; slim --purge removes them, and only "
                 "then is the space freed.")
    if dry:
        lines.append("dry run: nothing was written to the store.")
        lines.append(f"estimate, rough: the rewrite of what was examined takes about {span(guess['seconds'])}")
        if guess["rest_seconds"]:
            lines.append(f"estimate, rough: the snapshots not examined, about {span(guess['rest_seconds'])} more "
                         f"and about {size(guess['rest_saved_bytes'])} less in the store, projected by size")
    return lines


def cmd_record(args) -> int:
    summary = load(Path(args.plan)) if args.plan else {}
    row = {"set": args.set, "id": args.id, "state": args.state, "was_bytes": args.was_bytes,
           "now_bytes": args.now_bytes if args.now_bytes is not None else args.was_bytes,
           "seconds": args.seconds, "note": args.note or "",
           "dropped_files": summary.get("dropped_files", 0),
           "dropped_bytes": summary.get("dropped_bytes", 0),
           "rules": summary.get("rules", []), "nodes": summary.get("nodes", []),
           "outside": summary.get("outside", {})}
    with open(args.run, "a") as handle:
        handle.write(json.dumps(row) + "\n")
    if args.log and args.state == "slimmed":
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
        with open(args.log, "a") as handle:
            handle.write(json.dumps(dict(row, at=args.at)) + "\n")
    print(line_of(row))
    return 0


def cmd_summary(args) -> int:
    stats = {}
    for pair in args.stats:
        name, _, path = pair.partition("=")
        stats[name] = load(Path(path))
    sets = collect(Path(args.run), stats)
    for pair in args.old:
        name, _, path = pair.partition("=")
        sizes = [int(line.split("\t")[1] or 0) for line in Path(path).read_text().splitlines() if line.strip()]
        if name in sets:
            sets[name]["slim_old"] = {"count": len(sizes), "bytes": sum(sizes)}
    guess = estimate(sets)
    if args.json:
        print(json.dumps({"dry_run": args.dry, "sets": sets, "estimate": guess if args.dry else None}))
    else:
        print("\n".join(words(sets, args.dry, guess)))
    return 0


