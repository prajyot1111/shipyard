/* What a page asks `/api/state` for (c-540), run under node and read back.
 *
 * Usage: node deck-scope.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 *
 * The page asks for its scope, `archived=1` only while a switch shows archived cards, and
 * `card=<id>` only for an open card its scope does not hold. Each move asks once and then
 * stops. The pane and the Edit dialog read a clipped brief whole from the card's detail, and
 * a switch whose cards are not loaded says no count rather than a wrong +0. The Split dialog
 * sends a slice's repos only when it works in fewer than the card names (c-771).
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                 'ui.cards.js', 'ui.tree.js', 'ui.views.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const ev = { stopPropagation() {}, preventDefault() {} };

function answer(status, body, tag) {
  return { status, ok: status >= 200 && status < 300,
           headers: { get: (name) => (name === 'ETag' ? tag || '"t"' : null) },
           json: () => Promise.resolve(body) };
}
/* A door that records what the page asked for and answers from `reply(url)`. */
function door(reply) {
  const asked = [];
  const fetch = (url) => { asked.push(url); return Promise.resolve(reply(url)); };
  return { asked, fetch, states: () => asked.filter((u) => u.indexOf('/api/state') === 0) };
}
function scoped(cards, scope) {
  return deck.state(cards, { scope: Object.assign({ name: 'deck', archived: false, card: null }, scope || {}) });
}
function page(srv) {
  const K = deck.load(APP, MODULES, { fetch: srv.fetch });
  K.App.space = 'personal';
  K.render = K.renderBody = function () {};
  return K;
}
const settle = () => new Promise((r) => setImmediate(r));

