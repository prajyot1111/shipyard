# Vendored browser code

Two libraries, and they are here rather than fetched from a CDN because the deck loads **no
external resource**: it is served over the tailnet to a phone that may have no route to
the public internet, and a page that reaches out for a script is a page that fails
exactly when the user is away from their desk.

| File | What it is | Version | Licence | From |
|---|---|---|---|---|
| `highlight/core.min.js`, `highlight/languages/{xml,python,javascript,sql,yaml,json,bash}.min.js` | highlight.js, the syntax highlighter, as ES modules: its core and the seven grammars the plan pages colour (xml is there for JavaScript's JSX). `app/ui.plancode.js` imports them only when a page has code, walks the token tree (never the HTML string it also answers), and colours through six classes on the deck's own tokens. | highlight.js 11.11.1 | BSD-3-Clause (`highlight/LICENSE`) | `https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/es/core.min.js` and `.../es/languages/<name>.min.js` |
| `elk.bundled.js` | ELK, the Eclipse Layout Kernel, compiled to JavaScript. The board's diagram is laid out by it, in the browser: layered layout, nested groups, edge labels with measured sizes, and `elk.aspectRatio` with `MULTI_EDGE` wrapping so a long chain folds to the stage's shape rather than running off it. | elkjs 0.9.3 | EPL-2.0 | `https://cdn.jsdelivr.net/npm/elkjs@0.9.3/lib/elk.bundled.js` |

highlight.js is redistributed unmodified with its licence beside it. To move to another
version, download that version's files from the same paths, replace them whole, and change
the version in the row above in the same commit. `keel/serve.py` serves each file under
`/vendor/highlight/` (`serve.APP_FILES`); nothing loads them on a page's first request.

EPL-2.0 is a file-level copyleft: the file is redistributed unmodified, and nothing in
Keel is a derivative of it. Do not edit it. To move to another version, download that
version's `elk.bundled.js` from the same path, replace the file whole, and change the
version in the row above in the same commit.

`keel/serve.py` serves it at `/vendor/elk.bundled.js` (`serve.APP_FILES`), `app/index.html`
loads it deferred, and `app/sw.js` keeps it in the shell cache. `app/ui.board.js` asks for
it only when a graph frame is actually drawn, and says so on the frame rather than failing
if it is not there.
