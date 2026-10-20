"""Keel's own browser install: where it lives, and whether this host has one.

The tool is `bin/keel-browser` (its engine is `bin/keel-browser.js`); this module is the
Python half that knows the same two facts, so `keel doctor` can say whether a house on this
machine could render anything. It is deliberately small: the script is the source of truth
for how a browser is launched, and `tests/test_browser.py` holds the two files to the same
directory and the same pinned version so they cannot drift.

ONE KEEL-OWNED PLACE PER MACHINE, `~/.keel-browser`, overridable with `KEEL_BROWSER_HOME`.
Not a worktree, which is reaped and would make the next house download it again; not
`state/`, which is backed up nightly and does not want 400 MB of regenerable bytes in every
snapshot; not another project's directory, because a check that reads what someone else owns
stops working the day they move it.

IT NEVER LAUNCHES A BROWSER. `keel doctor` runs on a timer's schedule and from the deck, and
starting a Chromium to answer "is a Chromium installed" is how a health check becomes the
thing that eats the machine's memory. Presence is what this reports; `bin/keel-browser check`
is the one that proves a launch, and a person runs it.

IT IS A PROBLEM ONLY WHERE IT IS USED. A machine with `browsers_max` set and spaces to
serve is one where a card carrying `options.browser` will start a house that needs this
(`keel/drain.py`). Everywhere else the line reads "not applicable", so a doctor does not go
red over a tool nothing will ask for.
"""

import os
from pathlib import Path

HOME_VAR = "KEEL_BROWSER_HOME"
DEFAULT_HOME = "~/.keel-browser"
# The pin `bin/keel-browser` writes into its package.json. Two copies of one number, held
# together by a test rather than by memory.
PLAYWRIGHT_VERSION = "1.63.0"
MODULE = "node_modules/playwright-core"
BROWSERS = "browsers"
INSTALL_HINT = "bin/keel-browser install"


def home() -> Path:
    """The install directory: `KEEL_BROWSER_HOME` if set, else `~/.keel-browser`."""
    return Path(os.environ.get(HOME_VAR) or DEFAULT_HOME).expanduser()


def chromium_builds(where: Path) -> list[str]:
    """The chromium builds under `browsers/`, by directory name, newest name last.

    Playwright names them `chromium-<build>` and `chromium_headless_shell-<build>`; either
    one means `bin/keel-browser install` has run here.
    """
    try:
        return sorted(entry.name for entry in (where / BROWSERS).iterdir()
                      if entry.is_dir() and entry.name.startswith("chromium"))
    except OSError:
        return []


def gather(cfg) -> dict:
    """Presence only, and `applicable` false where no house here would drive a browser."""
    where = home()
    applicable = cfg.browsers_max is not None and bool(cfg.served_spaces())
    found = {"applicable": applicable, "home": str(where), "version": PLAYWRIGHT_VERSION,
             "package": (where / MODULE).is_dir(), "chromium": chromium_builds(where)}
    found["ok"] = bool(found["package"] and found["chromium"])
    return found


def problem(found: dict) -> str | None:
    """The one sentence for `keel doctor`'s missing list, or None."""
    if not found.get("applicable") or found.get("ok"):
        return None
    missing = "playwright-core is not installed" if not found["package"] else "no chromium build"
    return (f"browser: {missing} under {found['home']}, so a card carrying options.browser "
            f"has no tool to drive ({INSTALL_HINT})")


def line(found: dict) -> str:
    if not found.get("applicable"):
        return "browser       not applicable (no browsers_max for this host)"
    if not found.get("ok"):
        return f"browser       MISSING at {found['home']}  ({INSTALL_HINT})"
    return (f"browser       {found['home']}  playwright-core {found['version']}, "
            f"{len(found['chromium'])} chromium build(s)")
