# Keel

Keel is the rebuild of Harbor: one board, one drain, one deck. The module and data
contracts every builder must follow are `docs/layout.md`; read it before writing code here.
The design and the decisions that shaped it are one owner's history and live in that
owner's install (`history/docs/`), not in the code. This file holds only the rules that must
never be missed.

## The Atlas is the source of truth

`docs/atlas/` explains how every part of Keel, and of the setup around it, actually works:
one page per part, rendered on the deck at `?view=atlas`. The design and the decisions are
history, kept in the install (why this shape, what was decided); `docs/layout.md` is the
contract every builder follows now. The Atlas is the present tense of how it all works.

- **Read the page before you change a component.** It answers faster than the code, and it
  carries the reasons and the recorded facts the code cannot state.
- **When you do not understand something, the Atlas answers before the code does.** Start
  at `docs/atlas/00-start-here.md`: its "Where to look for what" table is the index, and
  its module map says which page owns which file.
- **Update the page in the same commit.** A change that renames a module, a script, a verb
  or a `[keel]` key without updating its page does not merge: `tests/test_atlas.py` names
  them all and fails on the one you missed.
- **A new component gets a page, or a section of one, in the commit that adds it.**
- **Where a page and the code disagree, the code wins and the page is the bug.** Fix the
  page rather than deleting the claim.

## Non-negotiable

- **The harness is the runtime.** Sessions are started with `claude --bg`, listed with
  `claude agents --json`, read with `claude logs`, resumed with `claude --resume <id> --bg`,
  and report through `Stop`, `Notification` and `SessionEnd` hooks. Never use tmux, never
  read a terminal pane, never type into one, never infer that a session is stuck from how
  long it has been quiet. If the harness cannot say it, Keel does not know it.
- **One store.** `state/board.db` (SQLite) is the only state. Gates, "needs you", sessions
  and worktrees are derived from cards and `claude agents --json`. Do not add a second
  store, a queue file, a ledger, or a cache that has to agree with the board.
- **Nothing automatic ends a live session.** The drain resumes only a session the harness
  reports as exited, once. `claude stop` is called by a human tap in the deck, by a
  resume on the one session it has just superseded (its conversation continues in the
  new one), and by Approve outcome (or Adopt, a tier or flow proposal's outcome) on the card's own
  finished house when the card is done
  (a work card at shipping keeps its house, which answers review there, c-600); by a
  merge to done on the card's own idle house; and by the drain on a shipping house the
  harness lists idle for over 2 hours, which its next review batch resumes (a-72, c-607);
  and by the drain on a shipping house whose turn on its re-offered batch has ended (his
  explicit word, c-651: `kb ship <id> reoffer`; idle once that turn ends, whatever it
  judged, and its next review batch resumes it); never on a session that is doing
  something. A resume of a conversation the harness no longer holds starts a new house
  from the card's record and stops nothing (c-654). The drain wakes Bosun, and tells a house his tap or
  its review batch, with a message into its live session, never a stop (c-530, c-598).
- **Mechanism over prose.** A rule for a house is a permission deny, a hook, a
  `--restricted` flag, or a command that does not exist in that session. The house
  contract (`etc/house-contract.md`) stays under 60 lines and explains; it does not enforce.
- **Employer vocabulary lives only in its pack**, the work pack, which is the install's own
  (`<install>/packs/work/`) and not in the code. Nothing in the code may name the employer,
  its tracker, its code host, or its tools. `make test` greps for this with each pack's own
  `drift-terms`, the install's packs included. The pack is named for the space, so the
  config never has to name the employer either (`docs/atlas/62-packs.md`).
- **Nothing of one user's is in the code.** No name, home path, host, config, memory or
  segment of the owner's: `make drift` runs the public check strict (`tests/publiccheck.py`).
- **Every path a card stores points outside every worktree**: `state/cards/<id>/`.

## Working here

- Python 3.14, standard library only (`sqlite3`, `tomllib`, `http.server`, `json`,
  `subprocess`). No pip dependencies. Tests are `unittest`, run with `make test`.
- Iterate with `make test-changed` (only the tests your change can reach; it runs every
  test whenever it cannot tell), and run it before review too: `make test` (the core suite
  in `tests/core.txt` plus the extended tests the change reaches) runs once per change, on
  the merged tree where it lands (decision G-5, c-646). `make test-core` is the core suite
  alone; `make test-all` is every test, voice included: on demand, and at every deploy,
  which is the gate that runs every module. A new test is extended unless it guards a core
  promise.
- Keel never writes into `~/harbor`. Do not unload, edit or restart any
  launchd agent of the human's own; that is the human's cutover step.
- Never `wt-activate`, never touch the shared `cloud`/`webapp` containers, never
  `pkill -f` or `killall`; look with `pgrep -f` and kill a pid you can name.
- Keep functions short and modules single-purpose. A module over ~600 lines is a sign the
  split in `docs/layout.md` is being ignored.
- No em-dashes anywhere (code comments, docs, commit messages): commas, colons,
  parentheses, or separate sentences.
- Commit with the human's global git identity; never set a repo-local `user.name` or
  `user.email`.
