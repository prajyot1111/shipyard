# Runbook

How the pieces you look after run. The Atlas is the source of truth; this is the short
form. Fill in what is true of this install as you learn it (where its checkouts are, what
its suite costs), and keep one user's taste out of the rules.

## This machine

- Size parallel work to the machine. Check its load before you start anything heavy, and
  wait when it is busy. How many builders at once is a default the user can change: start
  with two.
- One test run at a time, read to the end, and never in a loop. This is a default sized
  for a machine with little to spare: the user can change it for one with room.
- One landing at a time: each lands on what the last one left.
- Never end a process by pattern. A pattern matches processes you never meant to touch:
  look first, then end one process you can name by its id.
- Anything long-running is a service the install manages, never a session left open.

## Tests

A test never touches the machine it runs on. It never runs a real program that changes or
asks the machine's services, never writes the user's real settings, and never reaches a
real code host. The suite enforces this itself
(`docs/atlas/00-start-here.md`, "The test fence"): when the fence
fails a run, fix the test, not the fence.

## The drain

- `kb queue` shows what it will start and why anything is not starting.
- It resumes a house only when the harness reports that house exited, once. It never ends
  a live session, and neither do you (`docs/atlas/30-drain.md`).

## Your own session

- The user starts, stops and restarts you. Those verbs are denied to you.
- Your hooks print this memory, the open requests above each message, and a handoff note
  before a compaction. A change to them that lands reaches you on your next start.
- After a compaction, read the board again before you act on anything the note names.
- By voice, the user's sentences arrive quoted. Answer in short spoken sentences.

## What you never touch

- A live checkout, and any service you did not start.
- Another tool's processes, containers or config. If one is in your way, that is an ask.
