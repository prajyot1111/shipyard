"""`keel converse bosun`: "put me through to Bosun", on the same voice hold a house gets.

c-523 (BO-5) settles it as c-517 designed it: the conversation with Bosun is a house
conversation in every mechanism (`keel/converse.py`, `keel/housetier.py`,
`keel/housetalk.py`). Bosun's background session is stopped, one kept-alive `claude -p
--resume` takes his sentences, and "back to Harbor" closes it and wakes Bosun with no flags
and no prompt, which keeps the session id and the app link (probed on 2.1.283 for this card:
`state/cards/c-523/probe/`). What differs is only what a card would have supplied:

- **The hold** is the board's `holds` row keyed `bosun` (`keel/bosunhold.py`), not a key on a
  card, because Bosun has no card.
- **The plan** is Bosun's: its cwd (`console.cwd`: Keel's root, or on an install the
  builder's clones, never the live checkout), personal's config dir, its settings file (whose
  `env` holds its key, c-553), its model and permission mode (`console.permission_mode`:
  auto for the builder), and its launch environment
  (`console.launch_env`), so its `kb` is still `bosun` while he talks to it.
- **The guards** add two facts only Bosun has. It must have been started and not be stuck.
  And he may be typing to it in the app, which the harness cannot say; the nearest fact is
  the transcript's newest turn, so a turn under RECENT_SECONDS old that voice did not take is
  read as his app conversation and refused politely.
- **The record** is Bosun's own transcript (his words land in its conversation) and the
  Journal (`state/console.json`'s history): "voice connected", "voice released".

The board's half (connect, answer, release) and the session's half (the plan, the guards,
the stop and the wake) both run on this machine: the second in its `keel serve`, reached by
`housetier` over loopback with a pseudo card that names Bosun.
"""

import time
from datetime import datetime, timezone

from keel import console, converse, harness, housetier, narration
from keel.board import Refused
from keel.config import Config

TARGET = "bosun"
TITLE = "Bosun"
SUBTITLE = "the admin console"
ACTOR = "voice"
RECENT_SECONDS = 120
# The two refusal codes only a Bosun open can answer (beside housetier's busy and memory).
DOWN = "down"
TYPING = "typing"

# WHAT HE HEARS. Every one is a sentence, because the caller is holding a microphone open.
NO_CONSOLE = "There is no Bosun on this board."
CONNECTED = "Connected to Bosun."
BACK = "Back to Harbor."
BUSY = ("Bosun is in the middle of a turn, maybe answering you in the app, so I will leave it "
        "with you. Ask me again when it is done.")
SAID_TYPING = ("You were talking to Bosun in the app a moment ago, so I will leave it with you. "
               "Ask me again in a couple of minutes.")
NEVER = "Bosun has never been started. Start it from the Console, then ask me again."
STOPPED = "Bosun is stopped. Start it from the Console, then ask me again."
STUCK = "Bosun is stuck. Start it from the Console, then ask me again."
SHORT = "{host} is short of memory. Try again in a minute."
AWAY = "{host} is away, so I cannot reach Bosun."
NOT_CLOSED = ("{host} has not closed the last voice conversation with Bosun yet, so I cannot "
              "reach it. Its drain puts Bosun back within a minute or two.")
AWAY_MID = "{host} went away, so that conversation with Bosun is over. We are back to Harbor."
REFUSED = "{host} would not open a conversation with Bosun: {why}"
UNPINNED = "That conversation with Bosun was ended, so we are back to Harbor."
TURN_FAILED = "That turn did not come back: {why}"

# THE FRAMING, said once on the first sentence of a conversation (as a house's is).
SPOKEN = ("The user is talking to you out loud, through Harbor's voice gateway, instead of in the "
          "Claude app; your app chat is offline until the user goes back to Harbor. Answer in one to "
          "three spoken sentences, plain words, no markdown, no file paths. If the user asks you to "
          "leave, to go back to Harbor, or to end this conversation, reply with one short "
          "goodbye and write <<keel-leave>> on its own line at the end of your answer.")
MISHEARD = ("The user's words reached you through speech recognition and may be misheard. Your "
            "authority is exactly what it is in the chat: anything hard to reverse, you say "
            "back and wait for a spoken yes. An answer the user gives here to one of your asks is a "
            "chat answer: record it with --by chat and the user's exact words, as you always do.")


def spoken_host(cfg: Config) -> str:
    """Bosun's machine at the front of a spoken sentence, as `converse.spoken_host` names it."""
    return converse.spoken_host(cfg, cfg.host)


def pseudo(cfg: Config) -> dict:
    """What `housetier` is handed where a card would go: a card-shaped dict naming Bosun."""
    return {"id": TARGET, "space": console.LABEL, "title": TITLE, "stage": "",
            "session_id": "", "options": {}}


