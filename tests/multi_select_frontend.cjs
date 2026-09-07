const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function eventTarget(selector, matched) {
  return {
    closest(candidate) {
      return candidate === selector ? matched : null;
    },
  };
}

function makeNode(id = "") {
  return {
    id,
    value: "",
    checked: false,
    disabled: false,
    hidden: false,
    innerHTML: "",
    textContent: "",
    handlers: {},
    focusCount: 0,
    addEventListener(event, callback) { this.handlers[event] = callback; },
    setAttribute(name, value) { this[name] = value; },
    focus() { this.focusCount += 1; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
  };
}

function makeMultiSelect(id) {
  const label = makeNode();
  const toggle = makeNode();
  toggle.querySelector = selector => selector === "[data-multi-label]" ? label : null;
  const menu = makeNode();
  const select = makeNode(id);
  select.multiple = true;
  select.options = [];
  Object.defineProperty(select, "selectedOptions", {
    get() { return select.options.filter(option => option.selected); },
  });
  menu.querySelector = selector => {
    if (selector !== "[data-multi-search]") return null;
    const search = makeNode();
    search.value = select.multiSearch || "";
    search.setSelectionRange = () => {};
    return search;
  };
  menu.querySelectorAll = selector => {
    if (selector !== "[data-multi-option]") return [];
    return select.options.filter(option => option.value).map(option => ({
      value: option.value,
      checked: option.selected,
      focus() {},
    }));
  };
  const control = {
    querySelector(selector) {
      if (selector === "[data-multi-toggle]") return toggle;
      if (selector === "[data-multi-menu]") return menu;
      return null;
    },
  };
  select.closest = selector => selector === "[data-multi-select]" ? control : null;
  return { select, control, toggle, label, menu };
}

const multiIds = new Set([
  "collectionSelect",
  "originSelect",
  "destinationSelect",
  "carrierSelect",
  "materialSelect",
]);
const nodes = new Map();
const controls = new Map();
const document = {
  handlers: {},
  addEventListener(event, callback) { this.handlers[event] = callback; },
  querySelectorAll() { return []; },
  getElementById(id) {
    if (multiIds.has(id)) {
      if (!controls.has(id)) controls.set(id, makeMultiSelect(id));
      return controls.get(id).select;
    }
    if (!nodes.has(id)) nodes.set(id, makeNode(id));
    return nodes.get(id);
  },
};

const context = vm.createContext({
  assert,
  document,
  URLSearchParams,
  AbortController,
  setTimeout: () => 1,
  clearTimeout() {},
  console,
  window: {
    RATE_DESK_CONFIG: { demoMode: false },
    RATE_DESK_AUTH: { requireSession: async () => null },
  },
});
vm.runInContext(fs.readFileSync("UI/rate-desk.js", "utf8"), context);

const collection = controls.get("collectionSelect");
const origin = controls.get("originSelect");
collection.select.options = [
  { value: "", selected: false },
  { value: "Bristol", selected: false },
  { value: "Leeds", selected: false },
  { value: "Manchester", selected: false },
];
origin.select.options = [
  { value: "", selected: false },
  { value: "Felixstowe", selected: false },
  { value: "Southampton", selected: false },
];

vm.runInContext("renderMultiSelect(elements.collectionSelect); renderMultiSelect(elements.originSelect);", context);
assert.match(collection.menu.innerHTML, /Search collection places/);
assert.match(collection.menu.innerHTML, /None selected = all 3/);
assert.match(collection.menu.innerHTML, /Select all/);

vm.runInContext('openMultiSelect(elements.collectionSelect);', context);
assert.equal(collection.menu.hidden, false);
assert.equal(collection.toggle["aria-expanded"], "true");

const search = { value: "man", closest: selector => selector === "[data-multi-search]" ? search : null };
collection.menu.handlers.input({ target: search });
assert.equal(collection.select.multiSearch, "man");
assert.match(collection.menu.innerHTML, /Manchester/);
assert.doesNotMatch(collection.menu.innerHTML, />Bristol</);
assert.match(collection.menu.innerHTML, /Select matches/);

const selectMatches = { dataset: { multiAction: "select-visible" } };
collection.menu.handlers.click({
  stopPropagation() {},
  target: eventTarget("[data-multi-action]", selectMatches),
});
assert.deepEqual(collection.select.selectedOptions.map(option => option.value), ["Manchester"]);
assert.match(collection.label.innerHTML, /multi-filter-button-chip/);
assert.match(nodes.get("activeFilterChips").innerHTML, /Collection ·/);
assert.match(nodes.get("activeFilterChips").innerHTML, /Manchester/);

vm.runInContext('setSelectedValues(elements.collectionSelect, ["Bristol", "Leeds"]);', context);
assert.match(collection.label.innerHTML, /Bristol/);
assert.match(collection.label.innerHTML, /Leeds/);
assert.doesNotMatch(collection.label.innerHTML, /2 selected/);
vm.runInContext('setSelectedValues(elements.collectionSelect, ["Bristol", "Leeds", "Manchester"]);', context);
assert.match(collection.label.innerHTML, /3 selected/);

vm.runInContext('openMultiSelect(elements.originSelect);', context);
assert.equal(collection.menu.hidden, true);
assert.equal(origin.menu.hidden, false);
document.handlers.keydown({ key: "Escape" });
assert.equal(origin.menu.hidden, true);
assert.equal(origin.toggle.focusCount, 1);

vm.runInContext('openMultiSelect(elements.collectionSelect);', context);
document.handlers.click({ target: eventTarget("[data-multi-select]", null) });
assert.equal(collection.menu.hidden, true);

vm.runInContext('openMultiSelect(elements.collectionSelect);', context);
const clear = { dataset: { multiAction: "clear" } };
collection.menu.handlers.click({
  stopPropagation() {},
  target: eventTarget("[data-multi-action]", clear),
});
assert.equal(collection.select.selectedOptions.length, 0);
assert.equal(collection.menu.hidden, false);

const checkbox = {
  value: "Bristol",
  checked: true,
  closest: selector => selector === "[data-multi-option]" ? checkbox : null,
};
collection.menu.handlers.change({ target: checkbox });
assert.deepEqual(collection.select.selectedOptions.map(option => option.value), ["Bristol"]);
assert.equal(collection.menu.hidden, false);

vm.runInContext('setSelectedValues(elements.originSelect, ["Southampton"]);', context);
assert.deepEqual(collection.select.selectedOptions.map(option => option.value), ["Bristol"]);
assert.match(nodes.get("activeFilterChips").innerHTML, /Bristol/);
assert.match(nodes.get("activeFilterChips").innerHTML, /Southampton/);

const removeBristol = {
  dataset: { filterId: "collectionSelect", activeFilterRemove: "Bristol" },
};
nodes.get("activeFilterChips").handlers.click({
  target: eventTarget("[data-active-filter-remove]", removeBristol),
});
assert.equal(collection.select.selectedOptions.length, 0);
assert.deepEqual(origin.select.selectedOptions.map(option => option.value), ["Southampton"]);

vm.runInContext('openMultiSelect(elements.collectionSelect);', context);
const done = { dataset: { multiAction: "done" } };
collection.menu.handlers.click({
  stopPropagation() {},
  target: eventTarget("[data-multi-action]", done),
});
assert.equal(collection.menu.hidden, true);
assert.ok(collection.toggle.focusCount > 0);

console.log("Multi-select interaction checks passed.");
