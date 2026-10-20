/* The live strip (c-599): what a house is doing now, one line on its card.
 *
 * The facts are the harness's, read on the machine the house runs on (keel/livestrip.py,
 * keel/livetail.py): its status in the agents listing, how long its turn has run, its last
 * tool, its todo progress, its jobs, the harness's own line of what it is doing, and when
 * each was so. The board adds two things at once: the newest Notification of the turn
 * (`c.notice`, "waiting on a prompt") and a tap still in flight (`derived.relays`).
 *
 * FACTS WITH AGES, NEVER A VERDICT. Nothing here says a house is stuck; a tool running for
 * nine minutes says "running 9m" and he decides what that means.
 *
 * Two sources, the newer wins: `c.live` in the state document, and a `live <id> <json>`
 * line on the event stream (`heardLive`), which is kept in `App.strip` and patches the card
 * without a fetch. EVERY AGE IS MEASURED ON ONE CLOCK: the reading machine's own (`at` is
 * when it read, every other time is its own), plus how long this page has held it, so a
 * Mac a few seconds off the phone never shows a negative age.
 */
(function (K) {
  'use strict';
  var App = K.App, el = K.el;
  App.strip = App.strip || {};
  App.stripGot = App.stripGot || 0;
  /* A Notification older than the transcript's newest record by more than this is over:
     the house carried on after it. */
  var NOTICE_SLACK_MS = 2000;
  var PROMPT = 'idle_prompt';

  function ms(iso) { var t = iso ? Date.parse(iso) : NaN; return isNaN(t) ? null : t; }

  /* The facts to draw for a card and when this page got them: the stream's copy when it is
     newer than the document's (by the reading machine's own `at`), else the document's. */
  function liveOf(c) {
    if (!c) return null;
    var heard = App.strip[c.id], doc = c.live ? { facts: c.live, got: App.stripGot || Date.now() } : null;
    if (heard && heard.got >= (App.stripGot || 0)) {
      if (!heard.facts) return null;
      if (!doc || (ms(heard.facts.at) || 0) >= (ms(doc.facts.at) || 0)) return heard;
    }
    if (heard && heard.facts && doc && (ms(heard.facts.at) || 0) > (ms(doc.facts.at) || 0)) return heard;
    return doc;
  }
  /* Seconds since `iso`, on the reading machine's clock. */
  function ageOf(entry, iso) {
    var at = ms(entry.facts.at), then = ms(iso);
    if (at === null || then === null) return null;
    return Math.max(0, Math.round((at - then + (Date.now() - entry.got)) / 1000));
  }
  function short(s) {
    if (s === null || s === undefined) return '';
    if (s < 60) return s + 's';
    if (s < 3600) return Math.round(s / 60) + 'm';
    if (s < 86400) return Math.round(s / 3600) + 'h';
    return Math.round(s / 86400) + 'd';
  }
  /* A Notification from this turn that nothing in the transcript has come after. */
  function noticeOf(c) {
    var n = c && c.notice;
    if (!n) return null;
    var l = liveOf(c), wrote = l && ms(l.facts.wrote_at), said = ms(n.at);
    if (wrote !== null && said !== null && wrote > said + NOTICE_SLACK_MS) return null;
    return n;
  }
  function prompting(c) { var n = noticeOf(c); return !!n && n.type !== PROMPT; }
  /* the house row the strip carries, when it is newer than the one the document drew */
  /* c-605: the strip follows a house only at these stages (keel/livestrip.py LIVE_STAGES); a card
     that leaves them is said `live <id> null` at once, which is "nothing live to say", not
     "no house". A merged card's house stays listed, so its done pane lost Stop until the
     next state document; the document's own row stands for it instead. */
  var STRIP_STAGES = { planning: 1, building: 1, review: 1, shipping: 1 };
  function stripHouse(c) {
    var heard = App.strip[c.id];
    if (!heard || heard.got < (App.stripGot || 0)) return undefined;
    if (!heard.facts) return STRIP_STAGES[c.stage] ? null : undefined;
    return heard.facts.house || null;
  }

  /* A reading older than this (two of the door's leases) is what the house WAS doing: its
     machine stopped saying (keel/livestrip.py STALE_SECONDS). The box stops drawing it as a
     house; the strip keeps it, said as the past, with its age. */
  var STALE_S = 120;
  function statusWord(c, l) {
    if (prompting(c)) return { text: 'waiting on a prompt', cls: 'acc' };
    var s = l.facts.status;
    if ((ageOf(l, l.facts.at) || 0) > STALE_S) return { text: 'was ' + (s || 'idle'), cls: 'plain' };
    if (s === 'working') return { text: 'working', cls: 'acc' };
    /* c-607: he closed it while it was idle, and nothing has resumed it yet */
    if (s === 'exited' && c.derived && c.derived.closed_idle) return { text: 'closed while idle', cls: 'plain' };
    if (s === 'exited') return { text: 'exited', cls: 'crit' };
    return { text: s || 'idle', cls: 'warn' };
  }
  /* c-607: how much memory the house's process tree holds, as its machine read it; with an
     idle house, how long it has been idle beside it: "idle 42m, 0.8 GB" */
  function memPart(l) {
    var mb = l.facts.mem_mb;
    return typeof mb === 'number' && mb > 0 && l.facts.status !== 'exited' && K.memText ? K.memText(mb) : null;
  }
  function idlePart(l) {
    var f = l.facts, mem = memPart(l);
    if (f.status !== 'idle' || !f.turn_ended_at) return null;
    return 'idle ' + short(ageOf(l, f.turn_ended_at)) + (mem ? ', ' + mem : '');
  }
  function turnPart(l) {
    var f = l.facts;
    /* c-606: an exited session is in no turn, though its transcript never closed the last one */
    if (f.status === 'exited' && !f.turn_ended_at) return null;
    if (f.turn_at && !f.turn_ended_at) return 'in turn ' + short(ageOf(l, f.turn_at));
    if (f.turn_ended_at) return 'turn ended ' + short(ageOf(l, f.turn_ended_at)) + ' ago';
    return null;
  }
  function toolPart(l) {
    var t = l.facts.tool;
    if (!t) return null;
    var age = short(ageOf(l, t.at));
    return t.name + (t.what ? ': ' + t.what : '') + (t.done ? ' · ' + age + ' ago' : ' · running ' + age);
  }
  function todoPart(l) {
    var d = l.facts.todos;
    if (!d || !d.total) return null;
    return 'todos ' + d.done + '/' + d.total + (d.active ? ': ' + d.active : '');
  }
  function jobsPart(l) {
    var jobs = (l.facts.jobs || []).length, agents = (l.facts.agents || []).length, out = [];
    if (agents) out.push(agents + (agents === 1 ? ' subagent' : ' subagents'));
    if (jobs) out.push(jobs + (jobs === 1 ? ' job' : ' jobs'));
    return out.length ? out.join(', ') : null;
  }
  function tapPart(c) {
    var r = (c.derived && c.derived.relays || [])[0];
    return r ? r.what + ' asked of ' + r.to + (r.at ? ' ' + K.ago(r.at) : '') : null;
  }
  /* The second line: the prompt it is waiting on, else the harness's own line of what it is
     doing, else (its turn over) what Stop last said. */
  function saidLine(c, l) {
    var n = noticeOf(c);
    if (n && n.type !== PROMPT) return { text: n.message || 'a permission prompt', cls: 'lv-ask' };
    if (l.facts.detail && l.facts.status === 'working') return { text: l.facts.detail, cls: '' };
    if (l.facts.status !== 'working' && c.last_said) return { text: 'last said: ' + K.firstLine(c.last_said), cls: '' };
    if (l.facts.detail) return { text: l.facts.detail, cls: '' };
    return null;
  }

  /* Whether this card's strip carries its last words as its second line (c-606): a tile
     that would say them again under the strip asks first. */
  function stripSaysLast(c) {
    var l = liveOf(c), said = l ? saidLine(c, l) : null;
    return !!(said && said.text.indexOf('last said: ') === 0);
  }
  K.stripSaysLast = stripSaysLast;

  /* The strip itself, or null for a card with nothing live to say. `underWord` is a caller
     that draws the house word right above it (the Now tile, the pane), where the same word
     twice is noise: the status is left out when the house word already says it. */
  function liveStrip(c, underWord) {
    var l = liveOf(c);
    if (!l) return null;
    drawn[c.id + (underWord ? '/under' : '')] = { c: c, underWord: !!underWord };
    var w = statusWord(c, l), said = saidLine(c, l), idle = w.text === 'idle' ? idlePart(l) : null;
    /* a-72: a shipping house's idle word says when the drain closes it: "idle 1h40m, closes at 2h, 0.8 GB" */
    var due = w.text === 'idle' && K.shipIdleText ? K.shipIdleText(c) : null;
    if (due) idle = due + (memPart(l) ? ', ' + memPart(l) : '');
    var word = underWord && K.houseWord ? K.houseWord(c) : null;
    /* an idle house's word carries its age and its memory: "idle 42m, 0.8 GB" (c-607) */
    var status = idle ? el('span', { class: 'lv-status sw ' + w.cls, text: idle })
      : word && word.text === w.text ? null : el('span', { class: 'lv-status sw ' + w.cls, text: w.text });
    var parts = (idle ? [] : [turnPart(l), memPart(l)])
      .concat([toolPart(l), todoPart(l), jobsPart(l), tapPart(c)]).filter(Boolean);
    var read = ageOf(l, l.facts.at);
    return el('div', { class: 'livestrip', 'data-key': 'live', 'data-live': c.id, 'data-under': underWord ? '1' : null },
      el('div', { class: 'lv-line' },
        status,
        parts.map(function (p, i) { return el('span', { class: 'lv-part', 'data-key': 'p' + i, text: p }); }),
        el('span', { class: 'lv-read ink2', text: (l.facts.host ? l.facts.host + ' · ' : '') + 'read ' + short(read) + ' ago' })),
      said ? el('div', { class: 'lv-said ' + said.cls, 'data-key': 'said', text: said.text }) : null);
  }

  /* THE AGES TICK (c-605). Every age above is measured when the strip is drawn, and a
     strip is drawn again only when something redraws the page, so between two readings
     "turn ended 0s ago" stood for sixteen seconds. Once a second each strip on the page is
     drawn again from the card it was last drawn for (`drawn`, the newest wins) and morphed
     into place: the same reading, on the clock (`ageOf` adds how long the page has held it). */
  var drawn = {};
  function tickLive(strips) {
    Array.prototype.forEach.call(strips || [], function (node) {
      var id = node.getAttribute('data-live'), under = node.getAttribute('data-under') === '1';
      var was = drawn[id + (under ? '/under' : '')];
      if (!was) return;
      var fresh = liveStrip(was.c, was.underWord);
      if (fresh) K.morph(node, fresh);
    });
  }
  setInterval(function () {
    if (document.visibilityState === 'hidden') return;
    tickLive(document.querySelectorAll('.livestrip[data-live]'));
  }, 1000);

  /* `live <id> <json>` from the stream: kept, and the page drawn again (at most once a
     frame's worth, since a busy house says something every few seconds). */
  var drawTimer = null;
  function heardLive(line) {
    var first = line.indexOf(' '), second = line.indexOf(' ', first + 1);
    if (first < 0 || second < 0) return;
    var id = line.slice(first + 1, second), facts;
    try { facts = JSON.parse(line.slice(second + 1)); } catch (e) { return; }
    App.strip[id] = { facts: facts && typeof facts === 'object' ? facts : null, got: Date.now() };
    if (App.view === 'plan') { if (K.planLive) K.planLive(id); return; }
    if (drawTimer) return;
    drawTimer = setTimeout(function () { drawTimer = null; K.render(); }, 150);
  }

  K.liveOf = liveOf; K.liveStrip = liveStrip; K.noticeOf = noticeOf; K.prompting = prompting;
  K.stripHouse = stripHouse; K.heardLive = heardLive; K.tickLive = tickLive; K.liveAge = ageOf; K.liveShort = short;
})(window.Keel);
