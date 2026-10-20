"""The builder's auto mode (c-621; docs/atlas/96-bosun.md, "The builder").

On an install Bosun runs as the user, in Claude Code's `auto` permission mode unless the user
chose bypass (`keel/builder.py`). The classifier reviews what no rule settled; this module
writes what it reads, and the deny rules that hold in either mode:

- **The `autoMode` block** (`block`): the install described (`environment`), the accidents
  that matter (`hard_deny`: a push to a shared branch, a write into a live checkout, reading
  credentials, and, since auto mode is the first run's Guide builder (c-678), installing
  software or changing this computer's settings), the built-in soft blocks kept (`soft_deny`: "$defaults") and building in its
  clones allowed (`allow`). Prose, read by the classifier.
- **The push deny rules** (`push_deny`): the pushes it never makes, as permission deny
  rules, which run before the classifier and in bypass too.

The block rides in Bosun's own `--settings` file, not in the config dir's settings.json:
`claude --settings <file> auto-mode config` lists its entries (2.1.287, 2026-10-03), so the
houses that share the install's config dir never read it.
"""

from __future__ import annotations

from pathlib import Path

DEFAULTS = "$defaults"
# Pushes the builder never makes: its work lands by the user's Approve outcome, fetched from
# its clone.
PUSH_DENY = ("Bash(*git*push*--force*)", "Bash(*git*push* -f*)", "Bash(*git*push*--mirror*)",
             "Bash(*git*push*--delete*)", "Bash(*git*push* +*)", "Bash(*git*push* main*)",
             "Bash(*git*push*:main*)", "Bash(*git*push* master*)", "Bash(*git*push*:master*)",
             "Bash(*git*push* next*)", "Bash(*git*push*:next*)")


def push_deny() -> list[str]:
    return list(PUSH_DENY)


def environment(clones: Path, repos: list[str], live: list[Path]) -> list[str]:
    return [DEFAULTS,
            f"Host: this session is Bosun, the builder of a Keel install, running as the user "
            f"on the user's own machine with the user's reach. Its workspace is {clones}: one "
            f"full git clone per repo it builds ({', '.join(repos)}) at {clones}/<repo>, and "
            f"its own folder per card at {clones}/cards/<id>. Building, testing and committing "
            f"in the clones is its job; reading and debugging the install (its logs, its board "
            f"through kb, the deck and Voice on 127.0.0.1, tailscale status) is part of it.",
            f"Trusted repo: each clone under {clones}, on its own bosun/* branches, and its "
            f"origin, the user's live checkout it was cloned from, which it fetches from and "
            f"never writes: {', '.join(str(path) for path in live) or 'none listed'}.",
            "Trusted internal tools: kb and keel (Keel's own CLIs, the board and its boards), "
            "the deck and Voice on 127.0.0.1.",
            "Sensitive data locations: the install's credentials directory, ~/.ssh, ~/.gnupg, "
            "~/.aws, ~/.config/gh, ~/.git-credentials, ~/.netrc, Claude's credentials and "
            "every token or key file."]


def hard_deny(live: list[Path]) -> list[str]:
    return [DEFAULTS,
            "Pushing to main, master or next from any repository, force-pushing in any form, "
            "deleting a remote branch or tag, or pushing with --mirror.",
            f"Writing, deleting, resetting, checking out or committing in a live checkout "
            f"({', '.join(str(path) for path in live)}): the builder works in its clones, and "
            f"its work reaches a live checkout only by the user's Approve outcome.",
            "Reading, printing, copying or sending credentials, tokens, keys, cookies or Claude "
            "login files, from anywhere.",
            "Posting an action to the deck's own page API as the user (Approve, Send back, a "
            "tap): Bosun acts on the board only through kb, as Bosun.",
            # c-678, decision `forms`: auto mode is the Guide builder of the first run
            "Installing software on this computer, changing its settings, or writing outside the "
            "builder's own clones and card folders: the guide builder gives the user the exact "
            "command, why, and how they will know it worked, and the user runs it."]


def allow(clones: Path) -> list[str]:
    return [DEFAULTS,
            f"Building, running the tests (make test, make test-changed, python -m unittest), "
            f"creating bosun/* branches and committing inside the clones under {clones}.",
            "git fetch from a clone's own origin, and git merge or rebase of the clone's own "
            "bosun/* branch onto what it fetched.",
            "Running kb and keel board, Keel's own CLIs, and reading the install's logs."]


def block(clones: Path, repos: list[str], live: list[Path]) -> dict:
    """The `autoMode` settings block for the builder's session."""
    return {"environment": environment(clones, repos, live),
            "hard_deny": hard_deny(live),
            "soft_deny": [DEFAULTS],
            "allow": allow(clones)}
