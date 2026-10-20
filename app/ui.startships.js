/* How work ships, the first run's step 8 (c-678, rewritten for a newcomer in c-732), loaded
 * before `ui.start.js`, which reads it as `K.shipsScreen(report, step, parts)`.
 *
 * IT FOLLOWS FROM THE STEP BEFORE (c-758): each space opens with what was chosen on Where
 * finished work goes, the connection by name with its own description (the pack's words, read
 * from its row), or that work stays on this computer, and a way back to change it. "You
 * chose" is said only of a choice that was made (r1.F8): a connection that is on, or that
 * step recorded as seen; a user who skipped it or never opened it reads "Work for <space>
 * stays on this computer". The first
 * teammate to set Shipyard up could not tell that this page came from that choice.
 *
 * ONLY QUESTION 1 IS ASKED OF EVERYONE (c-758, the owner's word): a teammate with a connection
 * on read the Bosun questions as required. So the order is what was chosen, question 1, then
 * the drawing headed as ALREADY SET with Keep how it works now as the normal way on, and only
 * then the Bosun questions, under "Only if your team works differently". The questions come
 * from `step.asks` (keel/bases.py's ASKS, the list Bosun's brief asks from too). The numbered
 * notes below describe each part, not the order they are drawn in:
 *
 * 1. "Where does work start?" is answered on the page: the space's bases, the repo's default
 *    branch filled in, others added (staging). Save writes `[spaces.<name>] bases` through
 *    `setup.settings.save`, as every setting is, and every card form then offers them. Where
 *    the space's pack lists its own, the page shows those and says so.
 * 2. to 5. are answered in Bosun's session, and the page says why: Bosun turns the answers
 *    into a drawing, which takes a conversation, and asks back what it cannot place. Start
 *    this with Bosun files the card it drafts on (`setup.flow.draft`), as before.
 * 3. The drawing (`K.flowPicture`, app/ui.flowpicture.js): the flow the space has now, or,
 *    when Bosun's draft waits, "What you told Bosun" (the draft's description) above the two
 *    drawings, each with its one sentence, so the words and the drawing can be checked
 *    against each other; Adopt Bosun's draft (`setup.flow.adopt`, the only thing that writes the flow) and
 *    Keep how it works now. Adopted: "Adopted. Bosun's draft is how this space ships now."
 *    A space whose connection has no code host has nothing to draw: the panel says why in
 *    the server's own sentence (`flow.held`, keel/flows.py), never an empty box (c-758).
 * 4. Last, "New cards in <space> start as:" Attended or Autonomous (c-729).
 *
 * THE DRAFT FOLLOWS BOSUN, as before: whether a proposal is open, and its stage, come with
 * the state (`flow.proposal`); the draft drawn as a flow comes with the Setup report
 * (`spaces.<name>.flow_draft`), read again whenever the proposal's card or stage moved, and
 * asked for again on a timer, five times, when it is at review and not carried. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  var seen = null;      /* the proposals' signature the report was last read for */
  var tries = {};       /* proposal card -> how often the report was asked for its draft again */
  var armed = {};       /* proposal card -> a timer is set */
  var typed = {};       /* space -> the bases as the user is editing them, until saved */
  var adding = {};      /* space -> the branch name being typed */
  var RETRY_MS = 3000, RETRIES = 5;

  var STYLE = [
    '.ships{display:flex;flex-direction:column;gap:16px}',
    '.ships-panel{border:1px solid var(--hair-hi);background:var(--s1);padding:16px;display:flex;flex-direction:column;gap:12px;font-size:14px;line-height:1.5;min-width:0}',
    '.ships-panel.flag{border-color:var(--accent)}',
    '.ships-panel h3{margin:0;font-size:16px}.ships-panel p{margin:0}',
    '.ships-num{font-family:var(--mono);color:var(--accent-ink);margin-right:8px}',
    '.ships-eg{color:var(--ink-2);font-size:13px}.ships-eg i{font-style:normal;color:var(--ink)}',
    '.ships-asks{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:12px}',
    '.ships-asks li{display:flex;flex-direction:column;gap:2px}',
    '.ships-bases{display:flex;flex-wrap:wrap;gap:8px;align-items:center}',
    '.ships-base{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--accent);background:var(--accent-soft);color:var(--accent-ink);padding:0 4px 0 12px;min-height:36px;font-family:var(--mono);font-size:13px}',
    '.ships-base button{border:0;background:none;color:inherit;font:inherit;min-width:32px;min-height:32px;cursor:pointer}',
    '.ships-add{display:flex;gap:8px;flex-wrap:wrap}.ships-add input{min-height:44px;flex:1 1 200px;min-width:0}',
    '.ships-two{display:grid;grid-template-columns:minmax(0,1fr);gap:24px}',
    '.ships-side{display:flex;flex-direction:column;gap:8px;min-width:0}',
    '.ships-quote{border-left:3px solid var(--hair-hi);padding:4px 12px;margin:0;color:var(--ink)}',
    '.ships-btns{display:flex;gap:8px;flex-wrap:wrap}.ships-btns .btn{min-height:44px}.ships-btns .btn.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-ink)}',
    '.ships-line{font-size:13px;color:var(--ink-2)}',
    '.ships-chose{border-color:var(--good)}',
    '.ships-held{border-left:3px solid var(--warn);background:var(--warn-soft);padding:8px 12px}'
  ].join('\n');
  function styleOnce() {
    if (document.getElementById('startships-style')) return;
    var node = document.createElement('style');
    node.id = 'startships-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }
  function session() { return (App.data && (App.data.console || App.data.bosun)) || {}; }
  function flowOf(name) { return (((App.data || {}).spaces || {})[name] || {}).flow || null; }
  function asksOf(step) { return (step && step.asks) || []; }
  function basesOf(step, space) { return ((step && step.bases) || {})[space] || { bases: [], suggested: null, pack: false }; }
  /* the bases the drawing names: the space's, else the branch its repo has out */
  function drawn(step, space) {
    var b = basesOf(step, space);
    return b.bases.length ? b.bases : b.suggested ? [b.suggested] : [];
  }
  function eg(text) { return el('p', { class: 'ships-eg' }, 'For example: ', el('i', { text: '"' + text + '"' })); }
  function num(n) { return el('span', { class: 'ships-num', text: n + '.' }); }

  /* ---------- what was chosen on the step before (c-758) ---------- */

  function packOf(report, name) { return (report.packs || []).filter(function (p) { return p.name === name; })[0] || null; }
  /* a connection Bosun is still drafting for this space: work stays here meanwhile, and the page says so */
  function drafting(report, space) {
    var open = (((report.builder || {}).connection) || {}).open;
    return open && (!open.space || open.space === space) ? open : null;
  }
  /* the choice step is recorded as seen: the user went on past it with work kept on this computer */
  function choiceSeen(parts) {
    var step = (parts.steps ? parts.steps() : []).filter(function (s) { return s.id === 'integrations'; })[0];
    return !!(step && step.seen);
  }
  /* The opening's sentence about the drawing, worded from what is drawn (fix check): a
     space's own flow is its own, adopted in place of the usual path; nothing drawn promises
     no drawing; else the drawing is the path just named, already set */
  function drawnSaid(space, flow, on) {
    if (flow.held) return 'Nothing is drawn for it below yet, and the page says why there. ';
    if (flow.source === 'space') return 'The drawing below is ' + space + '\'s own flow, adopted in place of ' +
      (on ? on + '\'s usual path. ' : 'the usual path. ');
    return 'The drawing below shows that path, and it is already set. ';
  }
  function chose(report, space, parts, flow) {
    var on = (report.spaces[space] || {}).pack, row = on ? packOf(report, on) : null, open = on ? null : drafting(report, space);
    var made = !!on || choiceSeen(parts);
    var back = parts.open ? el('div', { class: 'ships-btns' }, el('button', { class: 'btn sm', 'data-key': 'ships-chose-back',
      onclick: function () { parts.open('integrations', space); } }, made ? 'Change it on Where finished work goes' : 'Choose on Where finished work goes')) : null;
    if (on) return el('div', { class: 'ships-panel ships-chose', 'data-key': 'ships-chose-' + space },
      el('h3', { 'data-key': 'ships-chose-said', text: 'You chose ' + on + ' for ' + space + ', so this page starts from it' }),
      row && row.description ? [el('span', { class: 'label', text: 'What ' + on + ' does, in its own words' }),
        el('p', { class: 'ships-quote', 'data-key': 'ships-chose-words', text: row.description })] : null,
      el('p', { text: drawnSaid(space, flow, on) + 'You answer question 1 here; changing the rest is optional.' }),
      back);
    return el('div', { class: 'ships-panel ships-chose', 'data-key': 'ships-chose-' + space },
      el('h3', { 'data-key': 'ships-chose-said', text: (made ? 'You chose to keep work for ' + space + ' on this computer'
        : 'Work for ' + space + ' stays on this computer') + ', so this page starts from that' }),
      el('p', { text: 'Finished work is merged on this computer, and you push when you say. ' + drawnSaid(space, flow, null) +
        'You answer question 1 here; changing the rest is optional.' }),
      open ? el('p', { 'data-key': 'ships-chose-draft', text: 'Bosun is drafting a connection for ' + space + ' (' + open.card +
        '). It is not finished, so this page still shows work kept on this computer.' }) : null,
      el('p', { class: 'ships-line', text: 'If your team reviews work on a code host, choose a connection first.' }),
      back);
  }

  /* ---------- the asking ---------- */

  /* 1. Where does work start? On the page: a list Shipyard keeps as it is */
  function starts(space, step) {
    var ask = asksOf(step)[0] || { ask: 'Where does work start?', example: 'main' };
    var b = basesOf(step, space), saved = b.bases.slice();
    /* c-732 r1.F4, F5: a repo whose cards land on an integration branch offers no choice */
    if (b.integration) {
      return el('div', { class: 'ships-panel', 'data-key': 'ships-bases-' + space },
        el('h3', {}, num(1), ask.ask),
        el('p', { 'data-key': 'ships-bases-integration', text: 'Every card here starts from ' + b.integration +
          ' and goes back into it. ' + b.integration + ' is where Shipyard collects approved work until you ' +
          'put it live, so there is nothing to choose here.' }));
    }
    if (b.pack) {
      return el('div', { class: 'ships-panel', 'data-key': 'ships-bases-' + space },
        el('h3', {}, num(1), ask.ask),
        el('p', { 'data-key': 'ships-bases-pack', text: b.listed && saved.length
          ? 'Your connection lists these, and every new card offers them: ' + saved.join(', ') + '.'
          : 'Your connection has a Base branch field of its own on every new card, so you name the branch there.' }));
    }
    var list = typed[space] || (saved.length ? saved : b.suggested ? [b.suggested] : []);
    var changed = JSON.stringify(list) !== JSON.stringify(saved);
    var put = function (next) { typed[space] = next; K.renderBody(); };
    var add = function () {
      var name = String(adding[space] || '').trim();
      if (!name || list.indexOf(name) >= 0) return;
      adding[space] = '';
      put(list.concat([name]));
    };
    return el('div', { class: 'ships-panel', 'data-key': 'ships-bases-' + space },
      el('h3', {}, num(1), ask.ask),
      el('p', { text: 'The branches a card\'s work can start from. Each card goes back to the branch it started from. ' +
        'You pick one on the card; a card that picks none starts where it always did. Save applies at once, to new cards only.' }),
      eg(ask.example),
      el('div', { class: 'ships-bases', 'data-key': 'ships-bases-list' }, list.map(function (name) {
        return el('span', { class: 'ships-base', 'data-key': 'ships-base' }, name,
          el('button', { type: 'button', 'aria-label': 'Remove ' + name, onclick: function () {
            put(list.filter(function (n) { return n !== name; }));
          } }, '×'));
      })),
      el('div', { class: 'ships-add' },
        el('input', { type: 'text', 'data-fk': 'ships-add-' + space, 'aria-label': 'Another branch', placeholder: 'another branch, like staging',
          value: adding[space] || '', oninput: function (ev) { adding[space] = ev.target.value; },
          onkeydown: function (ev) { if (ev.key === 'Enter') add(); } }),
        el('button', { type: 'button', class: 'btn', onclick: add }, 'Add'),
        el('button', { type: 'button', class: 'btn' + (changed && list.length ? ' primary' : ''), disabled: changed && list.length ? null : true,
          onclick: function () {
            K.setupParts.change({ verb: 'setup.settings.save', changes: [{ table: 'space', space: space, key: 'bases', value: list }] },
              'saved').then(function (r) { if (r) delete typed[space]; });
          } }, 'Save')),
      el('p', { class: 'ships-line', 'data-key': 'ships-bases-said', text: saved.length && !changed
        ? 'Saved. Every new card offers ' + saved.join(', ') + '.'
        : !saved.length && !typed[space] && b.suggested ? b.suggested + ' is your repo\'s default branch, filled in for you. Press Save to keep it.'
        : 'You answer this one here: Shipyard keeps the list as it is.' }));
  }

  /* 2. to 5. In Bosun's session, below what is already set, and said to be optional */
  function rest(space, flow, draft, step, ready) {
    var asks = asksOf(step).slice(1), attach = session().attach;
    return el('div', { class: 'ships-panel', 'data-key': 'ships-tell' },
      el('h3', { text: 'Only if your team works differently' }),
      /* fix check D8: said from the state: with nothing drawn (`flow.held`) there is no drawing above to compare with */
      el('p', { 'data-key': 'ships-optional', text: 'This part is optional. ' + (flow.held
        ? 'Nothing is drawn for ' + space + ' yet. To have your team\'s way drawn, tell Bosun how it ships: ' +
          'a short conversation, in which Bosun asks the questions below and turns your answers into a drawing. '
        : 'If the drawing above is not how your team ships, tell Bosun how it does: ' +
          'a short conversation, in which Bosun asks the questions below and turns your answers into a new drawing. ') +
        'Nothing changes until you press Adopt, and no code is written.' }),
      el('p', { class: 'ships-line', text: 'You answer them in Bosun\'s session, not on this page. Bosun asks them one at a time, and asks back anything ' +
        'it cannot place rather than guess.' }),
      el('ol', { class: 'ships-asks', 'data-key': 'ships-asks' }, asks.map(function (a, i) {
        return el('li', { 'data-key': 'ships-ask' }, el('strong', {}, num(i + 2), a.ask), eg(a.example));
      })),
      ready ? el('div', { class: 'ships-line', 'data-key': 'ships-drafting', text: 'Bosun\'s draft is above: check it against what you said.' })
        : draftLine(space, flow, draft),
      attach ? K.command(attach) : null);
  }
  function draftLine(space, flow, draft) {
    var p = flow.proposal;
    if (!p) return el('div', { class: 'ships-btns' }, el('button', { class: 'btn', onclick: function () {
      K.setupParts.change({ verb: 'setup.flow.draft', space: space }, 'Bosun is ready to ask you');
    } }, 'Start this with Bosun'));
    if (draft && draft.error) return el('div', { class: 'ships-line', 'data-key': 'ships-draft-error',
      text: 'Bosun\'s draft does not check yet, so it is not shown: ' + draft.error });
    if (p.stage === 'review') {
      if ((tries[p.card] || 0) >= RETRIES) return el('div', { class: 'ships-line', 'data-key': 'ships-draft-unread' },
        el('span', { text: 'Bosun\'s draft could not be read. Open its card to read it there, or tell Bosun in its session. ' }),
        el('button', { class: 'btn sm', onclick: function () { K.go('cards', p.card); } }, 'Open ' + p.card));
      if (!armed[p.card]) { armed[p.card] = true; setTimeout(function () { retry(p.card); }, RETRY_MS); }
    }
    return el('div', { class: 'ships-line', 'data-key': 'ships-drafting', text: p.stage === 'inbox'
      ? 'Bosun is ready to ask you (' + p.card + '). Open its session with the command below and say hello.'
      : p.stage === 'review' ? 'Reading Bosun\'s draft...' : 'Bosun is drafting (' + p.card + ').' });
  }
  /* what the timer does: the report asked for once more, and counted */
  function retry(card) {
    armed[card] = false;
    tries[card] = (tries[card] || 0) + 1;
    if (K.loadSetup) K.loadSetup(0);
    if (tries[card] >= RETRIES && K.renderBody) K.renderBody();
  }
  K.shipsRetry = retry;

  /* ---------- the showing ---------- */

  var ONLY = 'Only the arrows marked you are buttons on a card. The rest is a picture of what happens.';
  function picture(space, flow, own, step, key) {
    return K.flowPicture(flow, { key: key, space: space, bases: drawn(step, space), attach: session().attach,
      push: own && own.push && own.repos.length ? own.remote : null,
      onBases: function () {
        var box = document.querySelector('[data-key="ships-bases-' + space + '"]');
        if (box && box.scrollIntoView) box.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } });
  }
  /* Keep how it works now goes on to the next step, and the step is then seen (c-729): it says Kept */
  function keep(parts, primary, step) {
    var kept = !!(step && step.seen);
    return parts.next ? el('button', { class: 'btn' + (kept ? ' on' : primary ? ' primary' : ''), 'aria-pressed': kept ? 'true' : 'false',
      'data-key': 'ships-keep', onclick: parts.next }, kept ? 'Kept' : 'Keep how it works now') : null;
  }
  function waiting(space, flow, draft, own, parts, step) {
    return el('div', { class: 'ships-panel flag', 'data-key': 'ships-draft-' + space },
      el('h3', { text: 'Bosun has a draft: check it against what you said' }),
      el('span', { class: 'label', text: 'What you told Bosun' }),
      el('p', { class: 'ships-quote', 'data-key': 'ships-agreed', text: draft.flow.description }),
      /* one above the other, the draft first: each drawing needs the width to be read */
      el('div', { class: 'ships-two' },
        el('div', { class: 'ships-side' }, el('span', { class: 'label', text: 'Bosun\'s draft' }), picture(space, draft.flow, own, step, 'ships-theirs')),
        el('div', { class: 'ships-side' }, el('span', { class: 'label', text: 'How it works now' }), picture(space, flow, own, step, 'ships-now'))),
      el('p', { class: 'ships-line', text: 'Read the sentence under Bosun\'s draft. If it is not what you said, tell Bosun what to change ' +
        'in its session. ' + ONLY }),
      el('div', { class: 'ships-btns' },
        el('button', { class: 'btn primary', onclick: function () {
          K.setupParts.change({ verb: 'setup.flow.adopt', card: draft.card }, 'adopted');
        } }, 'Adopt Bosun\'s draft'),
        keep(parts, false, step)));
  }
  /* c-758: nothing to draw, and why, in the server's sentence; the way on is still there */
  function heldPanel(space, flow, parts) {
    return el('div', { class: 'ships-panel', 'data-key': 'ships-now-' + space },
      el('h3', { text: 'Nothing is drawn for ' + space + ' yet' }),
      el('p', { class: 'ships-held', 'data-key': 'ships-held', text: flow.held }),
      /* r1.F8: this advice fits a connection with no code host only (`held_codehost`,
         keel/flows.py); any other reason is the server's own sentence, and nothing is added */
      flow.held_codehost ? el('p', { 'data-key': 'ships-held-advice', text: 'Go back to Where finished work goes and turn on a connection that has a code host, ' +
        'or keep work on this computer. The drawing appears here once one of those is true.' }) : null,
      el('div', { class: 'ships-btns' },
        parts.open ? el('button', { class: 'btn primary', 'data-key': 'ships-held-back', onclick: function () { parts.open('integrations', space); } },
          'Back to Where finished work goes') : null));
  }
  /* headed as already set (the owner's word): by the connection that is on, or by work kept here */
  function setSaid(space, on) {
    return on ? 'This is how ' + on + ' ships work for ' + space + ', and it is already set'
      : 'Work for ' + space + ' is merged on this computer and pushed when you say, and that is already set';
  }
  /* The heading says what is DRAWN (fix check D7): a space's own flow is its own whatever a
     proposal is doing, so it is never headed as the connection's path or as work kept here */
  function standing(space, flow, own, parts, step, on) {
    if (flow.held) return heldPanel(space, flow, parts);
    var mine = flow.source === 'space', adopted = mine && !flow.proposal;
    return el('div', { class: 'ships-panel', 'data-key': 'ships-now-' + space },
      el('h3', { text: adopted ? 'How work ships in ' + space : mine ? 'This is how ' + space + ' ships work now: your own flow' : setSaid(space, on) }),
      mine ? null : el('p', { 'data-key': 'ships-set-said', text: 'Keeping it is all most people do: press Keep how it works now and go on.' }),
      !adopted ? null : flow.adopted
        ? el('p', { 'data-key': 'ships-adopted' }, el('strong', { text: 'Adopted. ' }), 'Bosun\'s draft is how this space ships now.')
        : el('p', { 'data-key': 'ships-own', text: 'This space ships by its own flow.' }),
      picture(space, flow, own, step, 'ships-now'),
      el('p', { class: 'ships-line', 'data-key': 'ships-only', text: ONLY }),
      adopted ? el('p', { text: 'Tell Bosun in its session if you want to change it again.' }) : null,
      adopted ? null : el('div', { class: 'ships-btns' }, keep(parts, true, step)));
  }

  /* ---------- the plan question ---------- */

  function plans(space, step) {
    var shows = (step.plans || {})[space];
    var chosen = shows === true ? 'attended' : shows === false ? 'autonomous' : null;
    return el('div', { class: 'ships-panel', 'data-key': 'ships-plans-' + space },
      el('h3', { 'data-key': 'ships-plans-ask', text: 'New cards in ' + space + ' start as:' }),
      K.startChoice({ key: 'ships-plans-' + space + '-how', label: 'New cards in ' + space + ' start as', chosen: chosen,
        options: [{ id: 'attended', title: 'Attended', said: 'It stops at its plan for you.' },
                  { id: 'autonomous', title: 'Autonomous', said: 'It plans and builds on its own.' }],
        pick: function (value) {
          K.setupParts.change({ verb: 'setup.settings.save', changes: [{ table: 'space', space: space, key: 'autonomy', value: value }] });
        } }),
      el('p', { class: 'ships-line', text: 'You can change it on any card.' }));
  }

  /* read the report again when a proposal's card or stage moved, or a flow's source did */
  function follow(names) {
    var sig = names.map(function (n) {
      var f = flowOf(n) || {}, p = f.proposal;
      return n + ':' + (f.source || '') + ':' + (p ? p.card + '@' + p.stage : '');
    }).join('|');
    if (seen !== null && sig !== seen && K.loadSetup) K.loadSetup(0);
    seen = sig;
  }

  function spacesOf(report) {
    var names = Object.keys(report.spaces || {});
    /* the spaces with a repo of the user's (the install's own repos, K.OWN_REPOS, are not) */
    var used = names.filter(function (n) {
      return (report.spaces[n].repos || []).some(function (r) { return !K.ownRepo(r.key); }) || (flowOf(n) || {}).proposal;
    });
    return used.length ? used : names;
  }

  K.shipsScreen = function (report, step, parts) {
    styleOnce();
    var names = spacesOf(report), lands = (report.start || {}).lands || {};
    follow(names);
    return el('div', { class: 'ships', 'data-key': 'ships' }, names.map(function (space) {
      var flow = flowOf(space), row = report.spaces[space] || {}, draft = row.flow_draft || null;
      if (!flow) return null;
      var own = row.pack ? null : (lands[space] || null);
      var ready = draft && draft.flow && flow.proposal && flow.proposal.card === draft.card && flow.proposal.stage === 'review';
      return parts.sub('ships-' + space, names.length > 1 ? space : null, [
        chose(report, space, parts, flow), starts(space, step),
        ready ? waiting(space, flow, draft, own, parts, step) : standing(space, flow, own, parts, step, row.pack || null),
        rest(space, flow, draft, step, ready), plans(space, step)]);
    }));
  };
})(window.Keel);