def framing(said: str) -> str:
    from keel import prompts
    return prompts.joined(SPOKEN, MISHEARD, "The user said:\n\n" + prompts.quoted(said))


def framing_more(said: str) -> str:
    from keel import prompts
    return "The user said:\n\n" + prompts.quoted(said)


# ----- the board's half -----

def configured(cfg: Config) -> bool:
    return console.configured(cfg)


def refusal(cfg: Config, was: housetier.Opened) -> str:
    host = spoken_host(cfg)
    if was.refused == housetier.BUSY:
        return BUSY
    if was.refused == TYPING:
        return SAID_TYPING
    if was.refused == DOWN:
        return {"stuck": STUCK, "stopped": STOPPED}.get(was.why, NEVER)
    if was.refused == housetier.SHORT:
        return SHORT.format(host=host)
    if was.refused == housetier.UNREACHED:
        return AWAY.format(host=host)
    return REFUSED.format(host=host, why=was.why or "no reason given")


def connect(cfg: Config, board) -> dict:
    """Take the hold, then open the conversation on Bosun's machine; a sentence either way."""
    if not configured(cfg):
        return {"ok": False, "say": NO_CONSOLE, "card": TARGET}
    held = board.bosun_hold()
    if held:
        held = board.hold_bosun(ACTOR, cfg.voice_hold_seconds)
        return connected(held)
    if not repaired(cfg, board):
        return {"ok": False, "say": NOT_CLOSED.format(host=spoken_host(cfg)), "card": TARGET}
    took = board.hold_bosun(ACTOR, cfg.voice_hold_seconds, turns=0)
    was = housetier.open_session(cfg, pseudo(cfg), timeout=harness.TURN_TIMEOUT)
    if not was.ok:
        if was.stopped:
            # THE DOOR STOPPED BOSUN AND THEN COULD NOT OPEN THE CONVERSATION: put it back,
            # since nothing automatic would ever start it again.
            housetier.close_session(cfg, pseudo(cfg), wake=True)
        board.release_bosun(ACTOR)
        return {"ok": False, "say": refusal(cfg, was), "card": TARGET}
    now = board.bosun_hold()
    if not (now and now.get("at") == took.get("at")):
        # HIS TAP ENDED IT WHILE THE OPEN WAS IN FLIGHT: undo over there what this did.
        housetier.close_session(cfg, pseudo(cfg), wake=bool(was.stopped))
        return {"ok": False, "say": UNPINNED, "card": TARGET}
    return connected(board.hold_bosun(ACTOR, cfg.voice_hold_seconds, stopped=was.stopped))


def repaired(cfg: Config, board) -> bool:
    """A hold that ran out and the drain has not cleared yet is repaired HERE before a new
    one is taken, the way the drain would: the conversation is closed and Bosun woken if that
    voice stopped it. False when the server did not close it: the old hold stays for the
    drain, and nothing new is taken over it."""
    expired = board.bosun_hold_expired()
    if expired is None:
        return True
    shut = housetier.close_session(cfg, pseudo(cfg), wake=bool(expired.get("stopped")))
    if shut.status in (housetier.AWAY, housetier.FAILED):
        return False        # the drain closes, wakes and journals it
    board.release_bosun(ACTOR)
    return True


def connected(held: dict) -> dict:
    # The page's header and the gateway's line 2 read it: "Entering Bosun, the admin console."
    return {"ok": True, "say": CONNECTED, "card": TARGET, "stage": "", "title": SUBTITLE,
            "space": console.LABEL, "held_until": held.get("until")}


