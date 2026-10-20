"""The kick: a relay is carried in seconds, not at the drain's next 30 s pass (c-598).

A tap held for a working house, or Approve outcome's landing, is written to the board as a
`relay` (`keel/drain.py`, "the relays"), and the drain used to find it only on its next pass.
Now whoever writes one kicks the drain that carries it:

- `kb`, right after a verb that wrote a relay (`kb relay`, and `kb approve` or `kb stage`
  with `--relay`), kicks this machine's drain (`after_verb`).
- A house's Stop hook (`bin/keel-turn-end`, `keel/ending.py`) kicks its own machine's drain
  when the card has a relay pending for this host (`after_stop`): that is how a tap held
  while the house was working goes out the moment its turn ends.
- `kb` that just recorded his Deploy (`kb console answer` of a deploy ask with A, which his
  tap and his voice run, or `kb console deploy`) kicks its own drain (`after_deploy`), whose
  kick thread starts the deploy at once (`deploy.kicked`, c-636); whether a drain heard it
  is in the verb's payload (`kick`).

The drain's end is an `Inbox`: a unix datagram socket at `state/drain.sock` that the drain's
`Listener` thread waits on for the drain's whole life (c-608): a datagram wakes it, and it
carries the relays at once (`drain.carry_pass`), even while a pass runs. (Until c-608 the
inbox was read only between passes, so a tap waited out a 75 s pass on the Mac.) There is no signal, so no pid that has been reused can ever be hit,
and nothing is stored: a kick nobody hears is lost, and the pass on its clock is the fallback.
At most once is the board's (`kb carried` before the act), never the kick's.
"""

from __future__ import annotations

import select
import socket
import threading
from pathlib import Path

SOCKET_NAME = "drain.sock"
WORD = b"kick"
# After a kick that left a relay held, how often and how many times the carry is tried again:
# the listing says idle within a second of the Stop that kicked it (probed, c-598).
HOLD_RETRY_SECONDS = 2
HOLD_RETRIES = 5
# How long one wait lasts with nothing held: the most a stop waits for the thread to see it.
LISTEN_SECONDS = 1
# What a kick found, in a log line and in the payload of his Deploy (`after_deploy`).
HEARD, NOBODY = "kicked", "no drain listening"


def socket_path(cfg) -> Path:
    return Path(cfg.state_dir) / SOCKET_NAME


class Inbox:
    """The drain's end: `wait` returns True when at least one kick arrived."""

    def __init__(self, sock: socket.socket, path: Path):
        self.sock, self.path = sock, path

    @classmethod
    def open(cls, cfg) -> Inbox | None:
        """Bind `state/drain.sock`, or None when it cannot be bound: the drain then rests on
        its clock alone and says why (`held_by_another`). A socket a live drain is listening
        on is never taken over, since the kicks would silently go to one of the two; a stale
        one from a drain that died (nothing answers a connect) is replaced."""
        path = socket_path(cfg)
        if held_by_another(path):
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(str(path))
            sock.setblocking(False)
        except OSError:
            return None
        return cls(sock, path)

    def wait(self, seconds: float) -> bool:
        """Wait up to `seconds` for a kick; every kick queued so far is taken at once."""
        try:
            ready, _, _ = select.select([self.sock], [], [], max(0.0, seconds))
        except InterruptedError:
            return False
        if not ready:
            return False
        while True:
            try:
                self.sock.recv(64)
            except OSError:          # BlockingIOError: the queue is empty
                return True

    def close(self) -> None:
        self.sock.close()
        self.path.unlink(missing_ok=True)