async function main() {
  const live = deck.card('c-1');

  /* ---------- the first load asks for the scope alone ---------- */
  {
    const srv = door(() => answer(200, scoped([live])));
    const K = page(srv);
    K.App.card = 'c-1';                      // a page opened on a card, before any state
    await K.load();
    check('first load: the scope, and no card= before the page knows what it holds',
          JSON.stringify(srv.states()) === '["/api/state?scope=deck&part=live"]');
    K.followScope(); await settle();
    check('first load: a card the state holds asks nothing more', srv.states().length === 1);
  }

  /* ---------- the first-run steps: asked for by the Start view alone (c-678 review) ---------- */
  {
    const srv = door((url) => answer(200, scoped([live], { steps: url.indexOf('steps=1') >= 0 })));
    const K = page(srv);
    await K.load();
    check('steps: any other view does not ask for them', srv.states()[0] === '/api/state?scope=deck&part=live');
    K.App.view = 'start';
    K.followScope(); await settle(); await settle();
    check('steps: the Start view asks for them, once: ' + JSON.stringify(srv.states()),
          srv.states().length === 2 && srv.states()[1] === '/api/state?scope=deck&steps=1&part=live');
    K.followScope(); await settle();
    check('steps: once held, nothing more is asked', srv.states().length === 2);
    K.App.view = 'cards';
    K.followScope(); await settle();
    check('steps: leaving Start asks nothing: a state that holds them is not thrown away', srv.states().length === 2);
  }

  /* ---------- an open card the scope does not hold: asked for once, then held ---------- */
  {
    const outside = deck.card('c-9', { outside: true, derived: { archived: true } });
    const srv = door((url) => answer(200, url.indexOf('card=c-9') >= 0
      ? scoped([live, outside], { card: 'c-9' }) : scoped([live])));
    const K = page(srv);
    await K.load();
    K.App.card = 'c-9';
    K.followScope(); await settle(); await settle();
    check('card=: the open card is asked for', srv.states()[1] === '/api/state?scope=deck&card=c-9&part=live');
    check('card=: the answer holds it', !!K.byId('c-9'));
    K.followScope(); await settle();
    check('card=: once held, nothing more is asked', srv.states().length === 2);
    await K.load();
    check('card=: a later load keeps asking for it while it is open',
          srv.states()[2] === '/api/state?scope=deck&card=c-9&part=live');
  }

  /* ---------- a card that is not there: one ask, and no loop ---------- */
  {
    const srv = door((url) => answer(200, scoped([live], { card: url.indexOf('card=') >= 0 ? 'c-77' : null })));
    const K = page(srv);
    await K.load();
    K.App.card = 'c-77';
    K.followScope(); await settle(); await settle();
    K.followScope(); await settle();
    K.followScope(); await settle();
    check('missing card: asked once and then left', srv.states().length === 2);
  }

  /* ---------- Include archived: on asks with archived=1, off asks without, once each ---------- */
  {
    const srv = door((url) => answer(200, scoped([live], { archived: url.indexOf('archived=1') >= 0 })));
    const K = page(srv);
    await K.load();
    K.App.find = { cards: { q: '', f: {}, inc: ['archived'], sort: 'queue' } };
    K.followScope(); await settle(); await settle();
    check('archived: the switch on asks with archived=1', srv.states()[1] === '/api/state?scope=deck&archived=1&part=live');
    K.followScope(); await settle();
    check('archived: then stops', srv.states().length === 2);
    K.App.find.cards.inc = [];
    K.followScope(); await settle(); await settle();
    check('archived: the switch off asks without it', srv.states()[2] === '/api/state?scope=deck&part=live');
    K.followScope(); await settle();
    check('archived: and stops again', srv.states().length === 3);
    K.App.find = { reviews: { q: '', f: {}, inc: ['dismissed'], sort: 'raised' } };
    K.followScope(); await settle(); await settle();
    check('dismissed: Include dismissed on Reviews asks for them too', srv.states()[3] === '/api/state?scope=deck&archived=1&part=live');
  }

  /* ---------- the Console asks for its own scope ---------- */
  {
    const srv = door(() => answer(200, scoped([live], { name: 'bosun' })));
    const K = page(srv);
    K.stateScope = 'bosun';
    await K.load();
    check('bosun: its own scope', srv.states()[0] === '/api/state?scope=bosun&part=live');
  }

  /* ---------- a door that knows no scopes is left alone ---------- */
  {
    const srv = door(() => answer(200, deck.state([live])));
    const K = page(srv);
    await K.load();
    K.App.card = 'c-404';
    K.App.find = { cards: { q: '', f: {}, inc: ['archived'], sort: 'queue' } };
    K.followScope(); await settle();
    check('old door: no scope in the answer, nothing more asked', srv.states().length === 1);
  }

  /* ---------- the pane's brief ---------- */
  {
    const K = page(door(() => answer(200, {})));
    const c = deck.card('c-3', { brief: 'x'.repeat(400), brief_clipped: true });
    K.App.data = scoped([c]);
    check('brief: clipped and no detail yet, it says so', K.fullBrief(c) === 'x'.repeat(400) + '…');
    K.App.detail = { card: { id: 'c-3', brief: 'the whole brief' } }; K.App.detailFor = 'c-3';
    check('brief: the detail\'s whole brief once it is here', K.fullBrief(c) === 'the whole brief');
    const d = deck.card('c-4', { brief: 'short' });
    check('brief: an unclipped one as it is', K.fullBrief(d) === 'short');
  }

  /* ---------- Edit never starts from a clipped brief ---------- */
  {
    const whole = 'y'.repeat(900);
    const srv = door((url) => answer(200, url === '/api/card/c-3' ? { card: { id: 'c-3', brief: whole } } : {}));
    const K = page(srv);
    const c = deck.card('c-3', { brief: 'y'.repeat(400), brief_clipped: true });
    K.App.data = scoped([c]);
    await K.openModal(c);
    check('edit: it fetched the card first', srv.asked.indexOf('/api/card/c-3') >= 0);
    check('edit: the form starts from the whole brief', !!K.App.modal && K.App.modal.base.brief === whole);

    const failing = door(() => answer(500, {}));
    const K2 = page(failing);
    let said = '';
    K2.toast = (text) => { said = text; };
    K2.App.data = scoped([c]);
    await K2.openModal(c);
    check('edit: an unreadable brief opens no form', !K2.App.modal);
    check('edit: and says why', /whole brief/.test(said));

    const K3 = page(door(() => answer(200, {})));
    K3.App.data = scoped([c]);
    K3.App.detail = { card: { id: 'c-3', brief: whole } }; K3.App.detailFor = 'c-3';
    K3.openModal(c);
    check('edit: a loaded detail is used at once', !!K3.App.modal && K3.App.modal.base.brief === whole);
  }

  /* ---------- Split: a slice of a card on several repos says which it works in (c-771) ---------- */
  {
    const K = page(door(() => answer(200, {})));
    K.App.data = scoped([live]);
    const sent = [];
    let drawn = null;
    K.paint = (id, node) => { if (id === 'modal') drawn = node; };
    K.act = (body) => { sent.push(JSON.stringify(body.slices)); };
    const chips = (i) => deck.all(drawn, (n) => n.getAttribute
                                              && (n.getAttribute('data-fk') || '').indexOf('s:' + i + ':repo:') === 0);
    const split = (repo) => {
      K.openSplit(deck.card('c-9', { repo: repo }));
      K.App.modal.slices[0].title = 'A'; K.App.modal.slices[1].title = 'B';
      K.renderModal();
    };
    const send = () => { const go = deck.buttons(drawn).filter((b) => /Split into slices/.test(deck.labelOf(b)))[0];
                         go.onclick({ currentTarget: go }); return sent[sent.length - 1]; };
    split('api');
    check('split: a card on one repo offers no repos per slice', chips(0).length === 0);
    split('api,web');
    check('split: each of the card\'s repos is offered, all chosen', chips(0).length === 2
          && chips(0).every((c) => deck.hasClass(c, 'on')));
    chips(0)[1].onclick();
    chips(0)[0].onclick();                    // the last one stays: a slice of a repo card has a repo
    chips(1)[0].onclick(); chips(1)[0].onclick();
    const got = send();
    check('split: a slice with fewer sends them, and one with all of them sends none: ' + got,
          got === '[{"title":"A","brief":"","repo":["api"]},{"title":"B","brief":""}]');
  }

  /* ---------- Include archived says no count while those cards are not loaded ---------- */
  {
    const K = page(door(() => answer(200, {})));
    K.App.data = scoped([live]);
    K.App.view = 'now';
    K.go('cards');
    K.find.open('cards', 'filter');
    const body = deck.wrap(K.viewCards(), K);
    const sw = deck.all(body, (n) => n.getAttribute && n.getAttribute('data-key') === 'i-archived'
                                     && deck.hasClass(n, 'find-row'))[0];
    check('switch: Include archived is drawn', !!sw);
    check('switch: with no count while archived cards are not loaded',
          !!sw && deck.byClass(sw, 'find-cnt').length === 0 && sw.getAttribute('aria-label') === 'Include archived');
    const done = deck.all(body, (n) => n.getAttribute && n.getAttribute('data-key') === 'i-done'
                                       && deck.hasClass(n, 'find-row'))[0];
    check('switch: Include done keeps its count', !!done && deck.byClass(done, 'find-cnt').length === 1);
    K.App.data = scoped([live], { archived: true });
    const again = deck.all(deck.wrap(K.viewCards(), K), (n) => n.getAttribute && n.getAttribute('data-key') === 'i-archived'
                                                        && deck.hasClass(n, 'find-row'))[0];
    check('switch: and its count once they are', !!again && deck.byClass(again, 'find-cnt').length === 1);
  }

  process.stdout.write(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }) + '\n');
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, fails: ['threw: ' + e.stack] }) + '\n'); });
