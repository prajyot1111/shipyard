"""Reading a command line as a shell would: the tokeniser under the guard (`guard.py`).

`Reader(text, named).read()` gives the line's simple commands, each a list of words with
the here-documents and here-strings it is fed. It splits on `;`, `|`, `&`, line ends and
brackets, reads quotes, escapes, redirects and here-documents, and lists every nested
command (a `$( )`, a backtick, a `<( )`, one inside `${ }`) beside the ones that hold it.
What the shell fills in at run time (a variable, a substitution, a `$'...'` quote) stands in
a word as `DYN`. An array (`NAME=(...)`) is not a command and `$(( ))` is arithmetic. A
line it cannot split raises `Unreadable`; `named` (the guard's, for the pack it runs for)
says whether such a line, or arithmetic that holds a command, is worth refusing.

Below the reader are the words of one simple command: `unwrap` takes off what only runs
another program (`env`, `sudo`, `xargs`, `time` ...), `alternatives` writes a brace word out
when that is small work, and `could_be` and `bare_after` say what a word may stand for.

Standard library only: it runs on every Bash call a house on a pack with a guard makes.
"""

import fnmatch
import re

DYN = "\x00"            # stands in a word for what the shell fills in at run time
ARRAY = re.compile(r"[A-Za-z_]\w*\+?=")           # the whole word before a `(`: an array, not a subshell
NAME = re.compile(r"[A-Za-z_]\w*|[0-9@*#?$!-]")
NOTHING = re.compile(r"(?!)")                       # a `named` that names nothing


class Unreadable(Exception):
    """A line the reader cannot split as a shell would."""


class Command:
    """One simple command: its words, and the here-documents and here-strings it is fed."""

    def __init__(self):
        self.words: list[str] = []
        self.bodies: list[str] = []


# ----- reading a line -----

