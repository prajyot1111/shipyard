"""`keel new pack|segment|view <name>`: one command per kind of extension (c-634, c-628 S6).

Each kind refuses a name that is not a plain identifier or is already taken, writes a
working starting point from one template, CHECKS what it wrote with the same check that
holds the shipped ones, and prints the files and what to do next. A starting point that
fails its check is removed again, so nothing half-made is left behind.

- **pack**: a copy of `packs/sandbox` (its executables keep their modes) with its name,
  description, header and first-run step renamed, the pack name in its example config, and
  the sandbox's `demo_only` mark left out (c-688), so Setup offers the copy.
  The sandbox's `[capabilities]`, `[terms]` and `[[setup]]` come along with the verbs and
  files behind them, so `packs.load` takes the copy first time. With `--kit` (c-735) it is
  a code host pack on the pack kit instead (`keel/scaffoldkit.py`).
- **segment**: `segment.md`, a stdlib `fetch.py` that writes `summary.json` with one tile
  and never touches the network, and the `test_fetch.py` that runs it in a temporary copy;
  then `segmentspec.check`.
- **view**: a row in `app/views.json` and `app/ui.<key>.js` with a `K.view<Key>` that draws
  one panel, its script placed before `ui.js`; then `deckviews.check`. Nothing else in the
  deck is edited: the page, the worker and the served files are drawn from the manifest.

Where it writes (decision `target`): the checkout it runs from, so an extension goes
through a card, review and the pipeline like any code. `--install` puts a pack or a segment
in the install's own `packs/` or `segments_dir`, which already win over the checkout's; a
view is code and is only ever the checkout's. `--into DIR` puts a pack in a packs folder
the caller names (c-678): the builder's clone of packs, where a connection it drafts for
the user goes through its own card. It files no card: whoever runs it is already
inside one. The rules are the Atlas page, Extending Shipyard (`docs/atlas/63-extending.md`).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from keel import deckviews, packs, scaffoldkit, segmentspec

CODE = Path(__file__).resolve().parent.parent
TEMPLATE_PACK = "sandbox"
ATLAS = "Read Extending Shipyard (docs/atlas/63-extending.md, the deck's Atlas) for the rules."
SEGMENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VIEW_ICON = "◇"


class Refused(Exception):
    """The scaffold will not write: a bad or taken name, or a starting point that fails."""


# ----- pack -----

PACK_HEADER = """# The {name} pack, made by `keel new pack {name}` (c-634) from the sandbox. As made, its
# verbs are the sandbox's: they serve a space that names this pack, and only inside a
# sandbox (demo/sandbox), refusing on any other install, since their tracker and code host
# are JSON files on disk. Replace the executables' insides with your tracker's and code
# host's, keeping each claim in [capabilities] true only while its verbs are here.
# docs/atlas/62-packs.md is the format; docs/atlas/63-extending.md the rules.
"""


def new_pack(name: str, root: Path = CODE, into: Path | None = None, kit: bool = False) -> list[Path]:
    """Copy the sandbox to `<into or root/packs>/<name>`, renamed, and load it; with `kit`
    (c-735), write a code host pack on the pack kit there instead (`keel/scaffoldkit.py`)."""
    if not packs.NAME.match(name or ""):
        raise Refused(f"{name!r} is not a pack name: lower case letters, digits, - and _")
    if kit and name[0].isdigit():
        raise Refused(f"{name} cannot start a pack on the kit: its modules are named for it, and a Python "
                      f"module cannot start with a digit")
    target = Path(into) if into else Path(root) / packs.PACKS
    taken = [r / name for r in [target, *packs.roots(root)] if (r / name).exists()]
    if taken:
        raise Refused(f"pack {name} is taken: {taken[0]}")
    source = Path(root) / packs.PACKS / TEMPLATE_PACK
    dest = target / name
    try:
        if kit:
            scaffoldkit.write(dest, name)
        else:
            shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            rename_pack(dest, name)
        packs.load(dest)
    except (OSError, ValueError, packs.PackError) as error:
        shutil.rmtree(dest, ignore_errors=True)
        raise Refused(f"the new pack does not load, so it was removed: {error}") from None
    return sorted(path for path in dest.rglob("*") if path.is_file())


def rename_pack(dest: Path, name: str) -> None:
    """The sandbox's name, description, header and step title, its step's first words, and its
    example config's pack."""
    spec = dest / packs.PACK_FILE
    text = spec.read_text(encoding="utf-8")
    body = text[text.index("\nname = ") + 1:]
    body = re.sub(r'^name = ".*"$', f'name = "{name}"', body, count=1, flags=re.M)
    body = re.sub(r'^description = ".*"$', f'description = "The {name} pack: say here what it '
                  f'integrates."', body, count=1, flags=re.M)
    body = re.sub(r'^title = "Try the sandbox"$', f'title = "Try the {name} pack"', body,
                  count=1, flags=re.M)
    # the copy is the user's own pack, to be offered like any other: the sandbox's demo-only
    # mark (c-688) and the comment over it stay behind
    body = re.sub(r"^(?:#.*\n)*demo_only = true\n", "", body, count=1, flags=re.M)
    spec.write_text(PACK_HEADER.format(name=name) + body, encoding="utf-8")
    step = dest / "setup" / "try.md"
    if step.is_file():
        said = step.read_text(encoding="utf-8")
        step.write_text(said.replace("The sandbox needs", f"The {name} pack, as made, needs", 1),
                        encoding="utf-8")
    example = dest / "config.example.toml"
    if example.is_file():
        said = example.read_text(encoding="utf-8").replace(f'pack = "{TEMPLATE_PACK}"', f'pack = "{name}"')
        # The demo's contract and pipeline are the sandbox's: its Publish runs the sandbox's
        # own `pr` (c-628 review r2.F4). A space on the copy writes its own.
        said = re.sub(r'^(contract|pipeline) = "demo/sandbox/.*"$',
                      lambda m: f"# {m.group(1)} = \"<your space's own; the sandbox's is the demo's>\"",
                      said, flags=re.M)
        example.write_text(said, encoding="utf-8")


