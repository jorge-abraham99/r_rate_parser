const RATE_DESK_DEMO_MODE = Boolean(window.RATE_DESK_CONFIG?.demoMode);
const DEFAULT_FX = { USD: 1, GBP: 1.29, EUR: 1.09, INR: 0.0104, THB: 0.0302 };
const EQUIPMENT_OPTIONS = [
  { value: "", label: "All sizes" },
  { value: "20GP", label: "20′" },
  { value: "40GP", label: "40′" },
  { value: "40HC", label: "40′ HC" },
];
const MATERIAL_OPTIONS = ["All materials", "Paper", "Metal", "Tyres"];
const deskState = {
  loaded: false,
  expandedId: null,
  connectedRates: [],
  initialConnectedRates: [],
  filters: {},
  haulageTariffs: {},
  haulageCurrency: "USD",
  sort: null,
  pageOffset: 0,
  pageSize: 50,
  totalMatches: 0,
  hasMore: false,
  searchTimer: null,
  searchController: null,
  detailCache: new Map(),
  detailLoading: new Set(),
  detailErrors: new Map(),
};

const elements = {
  collectionField: document.getElementById("collectionField"),
  collectionArrow: document.getElementById("collectionArrow"),
  collectionSelect: document.getElementById("collectionSelect"),
  originSelect: document.getElementById("originSelect"),
  destinationSelect: document.getElementById("destinationSelect"),
  equipmentSelect: document.getElementById("equipmentSelect"),
  qtyInput: document.getElementById("qtyInput"),
  materialSelect: document.getElementById("materialSelect"),
  showExpiredToggle: document.getElementById("showExpiredToggle"),
  showAllQuotesButton: document.getElementById("showAllQuotesButton"),
  rateRows: document.getElementById("rateRows"),
  laneTitle: document.getElementById("laneTitle"),
  laneSummary: document.getElementById("laneSummary"),
  refreshText: document.getElementById("refreshText"),
  demoBadge: document.getElementById("demoBadge"),
  deskAlert: document.getElementById("deskAlert"),
  figuresNote: document.getElementById("figuresNote"),
  sortButtons: [...document.querySelectorAll("[data-sort-key]")],
  paginationControls: document.getElementById("paginationControls"),
  previousPageButton: document.getElementById("previousPageButton"),
  nextPageButton: document.getElementById("nextPageButton"),
  paginationSummary: document.getElementById("paginationSummary"),
};

[elements.collectionSelect, elements.originSelect, elements.destinationSelect, elements.equipmentSelect, elements.materialSelect]
  .forEach((element) => element.addEventListener("change", resetAndRender));
elements.showExpiredToggle.addEventListener("change", renderDesk);
elements.showAllQuotesButton.addEventListener("click", showAllQuotes);
elements.previousPageButton.addEventListener("click", () => changePage(-1));
elements.nextPageButton.addEventListener("click", () => changePage(1));
elements.sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.sortKey;
    const activeSort = deskState.sort?.key === key ? deskState.sort : null;
    deskState.sort = !activeSort
      ? { key, direction: "asc" }
      : activeSort.direction === "asc"
        ? { key, direction: "desc" }
        : null;
    deskState.expandedId = null;
    renderDesk();
  });
});
elements.qtyInput.addEventListener("change", () => {
  elements.qtyInput.value = clampQuantity(elements.qtyInput.value);
  deskState.expandedId = null;
  renderDesk();
});
elements.qtyInput.addEventListener("input", () => {
  if (elements.qtyInput.value !== "") {
    deskState.expandedId = null;
    renderDesk();
  }
});

bootRateDesk();

async function bootRateDesk() {
  try {
    const session = await window.RATE_DESK_AUTH.requireSession();
    if (!session) return;
  } catch (error) {
    showAlert(error.message);
    return;
  }
  elements.demoBadge.hidden = !RATE_DESK_DEMO_MODE;
  if (RATE_DESK_DEMO_MODE) {
    deskState.loaded = true;
    populateDemoFilters();
    elements.refreshText.textContent = "Frontend preview · session only";
    renderDesk();
    return;
  }

  try {
    const metaResponse = await window.RATE_DESK_AUTH.apiFetch("/api/rate-desk/meta");
    if (!metaResponse.ok) throw new Error("The approved-rate service did not respond.");
    const metadata = await metaResponse.json();
    deskState.filters = metadata.filters || {};
    deskState.haulageTariffs = metadata.haulage_tariffs || {};
    deskState.haulageCurrency = metadata.haulage_currency || "USD";
    deskState.loaded = true;
    populateConnectedFilters();
    elements.refreshText.textContent = metadata.last_refreshed
      ? `Rates refreshed ${shortDateTime(metadata.last_refreshed)}`
      : "Rates refreshed from approved data";
    await refreshConnectedRates(true);
  } catch (error) {
    deskState.loaded = true;
    showAlert(`Could not load approved rates: ${error.message}`);
    elements.refreshText.textContent = "Rate service unavailable";
    elements.rateRows.innerHTML = '<div class="rate-empty">The Rate Desk could not connect to the local service.</div>';
  }
}

function populateDemoFilters() {
  const quote = window.RATE_DESK_DEMO.quote;
  const origins = unique(quote.rates.flatMap((rate) => rate.origins));
  const destinations = unique(quote.rates.flatMap((rate) => rate.destinations));
  populateSelect(elements.collectionSelect, Object.keys(quote.haulage), "None — port drop-off", "Abbots Bromley", true);
  populateSelect(elements.originSelect, origins, "Any origin", "Felixstowe", true);
  populateSelect(elements.destinationSelect, destinations, "Any destination", "Laem Chabang", true);
  populateEquipment("40HC");
  populateSelect(elements.materialSelect, MATERIAL_OPTIONS, "No materials", "All materials");
  setCollectionVisibility(true);
}

function populateConnectedFilters() {
  const rates = deskState.connectedRates;
  const metadata = deskState.filters || {};
  // Door-to-quay sheets still have a POL. Include it here so inline MSC
  // rates are presented as Collection → POL → POD rather than collection-only.
  const origins = unique(metadata.origins || rates.map((rate) => firstPresent(rate.pol, "")));
  const destinations = unique(metadata.destinations || rates.map(rateDestination));
  const equipment = unique(metadata.equipment_types || rates.map((rate) => rate.equipment_type));
  const materials = unique(metadata.materials || rates.flatMap((rate) => rate.materials || []));
  const pickups = Array.isArray(deskState.filters.door_pickups) ? deskState.filters.door_pickups : [];
  const doorCollections = uniqueLocations(
    rates
      .filter((rate) => isDoorRate(rate))
      .map(rateCollection)
      .filter(Boolean)
  );

  populateSelect(elements.originSelect, origins, "Any origin", origins[0] || "", true);
  populateSelect(elements.destinationSelect, destinations, "Any destination", destinations[0] || "", true);
  populateEquipment(canonicalEquipment(equipment[0] || "40HC"));
  populateSelect(
    elements.materialSelect,
    ["All materials", ...(materials.length ? materials : MATERIAL_OPTIONS.slice(1))],
    "No materials",
    "All materials",
  );
  refreshCollectionOptions();
}

