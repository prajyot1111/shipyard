# Contributing to Shipyard

Thank you for looking. This page is what you need to make a change that can land.

## Before you write code

Read `docs/atlas/00-start-here.md`. It is one page, it holds the whole model, and its
"Where to look for what" table says which page owns the part you want to change. Read that
page too: it answers faster than the code, and it carries the reasons the code cannot.

In the code and the docs the engine is called Keel (the package is `keel`). A reference
like `c-123` is an internal card number: it marks where a decision was recorded, and you do
not need to follow it.

## The house rules

- **Python 3.12 or newer, standard library only.** No package to install, no build step.
  The deck's JavaScript is plain, with no dependency and no bundler.
- **Tests first.** Write the test, see it fail, then make it pass. One test per behaviour,
  through its public seam. A test that cannot fail is removed.
- **The Atlas page in the same commit.** A change that adds or renames a module, a script,
  a verb or a config key updates its page, or `tests/test_atlas.py` fails and names what
  you missed. A new part gets a page or a section. Where a page and the code disagree, the
  code wins and the page is the bug: fix the page.
- **A rule for a session is a mechanism**, not a paragraph: a permission, a hook, a command
  that does not exist there. Generalise what exists before you add something new.
- **Short functions, single-purpose modules.** A module past about 600 lines wants
  splitting.
- **Plain words for what a user reads**: "you" or "the user", this machine and never a
  named one, no ticket or change noun spelled out in core (a pack supplies those).
- **No em-dashes**, anywhere: commas, colons, parentheses, or separate sentences.
- **A test never touches your machine.** It never runs a real service manager, never writes
  your real settings, never reaches a real code host. The suite fails a run that tries.

## Running the tests

```
make test-changed BASE=main    # the tests your change can reach; use this while you work
make test BASE=main            # the core suite plus what your change reaches
make test-all                  # every test
```

A single module runs with `python3 -m unittest tests.test_<name>`. Every target first runs
`make drift`, the wording and vocabulary checks: a pack's own words outside its pack, a
person's path or host name, a ticket noun in core, a pronoun where "the user" belongs. It prints what it
found and where. Run one suite at a time.

The voice gateway has its own interpreter and its own selftest; `make test-all` skips it
with a note until you have built it (`bin/keel voice venv`).

## Sending a change

- One change per pull request, with the tests and the Atlas page it needs.
- Say what you proved and how, and what you did not: not seen on a screen, not run against
  a real service.
- Keep anything of yours out of it: your name, your paths, your machine's names, the name
  of where you work. `python3 -m tests.publiccheck --range main..HEAD --list` reads your
  commits for them and prints where it found one.

## License

By contributing you agree that your contribution is licensed under the Apache License,
Version 2.0, the license of this project (see `LICENSE`).