class Reader:
    """A command line, read into its simple commands. Every nested command (a `$( )`, a
    backtick, a bracket) is listed beside the ones that hold it."""

    def __init__(self, text: str, named: re.Pattern = NOTHING):
        if DYN in text:
            raise Unreadable("a NUL in the line")
        self.text, self.at, self.out, self.waiting, self.named = text, 0, [], [], named

    def read(self) -> list[Command]:
        self.block(None)
        return self.out

    def block(self, closer: str | None, keep: bool = True) -> None:
        """Commands up to `closer` (a `)` or a backtick), or to the end of the line. With
        `keep` off the words are an array's elements, not a command: only what is nested
        in them (a `$( )`, a backtick) is listed."""
        text, size = self.text, len(self.text)
        current, word, taking = Command(), None, ""      # taking: "drop" a redirect's word, or a "body"

        def end_word():
            nonlocal word, taking
            if word is not None:
                if taking == "body":
                    current.bodies.append(word)
                elif not taking:
                    current.words.append(word)
                taking = ""
            word = None

        def end_command():
            nonlocal current, taking
            end_word()
            taking = ""
            if current.words and keep:
                self.out.append(current)
            current = Command()

        while self.at < size:
            char = text[self.at]
            if closer and char == closer:
                self.at += 1
                break
            if char == "\\":
                following = text[self.at + 1:self.at + 2]
                self.at += 2
                if following != "\n":
                    word = (word or "") + following
            elif char == "'":
                close = text.find("'", self.at + 1)
                if close < 0:
                    raise Unreadable("a quote that never closes")
                word, self.at = (word or "") + text[self.at + 1:close], close + 1
            elif char == '"':
                self.at += 1
                word = (word or "") + self.double()
            elif char == "`":
                self.at += 1
                self.block("`")
                word = (word or "") + DYN
            elif char == "$":
                word = (word or "") + self.dollar()
            elif char in " \t":
                end_word()
                self.at += 1
            elif char == "\n":
                end_command()
                self.at += 1
                self.bodies()
            elif char in ";&|)":
                end_command()
                self.at += 1
            elif char == "(" and word is not None and ARRAY.fullmatch(word):
                self.at += 1
                self.block(")", keep=False)              # `NAME=(...)`: an array
                word += DYN
            elif char == "(" and word is None and not current.words and text.startswith("((", self.at):
                self.at += 2
                self.arithmetic()                        # `(( n << 3 ))`: no command, no here-document
            elif char == "(":
                end_command()
                self.at += 1
                self.block(")")
            elif char in "<>":
                if word is not None and word.isdigit():
                    word = None                          # `2>`: the number names the stream
                end_word()
                if text.startswith("<<<", self.at):
                    self.at, taking = self.at + 3, "body"    # a here-string: what a shell would run
                elif text.startswith("<<", self.at):
                    self.heredoc(current)
                elif text.startswith("(", self.at + 1):
                    self.at += 2
                    self.block(")")
                    word = DYN
                else:
                    self.at += 1
                    while self.at < size and text[self.at] in ">&|":
                        self.at += 1
                    taking = "drop"                      # the next word is where it goes, not a word
            elif char == "#" and word is None:
                end = text.find("\n", self.at)
                self.at = size if end < 0 else end
            else:
                word = (word or "") + char
                self.at += 1
        end_command()

    def double(self) -> str:
        """The rest of a double-quoted stretch, the closing quote taken."""
        text, out = self.text, ""
        while self.at < len(text):
            char = text[self.at]
            if char == '"':
                self.at += 1
                return out
            if char == "\\":
                following = text[self.at + 1:self.at + 2]
                self.at += 2
                if following != "\n":
                    out += following if following in '$`"\\' else "\\" + following
            elif char == "`":
                self.at += 1
                self.block("`")
                out += DYN
            elif char == "$":
                out += self.dollar()
            else:
                out += char
                self.at += 1
        raise Unreadable("a quote that never closes")

    def dollar(self) -> str:
        """What a `$` stands for: a command read in place, or a value known only at run time."""
        text = self.text
        following = text[self.at + 1:self.at + 2]
        if text.startswith("((", self.at + 1):
            self.at += 3
            self.arithmetic()
            return DYN
        if following == "(":
            self.at += 2
            self.block(")")
            return DYN
        if following == "{":
            self.at += 2
            self.braces()
            return DYN
        if following == "'":
            at = self.at + 2                         # `$'...'`: the shell decodes it, so all of it is unknown
            while at < len(text) and text[at] != "'":
                at += 2 if text[at] == "\\" else 1
            if at >= len(text):
                raise Unreadable("a quote that never closes")
            self.at = at + 1
            return DYN
        found = NAME.match(text, self.at + 1)
        self.at = found.end() if found else self.at + 1
        return DYN if found else ("" if following == '"' else "$")

    def braces(self) -> None:
        """The inside of `${ }`, to its closing brace: a `$( )` or a backtick in it is read."""
        text = self.text
        while self.at < len(text):
            char = text[self.at]
            if char == "}":
                self.at += 1
                return
            if char == "\\":
                self.at += 2
            elif char == '"':
                self.at += 1
                self.double()
            elif char == "`":
                self.at += 1
                self.block("`")
            elif char == "$":
                self.dollar()
            else:
                self.at += 1
        raise Unreadable("a brace that never closes")

    def arithmetic(self) -> None:
        """The inside of `(( ))`, both brackets taken: `<<` there is a shift, not a
        here-document. A shell that fails to read it as arithmetic runs it as a command,
        so one that names what the guard reads (`named`) is not read as arithmetic at all."""
        text, depth, start = self.text, 2, self.at
        while self.at < len(text) and depth:
            char = text[self.at]
            if char == "$":
                self.dollar()
            elif char == "`":
                self.at += 1
                self.block("`")
            else:
                depth += {"(": 1, ")": -1}.get(char, 0)
                self.at += 1
        if self.named.search(text[start:self.at]):
            raise Unreadable("a command where arithmetic was expected")

    def heredoc(self, command: Command) -> None:
        """`<<WORD` or `<<-WORD`: its body starts at the next line end."""
        text = self.text
        self.at += 2
        strip = text.startswith("-", self.at)
        self.at += 1 if strip else 0
        while self.at < len(text) and text[self.at] in " \t":
            self.at += 1
        start = self.at
        while self.at < len(text) and text[self.at] not in " \t\n;&|()<>":
            self.at += 1
        raw = text[start:self.at]
        self.waiting.append((re.sub(r"[\"'\\]", "", raw), strip, raw != re.sub(r"[\"'\\]", "", raw), command))

    def bodies(self) -> None:
        """At a line end: take the body of each here-document opened on that line. A body
        under an unquoted word is expanded by the shell, so its `$( )` are read too."""
        text = self.text
        for word, strip, quoted, command in self.waiting:
            lines = []
            while self.at < len(text):
                end = text.find("\n", self.at)
                end = len(text) if end < 0 else end
                line, self.at = text[self.at:end], min(end + 1, len(text))
                if (line.lstrip("\t") if strip else line) == word:
                    break
                lines.append(line)
            body = "\n".join(lines)
            command.bodies.append(body)
            if not quoted:
                self.out += substitutions(body, self.named)
        self.waiting = []


