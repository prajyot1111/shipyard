/* The deck's card pane and the routes around it, rendered under node and read back.
 *
 * Usage: node deck-pane.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 *
 * Each block renders one surface the way the page would (the phone unless it says desk)
 * against a state document built here, and reads the tree it built. A grep can say a name
 * is in a file; this says what the page actually draws.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js', 'ui.shipping.js', 'ui.shipsendback.js', 'ui.cards.js', 'ui.tree.js', 'ui.reviews.js', 'ui.views.js',
                 'ui.atlas.js', 'ui.board.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function page(cards, opts, extra) {
  const K = deck.load(APP, MODULES, opts || {});
  K.App.data = deck.state(cards, extra);
  K.App.space = 'personal';
  /* ui.js (the boot) is not loaded: it would fetch and open the stream. Its two passes are
     stood in for, so a route change can be driven through `K.go` as the page drives it. */
  K.render = K.renderBody = function () {};
  return K;
}
function dts(node) { return deck.all(node, (n) => n.tagName === 'DT').map((n) => n.textContent); }

/* ---------- F7: provenance is not a raw options row ---------- */
(function () {
  const c = deck.card('c-1', { options: { provenance: { model: 'stated', repo: 'assumed' }, custom: 'x' } });
  const K = page([c]);
  const keys = dts(deck.wrap(K.detailPane(c), K));
  check('F7: provenance is hidden from the inspector facts', keys.indexOf('provenance') < 0);
  check('F7: an unknown option key is still listed', keys.indexOf('custom') >= 0);
})();

/* ---------- F6: a segment's notice is a needs-you item that says what it is ---------- */
(function () {
  const n = deck.card('c-2', { topic: 'notice', brief: 'backup pull is stale\nmore', options: { notice_key: 'backup-pull-stale' },
                               derived: { needs_you: true, notice: true } });
  const g = deck.card('c-3', { stage: 'planning', plan_ref: 'p.md', derived: { needs_you: true, plan_gate: true } });
  let K = page([n, g]);
  K.App.view = 'attention';
  const list = deck.wrap(K.viewAttention(), K);
  const text = list.textContent;
  check('F6: the notice is listed in Attention', text.indexOf('c-2') >= 0);
  check('F6: its chip says notice', deck.byClass(list, 'notice').some((x) => x.textContent === 'notice'));
  check('F6: nothing reads "null gate"', text.indexOf('null') < 0);
  check('F6: the row says what the notice is about', text.indexOf('backup pull is stale') >= 0);
  const tiles = deck.wrap(K.viewNow(), K).textContent;
  check('F6: the Attention tile counts it as a notice', tiles.indexOf('1 at a gate, 1 notice') >= 0);
  K = page([n], { desk: true });
  const pane = deck.wrap(K.gateActions(n), K);
  check('F6: a notice can be dismissed from where it is shown', deck.labels(pane).indexOf('Dismiss') >= 0);
})();

/* ---------- lane RC: Reviews is the review cards and nothing else ---------- */
function reviewCard(id, state, author, created, extra) {
  const stage = { waiting: 'inbox', reviewing: 'building', gate: 'review', posted: 'done', 'new': 'done' }[state];
  return deck.card(id, Object.assign({ space: 'work', repo: author === 'Bo Example' ? 'web' : 'api',
    stage: stage, title: 'Review: invented change ' + id, autonomy: 'autonomous',
    options: { review_key: 'api:' + id.slice(2), kind: 'review', pr: Number(id.slice(2)),
               review_pr: { author: author, created: created, updated: created, url: 'https://example.invalid/pr/' + id } },
    links: { pr: 'https://example.invalid/pr/' + id },
    derived: { review: state, needs_you: state === 'gate', outcome_gate: state === 'gate' } }, extra || {}));
}
function reviewsPage(cards, opts) {
  const K = page(cards, opts, {
    spaces: { personal: { adapter: null, repos: ['keel'], options: [], verbs: { card: [] }, topics: [], counts: {}, terms: deck.TERMS.personal },
              work: { adapter: 'work', repos: ['api', 'web'], options: [], verbs: { card: [] }, topics: [], counts: {}, terms: deck.TERMS.work } },
    providers: { work: { reviews: { route: 'reviews', columns: ['detected', 'inbox'], hidden: 0,
      settings: { auto_review: false, review_model: 'sonnet', models: ['sonnet', 'opus'], orientation: 'auto',
                  orientations: ['auto', 'off'] },
      items: [{ key: 'acme/api#9', label: 'api#9', title: 'an old scanner row', kanbanState: 'inbox',
                verbs: [{ verb: 'launch_review', label: 'Launch review', to: null },
                        { verb: 'lavish_review', label: 'Lavish review', to: null },
                        { verb: 'terminal_review', label: 'Terminal review', to: null }] }] } } }
  });
  K.App.space = 'work';
  K.App.view = 'reviews';
  return K;
}
(function () {
  const cards = [reviewCard('c-701', 'waiting', 'Ana Example', '2026-09-22T09:00:00+00:00'),
                 reviewCard('c-702', 'gate', 'Bo Example', '2026-09-23T09:00:00+00:00'),
                 reviewCard('c-703', 'new', 'Ana Example', '2026-09-20T09:00:00+00:00',
                            { options: { review_key: 'api:703', kind: 'review', pr: 703, review_new: { head: 'h2' },
                                         review_posted: { head: 'h1', verdict: 'changes', severity: 'high' },
                                         review_pr: { author: 'Ana Example', created: '2026-09-20T09:00:00+00:00' } },
                              derived: { review: 'new', review_severity: 'high' } }),
                 reviewCard('c-704', 'posted', 'Cy Example', '2026-09-21T09:00:00+00:00'),
                 reviewCard('c-706', 'waiting', 'Cy Example', '2026-08-01T09:00:00+00:00',
                            { derived: { review: 'waiting', backlog: true } }),
                 deck.card('c-705', { space: 'work', repo: 'api', title: 'not a review card' })];
  let K = reviewsPage(cards, { desk: true });
  let view = deck.wrap(K.viewRoute('reviews'), K);
  const rows = () => deck.all(view, (n) => deck.hasClass(n, 'row') && /^c-7/.test(n.getAttribute('data-key') || ''))
    .map((n) => n.getAttribute('data-key'));
  check('RC-6: the list is the review cards and nothing else, newest raised first', rows().join() === 'c-702,c-701,c-704,c-703');
  const labels = deck.labels(view);
  ['Lavish review', 'Terminal review', 'Launch review', 'Scan now', 'Generate orientation'].forEach((word) => {
    check('RC-6: the deck offers no ' + word, labels.indexOf(word) < 0);
  });
  check('RC-6: no sort or filter chips (the find bar does that, lane FIND)', deck.byClass(view, 'lanechip').length === 0);
  check('RC-6: the row says the severity he posted', deck.all(view, (n) => deck.hasClass(n, 'spill') && n.textContent === 'high').length === 1);
  const gearOf = () => deck.all(view, (n) => n.getAttribute && n.getAttribute('data-key') === 'review-gear')[0];
  check('RC-6: the settings sit behind a gear at the title', !!gearOf() && view.textContent.indexOf('auto review') < 0);
  gearOf().onclick();
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('RC-6: the gear opens auto review and the review model', view.textContent.indexOf('auto review') >= 0
        && view.textContent.indexOf('review model') >= 0 && deck.labels(view).indexOf('opus') >= 0);
  check('RC-6: no orientation setting is drawn', view.textContent.toLowerCase().indexOf('orientation') < 0);
  const inbox = cards[0], fresh = cards[2];
  const inboxPane = deck.labels(deck.wrap(K.cardItems(inbox), K));
  check('RC-6: an inbox review card is started with Review', inboxPane.indexOf('Review') >= 0 && inboxPane.indexOf('Assign') < 0);
  check('RC-6: Open PR is a link on the review card', inboxPane.indexOf('Open PR') >= 0);
  const freshPane = deck.labels(deck.wrap(K.cardItems(fresh), K));
  check('RC-6: new commits offer Re-review', freshPane.indexOf('Re-review') >= 0);
  check('RC-6: Reviews counts what waits on him, not the backlog', K.reviewCount() === 3);
  check('RC-7: a backlog review card is counted, not listed', rows().indexOf('c-706') < 0
        && deck.wrap(K.viewRoute('reviews'), K).textContent.indexOf('1 in the backlog') >= 0);
  K = reviewsPage(cards, {});
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('RC-6: the phone has the gear too', !!gearOf());
  K.App.card = 'c-701';
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('RC-6: a tapped row opens the card on the phone', view.textContent.indexOf('Review: invented change c-701') >= 0
        && deck.labels(view).indexOf('Review') >= 0);
})();

/* ---------- F5: Attention's age is how long the gate has been open ---------- */
(function () {
  const now = Date.parse('2026-09-24T10:00:00+00:00');   // the state document's own now
  const iso = (ms) => new Date(now - ms).toISOString();
  const c = deck.card('c-4', { stage: 'planning', plan_ref: 'p.md', updated_at: iso(60 * 1000),
                               derived: { needs_you: true, plan_gate: true, gate_since: iso(2 * 86400 * 1000) } });
  const K = page([c]);
  const ages = deck.byClass(deck.wrap(K.viewAttention(), K), 'age').map((n) => n.textContent);
  check('F5: the age counts from the gate opening, not the last note', ages.indexOf('2d') >= 0);
})();

/* ---------- F1: a blocked card takes his answer with the resume ---------- */
(function () {
  const c = deck.card('c-5', { stage: 'building', session_id: 'aaaaaaaa-1111', blocked_reason: 'which key do I use?',
                               last_said: 'I stopped: the upload needs a key and there are two.', derived: { needs_you: true } });
  const K = page([c], { desk: true });
  const row = deck.labels(deck.wrap(K.gateActions(c), K));
  check('F1: the blocked row offers Answer and resume', row.indexOf('Answer and resume') >= 0);
  check('F1: plain Resume house is still there', row.indexOf('Resume house') >= 0);
  const sheet = K.App.sheet = { kind: 'say', id: c.id, gate: 'blocked', mode: 'answer' };
  const drawn = deck.wrap(K.saySheet(sheet), K);
  check('F1: the sheet shows what the house asked', drawn.textContent.indexOf('the upload needs a key') >= 0);
  check('F1: the sheet has a field', deck.all(drawn, (n) => n.tagName === 'TEXTAREA').length === 1);
  let sent = null;
  K.act = function (body) { sent = body; return Promise.resolve(null); };
  K.toast = function () {};
  const send = () => deck.buttons(drawn).filter((b) => b.textContent === 'Answer and resume')[0].onclick({});
  send();
  check('F1: an empty answer is not sent', sent === null);
  K.setDraft(c.id, 'blocked', 'use the staging key');
  deck.buttons(deck.wrap(K.saySheet(sheet), K)).filter((b) => b.textContent === 'Answer and resume')[0].onclick({});
  check('F1: the answer is a resume carrying his words',
        !!sent && sent.verb === 'house.resume' && sent.id === 'c-5' && sent.said === 'use the staging key');
  const nosession = deck.card('c-6', { stage: 'building', blocked_reason: 'x', derived: { needs_you: true } });
  check('F1: a card with no session is not offered an answer',
        deck.labels(deck.wrap(K.gateActions(nosession), K)).indexOf('Answer and resume') < 0);
})();

/* ---------- F2: the phone pane is content first, then at most three actions ---------- */
function paneParts(K, c) {
  const pane = deck.wrap(K.detailPane(c), K);
  const top = pane.childNodes.filter((n) => n.nodeType === 1);
  const bar = top.filter((n) => deck.hasClass(n, 'actionbar'))[0];
  return { pane, top, bar, at: (pick) => top.findIndex(pick) };
}
function primaries(bar) { return deck.labels(bar).filter((l) => l !== 'More actions'); }
/* The desk pane's actions, every one of them: the buttons on its row, and each group's menu
   opened in turn (V2-1). The carets are the menus' own controls, not actions. */
function deskAll(K, c) {
  K.App.menu = null;
  const row = deck.wrap(K.detailPane(c), K);
  const out = deck.all(row, (n) => n.tagName === 'BUTTON' && !!n.getAttribute('data-key') &&
                                   !deck.hasClass(n, 'caret') && !deck.hasClass(n, 'close'));
  deck.all(row, (n) => !!n.getAttribute('data-menu-host')).forEach((host) => {
    K.App.menu = { id: host.getAttribute('data-menu-host') };
    const open = deck.wrap(K.detailPane(c), K);
    const menu = deck.all(open, (n) => n.getAttribute('role') === 'menu')[0];
    if (menu) deck.all(menu, (n) => n.getAttribute('role') === 'menuitem').forEach((n) => out.push(n));
  });
  K.App.menu = null;
  return out;
}
function labelsAll(nodes) { return nodes.map(deck.labelOf); }
(function () {
  const planCard = deck.card('c-7', { stage: 'planning', plan_ref: '/tmp/plan.md', session_id: 'bbbbbbbb-2222',
    brief: 'the brief of the plan card', links: { plan: '/api/artifact/x', context: '/api/artifact/y' },
    derived: { needs_you: true, plan_gate: true } });
  let K = page([planCard]);
  let p = paneParts(K, planCard);
  const plan = p.at((n) => n.getAttribute('data-key') === 'plan');
  const brief = p.at((n) => n.getAttribute('data-key') === 'brief');
  const bar = p.top.indexOf(p.bar);
  check('F2: the plan block comes before the actions on the phone', plan >= 0 && plan < bar);
  check('F2: the brief comes before the actions on the phone', brief >= 0 && brief < bar);
  check('F2: no button sits between the title and the content',
        p.top.slice(0, plan).every((n) => deck.buttons(n).every((b) => deck.hasClass(b, 'close'))));
  check('F2: a plan gate offers Open plan, Approve plan, Send back (a plan is reachable in one tap)',
        JSON.stringify(primaries(p.bar)) === JSON.stringify(['Open plan', 'Approve plan', 'Send back']));
  check('F2: the rest are behind More actions', deck.labels(p.bar).indexOf('More actions') >= 0);
  check('F2: the phone pane has no second grid of actions', deck.byClass(p.pane, 'agrid').length === 0);

  K.App.sheet = { kind: 'actions', id: planCard.id };
  const sheet = deck.wrap(K.actionsSheet(K.App.sheet), K);
  const rest = deck.labels(sheet);
  check('F2: the overflow holds the rest', ['Split', 'Edit', 'Drop in', 'Talk to this house', 'Archive'].every((l) => rest.indexOf(l) >= 0));
  check('F2: the overflow does not repeat a primary', rest.indexOf('Approve plan') < 0 && rest.indexOf('Open plan') < 0);
  check('F2: Approve with a note is under More actions', rest.indexOf('Approve with a note') >= 0);

  const inbox = deck.card('c-8', { brief: 'an idea' });
  K = page([inbox]);
  check('F2: an inbox card offers Assign, Edit, Archive',
        JSON.stringify(primaries(paneParts(K, inbox).bar)) === JSON.stringify(['Assign', 'Edit', 'Archive']));

  const blocked = deck.card('c-9', { stage: 'building', session_id: 'cccccccc-3333', blocked_reason: 'which key?',
                                     derived: { needs_you: true } });
  K = page([blocked]);
  p = paneParts(K, blocked);
  check('F2: a blocked card offers its answer, Resume house and Retry',
        JSON.stringify(primaries(p.bar)) === JSON.stringify(['Answer and resume', 'Resume house', 'Retry']));
  check('F2: the block reason comes before the actions',
        p.at((n) => n.getAttribute('data-key') === 'blocked') < p.top.indexOf(p.bar));
  check('F2: at most three primaries, always', primaries(p.bar).length <= 3);

  K = page([planCard], { desk: true });
  p = paneParts(K, planCard);
  check('F2: the desk keeps its whole action row, in groups',
        labelsAll(deskAll(K, planCard)).indexOf('Split') >= 0 && deck.labels(p.bar).indexOf('More actions') < 0);
  check('V2-1: the desk draws its actions in one row, with no second grid', deck.byClass(p.pane, 'agrid').length === 0);
})();

