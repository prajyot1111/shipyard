# <key>: how to work in this repo

Claude Code loads this file for every session that works in this repo, below the space's
file and Keel's house contract. The CLAUDE.md your team keeps inside the repo is not
loaded in Keel's sessions: what is worth keeping from it is written here, in this shape.

Keel itself reads four lines of this file, by their opening words: the two under Prepare
and test, the one under Where work lands, and a line that begins "Run the app:" once
Running the app has one. Keep those words, and put each command or branch in backticks.

## Prepare and test

- Prepare a fresh copy: (the install step, in backticks; leave this line as it is when a copy needs none)
- Run the tests: (the command, in backticks, and about how long it takes)

## Where work lands

- Finished work lands on (the branch, in backticks).

## Running the app

- Sessions run tests only until this section says how to run the app.

## Conventions

- Where the code lives, where the tests live, and what the main entry points are.
- Naming, structure and style rules a reviewer of this repo would ask for.
- What not to touch (generated files, vendored code, a frozen API).

## What never goes here

- Secrets, tokens or private hostnames.
- Rules for every repo of the space: those are the space's file, one folder up.
- Notes about one card or one session.

Keep it short: a few dozen lines that stay true.
