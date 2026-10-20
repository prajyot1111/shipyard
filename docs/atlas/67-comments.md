# A card's review comments

The review comments page shows, for one card at shipping, every round of review its house
was told and what it did with each item (c-643, c-639): what the reviewer said, the house's
verdict, its reasoning and commits, and the reply it drafted, with the user's Post, Edit and Drop on
each reply and Ship. It is a page of the card, beside its plan, outcome and CI, and each
links to the others. The card pane keeps one line of it and opens it.

Code: `keel/commentsroute.py` (the route and its data), `app/ui.comments.js` (the page), and
`app/ui.shipping.js` (the row and Ship, drawn for the pane and the page alike).

## The data

Nothing new is stored. The page reads what the pane read at shipping
([the deck](40-deck.md), "The standing batch"; `keel/shipreplies.py`):

- `options.shipping.told`: each item the house was told, with `batch` (its round) and
  `told_at`;
- the house's `verdict` events, one per item (`kb verdict`);
- the user's `mark` events: post, edit (the user's words) or drop on each reply.

**`/api/comments/<id>`** (`commentsroute.payload`) answers:

```
{"card": {id, title, space, stage, repo, output_ref, blocked_reason, session_id, terms,
          options: {shipping: {.., told: [{handle}]}}},
 "docs": [the card's pages], "at",
 "rounds": [{"round", "told_at", "rows": [shipreplies.rows' row + {"text", "whole"}]}],
 "shipping": {"summary": shipreplies.summary},
 "why": null, or why there is nothing to show}
```

- **Rounds are newest first** (the open round is what the user answers); a round's rows keep the
  order they were told in.
- **A comment's whole text.** The card keeps a comment cut to `shipwatch.TEXT_MAX`, ending
  with a marker naming its file. The page reads the whole text from the card's
  `comments/<file>` (`shipwatch.comment_file`, written by the drain that watches the pull
  request, `shipping.keep_whole`) where this machine keeps it, without its header, and only
  while it still begins with the cut text the house was told. Otherwise the row carries the
  cut text, `whole: false` and `cut`: `here` when the file is not there,
  `edited` when the comment was edited on the host since (the watcher rewrites the file),
  and the page says which.
- **`docs`** lists the card's pages (`planroute.more_pages`): `comments` on a card at
  shipping, or one whose house was ever told an item (`commentsroute.offered`). The plan,
  outcome, CI and comments headers all list it.

## The page

- **`/comments/<id>`** is served by the plan page's shell (`PLAN_PAGE` takes `comments`;
  `app/plan.html` loads `ui.shipping.js`, `ui.shipsendback.js` and `ui.comments.js`; `viewPlan` hands it the body).
- **The header**: back to the card, its space, "Comments", and the links to each other page
  of the card: the viewer's tabs (`K.docTabs`, c-644), and the flow's moves (`K.flowBar`).
- **The summary line** counts the items, the judged ones, the replies to post and the
  posted ones (`K.shipping.countLine`, the pane's line too), and the page's `summary` adds
  the commits the house made.
- **A card no longer at shipping** (merged, done) keeps its page read only: no Post, Edit or
  Drop, no replies counted to post, and a line that says the review is closed.
- **Ship** at the top and at the foot, the pane's own (`K.shipping.bar`, with its
  confirm): named for what it sends and drawn only where the send can succeed, else the
  one line saying why not, with Ship anyway or the by-hand commands where they apply (c-653, [the
  deck](40-deck.md), "A shipping card on the deck"); a blocked or declined card says that.
  After a Ship from here its own line stands where the button was until the page's next
  read is that Ship's (c-660), so the old label is never drawn over a send that was made.
  The page's card carries `house: {working: true}` while the house is in a turn
  (`commentsroute.in_turn`, the check's own rule), since this page has no listing of its own.
- **Each round** is a section, "Round 2, told 3h ago", and each item in it is the pane's row
  (`K.shipping.row`): the handle and verdict chip, who said it and where, the whole text,
  the house's summary and reasoning, each commit's diff folded under its sha and subject, the reply, and
  Post, Edit and Drop (`kb mark`, `doc: shipping`, `block: replies`), the same marks with the
  same refusal after posting. Items still waiting say when they go. A `prepared` row (r-55,
  c-723) says the house waits on the user's answer, with Answer (Send back with its handle
  leading the words), or that the user answered and the house records it again; the page's
  card carries `derived.ship_prepared` for it.
- **It is read** when the page opens, on every board event for the card (the shell's
  `K.loadPlan` hands it to `K.loadComments`), and after each mark or Ship it sends
  (`K.shipping.onActed`, since `K.act` reloads the deck's state, not this page's): the data
  is the board's alone, so a mark or a verdict shows at once. A re-read asks `?again=1` and
  keeps the header's pages it has, so the plan is not read on every event; they are read
  again when the card's stage moves (an outcome is written at a gate) and when the last list
  was empty. One read runs at a time, and an event during one reads once more
  after it. It wears its card's palette (`K.wearSpace`).

## The pane

At shipping the card pane's "review replies" section is one line, "4 review items: 3 judged,
2 replies to post. Open comments has each one." **Open comments** (`open-comments`) is among
the card's Pages (c-644), leading them at shipping, and opens the page beside the deck as the
plan does. It keeps the waiting line and the declined note. Ship stays among the
pane's gate actions: it is the shipping gate's one action, and needs-you leads to the pane.

Under the waiting line the pane says each kind's automatic handling in words, never
silently (c-655, `K.shipping.autoLines`): off with items, "3 comments waiting. Automatic
handling of review comments is off: hand them to the house, or turn it on to have each new
comment handled as it arrives."; off with none, that a new one waits here; on, that it is
on, and what still waits for the user's hand-over. Each has its tap (Turn on, Turn off, and Use
the space's setting where the card set its own), which is a `set` of the card's option.
The count is `derived.ship_handover`'s, the same the hand-over button says. The comments
page draws the same lines under its own waiting line, with the same taps (the route's card
carries `derived.ship_auto` and `ship_handover`), and a page with no round yet says "The
house has been told no review yet", never that review goes to the house as it arrives.

## The user's own send-back

Send back (c-663, `keel/shipsendback.py`) is on this page under Ship at the top, on a card
at shipping that is not blocked, declined or archived (`K.shipping.sendBackOffered`), and is
the pane's own button and box (`K.shipping.sendBackButton`, `app/ui.shipsendback.js`): the user's words, told
to the card's house as its next item, the card staying at shipping. What the user sent and the
house has not been told yet is drawn under the waiting line in the user's words, marked "yours"
and "waiting", or "held" with why when the drain is not telling it now (the route's card
carries `derived.ship_sendback` and `archived`). Once told it is a row of
its round like any other, marked "yours", saying it stays here and nothing is posted, and
"told, not judged yet" until the house records its verdict: the
house's verdict, its reasoning, its commits and its answer to the user, and no Post, Edit or
Drop. The summary counts the user's beside the review, never among the replies to post.

## The outcome only when behaviour changes

The batch's words (`keel/shipround.py`, step 1 of "Recording each item") tell the house to
change the card's `context.md` only when its change alters how the thing works (its
behaviour, an interface, its risk). A rename, a test, a comment or a style fix is recorded in
its verdict alone, which this page shows.
