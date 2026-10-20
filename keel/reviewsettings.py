"""The review fetcher's two settings, auto review and the review model (lane RETIRE, RT-2).

Auto review decides where a new review card is filed: at assigned (it starts by itself)
when on, in the inbox (it waits for his Review tap) when off. The review model is the model
a new review card carries. `keel/reviewcards.py` reads both on every filing, and the gear on
the deck's Reviews page shows and sets them (through the adapter's `act do reviews
set_auto_review|set_review_model`, which calls `write` here).

THE SAME TWO HALVES AS THE JUDGES' SWITCH (`keel/judges.py`), for the same reason:

- `[spaces.<name>] review_auto` and `review_model` in the install's `config.toml` are the SHIPPED values
  (his, carried over from the old review scanner's flag files on 2026-09-24: off, opus).
- `state/review-settings.json` holds the LIVE OVERRIDE, `{space: {"auto", "model"}}`, and
  only the gear writes it. The effective value is the override where there is one.

The live value is not written into the config because, when this was decided, the config was
a tracked `keel.toml`, and a tracked file is never left modified on a main checkout. The
override file sits beside the board, written by a temp file and a rename.

Before this, both settings lived in the retired review scanner's own flag files, in its
state directory, and the gear wrote them by shelling the scanner's CLI. Nothing in Keel
reads that directory any more.
"""

from __future__ import annotations

import json
from datetime import datetime
import os
from pathlib import Path

# The models a review card may be filed on: the two the old scanner offered.
REVIEW_MODELS = ("opus", "sonnet")
DEFAULT_MODEL = "sonnet"            # a space that names none, as the old scanner defaulted
SWITCHES = ("on", "off")
OVERRIDE_FILE = "review-settings.json"   # under state/
KEYS = ("auto", "model")


class SettingError(ValueError):
    """A value the gear may not set; the message says what it may be."""


def path(cfg) -> Path:
    return Path(cfg.state_dir) / OVERRIDE_FILE


def overrides(cfg) -> dict:
    """The whole override file, `{space: {"auto"?, "model"?}}`; empty on any trouble."""
    try:
        data = json.loads(path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def shipped(space) -> dict:
    """The space's own values from the config."""
    return {"auto": bool(getattr(space, "review_auto", False)),
            "model": getattr(space, "review_model", None) or DEFAULT_MODEL}


def effective(cfg, name: str) -> dict:
    """`{"auto": bool, "model": str}` for one space: the override where the gear set one,
    else the config. A hand-edited override that is not a valid value is ignored."""
    space = cfg.spaces.get(name)
    out = shipped(space) if space is not None else {"auto": False, "model": DEFAULT_MODEL}
    live = overrides(cfg).get(name)
    if isinstance(live, dict):
        if isinstance(live.get("auto"), bool):
            out["auto"] = live["auto"]
        if live.get("model") in REVIEW_MODELS:
            out["model"] = live["model"]
    return out


def parse(key: str, value) -> bool | str:
    """The gear's value in the stored type, or SettingError naming the choices."""
    text = str(value if value is not None else "").strip()
    if key == "auto":
        if text not in SWITCHES:
            raise SettingError(f"auto review is one of {', '.join(SWITCHES)}, not {text or 'nothing'!r}")
        return text == "on"
    if key == "model":
        if text not in REVIEW_MODELS:
            raise SettingError(f"the review model is one of {', '.join(REVIEW_MODELS)}, not {text or 'nothing'!r}")
        return text
    raise SettingError(f"no review setting {key!r}; one of {', '.join(KEYS)}")


def write(cfg, name: str, key: str, value) -> dict:
    """Set one setting for one space and return the space's effective settings after it."""
    if name not in cfg.spaces:
        raise SettingError(f"no space {name!r}")
    stored = parse(key, value)
    data = overrides(cfg)
    entry = data.get(name) if isinstance(data.get(name), dict) else {}
    entry[key] = stored
    data[name] = entry
    save_overrides(cfg, data)
    return effective(cfg, name)


def save_overrides(cfg, data: dict) -> None:
    target = path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".new")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, target)


def clear(cfg, name: str, key: str) -> None:
    """Drop the gear's override of one setting, so the config's value is the one in force:
    what saving the key in Settings does (c-633, decision gear-override: shown)."""
    data = overrides(cfg)
    entry = data.get(name)
    if not isinstance(entry, dict) or key not in entry:
        return
    entry.pop(key)
    if entry:
        data[name] = entry
    else:
        data.pop(name)
    save_overrides(cfg, data)


# ----- his "Scan now" (2026-09-25) -----
# `state/review-scan.json`, `{space: {"last": iso, "asked"?: iso}}`, beside the override file
# on the machine that holds the space: when the fetcher last looked, and a tap asking it to
# look now. The drain's pass scans when due OR asked, then records `last` and clears the ask
# (`keel/reviewcards.py`). A schedule's record, not a setting: never in the config.
SCAN_FILE = "review-scan.json"


def scan_path(cfg) -> Path:
    return Path(cfg.state_dir) / SCAN_FILE


def _scans(cfg) -> dict:
    try:
        data = json.loads(scan_path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_scans(cfg, data: dict) -> None:
    target = scan_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".new")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, target)


def scan_state(cfg, name: str) -> dict:
    """`{"last"?: iso, "asked"?: iso}` for one space; empty when it never scanned."""
    entry = _scans(cfg).get(name)
    return dict(entry) if isinstance(entry, dict) else {}


def ask_scan(cfg, name: str, at=None) -> dict:
    """His tap: the next drain pass on this machine scans the space whatever its cadence."""
    if name not in cfg.spaces:
        raise SettingError(f"no space {name!r}")
    data = _scans(cfg)
    entry = data.get(name) if isinstance(data.get(name), dict) else {}
    entry["asked"] = (at or datetime.now().astimezone()).isoformat()
    data[name] = entry
    _save_scans(cfg, data)
    return entry


def scanned(cfg, name: str, at) -> None:
    """The fetcher looked at `at`: record it, and clear an ask it has now answered."""
    data = _scans(cfg)
    entry = data.get(name) if isinstance(data.get(name), dict) else {}
    entry["last"] = at.isoformat()
    entry.pop("asked", None)
    data[name] = entry
    _save_scans(cfg, data)
