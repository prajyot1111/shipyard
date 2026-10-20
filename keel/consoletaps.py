"""Bosun's three taps, Start, Stop and Restart, and the stuck-row recovery they share
(c-531: split out of `keel/console.py`, a pure move).

A tap is his (the deck, `keel console <op>` at his terminal), one at a time under the tap
lock (`console.held_lock`), and never Bosun's own (`console.main` refuses them under
`KEEL_BOSUN`). Everything else about Bosun (its settings, its state file, its status) stays
in `keel/console.py`, which this module reads through its attributes, so a test that
patches one of them there patches it here too. An authority path, as console.py is.
"""

from pathlib import Path

from keel import builder, console, harness, house, housejobs
from keel import config as config_module
from keel.config import Config


def launch(cfg: Config, resume_from: str | None) -> dict:
    """Start the session, or resume `resume_from`; its ids and app link."""
    space = console.space_of(cfg)
    console.refuse_builder(cfg)         # the builder's own refusals (`builder.refusal`)
    common = dict(cwd=console.cwd(cfg), config_dir=console.config_dir(cfg),
                  settings_path=console.write_settings(cfg), model=space.model,
                  permission_mode=console.permission_mode(cfg), env=console.launch_env(cfg),
                  agents=builder.review_agents() if builder.in_app(cfg) else None)
    if resume_from:
        result = harness.resume_bg(resume_from, console.RESUME_PROMPT, name=console.NAME, **common)
    else:
        result = harness.start_bg(console.cwd(cfg), console.START_PROMPT, name=console.NAME,
                                  **{k: v for k, v in common.items() if k != "cwd"})
    return dict(result, app_link=house.app_link(result["bg_id"], console.config_dir(cfg)))


def came_up(cfg: Config, data: dict, result: dict, what: str, actor: str) -> dict:
    data = {key: value for key, value in data.items() if key != console.STALE_MARK}
    data = dict(data, session_id=result["session_id"], bg_id=result["bg_id"],
                app_link=result.get("app_link"), up_since=console.now_iso())
    data = console.noted(data, what, actor, result["session_id"])
    console.write_state(cfg, data)
    return data


def start(cfg: Config, actor: str = "human") -> dict:
    """Start Bosun: resume the last session when there is one, else a fresh one. A stuck row
    (listed with no process) is not up: it is stopped where it can be, and then resumed
    when the stop was confirmed; when it was not, a FRESH Bosun is started, since resuming a
    session the harness still lists would start a copy of it."""
    console.refuse_unconfigured(cfg)
    data = console.read_state(cfg)
    row = console.running_row(cfg, data, strict=True)
    if row is not None and not console.stuck(row):
        raise console.ConsoleError("Bosun is already up; Restart starts it fresh")
    if row is not None:
        data, gone = cleared(cfg, data, row, actor)
        if not gone:
            result = launch(cfg, None)
            came_up(cfg, data, result, "started fresh past a stuck session", actor)
            return console.status(cfg)
    resume_from = data.get("session_id")
    result = launch(cfg, resume_from)
    came_up(cfg, data, result, "resumed" if resume_from else "started", actor)
    return console.status(cfg)


def cleared(cfg: Config, data: dict, row: dict, actor: str) -> tuple[dict, bool]:
    """A stuck row, stopped where the harness can confirm it (it could not on the Mac), and
    the Journal told either way; the state as written, and whether the stop was confirmed."""
    bg_id = row.get("id") or data.get("bg_id") or ""
    try:
        housejobs.stop(bg_id, console.config_dir(cfg), harness.stop)
        said, gone = f"session {bg_id} was listed with no process (stuck); stopped it", True
    except harness.HarnessError as error:
        gone = False
        first = next((line.strip() for line in str(error).splitlines()[1:] if line.strip()), "")
        said = (f"session {bg_id} was listed with no process (stuck); claude stop could not "
                f"confirm it ({first or 'no reason given'}), so it was left listed")
    data = console.noted(data, said, actor, data.get("session_id"))
    console.write_state(cfg, data)
    return data, gone