function refreshCollectionOptions() {
  if (RATE_DESK_DEMO_MODE) return;
  const pickups = Array.isArray(deskState.filters.door_pickups) ? deskState.filters.door_pickups : [];
  const haulagePickupNames = uniqueLocations(pickups.map((pickup) => pickup.name || pickup.location).filter(Boolean));
  const doorCollections = uniqueLocations(deskState.filters.collection_places || []);
  const current = elements.collectionSelect.value || "";
  const pickupNames = uniqueLocations([...haulagePickupNames, ...doorCollections]);

  if (pickupNames.length) {
    populateSelect(elements.collectionSelect, pickupNames, "None — not filtered", current, true);
    setCollectionVisibility(true);
  } else {
    elements.collectionSelect.innerHTML = '<option value="">None — not filtered</option>';
    elements.collectionSelect.value = "";
    elements.collectionSelect.disabled = true;
    setCollectionVisibility(false);
  }
}

function populateEquipment(preferred) {
  elements.equipmentSelect.innerHTML = EQUIPMENT_OPTIONS
    .map((item) => `<option value="${item.value}">${item.label}</option>`)
    .join("");
  elements.equipmentSelect.value = EQUIPMENT_OPTIONS.some((item) => item.value === preferred) ? preferred : "40HC";
  elements.equipmentSelect.disabled = false;
}

function populateSelect(select, values, emptyLabel, preferred = "", includeBlank = false) {
  const clean = unique(values.filter(Boolean));
  select.innerHTML = [
    ...(includeBlank ? [`<option value="">${escapeHtml(emptyLabel)}</option>`] : []),
    ...clean.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`),
  ].join("");
  if (!clean.length && !includeBlank) {
    select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>`;
    select.disabled = true;
    return;
  }
  select.value = [...(includeBlank ? [""] : []), ...clean].includes(preferred) ? preferred : (includeBlank ? "" : clean[0]);
  select.disabled = false;
}

function setCollectionVisibility(visible) {
  elements.collectionField.hidden = !visible;
  elements.collectionArrow.hidden = !visible;
}

function resetAndRender() {
  deskState.expandedId = null;
  deskState.pageOffset = 0;
  if (RATE_DESK_DEMO_MODE) {
    renderDesk();
    return;
  }
  scheduleRefresh();
}

function scheduleRefresh() {
  if (deskState.searchTimer) clearTimeout(deskState.searchTimer);
  deskState.searchTimer = setTimeout(() => refreshConnectedRates(), 220);
}

async function refreshConnectedRates(initial = false) {
  const collection = elements.collectionSelect.value;
  const origin = elements.originSelect.value;
  const destination = elements.destinationSelect.value;
  const equipment = elements.equipmentSelect.value;
  const params = new URLSearchParams({
    limit: String(deskState.pageSize),
    offset: String(deskState.pageOffset),
  });
  if (collection) params.set("collection", collection);
  if (origin) params.set("pol", origin);
  if (destination) params.set("pod", destination);
  if (equipment) params.set("equipment_type", equipment);
  if (elements.materialSelect.value && elements.materialSelect.value !== "All materials") {
    params.set("material", elements.materialSelect.value);
  }

  if (deskState.searchController) deskState.searchController.abort();
  const controller = new AbortController();
  deskState.searchController = controller;

  try {
    const response = await window.RATE_DESK_AUTH.apiFetch(`/api/rate-desk/search?${params.toString()}`, { signal: controller.signal });
    if (!response.ok) throw new Error("The approved-rate service did not respond.");
    const payload = await response.json();
    if (controller.signal.aborted) return;
    deskState.connectedRates = (Array.isArray(payload.rates) ? payload.rates : []).filter((rate) => !isSpotRate(rate));
    deskState.initialConnectedRates = deskState.connectedRates;
    deskState.totalMatches = Number(payload.pagination?.total || deskState.connectedRates.length);
    deskState.hasMore = Boolean(payload.pagination?.has_more);
    renderDesk();
  } catch (error) {
    if (error.name === "AbortError" || controller.signal.aborted) return;
    showAlert(`Could not update quotes: ${error.message}`);
    if (!initial) deskState.connectedRates = deskState.initialConnectedRates;
    renderDesk();
  } finally {
    if (deskState.searchController === controller) deskState.searchController = null;
  }
}

function changePage(direction) {
  const nextOffset = deskState.pageOffset + direction * deskState.pageSize;
  if (nextOffset < 0 || (direction > 0 && !deskState.hasMore)) return;
  deskState.pageOffset = nextOffset;
  deskState.expandedId = null;
  refreshConnectedRates();
}

function renderDesk() {
  if (!deskState.loaded) return;
  hideAlert();
  updateSortHeaders();
  updatePagination();

  const quantity = clampQuantity(elements.qtyInput.value);
  elements.qtyInput.value = quantity;
  const rows = RATE_DESK_DEMO_MODE ? buildDemoRows(quantity) : buildConnectedRows(quantity);

  const collection = elements.collectionSelect.value;
  const laneParts = [
    ...(collection ? [collection] : []),
    elements.originSelect.value || "Any origin",
    elements.destinationSelect.value || "Any destination",
  ];
  elements.laneTitle.textContent = isAllQuotesView()
    ? allQuotesTitle()
    : laneParts.join(" → ");
  elements.figuresNote.textContent = quantity > 1
    ? `Figures are USD equivalents for the whole booking (${quantity} × ${formatEquipment(elements.equipmentSelect.value)}). Per-B/L charges are not multiplied.`
    : `Figures are USD equivalents per ${formatEquipment(elements.equipmentSelect.value)}.`;

  if (!rows.length) {
    const hasExpiredHidden = !elements.showExpiredToggle.checked && hasExpiredMatches();
    elements.laneSummary.textContent = isAllQuotesView()
      ? "no approved quotes match the current filters"
      : "no parsed rates on this lane";
    elements.rateRows.innerHTML = `<div class="rate-empty">${
      hasExpiredHidden
        ? "No current rates match these filters. Turn on Show expired to inspect expired quotes."
        : "No parsed rates match the current filters."
    }</div>`;
    return;
  }

  const best = rows.filter((row) => !row.poa).sort(compareAllInUsdRows)[0];
  const expiredCount = rows.filter((row) => row.expired).length;
  const hiddenExpiredCount = !elements.showExpiredToggle.checked ? countHiddenExpiredMatches() : 0;
  const scopeLabel = collection ? "routing option" : "contract rate";
  const visibleCount = RATE_DESK_DEMO_MODE ? rows.length : deskState.totalMatches || rows.length;
  const countLabel = `${visibleCount} ${scopeLabel}${visibleCount === 1 ? "" : "s"}`;
  const bestLabel = best ? ` · best ${formatUsd(best.totalUsd)} all-in` : "";
  const expiredLabel = expiredCount ? ` · ${expiredCount} expired` : "";
  const hiddenLabel = hiddenExpiredCount ? ` · ${hiddenExpiredCount} expired hidden` : "";
  elements.laneSummary.textContent = `${countLabel}${bestLabel}${expiredLabel}${hiddenLabel}`;

  const showBest = rows.filter((row) => !row.poa).length > 1;
  elements.rateRows.innerHTML = rows.map((row, index) => renderRate(row, index, showBest && row.id === best?.id)).join("");
  elements.rateRows.querySelectorAll("button[data-rate-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const rateId = button.dataset.rateId;
      deskState.expandedId = deskState.expandedId === rateId ? null : rateId;
      renderDesk();
      if (deskState.expandedId && !deskState.detailCache.has(rateId)) loadOfferDetail(rateId);
    });
  });
}

