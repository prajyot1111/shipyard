"""Rows the harness lists as working with no process behind them (r-26), for `keel doctor`.

Probed 2026-09-29 on 2.1.284: c-561's superseded session 735f0cab stayed in `claude agents
--json` as `state: working` with no `status` and no `pid` for two days after its house
stopped. Every live background row carries a `pid`. Landing read the row as working and
refused c-561 four times while Bosun's read said "not running", and nothing on any surface
named the row. `housejobs.working` now reads such a row as not working (one rule for landing,
resume, the deck and Bosun); this module is what makes it SEEN: one doctor line per row, a
problem, so it is also a sighting for Bosun.

Read-only: it lists, it never stops anything (a stop is his tap, Stop session).
"""

import subprocess

from keel import harness, housejobs


def gather(cfg) -> dict:
    """`{"rows": [{space, card, said, bg_id}], "error": str|None}` over every config dir
    this machine serves, each asked once, and each session named once."""
    rows, seen, sessions, error = [], set(), set(), None
    for name in cfg.served_spaces():
        config_dir = cfg.spaces[name].config_dir
        key = str(config_dir)
        if key in seen:
            continue
        seen.add(key)
        try:
            listed = harness.agents(config_dir, strict=True)
        except (harness.HarnessError, OSError, subprocess.SubprocessError) as failed:
            error = f"{name}: {str(failed).splitlines()[0] if str(failed) else 'no answer'}"
            continue
        for row in listed:
            session = row.get("sessionId") or row.get("id")
            if housejobs.ghost(row) and session not in sessions:
                sessions.add(session)
                rows.append({"space": name, "card": row.get("name") or "no card",
                             "bg_id": row.get("id") or (row.get("sessionId") or "")[:8],
                             "said": housejobs.row_said(row)})
    return {"rows": rows, "error": error}


def line(found: dict) -> str:
    rows = found.get("rows") or []
    if found.get("error") and not rows:
        return f"ghost houses  unknown ({found['error']})"
    if not rows:
        return "ghost houses  none (no row listed as working without a process)"
    return f"ghost houses  {len(rows)}: " + ", ".join(row["card"] for row in rows)


def problems(found: dict) -> list[str]:
    """One per row: which card, the row in the harness's words, and what he can do."""
    return [f"{row['card']}: the harness lists {row['said']} with no process behind it, so "
            f"the board reads it as not running; `claude stop {row['bg_id']}` under the "
            f"{row['space']} config dir asks the harness to let it go"
            for row in found.get("rows") or []]
