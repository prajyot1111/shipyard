/* Idle houses (c-607): which houses are live but doing nothing, how much memory each holds,
 * and his tap that closes one.
 *
 * His words (2026-09-30): "show this somewhere that these houses are live and are taking
 * memory, and especially if it's in review and someone has left it ... an option to close
 * the idle house ... it will just pick it up with 5 to 15 seconds delay".
 *
 * The memory is `mem_mb` in the live strip's facts (keel/housemem.py): the RSS of the
 * house's process tree, read on the machine the house runs on, in memory only. A house with
 * no reading shows none, never a guess. Idle is the harness's word (the listed row is not in
 * a turn, `K.houseBusy`), never a guess from quiet either; the age is since its turn ended.
 *
 * Close idle house (`house.close_idle`, keel/idleclose.py) is drawn only while the house is
 * idle, and the server checks again when the tap lands. Its next review batch, a gate tap of
 * his, or his Resume brings it back with its conversation.
 */
(function (K) {
  'use strict';
  var el = K.el;
  var CLOSED_SAID = 'closed while idle: the next review or your tap resumes it (about 5 to 15 s)';
  /* by stage, as keel/idleclose.py says it on the card's note */
  var SAID_BY_STAGE = { shipping: CLOSED_SAID,
    review: 'closed while idle: your answer at the gate or your Resume brings it back (about 5 to 15 s)' };
  function closedSaid(c) { return SAID_BY_STAGE[K.stageOf(c)] || CLOSED_SAID; }
  /* Now's Close all idle: the houses left waiting on him or on a reviewer */
  var LEFT_STAGES = ['review', 'shipping'];

  function memText(mb) {
    if (mb === null || mb === undefined) return null;
    return mb < 100 ? mb + ' MB' : (mb / 1024).toFixed(1) + ' GB';
  }
  /* The reading, when the strip has a fresh one of a house that is still there. */
  function houseMem(c) {
    var l = K.liveOf ? K.liveOf(c) : null;
    if (!l || !l.facts || l.facts.status === 'exited') return null;
    var mb = l.facts.mem_mb;
    return typeof mb === 'number' && mb > 0 ? mb : null;
  }
  /* Seconds since its turn ended, by the strip's clock; else the drain's idle record, else
     since the session started. */
  function idleSeconds(c) {
    var l = K.liveOf ? K.liveOf(c) : null;
    if (l && l.facts && l.facts.turn_ended_at && K.liveAge) return K.liveAge(l, l.facts.turn_ended_at);
    var since = (c.idle && c.idle.since) || (K.houseOf(c) && K.houseOf(c).started_at);
    var t = since ? new Date(since).getTime() : NaN;
    return isNaN(t) ? null : Math.max(0, Math.round((Date.now() - t) / 1000));
  }
  function ageText(s) {
    if (s === null || s === undefined) return '';
    return K.liveShort ? K.liveShort(s) : Math.round(s / 60) + 'm';
  }
  /* Listed, out of a turn by the harness's one rule, and not his terminal's. */
  /* a-72: the drain closes a shipping house the harness still lists idle this long after its
     turn ended (derived.ship_idle, keel/shipidle.py). Said ahead, so it never surprises him:
     "idle 1h40m, closes at 2h". Null for any other house. */
  function hm(s) {
    if (s < 3600) return Math.max(0, Math.round(s / 60)) + 'm';
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h + 'h' + (m < 10 ? '0' : '') + m + 'm';
  }
  function shipIdleText(c) {
    var si = c && c.derived && c.derived.ship_idle;
    if (!si || K.stageOf(c) !== 'shipping' || !idleHouse(c)) return null;
    var t = new Date(si.since).getTime();
    if (isNaN(t)) return null;
    var idle = 'idle ' + hm(Math.max(0, (Date.now() - t) / 1000));
    /* c-651: a re-offered batch whose turn ended closes on the drain's next pass */
    return idle + (si.reoffer ? ', closes now (its turn on the re-offer ended)' : ', closes at ' + si.hours + 'h');
  }
  function idleHouse(c) {
    var h = K.houseOf(c);
    return !!h && h.recorded !== false && !K.houseBusy(c) && !K.inTerminal(c) && K.stageOf(c) !== 'done';
  }
  /* What the server would refuse is not offered: a job of its own still running, voice
     talking to it, a tap already on its way to the other machine. */
  function closeable(c) {
    return idleHouse(c) && LEFT_STAGES.indexOf(K.stageOf(c)) >= 0 && !(c.jobs && c.jobs.length) && !(c.derived && c.derived.voice_hold)
      && !((c.derived && c.derived.relays) || []).length && !!c.session_id;
  }
  function closeIdleBtn(c, cls) {
    return K.actionBtn('Close idle house', { verb: 'house.close_idle', id: c.id }, {
      cls: cls || '', title: K.tip ? K.tip('close-idle', c) : null,
      confirm: 'Close ' + c.id + '\'s idle house to free its memory? Its next review batch, ' +
        'a gate answer or your Resume brings it back in about 5 to 15 s, conversation kept.'
    });
  }
  /* The server's idle list (`deckstate.idle_of`, which holds the idle shipping houses Now
     has no tile for) and Now's houses, read again against the newest row the strip said. */
  function idleHouses() {
    var data = K.App.data || {}, ids = (data.idle || []).concat(data.houses || []);
    return K.cards().filter(K.inSpace).filter(function (c) { return ids.indexOf(c.id) >= 0 && idleHouse(c); });
  }
  /* "3 idle houses holding about 2.1 GB": the total of the readings there are, and how
     many were read when not all of them were. */
  function idleLine(list) {
    var mems = list.map(houseMem).filter(function (m) { return m !== null; });
    var total = mems.reduce(function (a, b) { return a + b; }, 0);
    var head = list.length + ' idle ' + (list.length === 1 ? 'house' : 'houses');
    if (!mems.length) return head;
    return head + ' holding about ' + memText(total) + (mems.length < list.length ? ' (' + mems.length + ' read)' : '');
  }
  function idleRow(c) {
    var mem = memText(houseMem(c)), age = idleSeconds(c), due = shipIdleText(c);
    var facts = [K.stageOf(c), due || (age !== null ? 'idle ' + ageText(age) : 'idle'), mem].filter(Boolean).join(' · ');
    return el('div', { class: 'idlerow', 'data-key': c.id },
      el('span', { class: 'id', text: c.id }),
      el('button', { class: 't ellip', title: c.title, onclick: function () { K.go(K.cardRoute(c), c.id); } }, c.title),
      el('span', { class: 'idlefacts' + (LEFT_STAGES.indexOf(K.stageOf(c)) >= 0 ? ' left' : ''), text: facts }),
      closeable(c) && K.shownIn('close-idle', c) ? closeIdleBtn(c, 'sm') : null);
  }
  /* Now's panel: nothing at all while no house is idle. */
  function idlePanel() {
    var list = idleHouses();
    if (!list.length) return null;
    var left = list.filter(closeable);
    var all = left.length > 1 ? K.actionBtn('Close all idle (' + left.length + ')',
      { verb: 'house.close_idle', ids: left.map(function (c) { return c.id; }) }, { cls: 'sm',
        confirm: 'Close the ' + left.length + ' idle houses at review and shipping (' +
          left.map(function (c) { return c.id; }).join(', ') + ')? Each comes back at its next ' +
          'review batch, a gate answer or your Resume.' }) : null;
    return el('section', { class: 'panel', 'data-key': 'idle-panel' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Idle houses' }),
        el('span', { class: 'idlesum', 'data-key': 'idle-sum', text: idleLine(list) }), all),
      el('div', { class: 'panel-body idlelist' }, list.map(idleRow)));
  }

  K.memText = memText; K.houseMem = houseMem; K.idleSeconds = idleSeconds; K.idleHouse = idleHouse;
  K.closeableIdle = closeable; K.closeIdleBtn = closeIdleBtn; K.idleHouses = idleHouses;
  K.idleLine = idleLine; K.shipIdleText = shipIdleText; K.idlePanel = idlePanel; K.CLOSED_IDLE_SAID = CLOSED_SAID; K.closedSaid = closedSaid;
})(window.Keel);
