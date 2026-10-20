/* The page's half of the deck's auth (card c-451), run under node and read back.
 *
 * Usage: node deck-auth.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 *
 * The server sets its cookie on the page's GET of the shell and asks for it on every POST
 * that acts as him. So the page must (1) post with the browser's default credentials,
 * never `omit`, and (2) when a POST is refused with `renew` (the deck restarted since the
 * page loaded, and minted a new cookie), fetch the shell once to pick it up and send the
 * same POST again, once. A refusal that does not say `renew` is shown, not retried.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function answer(status, body) {
  const r = { status, ok: status >= 200 && status < 300, headers: { get: () => null },
              json: () => Promise.resolve(body) };
  r.clone = () => answer(status, body);
  return r;
}

/* A fetch that records every call and answers `/api/action` from a script of replies. */
function server(replies) {
  const calls = [];
  const fetch = (url, init) => {
    calls.push({ url, init: init || {} });
    if (url === '/api/action') return Promise.resolve(replies.shift() || answer(500, { ok: false, error: 'none left' }));
    if (url === '/api/state') return Promise.resolve(answer(200, deck.state([deck.card('c-1')])));
    return Promise.resolve(answer(200, {}));
  };
  return { calls, fetch };
}

function page(srv) {
  const K = deck.load(APP, ['ui.core.js'], { fetch: srv.fetch });
  K.App.data = deck.state([deck.card('c-1')]);
  K.render = K.renderBody = K.renderHeader = K.renderSheet = function () {};
  return K;
}
const actions = (srv) => srv.calls.filter((c) => c.url === '/api/action');
const shells = (srv) => srv.calls.filter((c) => c.url === '/');

async function main() {
  /* ---------- a tap goes with the page's cookie ---------- */
  {
    const srv = server([answer(200, { ok: true, result: { id: 'c-1' } })]);
    const K = page(srv);
    check('K.post is the page\'s one POST helper', typeof K.post === 'function');
    const result = await K.act({ verb: 'note', id: 'c-1', text: 'x' });
    const sent = actions(srv)[0];
    check('the tap reached /api/action', !!sent && sent.init.method === 'POST');
    check('it goes with the browser\'s default credentials, never omit',
          !!sent && (sent.init.credentials === undefined || sent.init.credentials === 'same-origin'));
    check('the tap resolves with its result', !!result && result.id === 'c-1');
    check('a tap that was taken fetches no shell', shells(srv).length === 0);
  }
  /* ---------- a restarted deck: renew once, then the same tap again ---------- */
  {
    const srv = server([answer(403, { ok: false, error: 'this deck restarted', renew: true }),
                        answer(200, { ok: true, result: { id: 'c-1' } })]);
    const K = page(srv);
    const result = await K.act({ verb: 'unblock', id: 'c-1' });
    const order = srv.calls.map((c) => c.url).filter((u) => u === '/' || u === '/api/action');
    check('renew fetches the shell between the two tries',
          JSON.stringify(order) === JSON.stringify(['/api/action', '/', '/api/action']));
    check('the shell is fetched past every cache', (shells(srv)[0] || { init: {} }).init.cache === 'no-store');
    check('the second try sends the same body', actions(srv).length === 2
          && actions(srv)[0].init.body === actions(srv)[1].init.body);
    check('the renewed tap resolves with its result', !!result && result.id === 'c-1');
  }
  /* ---------- renewed and still refused: shown, never a loop ---------- */
  {
    const srv = server([answer(403, { ok: false, error: 'not the page', renew: true }),
                        answer(403, { ok: false, error: 'not the page', renew: true })]);
    const K = page(srv);
    const result = await K.act({ verb: 'unblock', id: 'c-1' });
    check('it renews only once', shells(srv).length === 1 && actions(srv).length === 2);
    check('a second refusal resolves to nothing', result === null);
    check('and is said on the toast', /not the page/.test(K._doc.getElementById('toast').textContent));
  }
  /* ---------- a refusal without renew is not retried ---------- */
  {
    const srv = server([answer(409, { ok: false, error: 'no verb called nope' })]);
    const K = page(srv);
    await K.act({ verb: 'nope' });
    check('a 409 is not retried', actions(srv).length === 1 && shells(srv).length === 0);
    const srv2 = server([answer(403, { ok: false, error: 'forbidden for another reason' })]);
    const K2 = page(srv2);
    await K2.act({ verb: 'nope' });
    check('a 403 that does not say renew is not retried', actions(srv2).length === 1 && shells(srv2).length === 0);
  }
  process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: String(e && e.stack || e) })); });
