"""His tap, told to the house in place: a message into its live session, not a resumed copy
(c-598, approved by him in a-70 as Bosun's wake already is, c-530).

Probed on 2.1.285 (`tests/fixtures/harness/README.md`, c-598): a cross-session message into an
IDLE `claude --bg` session starts a new turn in the same process, so its session id and its
claude.ai link never move, nothing is stopped, and its Stop hook fires at the end of that turn
like any other. A resume (`claude --resume <id> --bg`) mints a new session, a new link, and
ends the old one (`house.retire_superseded`), which is what his Approve, Send back and Ask used
to cost. So `deliver` does this, under the card's lock:

- A house the harness does not list, or lists with no process, has EXITED: the resume path,
  unchanged (`house.resume_card`). So does a card voice is holding: that path owns the hold.
- A house open in his terminal, or behind a drop-in hold, is refused as it always was
  (`house.InTerminal`).
- A house in a turn (`housejobs.working`) raises `house.Busy` unless the caller says
  `when_busy="tell"`: the drain, which has already marked the relay carried, tells it anyway,
  because the probe found a message into a busy session queued and delivered at its next
  input point, never lost. Every other caller HOLDS the tap instead (a relay, `keel/drain.py`).
- Otherwise it is TOLD. The prompt is written to `state/cards/<id>/told/<stamp>.md` and the
  message is a short pointer naming that file (`pointer`), sent by `relay.tell` to the
  session named by the card id: the c-530 probe found the relay's model obeying words inside
  a long message instead of sending them, so only ids and a path go through it. The tell is
  recorded with `record_resume` on the SAME session, which keeps the drain's once-only mark and
  the quiet rule's turn start (`drain.quiet_turn`) as a resume would; briefed news rides with
  the prompt and a pending rotation is cancelled, as `house.resume_card` does.

A tell that certainly did not arrive (a HarnessError: two live sessions of that name, none
reachable) is noted and falls back to the resume path. One that MAY have arrived
(`relay.RelayUnclear`) is noted and never sent again: at most once beats twice.

What a tell does not do: pass flags, so a model changed since the house started takes effect at
its next real resume, not here. It does rewrite the settings file (`prepare`, c-600 review).
"""

from __future__ import annotations

import threading
import traceback
from datetime import datetime

from keel import adapters, briefnews, harness, house, housejobs, relay, views

TOLD_DIR = "told"
REFUSE, TELL = "refuse", "tell"
# What `deliver` does with a house that is not running (`exited`): resume it, as every tap
# does, or (c-718 r1.F4, the stacking step's words) refuse with `NotRunning`, so a step that
# only tells never wakes an exited house, whatever the listing said a moment before.
RESUME = "resume"


class NotRunning(house.InTerminal):
    """The house has no process (or voice holds it): a tell-only caller is refused, nothing
    is resumed. An `InTerminal`, so it is never retried as a held tap."""


# c-607 review: a tell in flight, marked beside its told file under the card's lock before the
# send and removed after it, so a close (`idleclose.close_here`, same lock) never stops a house
# a message is on its way to. A mark older than TELLING_SECONDS is a send that died with its
# process and is not believed: a send takes 7 to 17 s.
TELLING_FILE = "sending"
TELLING_SECONDS = 120


def telling_path(cfg, card_id: str):
    return cfg.card_dir(card_id) / TOLD_DIR / TELLING_FILE


def telling(cfg, card_id: str) -> bool:
    try:
        age = datetime.now().timestamp() - telling_path(cfg, card_id).stat().st_mtime
    except OSError:
        return False
    return age < TELLING_SECONDS


def mark_telling(cfg, card_id: str) -> None:
    path = telling_path(cfg, card_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now().astimezone().isoformat(timespec="seconds") + "\n")


def done_telling(cfg, card_id: str) -> None:
    try:
        telling_path(cfg, card_id).unlink()
    except OSError:
        pass


def pointer(card_id: str, path) -> str:
    """The message itself: ids and a path, never his words (see the module's note). It DESCRIBES
    and never instructs (c-600): the relay model took "Read that file and act on it" as its own
    instruction about one time in three in the sandbox run, reached for a file tool it does not
    have, and sent nothing; this wording went five times out of five."""
    return (f"Keel, for {card_id}: a prompt from the user waits in the file {path}. It takes the place "
            f"of a resume prompt.")


class Twinned(house.InTerminal):
    """Two live sessions carry the card's name, so a message by name cannot reach either
    (SendMessage refuses it). Said on the card with both ids; neither is stopped, and no
    resume mints yet another copy: the stale one is his to stop. An `InTerminal`, so every
    caller refuses or notes it and nobody holds or retries it."""