def stop(cfg: Config, actor: str = "human") -> dict:
    """Stop Bosun. Its conversation stays, and Start picks it up again. A stuck row is
    cleared as far as the harness allows, and never refused."""
    console.refuse_unconfigured(cfg)
    data = console.read_state(cfg)
    row = console.running_row(cfg, data, strict=True)
    if row is None:
        raise console.ConsoleError("Bosun is not running")
    if console.stuck(row):
        cleared(cfg, data, row, actor)
        return console.status(cfg)
    housejobs.stop(row.get("id") or data["bg_id"], console.config_dir(cfg),
                   harness.stop)
    console.write_state(cfg, console.noted(data, "stopped", actor, data.get("session_id")))
    return console.status(cfg)


def restart(cfg: Config, actor: str = "human") -> dict:
    """Stop Bosun if it is up, then start a FRESH session from its memory. A stuck row is
    cleared as far as the harness allows, and the fresh start goes ahead."""
    console.refuse_unconfigured(cfg)
    data = console.read_state(cfg)
    row = console.running_row(cfg, data, strict=True)
    if row is not None and console.stuck(row):
        data = cleared(cfg, data, row, actor)[0]
    elif row is not None:
        housejobs.stop(row.get("id") or data["bg_id"], console.config_dir(cfg),
                       harness.stop)
        data = console.noted(data, "stopped", actor, data.get("session_id"))
        console.write_state(cfg, data)      # the stop is kept even when the fresh launch fails
    result = launch(cfg, None)
    came_up(cfg, data, result, "restarted", actor)
    return console.status(cfg)


TAPS = {"start": start, "stop": stop, "restart": restart}


def tap(cfg: Config, op: str, actor: str = "human") -> dict:
    """One of OPS, carried out here; ConsoleError with the reason on refusal.

    ONE TAP AT A TIME. A start reads the file, checks the harness and launches, which takes
    seconds; two taps at once (the desk and the phone) would each launch a Bosun, and the
    one the file forgot would run on unseen. The second tap waits for no one: it is refused."""
    if op not in TAPS:
        raise console.ConsoleError(f"Bosun's taps are {', '.join(console.OPS)}, not {op!r}")
    with console.held_lock(cfg) as held:
        if not held:
            raise console.ConsoleError("another tap on Bosun is still being carried out; "
                               "look again in a moment")
        fresh_builder(cfg)
        try:
            from keel import bosuntalk
            if bosuntalk.voice_ended(cfg, op, actor):     # c-523: his tap ends a voice hold
                return console.status(cfg)
            return TAPS[op](cfg, actor)
        except harness.HarnessError as error:
            raise console.ConsoleError(failed_launch(op, str(error))) from None


def fresh_builder(cfg: Config) -> None:
    """The `[builder]` table as the file says it now. A tap runs inside the deck, which read
    its config once at its start, so a hand edit of `[builder] mode` (bypass for auto) took
    effect only after the deck restarted (his Mac, 2026-10-03). Only that table: the rest of
    the deck's config is what the deck runs on. A file that does not load leaves it as it was."""
    source = getattr(cfg, "source", None)
    if not source or not Path(source).is_file():
        return
    try:
        cfg.builder = config_module.load(Path(source), ensure=False).builder
    except Exception:  # noqa: BLE001 - a broken file is the doctor's to say; the tap goes on
        pass


def failed_launch(op: str, text: str) -> str:
    """The sentence for a launch the harness refused: its first line that says something
    (the first is `claude exited N:`), and for a resume, the way out."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    said = next((line for line in lines[1:] if line), lines[0] if lines else "no reason given")
    if text.startswith("claude agents"):
        return f"could not tell whether Bosun is running ({said}); nothing was done"
    if op == "start":
        return f"could not start or resume Bosun ({said}); Restart starts it fresh"
    return f"could not {op} Bosun ({said})"
