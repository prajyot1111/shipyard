/* Measure the strings the layout harness asked about, in Chrome, by hand (not in make test).
 *
 *   KEEL_RECORD_TEXT=/tmp/asked.json node tests/fixtures/board-layout.js app tests/fixtures/board-b009.txt
 *   NODE_PATH=~/harbor/.node/node_modules node tests/fixtures/board-text-measure.js /tmp/asked.json \
 *     > tests/fixtures/board-text-widths.json
 *
 * A fresh headless Chrome (playwright-core, as harbor-browser launches it), a blank page, and
 * the canvas `measureText` that `textWidth` in app/ui.board.js uses. Closed on every path.
 */
'use strict';
const fs = require('fs');
const { chromium } = require('playwright-core');
const keys = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await (await browser.newContext()).newPage();
    const widths = await page.evaluate(list => {
      const ctx = document.createElement('canvas').getContext('2d'), out = {};
      for (const key of list.sort()) {
        const at = key.indexOf('|');
        ctx.font = key.slice(0, at);
        out[key] = Math.round(ctx.measureText(key.slice(at + 1)).width * 1000) / 1000;
      }
      return out;
    }, keys);
    process.stdout.write(JSON.stringify(widths, null, 1) + '\n');
  } finally { await browser.close(); }
})().catch(err => { console.error(err); process.exit(1); });