function updatePagination() {
  if (RATE_DESK_DEMO_MODE || deskState.totalMatches <= deskState.pageSize) {
    elements.paginationControls.hidden = true;
    return;
  }
  const start = deskState.pageOffset + 1;
  const end = Math.min(deskState.pageOffset + deskState.connectedRates.length, deskState.totalMatches);
  elements.paginationControls.hidden = false;
  elements.previousPageButton.disabled = deskState.pageOffset <= 0;
  elements.nextPageButton.disabled = !deskState.hasMore;
  elements.paginationSummary.textContent = `${start}–${end} of ${deskState.totalMatches}`;
}

async function loadOfferDetail(offerId) {
  if (deskState.detailLoading.has(offerId)) return;
  deskState.detailLoading.add(offerId);
  deskState.detailErrors.delete(offerId);
  renderDesk();
  try {
    const response = await window.RATE_DESK_AUTH.apiFetch(`/api/rate-desk/offers/${encodeURIComponent(offerId)}`);
    if (!response.ok) throw new Error("The quote detail could not be loaded.");
    deskState.detailCache.set(offerId, await response.json());
  } catch (error) {
    if (error.name !== "AbortError") {
      deskState.detailErrors.set(offerId, error.message);
      showAlert(error.message);
    }
  } finally {
    deskState.detailLoading.delete(offerId);
    renderDesk();
  }
}

function buildDemoRows(quantity) {
  const quote = window.RATE_DESK_DEMO.quote;
  const origin = elements.originSelect.value;
  const destination = elements.destinationSelect.value;
  const equipment = elements.equipmentSelect.value;
  const material = elements.materialSelect.value;
  const collection = elements.collectionSelect.value;
  const baseRates = quote.rates.filter((rate) =>
    matchesFilter(rate.origins, origin)
    && matchesFilter(rate.destinations, destination)
    && (!equipment || canonicalEquipment(rate.equipment) === equipment)
    && (material === "All materials" || rate.materials.includes(material)));

  const rows = [];
  baseRates.forEach((rate) => {
    if (!collection) {
      if (rate.service === "Quay-to-quay") {
        rows.push(makeDemoVariant(rate, "quay", quantity, origin, ""));
      }
      return;
    }
    if (rate.service === "Door-to-quay" || rate.carrier === "Maersk") {
      rows.push(makeDemoVariant(rate, "door", quantity, origin, collection));
    }
    if (rate.service === "Quay-to-quay") {
      rows.push(makeDemoVariant(rate, "haulier", quantity, origin, collection));
    }
  });
  return sortViewRows(rows);
}

function makeDemoVariant(rate, mode, quantity, origin, collection) {
  const quote = window.RATE_DESK_DEMO.quote;
  const fx = quote.fx;
  const routeOrigin = firstPresent(origin, (rate.origins || [])[0]);
  const routeDestination = firstPresent(elements.destinationSelect.value, (rate.destinations || [])[0]);
  const originLines = rate.origin.map((line) => makeDemoLine(line, quantity, fx));
  let freightLines = rate.freight.map((line) => makeDemoLine(line, quantity, fx));
  const destinationLines = rate.destination.map((line) => makeDemoLine(line, quantity, fx));
  let inlandLines = [];
  let poa = false;
  let routing = "Quay to quay";
  let routingDetail = "Quay to quay · container delivered to the origin quay by you";
  let sourceFile = rate.sourceFile;
  let service = rate.service || "Quay-to-quay";
  let fineprint = "";

  if (mode === "door") {
    const isPublishedDoorRate = rate.service === "Door-to-quay";
    if (!isPublishedDoorRate) {
      const uplift = quote.doorUplift[collection] || 0;
      freightLines = freightLines.map((line) => line.name === "Basic Ocean Freight"
        ? makeLineView({ ...line, name: "Basic Ocean Freight — door-to-quay", unit: line.unit + uplift }, quantity, fx)
        : line);
      sourceFile = "MAERSK_DOOR_299077037_JUL.xlsx";
    }
    inlandLines = [makeLineView({
      name: `Inland Haulage Export — ${collection}`,
      basis: "Container",
      ccy: "—",
      unit: 0,
      included: true,
    }, quantity, fx)];
    routing = "Door to quay";
    routingDetail = "Door to quay · carrier haulage included in freight, not itemised";
    service = "Door-to-quay";
    fineprint = `Inland haulage from ${collection} is included in the freight price — ${rate.carrier} door rates do not itemise it.`;
  }

  if (mode === "haulier") {
    const tariff = quote.haulage[collection]?.[origin];
    poa = !tariff;
    inlandLines = [makeLineView({
      name: `Inland Haulage — ${collection} → ${origin} (UK Inland Haulage)`,
      basis: "Container",
      ccy: "GBP",
      unit: tariff || 0,
      poa,
    }, quantity, fx)];
    routing = "Quay to quay + your haulier";
    routingDetail = poa
      ? "Quay to quay + your haulier · no tariff rate on this corridor"
      : `Quay to quay + your haulier · £${formatNumber(tariff)}/ctn · separate haulier booking`;
    if (poa) {
      fineprint = `UK Inland Haulage has no ${collection} → ${origin} rate — request a haulage quote to price this routing.`;
    }
  }

  const groups = [
    ...(inlandLines.length ? [makeGroup("inland", "Inland haulage", inlandLines)] : []),
    makeGroup("origin", "Origin", originLines),
    makeGroup("freight", "Freight", freightLines),
    makeGroup("destination", "Destination", destinationLines),
  ];
  const totalUsd = sumGroups(groups);
  const services = [{ label: service, file: sourceFile }];
  if (mode === "haulier") {
    services.push({ label: "+ UK Inland Haulage", file: "UK Haulage — Export Haulage all UK POLs, Q2 2026 validity.xlsx" });
  }
  return {
    id: `${rate.id}-${mode}`,
    type: "CONTRACT",
    routeLane: formatRouteLane(
      ...(mode === "door" || mode === "haulier" ? [collection] : []),
      routeOrigin,
      routeDestination,
    ),
    routing,
    routingDetail,
    carrier: rate.carrier || "Maersk",
    services,
    transit: extractTransit(rate.sailing),
    validity: rate.validity,
    validTo: "",
    sailing: rate.sailing,
    freetime: rate.freetime,
    groups,
    inlandUsd: groupTotal(groups, "inland"),
    originUsd: groupTotal(groups, "origin"),
    freightUsd: groupTotal(groups, "freight"),
    destinationUsd: groupTotal(groups, "destination"),
    totalUsd,
    poa,
    zeroChargeCount: rate.zeroChargeCount || 0,
    fineprint,
    quantity,
    equipment: rate.equipment,
  };
}