def substitutions(body: str, named: re.Pattern = NOTHING) -> list[Command]:
    """The commands a here-document's body runs when the shell expands it."""
    out, at = [], 0
    while at < len(body):
        if body[at] == "\\":
            at += 2
        elif body.startswith("$(", at) or body[at] == "`":
            inner = Reader(body, named)
            inner.at = at + (2 if body[at] == "$" else 1)
            inner.block(")" if body[at] == "$" else "`")
            out, at = out + inner.out, inner.at
        else:
            at += 1
    return out


# ----- the words of a simple command -----

ASSIGN = re.compile(r"^[A-Za-z_]\w*(\[[^\]]*\])?\+?=")      # `name=`, `name+=`, `name[index]=`
KEYWORDS = frozenset(("{", "}", "!", "if", "then", "elif", "else", "while", "until", "do"))
WRAPPERS = {"env": ("-u", "--unset", "-C", "--chdir"), "command": (), "builtin": (),
            "exec": ("-a",), "nohup": (), "sudo": ("-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"),
            "xargs": ("-n", "-I", "-P", "-L", "-d", "-E", "-s", "-a", "-J", "-R"), "nice": ("-n",),
            "timeout": ("-s", "-k", "--signal", "--kill-after"), "stdbuf": ("-i", "-o", "-e"), "caffeinate": (),
            "time": ("-f", "-o", "--format", "--output")}
SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
PYTHON = re.compile(r"^python[\d.]*$")
PATTERN = "{?*["         # in a command word: the shell expands it into one we cannot see
BRACES = re.compile(r"\{([^{}]*)\}")
# A brace word is written out only when that is small work, decided BEFORE any of it is
# done. A longer word, more brace pairs, or more words than these, is not written out, and
# as a COMMAND WORD it is refused outright: no honest house names a command with a brace
# list that size. The guard runs inside a hook with a clock.
BRACES_MAX = 64          # the most words a brace word may stand for
BRACE_WORD_MAX = 256     # the longest command word that is written out
BRACE_PAIRS_MAX = 16     # the most brace pairs in it


