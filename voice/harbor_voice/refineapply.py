"""The refine's answer, read strictly and applied by Keel to the captured card only.

WHY THE MODEL NO LONGER TOUCHES THE BOARD (lane D review, round 2). A refine turn used to
hold a shell and run `kb` itself, and a shell reaches far more than `kb`: the deck's HTTP
door, `keel drain`, the board file itself. A capture's words are his, verbatim, so "block
c-312" said into the microphone must stay words. The turn now has no tools at all and
answers with ONE JSON object; this file reads it strictly and makes every write itself,
through `kb` as the `voice` actor, on the captured card and nowhere else.

THE ANSWER, every key required and no other allowed:

    title     str or null   a tidied title, at most TITLE_MAX characters
    topic     str or null   one of the board's own topics for that space
    repo      str or null   one of `kb repos` keys for that space
    note      str or null   one or two lines saying what it is (under the quote)
    question  str or null   a question only he can answer: the card is BLOCKED with it
    choices   list of str   the answers to offer, only with a question, at most CHOICES_MAX
    split     list or null  two or more separate ideas, one title each: each becomes an
                            inbox card `--from` this one, with no parent link
    line      str           one short line for the log, never spoken

A MALFORMED ANSWER CHANGES NOTHING. Anything else (not JSON, a missing or extra key, a
repo or topic that is not a real one, an over-long value) raises `Malformed`, and the
caller logs it and writes nothing. `repo` and `topic` are always set as `assumed`
(the refine is guessing from his words), and a field he STATED is never set at all.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import config

KEYS = ("title", "topic", "repo", "note", "question", "choices", "split", "line")
TITLE_MAX = 100
TOPIC_MAX = 40
NOTE_MAX = 400
QUESTION_MAX = 200
CHOICE_MAX = 60
CHOICES_MAX = 4
SPLIT_MAX = 5
LINE_MAX = 200
SCOPE_ENV = "KEEL_REFINE_CARD"
KB_TIMEOUT = 20.0
FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*)\n```\s*$", re.S)


class Malformed(ValueError):
    """The answer is not the one object the refine was asked for."""


def _text(value, name: str, limit: int, empty_ok: bool = False) -> str:
    if not isinstance(value, str):
        raise Malformed(f"{name} is not a string")
    said = " ".join(value.split())
    if not said and not empty_ok:
        raise Malformed(f"{name} is empty")
    if len(said) > limit:
        raise Malformed(f"{name} is longer than {limit} characters")
    return said


def _optional(value, name: str, limit: int):
    return None if value is None else _text(value, name, limit)


def _one_of(values: list, limit: int) -> dict:
    """A string from `values`, or null; just null when there are none to offer."""
    if not values:
        return {"type": "null"}
    return {"anyOf": [{"type": "string", "enum": list(values), "maxLength": limit},
                      {"type": "null"}]}


def _maybe(limit: int) -> dict:
    return {"type": ["string", "null"], "maxLength": limit}


def schema(repos: list, topics: list) -> dict:
    """The `--json-schema` for this turn (round 3): the exact keys, the caps, and the real
    repo keys and topics as enums, built per call. `choices` only with a question is not
    in it (kept to the features the probe proved); `parse` checks that, and everything
    here again, as the second check."""
    text_list = {"type": "string", "minLength": 1}
    return {"type": "object", "additionalProperties": False, "required": list(KEYS),
            "properties": {
                "title": _maybe(TITLE_MAX), "topic": _one_of(topics, TOPIC_MAX),
                "repo": _one_of(repos, TOPIC_MAX), "note": _maybe(NOTE_MAX),
                "question": _maybe(QUESTION_MAX),
                "choices": {"type": "array", "maxItems": CHOICES_MAX,
                            "items": {**text_list, "maxLength": CHOICE_MAX}},
                "split": {"anyOf": [{"type": "array", "minItems": 2, "maxItems": SPLIT_MAX,
                                     "items": {**text_list, "maxLength": TITLE_MAX}},
                                    {"type": "null"}]},
                "line": {**text_list, "maxLength": LINE_MAX}}}


def parse(text, repos: list, topics: list) -> dict:
    """The answer as a checked dict, or `Malformed`. `text` is the structured output
    itself (a dict) or its JSON; None (no structured output at all) is malformed."""
    if text is None:
        raise Malformed("the turn carried no structured output")
    if isinstance(text, dict):
        text = json.dumps(text)
    raw = str(text or "").strip()
    fenced = FENCE.match(raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise Malformed(f"not JSON: {exc}") from None
    if not isinstance(doc, dict):
        raise Malformed("not one JSON object")
    if set(doc) != set(KEYS):
        raise Malformed(f"keys {sorted(doc)}, expected {sorted(KEYS)}")
    got = {"title": _optional(doc["title"], "title", TITLE_MAX),
           "topic": _optional(doc["topic"], "topic", TOPIC_MAX),
           "repo": _optional(doc["repo"], "repo", TOPIC_MAX),
           "note": _optional(doc["note"], "note", NOTE_MAX),
           "question": _optional(doc["question"], "question", QUESTION_MAX),
           "line": _text(doc["line"], "line", LINE_MAX)}
    if got["repo"] is not None and got["repo"] not in repos:
        raise Malformed(f"repo {got['repo']!r} is not one of {repos}")
    if got["topic"] is not None and got["topic"] not in topics:
        raise Malformed(f"topic {got['topic']!r} is not one of {topics}")
    choices = doc["choices"]
    if not isinstance(choices, list) or len(choices) > CHOICES_MAX:
        raise Malformed(f"choices is not a list of at most {CHOICES_MAX}")
    if choices and got["question"] is None:
        raise Malformed("choices without a question")
    got["choices"] = [_text(one, "a choice", CHOICE_MAX) for one in choices]
    split = doc["split"]
    if split is not None:
        if not isinstance(split, list) or not 2 <= len(split) <= SPLIT_MAX:
            raise Malformed(f"split is not a list of 2 to {SPLIT_MAX} titles")
        split = [_text(one, "a split title", TITLE_MAX) for one in split]
    got["split"] = split
    return got


def kb(*argv: str, card: str = ""):
    """One `kb` call as JSON, with the refine's scope in its environment (the second belt,
    `keel/refinescope.py`). Raises with kb's own words when it refuses."""
    env = {**os.environ, "KEEL_HOME": str(config.KEEL_HOME), SCOPE_ENV: card}
    done = subprocess.run([str(config.KB), *argv, "--json"], capture_output=True, text=True,
                          timeout=KB_TIMEOUT, env=env)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"kb {argv[0]} failed")
    return json.loads(done.stdout or "null")