/* ---------- F3: Cards opens on the inbox, the Board leads More ---------- */
(function () {
  const gate = deck.card('c-10', { stage: 'planning', plan_ref: 'p.md', derived: { needs_you: true, plan_gate: true } });
  const idea = deck.card('c-11');
  let K = page([gate, idea]);
  K.App.view = 'now';
  K.go('cards');
  let body = deck.wrap(K.viewCards(), K);
  /* FS-2: the phone groups Cards by stage instead of showing one lane at a time, and the
     inbox, where triage starts, is the first heading */
  const heads = deck.byClass(body, 'fgroup-head').map((n) => n.getAttribute('data-key'));
  check('F3: the phone opens with the inbox as the first heading', heads[0] === 'g:inbox');
  check('F3: the inbox card is listed', body.textContent.indexOf('c-11') >= 0);
  check('F3: and the card at a gate is listed under its own stage', heads.indexOf('g:planning') > 0 && body.textContent.indexOf('c-10') >= 0);
  check('FS-2: the lane strip is gone', deck.byClass(body, 'lanechip').length === 0);
  check('F3: the dock is the same five', JSON.stringify(K.DOCK) === JSON.stringify(['now', 'attention', 'cards', 'segments', 'more']));
  const more = deck.wrap(K.viewMore(), K);
  const panels = deck.byClass(more, 'panel');
  check('F3: the Board is the first thing in More', panels.length > 0 && deck.labels(panels[0]).some((l) => l.indexOf('Board') === 0));
  check('F3: no empty "no extra routes" panel on personal', more.textContent.indexOf('no extra routes') < 0);
})();

/* ---------- c-519: Bosun's entry, left of the drain pill ---------- */
(function () {
  const K = page([], {}, { console: { state: 'idle', up: true, counts: { asks: 2, requests: 3 } } });
  K.renderHeader();
  const header = K._doc.getElementById('header');
  const links = deck.all(header, (n) => n.tagName === 'A' && n.getAttribute('href') === '/console');
  const pill = deck.all(header, (n) => deck.hasClass(n, 'pill') && n.tagName === 'BUTTON')[0];
  check('c-519: the header links to the Console', links.length === 1);
  const kids = Array.prototype.slice.call(header.childNodes);
  check('c-519: Bosun sits left of the drain pill', links.length === 1 && !!pill && kids.indexOf(links[0]) >= 0
        && kids.indexOf(links[0]) < kids.indexOf(pill));
  check('c-519: its name says the asks', links.length === 1 && /2 need you/.test(links[0].getAttribute('aria-label') || ''));
  const bare = page([], {}, {});
  bare.renderHeader();
  check('c-519: no console, no entry', deck.all(bare._doc.getElementById('header'),
        (n) => n.tagName === 'A' && n.getAttribute('href') === '/console').length === 0);
})();

/* ---------- F4: the services block and the header's health dot ---------- */
(function () {
  const health = { level: 'red', reasons: ['talker: stopped', 'drain: no pass in over 5 minutes'], services: [
    { name: 'talker', state: 'stopped', level: 'red', at: null },
    { name: 'voice', state: 'answering', level: 'green', at: '2026-09-24T09:59:00+00:00' },
    { name: 'drain', state: 'quiet', level: 'amber', at: '2026-09-24T09:50:00+00:00' },
    { name: 'backup', state: 'last good run', level: 'green', at: '2026-09-24T08:00:00+00:00' }] };
  const K = page([], {}, { health });
  K.renderHeader();
  const header = K._doc.getElementById('header');
  const pill = deck.all(header, (n) => deck.hasClass(n, 'pill') && n.tagName === 'BUTTON')[0];
  check('F4: the drain pill is the one health control', !!pill);
  check('F4: no separate health box in the header', deck.all(header, (n) => deck.hasClass(n, 'healthdot')).length === 0);
  check('F4: the pill wears the verdict', !!pill && deck.hasClass(pill, 'h-red'));
  /* on the phone the pill is its dot alone (c-519) and the word lives in its name */
  check('F4: the pill keeps its drain word', !!pill && (/drain/.test(pill.textContent)
        || (deck.hasClass(pill, 'dotonly') && /drain/.test(pill.getAttribute('aria-label') || ''))));
  check('F4: the pill says the verdict in words',
        !!pill && /red/.test(pill.getAttribute('aria-label') || '') && /talker: stopped/.test(pill.getAttribute('aria-label') || ''));
  const dot = pill;
  K.renderSheet = function () {};
  if (dot) dot.onclick({ stopPropagation() {} });
  check('F4: a tap opens the services sheet', K.App.sheet && K.App.sheet.kind === 'health');
  const sheet = deck.wrap(K.healthSheet(K.App.sheet), K).textContent;
  check('F4: the sheet says the reasons', sheet.indexOf('talker: stopped') >= 0 && sheet.indexOf('drain: no pass in over 5 minutes') >= 0);
  check('F4: the sheet lists the four services', ['talker', 'voice', 'drain', 'backup'].every((n) => sheet.indexOf(n) >= 0));
  check('F4: each service says its state and its age', sheet.indexOf('quiet') >= 0 && sheet.indexOf('10m') >= 0 && sheet.indexOf('2h') >= 0);
  const now = deck.wrap(K.viewNow(), K);
  check('F4: Now carries the services block', deck.byClass(now, 'services').length === 1);
  K.App.health = { level: 'green', reasons: [], services: [] };
  K.renderHeader();
  const later = deck.all(K._doc.getElementById('header'), (n) => deck.hasClass(n, 'pill') && n.tagName === 'BUTTON')[0];
  check('F4: a verdict fetched on its own wins over the state document\'s', !!later && deck.hasClass(later, 'h-green'));
})();

/* ---------- a notice's pane says its brief once ---------- */
(function () {
  const n = deck.card('c-12', { brief: 'the nightly pull is stale', options: { notice_key: 'k' }, derived: { needs_you: true, notice: true } });
  for (const desk of [false, true]) {
    const K = page([n], { desk });
    const text = deck.wrap(K.detailPane(n), K).textContent;
    check('F6: the notice pane draws its brief once (' + (desk ? 'desk' : 'phone') + ')',
          text.split('the nightly pull is stale').length === 2);
  }
})();

/* ---------- review: a dismissed notice is not offered Dismiss again ---------- */
(function () {
  const n = deck.card('c-13', { brief: 'x', options: { notice_key: 'k', archived: true }, derived: { notice: true, archived: true } });
  const K = page([n]);
  check('F6: a dismissed notice offers no Dismiss', deck.labels(deck.wrap(K.gateActions(n), K)).indexOf('Dismiss') < 0);
  const bar = deck.wrap(K.detailPane(n), K);
  check('F6: a dismissed notice reads as an inbox card on the phone', deck.labels(bar).indexOf('Unarchive') >= 0);
})();

/* ---------- c-302 x F2: a big card's phone pane is its tree first, Assign tree a primary ---------- */
(function () {
  const node = (id, step, extra) => Object.assign({ id, title: id + ' title', stage: 'inbox', step, next: false,
    after: [], waiting_for: [], unblocks: 0, blocked: false }, extra || {});
  const tree = { unassigned: 2, follow_ups: [], steps: [
    { step: 1, cards: [node('c-21', 1, { unblocks: 1 })] },
    { step: 2, cards: [node('c-22', 2, { after: ['c-21'], waiting_for: ['c-21'] })] }] };
  const big = deck.card('c-20', { stage: 'building', children: ['c-21', 'c-22'], brief: 'the big one',
    derived: { tracking: true, parent_stage: 'building', tree } });
  const kids = [deck.card('c-21', { parent: 'c-20' }), deck.card('c-22', { parent: 'c-20' })];
  let K = page([big].concat(kids));
  const p = paneParts(K, big);
  const treeAt = p.at((n) => n.getAttribute('data-key') === 'tree');
  check('T: the tree leads the phone pane, above the actions', treeAt >= 0 && treeAt < p.top.indexOf(p.bar));
  check('T: Assign tree is a primary for a big card', primaries(p.bar)[0] === 'Assign tree (2)');
  check('T: the tree head does not repeat Assign tree on the phone',
        deck.labels(p.top[treeAt]).every((l) => l.indexOf('Assign tree') < 0));
  check('T: at most three primaries', primaries(p.bar).length <= 3);
  K = page([big].concat(kids), { desk: true });
  const desk = deck.wrap(K.detailPane(big), K);
  check('T: the desk keeps Assign tree in the tree head',
        deck.labels(deck.all(desk, (n) => n.getAttribute('data-key') === 'tree')[0]).indexOf('Assign tree (2)') >= 0);
  const queued = deck.card('c-23', { stage: 'assigned', rank: 1 });
  K = page([queued]);
  K.App.sheet = { kind: 'actions', id: 'c-23' };
  const rest = deck.labels(deck.wrap(K.actionsSheet(K.App.sheet), K));
  check('T: Move to front of queue is under More actions',
        rest.indexOf('Move to front of queue') >= 0 && primaries(paneParts(K, queued).bar).indexOf('Move to front of queue') < 0);
})();


/* ---------- P2-5: the plan and the outcome are pages of their own, opened in a new tab ---------- */
(function () {
  const c = deck.card('c-31', { plan_ref: '/x/plan.md',
                                links: { context: '/api/artifact/y', formats: { plan: true, outcome: true } } });
  for (const desk of [false, true]) {
    const K = page([c], { desk: desk });
    const opened = [];
    K._win.open = function (url, target) { opened.push([url, target]); };
    const plan = K.planLink(c);
    check('P2-5: a markdown plan opens /plan/<id>', plan && plan.url === '/plan/c-31');
    K.openPlan(plan.url);
    check('P2-5: Open plan is a new tab (' + (desk ? 'desk' : 'phone') + ')',
      opened.length === 1 && opened[0][0] === '/plan/c-31' && opened[0][1] === '_blank');
    check('P2-5: View context is the outcome page', K.contextLink(c) === '/outcome/c-31');
  }
})();

/* ---------- P4-2: only a document in the format opens on the new pages ---------- */
(function () {
  const old = deck.card('c-32', { plan_ref: '/x/plan.md',
                                  links: { plan: '/api/artifact/p', context: '/api/artifact/y',
                                           formats: { plan: false, outcome: false } } });
  const K = page([old], { desk: true });
  check('P4-2: a markdown plan without frontmatter keeps its markdown pane',
        K.planLink(old).url === '/api/artifact/p');
  /* c-644: a record without frontmatter is the viewer's Context page, drawn as markdown */
  check('c-644: a record without frontmatter opens as the viewer\'s Context page',
        K.contextLink(old) === '/context/c-32');
  const lavish = deck.card('c-33', { plan_ref: '/x/plan.html', links: { plan_live: '/session/k/',
                                     plan: '/api/artifact/h', formats: { plan: false } } });
  check('P4-2: a lavish plan keeps its live surface', K.planLink(lavish).url === '/session/k/');
  const pushed = deck.card('c-34', { plan_ref: '/x/plan.md', links: { plan: '/host/mac/api/artifact/p' } });
  check('P4-2: a push from a machine on older code (no formats) opens the old way',
        K.planLink(pushed).url === '/host/mac/api/artifact/p');
})();

/* ---------- P4-5: the row and Attention say what a format plan asks ---------- */
(function () {
  const c = deck.card('c-35', { stage: 'planning', plan_ref: '/x/plan.md',
    derived: { plan_gate: true, needs_you: true },
    links: { formats: { plan: true } },
    plan_doc: { doc: 'plan', decisions: 4, questions: 1, changed: 1, notes: 2, asks_open: 1, replies: 1,
                ok: false, breaks: 2 } });
  for (const desk of [false, true]) {
    const K = page([c], { desk: desk });
    const row = deck.wrap(K.wordsRow(c, true), K).textContent;
    check('P4-5: the row counts the round (' + (desk ? 'desk' : 'phone') + ')',
          row.indexOf('4 decisions, 1 changed · 1 question · 2 notes · 1 reply waiting · 1 ask open') >= 0);
    check('P4-5: the row says the contract breaks', row.indexOf('2 breaks') >= 0);
    const att = deck.wrap(K.viewAttention(), K).textContent;
    check('P4-5: Attention counts the round (' + (desk ? 'desk' : 'phone') + ')',
          att.indexOf('4 decisions, 1 changed') >= 0 && att.indexOf('2 breaks') >= 0);
  }
  const held = deck.card('c-36', { stage: 'planning', derived: { plan_gate: true },
    plan_doc: { doc: 'plan', decisions: 0, questions: 0, changed: 0, notes: 0, asks_open: 0, replies: 0, ok: true, breaks: 0 } });
  const K = page([held]);
  const row = deck.wrap(K.wordsRow(held, true), K).textContent;
  check('P4-5: a plan with nothing to ask says only that the contract holds',
        row.indexOf('contract holds') >= 0 && row.indexOf('decision') < 0);
  const none = deck.card('c-37', { stage: 'planning', derived: { plan_gate: true } });
  check('P4-5: a card with no format plan draws no round word', K.roundWord(none) === null && K.contractWord(none) === null);
})();

/* ---------- U1, U2, U3: one name per verb, a line on every action, a card in a terminal ---------- */
(function () {
  const exited = deck.card('c-30', { stage: 'building', session_id: 'dddddddd-4444', blocked_reason: 'exited twice',
                                     derived: { needs_you: true } });
  let K = page([exited], { desk: true });
  let pane = deck.wrap(K.detailPane(exited), K);
  const every = deskAll(K, exited);
  const labels = labelsAll(every);
  check('U1: Resume house is drawn once on a blocked card', labels.filter((l) => l === 'Resume house').length === 1);
  check('U1: no bare Resume', labels.indexOf('Resume') < 0);
  check('U1: Unblock only', labels.indexOf('Unblock only') >= 0 && labels.indexOf('Unblock') < 0);
  const keyed = every;
  const bare = keyed.filter((n) => !n.getAttribute('title')).map((n) => n.getAttribute('data-key'));
  check('U2: every keyed action on the desk pane has a hover line (' + bare.join(',') + ')', keyed.length > 6 && bare.length === 0);
  check('U2: no action carries an aria-label for its line', keyed.every((n) => !n.getAttribute('aria-label')));
  const drop = keyed.filter((n) => n.getAttribute('data-key') === 'dropin')[0];
  check('U2: Drop in on an exited house says it resumes it',
        !!drop && drop.getAttribute('title').indexOf('The house has exited') >= 0);
  const fresh = deck.card('c-31', { stage: 'inbox' });
  K = page([fresh], { desk: true });
  const freshDrop = deskAll(K, fresh).filter((n) => n.getAttribute('data-key') === 'dropin')[0];
  check('U2: Drop in with no session says it opens a fresh one',
        !!freshDrop && freshDrop.getAttribute('title').indexOf('No session on this card yet') >= 0);

  const until = new Date(Date.now() + 10 * 60 * 1000).toISOString();
  const held = deck.card('c-32', { stage: 'building', session_id: 'eeeeeeee-5555',
                                   options: { dropin_hold: { until: until, seen: false } } });
  K = page([held], { desk: true });
  pane = deck.wrap(K.detailPane(held), K);
  const heldLabels = labelsAll(deskAll(K, held));
  check('U3: a card he dropped into says so', pane.textContent.indexOf('in a terminal') >= 0);
  check('U3: and draws no resume of any kind', heldLabels.indexOf('Resume house') < 0 && heldLabels.indexOf('Answer and resume') < 0);
  const term = deck.card('c-33', { stage: 'building', session_id: 'ffffffff-6666',
                                   house: { kind: 'interactive', status: 'idle', bg_id: null } });
  K = page([term], { desk: true });
  const termLabels = labelsAll(deskAll(K, term));
  check('U3: a session in his terminal gets no Logs or Stop', termLabels.indexOf('Logs') < 0 && termLabels.indexOf('Stop session') < 0);

  K = page([exited]);
  const phone = paneParts(K, exited);
  check('U1: the phone row is the same three, by key',
        JSON.stringify(primaries(phone.bar)) === JSON.stringify(['Answer and resume', 'Resume house', 'Retry']));
})();