function makeDemoLine(tuple, quantity, fx) {
  return makeLineView({
    name: tuple[0],
    basis: tuple[1],
    ccy: tuple[2],
    unit: tuple[3],
  }, quantity, fx);
}

function buildConnectedRows(quantity) {
  const collection = elements.collectionSelect.value;
  const portRates = filterConnectedRates({ includeExpired: elements.showExpiredToggle.checked, kind: "port" })
    .map((rate) => makeConnectedRow(rate, quantity));
  const doorRates = filterConnectedRates({ includeExpired: elements.showExpiredToggle.checked, kind: "door" })
    .map((rate) => makeConnectedDoorRow(rate, quantity));
  const haulageRates = collection
    ? filterConnectedRates({ includeExpired: elements.showExpiredToggle.checked, kind: "port" })
      .filter((rate) => canAttachMerchantHaulage(rate))
      .map((rate) => makeConnectedHaulierRow(rate, quantity, collection))
    : [];

  return sortViewRows(collection
    ? [...doorRates, ...haulageRates]
    : [...portRates, ...doorRates]);
}

function makeConnectedRow(rate, quantity) {
  const detail = deskState.detailCache.get(rate.offer_id);
  const groups = detail ? connectedGroups({ ...rate, ...detail }, quantity) : [];
  const totalUsd = detail
    ? sumGroups(groups)
    : (numberValue(rate.all_in_usd) || 0) * quantity;
  const sourceFile = rate.source_file_name || rate.raw_sheet_name || "Approved rate";
  const expired = isExpiredRate(rate);
  const carrier = carrierLabel(rate);
  return {
    id: String(rate.offer_id || `${sourceFile}-${rate.raw_row_reference || "row"}`),
    type: "CONTRACT",
    routeLane: formatRouteLane(rateOrigin(rate), rateDestination(rate)),
    routing: formatRouting(rate),
    routingDetail: laneDetail(rate),
    carrier,
    services: [{ label: serviceLabel(rate), file: sourceFile }],
    transit: rate.transit_time_days ? `${rate.transit_time_days}d` : extractTransit(rate.routing_note || ""),
    validity: validityLabel(rate.valid_from, rate.valid_to, expired),
    validTo: rate.valid_to || "",
    sailing: rate.routing_note || "",
    freetime: extractFreetime(rate),
    groups,
    inlandUsd: detail ? groupTotal(groups, "inland") : 0,
    originUsd: detail ? groupTotal(groups, "origin") : (numberValue(rate.origin_usd) || 0) * quantity,
    freightUsd: detail ? groupTotal(groups, "freight") : (numberValue(rate.freight_usd) || 0) * quantity,
    destinationUsd: detail ? groupTotal(groups, "destination") : (numberValue(rate.destination_usd) || 0) * quantity,
    totalUsd,
    poa: false,
    expired,
    zeroChargeCount: detail
      ? groups.reduce((sum, group) => sum + group.zeroLines.length, 0)
      : Number(rate.zero_charge_count || 0),
    fineprint: "",
    quantity,
    equipment: rate.equipment_type,
    detailLoaded: Boolean(detail),
    detailLoading: deskState.detailLoading.has(rate.offer_id),
  };
}

function makeConnectedDoorRow(rate, quantity) {
  const sourceFile = rate.source_file_name || rate.raw_sheet_name || "Approved rate";
  const customerRateLabel = normalized(rate.offer_reference) === "peute" ? "PEUTE" : "";
  const baseRow = makeConnectedRow(rate, quantity);
  const inlandZone = formatZoneLabel(rate.zone);
  const groups = baseRow.detailLoaded
    ? orderGroups([
      makeGroup("inland", "Inland haulage", [makeLineView({
        name: `Inland haulage included in quoted door-to-quay rate${inlandZone ? ` — ${inlandZone}` : ""}`,
        basis: "Container",
        ccy: "—",
        unit: 0,
        included: true,
      }, quantity, DEFAULT_FX)]),
      ...baseRow.groups,
    ])
    : baseRow.groups;
  return {
    ...baseRow,
    type: "CONTRACT",
    routeLane: formatRouteLane(
      rateCollection(rate),
      rate.pol,
      rateDestination(rate),
    ),
    routing: "Door to quay",
    routingDetail: laneDetail(rate),
    services: [
      { label: "Door-to-quay", file: sourceFile },
      ...(customerRateLabel ? [{ label: customerRateLabel, file: sourceFile, customerSpecific: true }] : []),
    ],
    groups,
    inlandIncluded: true,
    inlandZone,
    fineprint: `Inland haulage is included in the quoted door-to-quay rate${inlandZone ? ` via ${inlandZone}` : ""}; it is not itemised separately by the carrier.`,
  };
}

