# Cards from conversation

How what the user says becomes a card.

- **Their words go on the card as they said them.** When the user describes how something
  should behave, quote it in the brief and put your reading underneath, never in its
  place. A paraphrase loses the detail the house needed.
- **"Card it" means the inbox, and stop.** Create the card and say so. Assign it only when
  the user says assign, start or run. This is a default, for a user who pulls cards
  themselves: one who wants a carded thing started says so in the install's identity file.
- **Autonomous is the default.** File a card `attended` only when the user asks to see a
  plan first. A plan gate nobody asked for leaves a house waiting on a user who does not
  know it is.
- **Settings are fields, not prose.** A model, a repo or an option the user names goes in
  the card's own field. A brief that repeats a field can disagree with it.
- **A card that changes code names its repo.** With none it is an errand with no worktree,
  and cannot change a line. If the user's words do not settle which repo, ask, with the
  choices `kb repos` prints. Never recite repo names from memory.
- **The space is the boundary.** A card's space decides which credentials its house holds,
  and it cannot be changed after. Set it right the first time.
- **Run what is mechanical yourself.** Never hand the user a list of commands to type. If
  a step needs their hand, give one command they can copy, not a description of an edit.
- **Read back what you wrote.** After filing or changing cards, read them with `kb show`
  before you say it is done. Never report a batch from the command's silence.

## A big card

A card with slices is a tree. `kb tree <id>` reads it; `kb queue` says what starts next and
why anything waits. Assigning a whole tree is a dry run first, then the real run on the
user's yes (`docs/atlas/10-cards-and-gates.md`, "Only the user orders or assigns").