/* ---------- V2-1 and V2-3: the card's actions in groups ---------- */
function keyOf(n) { return n.getAttribute('data-key'); }
function hosts(node) { return deck.all(node, (n) => !!n.getAttribute('data-menu-host')); }
function rowOf(K, c) { return deck.wrap(K.detailPane(c), K).childNodes.filter((n) => deck.hasClass(n, 'actionbar'))[0]; }
(function () {
  const planCard = deck.card('c-40', { stage: 'planning', plan_ref: '/tmp/plan.md', session_id: 'bbbbbbbb-2222',
    links: { plan: '/api/artifact/x', context: '/api/artifact/y' }, derived: { needs_you: true, plan_gate: true } });
  const K = page([planCard], { desk: true });
  const row = rowOf(K, planCard);
  const groups = hosts(row);
  check('V2-1: the plan gate row leads with the Decide group', groups.length > 0 && groups[0].getAttribute('aria-label') === 'Decide');
  const decide = groups[0];
  const main = deck.buttons(decide)[0];
  check('V2-1: Approve plan is the group\'s button, and the primary', deck.labelOf(main) === 'Approve plan' && deck.hasClass(main, 'primary'));
  const caret = deck.byClass(decide, 'caret')[0];
  check('V2-1: the caret is a menu button', !!caret && caret.getAttribute('aria-haspopup') === 'menu' &&
        caret.getAttribute('aria-expanded') === 'false' && !!caret.getAttribute('aria-label'));
  check('V2-1: no menu is drawn while it is shut', deck.all(row, (n) => n.getAttribute('role') === 'menu').length === 0);

  /* the keyboard: ArrowDown on the caret opens it, Escape closes it */
  K.renderBody = function () {};
  caret.onkeydown({ key: 'ArrowDown', preventDefault() {} });
  const id = decide.getAttribute('data-menu-host');
  check('V2-3: ArrowDown on the caret opens its menu', !!K.App.menu && K.App.menu.id === id);
  const open = rowOf(K, planCard);
  const menu = deck.all(open, (n) => n.getAttribute('role') === 'menu')[0];
  const openCaret = deck.all(open, (n) => n.getAttribute('data-caret') === id)[0];
  check('V2-3: the open caret says so', !!openCaret && openCaret.getAttribute('aria-expanded') === 'true' &&
        openCaret.getAttribute('aria-controls') === id);
  const entries = menu ? deck.all(menu, (n) => n.getAttribute('role') === 'menuitem') : [];
  check('V2-3: the menu holds the rest of Decide', JSON.stringify(entries.map(deck.labelOf)) ===
        JSON.stringify(['Approve with a note', 'Send back']));
  check('V2-3: every entry shows its line under its name', entries.length > 0 && entries.every((n) => {
    const line = deck.byClass(n, 'mdesc')[0];
    return !!line && line.textContent === K.lineUnder(keyOf(n), planCard) && line.textContent.length > 20;
  }));
  check('V2-3: the line is lane U\'s, without the name above it',
        entries.some((n) => deck.byClass(n, 'mdesc')[0].textContent.indexOf('The same approve, with your words') === 0));
  check('V2-3: the entry\'s name is its accessible name, the line its description', entries.every((n) =>
        n.getAttribute('aria-labelledby') && n.getAttribute('aria-describedby') && !n.getAttribute('aria-label')));
  let stopped = false;
  menu.onkeydown({ key: 'ArrowDown', currentTarget: menu, preventDefault() {}, stopPropagation() {} });
  menu.onkeydown({ key: 'Escape', currentTarget: menu, preventDefault() {}, stopPropagation() { stopped = true; } });
  check('V2-3: Escape closes the menu and goes no further', K.App.menu === null && stopped);
  K.openMenu(id);
  menu.onkeydown({ key: 'Tab', currentTarget: menu, preventDefault() {}, stopPropagation() {} });
  check('V2-3: Tab closes the menu', K.App.menu === null);
})();

/* every group's button is legal for the states that draw it, and the primary is never in a menu */
(function () {
  const cases = [
    deck.card('c-41', { stage: 'planning', plan_ref: 'p.md', session_id: 'aaaaaaaa-1', links: { plan: '/x', context: '/y' },
                        derived: { needs_you: true, plan_gate: true } }),
    deck.card('c-42', { stage: 'review', output_ref: 'o', session_id: 'aaaaaaaa-2', links: { output: '/o', context: '/y' },
                        derived: { needs_you: true, outcome_gate: true } }),
    deck.card('c-43', { stage: 'building', session_id: 'aaaaaaaa-3', blocked_reason: 'which key?', derived: { needs_you: true } }),
    deck.card('c-44', { stage: 'building', blocked_reason: 'no model', derived: { needs_you: true } }),
    deck.card('c-45', { brief: 'n', options: { notice_key: 'k' }, derived: { needs_you: true, notice: true } }),
    deck.card('c-46', { brief: 'an idea' }),
    deck.card('c-47', { stage: 'building', session_id: 'aaaaaaaa-7', links: { context: '/y' }, options: { app_link: 'https://claude.ai/code/x' },
                        house: { kind: 'background', status: 'idle', bg_id: 'aaaaaaaa' } }),
    deck.card('c-48', { stage: 'building', session_id: 'aaaaaaaa-8', links: { context: '/y' } }),
    deck.card('c-49', { stage: 'building', session_id: 'aaaaaaaa-9', house: { kind: 'background', status: 'busy', bg_id: 'aaaaaaaa' } })
  ];
  for (const c of cases) {
    const K = page([c], { desk: true });
    const drawn = K.gateActions(c).concat(K.cardItems(c)).filter((n) => ['on-voice', 'in-terminal'].indexOf(keyOf(n)) < 0);
    const unplaced = drawn.filter((n) => !K.groupOf(keyOf(n))).map(keyOf);
    check('V2-3: every drawn key is in a group (' + c.id + ': ' + unplaced.join(',') + ')', unplaced.length === 0);
    const once = drawn.every((n) => K.GROUPS.filter((g) => g.keys.indexOf(keyOf(n).indexOf('verb-') === 0 ? 'verb' : keyOf(n)) >= 0).length === 1);
    check('V2-3: and in exactly one (' + c.id + ')', once);
    const row = rowOf(K, c);
    const drawnKeys = drawn.map(keyOf);
    K.grouped(c, drawn).forEach((x) => {
      const want = x.nodes[0];
      const host = hosts(row).filter((h) => h.getAttribute('aria-label') === x.group.name)[0];
      const shown = host ? deck.buttons(host)[0] : deck.buttons(row).filter((b) => keyOf(b) === keyOf(want))[0];
      check('V2-3: ' + c.id + ' ' + x.group.name + '\'s button is an action the card draws',
            !!shown && drawnKeys.indexOf(keyOf(shown)) >= 0 && keyOf(shown) === keyOf(want));
    });
    /* the GATE's primary: a notice at inbox also has Assign in the accent, which is the
       card's, and it may sit behind Dismiss in Card's menu */
    const primary = K.gateActions(c).filter((n) => deck.hasClass(n, 'primary')).map(keyOf);
    const onRow = deck.buttons(row).filter((b) => !deck.hasClass(b, 'caret')).map(keyOf);
    check('V2-1: ' + c.id + '\'s gate primary is on the row, never in a menu (' + primary.join(',') + ')',
          primary.every((k) => onRow.indexOf(k) >= 0));
    check('V2-1: ' + c.id + ' draws each group once at most', hosts(row).length <= K.GROUPS.length);
  }
  const blocked = cases[2];
  const K = page([blocked], { desk: true });
  const cont = hosts(rowOf(K, blocked)).filter((h) => h.getAttribute('aria-label') === 'Continue')[0];
  check('V2-1: a blocked house leads Continue with Answer and resume', !!cont && deck.labelOf(deck.buttons(cont)[0]) === 'Answer and resume');
  const review = page([cases[1]], { desk: true });
  /* c-644: Read is Pages (the card's own, in its viewer) and Links (what leaves the card) */
  const links = hosts(rowOf(review, cases[1])).filter((h) => h.getAttribute('aria-label') === 'Links')[0];
  /* the groups as the row draws them, read from the table (no fallback that always passes) */
  function lead(Kx, c, key) {
    const x = Kx.grouped(c, Kx.gateActions(c).concat(Kx.cardItems(c))).filter((y) => y.group.key === key)[0];
    return x ? keyOf(x.nodes[0]) : null;
  }
  check('V2-1, c-644: at review Links leads with the output', lead(review, cases[1], 'links') === 'open-output');
  /* c-644: Pages leads with what the stage is about */
  const planning = page([cases[0]], { desk: true });
  check('c-644: while planning Pages leads with the plan', lead(planning, cases[0], 'pages') === 'open-plan');
  const built = page([cases[7]], { desk: true });
  check('c-644: while building Pages leads with the context', lead(built, cases[7], 'pages') === 'context');
  const shipped = deck.card('c-51', { stage: 'shipping', repo: 'api', session_id: 'aaaaaaaa-5', links: { context: '/y', plan: '/x' },
    options: { shipping: { told: [{ handle: 'c1', batch: 1 }], posted: {}, local: {}, facts: {} } } });
  const ship = page([shipped], { desk: true });
  check('c-644: at shipping Pages leads with the comments', lead(ship, shipped, 'pages') === 'open-comments');
  const finished = deck.card('c-52', { stage: 'done', links: { context: '/y', plan: '/x' } });
  const fin = page([finished], { desk: true });
  check('c-644: when done Pages leads with the context', lead(fin, finished, 'pages') === 'context');
  /* r2.F8: a done card whose house answered review keeps Open comments among its Pages */
  const answered = deck.card('c-53', { stage: 'done', links: { context: '/y' },
    options: { shipping: { told: [{ handle: 'c1', batch: 1 }], posted: { c1: 'd' } } } });
  const ans = page([answered], { desk: true });
  const pagesOf = (Kx, c) => (Kx.grouped(c, Kx.gateActions(c).concat(Kx.cardItems(c))).filter((y) => y.group.key === 'pages')[0] || { nodes: [] }).nodes.map(keyOf);
  check('c-644: a done card keeps Open comments: ' + pagesOf(ans, answered).join(), pagesOf(ans, answered).indexOf('open-comments') >= 0);
  check('c-644: one never told has none', pagesOf(fin, finished).indexOf('open-comments') < 0);
  /* r2.F1: the split button names its group where it can be seen, so View context under the
     caret of "Open plan" reads as one of the card's Pages, never as the plan's */
  const planned = deck.card('c-54', { stage: 'planning', plan_ref: 'p.md', links: { plan: '/x', context: '/y' } });
  const pl = page([planned], { desk: true });
  const pagesHost = hosts(rowOf(pl, planned)).filter((h) => h.getAttribute('aria-label') === 'Pages')[0];
  const caret = pagesHost ? deck.buttons(pagesHost).filter((b) => deck.hasClass(b, 'caret'))[0] : null;
  check('c-644: the Pages split button shows its name: ' + (caret ? caret.textContent : 'none'),
        !!caret && caret.textContent.indexOf('Pages') >= 0 && deck.labelOf(deck.buttons(pagesHost)[0]) === 'Open plan');
  const building = page([cases[7]], { desk: true });
  const single = deck.buttons(rowOf(building, cases[7])).filter((b) => keyOf(b) === 'context')[0];
  check('V2-1: a group with one live action is a plain button', !!single &&
        !hosts(rowOf(building, cases[7])).some((h) => h.getAttribute('aria-label') === 'Pages'));
})();

/* the phone's More sheet is grouped under the desk's headings, with the same lines */
(function () {
  const c = deck.card('c-50', { stage: 'planning', plan_ref: '/tmp/plan.md', session_id: 'bbbbbbbb-2222',
    links: { plan: '/api/artifact/x', context: '/api/artifact/y' }, derived: { needs_you: true, plan_gate: true } });
  let K = page([c]);
  K.App.sheet = { kind: 'actions', id: c.id };
  const sheet = deck.wrap(K.actionsSheet(K.App.sheet), K);
  const secs = deck.byClass(sheet, 'gsec');
  const heads = secs.map((s) => deck.byClass(s, 'ghead')[0].textContent);
  const order = K.GROUPS.map((g) => g.name);
  check('V2-3: the More sheet has group headings in the desk\'s order (' + heads.join(',') + ')',
        heads.length >= 3 && heads.every((h, i) => i === 0 || order.indexOf(h) > order.indexOf(heads[i - 1])));
  const desk = page([c], { desk: true });
  const deskGroup = {};
  hosts(rowOf(desk, c)).forEach((h) => {
    desk.App.menu = { id: h.getAttribute('data-menu-host') };
    const open = hosts(rowOf(desk, c)).filter((x) => x.getAttribute('data-menu-host') === h.getAttribute('data-menu-host'))[0];
    deck.buttons(open).filter((b) => !deck.hasClass(b, 'caret')).forEach((b) => { deskGroup[keyOf(b)] = h.getAttribute('aria-label'); });
  });
  desk.App.menu = null;
  deck.buttons(rowOf(desk, c)).filter((b) => !b.parentNode.getAttribute('data-menu-host') && keyOf(b))
    .forEach((b) => { deskGroup[keyOf(b)] = desk.groupOf(keyOf(b)).name; });
  let same = true;
  secs.forEach((s) => {
    const head = deck.byClass(s, 'ghead')[0].textContent;
    deck.buttons(s).forEach((b) => { if (deskGroup[keyOf(b)] !== head) same = false; });
  });
  check('V2-3: every action in the sheet sits under the group the desk puts it in', same);
  check('V2-3: every action in the sheet shows its line', deck.buttons(sheet).filter((b) => keyOf(b)).every((b) =>
        deck.byClass(b, 'mdesc').length === 1 && deck.byClass(b, 'mdesc')[0].textContent === K.lineUnder(keyOf(b), c)));
  check('V2-3: the phone keeps its three by key', JSON.stringify(primaries(paneParts(K, c).bar)) ===
        JSON.stringify(['Open plan', 'Approve plan', 'Send back']));
})();

