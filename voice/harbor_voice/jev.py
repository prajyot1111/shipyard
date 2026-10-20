"""The Jev client: one long-lived connection, one budget, and no opinions.

Jev is a text-only classifier that returns typed choices with a confidence and never
writes. V10 puts it behind the judges, and this module is the wire: it asks a question set
and returns typed answers, or it raises. It has no view about what to do when it fails,
because fail-open is a property of the judge and not of the socket
(`voice/harbor_voice/judges.py` owns it).

WHY ONE CONNECTION. c-295's B0 measured a fresh connection at about 850 ms from the Mac
against about 350 ms warm, and V10's budget is 600 ms, so the connection is the difference
between a judge that answers and a judge that is always a counted miss. One
`http.client.HTTPSConnection` is held behind a lock and reused; a connection older than
`JEV_CONNECTION_MAX_AGE` is replaced on purpose rather than discovered dead.

WHAT IT REFUSES TO DO. It will not send a byte before `~/.config/jev/retention` declares
the route his text goes out under, because the direct API has no per-request retention flag
and a declaration in a file is a fact on the machine rather than a memory (c-295, c-300).
It will not read the key from an environment variable or a guessed path: exactly one place
per machine, the same rule `GoogleTTS._key` follows.

WHAT GOES OUT. The `state` string the caller hands it, and the criteria of the questions.
Nothing else, and never audio.
"""

import http.client
import json
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

from harbor_voice import config, loginmark

# The three question kinds Jev answers. A Choice is one of up to 255 named options, a Noul
# is yes or no as a probability, a Score is an ordered few. Only the first two are used by
# V10's judges; Score is named here because the wire accepts it and a later judge may.
CHOICE, NOUL, SCORE = "choice", "noul", "score"