class Listener:
    """The kick thread (c-608): waits on the inbox for the drain's whole life and runs
    `carry` (the drain's `carry_pass`, which returns how many relays are still held) on
    every kick. While a kicked relay is still held it carries again every
    `HOLD_RETRY_SECONDS`, `HOLD_RETRIES` times. It never dies: whatever a round raises goes
    to `failed` (the drain's `failed_step`), and it listens on. `stop` ends it."""

    def __init__(self, inbox: Inbox, carry, failed):
        self.inbox, self.carry, self.failed = inbox, carry, failed
        self.stopping = threading.Event()
        self.tries = 0
        self.thread = threading.Thread(target=self.listen, daemon=True, name="kick")

    def start(self) -> Listener:
        self.thread.start()
        return self

    def listen(self) -> None:
        while not self.stopping.is_set():
            try:
                self.round()
            except Exception:  # noqa: BLE001 - the thread is what must not die
                self.tries = 0
                try:
                    self.failed()
                except Exception:  # noqa: BLE001,S110 - even a failed log must not end it
                    pass
                self.stopping.wait(LISTEN_SECONDS)

    def round(self) -> None:
        """One wait, and the carry when it was kicked or a held relay is due again."""
        kicked = self.inbox.wait(HOLD_RETRY_SECONDS if self.tries else LISTEN_SECONDS)
        if self.stopping.is_set() or (not kicked and not self.tries):
            return
        self.tries = HOLD_RETRIES if kicked else self.tries - 1
        if not self.carry():
            self.tries = 0

    def stop(self, timeout: float | None = 60) -> None:
        """End the thread; a carry under way finishes first (up to `timeout`)."""
        self.stopping.set()
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout)


def held_by_another(path: Path) -> bool:
    """True when a live process is bound to the socket at `path` (a connect succeeds)."""
    if not path.exists():
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        probe.connect(str(path))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def local(cfg) -> bool:
    """Kick this machine's drain; False when no drain is listening here."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(WORD, str(socket_path(cfg)))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def host(cfg, name: str | None) -> str:
    """Kick this machine's drain for a relay written for `name`. One word for a log; it never
    raises, because the relay is already on the board and the next pass carries it anyway."""
    if not name:
        return "no host"
    return HEARD if local(cfg) else NOBODY


def relayed_to(args) -> str | None:
    """The host a `kb` verb just wrote a relay for, or None when it wrote none."""
    verb = getattr(args, "verb", None)
    if verb == "relay":
        return getattr(args, "to", None)
    if verb in ("approve", "stage") and getattr(args, "relay", None) is not None:
        return getattr(args, "to", None)
    return None


def deploy_said(args, payload) -> bool:
    """True when the verb just recorded his Deploy (c-636): `kb console deploy`, or `kb
    console answer` of a deploy ask with A, which is how his tap and his voice say it."""
    if getattr(args, "verb", None) != "console" or not isinstance(payload, dict):
        return False
    sub = getattr(args, "sub", None)
    if sub == "deploy":
        return bool(payload.get("answered"))
    from keel import deployask          # noqa: PLC0415 - kb needs it only after an answer
    return sub == "answer" and payload.get("answer") == "A" and deployask.is_deploy(payload)


def after_deploy(cfg, args, payload) -> str | None:
    """`kb`'s kick after it recorded his Deploy (c-636): this machine's drain, which starts
    it. What the kick found is put in the payload (`kick`: `HEARD` or `NOBODY`) before it is
    printed, so his tap never says the deploy starts now when no drain heard it. None when
    the verb did not record his Deploy."""
    if not deploy_said(args, payload):
        return None
    payload["kick"] = HEARD if local(cfg) else NOBODY
    return payload["kick"]


def after_verb(cfg, args) -> str | None:
    """`kb`'s kick after a verb that wrote a relay, or None when it wrote none."""
    name = relayed_to(args)
    return host(cfg, name) if name else None


def pending_here(cfg, card: dict) -> bool:
    """Any pending relay: on one machine a relay under an older host name is carried here
    too (`drain.relays_for`, c-622 r1.F1)."""
    return bool((card.get("derived") or {}).get("relays"))


def after_stop(cfg, card: dict) -> bool:
    """The Stop hook's kick: only when this card has a relay pending."""
    return local(cfg) if pending_here(cfg, card) else False