/* ---------- V2-2: Resume and open in app ---------- */
(function () {
  const exited = deck.card('c-60', { stage: 'building', session_id: 'aaaaaaaa-60', links: { context: '/y' } });
  let K = page([exited], { desk: true });
  const keys = deskAll(K, exited).map(keyOf);
  check('V2-2: an exited house offers Resume and open in app', keys.indexOf('resume-app') >= 0);
  check('V2-2: it is in Continue', K.groupOf('resume-app').key === 'continue');
  const btn = deskAll(K, exited).filter((n) => keyOf(n) === 'resume-app')[0];
  check('V2-2: its hover line is the brief\'s', !!btn && btn.getAttribute('title') ===
        'Resume and open in app: brings the house back idle, with no turn, and opens it in the Claude app so you can type to it.');
  check('V2-2: its menu line starts as the brief says', K.lineUnder('resume-app', exited) ===
        'Brings the house back idle, with no turn, and opens it in the Claude app so you can type to it.');
  /* the tab is opened on the tap and pointed at the link the server answers with */
  const tab = { location: { href: '' }, opener: 'x', closed: false, close() { this.closed = true; } };
  let opened = 0, sent = null;
  K._win.open = function () { opened += 1; return tab; };
  K.act = function (body, done) { sent = body; const said = done({ link: 'https://claude.ai/code/s1', woken: true });
    K._said = said; return Promise.resolve({ link: 'https://claude.ai/code/s1' }); };
  btn.onclick({ stopPropagation() {}, currentTarget: btn });
  check('V2-2: the tap opens a tab first, then sends the verb', opened === 1 && !!sent && sent.verb === 'house.open_app' && sent.id === 'c-60');
  check('V2-2: the tab goes to the link', tab.location.href === 'https://claude.ai/code/s1' && tab.opener === null);
  K.act = function (body, done) { K._said = done({ link: null, note: 'no link yet; the house is awake' }); return Promise.resolve({}); };
  const tab2 = { location: { href: '' }, closed: false, close() { this.closed = true; } };
  K._win.open = function () { return tab2; };
  btn.onclick({ stopPropagation() {}, currentTarget: btn });
  check('V2-2: no link closes the tab and says so in one line', tab2.closed && K._said && K._said.err && /awake/.test(K._said.text));

  const listed = deck.card('c-61', { stage: 'building', session_id: 'aaaaaaaa-61', options: { app_link: 'https://claude.ai/code/x' },
                                     house: { kind: 'background', status: 'idle', bg_id: 'aaaaaaaa' } });
  const busy = deck.card('c-62', { stage: 'building', session_id: 'aaaaaaaa-62', house: { kind: 'background', status: 'busy', bg_id: 'aaaaaaaa' } });
  const until = new Date(Date.now() + 10 * 60 * 1000).toISOString();
  const held = deck.card('c-63', { stage: 'building', session_id: 'aaaaaaaa-63', options: { dropin_hold: { until: until } } });
  const none = deck.card('c-65', { stage: 'building' });
  for (const [c, why] of [[listed, 'a listed house whose link the card has (Open in Claude app does it)'],
                          [busy, 'a working house'], [held, 'a house held in his terminal'],
                          [none, 'a card with no session']]) {
    K = page([c], { desk: true });
    check('V2-2: not drawn for ' + why, deskAll(K, c).map(keyOf).indexOf('resume-app') < 0);
  }
  const listedNoLink = deck.card('c-66', { stage: 'building', session_id: 'aaaaaaaa-66', house: { kind: 'background', status: 'idle', bg_id: 'aaaaaaaa' } });
  K = page([listedNoLink], { desk: true });
  check('V2-2: drawn for a listed idle house whose card has no link', deskAll(K, listedNoLink).map(keyOf).indexOf('resume-app') >= 0);
})();

/* ---------- V2-1 on Now: a tile with more than two actions groups them ---------- */
(function () {
  const blocked = deck.card('c-70', { stage: 'building', session_id: 'aaaaaaaa-70', blocked_reason: 'exited twice',
                                      derived: { needs_you: true } });
  let K = page([blocked], { desk: true });
  let tile = deck.wrap(K.houseActions(blocked), K);
  const host = hosts(tile)[0];
  check('V2-1: a blocked tile draws Continue as one split button', hosts(tile).length === 1 && !!host &&
        host.getAttribute('aria-label') === 'Continue' && deck.labelOf(deck.buttons(host)[0]) === 'Resume house');
  check('V2-1: the tile\'s caret is a menu button', deck.byClass(tile, 'caret').length === 1);
  K = page([blocked]);
  K.renderSheet = function () {};
  tile = deck.wrap(K.houseActions(blocked), K);
  deck.byClass(tile, 'caret')[0].onclick({ stopPropagation() {} });
  check('V2-1: on the phone the tile\'s caret opens a sheet', !!K.App.sheet && K.App.sheet.kind === 'menu');
  const sheet = deck.wrap(K.menuSheet(K.App.sheet), K);
  check('V2-1: the sheet lists the rest of Continue with their lines',
        JSON.stringify(deck.labels(sheet).filter((l) => l.indexOf('close') < 0)) === JSON.stringify(['Resume and open in app', 'Retry']) &&
        deck.byClass(sheet, 'mdesc').length === 2 && deck.byClass(sheet, 'ghead')[0].textContent === 'Continue');
  const four = deck.card('c-71', { stage: 'planning', session_id: 'aaaaaaaa-71',
                                   options: { app_link: 'https://claude.ai/code/x', discussion: true },
                                   house: { kind: 'background', status: 'busy', bg_id: 'aaaaaaaa' } });
  K = page([four], { desk: true });
  const grouped = deck.wrap(K.houseActions(four), K);
  check('V2-1: a talking tile\'s four actions are three controls, Stop behind End discussion',
        deck.buttons(grouped).filter((b) => !deck.hasClass(b, 'caret')).map(deck.labelOf).join(',') === 'Open in app,Logs,End discussion' &&
        hosts(grouped).length === 1 && hosts(grouped)[0].getAttribute('aria-label') === 'Card');
  const pair = deck.card('c-72', { stage: 'building', session_id: 'aaaaaaaa-72',
                                   house: { kind: 'background', status: 'busy', bg_id: 'aaaaaaaa' } });
  K = page([pair], { desk: true });
  const two = deck.wrap(K.houseActions(pair), K);
  check('V2-1: two actions stay two plain buttons', hosts(two).length === 0 && deck.labels(two).join(',') === 'Logs,Stop');
})();

/* ---------- a review card's actions make sense for a review (2026-09-24) ---------- */
function rv(id, state, extra) {
  const o = extra || {};
  const stage = { waiting: 'inbox', reviewing: 'building', gate: 'review', posted: 'done', 'new': 'done' }[state];
  return deck.card(id, Object.assign({ space: 'work', repo: 'api', stage, title: 'Review: invented change ' + id,
    autonomy: 'autonomous',
    options: Object.assign({ review_key: 'api:' + id.slice(2), kind: 'review', slot: 'review', pr: Number(id.slice(2)),
                             review_pr: { author: 'Ana Example', created: '2026-09-22T09:00:00+00:00' } }, o.options || {}),
    links: Object.assign({ pr: 'https://example.invalid/pr/' + id }, o.links || {}),
    derived: Object.assign({ review: state, needs_you: state === 'gate', outcome_gate: state === 'gate' }, o.derived || {}) },
    o.rest || {}));
}
function groupMain(K, c, name) {
  const host = hosts(rowOf(K, c)).filter((h) => h.getAttribute('aria-label') === name)[0];
  return host ? deck.labelOf(deck.buttons(host)[0]) : null;
}
(function () {
  const idle = { kind: 'background', status: 'idle', bg_id: 'aaaaaaaa' };
  const inbox = rv('c-721', 'waiting');
  const reviewing = rv('c-722', 'reviewing', { rest: { session_id: 'aaaaaaaa-22', house: idle },
    options: { app_link: 'https://claude.ai/code/x' }, links: { context: '/y' } });
  const gate = rv('c-723', 'gate', { rest: { session_id: 'aaaaaaaa-23', output_ref: '/o', house: idle },
    links: { output: '/o', context: '/y' } });
  const posted = rv('c-724', 'posted', { rest: { session_id: 'aaaaaaaa-24', output_ref: '/o' }, links: { output: '/o' },
    options: { review_posted: { head: 'h1', verdict: 'changes' } } });
  const fresh = rv('c-725', 'new', { rest: { session_id: 'aaaaaaaa-25', output_ref: '/o' }, links: { output: '/o' },
    options: { review_posted: { head: 'h1' }, review_new: { head: 'h2' } } });
  const closed = rv('c-726', 'waiting', { options: { notice_key: 'review:api:726', review_closed: 'merged' },
    derived: { review: 'closed', notice: true, needs_you: true } });
  const dismissed = rv('c-727', 'waiting', { derived: { archived: true } });
  const queued = rv('c-728', 'reviewing', { rest: { stage: 'assigned' } });
  const all = [inbox, reviewing, gate, posted, fresh, closed, dismissed, queued];
  const K = page(all, { desk: true });
  K.App.space = 'work';
  const keys = (c) => deskAll(K, c).map(keyOf);
  const labels = (c) => labelsAll(deskAll(K, c));
  const houseKeys = ['dropin', 'talk-voice', 'open-app', 'resume-house', 'resume-app', 'rotate'];
  all.forEach((c) => check('RV-3: ' + c.id + ' offers no Split', keys(c).indexOf('split') < 0));
  all.forEach((c) => check('RV-3: ' + c.id + ' offers no Edit (its fields come from its pull request)', keys(c).indexOf('edit') < 0));
  [inbox, queued, posted, fresh].forEach((c) => check('RV-3: ' + c.id + ' offers Review settings', labels(c).indexOf('Review settings') >= 0));
  [reviewing, gate, closed, dismissed].forEach((c) => check('RV-3: ' + c.id + ' offers no Review settings', keys(c).indexOf('review-settings') < 0));
  check('RV-3: Review settings says what it holds', K.lineUnder('review-settings', inbox) ===
        'The model this review runs on, and an optional focus note for the reviewer.');

  check('RV-3 inbox: Review is the Card group\'s button', groupMain(K, inbox, 'Card') === 'Review');
  check('RV-3 inbox: with Open PR and Dismiss review', labels(inbox).indexOf('Open PR') >= 0 && labels(inbox).indexOf('Dismiss review') >= 0);
  check('RV-3 inbox: no house actions before the review starts', houseKeys.every((k) => keys(inbox).indexOf(k) < 0));
  check('RV-3: Dismiss review says what it does', K.tip('archive', inbox) ===
        'Dismiss review: hides this review. It is not filed again unless the pull request gets new activity.' &&
        K.lineUnder('archive', inbox) === 'Hides this review. It is not filed again unless the pull request gets new activity.');
  check('RV-3: an ordinary card still says Archive', K.tip('archive', deck.card('c-799')).indexOf('Archive: ') === 0);

  check('RV-3 reviewing: the usual Continue and Talk to it', ['dropin', 'talk-voice', 'resume-house'].every((k) => keys(reviewing).indexOf(k) >= 0));
  check('RV-3 reviewing: Talk to it is a group of its own', hosts(rowOf(K, reviewing)).some((h) => h.getAttribute('aria-label') === 'Talk to it'));

  check('RV-3 gate: Approve (it posts) is Decide\'s button', groupMain(K, gate, 'Decide') === 'Approve' &&
        /posts/.test(K.tip('approve-outcome', gate)) && K.tip('approve-outcome', gate).indexOf('Approve: ') === 0);
  check('RV-3 gate: with Send back', keys(gate).indexOf('sendback') >= 0);
  check('RV-3 gate: the page (where Ask is) leads Links', groupMain(K, gate, 'Links') === 'Open output' ||
        deck.labels(rowOf(K, gate)).indexOf('Open output') >= 0);
  check('RV-3 gate: no house actions at the gate', houseKeys.every((k) => keys(gate).indexOf(k) < 0));

  check('RV-3 posted: Open PR leads Links', groupMain(K, posted, 'Links') === 'Open PR');
  check('RV-3 posted: no Re-review without new commits', keys(posted).indexOf('rereview') < 0);
  check('RV-3 posted: no house actions after posting', houseKeys.every((k) => keys(posted).indexOf(k) < 0));
  check('RV-3 new commits: Re-review is drawn, as a primary', keys(fresh).indexOf('rereview') >= 0 &&
        deck.labels(rowOf(K, fresh)).indexOf('Re-review') >= 0);
  check('RV-3 new commits: and Open PR', labels(fresh).indexOf('Open PR') >= 0);
  check('RV-3 closed: one Dismiss, not two', labels(closed).filter((l) => /^Dismiss/.test(l)).length === 1);
  check('RV-3 dismissed: it can be brought back', labels(dismissed).indexOf('Restore review') >= 0);

  const P = page(all, {});
  P.App.space = 'work';
  const phone = (c) => primaries(paneParts(P, c).bar);
  check('RV-3 phone inbox: Review, Open PR, Review settings', JSON.stringify(phone(inbox)) === '["Review","Open PR","Review settings"]');
  check('RV-3 phone gate: Approve and Send back first', JSON.stringify(phone(gate).slice(0, 2)) === '["Approve","Send back"]');
  check('RV-3 phone posted: Open PR first', phone(posted)[0] === 'Open PR');
  check('RV-3 phone new commits: Re-review, Open PR, Review settings', JSON.stringify(phone(fresh)) === '["Re-review","Open PR","Review settings"]');

  /* the sheet: two fields, Model and Focus, written with one set */
  const S = page(all, { desk: true });
  S.App.space = 'work';
  S.renderSheet = function () {};
  let sent = null;
  S.act = function (body, done) { sent = body; if (done) done({}); return Promise.resolve({}); };
  const settingsBtn = deskAll(S, posted).filter((n) => keyOf(n) === 'review-settings')[0];
  settingsBtn.onclick({ stopPropagation() {}, currentTarget: settingsBtn });
  check('RV-3: Review settings opens its sheet', !!S.App.sheet && S.App.sheet.kind === 'review-settings' && S.App.sheet.id === 'c-724');
  let sheet = deck.wrap(S.reviewSettingsSheet(S.App.sheet), S);
  check('RV-3: the sheet has exactly Model and Focus', JSON.stringify(deck.byClass(sheet, 'label').map((n) => n.textContent)) === '["Model","Focus"]');
  const models = deck.all(sheet, (n) => n.getAttribute && /^rs-model-/.test(n.getAttribute('data-key') || ''));
  check('RV-3: Model is Sonnet or Opus, the card\'s own ticked', JSON.stringify(models.map(deck.labelOf)) === '["Sonnet","Opus"]' &&
        deck.hasClass(models[1], 'on'));
  models[0].onclick({});
  const focus = deck.all(sheet, (n) => n.tagName === 'TEXTAREA')[0];
  focus.oninput({ target: { value: '  Look hardest at the retry cap.  ' } });
  sheet = deck.wrap(S.reviewSettingsSheet(S.App.sheet), S);
  deck.all(sheet, (n) => n.getAttribute && n.getAttribute('data-key') === 'rs-save')[0].onclick({});
  check('RV-3: Save writes the model and the focus on the card', !!sent && sent.verb === 'set' && sent.id === 'c-724' &&
        sent.fields.model === 'sonnet' && sent.fields['options.review_focus'] === 'Look hardest at the retry cap.');
  S.App.sheet = { kind: 'review-settings', id: 'c-724', model: 'opus', focus: '' };
  sheet = deck.wrap(S.reviewSettingsSheet(S.App.sheet), S);
  deck.all(sheet, (n) => n.getAttribute && n.getAttribute('data-key') === 'rs-save')[0].onclick({});
  check('RV-3: an empty focus clears it', sent.fields['options.review_focus'] === null);
})();

/* ---------- Attention and Now around review cards (2026-09-24) ---------- */
(function () {
  const inbox = rv('c-731', 'waiting');
  const gate = rv('c-732', 'gate');
  const running = rv('c-733', 'reviewing', { rest: { session_id: 'aaaaaaaa-33',
    house: { kind: 'background', status: 'busy', bg_id: 'aaaaaaaa' } } });
  const K = page([inbox, gate, running], { desk: true }, { houses: ['c-733'], running: ['c-733'] });
  K.App.space = 'work';
  K.App.view = 'attention';
  const text = deck.wrap(K.viewAttention(), K).textContent;
  check('RV-4: a review card at his gate is in Attention', text.indexOf('c-732') >= 0);
  check('RV-4: one waiting for his Review tap is not', text.indexOf('c-731') < 0);
  K.App.view = 'now';
  const now = deck.wrap(K.viewNow(), K);
  const tile = deck.all(now, (n) => deck.hasClass(n, 'house') && n.getAttribute('data-key') === 'c-733')[0];
  check('RV-4: a running review house shows on Now like any house', !!tile);
  deck.all(tile, (n) => deck.hasClass(n, 't') && n.tagName === 'BUTTON')[0].onclick();
  check('RV-4: its title opens it on Reviews, its only list', K.App.view === 'reviews' && K.App.card === 'c-733');
})();