def deliver(cfg, board, card_id: str, prompt: str | None = None, *, actor: str = "drain",
            force: bool = False, when_busy: str = REFUSE, background: bool = False,
            on_error=None, exited: str = RESUME) -> dict:
    """Tell the card's idle house `prompt`, or resume an exited one. The answer is what a
    resume returns (`session_id`, `bg_id`), with `told` set when it went by message.

    Only the DECISION holds the card's lock (the listing, the checks, the file); the relay
    itself, 7 to 17 s, runs outside it. With `background` it runs on a thread of its own with
    its own board, at most `TELLS_AT_ONCE` together, and the answer says `told: "sending"`:
    his tap returns at once, and the drain joins them at the end of its carry (`join`).
    `on_error(board, error)` runs on that thread when the send fails in a way nothing else
    handles (c-600 review): the drain's batch puts itself back and blocks the card there,
    as its own failure path does when the tell runs in line."""
    with house.card_lock(cfg, card_id):
        card = board.get(card_id)
        space = adapters.space_of(cfg, card)
        rows = house.harness.agents(space.config_dir)
        row = house.harness.find(card.get("session_id") or "", rows)
        if not housejobs.has_process(row) or views.voice_hold(card.get("options")):
            if exited == REFUSE:
                raise NotRunning(f"{card_id}'s house is not running, so it was not told")
            return house.resume_card(cfg, board, card_id, prompt=prompt, force=force, actor=actor)
        house.refuse_if_in_terminal(card, row)
        if housejobs.working(row) and when_busy != TELL:
            raise house.Busy(f"{card_id}'s house is working right now, so it was not told "
                             f"(the harness lists {housejobs.row_said(row)})")
        refuse_twins(board, card, rows, actor)
        plan = dict(prepare(cfg, board, card, row, prompt, actor, force), exited=exited)
        mark_telling(cfg, card_id)      # under the lock: a close decided after this sees it
    if not background:
        try:
            return send(cfg, board, plan)
        finally:
            done_telling(cfg, card_id)
    thread = threading.Thread(target=send_alone, args=(cfg, plan, on_error), daemon=True,
                              name=f"tell-{card_id}")
    with _threads_lock:
        _threads[:] = [alive for alive in _threads if alive.is_alive()]
        _threads.append(thread)
        thread.start()          # under the lock: a join never sees it unstarted
    return dict(plan["result"], told=SENDING, note=SENDING_NOTE)


SENDING = "sending"
SENDING_NOTE = "told to the house in its own session; the message is on its way"
UNCLEAR = "unclear"
UNCLEAR_NOTE = ("the message to the house may not have arrived and is not sent again; if the "
                "house has not answered in a few minutes, tap Resume")
TELLS_AT_ONCE = 4
_slots = threading.BoundedSemaphore(TELLS_AT_ONCE)
_threads: list[threading.Thread] = []
# The drain's pass and its kick thread (c-608) both start tells and join them.
_threads_lock = threading.Lock()


def join(timeout: float | None = None) -> None:
    """Wait for the tells started in the background before this call (the drain, at the
    end of its carry; the pass and the kick thread may both be joining)."""
    with _threads_lock:
        started = list(_threads)
    for thread in started:
        thread.join(timeout)
    with _threads_lock:
        _threads[:] = [alive for alive in _threads if alive.is_alive()]


def refuse_twins(board, card: dict, rows: list[dict], actor: str) -> None:
    """Two live sessions named for the card: say which, plainly, and tell nobody."""
    twins = [row for row in rows if row.get("name") == card["id"] and housejobs.has_process(row)]
    if len(twins) < 2:
        return
    ids = ", ".join(str(row.get("sessionId") or row.get("id")) for row in twins)
    why = (f"{card['id']}'s house was not told: {len(twins)} live sessions are named {card['id']} "
           f"({ids}), so a message by name cannot reach one. Stop the stale one, then tap again")
    board.note(card["id"], why, actor)
    raise Twinned(why)


def prepare(cfg, board, card: dict, row: dict, prompt: str | None, actor: str, force: bool) -> dict:
    """Under the lock: the prompt with its news, written beside the card, and the house's
    settings file rewritten for the stage it is at NOW (c-600 review), as every resume does:
    a house started before its card reached shipping (or before a deploy) has its fence, its
    deny list and its guard hook with the card's id, in the file it reads. A live session may
    reread that file mid-run; a resume certainly does."""
    house.settings_for(cfg, card)
    prompt = prompt or house.RESUME_PROMPT.format(stage=card["stage"])
    card_dir = cfg.card_dir(card["id"])
    news = briefnews.news(card_dir, card, board.events(card["id"]))
    if news:
        prompt = f"{prompt}\n\n{news}"
    path = write_prompt(card_dir, prompt)
    result = {"session_id": card["session_id"], "bg_id": row.get("id") or card["session_id"][:8],
              "told": str(path)}
    return {"card": card, "prompt": prompt, "path": path, "news": news, "actor": actor,
            "force": force, "result": result}


