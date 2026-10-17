// Run with: node tests/test_recovery.js
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createHarness, state, response, flush} = require('./client_harness');

test('409 automatically preserves the newest local edits and adopts the recovered server state', async () => {
  const calls = [];
  const recovered = state('Server winner');
  recovered.lists.push({...state('Local edits').lists[0], id:'recovered', title:'Local edits (Recovered)'});
  const h = createHarness(async (url, options) => {
    calls.push({url, body:JSON.parse(options.body)});
    return url === '/api/state' ? response(409, {error:'Conflict'}) :
      response(200, {revision:3, state:recovered, recoveredCount:1});
  });
  h.client.configure(state('Original'), 1);
  h.client.setState(state('Local edits'));
  h.client.saveState();
  await flush();
  assert.deepEqual(calls.map(call => call.url), ['/api/state', '/api/recovery']);
  assert.equal(calls[1].body.state.lists[0].title, 'Local edits');
  assert.equal(h.client.getState().lists[0].title, 'Server winner');
  assert.equal(h.client.getState().lists[1].title, 'Local edits (Recovered)');
  assert.equal(h.client.getRevision(), 3);
  assert.equal(h.client.getPending(), null);
  assert.equal(h.element('#recoveryNotice').hidden, false);
});

test('lost recovery responses keep edits pending and reuse the recovery ID on retry', async () => {
  const ids = [];
  let fail = true;
  const h = createHarness(async (url, options) => {
    if (url === '/api/state') return response(409, {error:'Conflict'});
    ids.push(JSON.parse(options.body).recoveryId);
    if (fail) throw new Error('Connection dropped after commit');
    return response(200, {revision:3, state:state('Recovered'), recoveredCount:0});
  });
  h.client.configure(state('Local edits'), 1);
  h.client.saveState();
  await flush();
  assert.notEqual(h.client.getPending(), null);
  assert.equal(h.element('.app').inert, false);
  fail = false;
  await h.client.persistPending();
  assert.equal(ids.length, 2);
  assert.equal(ids[0], ids[1]);
  assert.equal(h.client.getPending(), null);
});

test('session loss during conflict recovery preserves edits and stops retries', async () => {
  const h = createHarness(async url => url === '/api/state' ? response(409, {}) : response(401, {error:'Sign in required'}));
  h.client.configure(state('Private edits'), 1);
  h.client.saveState();
  await flush();
  assert.equal(h.client.getAuthExpired(), true);
  assert.notEqual(h.client.getPending(), null);
  assert.equal(h.element('#signInAgain').hidden, false);
});