/* ---------- lane FC: a review card's pane says what a review card is ---------- */
(function () {
  /* FC-8: a review card posts comments, not a pull request of its own, so its gate pane
     never says "context.md has no PR body yet" */
  const gate = rv('c-741', 'gate', { rest: { output_ref: 'https://example.invalid/pr/741' } });
  const K = page([gate], { desk: true });
  K.App.space = 'work';
  K.App.detailFor = 'c-741';
  K.App.detail = { card: gate, events: [], context: '', pr_body: null, stands: null, plan_text: null, children: [] };
  const ev = deck.wrap(K.gateEvidence(gate), K).textContent;
  check('FC-8: a review card at its gate never says it has no PR body', ev.indexOf('no PR body') < 0 && ev.indexOf('PR body') < 0);
  check('FC-8: it says where the findings are', ev.indexOf('outcome page') >= 0);
  const plain = deck.card('c-742', { space: 'work', stage: 'review', output_ref: 'https://example.invalid/pr/9',
                                     derived: { outcome_gate: true, needs_you: true } });
  const P = page([plain], { desk: true });
  P.App.detailFor = 'c-742';
  P.App.detail = { card: plain, events: [], context: '', pr_body: null, stands: null, plan_text: null, children: [] };
  check('FC-8: a build card still says it has no PR body yet', deck.wrap(P.gateEvidence(plain), P).textContent.indexOf('no PR body yet') >= 0);
})();

