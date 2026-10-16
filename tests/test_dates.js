// Run with: node tests/test_dates.js
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {spawnSync} = require('node:child_process');
const {test} = require('node:test');
const vm = require('node:vm');

const html = readFileSync(resolve(__dirname, '../index.html'), 'utf8');
const helpers = html.slice(html.indexOf('  const pad ='), html.indexOf('  const DOW_TITLES'));

if (process.env.DATE_TEST_CHILD) {
  vm.runInThisContext(helpers);
  for (const [date, days, expected] of [
    ['2026-10-15', 0, '2026-10-15'],
    ['2026-10-15', 1, '2026-10-16'],
    ['2026-03-08', 1, '2026-03-09'], // US spring DST
    ['2026-11-01', 1, '2026-11-02'], // US autumn DST
    ['2026-03-29', 1, '2026-03-30'], // European DST
    ['2026-12-31', 1, '2027-01-01'],
    ['2028-02-28', 1, '2028-02-29'],
    ['2026-03-01', -1, '2026-02-28'],
  ]) assert.equal(addDaysISO(date, days), expected);
  assert.equal(getMondayISO('2026-10-18'), '2026-10-12');
  assert.equal(getMondayISO('2026-10-19'), '2026-10-19');
  const now = new Date();
  assert.equal(todayISO(), `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`);

  // Exercise the copy action against local dates around DST, too.
  const action = html.slice(html.indexOf('  function copyIncompleteToNext(){'), html.indexOf('  // Week creation'));
  vm.runInThisContext(action);
  for (const [date, next] of [['2026-03-08', '2026-03-09'], ['2026-11-01', '2026-11-02']]) {
    global.state = {currentId: 'first', lists: [
      {id: 'first', date, tasks: [{text: 'Carry over', done: false}]},
      {id: 'second', date: next, tasks: []},
    ]};
    global.saveCurrentFromInputs = global.saveState = global.renderAll = () => {};
    global.alert = () => {};
    copyIncompleteToNext();
    assert.equal(state.currentId, 'second');
    assert.equal(state.lists[1].tasks[0].text, 'Carry over');
  }
} else {
  for (const timezone of ['UTC', 'America/Chicago', 'America/Los_Angeles', 'Europe/Berlin', 'Asia/Tokyo', 'Pacific/Auckland']) {
    test(`Calendar dates in ${timezone}`, () => {
      const result = spawnSync(process.execPath, [__filename], {
        env: {...process.env, TZ: timezone, DATE_TEST_CHILD: '1'}, encoding: 'utf8',
      });
      assert.equal(result.status, 0, result.stderr || result.stdout);
    });
  }
}
