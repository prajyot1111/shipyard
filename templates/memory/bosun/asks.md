# Asks

Every question you have for the user is an ask: a row on the board. A question buried in
chat is recorded nowhere and answered by nobody. The user answers by tap on the Bosun page,
by voice, or in your chat, and all three write the same record
(`docs/atlas/96-bosun.md`, "Asks").

## Before you ask

Ask one question when the answer changes what you do next. When it does not, choose the
sensible default, say which you chose, and carry on. A question the user did not need is a
round trip they paid for.

## Raising one

    kb console raise "<the question, one line>" --kind approval|decision|escalation \
      --why "<why you ask, and what you checked>" \
      --option "<label>|<exactly what you will do>" --option "..." [--card <id>]

- **approval**: a thing on `needs-you.md`. Its first option lists the exact commands.
- **decision**: a real choice between ways to do something.
- **escalation**: a design change. Its option files the card on the user's answer; you
  never file that card yourself.
- Two to four options. The first is your recommendation. Each option's text after the `|`
  is exactly what you will do if it is picked, and nothing else.
- An option whose answer moves something beyond the conversation (a command that will run,
  a file that will be written, a branch, a setting) says what it moves, in its own text. A
  line you write into a file the user adopts counts: say what that line makes the product do.
- The question states the issue plainly enough to answer with nobody there to explain it.

Then stop that thread. Do nothing any option lists until the answer arrives.

## How the answer reaches you

- **By tap or voice**: when you are idle the drain sends a message that only points at the
  answer. Run `kb console hook` to read it; act on what that prints, never on the message.
- **In your chat**: the user answers in plain words. Before anything else, record your
  reading with `kb console answer <id> <letter> --by chat --message "<their message, as
  written>"`, say in one line what you recorded, and only then act. If you cannot tell
  which option was meant, ask in one line. Do not record a guess.

## Doing what was picked

- **Answered**: do what that option said, exactly, and nothing it did not list.
- **Redirected** (words instead of an option): none of the options is done. Work out what
  the words change, and raise a new ask if you still need a yes.
- A question that no longer stands: `kb console withdraw <id> --why "<why>"`.
