"""The noun guard (c-630, c-628 S2): no ticket or change noun spelled out in core.

What a space calls a ticket and a change comes from its pack's `[terms]`, laid over the
neutral defaults in `keel/terms.py` (the one file in core that may spell them). This check
reads every string literal a user could end up reading, in `app/*.js` (not `app/vendor/`),
`keel/**/*.py` and Keel's own flows, `etc/flows/*.toml` (every string value: a flow says
`{change}`, c-664), and fails on a guarded noun in one:

- story, stories, pull request(s), merge request(s), in any case;
- PR or PRs as a word, and MR or MRs;
- `sc-` followed by a digit (a tracker's ticket ref).

Python is read through `tokenize`, so comments are never literals, docstrings (a string that
is a statement of its own) are skipped, and an f-string's text parts are read. JavaScript is
read by a small lexer that drops comments and regex literals and reads a template literal's
text parts, not its `${...}` code (whose own strings are read as literals).

A literal that is a bare lower-case identifier (`'story'`, `'open-pr'`, `options.pr`,
`tracker_ref`) is a data key, never flagged. The exceptions are `tests/nouns-allow`, one per
line as `path | literal | why`: `literal` is a piece of the flagged literal's text, or `*` for
the whole file. An entry that matches nothing fails too, so the list cannot rot.

Run as `python3 -m tests.nouns` (`make drift` does): it prints each hit and exits 1, or
exits 0 silently.
"""

import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = "tests/nouns-allow"
NOUN = re.compile(r"(?i:\b(?:stor(?:y|ies)|pull[ -]requests?|merge[ -]requests?)\b)"
                  r"|\b(?:PR|MR)s?\b|\bsc-\d")
REF = re.compile(r"\bsc-\d")
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_.\-/]*$")
STRING_TYPES = {tokenize.STRING}
TEXT_PARTS = {getattr(tokenize, name) for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")
              if hasattr(tokenize, name)}
STARTS = {getattr(tokenize, name) for name in ("FSTRING_START", "TSTRING_START")
          if hasattr(tokenize, name)}
ENDS = {getattr(tokenize, name) for name in ("FSTRING_END", "TSTRING_END")
        if hasattr(tokenize, name)}
LINE_STARTS = {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
               tokenize.ENCODING, None}
SKIP = {tokenize.NL, tokenize.COMMENT}


def flagged(text: str) -> bool:
    """Whether a literal's text says a guarded noun, a bare identifier being a data key."""
    if REF.search(text):
        return True
    if IDENTIFIER.match(text):
        return False
    return bool(NOUN.search(text))


# ----- Python -----

def body(token: str) -> str:
    """A STRING token's text: its prefix and quotes dropped, escapes left as written."""
    start = 0
    while token[start] not in "'\"":
        start += 1
    quote = token[start:start + 3] if token[start:start + 3] in ('"""', "'''") else token[start]
    return token[start + len(quote):len(token) - len(quote)]


def python_literals(source: str) -> list[tuple[int, str]]:
    """`(line, text)` for each string literal that is not a docstring; an f-string's text
    parts joined, its `{...}` fields read on their own."""
    tokens = [tok for tok in tokenize.generate_tokens(io.StringIO(source).readline)
              if tok.type not in SKIP]
    out, depth, parts, opened = [], 0, [], []
    for index, tok in enumerate(tokens):
        if tok.type in STARTS:
            opened.append((tok.start[0], parts))
            parts = []
            depth += 1
        elif tok.type in TEXT_PARTS:
            parts.append(tok.string)
        elif tok.type in ENDS:
            line, outer = opened.pop()
            out.append((line, "".join(parts)))
            parts = outer
            depth -= 1
        elif tok.type in STRING_TYPES:
            before = tokens[index - 1].type if index else None
            after = tokens[index + 1].type if index + 1 < len(tokens) else None
            if depth == 0 and before in LINE_STARTS and after in (tokenize.NEWLINE, tokenize.ENDMARKER):
                continue    # a docstring, or a string statement standing as one
            out.append((tok.start[0], body(tok.string)))
    return out


# ----- JavaScript -----

REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
REGEX_WORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new"}


def js_literals(source: str) -> list[tuple[int, str]]:
    """`(line, text)` for each string and template text part; comments and regex literals
    dropped. A template's `${...}` code is lexed again, so its strings are read too."""
    out: list[tuple[int, str]] = []
    lex(source, 0, len(source), out)
    return out


def line_of(source: str, at: int) -> int:
    return source.count("\n", 0, at) + 1


