// Run with: node tests/test_offline.js
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createHarness, state, response, flush} = require('./client_harness');

test('keystrokes are durable before the autosave debounce and after tab closure', () => {
  const storage = new Map();
  const tab = createHarness(async () => { throw new Error('Offline'); }, storage);
  tab.client.configure(state('Saved'), 4);
  tab.client.setState(state('Typed just now'));
  tab.client.saveInputsToStateDebounced();
  const reopened = createHarness(async () => {}, storage);
  reopened.client.configure(state('Saved'), 4);
  const drafts = reopened.client.storedDrafts();
  assert.equal(drafts.length, 1);
  assert.equal(JSON.parse(drafts[0].record.snapshot).lists[0].title, 'Typed just now');
  assert.equal(drafts[0].record.baseRevision, 4);
  assert.equal(JSON.parse(drafts[0].record.baseSnapshot).lists[0].title, 'Saved');
});

test('offline edits survive session loss and sync after sign-in when the baseline is unchanged', async () => {
  const storage = new Map();
  const oldTab = createHarness(async () => response(401, {error:'Server restarted'}), storage);
  oldTab.client.configure(state('Saved'), 4);
  oldTab.client.setState(state('Offline edits'));
  oldTab.client.saveState();
  await flush();
  assert.equal(oldTab.client.getAuthExpired(), true);
  const calls = [];
  const reopened = createHarness(async (url, options) => {
    calls.push({url, options});
    return options?.method === 'PUT' ? response(200, {revision:6}) : response(200, {revision:5, state:state('Saved')});
  }, storage);
  reopened.client.configure(state('Saved'), 5);
  await reopened.client.syncUnsavedDrafts();
  assert.equal(reopened.client.getState().lists[0].title, 'Offline edits');
  assert.equal(JSON.parse(calls[1].options.body).revision, 5);
  assert.equal(reopened.client.storedDrafts().length, 0);
});

test('diverged server data is recovered without an overwrite, even if revisions match', async () => {
  const storage = new Map();
  const oldTab = createHarness(async () => {}, storage);
  oldTab.client.configure(state('Original'), 4);
  oldTab.client.setState(state('Local edits'));
  oldTab.client.captureInputDraft();
  const calls = [];
  const reopened = createHarness(async (url, options) => {
    calls.push({url, options});
    return url === '/api/recovery' ? response(200, {revision:5, state:state('Recovered copies')}) :
      response(200, {revision:4, state:state('Different server data')});
  }, storage);
  reopened.client.configure(state('Different server data'), 4);
  await reopened.client.syncUnsavedDrafts();
  assert.deepEqual(calls.map(call => call.url), ['/api/state', '/api/recovery']);
  assert.equal(reopened.client.storedDrafts().length, 0);
});

test('a race during sync falls back to conflict recovery', async () => {
  const storage = new Map();
  const oldTab = createHarness(async () => {}, storage);
  oldTab.client.configure(state('Original'), 4);
  oldTab.client.setState(state('Local edits'));
  oldTab.client.captureInputDraft();
  const calls = [];
  const reopened = createHarness(async (url, options) => {
    calls.push(url);
    if (url === '/api/recovery') return response(200, {revision:6, state:state('Recovered')});
    if (options?.method === 'PUT') return response(409, {});
    return response(200, {revision:4, state:state('Original')});
  }, storage);
  reopened.client.configure(state('Original'), 4);
  await reopened.client.syncUnsavedDrafts();
  assert.deepEqual(calls, ['/api/state', '/api/state', '/api/recovery']);
  assert.equal(reopened.client.storedDrafts().length, 0);
});

test('drafts are not offered to a different account or a replacement database', () => {
  const storage = new Map();
  const tab = createHarness(async () => {}, storage);
  tab.client.configure(state('Private'), 1, 1, 'originaldb');
  tab.client.captureInputDraft();
  for (const [owner, scope] of [[2, 'originaldb'], [1, 'replacementdb']]) {
    const other = createHarness(async () => {}, storage);
    other.client.configure(state('Empty'), 1, owner, scope);
    assert.equal(other.client.storedDrafts().length, 0);
  }
});

