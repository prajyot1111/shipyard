"""The deck's views and scripts, from one manifest: `app/views.json` (c-634).

A deck view used to be six hand-kept lists that had to agree: `VIEWS` and `DOCK` in
`app/ui.core.js`, the body's switch in `app/ui.js`, the script tags in `app/index.html`,
`APP_FILES` in `keel/serve.py`, and the service worker's `SHELL` with a `CACHE` name bumped
by hand. Now there is one file, and everything else is drawn from it:

- `scripts` is the deck page's load order. The served page gets one script tag per entry
  where `index.html` says `<!-- keel:views -->`, with the manifest inline as
  `window.KEEL_VIEWS` ahead of them, which is what `ui.core.js` reads its views from.
- `views` is one row per view: `key`, `name`, `icon`, `render` (the `K.<render>` that draws
  its body, called with `arg`), `script` (the file that defines it), `needs` (the readiness
  rows it depends on, c-631), `dock` (true, or `when-ready` to wait for its needs), `nav`
  (false keeps a row off the rail: More), and `rail` (`until-finished`: Start, c-632;
  `when-declared`: Reviews, shown only while some space can use what it needs, c-730).
- The service worker's `var DECK = ...;` line is filled with the scripts and a short hash
  of the manifest, so its cache name changes whenever the manifest does.

`load` reads the file once per mtime. `check` says what is wrong with one, and the scaffold
(`keel new view`) and the suite both hold the shipped manifest to it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from keel import readiness

MANIFEST = "views.json"
INDEX_MARK = "<!-- keel:views -->"
WORKER_LINE = re.compile(r"^var DECK = .*;$", re.M)
KEY = re.compile(r"^[a-z][a-z0-9]*$")
# Routes the deck's core answers itself, so no view may take the key (c-628 review r2.F1):
# `plan` (a plan page, which redraws only on its card's events), `console` (reloaded on every
# tick) and `prs` (a retired link, redirected to Cards). tests/test_deckviews.py holds this to
# every route literal app/*.js branches on that is not a manifest row.
RESERVED = ("plan", "console", "prs")
SCRIPT = re.compile(r"^ui(?:\.[a-z][a-z0-9]*)?\.js$")
RENDER = re.compile(r"^view[A-Z][A-Za-z0-9]*$")
ROW_KEYS = {"key", "name", "icon", "render", "arg", "script", "needs", "dock", "nav", "rail"}
REQUIRED = ("key", "name", "icon", "render", "script")
# The readiness rows a view may need (keel/readiness.py, c-629): a space's and the install's.
NEEDS = frozenset(readiness.STEPS)
DOCKS = (True, False, "when-ready")
# `until-finished`: Start, off the rail once the first run is finished (c-632).
# `when-declared` (c-730): Reviews, shown only while some space declares every capability it
# needs (each readiness row's `declared`), so a fresh install with nothing that could fill it
# does not list it.
RAILS = ("until-finished", "when-declared")
# The files the server fills from the manifest rather than sending as they are; the shell
# (`/`, `index.html`) is `Handler.reply_shell`'s, since it also carries the page's cookie.
FILLED = {"/sw.js": "sw.js"}

_held: dict[Path, tuple[int, dict]] = {}


class ManifestError(ValueError):
    """The manifest cannot be read, or says something the deck cannot draw."""


def path_of(app_dir: Path) -> Path:
    return Path(app_dir) / MANIFEST


def load(app_dir: Path) -> dict:
    """The manifest, read once per mtime and checked; a bad one raises ManifestError."""
    path = path_of(app_dir)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError as error:
        raise ManifestError(f"{path}: {error.strerror}") from error
    held = _held.get(path)
    if held and held[0] == stamp:
        return held[1]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ManifestError(f"{path}: {error}") from error
    problems = check(manifest, app_dir)
    if problems:
        raise ManifestError(f"{path}: " + "; ".join(problems))
    _held[path] = (stamp, manifest)
    return manifest


def check(manifest, app_dir: Path | None = None) -> list[str]:
    """What is wrong with a manifest, one sentence each; empty when nothing is."""
    if not isinstance(manifest, dict) or set(manifest) != {"scripts", "views"}:
        return ["it is an object of exactly scripts and views"]
    scripts, views = manifest["scripts"], manifest["views"]
    out = []
    if not isinstance(scripts, list) or not all(isinstance(s, str) and SCRIPT.match(s) for s in scripts):
        return ["scripts is a list of ui.<name>.js file names"]
    if len(set(scripts)) != len(scripts):
        out.append("a script is listed twice")
    if scripts[-1:] != ["ui.js"] or scripts[:1] != ["ui.core.js"]:
        out.append("scripts start with ui.core.js and end with ui.js, the boot")
    if app_dir is not None:
        out += [f"{name} is listed and is not in app/" for name in scripts
                if not (Path(app_dir) / name).is_file()]
    if not isinstance(views, list) or not views:
        return out + ["views is a list of rows"]
    seen = set()
    for row in views:
        out += row_problems(row, scripts, seen)
    out += render_problems(views, scripts, app_dir)
    return out


def render_problems(views: list, scripts: list[str], app_dir: Path | None) -> list[str]:
    """Each row's `render` is its own: no other row names it, and no script that loads before
    the row's own assigns it, since `K[render]` is called and a later assignment replaces an
    earlier one (a view keyed `of` would have replaced `K.viewOf`, which draws every view)."""
    out, owner = [], {}
    rows = [row for row in views if isinstance(row, dict) and isinstance(row.get("render"), str)]
    for row in rows:
        render = row["render"]
        if render in owner:
            out.append(f"view {row.get('key')}: render {render} is view {owner[render]}'s too")
        owner.setdefault(render, row.get("key"))
    if app_dir is None:
        return out
    for row in rows:
        if row.get("script") not in scripts:
            continue
        earlier = [name for name in scripts[:scripts.index(row["script"])]
                   if assigns(Path(app_dir) / name, row["render"])]
        if earlier:
            out.append(f"view {row.get('key')}: K.{row['render']} is already defined in "
                       f"app/{earlier[0]}, which loads first")
    return out


def assigns(path: Path, name: str) -> bool:
    """The script assigns `K.<name>`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(rf"\bK\.{re.escape(name)}\s*=(?!=)", text) is not None