# ----- segment -----

SEGMENT_MD = """---
name: {name}
space: {space}
cadence: hourly
---

# {name}

What this segment looks after, in a sentence or two. Made by `keel new segment {name}`
(c-634). The frontmatter above is checked by `keel/segmentspec.py`; segments/README.md is
the contract for the inside of a segment, and docs/atlas/63-extending.md the rules.
"""

FETCH_PY = '''#!/usr/bin/env python3
"""{name}'s fetcher: run by the fetch role on its cadence, with this directory as its cwd.

It writes summary.json, the tiles the deck shows for this segment, and never touches the
network: a fetcher reads files and writes files (segments/README.md, "Two rules").
"""

import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def summary() -> dict:
    """The tiles: the first is the big one. Replace the count with what this segment reads."""
    count = len(list((HERE / "data").glob("*"))) if (HERE / "data").is_dir() else 0
    return {{"tiles": [{{"label": "items", "value": count}}],
            "notes": ["made by keel new segment; nothing is fetched yet"],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}}


def main() -> int:
    (HERE / "summary.json").write_text(json.dumps(summary(), indent=2) + "\\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST_FETCH_PY = '''#!/usr/bin/env python3
"""{name}'s own test: run fetch.py in a temporary copy and read what it wrote.

Run it as `python3 segments/{name}/test_fetch.py`.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class FetchTest(unittest.TestCase):
    def test_it_writes_a_summary_with_a_tile_and_when(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "{name}"
            shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns("data", "summary.json"))
            done = subprocess.run([sys.executable, str(copy / "fetch.py")], cwd=copy,
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            said = json.loads((copy / "summary.json").read_text())
            self.assertTrue(said["tiles"])
            self.assertTrue(all({{"label", "value"}} <= set(tile) for tile in said["tiles"]))
            self.assertTrue(said["generated_at"])


if __name__ == "__main__":
    unittest.main()
'''


def new_segment(name: str, space: str, spaces, root: Path = CODE, into: Path | None = None,
                roots=()) -> list[Path]:
    """Write `<into or root/segments>/<name>` and check it against the config's spaces."""
    if not SEGMENT_NAME.match(name or ""):
        raise Refused(f"{name!r} is not a segment name: lower case letters, digits and -")
    target = Path(into) if into else Path(root) / "segments"
    taken = [r / name for r in [target, *roots] if (r / name).exists()]
    if taken:
        raise Refused(f"segment {name} is taken: {taken[0]}")
    if space not in set(spaces):
        raise Refused(f"space {space} is not configured (the spaces: {', '.join(spaces) or 'none'})")
    dest = target / name
    dest.mkdir(parents=True)
    written = [dest / "segment.md", dest / "fetch.py", dest / "test_fetch.py"]
    for path, text in zip(written, (SEGMENT_MD, FETCH_PY, TEST_FETCH_PY)):
        path.write_text(text.format(name=name, space=space), encoding="utf-8")
    for path in written[1:]:
        path.chmod(0o755)
    problems = segmentspec.check(dest, spaces)
    if problems:
        shutil.rmtree(dest, ignore_errors=True)
        raise Refused("the new segment fails its check, so it was removed: " + "; ".join(problems))
    return written