test('lost normal save responses do not duplicate already-saved data on sync', async () => {
  const storage = new Map();
  const oldTab = createHarness(async () => { throw new Error('Response lost'); }, storage);
  oldTab.client.configure(state('Original'), 1);
  oldTab.client.setState(state('Committed but not acknowledged'));
  oldTab.client.saveState();
  await flush();
  const reopened = createHarness(async (url, options) => {
    assert.equal(options.method, undefined);
    return response(200, {revision:2, state:state('Committed but not acknowledged')});
  }, storage);
  reopened.client.configure(state('Committed but not acknowledged'), 2);
  await reopened.client.syncUnsavedDrafts();
  assert.equal(reopened.client.storedDrafts().length, 0);
});

test('a newer edit made during an in-flight save remains durable with the acknowledged baseline', async () => {
  const storage = new Map();
  let finish;
  const tab = createHarness(() => new Promise(resolve => { finish = resolve; }), storage);
  tab.client.configure(state('Original'), 1);
  tab.client.setState(state('First edit'));
  tab.client.saveState();
  tab.client.setState(state('Second edit during request'));
  tab.client.captureInputDraft();
  finish(response(200, {revision:2}));
  await flush();
  const reopened = createHarness(async () => {}, storage);
  reopened.client.configure(state('First edit'), 2);
  const record = reopened.client.storedDrafts()[0].record;
  assert.equal(JSON.parse(record.snapshot).lists[0].title, 'Second edit during request');
  assert.equal(JSON.parse(record.baseSnapshot).lists[0].title, 'First edit');
  assert.equal(record.baseRevision, 2);
});

test('simultaneous tabs retain separate drafts and a failed sync retains every snapshot', async () => {
  const storage = new Map();
  for (const title of ['Tab A', 'Tab B']) {
    const tab = createHarness(async () => {}, storage);
    tab.client.configure(state('Original'), 1);
    tab.client.setState(state(title));
    tab.client.captureInputDraft();
  }
  const reopened = createHarness(async () => { throw new Error('Offline'); }, storage);
  reopened.client.configure(state('Original'), 1);
  assert.equal(reopened.client.storedDrafts().length, 2);
  await reopened.client.syncUnsavedDrafts();
  assert.equal(reopened.client.storedDrafts().length, 2);
});

test('unavailable browser storage warns without preventing online saving', async () => {
  const tab = createHarness(async () => response(200, {revision:2}));
  tab.client.configure(state('Original'), 1);
  tab.context.localStorage.setItem = () => { throw new Error('Quota exceeded'); };
  tab.client.setState(state('Online edits'));
  tab.client.saveState();
  await flush();
  assert.equal(tab.element('#localStorageWarning').hidden, false);
  assert.equal(tab.client.getPending(), null);
});

test('a lost recovery response survives closing and reopening without a new recovery ID', async () => {
  const storage = new Map();
  let originalId;
  const oldTab = createHarness(async (url, options) => {
    if (url === '/api/state') return response(409, {});
    originalId = JSON.parse(options.body).recoveryId;
    throw new Error('Committed recovery response lost');
  }, storage);
  oldTab.client.configure(state('Original'), 1);
  oldTab.client.setState(state('Local edits'));
  oldTab.client.saveState();
  await flush();
  const reopened = createHarness(async (url, options) => {
    if (url === '/api/state') return response(200, {revision:3, state:state('Existing recovered lists')});
    assert.equal(JSON.parse(options.body).recoveryId, originalId);
    return response(200, {revision:3, state:state('Existing recovered lists'), recoveredCount:0});
  }, storage);
  reopened.client.configure(state('Existing recovered lists'), 3);
  await reopened.client.syncUnsavedDrafts();
  assert.equal(reopened.client.storedDrafts().length, 0);
});

test('an expired session during manual sync keeps the draft and offers sign-in', async () => {
  const storage = new Map();
  const oldTab = createHarness(async () => {}, storage);
  oldTab.client.configure(state('Original'), 1);
  oldTab.client.setState(state('Unsaved'));
  oldTab.client.captureInputDraft();
  const reopened = createHarness(async () => response(401, {}), storage);
  reopened.client.configure(state('Original'), 1);
  await reopened.client.syncUnsavedDrafts();
  assert.equal(reopened.client.storedDrafts().length, 1);
  assert.equal(reopened.client.getAuthExpired(), true);
  assert.equal(reopened.element('#signInAgain').hidden, false);
});