def answer(cfg: Config, board, said: str, timeout: int, pinned: bool = False,
           progress: str = "", turn_id: str = "") -> dict:
    """One sentence into Bosun's conversation. A turn with no pin behind it (the phone
    Harbor's single question) connects, asks and lets go, as a house's one-shot does."""
    from keel import converse
    if pinned and not board.bosun_hold():
        return {"ok": False, "say": UNPINNED, "card": TARGET, "unpin": True}
    own = not board.bosun_hold()
    if own:
        opened = connect(cfg, board)
        if not opened["ok"]:
            return opened
    took = board.bosun_hold() or {}
    narrator = narration.Narrator(progress, turn=turn_id) if progress else None
    leave = converse.LeaveDirective()
    on_event = converse.events_into(narrator, None, leave) if narrator is not None else None
    turn_id = turn_id or converse.new_turn_id()
    started = time.time()
    try:
        payload = housetier.say(cfg, pseudo(cfg), said, turn_id=turn_id, timeout=timeout,
                                on_event=on_event)
    except housetier.Unreachable:
        return {"ok": False, "say": AWAY_MID.format(host=spoken_host(cfg)), "card": TARGET,
                "unpin": True}
    except housetier.Away:
        # NOTHING REACHED BOSUN: its machine refused the sentence, which for Bosun means the
        # conversation was ended there (his tap, or it went idle). Never reopened
        # silently: the hold goes, the pin drops, and he hears why.
        release(cfg, board)
        return {"ok": False, "say": UNPINNED, "card": TARGET, "unpin": True}
    except harness.HarnessError as error:
        if own:
            release(cfg, board)
        return {"ok": False, "say": TURN_FAILED.format(why=error), "card": TARGET}
    text = converse.spoken_answer(None, leave, payload)
    if leave.asked and not text.strip():
        text = converse.LEAVING_SAID
    held = board.bosun_hold() or {}
    turns = int(held.get("turns") or 0) + 1
    if own:
        release(cfg, board)
        held = {}
    elif not (held and held.get("at") == took.get("at")):
        # HIS TAP ENDED IT WHILE THE TURN RAN: the answer is his, and the hold is not
        # re-taken over a conversation that is over.
        return {"ok": True, "say": text, "card": TARGET, "unpin": True, "turns": turns}
    else:
        held = board.hold_bosun(ACTOR, cfg.voice_hold_seconds, turns=turns)
    return {"ok": True, "say": text, "card": TARGET, "stage": "", "drew": 0, "board": "",
            "leave": leave.asked, "seconds": round(time.time() - started, 1),
            "held_until": held.get("until"), "turns": turns}


def release(cfg: Config, board) -> dict:
    """"Back to Harbor": close the conversation there, and wake Bosun there if voice stopped
    it. A machine that is away keeps the hold: its own drain repairs it when it is back."""
    held = board.bosun_hold()
    if not held:
        return {"ok": True, "say": BACK, "card": TARGET, "held_until": None}
    shut = housetier.close_session(cfg, pseudo(cfg), wake=bool(held.get("stopped")))
    if shut.status in (housetier.AWAY, housetier.FAILED):
        # NOTHING THERE CLOSED IT, so nothing woke Bosun: the hold is left for the drain,
        # which closes, wakes and journals it, and is run out NOW (its `until` set
        # to this moment) so the conversation reads as over and that drain repairs it on
        # its next pass. Bosun has no `reconcile` to put it back otherwise.
        board.hold_bosun(ACTOR, 0)
        return {"ok": True, "say": BACK, "card": TARGET, "held_until": None,
                "away": shut.status == housetier.AWAY, "failed": shut.status == housetier.FAILED}
    board.release_bosun(ACTOR)
    return {"ok": True, "say": BACK, "card": TARGET, "held_until": None,
            "turns": held.get("turns") or 0, "woke": shut.woke}


# ----- the session's half: in the `keel serve` Bosun runs beside -----

def door_plan(cfg: Config, board) -> dict:
    """Bosun's plan, after the board's question (is voice holding it)."""
    if not console.configured(cfg):
        raise Refused(console.NO_BOSUN)
    if not board.bosun_hold():
        raise Refused("Bosun is not held by voice, so there is no conversation")
    data = console.read_state(cfg)
    space = console.space_of(cfg)
    # A Bosun never started has no session; `ready` refuses it with its own sentence.
    return {"card": TARGET, "bosun": True, "session_id": data.get("session_id") or "",
            "cwd": str(console.cwd(cfg)), "config_dir": str(console.config_dir(cfg)),
            "settings_path": str(console.write_settings(cfg)), "model": space.model,
            "add_dirs": [], "restricted": False, "tools": None, "worktree": False,
            "permission_mode": console.permission_mode(cfg),
            "env": console.launch_env(cfg)}


def ready(cfg: Config, made: dict) -> tuple[str, str] | None:
    """The refusal code (and its detail) for the guards only Bosun has, or None: never
    started, stopped and stuck are all refused (the plan's guards), so voice only ever
    holds a Bosun it stopped itself, and "back to Harbor" always puts it back."""
    if not made.get("session_id"):
        return DOWN, "never"
    data = console.read_state(cfg)
    row = console.running_row(cfg, data)
    if row is None:
        return DOWN, "stopped"
    if console.stuck(row):
        return DOWN, "stuck"
    if row.get("status") == "busy":
        return housetier.BUSY, ""
    if typing(cfg, data):
        return TYPING, ""
    return None


def typing(cfg: Config, data: dict, now: datetime | None = None) -> bool:
    """Its newest turn is under RECENT_SECONDS old and newer than voice's own last release:
    the nearest fact to "he is typing to it in the app" the transcript holds."""
    path = console.transcript_of(console.config_dir(cfg), data.get("session_id"))
    last = console.turn_facts(console.tail_records(path), 0)["last_turn"] if path else None
    last_at = moment(last)
    if last_at is None:
        return False
    released = moment(data.get("voice_released_at"))
    if released is not None and last_at <= released:
        return False
    return ((now or datetime.now(timezone.utc)) - last_at).total_seconds() < RECENT_SECONDS


