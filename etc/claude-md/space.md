# <space>: how the repos fit together

Claude Code loads this file for every session that works in a repo of this space, above
the repo's own file (`<key>/CLAUDE.md`). Keel's house contract comes first and is not
edited here. Write what is true across the repos of the space, and nothing else. With one
repo there is nothing to say here yet.

## The repos

- What each repo is, and which one owns what.
- What a change in one means for another (a route one serves and the other reads).

## Prepare and test

- Each repo has its own commands in its own CLAUDE.md. Say here only what is shared: run
  the tests of every repo a change touches.

## Running the app

- Sessions run tests only until this section says how to run the app.

## Conventions

- Names, formats and habits that hold across the repos.
- How small a change should be, and whether one card may change more than one repo.

## What never goes here

- Secrets, tokens, passwords, hostnames that are private: this file is read by every
  session and may be shown in logs.
- Anything about one repo: that is the repo's own file.
- Notes about one card or one session: that belongs on the card.
- Rules a session must not break: put those in a permission or a hook, not prose.

Keep it short: a few dozen lines that stay true beat a long file that drifts.