def repo_keys(space: str, kb=None) -> list:
    """The repo keys a card in this space may name, read by Keel, never by the model."""
    kb = kb or globals()["kb"]
    try:
        return [str(row.get("repo")) for row in kb("repos", "--space", space) or []]
    except Exception:                                                   # noqa: BLE001
        return []


def stated(card: str, kb=None) -> set:
    """The tracked fields he stated on this card: a refine never sets those."""
    kb = kb or globals()["kb"]
    try:
        shown = kb("show", card, card=card) or {}
    except Exception:                                                   # noqa: BLE001
        # UNREADABLE MEANS NOTHING IS SET: every tracked field is treated as his.
        return {"repo", "topic", "model", "autonomy"}
    tags = ((shown.get("options") or {}).get("provenance") or {})
    return {name for name, tag in tags.items() if tag == "stated"}


def apply(answer: dict, card: str, space: str, kb=None) -> list:
    """Write the answer onto `card` through `kb` as voice. Returns what was done, as
    lines for the log. A write kb refuses is logged and the rest still applied."""
    kb = kb or globals()["kb"]
    done: list = []
    said = ["--actor", "voice"]

    def write(*argv):
        try:
            result = kb(*said, *argv, card=card)
            done.append(" ".join(argv[:2]))
            return result
        except Exception as exc:                                        # noqa: BLE001
            done.append(f"refused {argv[0]}: {exc}")
            return None
    mine = stated(card, kb=kb)
    if answer["title"]:
        write("set", card, f"title={answer['title']}")
    guesses = [name for name in ("repo", "topic") if answer[name] and name not in mine]
    if guesses:
        write("set", card, *[f"{name}={answer[name]}" for name in guesses],
              "--assumed", ",".join(guesses))
    if answer["note"]:
        write("note", card, answer["note"])
    for title in answer["split"] or []:
        child = write("create", "--space", space, "--title", title, "--from", card,
                      "--brief", f"Split out of {card} by its refine.",
                      "--option", "source=voice")
        if child and child.get("id"):
            write("note", card, f"split out as {child['id']}: {title}")
    if answer["question"]:
        write("block", card, answer["question"])
        if answer["choices"]:
            write("set", card, "options.choices=" + json.dumps(answer["choices"]))
    write("set", card, "options.capture=refined")
    return done
