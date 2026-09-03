// Run by test_quote_search.py with results produced by the actual Python services.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));

function makeContext(demoMode = false) {
  const nodes = new Map();
  const document = {
    querySelectorAll: () => [],
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {
        value: "", checked: false, hidden: false, innerHTML: "", textContent: "",
        handlers: {},
        addEventListener(event, callback) { this.handlers[event] = callback; },
        querySelectorAll() {
          return [...this.innerHTML.matchAll(/data-rate-id="([^"]+)"(?: data-detail-id="([^"]+)")?/g)]
            .map((match) => ({
              dataset: { rateId: match[1], detailId: match[2] }, handlers: {},
              addEventListener(event, callback) { this.handlers[event] = callback; },
            }));
        },
      });
      return nodes.get(id);
    },
  };
  const context = vm.createContext({
    input, assert, document, URLSearchParams, AbortController,
    setTimeout: () => 1, clearTimeout() {}, console,
    window: { RATE_DESK_CONFIG: { demoMode }, RATE_DESK_AUTH: { requireSession: async () => null } },
  });
  vm.runInContext(fs.readFileSync("UI/demo-data.js", "utf8"), context);
  vm.runInContext(fs.readFileSync("UI/rate-desk.js", "utf8"), context);
  return context;
}

(async () => {
  await vm.runInContext(`(async () => {
    deskState.loaded = true;
    elements.materialSelect.value = "All materials";
    elements.equipmentSelect.value = "40HC";
    elements.qtyInput.value = "1";
    const samePrice = (actual, expected) => assert.ok(Math.abs(actual - expected) < 0.00001, actual + " != " + expected);
    for (const payload of [input.browse, input.quay, input.collection]) {
      deskState.connectedRates = payload.rates;
      deskState.resultType = payload.result_type;
      deskState.totalMatches = payload.pagination.total;
      for (const quantity of [1, 3]) {
        deskState.detailCache.clear();
        const before = buildConnectedRows(quantity);
        assert.equal(before.length, payload.pagination.total);
        for (const row of before) {
          const summary = payload.rates.find(rate => rate.quote_id === row.id);
          const fixed = Object.values(summary.per_booking_usd || {}).reduce((sum, value) => sum + value, 0);
          samePrice(row.totalUsd, summary.all_in_usd * quantity - fixed * (quantity - 1));
          if (summary.quote_kind === "combined") {
            assert.ok(row.routeLane.startsWith(summary.collection_location_name + " → "));
            assert.equal(row.inlandUsd, summary.inland_usd * quantity);
            assert.equal(row.detailId, summary.offer_id);
            assert.ok(row.services.some(service => service.file === summary.haulage.source_file_name));
          }
          if (summary.quote_kind === "door") assert.equal(row.inlandIncluded, true);
          if (summary.quote_kind === "quay") assert.equal(row.inlandUsd, 0);
        }
        for (const rate of payload.rates) deskState.detailCache.set(rate.offer_id, input.details[rate.offer_id]);
        const after = buildConnectedRows(quantity);
        for (const row of after) samePrice(row.totalUsd, before.find(item => item.id === row.id).totalUsd);
      }
      renderDesk();
      assert.ok(elements.laneSummary.textContent.includes(String(payload.pagination.total)));
      assert.equal(elements.rateRows.querySelectorAll().length, payload.pagination.total);
    }

    // Row identity belongs to the combined quote; detail requests belong to its ocean offer.
    deskState.connectedRates = input.browse.rates;
    deskState.detailCache.clear();
    const combined = input.browse.rates.find(rate => rate.quote_kind === "combined");
    const requested = [];
    window.RATE_DESK_AUTH.apiFetch = async (url) => {
      requested.push(url);
      return { ok: true, json: async () => input.details[combined.offer_id] };
    };
    deskState.expandedId = combined.quote_id;
    await loadOfferDetail(combined.offer_id);
    assert.equal(requested[0], "/api/rate-desk/offers/" + combined.offer_id);
    assert.ok(deskState.detailCache.has(combined.offer_id));
    assert.ok(elements.rateRows.innerHTML.includes('data-detail-id="' + combined.offer_id + '"'));

    // Existing filters determine mode; expiry is sent before the API paginates.
    let lastUrl;
    window.RATE_DESK_AUTH.apiFetch = async (url) => {
      lastUrl = url;
      return { ok: true, json: async () => input.quay };
    };
    elements.collectionSelect.value = "";
    elements.originSelect.value = "Felixstowe";
    elements.destinationSelect.value = "Mundra";
    elements.showExpiredToggle.checked = false;
    await refreshConnectedRates();
    const query = new URLSearchParams(lastUrl.split("?")[1]);
    assert.equal(query.get("include_expired"), "false");
    assert.equal(query.get("pol"), "Felixstowe");
    assert.equal(query.get("pod"), "Mundra");
    assert.equal(query.has("collection"), false);
    assert.equal(query.has("service_mode"), false);
    assert.ok(elements.figuresNote.textContent.includes("exclude collection"));
    assert.equal(elements.priceScopeLabel.textContent, "excl. inland");

    const selectMany = (element, ...values) => {
      element.multiple = true;
      element.selectedOptions = values.map(value => ({ value }));
      element.value = values[0] || "";
    };
    selectMany(elements.originSelect, "Felixstowe", "Southampton");
    selectMany(elements.destinationSelect, "Mundra", "Singapore");
    selectMany(elements.carrierSelect, "COSCO", "Maersk");
    selectMany(elements.collectionSelect, "Bristol", "Leeds");
    await refreshConnectedRates();
    const multiQuery = new URLSearchParams(lastUrl.split("?")[1]);
    assert.equal(multiQuery.getAll("pol").join("|"), "Felixstowe|Southampton");
    assert.equal(multiQuery.getAll("pod").join("|"), "Mundra|Singapore");
    assert.equal(multiQuery.getAll("carrier_name").join("|"), "COSCO|Maersk");
    assert.equal(multiQuery.getAll("collection").join("|"), "Bristol|Leeds");

    elements.collectionSelect.multiple = false;
    elements.collectionSelect.selectedOptions = undefined;
    elements.collectionSelect.value = "Bristol";
    window.RATE_DESK_AUTH.apiFetch = async () => ({ ok: true, json: async () => input.collection });
    await refreshConnectedRates();
    assert.ok(!elements.figuresNote.textContent.includes("exclude collection"));
    assert.equal(elements.priceScopeLabel.textContent, "incl. inland");
    assert.equal(deskState.connectedRates.length, input.collection.rates.length);

    window.RATE_DESK_AUTH.apiFetch = async () => ({ ok: true, json: async () => ({
      rates: [], result_type: "collection", hidden_expired: 0,
      pagination: { total: 0, has_more: false },
    }) });
    await refreshConnectedRates();
    assert.ok(elements.rateRows.innerHTML.includes("No fully priced collection routes"));
    assert.equal(deskState.totalMatches, 0);

    window.RATE_DESK_AUTH.apiFetch = async () => { throw new Error("offline"); };
    await refreshConnectedRates();
    assert.equal(deskState.connectedRates.length, 0);
    assert.ok(elements.deskAlert.textContent.includes("offline"));
    assert.equal(elements.deskAlert.hidden, false);
  })()`, makeContext());

  vm.runInContext(`
    elements.materialSelect.value = "All materials";
    elements.equipmentSelect.value = "40HC";
    const browse = buildDemoRows(1);
    assert.ok(browse.length > 0);
    assert.ok(browse.every(row => row.routing === "Door to quay"));
    assert.equal(new Set(browse.map(row => row.id)).size, browse.length);
    elements.originSelect.value = "Felixstowe";
    elements.destinationSelect.value = "Laem Chabang";
    const quay = buildDemoRows(1);
    assert.ok(quay.length > 0);
    assert.ok(quay.every(row => row.routing === "Quay to quay" && row.inlandUsd === 0));
    elements.collectionSelect.value = "Abbots Bromley";
    assert.ok(buildDemoRows(1).every(row => row.routing === "Door to quay"));
    elements.collectionSelect.value = "Unknown";
    assert.equal(buildDemoRows(1).length, 0);
  `, makeContext(true));
  console.log("Frontend quote search checks passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
