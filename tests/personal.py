"""The personal drift check (c-610 S1): no one person's paths or hostnames in the tracked
tree, beside the employer-word check in `make drift`. It needs no install to run.

Two rules, over every file git tracks (plus untracked files that are not ignored), outside
`docs/` (history):

- a home path, `/Users/<name>` or `/home/<name>`, whose name is not a placeholder
  (`PLACEHOLDERS`: the stand-ins tests use, and the product's own Unix users);
- a tailnet hostname, `<host>.ts.net`, that is not an `example` one.

It has no list of files it lets through any more (c-722 landing B: one owner's things left
the tree, and `etc/personal-content.txt` went with them). Names are the public check's
(`tests/publiccheck.py`), which reads them from the install and git; `hits_in` still takes
names, for the copyright line the two checks share (`ALLOWED`). Run as
`python3 -m tests.personal`; it prints each hit and exits 1, or exits 0 silently.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEMPT_DIRS = ("docs/",)
PLACEHOLDERS = {"me", "you", "u", "x", "p", "him", "someone", "elsewhere", "user", "example",
                "ubuntu", "bosun"}
HOME_PATH = re.compile(r"(?<![\w./-])/(?:Users|home)/([A-Za-z][A-Za-z0-9._-]*)")
TAILNET = re.compile(r"\b((?:[A-Za-z0-9-]+\.)+)ts\.net\b")


def tracked(root: Path = ROOT) -> list[str]:
    done = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
                          capture_output=True, text=True, check=True)
    return [line for line in done.stdout.splitlines() if line]


# The one line a name may stand on, each `(path, line form, why)`: the FIRST line of that
# file whose whole text has that form, whatever name it carries, is the allowed line, and
# a name on it is not a name hit. It is chosen before any name is looked for, so a second
# such line, the name in any other form, or any other file is still a hit, and so is
# anything else on the allowed line. `tests/publiccheck.py` reads this same table.
ALLOWED = [
    ("NOTICE", re.compile(r"Copyright \d{4}(?:-\d{4})? [A-Za-z][A-Za-z .'-]*"),
     "the copyright line names its holder, the owner's own choice for the public tree"),
]


def allowed_line(where: str, text: str) -> int | None:
    """The number of the one line of `where` that `ALLOWED` lets carry a name, or None:
    the first line of the form, decided before any name is read."""
    forms = [form for path, form, _ in ALLOWED if path == where]
    return next((number for number, line in enumerate(text.splitlines(), 1)
                 if any(form.fullmatch(line.strip()) for form in forms)), None)


def hits_in(text: str, names: list[str], where: str = "") -> list[str]:
    """What one file's text says that it should not, one entry per rule broken per line.
    `where` is the file's path, for the one line `ALLOWED` names."""
    found, allowed = [], allowed_line(where, text)
    for number, line in enumerate(text.splitlines(), 1):
        lower = line.lower()
        if any(m.group(1) not in PLACEHOLDERS for m in HOME_PATH.finditer(line)):
            found.append(f"{number}: home path: {line.strip()[:160]}")
        if any("example." not in m.group(1).lower() for m in TAILNET.finditer(line)):
            found.append(f"{number}: tailnet host: {line.strip()[:160]}")
        if any(name in lower for name in names) and number != allowed:
            found.append(f"{number}: personal name: {line.strip()[:160]}")
    return found


def check(root: Path = ROOT) -> list[str]:
    out = []
    for rel in tracked(root):
        if rel.startswith(EXEMPT_DIRS):
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue     # a binary, or a file listed but gone from the work tree
        out += [f"{rel}:{hit}" for hit in hits_in(text, [], rel)]
    return out


def main() -> int:
    found = check()
    if found:
        print("drift: one person's home path or tailnet host in the tree:")
        print("\n".join(found))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
