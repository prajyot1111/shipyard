# Shipyard

Shipyard runs Claude Code sessions on cards. A card is one piece of work, from your words
to a change you approve. You write what you want, a session plans it and builds it, and
nothing lands until you have looked at the result and said yes.

It runs on one computer, yours, on macOS or Linux. There is no server to sign up for and
no account besides your own Claude sign-in.

## What you get


https://github.com/user-attachments/assets/a8c28163-4cf2-4ce2-9378-a3f210dd6881


- **A board.** Every piece of work is a card with a stage. What waits on you is always one
  list.
- **Two gates, both yours.** A plan you can read and answer before anything is built (when
  you ask for one), and an outcome you approve before it lands.
- **A deck.** One web page, on your desk and on your phone, where you file cards, read
  plans, answer questions and approve.
- **A builder.** One session that stays with your install, walks you through setup, and
  can build additions for you.
- **Voice**, if you want it: talk to the board from your phone.
- **Packs.** A pack connects a space of yours to where its code lives (a code host, a
  tracker). One for GitHub ships; you can write your own.

## What you need

- macOS or Linux. On Windows, Shipyard runs inside WSL2 (see Windows, below).
- Python 3.12 or newer. There are no Python packages to install: Shipyard uses the
  standard library only.
- git.
- Claude Code, signed in or ready to be.

If git has no name and email yet, the setup page asks for them. The installer checks each
of these and, for anything missing, says what happened, the fix, and whether it is
required. A run that misses something required stops there and makes nothing: do the fix
and run the command again.

## Install

From a checkout of this repository, run:

```
bin/shipyard init ~/shipyard
```

`~/shipyard` is the install: the folder that holds your config, your board and Shipyard's
own Claude sign-in. Choose any folder outside this checkout. The checkout stays where it
is and is the code the install runs.

Running the command again on the same folder is safe: it keeps your config and your board
and makes only what is missing.

The install also holds what your builder and your talker remember, in `memory/` (a git
repo), and a profile about you in `identity/about-you.md`. Both start from neutral
templates and are yours from then on: nothing Shipyard ships writes over them.

## Windows

Shipyard runs on Windows inside WSL2, as it does on Linux. Native Windows is not supported.

1. Install WSL2 with Ubuntu: in PowerShell, `wsl --install -d Ubuntu`, then restart if
   asked and open Ubuntu from the Start menu.
2. Turn systemd on inside it, since Shipyard's services are systemd user units: add these
   two lines to `/etc/wsl.conf` (for example with `sudo nano /etc/wsl.conf`):

   ```
   [boot]
   systemd=true
   ```

   then run `wsl --shutdown` from PowerShell and open Ubuntu again.
3. Inside Ubuntu, follow the Linux steps: install what "What you need" lists, clone this
   repository, and run `bin/shipyard init ~/shipyard`.

The page Shipyard serves is reached from Windows' own browser at the same address the
installer prints (`http://127.0.0.1:<port>`): WSL2 forwards it. The installer checks that
systemd is on, and `keel doctor` says so too, with the same fix.

## The first run

When the installer finishes it opens Shipyard's page in your browser, or prints its
address when it cannot. The page walks the rest of the setup one step at a time:

1. Choose your builder: how much it stops to ask you.
2. Check this computer: the same tools the installer checked, each with its fix.
3. Sign Shipyard in to Claude. It keeps its own sign-in in its own folder, so nothing here
   reads or changes the one you already use.
4. Meet your builder, connect your repos, and say where finished work goes.
5. Give it one small piece of work, and watch a card go from your words to a change you
   approve.

Steps that are not required can be skipped and done later.

## What is in this repository

The engine and nothing of any one user's. `keel/` and `bin/` are the engine and its
commands, `app/` the deck, `voice/` the voice gateway, `packs/` the packs that ship (`github`,
and `sandbox`, the example the demo runs on), `segments/` the segment that ships (`voice`),
`templates/` the memory and profile a new install starts from, and
`etc/shipyard.example.toml` every setting with its default, which `shipyard init` makes
your config from. Your config, your memory, your own packs and segments, and your services
live in your install, never in the checkout, so updating the code never touches them.

## Where the docs are

The Atlas, `docs/atlas/`, explains how every part works, one page per part. The deck shows
it too, under Atlas.

- `docs/atlas/00-start-here.md`: the whole model on one page, and where to look for what.
- `docs/atlas/88-install.md`: everything the installer does, in order.
- `docs/atlas/89-onboarding.md`: the first run, step by step.
- `docs/atlas/63-extending.md`: adding a pack, a segment or a view.

In the code and the docs the engine is called Keel: the package is `keel`, the commands are
`shipyard`, `keel` and `kb`, and the settings a session sees start with `KEEL_`. The `keel`
and `kb` commands and the `KEEL_` variables keep those names: they are not renamed to
Shipyard, so a script or a habit that uses them keeps working. A reference
like `c-123` in a comment is an internal card number; it explains nothing you need.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