class JevError(RuntimeError):
    """A call that did not produce usable answers, carrying the reason a miss is counted
    under: timeout, error, no-key, no-retention or malformed."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class Reply:
    """One call's answers, with the clock. `answers` is `{name: {"value", "confidence"}}`,
    where a value is a string for a choice and a bool for a noul."""

    def __init__(self, answers: dict, seconds: float, request_id: str = ""):
        self.answers = answers
        self.seconds = seconds
        self.request_id = request_id


def key() -> str:
    """Exactly one place per machine, and never an environment variable.

    The Mac: the login keychain. The box: the copy the unit's `LoadCredential=` made, whose
    directory was popped out of the environment as this package loaded. An empty or missing
    key is an empty string, never an exception: a gateway that raises under systemd is a
    restart loop."""
    if sys.platform == "darwin":
        try:
            done = subprocess.run(
                ["security", "find-generic-password", "-s", config.JEV_KEYCHAIN, "-w"],
                capture_output=True, text=True, timeout=5)
            return done.stdout.strip() if done.returncode == 0 else ""
        except Exception:                                               # noqa: BLE001
            return ""
    if not config.CREDENTIALS_DIRECTORY:
        return ""
    try:
        return (Path(config.CREDENTIALS_DIRECTORY)
                / config.JEV_CREDENTIAL).read_text().strip()
    except OSError:
        return ""


def where_the_key_lives() -> str:
    if sys.platform == "darwin":
        return f"the login keychain under service {config.JEV_KEYCHAIN!r}"
    return (f"the systemd credential {config.JEV_CREDENTIAL!r} "
            f"(`keel voice key set --name jev` writes its source)")


def retention() -> str:
    try:
        return config.JEV_RETENTION_FILE.read_text().strip()
    except OSError:
        return ""


def noul(instructions: str, yes: str, no: str) -> dict:
    return {"type": NOUL, "instructions": instructions,
            "criteria": {"true": yes, "false": no}}


def choice(instructions: str, criteria: dict) -> dict:
    return {"type": CHOICE, "instructions": instructions, "criteria": dict(criteria)}


class Jev:
    """The one client the gateway holds. Thread-safe by one lock around the connection."""

    def __init__(self, host: str | None = None, budget: float | None = None):
        self.host = host or config.JEV_HOST
        self.budget = budget if budget is not None else config.JEV_BUDGET
        self._lock = threading.Lock()
        self._conn: http.client.HTTPSConnection | None = None
        self._opened_at = 0.0
        self._key: str | None = None
        self.calls = 0
        self.misses: dict[str, int] = {}
        self.seconds: list[float] = []

    # -- what it can and cannot do, without making a call ------------------ #

    def ready(self) -> tuple[bool, str]:
        """(can it ask, why not). Read by `/voice/health`, so `keel doctor` and the page's
        settings sheet answer "can the judges reach the key" from one place."""
        route = retention()
        if route not in config.JEV_RETENTION_OK:
            return False, (f"no retention route declared in {config.JEV_RETENTION_FILE} "
                           f"(wanted one of {', '.join(config.JEV_RETENTION_OK)})")
        if not self.key():
            return False, f"no key in {where_the_key_lives()}"
        return True, ""

    def key(self) -> str:
        """Read once and held, like the Google key: a per-call keychain read would cost
        more than the budget it is spent inside."""
        if self._key is None:
            self._key = key()
        return self._key

    def forget_key(self) -> None:
        """After `keel voice key set` restarts the gateway this never runs, but a test and
        a future hot reload both want it."""
        self._key = None

    # -- one call ---------------------------------------------------------- #

    def ask(self, state: str, questions: dict, budget: float | None = None) -> Reply:
        """Ask one question set about one piece of text. Raises `JevError` and nothing else.

        The budget is a wall-clock ceiling on the whole call, connection included, because
        that is what the turn actually feels. A connection that fails mid-request is retried
        once, and only if the budget has time left in it."""
        ceiling = self.budget if budget is None else budget
        deadline = time.monotonic() + ceiling
        ok, why = self.ready()
        if not ok:
            self._miss("no-key" if "no key" in why else "no-retention")
            raise JevError("no-key" if "no key" in why else "no-retention", why)
        body = json.dumps({"state": state, "model": config.JEV_MODEL,
                           "questions": questions}).encode()
        with self._lock:
            for attempt in (1, 2):
                left = deadline - time.monotonic()
                if left <= 0:
                    self._miss("timeout")
                    raise JevError("timeout", f"no time left in the {ceiling:g}s budget")
                try:
                    return self._once(body, questions, left)
                except JevError:
                    raise
                except Exception as exc:                                # noqa: BLE001
                    self._drop()
                    if attempt == 2 or deadline - time.monotonic() <= 0:
                        reason = "timeout" if isinstance(exc, TimeoutError) else "error"
                        self._miss(reason)
                        raise JevError(reason, f"{exc.__class__.__name__}: {exc}") from exc
        raise JevError("error", "unreachable")                          # pragma: no cover

    def _once(self, body: bytes, questions: dict, timeout: float) -> Reply:
        conn = self._connection(timeout)
        started = time.perf_counter()
        conn.request("POST", config.JEV_PATH, body=body, headers={
            "Authorization": f"Bearer {self.key()}",
            "Content-Type": "application/json",
            "Content-Length": str(len(body))})
        response = conn.getresponse()
        raw = response.read()
        seconds = time.perf_counter() - started
        if response.status != 200:
            self._drop()
            self._miss("error")
            if response.status in loginmark.REFUSED:
                loginmark.refused("jev", f"Jev answered HTTP {response.status}")
            raise JevError("error", f"HTTP {response.status}")
        loginmark.works("jev")
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            self._miss("malformed")
            raise JevError("malformed", "the body was not json") from exc
        answers = self._read(doc.get("answers"), questions)
        self.calls += 1
        self.seconds.append(seconds)
        # The id is a header, not a body field (checked live 2026-09-20), and it is the one
        # thing that lets a logged line be quoted back to the vendor.
        return Reply(answers, seconds,
                     str(response.getheader("x-typesafe-request-id") or ""))

    def _read(self, answers, questions: dict) -> dict:
        """Take only what was asked for, typed as it was asked for.

        "Never hallucinates" means the output matches the schema, not that the answer is
        right, and this is a third party's schema. So an answer for a question nobody asked
        is dropped, and a value outside the question's own criteria is a malformed reply
        rather than a verdict."""
        if not isinstance(answers, dict):
            raise JevError("malformed", "no answers object")
        out = {}
        for name, question in questions.items():
            said = answers.get(name)
            if not isinstance(said, dict):
                continue
            reader = self._noul if question["type"] == NOUL else self._choice
            out[name] = reader(name, said, question)
        if not out:
            raise JevError("malformed", "nothing that was asked for came back")
        return out

    @staticmethod
    def _noul(name: str, said: dict, _question: dict) -> dict:
        """A noul is ONE number and no confidence field: `{"type": "noul", "noul": 0.88}`,
        checked against the live API on 2026-09-20.

        The probability IS the answer and the certainty at once, so the value is which side
        of a half it falls on and the confidence is the distance from the fence. Reading a
        `confidence` key here would reject every noul the API sends, and c-295 scored B3 on
        this same reading ("confidence used: noul probability")."""
        raw = said.get("noul")
        if raw is None:
            raw = said.get("value")
        if isinstance(raw, bool):                   # a value with no probability: certain
            return {"value": raw, "confidence": 1.0}
        try:
            probability = float(raw)
        except (TypeError, ValueError):
            raise JevError("malformed", f"{name}: {raw!r} is not a probability") from None
        if not 0.0 <= probability <= 1.0:
            raise JevError("malformed", f"{name}: {probability} is not a probability")
        value = probability >= 0.5
        return {"value": value, "confidence": probability if value else 1.0 - probability}

    @staticmethod
    def _choice(name: str, said: dict, question: dict) -> dict:
        """A choice carries its own confidence, and the value has to be one of the criteria.

        "Never hallucinates" means the output matches the schema, not that the answer is
        right, and this is a third party's schema, so a value outside the criteria is a
        malformed reply rather than a verdict."""
        value = said.get("choice")
        if value is None:
            value = said.get("value")
        if not isinstance(value, str) or value not in question["criteria"]:
            raise JevError("malformed", f"{name}: {value!r} is not one of the criteria")
        try:
            confidence = float(said.get("confidence"))
        except (TypeError, ValueError):
            raise JevError("malformed", f"{name}: no confidence") from None
        return {"value": value, "confidence": max(0.0, min(1.0, confidence))}

    # -- the connection ---------------------------------------------------- #

    def _connection(self, timeout: float) -> http.client.HTTPSConnection:
        aged = time.monotonic() - self._opened_at > config.JEV_CONNECTION_MAX_AGE
        if self._conn is not None and aged:
            self._drop()
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(
                self.host, timeout=timeout, context=ssl.create_default_context())
            self._opened_at = time.monotonic()
        else:
            self._conn.timeout = timeout
            try:
                if self._conn.sock is not None:
                    self._conn.sock.settimeout(timeout)
            except OSError:
                self._drop()
                return self._connection(timeout)
        return self._conn

    def warm(self) -> bool:
        """Open the connection before it is needed, so the first call of a conversation is
        a warm one. Called when a client connects to the socket, never on a timer: a warmer
        that runs while nobody is there costs a connection for nothing."""
        ok, _why = self.ready()
        if not ok:
            return False
        with self._lock:
            try:
                self._connection(self.budget)
                self._conn.connect()                # explicit, so the TLS cost is paid here
                return True
            except Exception:                                           # noqa: BLE001
                self._drop()
                return False

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:                                           # noqa: BLE001
                pass
        self._conn = None
        self._opened_at = 0.0

    def close(self) -> None:
        with self._lock:
            self._drop()

    # -- what it has done -------------------------------------------------- #

    def _miss(self, reason: str) -> None:
        self.misses[reason] = self.misses.get(reason, 0) + 1

    def as_json(self) -> dict:
        ok, why = self.ready()
        ordered = sorted(self.seconds)
        return {"model": config.JEV_MODEL, "budgetSeconds": self.budget,
                "key": "set" if self.key() else "missing",
                "where": where_the_key_lives(),
                "retention": retention() or "undeclared",
                "ready": ok, "why": why,
                "connected": self._conn is not None,
                "calls": self.calls, "misses": dict(self.misses),
                "p50Seconds": round(ordered[len(ordered) // 2], 3) if ordered else None}
