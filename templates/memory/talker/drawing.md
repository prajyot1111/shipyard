# Drawing on the board

You draw. A card is never the way to draw: asked to show something, show it.

- **In a spoken answer**, write the lines in a fenced block whose language is `board`. Put
  one or two sentences before the block. Nothing after it is spoken.
- **In a typed chat**, run `keel board push --talker`.
- **Open every push with the topic.** The `board "<what this is about>"` line names the
  board: the same title continues it, a different title starts a new one. Leaving it out,
  or changing it by accident, puts lines on the wrong board.
- **A board is one diagram.** Groups, nodes and edges, with the detail (a note, a step, a
  table, a file) hanging on the node it is about. Keep it small enough to read at a
  glance; a second picture is a second board, not more nodes on the first.
- **Look before you draw.** `keel board find "<a few words>"` says whether there is already
  a board about this. Offer that one before starting another.
- **There is no erase.** A wrong line is corrected by a new note or a new board, so read
  the grammar before you write, not after.
- **Delete only your own boards**, never a card's. What is deleted goes to a trash the user
  can restore from.

The grammar is not kept here, because a copy kept by hand goes stale. It is printed, in its
current form, by `python3 -m keel.boardgrammar`, and its rules are the Atlas page
`docs/atlas/45-board.md`.
