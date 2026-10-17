const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

function createHarness(fetch, storage = new Map()) {
  const elements = new Map();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      value: '', textContent: '', hidden: true, inert: false, disabled: false,
      addEventListener() {}, querySelectorAll() { return []; },
    });
    return elements.get(selector);
  };
  const context = vm.createContext({
    fetch, crypto: webcrypto, Uint8Array, Blob, URL, console,
    setTimeout: () => 1, clearTimeout() {},
    document: {querySelector: element, addEventListener() {}},
    window: {addEventListener() {}},
    location: {replace() {}},
    localStorage: {
      get length() { return storage.size; },
      key: index => Array.from(storage.keys())[index] ?? null,
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
  });
  const html = readFileSync(resolve(__dirname, '../index.html'), 'utf8');
  let source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  source = source.replace('  initialize();\n})();', `
    renderAll = renderNav = initDarkMode = updateHistoryButtons = () => {};
    readInputs = () => {
      const current = state.lists.find(list => list.id === state.currentId);
      return {title:current.title, date:current.date, notes:current.notes, tasks:current.tasks};
    };
    globalThis.client = {
      saveState, queueSave, persistPending, recoverConflict, initialize,
      captureInputDraft, saveInputsToStateDebounced, storedDrafts, syncUnsavedDrafts,
      getState: () => state,
      getRevision: () => revision,
      getPending: () => pendingSnapshot,
      getAuthExpired: () => authExpired,
      setState: value => { state = value; },
      configure: (value, rev = 0, userId = 1, scope = "testdb") => {
        state = value; revision = rev; csrfToken = "csrf"; ready = true;
        document.querySelector(".app").inert = false;
        ownerId = userId; storageScope = scope; serverSnapshot = JSON.stringify(value);
        lastSavedSnapshot = JSON.stringify(value);
      },
    };
  })();`);
  vm.runInContext(source, context);
  return {client: context.client, context, element, storage};
}

const state = title => ({currentId:'one', theme:'dark', lists:[
  {id:'one', title, date:'2026-10-17', notes:'', tasks:[]},
]});
const response = (status, body) => ({status, ok:status >= 200 && status < 300, json:async () => body});
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
module.exports = {createHarness, state, response, flush};