(function () {
  /* FC-9: no raw JSON in the facts grid, for any card kind: every object an option can
     hold is drawn as readable facts, or not at all */
  const objects = {
    review_pr: { author: 'Ana Example', created: '2026-09-22T09:00:00+00:00', url: 'https://example.invalid/pr/4150',
                 head: 'abcdef1234567890', title: 'Tidy the loader', activity: '2026-09-23T09:00:00+00:00', backlog_days: 7 },
    review_focus: 'Look hardest at the retry cap.',
    review_members: [{ label: 'api#4150', repo: 'api', pr: 4150, url: 'https://example.invalid/pr/4150' },
                     { label: 'web#2200', repo: 'web', pr: 2200 }],
    review_heads: { 'api#4150': 'aaa1111222', 'web#2200': 'bbb2222333' },
    review_worktrees: { 'api#4150': '/wt/a', 'web#2200': '/wt/b' },
    review_posted: { head: 'feedface0011', verdict: 'changes', round: 1, ledger: [{ id: 'r1-f1' }], comments: { 'r1-f1': 7 },
                     at: '2026-09-23T10:00:00+00:00' },
    review_posting: { round: 1, comments: { 'r1-f1': 7 } },
    review_new: { head: 'cafe12345678', at: '2026-09-24T10:00:00+00:00' },
    review_wait: { story: 'st-41001', sibling_repo: 'web', since: '2026-09-24T08:00:00+00:00', hours: 48 },
    review_carried: [{ member: 'api#4150', ledger: [] }],
    review_closed: 'merged',
    shipping: { round: 2, facts: { prs: [{ repo: 'api', pr: 9, state: 'open' }], comments: 1 } },
    landing: { state: 'testing', host: 'mac' },
    pretest: { result: 'green', at: '2026-09-24T10:00:00+00:00' },
    rotate: { state: 'idle' },
    claim: { host: 'mac', at: '2026-09-24T10:00:00+00:00' },
    relays: [{ what: 'land', to: 'box' }],
    custom_list: ['one', 'two'],
    custom_map: { a: 1, b: 'two', nested: { c: 3 } }
  };
  const cards = [rv('c-751', 'posted', { options: objects }),
                 deck.card('c-752', { space: 'work', repo: 'api', options: objects }),
                 deck.card('c-753', { options: { custom_map: objects.custom_map, provenance: { model: 'stated' } } })];
  cards.forEach((c) => {
    const K = page(cards, { desk: true });
    K.App.space = c.space;
    const pane = deck.wrap(K.detailPane(c), K);
    const grid = deck.byClass(pane, 'kv-grid')[0];
    const raw = deck.all(grid, (n) => n.tagName === 'DD').map((n) => n.textContent).filter((t) => /[{[]/.test(t));
    check('FC-9: ' + c.id + ' draws no option as raw JSON', raw.length === 0);
  });
  const K = page(cards, { desk: true });
  K.App.space = 'work';
  const grid = deck.byClass(deck.wrap(K.detailPane(cards[0]), K), 'kv-grid')[0];
  const facts = {};
  const dt = deck.all(grid, (n) => n.tagName === 'DT'), dd = deck.all(grid, (n) => n.tagName === 'DD');
  dt.forEach((n, i) => { facts[n.textContent] = dd[i]; });
  check('FC-9: the review facts are readable: its author', !!facts.author && facts.author.textContent === 'Ana Example');
  const link = facts['pull request'] && deck.all(facts['pull request'], (n) => n.tagName === 'A')[0];
  check('FC-9: its pull request is a link', !!link && link.getAttribute('href') === 'https://example.invalid/pr/4150');
  check('FC-9: when it was raised', !!facts.raised && /ago/.test(facts.raised.textContent));
  check('FC-9: its head, short', !!facts.head && facts.head.textContent === 'abcdef12');
  check('FC-9: the focus as its words', !!facts.focus && facts.focus.textContent === 'Look hardest at the retry cap.');
  check('FC-9: the bookkeeping is not listed', !facts.review_posting && !facts.review_worktrees && !facts.review_carried
        && !facts.review_pr && !facts.review_focus);
})();

(function () {
  /* FC-10: the held line is the whole wait, wrapped where it is long, never cut off; its
     title carries it whole too */
  const held = rv('c-761', 'waiting', { derived: { review: 'held', review_wait: { sibling_repo: 'web', story: 'st-41001', hours_left: 47 } } });
  const K = page([held], { desk: true });
  K.App.space = 'work';
  const words = deck.all(deck.wrap(K.detailPane(held), K), (n) => deck.hasClass(n, 'sw') && /waiting for the/.test(n.textContent));
  check('FC-10: the held line wraps rather than clipping', words.length >= 1 && words.every((n) => deck.hasClass(n, 'tally')));
  check('FC-10: and its title is the whole line', words.every((n) => (n.getAttribute('title') || '').indexOf(n.textContent) >= 0));
})();

/* ---------- c-565: a cross-repo card's Open output offers each pull request ---------- */
(function () {
  const prs = [{ repo: 'api', pr: 4140, url: 'https://host/api/pr/4140' },
               { repo: 'web', pr: 812, url: 'https://host/web/pr/812' }];
  const two = deck.card('c-565', { space: 'work', stage: 'shipping', repo: 'api,web',
                                   links: { pr: prs[0].url, prs: prs } });
  let K = page([two]);
  K.App.space = 'work';
  K.renderSheet = function () {};
  let opened = null;
  K.openLink = function (url) { opened = url; };
  const output = K.cardItems(two).filter((n) => n.getAttribute('data-key') === 'open-output')[0];
  check('c-565: a card with two pull requests draws Open output', !!output && deck.labelOf(output) === 'Open output');
  output.onclick({});
  check('c-565: Open output opens the pull request sheet, not the primary', !!K.App.sheet && K.App.sheet.kind === 'prs' && opened === null);
  const sheet = deck.wrap(K.prsSheet(K.App.sheet), K);
  const links = deck.all(sheet, (n) => n.tagName === 'A');
  check('c-565: the sheet links each pull request by repo',
        JSON.stringify(links.map((a) => [a.textContent, a.getAttribute('href')])) ===
        JSON.stringify([['api #4140', prs[0].url], ['web #812', prs[1].url]]));
  check('c-565: its hover line says to pick one', (output.getAttribute('title') || '').indexOf('each of its repos') >= 0);
  const one = deck.card('c-566', { space: 'work', stage: 'shipping', repo: 'api',
                                   links: { pr: prs[0].url, prs: prs.slice(0, 1) } });
  K = page([one]);
  K.App.space = 'work';
  opened = null;
  K.openLink = function (url) { opened = url; };
  K.cardItems(one).filter((n) => n.getAttribute('data-key') === 'open-output')[0].onclick({});
  check('c-565: one pull request still opens straight away', opened === prs[0].url && !K.App.sheet);
})();

/* ---------- c-592: personal cards without Bosun driving ---------- */
function keelCard(id, filedBy, state, shown, extra) {
  return deck.card(id, Object.assign({ repo: 'keel', autonomy: 'autonomous', stage: state === 'next' || state === 'live' ? 'done' : 'assigned',
    derived: { bosun: true, keel_card: { filed_by: filedBy, state: state, shown: shown } } }, extra || {}));
}
(function () {
  const his = keelCard('c-801', 'him', 'building', true, { stage: 'building', options: { bosun: { batch: 'b-4', branch: 'bosun/c-801-x' } } });
  const onNext = keelCard('c-802', 'him', 'next', true);
  const live = keelCard('c-803', 'him', 'live', false);
  const bosuns = keelCard('c-804', 'bosun', 'queued', false);
  const asking = keelCard('c-805', 'bosun', 'queued', true, { derived: { bosun: true, needs_you: true, ask: { id: 'a-1', question: 'q' },
    keel_card: { filed_by: 'bosun', state: 'queued', shown: true } } });
  const errand = deck.card('c-806', { repo: null, stage: 'building' });
  let K = page([his, onNext, live, bosuns, asking, errand]);
  /* each repo's landing branch by name, as the server sends it (`flow.landing`, c-665) */
  K.App.data.spaces.personal.flow = { branches: [], moves: [], landing: { keel: 'next' } };
  K.App.view = 'cards';
  const ids = K.findCards().items.map((c) => c.id).sort().join();
  check('c-592: his board shows his Keel cards until live, and Bosun\'s only while it needs him', ids === 'c-801,c-802,c-805,c-806');
  const body = deck.wrap(K.viewCards(), K);
  const text = body.textContent;
  check('c-592: a Keel card carries the Keel / Bosun label', deck.byClass(body, 'kchip').length === 3 && text.indexOf('Keel · Bosun') >= 0);
  check('c-592: the label never marks a house\'s card', !deck.byClass(deck.wrap(K.wordsRow(errand), K), 'kchip').length);
  check('c-592: Bosun\'s state is said', text.indexOf('building') >= 0 && text.indexOf('on next') >= 0);
  /* c-665: the branch is the card's own landing branch, and no name is guessed for a repo with none */
  check('c-665: a landed card names its own landing branch or none: ' + K.keelWord(keelCard('c-9', 'him', 'next', true, { repo: 'notes' })).text,
        K.keelWord(onNext).text === 'on next' && !/\bnext\b/.test(K.keelWord(keelCard('c-9', 'him', 'next', true, { repo: 'notes' })).text));
  const words = (c) => K.wordsOf(c).map((n) => n.textContent).join('|');
  check('c-592: each state has its words', words(keelCard('c-9', 'him', 'plan', true)) === 'plan waiting for you'
        && words(bosuns) === 'queued' && words(live) === 'live' && words(asking) === 'Bosun asks|queued');
  check('c-592: nothing reads the old bosun chip', deck.byClass(body, 'bchip').length === 0);

  /* Bosun's view of it */
  const pane = deck.wrap(K.detailPane(his), K);
  const keel = deck.all(pane, (n) => n.getAttribute && n.getAttribute('data-key') === 'keel')[0];
  check('c-592: the pane leads with Bosun\'s view', !!keel && keel.textContent.indexOf('b-4') >= 0 && keel.textContent.indexOf('bosun/c-801-x') >= 0);
  const opens = deck.all(pane, (n) => n.tagName === 'A' && n.getAttribute('href') === '/console/queue');
  check('c-592: it opens the Bosun page', opens.length >= 1);
  const labels = deck.labels(deck.wrap(K.cardItems(his), K));
  ['Drop in', 'Talk to this house', 'Resume house', 'Logs'].forEach((w) => check('c-592: a Keel card offers no ' + w, labels.indexOf(w) < 0));
  const all = pane.textContent;
  ['Driven by Bosun', 'May not', 'Bosun\'s note', 'Bosun may approve', 'this hour'].forEach((w) =>
    check('c-592: the pane draws no ' + w, all.indexOf(w) < 0));
  const driven = deck.card('c-807', { options: { driver: 'bosun', grant: 'c-807' }, derived: { driving: { grant: 'c-807', strikes: 2, strikes_max: 3 } } });
  const old = deck.wrap(K.detailPane(driven), K).textContent;
  check('c-592: a card still carrying driver and grant draws neither', old.indexOf('Driven') < 0 && old.indexOf('grant') < 0 && old.indexOf('May') < 0);
})();
(function () {
  /* a repo-less card's outcome gate: read the result, then Done or Send back with a note */
  const r = deck.card('c-811', { repo: null, stage: 'review', output_ref: '/state/cards/c-811/context.md',
    links: { formats: { outcome: true } }, derived: { outcome_gate: true, needs_you: true } });
  let K = page([r]);
  let gate = deck.labels(deck.wrap(K.gateActions(r), K));
  check('c-592: research\'s gate is Open result, Done, Send back with a note',
        gate.indexOf('Open result') >= 0 && gate.indexOf('Done') >= 0 && gate.indexOf('Send back with a note') >= 0
        && gate.indexOf('Approve outcome') < 0);
  const pane = deck.wrap(K.detailPane(r), K);
  check('c-592: research draws no PR body', pane.textContent.indexOf('PR body') < 0 && pane.textContent.indexOf('what it says') >= 0);
  check('c-592: its outcome word says the result is ready', K.outcomeWord(r).text === 'result ready');
  const items = deck.labels(deck.wrap(K.cardItems(r), K));
  check('c-592: Drop in stays on a personal card', items.indexOf('Drop in') >= 0);
  const repoCard = deck.card('c-812', { space: 'work', repo: 'api', stage: 'review', derived: { outcome_gate: true, needs_you: true } });
  K = page([repoCard]);
  gate = deck.labels(deck.wrap(K.gateActions(repoCard), K));
  check('c-592: a card with a repo keeps Approve outcome', gate.indexOf('Approve outcome') >= 0 && gate.indexOf('Done') < 0);
})();
(function () {
  /* c-719: a work research card is research by its kind: Done, no PR body, never "This
     publishes it" (its approve publishes nothing) */
  const w = deck.card('c-815', { space: 'work', repo: 'api', stage: 'review', options: { kind: 'research' },
    links: { formats: { outcome: true } }, derived: { outcome_gate: true, needs_you: true } });
  const K = page([w]);
  check('c-719: a work research card is research', K.research(w) === true);
  const row = deck.wrap(K.gateActions(w), K);
  const gate = deck.labels(row);
  check('c-719: a work research card\'s gate is Done, not Approve outcome: ' + gate.join('|'),
        gate.indexOf('Done') >= 0 && gate.indexOf('Approve outcome') < 0 && gate.indexOf('Open result') >= 0);
  const pane = deck.wrap(K.detailPane(w), K).textContent;
  check('c-719: a work research card draws no PR body', pane.indexOf('PR body') < 0 && pane.indexOf('This publishes it') < 0);
  check('c-719: a work feature card keeps Approve outcome', K.research(deck.card('c-816', { space: 'work', repo: 'api',
    options: { kind: 'feature' } })) === false);
})();
(function () {
  /* c-719 r1.F6: a work research card's declared output (its findings board link) is offered
     under its own name beside Open result, at the gate and after it */
  const board = 'http://127.0.0.1:8800/board/b-12';
  const at = deck.card('c-817', { space: 'work', repo: 'api', stage: 'review', options: { kind: 'research' }, output_ref: board,
    links: { formats: { outcome: true }, output: board }, derived: { outcome_gate: true, needs_you: true } });
  let K = page([at]);
  let opened = [];
  K.openPlan = function (url) { opened.push(url); };
  K.openLink = function (url) { opened.push(url); };
  const gate = deck.wrap(K.gateActions(at), K);
  const named = deck.buttons(gate).filter((b) => deck.labelOf(b) === 'Open findings board')[0];
  check('r1.F6: the gate offers the findings board by name: ' + deck.labels(gate).join('|'), !!named);
  if (named) named.onclick({ stopPropagation() {}, preventDefault() {} });
  check('r1.F6: it opens the board: ' + opened.join(), opened.indexOf(board) >= 0);
  const done = deck.card('c-818', { space: 'work', repo: 'api', stage: 'done', options: { kind: 'research' }, output_ref: board,
    links: { formats: { outcome: true }, output: board }, derived: {} });
  K = page([done]);
  check('r1.F6: and after the gate: ' + deck.labels(deck.wrap(K.cardItems(done), K)).join('|'),
        deck.labels(deck.wrap(K.cardItems(done), K)).indexOf('Open findings board') >= 0);
  /* r2.F1, r2.F10: through what the user SEES: the desk pane (a button, or a name under a
     group's caret), the phone pane's primary row and its More sheet */
  [[at, 'at the gate'], [done, 'after the gate']].forEach(function (pair) {
    const c = pair[0], when = pair[1];
    check('r2.F1: the desk pane draws Open findings board ' + when + ': ' + drawnDesk(c).join('|'),
          drawnDesk(c).indexOf('Open findings board') >= 0);
    check('r2.F1: the phone pane or its More sheet draws it ' + when + ': ' + drawnPhone(c).join('|'),
          drawnPhone(c).indexOf('Open findings board') >= 0);
  });
})();
/* What the desk pane draws: its buttons, and the names under each group's caret. */
function drawnDesk(c) {
  const K = page([c], { desk: true });
  const pane = deck.wrap(K.detailPane(c), K);
  const carets = deck.all(pane, (n) => n.getAttribute && n.getAttribute('data-caret'))
    .map((n) => String(n.getAttribute('title') || '').replace(/^[^:]*: /, '')).join(', ').split(', ');
  return deck.labels(pane).concat(carets).filter(Boolean);
}
/* What the phone draws: the pane (its three actions) and the More actions sheet. */
function drawnPhone(c) {
  const K = page([c]);
  const pane = deck.labels(deck.wrap(K.detailPane(c), K));
  K.App.sheet = { kind: 'actions', id: c.id };
  return pane.concat(deck.labels(deck.wrap(K.actionsSheet(K.App.sheet), K)));
}
(function () {
  /* c-719, r2: EVERY control and link this card added or changed, through each surface the
     user sees: the desk pane, the phone pane and its More sheet, the Attention pane (the raw
     gate row), each with the card's files once its detail is loaded. The plan page's own
     send panel is tests/fixtures/research-send.js; the viewer's tabs tests/fixtures/cardfiles.js. */
  const board = 'http://127.0.0.1:8800/board/b-12';
  const w = deck.card('c-821', { space: 'work', repo: 'api', stage: 'review', options: { kind: 'research' }, output_ref: board,
    links: { formats: { outcome: true }, output: board }, derived: { outcome_gate: true, needs_you: true } });
  const files = [{ name: 'report.md', url: '/file/c-821/report.md' }, { name: 'results/B0.md', url: '/file/c-821/results/B0.md' }];
  function loaded(K) { K.App.detailFor = w.id; K.App.detail = { files: files, events: [], stands: 'found it' }; K.App.space = 'work'; return K; }
  const deskK = loaded(page([w], { desk: true })), phoneK = loaded(page([w]));
  const desk = deck.wrap(deskK.detailPane(w), deskK), phone = deck.wrap(phoneK.detailPane(w), phoneK);
  phoneK.App.sheet = { kind: 'actions', id: w.id };
  const sheet = deck.labels(deck.wrap(phoneK.actionsSheet(phoneK.App.sheet), phoneK));
  const deskSeen = drawnDesk(w);
  check('surfaces: the desk pane says Done, Open result, Open findings board: ' + deskSeen.join('|'),
        ['Done', 'Open result', 'Open findings board'].every((x) => deskSeen.indexOf(x) >= 0) && deskSeen.indexOf('Approve outcome') < 0);
  const primary = deck.labels(phone).filter((x) => x !== 'More actions' && x !== '\u2715');
  check('surfaces: the phone\'s primary row is Open result, Done, Send back with a note: ' + primary.slice(0, 3).join('|'),
        primary.slice(0, 3).join('|') === 'Open result|Done|Send back with a note');
  check('surfaces: the phone\'s More sheet holds Open findings board: ' + sheet.join('|'), sheet.indexOf('Open findings board') >= 0);
  [['desk', desk], ['phone', phone]].forEach(function (pair) {
    const text = pair[1].textContent;
    check('surfaces: the ' + pair[0] + ' pane draws no PR body and no publish words', text.indexOf('PR body') < 0 && text.indexOf('publishes') < 0);
    const fileLinks = deck.all(pair[1], (n) => n.getAttribute && /^f:/.test(n.getAttribute('data-key') || '')).map((n) => n.textContent);
    check('surfaces: the ' + pair[0] + ' pane lists the card\'s files: ' + fileLinks.join('|'), fileLinks.join('|') === 'report.md|results/B0.md');
    const all = deck.all(pair[1], (n) => n.getAttribute && n.getAttribute('href')).map((n) => n.getAttribute('href'));
    check('surfaces: the ' + pair[0] + ' pane\'s result line links the outcome and the board: ' + all.join(' '),
          all.indexOf('/outcome/c-821') >= 0 && all.indexOf(board) >= 0 && all.indexOf('/files/c-821') >= 0);
  });
  const attnK = loaded(page([w], { desk: true }));
  attnK.App.card = w.id;
  const attn = deck.labels(deck.wrap(attnK.viewAttention(), attnK));
  check('surfaces: the Attention pane\'s gate row says Done and Open findings board: ' + attn.join('|'),
        attn.indexOf('Done') >= 0 && attn.indexOf('Open findings board') >= 0 && attn.indexOf('Approve outcome') < 0);
})();
(function () {
  /* r2.F4: a research card whose output is its own record: one Open result, no second link */
  const own = deck.card('c-819', { repo: null, stage: 'review', output_ref: '/state/cards/c-819/context.md',
    links: { formats: { outcome: true }, output: '/outcome/c-819' }, derived: { outcome_gate: true, needs_you: true } });
  const plain = deck.card('c-820', { repo: null, stage: 'review', output_ref: '/state/cards/c-820/context.md',
    links: { output: '/context/c-820' }, derived: { outcome_gate: true, needs_you: true } });
  [own, plain].forEach(function (c) {
    const desk = drawnDesk(c), phone = drawnPhone(c);
    check('r2.F4: ' + c.id + ' draws Open result and no Open output: ' + desk.join('|') + ' / ' + phone.join('|'),
          desk.indexOf('Open result') >= 0 && desk.indexOf('Open output') < 0 && phone.indexOf('Open output') < 0
          && desk.filter((w) => w === 'Open result').length === 1);
  });
})();
(function () {
  /* c-719: a result whose output names a markdown file: the outcome is Open result, and the
     named file is offered beside it by its name, in the viewer, never hidden behind it */
  const r = deck.card('c-813', { repo: null, stage: 'review', output_ref: '/state/cards/c-813/report.md',
    links: { formats: { outcome: true }, output: '/file/c-813/report.md' }, derived: { outcome_gate: true, needs_you: true } });
  const K = page([r]);
  let opened = [];
  K.openPlan = function (url) { opened.push(url); };
  const row = deck.wrap(K.gateActions(r), K);
  const gate = deck.labels(row);
  check('c-719: the gate offers the outcome and the named file: ' + gate.join('|'),
        gate.indexOf('Open result') >= 0 && gate.indexOf('Open report.md') >= 0);
  deck.buttons(row).filter((b) => /^Open/.test(deck.labelOf(b))).forEach((b) => b.onclick({ preventDefault() {}, stopPropagation() {} }));
  check('c-719: Open result opens the outcome, the file its viewer page: ' + opened.join(),
        opened.indexOf('/outcome/c-813') >= 0 && opened.indexOf('/file/c-813/report.md') >= 0);
  const evidence = deck.wrap(K.gateEvidence(r), K);
  const hrefs = deck.all(evidence, (n) => n.tagName === 'A').map((n) => n.getAttribute('href'));
  check('c-719: the result line links both: ' + hrefs.join(), hrefs.indexOf('/outcome/c-813') >= 0 && hrefs.indexOf('/file/c-813/report.md') >= 0);
  check('r2.F10: the desk pane draws Open report.md: ' + drawnDesk(r).join('|'), drawnDesk(r).indexOf('Open report.md') >= 0);
  check('r2.F10: the phone draws Open report.md: ' + drawnPhone(r).join('|'), drawnPhone(r).indexOf('Open report.md') >= 0);
  /* with no outcome page, Open result is the named file itself, and is not offered twice */
  const bare = deck.card('c-814', { repo: null, stage: 'review', output_ref: '/state/cards/c-814/report.md',
    links: { output: '/file/c-814/report.md' }, derived: { outcome_gate: true, needs_you: true } });
  const K2 = page([bare]);
  const labels = deck.labels(deck.wrap(K2.gateActions(bare), K2));
  check('c-719: with no outcome page the file is the result, once: ' + labels.join('|'),
        labels.indexOf('Open result') >= 0 && labels.indexOf('Open report.md') < 0);
})();
(function () {
  /* the create modal: no Driven by Bosun, no Plan style while plans are pages */
  const K = page([], {}, { spaces: { personal: { adapter: null, repos: ['keel'], verbs: { card: [] }, topics: [], counts: {},
    options: [{ key: 'repo', label: 'Repo', type: 'multiselect', stored: 'card', options: ['keel'], default: [] },
              { key: 'model', label: 'Model', type: 'select', stored: 'card', options: ['opus'], default: 'opus' },
              { key: 'plan_style', label: 'Plan style', type: 'select', stored: 'options', options: ['auto'], default: 'auto' }] },
    work: { adapter: null, repos: [], options: [], verbs: { card: [] }, topics: [], counts: {} } },
    config: { houses_max: 3, drain_paused: false, plan_pages: true } });
  let painted = null;
  K.paint = function (slot, node) { if (slot === 'modal') painted = node; };
  K.openModal(null);
  const text = painted ? deck.wrap(painted, K).textContent : '';
  check('c-592: the create modal opens', text.indexOf('New card') >= 0);
  check('c-592: the create modal has no Driven by Bosun', text.indexOf('Driven by Bosun') < 0);
  check('c-592: no Plan style while plans are pages', text.indexOf('Plan style') < 0);
  check('c-592: Model is asked of a card with no repo', text.indexOf('Model') >= 0);
})();

/* ---------- c-645: who works a card, said before it exists and on the pane ---------- */
(function () {
  function form(builder, repo, mode, lands) {
    const K = page([], {}, { spaces: { personal: { adapter: null, repos: ['keel', 'notes'], verbs: { card: [] }, topics: [], counts: {},
      flow: { branches: [], moves: [], landing: lands || { keel: 'next' } },
      options: [{ key: 'repo', label: 'Repo', type: 'multiselect', stored: 'card', options: ['keel', 'notes'], default: [] }] } },
      config: { houses_max: 3, drain_paused: false, plan_pages: true, builder: builder } });
    let painted = null;
    K.paint = function (slot, node) { if (slot === 'modal') painted = node; };
    K.openModal(null);
    K.App.modal.values.repo = repo;
    if (mode) K.App.modal.mode = mode;
    K.renderModal();
    return { K: K, view: deck.wrap(painted, K) };
  }
  const ON = { on: true, builds: ['keel'], lands: false };
  let f = form(ON, ['keel']);
  const select = deck.all(f.view, (n) => n.getAttribute && n.getAttribute('data-fk') === 'f:worker')[0];
  check('c-645: a builder repo offers Bosun or a house', !!select && deck.all(select, (n) => n.tagName === 'OPTION').map((o) => o.value).join() === 'bosun,house');
  check('c-645: Bosun is the default, as before', !!select && (deck.all(select, (n) => n.tagName === 'OPTION' && n.selected)[0] || {}).value === 'bosun');
  check('c-645: the row says who approves in this mode', f.view.textContent.indexOf('you approve its plan and outcome') >= 0);
  f = form(Object.assign({}, ON, { lands: true }), ['keel']);
  check('c-645: in superbuilder mode it says he lands it', f.view.textContent.indexOf('lands it on next itself') >= 0);
  /* c-665: the branch is the repo's own landing branch, and none is named where none is known */
  f = form(Object.assign({}, ON, { lands: true }), ['keel'], null, { keel: 'trial' });
  check('c-665: the form names the repo\'s own landing branch', f.view.textContent.indexOf('lands it on trial itself') >= 0
        && !/\bnext\b/.test(f.view.textContent));
  f = form({ on: true, builds: null, lands: true }, ['notes']);
  check('c-665: a repo with no landing branch names none: ' + f.view.textContent.slice(0, 300),
        f.view.textContent.indexOf('Bosun builds it and lands it itself') >= 0 && !/\bnext\b/.test(f.view.textContent));
  const mine = (repo) => deck.card('c-901', { repo: repo, derived: { worker: 'bosun' } });
  check('c-665: the pane\'s worker line names the card\'s own landing branch: ' + f.K.workerLine(mine('keel')),
        f.K.workerLine(mine('keel')).indexOf('lands it on next;') >= 0
        && !/\bnext\b/.test(f.K.workerLine(mine('notes'))) && f.K.workerLine(mine('notes')).indexOf('lands it;') >= 0);
  /* review pass 2: the card does not say which branch moved (`options.merging` is `true`),
     so the word names none, for every card: it never guesses the landing branch or `main` */
  const merging = (repo) => f.K.houseWord(deck.card('c-902', { repo: repo, options: { merging: true } })).text;
  check('c-665: the house word names no branch: ' + merging('keel') + ' / ' + merging('notes'),
        merging('keel') === 'merging its target' && merging('notes') === 'merging its target');
  const moved = (target) => f.K.sentence({ verb: 'approve', gate: 'outcome', id: 'c-1' }, { merge_conflict: true, target: target }).text;
  check('c-665: a conflict says which branch moved, or names none: ' + moved('next,main') + ' / ' + moved(null),
        moved('next,main').indexOf('next and main moved:') === 0 && !/\b(next|main)\b/.test(moved(null)));
  const bosunMoved = f.K.sentence({ verb: 'approve', gate: 'outcome', id: 'c-1' }, { merge_conflict: true, target: 'next', bosun: true }).text;
  check('c-647: a conflict on a card Bosun builds never says a house is merging: ' + bosunMoved,
        bosunMoved.indexOf('waiting for Bosun to merge') > 0 && bosunMoved.indexOf('house') < 0);
  /* c-734: a gate tap on a card Bosun builds resumes no house: Bosun is told, and that is no error */
  const told = { resumed: null, told: 'plan', note: 'Bosun is told at once, or as soon as it is free' };
  const tapsSay = [f.K.sentence({ verb: 'approve', gate: 'plan', id: 'c-1' }, told),
    f.K.sentence({ verb: 'sendback', id: 'c-1' }, Object.assign({}, told, { told: 'sendback' })),
    f.K.sentence({ verb: 'approve', gate: 'outcome', id: 'c-1' }, Object.assign({}, told, { told: 'outcome' }))];
  check('c-734: a gate tap on a card Bosun builds says Bosun is told, never an error: ' + JSON.stringify(tapsSay),
        tapsSay.every((s) => s && s.err === false && s.text === told.note));
  f = form(ON, ['notes']);
  check('c-645: off a builder repo, one line says a house', deck.all(f.view, (n) => n.getAttribute && n.getAttribute('data-fk') === 'f:worker').length === 0
        && f.view.textContent.indexOf('A house: Bosun builds only the repos') >= 0);
  f = form(ON, []);
  check('c-645: no repo says a house too', f.view.textContent.indexOf('A house: no repo') >= 0);
  /* r1.F6: a new project becomes the card's repo, so under the superuser (every repo) it is Bosun's */
  f = form({ on: true, builds: null, lands: true }, []);
  f.K.App.modal.values.new_project = 'coach';
  let again = null;
  f.K.paint = function (slot, node) { if (slot === 'modal') again = node; };
  f.K.renderModal();
  const redrawn = deck.wrap(again, f.K).textContent;
  /* c-665: a project that is not there yet has no landing branch to name */
  check('c-645: a new project counts as its repo: ' + redrawn.slice(0, 200),
        redrawn.indexOf('A house: no repo') < 0 && redrawn.indexOf('Bosun builds it and lands it itself') >= 0);
  f = form({ on: false }, ['keel']);
  check('c-645: builder mode off says nothing of workers', f.view.textContent.indexOf('Worker') < 0);
  f = form(ON, ['keel'], 'edit');
  check('c-645: an edit leaves the worker alone', f.view.textContent.indexOf('Worker') < 0);
  /* what the form sends: the chosen worker, as an option */
  f = form(ON, ['keel']);
  f.K.App.modal.values.title = 'a keel card';
  f.K.App.modal.values.worker = 'house';
  let sent = null;
  f.K.act = function (body) { sent = body; return Promise.resolve(null); };
  const create = deck.buttons(f.view).filter((b) => /Create, file to inbox/.test(b.textContent))[0];
  if (create) create.onclick({ currentTarget: create });
  check('c-645: the form sends the worker it shows: ' + JSON.stringify(sent), !!sent && sent.options && sent.options.worker === 'house');

  /* the pane: the line, and his move before anything starts */
  const keyOf = (n) => n.getAttribute && n.getAttribute('data-key');
  const bosunCard = deck.card('c-70', { repo: 'keel', derived: { worker: 'bosun', worker_eligible: true } });
  let K = page([bosunCard], { desk: true });
  K.App.data.config.builder = ON;
  const give = K.cardItems(bosunCard).filter((n) => keyOf(n) === 'worker')[0];
  check('c-645: Bosun\'s card offers Give to a house', !!give && give.textContent === 'Give to a house');
  check('c-645: the pane says who works it', deck.wrap(K.detailPane(bosunCard), K).textContent.indexOf('Bosun: you approve its plan and outcome') >= 0);
  const houseCard = deck.card('c-71', { repo: 'keel', options: { worker: 'house' }, derived: { worker: 'house', worker_eligible: true } });
  K = page([houseCard], { desk: true });
  const back = K.cardItems(houseCard).filter((n) => keyOf(n) === 'worker')[0];
  check('c-645: a house card Bosun could build offers Give to Bosun', !!back && back.textContent === 'Give to Bosun');
  const started = deck.card('c-72', { repo: 'keel', stage: 'building', session_id: 'aaaaaaaa-7', derived: { worker: 'bosun', worker_eligible: true } });
  K = page([started], { desk: true });
  check('c-645: not once it has started', K.cardItems(started).every((n) => keyOf(n) !== 'worker'));
  const tracker = deck.card('c-74', { repo: 'keel', derived: { worker: 'bosun', worker_eligible: true, tracking: true } });
  K = page([tracker], { desk: true });
  check('c-645: not on a tracking card', K.cardItems(tracker).every((n) => keyOf(n) !== 'worker'));
  const notes = deck.card('c-73', { repo: 'notes', derived: { worker: 'house', worker_eligible: false } });
  K = page([notes], { desk: true });
  check('c-645: not on a card Bosun cannot build', K.cardItems(notes).every((n) => keyOf(n) !== 'worker'));
})();

/* ---------- c-600: the shipping phase draws only the controls it justifies ---------- */
function keysIn(node) {
  return deck.all(node, (n) => n.getAttribute && !!n.getAttribute('data-key')).map((n) => n.getAttribute('data-key'));
}
(function () {
  const SESSION = 'f00dcafe-0000-4000-8000-000000000001';
  function shipCard(id, extra) {
    return deck.card(id, Object.assign({ space: 'work', repo: 'api', stage: 'shipping', session_id: SESSION,
      output_ref: 'https://example.invalid/pr/1', links: { pr: 'https://example.invalid/pr/1', story: 'https://example.invalid/story/1', context: '/api/context/' + id },
      house: { bg_id: SESSION.slice(0, 8), status: 'idle', state: 'done', kind: 'background' },
      options: { app_link: 'https://example.invalid/app', shipping: { round: 1, told: [{ handle: 'c11', batch: 1 }], posted: {},
        local: { ahead: 2, unchecked: true, conflicts: false }, facts: { state: 'open', comments: 3, draft: false, behind: 1 } } } }, extra || {}));
  }
  const idle = shipCard('c-901');
  let K = page([idle], { desk: true });
  const gate = deck.labels(deck.wrap(K.gateActions(idle), K));
  /* c-663: Send back, his own notes for the house, is the one other act of his there */
  const gateKeys = deck.wrap(K.gateActions(idle), K).childNodes.filter((n) => n.tagName === 'BUTTON').map((n) => n.getAttribute('data-key'));
  check('c-600: Ship leads the gate actions at shipping, with Send back the one other: ' + gateKeys,
        gate.length === 2 && gateKeys.join() === 'ship,ship-sendback');
  /* c-663 review: no Send back where no tell can follow (an archived card) */
  const put = shipCard('c-902', { derived: { archived: true } });
  check('c-663: an archived shipping card has no Send back',
        deck.labels(deck.wrap(K.gateActions(put), K)).indexOf('Send back') < 0);
  const items = deck.labels(deck.wrap(K.cardItems(idle), K));
  /* c-653: the ways into the house are on the row itself; Talk, the sheet, only with voice */
  check('c-600, c-644, c-653: the shipping card items are Open in Claude app, Drop in, Open output, Open story, View context, Open comments, Archive',
        items.join() === 'Open in Claude app,Drop in,Open output,Open story,View context,Open comments,Archive');
  ['Resume house', 'Retry', 'Split', 'Edit', 'Address now', 'Rotate session', 'Resume and open in app', 'Logs', 'Talk to this house'].forEach((word) => {
    check('c-600: no ' + word + ' at shipping', items.indexOf(word) < 0 && gate.indexOf(word) < 0);
  });
  const confirm = K.shipping.shipConfirm(idle);
  check('c-600: Ship says what it will push and warns of unchecked commits and the behind base',
        confirm.indexOf('push 2 commits') >= 0 && confirm.indexOf('not checked') >= 0 && confirm.indexOf('1 behind') >= 0);
  check('c-600: the chip says what is open and what is to ship', K.outcomeWord(idle).text.indexOf('1 open') >= 0
        && K.outcomeWord(idle).text.indexOf('2 commits to ship') >= 0);
  const busy = shipCard('c-902', { house: { bg_id: 'x', status: 'busy', state: 'working', kind: 'background' } });
  K = page([busy], { desk: true });
  check('c-600: Stop session only while the house answers review', deck.labels(deck.wrap(K.cardItems(busy), K)).indexOf('Stop session') >= 0);
  const blocked = shipCard('c-903', { blocked_reason: 'the review batch could not reach the house', derived: { needs_you: true } });
  K = page([blocked], { desk: true });
  const bgate = deck.labels(deck.wrap(K.gateActions(blocked), K));
  check('c-600: a blocked shipping card offers Unblock only, never Retry or Resume', bgate.join() === 'Unblock only');
  const tile = deck.labels(deck.wrap(K.houseActions(blocked), K));
  check('c-600: its Now tile has no Retry either', tile.join() === 'Unblock only');
  const done = shipCard('c-904', { options: { shipping: { told: [{ handle: 'c11' }], posted: { c11: 'd' }, local: { ahead: 0 }, facts: {} } } });
  K = page([done], { desk: true });
  check('c-600: nothing to ship draws no Ship', keysIn(deck.wrap(K.gateActions(done), K)).indexOf('ship') < 0);
  /* the standing batch in the pane */
  K = page([idle]);
  K.App.detailFor = idle.id;
  K.App.detail = { events: [], shipping: { summary: { told: 3, judging: 1, to_post: 1, local: {}, draft: false }, rows: [
    { handle: 'c11', item: { kind: 'comment', author: 'Ana', path: 'a.py', line: 4, text: 'Why 40?', batch: 1 },
      verdict: { verdict: 'not-valid', why: 'the host pages at 40', summary: 'why the cap', reply: 'It is the page size.', commits: [] },
      choice: 'post', words: 'It is the page size.', posted: false, edited: '' },
    { handle: 'c12', item: { kind: 'comment', author: 'Bo', text: 'Use a dict', batch: 1 },
      verdict: { verdict: 'valid', why: 'lookups', reply: '', commits: [{ sha: 'abc1234def', diff: '+x = {}' }] },
      choice: null, words: '', posted: false, edited: '' },
    { handle: 'ci', item: { kind: 'ci', name: 'unit tests', batch: 1 }, verdict: null, choice: null, words: '', posted: false, edited: '' }] } };
  const pane = deck.wrap(K.detailPane(idle), K);
  const text = pane.textContent;
  /* c-643: the rows live on the review comments page; the pane says one line and opens it */
  check('c-643: the pane says the standing batch in one line',
        text.indexOf('3 review items: 2 judged, 1 reply to post') >= 0);
  check('c-643: the pane draws no rows', deck.all(pane, (n) => n.getAttribute && /^row-/.test(n.getAttribute('data-key') || '')).length === 0
        && deck.labels(pane).indexOf('Post') < 0);
  /* c-644: Open comments is among the card's Pages, not in the section */
  check('c-644: the section has no button of its own', deck.all(deck.all(pane, (n) => n.getAttribute && n.getAttribute('data-key') === 'shipping-sec')[0] || pane,
        (n) => n.getAttribute && n.getAttribute('data-key') === 'open-comments').length === 0);
  const open = deck.wrap(K.cardItems(idle), K).childNodes.filter((n) => n.getAttribute && n.getAttribute('data-key') === 'open-comments')[0];
  let opened = null;
  K.openPlan = function (url) { opened = url; };
  if (open) open.onclick();
  check('c-643: Open comments opens the card\'s comments page', opened === '/comments/' + idle.id);
  const confirmWords = K.shipping.shipConfirm(idle);
  check('c-600: the Ship confirm says replies, never replys', String(confirmWords).indexOf('replys') < 0);
  check('c-600 review: a held Ship says nothing yet and asks him (Ship anyway)',
        typeof K.shipping.shipDone === 'function' && K.shipping.shipDone(idle)({ note: 'shipped: x' }) === 'shipped: x');
  /* Talk: one sheet, voice only where it is installed */
  K = page([idle]);
  let sheet = deck.labels(deck.wrap(K.talkSheet({ kind: 'talk', id: idle.id }), K));
  check('c-600: Talk offers the Claude app and Drop in', sheet.indexOf('Open in Claude app') >= 0 && sheet.indexOf('Drop in') >= 0);
  check('c-600: no voice where it is not installed', sheet.indexOf('Talk by voice') < 0);
  K = page([idle], {}, { health: { level: 'green', reasons: [], services: [{ name: 'voice', level: 'green', state: 'up' }] } });
  sheet = deck.labels(deck.wrap(K.talkSheet({ kind: 'talk', id: idle.id }), K));
  check('c-600: voice where it is installed', sheet.indexOf('Talk by voice') >= 0);
})();

/* ---------- c-653: Ship says what it sends, is drawn only where the send can go, the way
   into a live house is on the row, and a critical action never leads a split group ---------- */
(function () {
  const SESSION = 'f00dcafe-0000-4000-8000-000000000002';
  const LIVE = { bg_id: SESSION.slice(0, 8), status: 'idle', state: 'done', kind: 'background', recorded: true, working: false };
  const BUSY = Object.assign({}, LIVE, { status: 'busy', state: 'working', working: true });
  function shipCard(id, local, extra) {
    return deck.card(id, Object.assign({ space: 'work', repo: 'api', stage: 'shipping', session_id: SESSION,
      output_ref: 'https://example.invalid/pr/1', links: { pr: 'https://example.invalid/pr/1' }, house: LIVE,
      options: { app_link: 'https://example.invalid/app', shipping: { round: 2, told: [{ handle: 'c11', batch: 1 }], posted: {},
        local: Object.assign({ ahead: 0, behind: 0, unchecked: false, conflicts: false }, local), facts: { state: 'open', draft: false } } } }, extra || {}));
  }
  function loaded(K, c, summary) {
    K.App.detailFor = c.id;
    K.App.detail = { events: [], shipping: { summary: Object.assign({ told: 3, judging: 0, to_post: 0 }, summary), rows: [] } };
  }
  function gateOf(c, summary, opts) {
    const K = page([c], Object.assign({ desk: true }, opts || {}));
    loaded(K, c, summary);
    const row = deck.wrap(K.gateActions(c), K);
    const by = (key) => deck.all(row, (n) => n.getAttribute && n.getAttribute('data-key') === key)[0] || null;
    /* the buttons but for Send back (c-663), which every shipping row not declined carries */
    const sends = deck.buttons(row).filter((b) => b.getAttribute('data-key') !== 'ship-sendback');
    return { K, row, sends, ship: by('ship'), why: by('ship-why'), hand: by('ship-by-hand'), anyway: by('ship-anyway') };
  }
  /* 1: the button names what is waiting, and it is one button */
  let g = gateOf(shipCard('c-911', { ahead: 2 }), { to_post: 3 });
  check('c-653: commits and replies are both named on the one button',
        !!g.ship && /2 commits/.test(g.ship.textContent) && /3 replies/.test(g.ship.textContent) && g.sends.length === 1);
  check('c-653: the push is named before the replies', g.ship.textContent.indexOf('commits') < g.ship.textContent.indexOf('replies'));
  g = gateOf(shipCard('c-912', {}), { to_post: 1 });
  check('c-653: replies alone name no push', !!g.ship && /1 reply/.test(g.ship.textContent) && !/commit/i.test(g.ship.textContent));
  g = gateOf(shipCard('c-913', { ahead: 1 }), {});
  check('c-653: commits alone name no reply', !!g.ship && /1 commit/.test(g.ship.textContent) && !/repl/i.test(g.ship.textContent));
  const draft = shipCard('c-914', {});
  draft.options.shipping.facts.draft = true;
  g = gateOf(draft, {});
  check('c-653: a draft alone is marked ready for review', !!g.ship && /ready for review/.test(g.ship.textContent));
  /* c-660: a Ship that went. Until the state drawn is the Ship's own, its line is where the
     button was; then the row says what waits now. Never the old label after a send. */
  const went = shipCard('c-931', { ahead: 23 });
  went.options.shipping.since = '2026-10-01T09:00:00+05:30';
  g = gateOf(went, { to_post: 1 });
  const again = () => {
    const drawn = deck.wrap(g.K.gateActions(went), g.K);
    const by = (key) => deck.all(drawn, (n) => n.getAttribute && n.getAttribute('data-key') === key)[0] || null;
    return { ship: by('ship'), why: by('ship-why') };
  };
  const AT = '2026-10-06T10:00:00+05:30', LINE = 'shipped: pushed api f8e7cb9c34, posted 0 replies';
  check('c-660: before the tap the button names the commits', !!g.ship && /23 commits/.test(g.ship.textContent));
  const answer = () => ({ card: { options: { shipping: { shipped_at: AT, since: went.options.shipping.since, round: 2 } } }, note: LINE });
  g.K.shipping.shipDone(went)(answer());
  let after = again();
  check('c-660: after the answer the old label is gone and the Ship\'s own line is in its place',
        !after.ship && !!after.why && after.why.textContent.indexOf(LINE) >= 0);
  /* r1.F5: the card is the Ship's, the pane's standing batch is still the older read, and
     that read alone would draw "Post 1 reply" for the reply the Ship just posted */
  went.options.shipping.shipped_at = AT;
  went.options.shipping.local.ahead = 0;
  after = again();
  check('c-660: the card\'s new state alone brings no label back from the pane\'s older read',
        !after.ship && !!after.why && after.why.textContent.indexOf(LINE) >= 0);
  loaded(g.K, went, { shipped_at: AT, to_post: 1 });
  after = again();
  check('c-660: the batch read after the Ship brings back the button for what really waits',
        !!after.ship && /1 reply/.test(after.ship.textContent) && !/commit/.test(after.ship.textContent));
  /* r1.F4: the line never outlives what it describes. A record begun afresh (no
     `shipped_at`, another `since`) is drawn as it is; and the line ends on its bound */
  went.options.shipping.shipped_at = null;
  went.options.shipping.local.ahead = 23;
  loaded(g.K, went, { to_post: 0 });
  g.K.shipping.shipDone(went)(answer());
  check('c-660: the line stands while the page still holds the state from before the Ship', !again().ship);
  went.options.shipping.since = '2026-10-06T11:00:00+05:30';
  after = again();
  check('c-660: a record begun afresh is drawn as it is, never under the old line', !!after.ship && /23 commits/.test(after.ship.textContent));
  g.K.shipping.shipDone(went)(answer());
  check('c-660: (the line again, on the record this Ship answered on)', !again().ship);
  const clock = Date.now;
  Date.now = () => clock() + 60000;
  after = again();
  Date.now = clock;
  check('c-660: the line ends on its bound, whatever the page holds', !!after.ship && /23 commits/.test(after.ship.textContent));
  /* r1.F6: Ship anyway waits while an action on the card is on its way */
  const held = shipCard('c-932', { ahead: 2 }, { house: BUSY });
  g = gateOf(held, {});
  check('c-660: Ship anyway is open with nothing on its way', !!g.anyway && g.anyway.getAttribute('disabled') === null);
  g.K.App.pending['mark\u00b7' + held.id] = { subject: held.id, label: 'Saving…' };
  const waits = deck.all(deck.wrap(g.K.gateActions(held), g.K), (n) => n.getAttribute && n.getAttribute('data-key') === 'ship-anyway')[0];
  check('c-660: Ship anyway cannot be tapped while an action on the card is on its way', !!waits && waits.getAttribute('disabled') !== null);
  /* 2: only where the send can succeed; otherwise one line where the button would be */
  g = gateOf(shipCard('c-915', {}), {});
  check('c-653: nothing waiting draws no button and says so', !g.ship && !!g.why && /Nothing to send/.test(g.why.textContent));
  g = gateOf(shipCard('c-916', {}), { judging: 2 });
  check('c-653: told and none judged offers no post', !g.ship && !!g.why && /2 items/.test(g.why.textContent));
  /* r1.F2: the sentence is the backend's, drawn as given */
  const SAID = 'The branch has diverged from the pull request\'s branch (223 ahead, 220 behind): THE-BACKEND-SENTENCE.';
  const HAND = [{ repo: 'api', root: '/w/api', own: 3, command: 'cd /w/api && test "$(git rev-parse HEAD)" = abc && git fetch origin b && git branch -f keep abc && git rebase --onto origin/b def' }];
  const lead = (node) => deck.buttons(node).filter((b) => deck.hasClass(b, 'primary')).map((b) => b.getAttribute('data-key'));
  const copies = (node) => deck.all(node, (n) => n.getAttribute && /lcopy/.test(n.getAttribute('class') || ''));
  g = gateOf(shipCard('c-917', { ahead: 0, behind: 220, diverged: { ahead: 223, behind: 220 }, said: SAID, by_hand: HAND }), { to_post: 1 });
  check('c-653: a diverged branch draws no Ship and says the backend\'s own sentence',
        !g.ship && !!g.why && g.why.textContent.indexOf(SAID) === 0);
  check('c-653: the by-hand commands are under it, whole, in a block with a copy button',
        !!g.hand && g.hand.textContent.indexOf(HAND[0].command) === 0 && copies(g.hand).length === 1);
  check('c-653: Keel offers no button that moves the branch', lead(g.row).length === 0 && g.sends.length === 1);
  /* a history Keel cannot place: the sentence says so, and there is no block */
  g = gateOf(shipCard('c-925', { behind: 3, diverged: { ahead: 2, behind: 3 }, said: SAID, by_hand: [{ repo: 'api', root: '/w', why: 'x' }] }), {});
  check('c-653: with no commands to give, no block is drawn', !!g.why && !g.hand);
  g = gateOf(shipCard('c-928', { behind: 3, diverged: { ahead: 2, behind: 3 }, said: SAID,
    by_hand: HAND.concat([{ repo: 'web', root: '/w/web', command: 'cd /w/web && git merge --ff-only origin/b' }]) }), {});
  check('c-653: a cross-repo card\'s commands are one block, one chain a line for each worktree',
        !!g.hand && g.hand.textContent.indexOf(HAND[0].command + '\ncd /w/web && git merge') === 0);
  /* with c-655's hand-over on the row: ONE leading button, Ship, else the hand-over (r3.F6);
     and no merge of the base asked of a house whose branch is behind or has diverged (r3.F5) */
  const both = shipCard('c-926', { ahead: 2 }, { derived: { ship_handover: { comments: 2, checks: 0, base: true } } });
  let row = deck.wrap(page([both], { desk: true }).gateActions(both), page([both], { desk: true }));
  check('c-653, c-655: with commits to push and review to hand over, Ship leads and the hand-over is beside it',
        lead(row).join() === 'ship' && keysIn(row).indexOf('hand-over') >= 0 && keysIn(row).indexOf('hand-base') >= 0);
  const split = shipCard('c-927', { behind: 3, diverged: { ahead: 2, behind: 3 }, said: SAID, by_hand: HAND },
                         { derived: { ship_handover: { comments: 2, checks: 0, base: true } } });
  let SK = page([split], { desk: true });
  row = deck.wrap(SK.gateActions(split), SK);
  check('c-653, c-655: on a diverged card the hand-over is the one leading button, and no base merge is asked',
        lead(row).join() === 'hand-over' && keysIn(row).indexOf('hand-base') < 0);
  let asked = null;
  SK._win.confirm = function (text) { asked = text; return false; };
  deck.buttons(row).filter((b) => b.getAttribute('data-key') === 'hand-over')[0].onclick({ stopPropagation: function () {} });
  check('c-653: handing over on a diverged card first says the branch is out of step and the house is told so',
        !!asked && /out of step/.test(asked) && /told/.test(asked));
  const lag = shipCard('c-929', { behind: 1, said: 'BEHIND-SENTENCE.' }, { derived: { ship_handover: { comments: 1, checks: 0, base: true } } });
  SK = page([lag], { desk: true });
  loaded(SK, lag, { to_post: 2 });
  row = deck.wrap(SK.gateActions(lag), SK);
  check('c-653: a branch only behind hides the base merge too, and Ship is the one leading button',
        lead(row).join() === 'ship' && keysIn(row).indexOf('hand-base') < 0 && keysIn(row).indexOf('hand-over') >= 0);
  /* r1.F8: behind only is no refusal: what needs no push still goes, the commands beside it */
  g = gateOf(shipCard('c-923', { behind: 1, said: 'BEHIND-SENTENCE.', by_hand: [{ repo: 'api', root: '/w', command: 'cd /w && git merge --ff-only origin/b' }] }), { to_post: 2 });
  check('c-653: a branch only behind still sends the replies, with the sentence and the commands',
        !!g.ship && /2 replies/.test(g.ship.textContent) && !!g.hand && !!g.why && g.why.textContent.indexOf('BEHIND-SENTENCE.') === 0);
  g = gateOf(shipCard('c-918', { ahead: 1 }, { house: BUSY }), { to_post: 1 });
  check('c-653: a house in its turn draws no Ship and says so', !g.ship && !!g.why && /in its turn/.test(g.why.textContent));
  let sent = null;
  g.K.act = function (body) { sent = body; return { then: function () {} }; };
  if (g.anyway) g.anyway.onclick({ stopPropagation: function () {} });
  check('c-653: Ship anyway stays reachable from the line', !!g.anyway && !!sent && sent.verb === 'ship' && sent.anyway === true);
  g = gateOf(shipCard('c-920', { ahead: 1, conflicts: true }), {});
  check('c-653: a conflict with the base is a line, not a refusal', !!g.ship && !!g.why && /conflict/.test(g.why.textContent));
  /* 5: the way into a running house is on the row */
  const busy = shipCard('c-921', { ahead: 1 }, { house: BUSY });
  let K = page([busy], { desk: true });
  loaded(K, busy, {});
  const deskRow = deck.wrap(K.groupRow(busy, K.gateActions(busy).concat(K.cardItems(busy)), 'pane'), K);
  const top = deskRow.childNodes.filter((n) => n.nodeType === 1);
  const direct = top.map((n) => n.getAttribute('data-key'));
  check('c-653: the line leads the desk row', direct[0] === 'ship-why');
  const talkGroup = top.filter((n) => n.getAttribute('data-key') === 'g-talk')[0];
  check('c-653: Open in Claude app is on the row, Drop in beside it',
        !!talkGroup && deck.labelOf(deck.buttons(talkGroup)[0]) === 'Open in Claude app'
        && labelsAll(deskAll(K, busy)).indexOf('Drop in') >= 0);
  /* the stop stands alone: not inside a split group, and the Card group's rest is its own control */
  const stop = deck.all(deskRow, (n) => n.getAttribute && n.getAttribute('data-key') === 'stop')[0];
  check('c-653: a critical action is never the lead of a split group',
        !!stop && stop.parentNode === deskRow && !deck.hasClass(stop, 'amain') && direct.indexOf('archive') > direct.indexOf('stop'));
  const nolink = shipCard('c-922', {}, {});
  delete nolink.options.app_link;
  K = page([nolink], { desk: true });
  check('c-653: a house with no link on record offers Resume and open in app',
        deck.labels(deck.wrap(K.cardItems(nolink), K)).indexOf('Resume and open in app') >= 0);
  /* r1.F1: a house in its turn with no link on record still has its way in */
  const busyNoLink = shipCard('c-924', {}, { house: BUSY });
  delete busyNoLink.options.app_link;
  K = page([busyNoLink], { desk: true });
  const way = deck.wrap(K.cardItems(busyNoLink), K).childNodes.filter((n) => n.getAttribute && n.getAttribute('data-key') === 'open-app')[0];
  check('c-653: a working house with no link on record offers Open in Claude app, which fetches it',
        !!way && deck.labelOf(way) === 'Open in Claude app' && /house\.open_app/.test(way.getAttribute('data-pend') || ''));
  /* the phone: the way in is a primary, and Stop session is under More actions */
  K = page([busy]);
  loaded(K, busy, {});
  const p = paneParts(K, busy);
  check('c-653: the phone leads with the line and the way in',
        keysIn(p.bar).indexOf('ship-why') >= 0 && primaries(p.bar).indexOf('Open in Claude app') >= 0);
  K.App.sheet = { kind: 'actions', id: busy.id };
  check('c-653: Stop session is under More actions on the phone',
        deck.labels(deck.wrap(K.actionsSheet(K.App.sheet), K)).indexOf('Stop session') >= 0);
})();

/* ---------- c-667: a proposal card's outcome tap is Adopt, and its answer is said ---------- */
(function () {
  const gate = { repo: null, stage: 'review', output_ref: '/state/cards/c-820/claude-md.md',
    derived: { outcome_gate: true, needs_you: true } };
  const tier = deck.card('c-820', Object.assign({}, gate, { options: { tier_proposal: 'personal/api' } }));
  const flow = deck.card('c-821', Object.assign({}, gate, { options: { flow_proposal: 'work' } }));
  const K = page([tier, flow]);
  const labels = deck.labels(deck.wrap(K.gateActions(tier), K));
  check('c-667: a proposal\'s outcome button is Adopt, never Done: ' + labels.join(', '),
        labels.indexOf('Adopt') >= 0 && labels.indexOf('Done') < 0 && labels.indexOf('Approve outcome') < 0);
  const asked = K.adoptConfirm ? [K.adoptConfirm(tier), K.adoptConfirm(flow)] : ['', ''];
  check('c-667: its confirm says it writes the draft, and into what: ' + asked.join(' / '),
        asked[0].indexOf('Adopt c-820? This writes its draft into ') === 0 && /api repo/.test(asked[0]) && /personal space/.test(asked[0])
        && /flow of the work space/.test(asked[1]));
  const tip = String(K.tip('approve-outcome', tier));
  check('c-667: its tip says what is written and that nothing changes until the tap: ' + tip,
        tip.indexOf('Adopt: ') === 0 && /api repo/.test(tip) && /Nothing changes until/.test(tip) && !/Nothing is published/.test(tip));
  const body = { verb: 'approve', gate: 'outcome', id: 'c-820' };
  const said = (r) => { const s = K.sentence(body, r); return typeof s === 'string' ? { text: s, err: false } : s; };
  const done = said({ where: '/t/CLAUDE.md', note: 'adopted into /t/CLAUDE.md', stage: 'done' });
  const held = said({ where: '/t/CLAUDE.md', note: 'adopted, but c-820 was not moved to done: held', stage: 'review' });
  check('c-667: an adopting approve says its note: ' + done.text, done.text === 'adopted into /t/CLAUDE.md' && !done.err);
  check('c-667: adopted but not moved is said as an error', held.text.indexOf('was not moved to done') > 0 && held.err === true);
  check('c-667: any other outcome approve says what it said', said({ card: {} }).text === 'c-820 approved');
})();

/* ---------- c-667 review 2: Adopt wherever the proposal is filed, and nothing else moved ---------- */
(function () {
  const stop = { stopPropagation: function () {} };
  const tapped = (K, c) => {
    let asked = null;
    K._win.confirm = function (text) { asked = text; return false; };
    const row = deck.wrap(K.gateActions(c), K);
    const b = deck.buttons(row).filter((n) => n.getAttribute('data-key') === 'approve-outcome')[0];
    b.onclick({ stopPropagation: stop.stopPropagation, currentTarget: b });
    return { label: b.textContent, asked: asked };
  };
  const gate = { stage: 'review', output_ref: '/state/cards/x/out.md', derived: { outcome_gate: true, needs_you: true } };
  /* a proposal filed outside personal (no personal space: the first space with no pack) */
  const away = deck.card('c-830', Object.assign({}, gate, { space: 'home', repo: null, options: { flow_proposal: 'work' } }));
  let got = tapped(page([away]), away);
  check('c-667: a proposal outside personal is Adopt with the Adopt confirm: ' + got.label + ' / ' + got.asked,
        got.label === 'Adopt' && got.asked === 'Adopt c-830? This writes its draft into the flow of the work space.');
  /* F3: a proposal with slices still reads the Adopt confirm, as its label and tip do */
  const sliced = deck.card('c-831', Object.assign({}, gate, { space: 'home', repo: null, options: { tier_proposal: 'home' }, children: ['c-839'] }));
  let SK = page([sliced]);
  got = SK.tracking(sliced) ? tapped(SK, sliced) : { label: 'not tracking', asked: '' };
  check('c-667: a proposal with slices asks the Adopt confirm, never the tracking one: ' + got.label + ' / ' + got.asked,
        got.label === 'Adopt' && got.asked === 'Adopt c-831? This writes its draft into the tier (the rules) of the home space.');
  /* a kanban drop on done asks the same thing */
  const dropped = (c) => {
    const K = page([c]);
    let asked = null;
    K._win.confirm = function (text) { asked = text; return false; };
    globalThis.confirm = K._win.confirm;
    if (K.dropOn) K.dropOn(c, 'done', null);
    delete globalThis.confirm;
    return asked;
  };
  const tier = deck.card('c-832', Object.assign({}, gate, { repo: null, options: { tier_proposal: 'personal/api' } }));
  check('c-667: a drop on done asks the Adopt confirm for a proposal: ' + dropped(tier),
        dropped(tier) === 'Adopt c-832? This writes its draft into the tier (the rules) of the api repo in the personal space.');
  /* ORDINARY cards: the label and the confirm they always had, to the letter */
  const research = deck.card('c-833', Object.assign({}, gate, { repo: null }));
  got = tapped(page([research]), research);
  check('c-667: research keeps Done and its confirm: ' + got.label + ' / ' + got.asked,
        got.label === 'Done' && got.asked === 'Mark c-833 done?');
  const repo = deck.card('c-834', Object.assign({}, gate, { repo: 'keel' }));
  got = tapped(page([repo]), repo);
  check('c-667: a repo card keeps Approve outcome and its confirm: ' + got.label + ' / ' + got.asked,
        got.label === 'Approve outcome' && got.asked === 'Approve the outcome of c-834? This publishes it.');
  check('c-667: an ordinary drop keeps its confirm: ' + dropped(repo), dropped(repo) === 'Approve the outcome of c-834?');
})();

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