function makeConnectedHaulierRow(rate, quantity, collection) {
  const row = makeConnectedRow(rate, quantity);
  const port = merchantHaulagePort(rate);
  const tariff = findHaulageTariff(collection, port);
  const poa = tariff == null;
  const inlandLines = [makeLineView({
    name: `Inland Haulage — ${collection} → ${port} (UK Inland Haulage)`,
    basis: "Container",
    ccy: deskState.haulageCurrency || "USD",
    unit: tariff || 0,
    poa,
  }, quantity, DEFAULT_FX)];
  const groups = orderGroups([makeGroup("inland", "Inland haulage", inlandLines), ...row.groups]);
  return {
    ...row,
    id: `${row.id}-haulage-${slugify(collection)}`,
    type: "CONTRACT",
    routeLane: formatRouteLane(collection, port, rateDestination(rate)),
    routing: "Quay to quay + your haulier",
    routingDetail: poa
      ? `${collection} → ${port} → ${rateDestination(rate)} · no tariff rate for ${collection} → ${port}`
      : `${collection} → ${port} → ${rateDestination(rate)} · ${formatMoney(tariff, deskState.haulageCurrency)}/ctn · separate haulier booking`,
    services: [...row.services, { label: "+ UK Inland Haulage", file: "UK Inland Haulage" }],
    groups,
    inlandUsd: groupTotal(groups, "inland"),
    totalUsd: sumGroups(groups),
    poa,
    fineprint: poa
      ? `UK Inland Haulage has no ${collection} → ${port} tariff in the approved sheet — request a haulage quote.`
      : row.fineprint,
  };
}

function connectedGroups(rate, quantity) {
  const analysisGroups = Array.isArray(rate.charge_analysis?.groups) ? rate.charge_analysis.groups : null;
  if (analysisGroups) {
    const groups = analysisGroups.map((group) => {
      const lines = (group.lines || []).map((line) => makeLineView({
        name: line.name,
        basis: line.basis,
        ccy: line.currency || "USD",
        unit: numberValue(line.unit_amount) || 0,
        usdUnit: numberValue(line.usd_unit_amount),
        zeroRated: Boolean(line.zero_rated),
        countsTowardTotal: line.counts_toward_total !== false,
      }, quantity, DEFAULT_FX, line.quantity_rule));
      return makeGroup(group.key, (group.label || group.key).replace(" charges", ""), lines);
    });
    if (Array.isArray(rate.charge_analysis.unmatched_lines) && rate.charge_analysis.unmatched_lines.length) {
      const lines = rate.charge_analysis.unmatched_lines.map((line) => makeLineView({
        name: line.name,
        basis: line.basis,
        ccy: line.currency || "USD",
        unit: numberValue(line.unit_amount) || 0,
        usdUnit: numberValue(line.usd_unit_amount),
        zeroRated: Boolean(line.zero_rated),
        countsTowardTotal: line.counts_toward_total !== false,
      }, quantity, DEFAULT_FX, line.quantity_rule));
      groups.push(makeGroup("unmatched", "Unmapped", lines));
    }
    return orderGroups(groups);
  }

  const raw = Array.isArray(rate.charges) ? rate.charges : [];
  const lines = raw.map((charge) => makeLineView({
    name: charge.charge_name || charge.name || "Charge",
    basis: charge.basis || "Container",
    ccy: charge.currency || charge.ccy || rate.base_currency || "USD",
    unit: numberValue(charge.amount ?? charge.unit) || 0,
  }, quantity, DEFAULT_FX));
  if (!raw.some(isBaseCharge) && rate.base_amount != null) {
    lines.push(makeLineView({
      name: rate.all_in_flag === true ? "All-in as quoted" : "Basic Ocean Freight",
      basis: "Container",
      ccy: rate.base_currency || "USD",
      unit: numberValue(rate.base_amount) || 0,
    }, quantity, DEFAULT_FX));
  }
  return orderGroups(["origin", "freight", "destination"].map((key) =>
    makeGroup(key, capitalize(key), lines.filter((line) => bucketForLine(line) === key))));
}

function makeLineView(line, quantity, fx, quantityRule = "") {
  const basis = line.basis || "Container";
  const qty = quantityRule === "per_bill_of_lading" || quantityRule === "percent"
    ? 1
    : quantityForBasis(basis, quantity);
  const ccy = (line.ccy || "USD").toUpperCase();
  const unit = numberValue(line.unit) || 0;
  const usdExact = line.included || line.poa
    ? 0
    : line.usdUnit != null
      ? line.usdUnit * qty
      : unit * qty * (fx[ccy] || 1);
  return {
    name: line.name || "Charge",
    basis,
    qty,
    ccy,
    unit,
    usdExact,
    countsTowardTotal: line.countsTowardTotal !== false,
    excludedFromTotal: line.countsTowardTotal === false,
    included: Boolean(line.included),
    poa: Boolean(line.poa),
    zeroRated: Boolean(line.zeroRated) || (!line.included && !line.poa && unit === 0),
  };
}

function makeGroup(key, label, allLines) {
  const lines = allLines.filter((line) => !line.zeroRated);
  const zeroLines = allLines.filter((line) => line.zeroRated);
  return {
    key,
    label,
    lines,
    zeroLines,
    subtotalUsd: allLines.reduce(
      (sum, line) => sum + (line.countsTowardTotal === false ? 0 : line.usdExact),
      0,
    ),
    hasPoa: allLines.some((line) => line.poa),
  };
}

function orderGroups(groups) {
  const order = ["inland", "origin", "freight", "destination", "unmatched"];
  return groups
    .filter((group) => group.lines.length || group.zeroLines.length || group.subtotalUsd)
    .sort((left, right) => order.indexOf(left.key) - order.indexOf(right.key));
}

function renderRate(row, index, isBest) {
  const expanded = deskState.expandedId === row.id;
  const detailIncludesLane = row.routeLane && normalized(row.routingDetail).startsWith(normalized(row.routeLane));
  const routingTitle = detailIncludesLane
    ? row.routingDetail
    : [row.routeLane, row.routingDetail].filter(Boolean).join(" · ");
  return `
    <article class="rate-record">
      <button class="quote-grid quote-row${row.poa ? " poa-row" : ""}${row.expired ? " expired-row" : ""}" type="button" data-rate-id="${escapeAttr(row.id)}" aria-expanded="${expanded}">
        <span><span class="type-chip">${escapeHtml(row.type)}</span></span>
        <span class="${isBest ? "rank best-rank" : "rank"}">${row.defaultRank || index + 1}</span>
        <span class="routing-cell" title="${escapeAttr(routingTitle)}">
          <strong class="routing-lane">${escapeHtml(row.routeLane || row.routing)}</strong>
          <small class="routing-type">${escapeHtml(row.routing)}</small>
        </span>
        <span class="carrier-name">${escapeHtml(row.carrier || "—")}</span>
        <span class="service-tags">${row.services.map((serviceItem) => `<span class="${serviceItem.customerSpecific ? "customer-rate-tag" : ""}" title="${escapeAttr(`${row.carrier} · ${serviceItem.file}`)}">${escapeHtml(serviceItem.label)}</span>`).join("")}</span>
        <span class="mono transit-value">${escapeHtml(row.transit || "—")}</span>
        <span class="number">${renderInland(row)}</span>
        <span class="number component-value">${escapeHtml(formatUsd(row.originUsd))}</span>
        <span class="number component-value">${escapeHtml(formatUsd(row.freightUsd))}</span>
        <span class="number component-value">${escapeHtml(formatUsd(row.destinationUsd))}</span>
        <span class="number all-in-cell">
          <strong>${escapeHtml(formatUsd(row.totalUsd))}</strong>
          ${row.poa ? '<small>+ haulage POA</small>' : ""}
        </span>
        <span class="number validity-text${row.expired ? " is-expired" : ""}">${escapeHtml(row.validity)}</span>
      </button>
      ${expanded ? renderBreakdown(row) : ""}
    </article>
  `;
}