def row_problems(row, scripts: list[str], seen: set) -> list[str]:
    if not isinstance(row, dict):
        return ["a view row is an object"]
    key = row.get("key")
    name = f"view {key}" if isinstance(key, str) else "a view row"
    out = [f"{name} has no {part}" for part in REQUIRED if not row.get(part)]
    out += [f"{name}: {extra} is not a view key" for extra in sorted(set(row) - ROW_KEYS)]
    if isinstance(key, str):
        if not KEY.match(key):
            out.append(f"{name}: the key is lower case letters and digits")
        if key in RESERVED:
            out.append(f"{name}: {key} is a route the deck answers itself")
        if key in seen:
            out.append(f"{name} is listed twice")
        seen.add(key)
    if row.get("render") and not RENDER.match(str(row["render"])):
        out.append(f"{name}: render names a K.view<Name> function")
    if row.get("script") and row["script"] not in scripts:
        out.append(f"{name}: its script {row['script']} is not in scripts")
    needs = row.get("needs", [])
    if not isinstance(needs, list) or any(n not in NEEDS for n in needs):
        out.append(f"{name}: needs lists readiness rows ({', '.join(sorted(NEEDS))})")
    if row.get("dock", False) not in DOCKS:
        out.append(f"{name}: dock is true, false or when-ready")
    if row.get("nav", True) not in (True, False):
        out.append(f"{name}: nav is true or false")
    if "rail" in row and row["rail"] not in RAILS:
        out.append(f"{name}: rail is until-finished or when-declared")
    return out


def dump(manifest: dict) -> str:
    """The manifest as the file is laid out: the scripts wrapped, one view per line. The
    scaffold writes through this, so an added view is a one-line diff."""
    names = [json.dumps(name) for name in manifest["scripts"]]
    lines, line = [], "   "
    for index, name in enumerate(names):
        piece = f" {name}" + ("," if index < len(names) - 1 else "")
        if len(line) + len(piece) > 100:
            lines.append(line)
            line = "   "
        line += piece
    lines.append(line)
    rows = [f"    {{ {', '.join(f'{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}' for k, v in row.items())} }}"
            for row in manifest["views"]]
    return ("{\n  \"scripts\": [\n" + "\n".join(lines) + "\n  ],\n  \"views\": [\n"
            + ",\n".join(rows) + "\n  ]\n}\n")


def digest(manifest: dict) -> str:
    """A short hash of the manifest: the service worker's cache name carries it."""
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def inline(manifest: dict) -> str:
    """The manifest as a script's JSON, with nothing in it that could close the tag."""
    return json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")


def index_html(template: str, manifest: dict) -> str:
    """`index.html` with its mark filled: the manifest inline, then one tag per script."""
    if INDEX_MARK not in template:
        raise ManifestError(f"index.html has no {INDEX_MARK}")
    tags = [f"<script>window.KEEL_VIEWS = {inline(manifest)};</script>"]
    tags += [f'<script src="/{name}"></script>' for name in manifest["scripts"]]
    return template.replace(INDEX_MARK, "\n".join(tags), 1)


def worker_js(template: str, manifest: dict) -> str:
    """`sw.js` with its `var DECK = ...;` line filled: the scripts and the manifest's hash."""
    if not WORKER_LINE.search(template):
        raise ManifestError("sw.js has no `var DECK = ...;` line")
    deck = json.dumps({"scripts": ["/" + name for name in manifest["scripts"]],
                       "hash": digest(manifest)})
    return WORKER_LINE.sub(lambda _: f"var DECK = {deck};", template, count=1)


def rendered(app_dir: Path, name: str) -> str:
    """`index.html` or `sw.js` as the server sends it."""
    app_dir = Path(app_dir)
    template = (app_dir / name).read_text(encoding="utf-8")
    manifest = load(app_dir)
    return index_html(template, manifest) if name == "index.html" else worker_js(template, manifest)


def filled_tag(app_dir: Path, name: str, zipped: bool) -> str:
    """A filled file's ETag: the file's and the manifest's mtime and size, and the encoding,
    so a change to either is a new tag."""
    parts = []
    for path in (Path(app_dir) / name, path_of(app_dir)):
        stat = path.stat()
        parts.append(f"{stat.st_mtime_ns:x}-{stat.st_size:x}")
    return f'"{"-".join(parts)}{"-gz" if zipped else ""}"'


def served(app_dir: Path) -> dict[str, str]:
    """`{"/<script>": "<script>"}` for every deck script, the server's file list's share."""
    try:
        return {"/" + name: name for name in load(app_dir)["scripts"]}
    except ManifestError:
        return {}