# ----- view -----

VIEW_JS = """/* The {title} view, made by `keel new view {key}` (c-634): one panel to start from.
 *
 * Its row in app/views.json is everything the deck needs: the rail lists it, `?view={key}`
 * opens it, and app/ui.js draws its body with `K.{render}()`. The phone reaches it under
 * More (below). Add the readiness rows it
 * depends on to the row's `needs` and the page opens with the panel saying what is missing
 * (c-631). docs/atlas/63-extending.md has the rules, and docs/atlas/40-deck.md the deck's
 * helpers (`K.el`, the morph, `data-key`). */
(function (K) {{
  'use strict';

  var el = K.el;

  function {render}() {{
    return el('section', {{ class: 'panel', 'data-key': '{key}' }},
      el('div', {{ class: 'panel-head' }}, el('span', {{ class: 'label', text: '{title}' }})),
      el('div', {{ class: 'panel-body' }},
        el('div', {{ class: 'empty', text: 'Nothing here yet: draw this view in app/ui.{key}.js.' }})));
  }}

  K.{render} = {render};

  /* The phone reaches it under More, as it does Setup and the Atlas: the dock has no room. */
  var baseMore = K.viewMore;
  K.viewMore = function () {{
    var out = baseMore ? baseMore() : [];
    if (!Array.isArray(out)) out = [out];
    out.splice(Math.max(out.length - 1, 0), 0, el('section', {{ class: 'panel', 'data-key': '{key}-entry' }},
      el('div', {{ class: 'panel-body' }},
        el('button', {{ class: 'row', onclick: function () {{ K.go('{key}'); }} }},
          el('div', {{ class: 'row-head' }}, el('span', {{ class: 't', text: '{title}' }}))))));
    return out;
  }};
}})(window.Keel);
"""