function renderInland(row) {
  if (row.poa) return '<span class="poa-chip">POA</span>';
  const inlandGroup = row.groups.find((group) => group.key === "inland");
  if (row.inlandIncluded || inlandGroup?.lines.some((line) => line.included)) {
    return `<span class="included-inland"><strong>Included</strong>${row.inlandZone ? `<small>${escapeHtml(row.inlandZone)}</small>` : ""}</span>`;
  }
  if (!inlandGroup) {
    return '<span class="muted-mono">—</span>';
  }
  return `<span class="component-value">${escapeHtml(formatUsd(row.inlandUsd))}</span>`;
}

function formatZoneLabel(value) {
  const zone = String(value || "").trim();
  if (!zone) return "";
  const match = zone.match(/(?:ZONE\s*)?(\d+)/i);
  return match ? `Zone ${match[1]}` : zone;
}

function renderBreakdown(row) {
  if (deskState.detailErrors.has(row.id)) {
    return `<div class="rate-breakdown"><div class="breakdown-panel"><div class="rate-empty">${escapeHtml(deskState.detailErrors.get(row.id))}</div></div></div>`;
  }
  if (row.detailLoading || (deskState.expandedId === row.id && !row.detailLoaded)) {
    return '<div class="rate-breakdown"><div class="breakdown-panel"><div class="rate-empty">Loading charge breakdown…</div></div></div>';
  }
  if (!row.detailLoaded) {
    return '<div class="rate-breakdown"><div class="breakdown-panel"><div class="rate-empty">Charge breakdown unavailable.</div></div></div>';
  }
  const totalLabel = row.quantity > 1
    ? `Total per booking (${row.quantity} × ${formatEquipment(row.equipment)})`
    : `Total per ${formatEquipment(row.equipment)}`;
  return `
    <div class="rate-breakdown">
      ${(row.sailing || row.freetime) ? `
        <div class="breakdown-meta">
          ${row.sailing ? `<span class="mono">${escapeHtml(row.sailing)}</span>` : ""}
          ${row.freetime ? `<span class="freetime-chip">${escapeHtml(row.freetime)}</span>` : ""}
        </div>` : ""}
      <div class="breakdown-panel">
        <div class="breakdown-header">
          <span>Charge</span><span>Basis</span><span class="number">Unit price</span><span class="number">USD</span>
        </div>
        ${row.groups.map(renderGroup).join("")}
        <div class="breakdown-total">
          <span>${escapeHtml(totalLabel)}${row.poa ? " — priced legs only" : ""}</span>
          <strong>${escapeHtml(formatUsd(row.totalUsd))}</strong>
        </div>
      </div>
      ${row.zeroChargeCount ? `<div class="zero-note">+ ${row.zeroChargeCount} charges on the sheet at 0 — collapsed from this view.</div>` : ""}
      ${row.fineprint ? `<div class="fine-print">${escapeHtml(row.fineprint)}</div>` : ""}
    </div>
  `;
}

function renderGroup(group) {
  const subtotal = group.hasPoa ? `${formatUsd(group.subtotalUsd)} + POA` : formatUsd(group.subtotalUsd);
  return `
    <div class="breakdown-band"><span>${escapeHtml(group.label)}</span><strong>${escapeHtml(subtotal)}</strong></div>
    ${group.lines.map(renderLine).join("")}
  `;
}

function renderLine(line) {
  let unit = `${line.ccy} ${formatNumber(line.unit)}${line.qty > 1 ? ` × ${line.qty}` : ""}`;
  let usd = `${line.ccy !== "USD" && line.usdExact !== 0 ? "≈ " : ""}${formatNumber(line.usdExact)}`;
  if (line.included) {
    unit = "—";
    usd = "Incl.";
  } else if (line.poa) {
    unit = `${line.ccy} POA`;
    usd = "—";
  } else if (line.excludedFromTotal) {
    usd = `${formatNumber(line.usdExact)} · excluded`;
  }
  return `
    <div class="breakdown-row">
      <span>${escapeHtml(line.name)}</span>
      <span class="dim">${escapeHtml(line.basis)}</span>
      <span class="number mono">${escapeHtml(unit)}</span>
      <span class="number mono">${escapeHtml(usd)}</span>
    </div>
  `;
}

function updateSortHeaders() {
  elements.sortButtons.forEach((button) => {
    const active = button.dataset.sortKey === deskState.sort?.key;
    const direction = active ? deskState.sort?.direction : null;
    const nextAction = !active
      ? "sort ascending"
      : direction === "asc"
        ? "sort descending"
        : "return to price order";
    const label = button.dataset.sortLabel || button.textContent.trim();
    button.classList.toggle("is-active", active);
    button.querySelector(".sort-indicator").textContent = active
      ? direction === "asc" ? "↑" : "↓"
      : "";
    button.parentElement.setAttribute("aria-sort", active
      ? direction === "asc" ? "ascending" : "descending"
      : "none");
    button.setAttribute("aria-label", `${label}. ${active ? `Sorted ${direction === "asc" ? "ascending" : "descending"}. ` : ""}Activate to ${nextAction}.`);
  });
}

function sortViewRows(rows) {
  const rankedRows = [...rows]
    .sort(compareAllInUsdRows)
    .map((row, index) => ({ ...row, defaultRank: index + 1 }));
  if (!deskState.sort) return rankedRows;
  return rankedRows.sort((left, right) => compareRowsByActiveSort(left, right));
}

function compareAllInUsdRows(left, right) {
  return comparePoaRows(left, right)
    || compareNumbers(left.totalUsd, right.totalUsd)
    || compareText(left.routeLane, right.routeLane)
    || compareText(serviceSortValue(left), serviceSortValue(right))
    || compareText(left.id, right.id);
}