def send_alone(cfg, plan: dict, on_error=None) -> None:
    """A background tell: its own board, one of `TELLS_AT_ONCE` slots, never raises. A failure
    is never silent (c-600 review): its traceback goes to the drain log, the card says so, and
    the caller's `on_error` runs."""
    from keel.board import open_board
    try:
        with _slots:
            try:
                board = open_board(cfg)
                try:
                    send(cfg, board, plan)
                finally:
                    board.close()
            except Exception as error:  # noqa: BLE001 - a thread must not die loudly; it says so instead
                failed_alone(cfg, plan, error, traceback.format_exc(), on_error, open_board)
    finally:
        done_telling(cfg, plan["card"]["id"])


LOG_NAME = "drain.log"


def failed_alone(cfg, plan: dict, error: Exception, trace: str, on_error, open_board) -> None:
    card_id = plan["card"]["id"]
    log(cfg, f"telling {card_id}'s house failed:\n{trace.strip()}")
    try:
        board = open_board(cfg)
        try:
            board.note(card_id, f"telling the house failed ({first_line(error)}); the drain log "
                                f"has the whole of it", plan["actor"])
            if on_error is not None:
                on_error(board, error)
        finally:
            board.close()
    except Exception:  # noqa: BLE001 - the log line above already says it
        log(cfg, f"and {card_id}'s card could not be told so:\n{traceback.format_exc().strip()}")


def log(cfg, text: str) -> None:
    try:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        with open(cfg.logs_dir / LOG_NAME, "a") as handle:
            handle.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} tell: {text}\n")
    except OSError:
        pass


def send(cfg, board, plan: dict) -> dict:
    """Send the pointer. Only `relay.tell` is inside the failure handling: once it has sent,
    nothing after it can turn into a resume, which would be a second delivery."""
    card, card_id, actor = plan["card"], plan["card"]["id"], plan["actor"]
    space = adapters.space_of(cfg, card)
    try:
        relay.tell(card_id, pointer(card_id, plan["path"]), cwd=cfg.card_dir(card_id),
                   env=relay_env(space.config_dir), run=house.harness.run)
    except relay.RelayUnclear as unclear:
        return unclear_tell(board, plan, unclear)
    except (harness.HarnessError, OSError) as error:
        if plan.get("exited") == REFUSE:
            raise NotRunning(f"{card_id}'s house was not told ({first_line(error)}), and is not resumed") from None
        board.note(card_id, f"telling the house in place failed ({first_line(error)}), so it "
                            f"was resumed instead", actor)
        return house.resume(cfg, board, card_id, prompt=plan["prompt"], force=plan["force"], actor=actor)
    return recorded(cfg, board, plan, plan["result"])


def unclear_tell(board, plan: dict, unclear: Exception) -> dict:
    """A tell that may have arrived: NEVER sent again, and never silent. It is recorded as a
    turn start like any tell, so a house that did not take it and sits idle with no Stop is
    the quiet rule's (`drain.idle_stuck`, a resume after `idle_resume_minutes`), and the card
    and the answer say so plainly, with what to do."""
    card_id = plan["card"]["id"]
    board.note(card_id, f"{UNCLEAR_NOTE} ({first_line(unclear)})", plan["actor"])
    result = dict(plan["result"], told=UNCLEAR, note=UNCLEAR_NOTE)
    board.record_resume(card_id, plan["actor"], plan["prompt"], plan["result"])
    return result


def recorded(cfg, board, plan: dict, result: dict) -> dict:
    """After a sent tell: the turn start on the same session, the news, a rotation."""
    card, card_id = plan["card"], plan["card"]["id"]
    board.record_resume(card_id, plan["actor"], plan["prompt"], result)
    if plan["news"]:
        briefnews.refresh(cfg.card_dir(card_id), card)
    if views.rotating(card.get("options")):
        board.set_fields(card_id, {"options": {views.ROTATE_OPTION: None}}, "drain")
        board.note(card_id, "rotation cancelled: the house was told something after it was asked",
                   "drain")
    return result


# The told files a card keeps: each is read once by the house, at its next turn, and the board
# keeps the prompt anyway (the `resume` event), so only the newest few are worth their space.
TOLD_KEEP = 10


def write_prompt(card_dir, prompt: str):
    """`told/<stamp>.md` in the card's own directory, never in a worktree; a second one in the
    same second gets a suffix rather than overwriting the first."""
    folder = card_dir / TOLD_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    path, n = folder / f"{stamp}.md", 1
    while path.exists():
        n += 1
        path = folder / f"{stamp}-{n}.md"
    path.write_text(prompt.rstrip() + "\n")
    for old in sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime)[:-TOLD_KEEP]:
        old.unlink(missing_ok=True)
    return path


def relay_env(config_dir) -> dict:
    """The relay's environment: the house's config dir, so it reaches the house as a peer, and
    nothing of any card's (its one tool is SendMessage)."""
    env = harness.scoped_env(config_dir)
    env.pop("KEEL_CARD", None)
    return env


def first_line(error: BaseException) -> str:
    return (str(error).splitlines() or [type(error).__name__])[0][:300]
