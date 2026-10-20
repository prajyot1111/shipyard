"""A transport for a host reached through its own command line tool (the GitHub pack's
`gh`): the tool run as a subprocess with a clock, never a prompt, never the verb's own stdin,
and its failure said as ONE sentence.

A pack's own module (`gh_cli.py`) says what is its tool's: the environment that keeps it
quiet, the words that mean "not signed in" or "not found", and the classes those raise.
`sentence` is also how the kit says git's own last word.

A tool's own words are never trusted to leave out a secret: before a failure is said, the
value of every variable of the tool's environment named like one (`*TOKEN`, `*SECRET`,
`*PASSWORD`, `*_KEY`) is taken out of them (`redacted`, r1.F5), so a host that folds the
token it was sent into its error cannot make the kit repeat it.
"""

import json
import os
import re
import subprocess

from keel.packkit.errors import HostError, Missing

SECONDS = 30            # one call's clock; a verb makes a handful, each inside the engine's own
SENTENCE_MAX = 240
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SECRET_NAME = re.compile(r"(?:TOKEN|SECRET|PASSWORD|_KEY)$", re.I)
SECRET_MIN = 8          # a shorter value is not a credential, and taking it out would garble the words
HIDDEN = "[a secret]"


def hidden(text: str, secrets) -> str:
    """`text` with each of `secrets` of `SECRET_MIN` characters or more taken out, as `HIDDEN`."""
    for value in secrets:
        if len(value or "") >= SECRET_MIN:
            text = text.replace(value, HIDDEN)
    return text


def redacted(text: str, env=None) -> str:
    """`text` with the value of every secret-named variable of `env` (this process's when
    None) taken out."""
    env = os.environ if env is None else env
    return hidden(text, [value for name, value in env.items() if SECRET_NAME.search(name)])


def noise(tool: str | None) -> re.Pattern:
    """The lines a tool prints around its message: usage, flags, and "try <tool> ..."."""
    named = rf"|try ['`\"]?{re.escape(tool)} |run ['`\"]?{re.escape(tool)} .* --help" if tool else ""
    return re.compile(rf"^(usage:|flags:|for more information{named})", re.I)


def sentence(text: str, tool: str | None = None) -> str:
    """A tool's (or git's) own message as one plain sentence: the first line that says
    something, without colour, a leading mark or `error:`, cut to a line's length."""
    lines = [ANSI.sub("", line).strip() for line in str(text or "").splitlines()]
    skip = noise(tool)
    kept = [line for line in lines if line and not skip.match(line)]
    marks = r"X |✗ |! |[Ee]rror: |[Ff]atal: " + (rf"|{re.escape(tool)}: " if tool else "") + "|remote: "
    said = re.sub(rf"^(?:{marks})+", "", kept[0] if kept else "")
    said = re.sub(r"\s+", " ", said).strip().rstrip(".")
    if len(said) > SENTENCE_MAX:
        said = said[:SENTENCE_MAX].rsplit(" ", 1)[0] + " [cut]"
    return said or "it gave no reason"


def named(tool: str, args: tuple) -> str:
    """`gh pr view`, `gh api`: the command a failure names, without its arguments."""
    words = []
    for word in args:
        if word.startswith("-") or len(words) == 2:
            break
        words.append(word)
    return f"{tool} " + " ".join(words[:1] if words[:1] == ["api"] else words)


def run(tool: str, *args: str, stdin: str | None = None, timeout: float = SECONDS, cwd=None, env=None,
        host: str = "the host", missing: HostError | None = None, refusal=None) -> str:
    """`<tool> <args>`: its stdout. `stdin` is handed to it when given; without one it is
    given none, so it can never wait on the verb's own. `refusal(said, failed)` may name the
    error a failure is (signed out, not found); `failed` is the plain sentence, and the
    plain `HostError` is raised when it names none."""
    feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        done = subprocess.run([tool, *args], capture_output=True, text=True, timeout=timeout,
                              env=env, cwd=cwd, **feed)
    except FileNotFoundError:
        raise (missing or Missing(f"{tool} is not installed on this machine")) from None
    except subprocess.TimeoutExpired:
        raise HostError(f"{named(tool, args)} gave no answer in {timeout} seconds: {host} may be slow "
                        f"or out of reach, so try again") from None
    except OSError as error:
        raise HostError(f"{tool} could not be run: {error.strerror or error}") from None
    if done.returncode != 0:
        said = redacted(done.stderr.strip() or done.stdout.strip(), env)
        failed = f"{named(tool, args)} failed: {sentence(said, tool)}"
        raise (refusal(said, failed) if refusal else None) or HostError(failed)
    return done.stdout


def parsed(out: str, what: str):
    """One JSON value a call answered."""
    try:
        return json.loads(out or "null")
    except ValueError:
        raise HostError(f"{what} answered something that is not JSON") from None


def rows(out: str, what: str) -> list[dict]:
    """Every row of a paged listing printed as one JSON array per page, one after another."""
    found, decoder, at = [], json.JSONDecoder(), 0
    while at < len(out):
        if out[at].isspace():
            at += 1
            continue
        try:
            value, at = decoder.raw_decode(out, at)
        except ValueError:
            raise HostError(f"{what} answered something that is not JSON") from None
        found += value if isinstance(value, list) else [value]
    return [row for row in found if isinstance(row, dict)]