function compareRowsByActiveSort(left, right) {
  const poaOrder = comparePoaRows(left, right);
  if (poaOrder) return poaOrder;
  const { key, direction } = deskState.sort;
  const leftValue = rowSortValue(left, key);
  const rightValue = rowSortValue(right, key);
  const leftMissing = leftValue === null || leftValue === undefined || leftValue === "";
  const rightMissing = rightValue === null || rightValue === undefined || rightValue === "";

  if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;

  let result = 0;
  if (!leftMissing) {
    result = typeof leftValue === "number" && typeof rightValue === "number"
      ? compareNumbers(leftValue, rightValue)
      : compareText(leftValue, rightValue);
  }
  if (result) return direction === "desc" ? -result : result;
  return compareNumbers(left.defaultRank, right.defaultRank);
}

function comparePoaRows(left, right) {
  if (Boolean(left.poa) === Boolean(right.poa)) return 0;
  return left.poa ? 1 : -1;
}

function rowSortValue(row, key) {
  if (key === "type") return row.type;
  if (key === "rank") return row.defaultRank;
  if (key === "routing") return [row.routeLane, row.routing].filter(Boolean).join(" ");
  if (key === "carrier") return row.carrier;
  if (key === "service") return serviceSortValue(row);
  if (key === "transit") return transitHours(row.transit);
  if (key === "inlandUsd") return hasPricedInland(row) ? row.inlandUsd : null;
  if (key === "originUsd") return row.originUsd;
  if (key === "freightUsd") return row.freightUsd;
  if (key === "destinationUsd") return row.destinationUsd;
  if (key === "totalUsd") return row.totalUsd;
  if (key === "validity") return validitySortValue(row);
  return row.defaultRank;
}

function serviceSortValue(row) {
  return (row.services || [])
    .map((serviceItem) => [serviceItem.label, serviceItem.file].filter(Boolean).join(" "))
    .join(" ");
}