def base(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def alternatives(word: str) -> list[str] | None:
    """Every word a brace word stands for (`{gh,x}` gives `gh` and `x`, nested lists
    included), the word alone when it has no braces, and None when it is too large to
    write out. The size is judged first, in one pass over the word as written: its
    length, its brace pairs, and the words it stands for, which is each pair's own
    commas plus one, multiplied (a nested list counts a little high, never low)."""
    pairs = word.count("{")
    if pairs and (len(word) > BRACE_WORD_MAX or pairs > BRACE_PAIRS_MAX):
        return None
    stands_for, open_lists = 1, []
    for char in word if pairs else "":
        if char == "{":
            open_lists.append(1)
        elif char == "," and open_lists:
            open_lists[-1] += 1
        elif char == "}" and open_lists:
            stands_for *= open_lists.pop()
    if stands_for > BRACES_MAX:
        return None
    done, waiting = [], [word]
    while waiting:
        one = waiting.pop()
        found = BRACES.search(one)
        if found is None:
            done.append(one)
        else:
            waiting += [one[:found.start()] + part + one[found.end():] for part in found.group(1).split(",")]
        if len(done) + len(waiting) > BRACES_MAX:
            return None
    return list(dict.fromkeys(done))        # a nested list writes its outer words out twice


def could_be(tool: str, name: str) -> bool:
    """Whether a base name that is not fully written could be `tool`. Only `?` and `*`
    mean the same in every shell, so only a name made of letters and those two is
    matched and can be ruled out; a bracket, a brace or a part the shell fills in is
    unknown, and unknown could be anything."""
    if any(mark in name for mark in (DYN, "[", "{")):
        return True
    return fnmatch.fnmatchcase(tool, name)


def bare_after(words: list[str], valued: tuple[str, ...]) -> str:
    """The first word that is no flag and no value of one of the `valued` flags."""
    skip = False
    for word in words:
        if not (skip or word.startswith("-")):
            return word
        skip = word in valued
    return ""


def unwrap(words: list[str]) -> tuple[list[str], bool]:
    """The command under leading `NAME=value` words, shell keywords and the programs that
    only run another (`env`, `sudo`, `xargs`, `time` ...); and whether xargs adds its
    arguments. `env -S <string>` comes back as an `eval` of the string."""
    words, flags = unwrapped(words)
    return words, flags is not None


def unwrapped(words: list[str]) -> tuple[list[str], list[str] | None]:
    """`unwrap`, with the flags (and their values) of every xargs it took off, or None when
    no xargs runs the command: where xargs puts its input is read from them (r1.F5)."""
    fed: list[str] | None = None
    while words:
        head = words[0]
        if ASSIGN.match(head) or head in KEYWORDS:
            words = words[1:]
            continue
        if head in ("function", "coproc"):
            named = head == "function" or words[2:3] == ["{"]       # `coproc NAME { ...; }`
            words = words[2:] if named else words[1:]
            continue
        name = base(head)
        if name not in WRAPPERS:
            break
        rest = words[1:]
        if name == "xargs" and fed is None:
            fed = []
        while rest and (rest[0].startswith("-") or (name == "env" and ASSIGN.match(rest[0]))):
            flag = rest.pop(0)
            if flag == "--":
                break
            if name == "env" and (flag.startswith("-S") or flag.startswith("--split-string")):
                said = flag.partition("=")[2] if flag.startswith("--") else flag[2:]
                return ["eval", said or (rest.pop(0) if rest else ""), *rest], fed
            taken = [flag, rest.pop(0)] if flag in WRAPPERS[name] and rest else [flag]
            if name == "xargs":
                fed += taken
        if name == "timeout" and rest:
            rest.pop(0)                              # how long
        words = rest
    return words, fed


def help_at(args: list[str]) -> int | None:
    """Where a tool is asked for its help, which runs nothing, or None: `--help`, or `-h` as
    the last word. Neither counts straight after another flag, whose value it would be
    (`--body --help` posts the words "--help"), and any flag the judge does not know is taken
    as one that may take a value. Moved here from the GitHub guard (r2.F1) so every judge reads
    help the same way."""
    def free(index: int) -> bool:
        return not (index and args[index - 1].startswith("-"))
    found = [index for index, word in enumerate(args) if word == "--help" and free(index)]
    if args[-1:] == ["-h"] and free(len(args) - 1):
        found.append(len(args) - 1)
    return min(found) if found else None


def asks_for_help(args: list[str]) -> bool:
    return help_at(args) is not None
