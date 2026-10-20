# The deck, for the user

What the user can do on the deck, so you can point at the right place instead of
describing it. When you send a link, send the one that already shows what you mean.

- **Plans and outcomes are pages.** `/plan/<id>` and `/outcome/<id>` are answered in place:
  a choice per decision, a note pinned where it applies, then Approve or Send back
  (`docs/atlas/47-plans.md`).
- **Ask** puts one question to the card's house without sending the plan back. The house
  replies under the question.
- **A card's actions are grouped** in one row under its title. Resume house continues an
  idle house; Drop in opens it in a terminal; Open in Claude app opens it in the Claude app.
- **The find bar is the same on every list**: typed filters, switches that add what is
  hidden by default, and the state kept in the address. Hand the user a link that is
  already filtered.
- **Needs you** is the list of what waits on the user. It is derived from the board, so it
  is always current; read it with `kb needs-you` and do not keep a list of your own.
- **Settings** hold each space's choices and the install's. Setup is where repos and packs
  are added (`docs/atlas/89-onboarding.md`).

How the page is built is `docs/atlas/40-deck.md`.
