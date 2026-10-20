"""Waking Bosun (c-521 BO-3, c-522 BO-4, c-530; docs/atlas/96-bosun.md, "Asks").

The drain on Bosun's machine (`drain.answers_upkeep`, `drain.pause_upkeep`) tells Bosun his
answers and the houses auto mode paused. It tells it with a MESSAGE into its live
session (`relay.tell`, probed 2026-09-26 on 2.1.283 on the Mac's real Bosun, c-530): a new
turn in the same process, so nothing is stopped or resumed and its session id and app link
never move. The message is a POINTER made of ids (`answers_note`, `pausewake.wake_prompt`): the
relay is a model that obeyed text inside a longer message in the probe, and the board is
the authority anyway, so Bosun reads the words there (`kb console hook` for his answers).
Only an idle Bosun is told; a working, stopped, stuck or never started one is not, and the
answers wait for the hook atop his next message. A relay that fails leaves Bosun exactly as
it was. Everything here runs under the taps' own lock (`console.held_lock`), and writes to
the same `state/console.json`.
"""

from datetime import datetime, timedelta

from keel import console, harness, relay
from keel.config import Config

# How long the wakes rest after a relay that failed (the drain passes every 30 seconds, and
# each relay is a paid model turn), read from the Journal in `state/console.json`: only
# the newest failure matters, so its twenty-entry window is enough. How many times one
# answer is pointed at is counted on the board (`asks.POINTS_MAX`).
BACKOFF_MINUTES = 15
FAILED = ("did not reach Bosun", "may not have reached Bosun")
# c-734: no two wakes land back to back, whatever starts them (a pass, a pass a tell asked
# for, a second drain's): one is not sent within this long of the newest the Journal says
# went. It is the relay's own limit (`relay.RELAY_TIMEOUT`, 120 s), the longest a sent
# message can take to start its turn; until then a Bosun just told can still read as idle.
SPACING_SECONDS = relay.RELAY_TIMEOUT
TOLD = "told "          # the Journal's word for a wake that went (`wake`)


def spaced(data: dict, now: datetime | None = None) -> bool:
    """True while the newest wake the Journal says went is under SPACING_SECONDS old."""
    for entry in reversed(data.get("history") or []):
        if entry.get("by") == "drain" and str(entry.get("what") or "").startswith(TOLD):
            try:
                at = datetime.fromisoformat(entry["at"])
            except (KeyError, TypeError, ValueError):
                return False
            now = now or datetime.fromisoformat(console.now_iso())
            return now - at < timedelta(seconds=SPACING_SECONDS)
    return False


def answers_note(ids: list[str]) -> str:
    """The message for his answers: their ids, nothing else (see the module's note)."""
    return (f"Keel drain: the user's answers to {', '.join(ids)} are recorded on the board and not "
            f"yet read by you; `kb console hook` reads them.")


def resting(data: dict, now: datetime | None = None) -> bool:
    """True while the newest failed relay in the Journal is under BACKOFF_MINUTES old."""
    for entry in reversed(data.get("history") or []):
        if entry.get("by") == "drain" and any(word in str(entry.get("what")) for word in FAILED):
            try:
                at = datetime.fromisoformat(entry["at"])
            except (KeyError, TypeError, ValueError):
                return False
            now = now or datetime.fromisoformat(console.now_iso())
            return now - at < timedelta(minutes=BACKOFF_MINUTES)
    return False


def can_wake(cfg: Config) -> bool:
    """A cheap look before the drain claims answers: this config has a Bosun, it has a
    session, no relay failed in the last BACKOFF_MINUTES, and that session is up and idle.
    `wake` checks the session again under the lock."""
    if not console.configured(cfg):
        return False
    data = console.read_state(cfg)
    if not data.get("session_id") or resting(data) or spaced(data):
        return False
    return idle(console.running_row(cfg, data))


def idle(row: dict | None) -> bool:
    """A listed row with a process that is not working: the only Bosun a message wakes."""
    return row is not None and not console.stuck(row) and row.get("status") != "busy"


def wake(cfg: Config, note: str, what: str) -> dict | None:
    """Send Bosun `note`, a pointer of ids: None when it cannot be told now (another tap holds
    the lock, it is not idle, or it was never started), else what was done.

    The message goes into the live session and starts a turn there; nothing is stopped, so
    a relay that fails leaves Bosun up, with the same link, and the Journal says what was
    not told. The error is raised for the caller: a HarnessError certainly did not deliver,
    a `relay.RelayUnclear` may have. Two live sessions named Bosun are refused before
    anything is sent, since the message goes by name and could reach the other one."""
    if not console.configured(cfg):
        return None
    with console.held_lock(cfg) as held:
        if not held:
            return None
        data = console.read_state(cfg)
        session = data.get("session_id")
        if spaced(data):
            return None         # c-734: a wake went moments ago; this one waits for a later pass
        rows = harness.agents(console.config_dir(cfg), strict=True)
        if not session or not idle(harness.find(session, rows)):
            return None
        live = [row for row in rows if row.get("name") == console.NAME and not console.stuck(row)]
        try:
            if len(live) > 1:
                raise harness.HarnessError(f"{len(live)} live sessions are named {console.NAME}, "
                                           f"so a message by name could reach the wrong one")
            relay.tell(console.NAME, note, cwd=cfg.root, env=relay_env(cfg))
        except Exception as error:  # noqa: BLE001 - a timeout or an OSError is a failed relay too
            first = (str(error).splitlines() or [type(error).__name__])[0]
            reached = ("may not have reached" if isinstance(error, relay.RelayUnclear)
                       else "did not reach")
            said = f"the message with {what} {reached} Bosun ({first}); it was left as it was"
            console.write_state(cfg, console.noted(data, said, "drain", session))
            raise
        console.write_state(cfg, console.noted(data, f"{TOLD}{what}, by message", "drain", session))
        return {"session_id": session}


def relay_env(cfg: Config) -> dict:
    """The relay's environment: Bosun's config dir, so it sees Bosun as a peer, and nothing
    of Bosun's own (no key, no `KEEL_BOSUN`, no card): its one tool is SendMessage."""
    env = harness.scoped_env(console.config_dir(cfg))
    env.pop("KEEL_CARD", None)
    env.pop(console.BOSUN_ENV, None)
    return env