def moment(stamp) -> datetime | None:
    if not stamp:
        return None
    try:
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def noted(cfg: Config, what: str, **fields) -> None:
    data = console.read_state(cfg)
    console.write_state(cfg, dict(console.noted(data, what, ACTOR, data.get("session_id")),
                                  **fields))


def opened(cfg: Config, stopped: bool) -> None:
    noted(cfg, "voice connected" + ("" if stopped else " (it was already stopped)"))


def wake(cfg: Config) -> bool:
    """Put Bosun back with no flags and no prompt, under its own environment. A build of
    `claude` that answered with a new session id resumed it in all but name: the record
    follows the new id, and the next status asks the log for its link."""
    data = console.read_state(cfg)
    result = harness.wake(data["session_id"], cwd=console.cwd(cfg),
                          config_dir=console.config_dir(cfg), name=console.NAME,
                          env=console.launch_env(cfg))
    fields = {"bg_id": result["bg_id"]}
    if result["session_id"] != data["session_id"]:
        fields.update(session_id=result["session_id"], app_link=None)
    console.write_state(cfg, dict(console.read_state(cfg), **fields))
    return True


def closed(cfg: Config, woke: bool, failed: str = "") -> None:
    said = ("; Bosun is awake again" if woke else
            f"; waking Bosun failed, so it is down: {failed}" if failed else "")
    noted(cfg, "voice released" + said, voice_released_at=console.now_iso())


# ----- the paths that end a hold without "back to Harbor" -----

def end_for_tap(cfg: Config) -> dict | None:
    """His Start, Stop or Restart while voice holds Bosun: the conversation ends first (his
    tap wins, as his Stop does over a house's hold), with no wake, since the tap itself
    decides what Bosun does next. The hold as it stood, or None when there was none.

    THE RELEASE IS VOICE'S OWN: the hold belongs to voice, and voice may clear it. A board
    that cannot be read is no reason to leave a conversation holding the session under his
    tap, so the close is sent anyway; the house tier also refuses any later sentence into a
    conversation it no longer has (`housetier.house_plan`)."""
    from keel.board import open_board
    board = None
    try:
        board = open_board(cfg)
        state = board.bosun_hold_state()
        held = state.get("hold") or state.get("expired")
    except Exception:                                                   # noqa: BLE001
        held = {}
    try:
        if held is None:
            return None
        housetier.close_session(cfg, pseudo(cfg), wake=False)
        if board is not None:
            try:
                board.release_bosun(ACTOR)
            except Exception:                                           # noqa: BLE001
                pass            # it runs out on its own, and the drain clears it
        return held
    finally:
        if board is not None:
            board.close()


def voice_ended(cfg: Config, op: str, actor: str) -> bool:
    """`consoletaps.tap`'s first step: end a voice conversation with Bosun before the tap acts.
    True when that was the whole of a Stop: voice had stopped the session itself, so there
    is nothing left running to stop, and the Journal says so."""
    held = end_for_tap(cfg)
    if held is None:
        return False
    data = console.read_state(cfg)
    if op != "stop" or console.running_row(cfg, data, strict=True) is not None:
        return False
    what = ("stopped (voice had already stopped it)" if held.get("stopped")
            else "stopped (it was not running)")
    console.write_state(cfg, console.noted(data, what, actor, data.get("session_id")))
    return True


def release_expired(cfg: Config, board) -> bool:
    """The drain: a hold that ran out is cleared and Bosun woken if voice stopped it.
    The close goes to this machine's own server, which owns the conversation; when nothing
    answers there, nothing holds the session and the wake is done here."""
    if not console.configured(cfg):
        return False
    held = board.bosun_hold_expired()
    if held is None:
        return False
    shut = housetier.close_session(cfg, pseudo(cfg), wake=bool(held.get("stopped")))
    board.release_bosun("drain")
    if shut.status == housetier.FAILED:
        # SOMETHING STILL HOLDS THE SESSION: a wake would be refused. Said in the Journal,
        # which is where his Console shows why Bosun is down and that Start is the way back.
        closed(cfg, False, failed="the conversation would not close; Start brings it back")
    elif shut.status == housetier.AWAY and held.get("stopped"):
        try:
            wake(cfg)
        except Exception as error:                                      # noqa: BLE001
            closed(cfg, False, failed=str(error).splitlines()[0] if str(error) else
                   type(error).__name__)
            return True
        closed(cfg, True)
    return True