def lex(src: str, i: int, end: int, out: list, closing: bool = False) -> int:
    """Lex `src[i:end]`; with `closing`, stop at the `}` that closes a `${`. Returns where it
    stopped."""
    depth, last = 0, ""
    while i < end:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            nl = src.find("\n", i)
            i = end if nl < 0 else nl
            continue
        if src.startswith("/*", i):
            close = src.find("*/", i + 2)
            i = end if close < 0 else close + 2
            continue
        if ch in "'\"":
            j, text = i + 1, []
            while j < end and src[j] != ch and src[j] != "\n":
                if src[j] == "\\":
                    text.append(src[j:j + 2])
                    j += 2
                    continue
                text.append(src[j])
                j += 1
            out.append((line_of(src, i), "".join(text)))
            i, last = j + 1, "x"
            continue
        if ch == "`":
            i = template(src, i + 1, end, out)
            last = "x"
            continue
        if ch == "/" and (last == "" or last in REGEX_AFTER or last in REGEX_WORDS):
            j, klass = i + 1, False
            while j < end and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    klass = True
                elif src[j] == "]":
                    klass = False
                elif src[j] == "/" and not klass:
                    break
                j += 1
            i = j + 1
            while i < end and (src[i].isalpha()):
                i += 1
            last = "x"
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            if closing and depth == 0:
                return i + 1
            depth -= 1
        if ch.isalnum() or ch in "_$":
            j = i
            while j < end and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            last = src[i:j]
            last = last if last in REGEX_WORDS else "x"
            i = j
            continue
        last = ch if ch not in ")]" else "x"
        i += 1
    return i


def template(src: str, i: int, end: int, out: list) -> int:
    """A template literal from just after its opening backtick: its text parts are one
    literal, and each `${...}` is lexed as code. Returns the index after the closing one."""
    start, text = i, []
    while i < end and src[i] != "`":
        if src[i] == "\\":
            text.append(src[i:i + 2])
            i += 2
            continue
        if src.startswith("${", i):
            text.append(" ")
            i = lex(src, i + 2, end, out, closing=True)
            continue
        text.append(src[i])
        i += 1
    out.append((line_of(src, start), "".join(text)))
    return i + 1


# ----- the check -----

def toml_literals(source: str) -> list[tuple[int, str]]:
    """`(line, text)` for each string value of a TOML document, at any depth; the line is
    where the text first appears (1 when it spans lines). Comments are never values."""
    import tomllib      # noqa: PLC0415 - only a flow file is TOML
    found = []

    def walk(value):
        if isinstance(value, str):
            at = source.find(value)
            found.append((source.count("\n", 0, at) + 1 if at >= 0 else 1, value))
        elif isinstance(value, dict):
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)
    walk(tomllib.loads(source))
    return found


READERS = {".js": js_literals, ".py": python_literals, ".toml": toml_literals}


def sources(root: Path = ROOT) -> list[Path]:
    js = [path for path in sorted((root / "app").glob("*.js"))]
    py = sorted((root / "keel").rglob("*.py"))
    return js + py + sorted((root / "etc" / "flows").glob("*.toml"))


def allowlist(root: Path = ROOT) -> list[tuple[str, str, str]]:
    """`tests/nouns-allow`: `(path, literal, why)` for each line, comments and blanks dropped."""
    entries = []
    path = root / ALLOW
    for raw in path.read_text().splitlines() if path.exists() else ():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(" | ")]
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"{ALLOW}: {raw!r} is not `path | literal | why`")
        entries.append(tuple(parts))
    return entries


def hits(root: Path = ROOT, allow: list | None = None) -> tuple[list[str], list[str]]:
    """`(hits, unused)`: each flagged literal outside the allowlist as `path:line: text`,
    and each allowlist entry that matched nothing."""
    allow = allowlist(root) if allow is None else allow
    used = set()
    found = []
    for path in sources(root):
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        for line, text in READERS[path.suffix](source):
            if not flagged(text):
                continue
            match = next((index for index, (where, piece, _) in enumerate(allow)
                          if where == rel and (piece == "*" or piece in text)), None)
            if match is None:
                found.append(f"{rel}:{line}: {' '.join(text.split())[:160]}")
            else:
                used.add(match)
    unused = [f"{ALLOW}: {where} | {piece} matches nothing"
              for index, (where, piece, _) in enumerate(allow) if index not in used]
    return found, unused


def main() -> int:
    found, unused = hits()
    if found:
        print(f"nouns: {len(found)} ticket or change noun(s) spelled out in core; "
              f"say them through keel/terms.py (K.term, K.say, terms.say):")
        print("\n".join(found))
    if unused:
        print("\n".join(unused))
    return 1 if found or unused else 0


if __name__ == "__main__":
    sys.exit(main())