function transitHours(value) {
  const match = String(value || "").match(/(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?/i);
  if (!match || (!match[1] && !match[2])) return null;
  return (Number(match[1]) || 0) * 24 + (Number(match[2]) || 0);
}

function hasPricedInland(row) {
  const inlandGroup = row.groups.find((group) => group.key === "inland");
  return Boolean(inlandGroup && !row.poa && !inlandGroup.lines.some((line) => line.included));
}

function validitySortValue(row) {
  const end = parseDate(row.validTo);
  if (end) return end.getTime();
  return normalized(row.validity);
}

function compareNumbers(left, right) {
  return Number(left) - Number(right);
}

function compareText(left, right) {
  return String(left || "").localeCompare(String(right || ""), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function sumGroups(groups) {
  return groups.reduce((sum, group) => sum + group.subtotalUsd, 0);
}

function groupTotal(groups, key) {
  return groups.find((group) => group.key === key)?.subtotalUsd || 0;
}

function formatRouting(rate) {
  const mode = normalized(rate.service_mode);
  if (isDoorServiceMode(mode)) return "Door to quay";
  return "Quay to quay";
}

function carrierLabel(rate) {
  const explicit = firstPresent(rate.carrier_name, rate.provider_name);
  if (explicit) return explicit;
  const combined = String(rate.carrier_label || "");
  return combined.split(/[·—]/)[0].trim() || "Carrier";
}

function serviceLabel(rate) {
  return isDoorRate(rate) ? "Door-to-quay" : "Quay-to-quay";
}

function laneDetail(rate) {
  if (isDoorRate(rate)) {
    const receipt = rateCollection(rate);
    const delivery = rateDestination(rate);
    const canonicalLane = [receipt, delivery].filter(Boolean).join(" → ");
    const rawLane = [
      firstPresent(rate.place_of_receipt, rate.origin),
      firstPresent(rate.final_destination, rate.pod),
    ].filter(Boolean).join(" → ");
    if (canonicalLane && rawLane && !sameValue(canonicalLane, rawLane)) {
      return `${canonicalLane} · Carrier wording: ${rawLane}`;
    }
    return canonicalLane || formatRouting(rate);
  }
  const origin = firstPresent(rate.pol, rate.place_of_receipt, rate.origin);
  const destination = rateDestination(rate);
  return [origin, destination].filter(Boolean).join(" → ") || formatRouting(rate);
}

function formatRouteLane(...parts) {
  const routeParts = [];
  parts.forEach((part) => {
    const value = String(part || "").trim();
    if (!value || sameValue(routeParts.at(-1), value)) return;
    routeParts.push(value);
  });
  return routeParts.join(" → ");
}

function validityLabel(validFrom, validTo, expired = false) {
  const start = parseDate(validFrom);
  const end = parseDate(validTo);
  if (expired && end) return `expired ${shortDate(end)}`;
  if (start && end) return `${shortDate(start)} → ${shortDate(end)}`;
  if (end) return `to ${shortDate(end)}`;
  if (start) return `from ${shortDate(start)}`;
  return "open";
}

function extractTransit(value) {
  const match = String(value || "").match(/(\d+d(?:\s+\d+h)?)/i);
  return match ? match[1] : "—";
}

function extractFreetime(rate) {
  const text = [rate.notes_summary, ...(rate.notes || []).map((note) => note.note_text)].filter(Boolean).join(" ");
  return text.match(/(\d+\s*d[^·,.]*)/i)?.[1] || "";
}

function quantityForBasis(basis, quantity) {
  const value = normalized(basis);
  if (value.includes("bill of lading") || value.includes("b/l") || value === "bl" || value.includes("booking") || value.includes("percent")) return 1;
  return quantity;
}

function bucketForLine(line) {
  const name = normalized(line.name);
  if (name.includes("origin") || name.includes("export") || name.includes("haulage") || name.includes("intermodal") || name.includes("pick")) return "origin";
  if (name.includes("destination") || name.includes("import") || name.includes("terminal") || name.includes("documentation") || name.includes("protect") || name.includes("delivery") || name.includes("thc")) return "destination";
  return "freight";
}

function isBaseCharge(charge) {
  const name = normalized(charge.charge_name || charge.name);
  return normalized(charge.charge_type) === "base" || name.includes("basic ocean freight") || name === "ocean freight";
}

function isSpotRate(rate) {
  return [rate.contract_tag, rate.carrier_label, rate.offer_reference, rate.source_file_name]
    .filter(Boolean)
    .some((value) => normalized(value).includes("spot"));
}

function isDoorRate(rate) {
  return [rate.contract_tag, rate.carrier_key, rate.carrier_label, rate.service_mode]
    .filter(Boolean)
    .some((value) => {
      const text = normalized(value);
      return text.includes("door") || isDoorServiceMode(text);
    });
}

function isDoorServiceMode(value) {
  const text = normalized(value);
  return text === "sd / cy" || text === "sd/cy" || text === "sd-cy" || text.startsWith("sd ");
}

function isHaulageRate(rate) {
  // Inline ocean rates can include haulage in their display label. Only exclude
  // a sheet that is explicitly an inland tariff from quote results.
  return normalized(rate.document_type) === "inland_export"
    || normalized(rate.carrier_key) === "haulage-q2"
    || normalized(rate.contract_tag) === "haul";
}

function rateOrigin(rate) {
  return firstPresent(rate.pol, rate.place_of_receipt, rate.origin);
}

function rateCollection(rate) {
  return firstPresent(
    rate.collection_location_name,
    rate.place_of_receipt,
    rate.origin,
  );
}

function rateDestination(rate) {
  return firstPresent(
    rate.destination_location_name,
    rate.final_destination,
    rate.pod,
  );
}

function merchantHaulagePort(rate) {
  const pol = firstPresent(rate.pol, "");
  return supportedHaulagePort(pol) ? pol : "";
}

function canAttachMerchantHaulage(rate) {
  return Boolean(merchantHaulagePort(rate));
}

function supportedHaulagePort(value) {
  if (!value) return false;
  const target = locationKey(value);
  return Object.values(deskState.haulageTariffs || {}).some((portMap) =>
    Object.keys(portMap || {}).some((port) => locationKey(port) === target));
}

function findHaulageTariff(collection, port) {
  const collectionEntry = Object.entries(deskState.haulageTariffs || {})
    .find(([name]) => locationsMatch(name, collection));
  if (!collectionEntry) return null;
  const portEntry = Object.entries(collectionEntry[1] || {})
    .find(([name]) => locationsMatch(name, port));
  return portEntry ? portEntry[1] : null;
}

function canonicalEquipment(value) {
  const text = normalized(value);
  if (["20", "20gp", "20ft", "20dv"].includes(text)) return "20GP";
  if (["40", "40gp"].includes(text)) return "40GP";
  if (["40hc", "40hq", "40'hc", "40′hc", "feu"].includes(text)) return "40HC";
  return String(value || "").toUpperCase();
}

function formatEquipment(value) {
  const canonical = canonicalEquipment(value);
  return EQUIPMENT_OPTIONS.find((item) => item.value === canonical)?.label || canonical || "container";
}

function clampQuantity(value) {
  const number = Math.round(Number(value));
  return Number.isFinite(number) ? Math.min(999, Math.max(1, number)) : 1;
}

function formatUsd(value) {
  return `$${Math.round(numberValue(value) || 0).toLocaleString("en-US")}`;
}

function formatMoney(value, currency = "USD") {
  const amount = formatNumber(value);
  const code = String(currency || "").toUpperCase();
  if (code === "USD") return `$${amount}`;
  if (code === "GBP") return `£${amount}`;
  if (code === "EUR") return `EUR ${amount}`;
  return `${code || "USD"} ${amount}`;
}

function formatNumber(value) {
  const number = numberValue(value) || 0;
  if (Number.isInteger(number)) return number.toLocaleString("en-US");
  return number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function numberValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function shortDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value || "—")
    : date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function shortDate(value) {
  return value.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function todayUtc() {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

function isExpiredRate(rate) {
  const end = parseDate(rate.valid_to);
  return Boolean(end && end.getTime() < todayUtc().getTime());
}

function matchesFilter(valueOrValues, selected) {
  if (!normalized(selected)) return true;
  if (Array.isArray(valueOrValues)) {
    return valueOrValues.some((value) => sameValue(value, selected));
  }
  return sameValue(valueOrValues, selected);
}

function showAllQuotes() {
  elements.collectionSelect.value = "";
  elements.originSelect.value = "";
  elements.destinationSelect.value = "";
  elements.equipmentSelect.value = "";
  elements.materialSelect.value = "All materials";
  elements.showExpiredToggle.checked = true;
  resetAndRender();
}

function isAllQuotesView() {
  return !elements.collectionSelect.value
    && !elements.originSelect.value
    && !elements.destinationSelect.value
    && !elements.equipmentSelect.value
    && elements.materialSelect.value === "All materials";
}

function allQuotesTitle() {
  return "All approved quotes";
}

function countHiddenExpiredMatches() {
  const kind = elements.collectionSelect.value ? "all" : "port";
  return filterConnectedRates({ includeExpired: true, kind }).filter((rate) => isExpiredRate(rate)).length;
}

function hasExpiredMatches() {
  return countHiddenExpiredMatches() > 0;
}

function filterConnectedRates({ includeExpired, kind }) {
  const origin = elements.originSelect.value;
  const destination = elements.destinationSelect.value;
  const equipment = elements.equipmentSelect.value;
  const material = elements.materialSelect.value;
  const collection = elements.collectionSelect.value;
  return deskState.connectedRates
    .filter((rate) => {
      if (isHaulageRate(rate)) return false;
      const doorRate = isDoorRate(rate);
      if (kind === "port" && doorRate) return false;
      if (kind === "door" && !doorRate) return false;
      if (!includeExpired && isExpiredRate(rate)) return false;
      if (!matchesFilter(rateDestination(rate), destination)) return false;
      if (equipment && canonicalEquipment(rate.equipment_type) !== equipment) return false;
      if (!(material === "All materials" || (rate.materials || []).some((item) => sameValue(item, material)))) return false;
      if (doorRate) {
        if (collection && !locationsMatch(rateCollection(rate), collection)) return false;
        const explicitPort = rate.pol || "";
        if (origin && explicitPort && !matchesFilter(explicitPort, origin)) return false;
        return true;
      }
      return matchesFilter(rateOrigin(rate), origin);
    });
}

function firstPresent(...values) {
  return values.find(Boolean) || "";
}

function sameValue(left, right) {
  return normalized(left) === normalized(right);
}

function locationKey(value) {
  return normalized(value)
    .replace(/[,\s]+(?:gb|uk)$/i, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function locationsMatch(left, right) {
  return Boolean(locationKey(left)) && locationKey(left) === locationKey(right);
}

function uniqueLocations(values) {
  const seen = new Set();
  return values.filter((value) => {
    const key = locationKey(value);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function normalized(value) {
  return String(value || "").trim().toLowerCase();
}

function capitalize(value) {
  const text = String(value || "");
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

function slugify(value) {
  return normalized(value).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function unique(values) {
  const seen = new Set();
  return values.filter((value) => {
    const key = normalized(value);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function showAlert(message) {
  elements.deskAlert.hidden = false;
  elements.deskAlert.className = "desk-alert error";
  elements.deskAlert.textContent = message;
}

function hideAlert() {
  elements.deskAlert.hidden = true;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}
