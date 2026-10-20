"""Twins on a feature card: one change raised on two bases of one repo, reviewed once
(2026-09-25, reshaped by c-559 on 2026-09-27).

A story's fix is often raised on two bases of one repo (a cherry-pick: different commits,
different heads, the same change). Grouped by story, both are members of one feature card
(lane GRP). His call: review it ONCE, on the member the adapter says it follows.

- **who is a twin** is the ADAPTER's to say, by its own rule, never Keel's: a member's
  `twin_of` names the member it follows (`keel/reviewfeature.py`), and which base is the
  reviewed one, and why, is the adapter's too. The house brief passes each as
  `keel-review prep --twin <twin> <member it follows>`.
- **prep** (`pair`, then `write`) leaves the twin's diff out of what the reviewer is
  handed, names it in the header of the member it follows, and records it in
  `review-twins.json` in the card directory: per twin, the member it follows and its base.
  That file is what this round reviewed, which is why the lint and his Approve read it
  rather than the card's members, which may move after prep.
- **downstream**: the lint (`keel/review/ledger.py`, then `keel/planreview.py` C32) wants no
  finding and no verdict for a twin, and the orientation to name each twin with the member
  it follows; his Approve (`keel/reviewround.py`) gives the twin no inline comment, one
  pointer comment to the reviewed member's pull request, and the same verdict, so the two
  leave his queue together.
"""

from __future__ import annotations

import json
from pathlib import Path

TWINS_FILE = "review-twins.json"


class TwinError(ValueError):
    """A `--twin` that names no member, itself, another twin, or another repo."""


def pair(flags: list, sides: list[dict]) -> dict[str, dict]:
    """{twin label: {primary, base}} from prep's `--twin <twin> <primary>` flags, each held
    to the members prep was given (`sides`: one {label, repo, base} per member)."""
    by_label = {side["label"]: side for side in sides if side.get("label")}
    twins: dict[str, dict] = {}
    for twin, primary in flags:
        if twin not in by_label or primary not in by_label:
            raise TwinError(f"--twin {twin} {primary}: both must be members ({', '.join(by_label)})")
        if twin == primary:
            raise TwinError(f"--twin {twin} names itself")
        if by_label[twin]["repo"] != by_label[primary]["repo"]:
            raise TwinError(f"--twin {twin} {primary}: a twin is in the same repo as the member it follows")
        twins[twin] = {"primary": primary, "base": by_label[twin].get("base")}
    for twin, one in twins.items():
        if one["primary"] in twins:
            raise TwinError(f"--twin {twin} {one['primary']}: {one['primary']} is a twin itself")
    return twins


def write(card_dir: Path, twins: dict) -> None:
    path = Path(card_dir) / TWINS_FILE
    if twins:
        path.write_text(json.dumps(twins, indent=2) + "\n")
    else:
        path.unlink(missing_ok=True)


def read(card_dir: Path | None) -> dict[str, dict]:
    """The card's twins, {} when prep named none (or has not run)."""
    if card_dir is None:
        return {}
    try:
        found = json.loads((Path(card_dir) / TWINS_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def followed(card_dir: Path | None) -> dict[str, str]:
    """{twin label: the label of the member it follows}."""
    return {label: str(one.get("primary")) for label, one in read(card_dir).items() if isinstance(one, dict)}