def new_view(key: str, root: Path = CODE, name: str | None = None, icon: str = VIEW_ICON) -> list[Path]:
    """A manifest row and `app/ui.<key>.js`, checked; the manifest is put back on a failure."""
    app = Path(root) / "app"
    if not deckviews.KEY.match(key or ""):
        raise Refused(f"{key!r} is not a view key: lower case letters and digits, a letter first")
    manifest_path = deckviews.path_of(app)
    try:
        before = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(before)
        rows, scripts = list(manifest["views"]), list(manifest["scripts"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Refused(f"app/{deckviews.MANIFEST} does not read: {error}") from None
    if key in deckviews.RESERVED:
        raise Refused(f"view {key} is a route the deck answers itself; pick another key")
    script = f"ui.{key}.js"
    if any(isinstance(row, dict) and row.get("key") == key for row in rows) or (app / script).exists():
        raise Refused(f"view {key} is taken: app/views.json or app/{script} has it")
    render = "view" + key[:1].upper() + key[1:]
    clash = [f"view {row.get('key')}'s render" for row in rows
             if isinstance(row, dict) and row.get("render") == render]
    clash += [f"app/{name}" for name in scripts if deckviews.assigns(app / name, render)]
    if clash:
        raise Refused(f"view {key} would be drawn by K.{render}, which {clash[0]} already "
                      f"defines; pick another key")
    title = name or key[:1].upper() + key[1:]
    # before More (the rows off the rail), so the diff is one added line
    at = next((index for index, row in enumerate(manifest["views"]) if row.get("nav") is False),
              len(manifest["views"]))
    manifest["views"].insert(at, {"key": key, "name": title, "icon": icon, "render": render,
                                  "script": script, "needs": []})
    manifest["scripts"].insert(manifest["scripts"].index("ui.js"), script)
    (app / script).write_text(VIEW_JS.format(key=key, title=title, render=render), encoding="utf-8")
    manifest_path.write_text(deckviews.dump(manifest), encoding="utf-8")
    problems = deckviews.check(manifest, app)
    if problems:
        manifest_path.write_text(before, encoding="utf-8")
        (app / script).unlink(missing_ok=True)
        raise Refused("the new view fails the manifest's check, so it was taken out: " + "; ".join(problems))
    return [manifest_path, app / script]


# ----- the verb -----

NEXT = {
    "pack": ["turn it on for a space in Setup (Packs), or name it as `pack = \"{name}\"` "
             "in a [spaces.<name>] table", "replace the sandbox's executables with your own, "
             "keeping [capabilities] true only for verbs that are here"],
    "kit": ["write the host layer ({stem}_layer.py), its checks, its guard policy and its stand-in "
            "hook (tests/standin.py)", "run `keel pack check {where}` until it passes",
            "turn it on for a space in Setup (Packs)"],
    "segment": ["run its test: python3 {where}/test_fetch.py",
                "make fetch.py read what this segment is about; `keel fetch` runs it on its cadence"],
    "view": ["open ?view={name} on the deck (a running deck serves the new script at once; "
             "restart it to list the file from the start)", "draw the view in app/ui.{name}.js, "
             "and name its readiness rows in its row's needs"],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keel new", description=(
        "a checked starting point for a pack, a segment or a deck view (docs/atlas/63-extending.md)"))
    parser.add_argument("kind", choices=("pack", "segment", "view"))
    parser.add_argument("name")
    parser.add_argument("--install", action="store_true",
                        help="a pack or segment in this install's own packs/ or segments_dir, "
                             "not the checkout (nothing reviews it there)")
    parser.add_argument("--into", metavar="DIR",
                        help="a pack in DIR, a packs folder of your choosing (the builder's clone of "
                             "packs, so the draft goes through its card)")
    parser.add_argument("--kit", action="store_true",
                        help="a code host pack on the pack kit (c-735): shims, a layer stub, a stand-in hook "
                             "and the conformance file; `keel pack check <dir>` says what is left")
    parser.add_argument("--space", help="a segment's space; default: the first configured space")
    parser.add_argument("--title", help="a view's name on the rail; default: its key, capitalised")
    return parser


def run(args, load, root: Path = CODE) -> list[Path]:
    """One `keel new`. `load` reads the config, and is called only when the kind needs it
    (a segment's spaces, or `--install`): a pack or a view in the checkout is made even while
    the config does not load, which is when a builder may most need one."""
    if args.install and args.kind == "view":
        raise Refused("a view is code: it lives in the checkout, so --install does not apply")
    if args.kit and args.kind != "pack":
        raise Refused("--kit is for a pack: a segment or a view has no host layer")
    if args.into:
        return pack_into(args, root)
    cfg = load() if args.install or args.kind == "segment" else None
    if args.install and cfg.install_home is None:
        raise Refused("--install needs an install's config (shipyard init); this one is not")
    if args.kind == "pack":
        into = cfg.install_home / packs.PACKS if args.install else None
        return new_pack(args.name, root, into, kit=args.kit)
    if args.kind == "segment":
        spaces = list(cfg.spaces)
        into = cfg.segments_dir if args.install else None
        return new_segment(args.name, args.space or (spaces[0] if spaces else ""), spaces, root,
                           into, cfg.segment_roots)
    return new_view(args.name, root, args.title)


def pack_into(args, root: Path) -> list[Path]:
    """`keel new pack <name> --into DIR` (c-678): the pack written into a packs folder the
    caller names, which is how the builder drafts one in its own clone of packs, on its
    card's branch. The config is never read."""
    if args.kind != "pack":
        raise Refused("--into is for a pack: a segment or a view has its own place")
    if args.install:
        raise Refused("one of --into and --install: --install is the install's own packs folder")
    target = Path(args.into).expanduser()
    if not target.is_dir():
        raise Refused(f"{target} is not a folder")
    return new_pack(args.name, root, target, kit=args.kit)


def main(argv: list[str] | None = None) -> int:
    from keel import config as config_module   # noqa: PLC0415 - only the verb reads a config
    args = build_parser().parse_args(argv)

    def load():
        try:
            return config_module.load(ensure=False)
        except config_module.ConfigError as error:
            raise Refused(f"the config does not load: {error}") from None
    try:
        written = run(args, load)
    except Refused as refused:
        print(f"keel new {args.kind}: {refused}", file=sys.stderr)
        return 1
    where = written[-1].parent
    print(f"made {args.kind} {args.name}:")
    print("\n".join(f"  {path}" for path in written))
    print("next:")
    print("\n".join(f"  {step.format(name=args.name, stem=scaffoldkit.stem(args.name), where=where)}" for step in NEXT["kit" if args.kit else args.kind]))
    print(ATLAS)
    return 0
