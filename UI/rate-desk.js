const RATE_DESK_DEMO_MODE = Boolean(window.RATE_DESK_CONFIG?.demoMode);
const DEFAULT_FX = { USD: 1, GBP: 1.29, EUR: 1.09, INR: 0.0104, THB: 0.0302 };
const EQUIPMENT_OPTIONS = [
  { value: "", label: "All sizes" },
  { value: "20GP", label: "20′" },
  { value: "40GP", label: "40′" },
  { value: "40HC", label: "40′ HC" },
];
const MATERIAL_OPTIONS = ["All materials", "Paper", "Metal", "Tyres"];
const ROUTING_MODE_OPTIONS = [
  { value: "all", label: "All routings" },
  { value: "port", label: "Port drop-off" },
  { value: "door", label: "Carrier door-to-quay" },
  { value: "haulage", label: "Merchant haulage" },
];

const deskState = {
  loaded: false,
  expandedId: null,
  connectedRates: [],
  filters: {},
  haulageTariffs: {},
  haulageCurrency: "USD",
};

const elements = {
  collectionField: document.getElementById("collectionField"),
  collectionArrow: document.getElementById("collectionArrow"),
  collectionSelect: document.getElementById("collectionSelect"),
  originSelect: document.getElementById("originSelect"),
  destinationSelect: document.getElementById("destinationSelect"),
  equipmentSelect: document.getElementById("equipmentSelect"),
  routingModeSelect: document.getElementById("routingModeSelect"),
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
};

[elements.collectionSelect, elements.originSelect, elements.destinationSelect, elements.equipmentSelect, elements.materialSelect]
  .forEach((element) => element.addEventListener("change", resetAndRender));
elements.routingModeSelect.addEventListener("change", () => {
  refreshCollectionOptions();
  resetAndRender();
});
elements.showExpiredToggle.addEventListener("change", resetAndRender);
elements.showAllQuotesButton.addEventListener("click", showAllQuotes);
elements.qtyInput.addEventListener("change", () => {
  elements.qtyInput.value = clampQuantity(elements.qtyInput.value);
  resetAndRender();
});
elements.qtyInput.addEventListener("input", () => {
  if (elements.qtyInput.value !== "") resetAndRender();
});

bootRateDesk();

async function bootRateDesk() {
  elements.demoBadge.hidden = !RATE_DESK_DEMO_MODE;
  if (RATE_DESK_DEMO_MODE) {
    deskState.loaded = true;
    populateDemoFilters();
    elements.refreshText.textContent = "Frontend preview · session only";
    renderDesk();
    return;
  }

  try {
    const response = await fetch("/api/rate-desk?limit=5000");
    if (!response.ok) throw new Error("The approved-rate service did not respond.");
    const payload = await response.json();
    deskState.connectedRates = (Array.isArray(payload.rates) ? payload.rates : []).filter((rate) => !isSpotRate(rate));
    deskState.filters = payload.filters || {};
    deskState.haulageTariffs = payload.haulage_tariffs || {};
    deskState.haulageCurrency = payload.haulage_currency || "USD";
    deskState.loaded = true;
    populateConnectedFilters();
    elements.refreshText.textContent = payload.last_refreshed
      ? `Rates refreshed ${shortDateTime(payload.last_refreshed)}`
      : "Rates refreshed from approved data";
    renderDesk();
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
  populateRoutingModes("all");
  populateSelect(elements.materialSelect, MATERIAL_OPTIONS, "No materials", "All materials");
  setCollectionVisibility(true);
}

function populateConnectedFilters() {
  const rates = deskState.connectedRates;
  const nonDoorRates = rates.filter((rate) => !isDoorRate(rate));
  const defaultRate = (nonDoorRates[0] || rates[0] || {});
  const origins = unique(
    nonDoorRates
      .map((rate) => firstPresent(rate.pol, ""))
      .filter(Boolean)
  );
  const destinations = unique(deskState.filters.destinations || rates.map(rateDestination));
  const equipment = unique(deskState.filters.equipment_types || nonDoorRates.map((rate) => rate.equipment_type));
  const materials = unique(deskState.filters.materials || rates.flatMap((rate) => rate.materials || []));
  const pickups = Array.isArray(deskState.filters.door_pickups) ? deskState.filters.door_pickups : [];
  const doorCollections = unique(
    rates
      .filter((rate) => isDoorRate(rate))
      .map((rate) => firstPresent(rate.place_of_receipt, rate.origin))
      .filter(Boolean)
  );

  populateSelect(elements.originSelect, origins, "Any origin", firstPresent(defaultRate.pol, "") || origins[0] || "", true);
  populateSelect(elements.destinationSelect, destinations, "Any destination", rateDestination(defaultRate) || destinations[0] || "", true);
  populateEquipment(canonicalEquipment(defaultRate.equipment_type || equipment[0] || "40HC"));
  populateRoutingModes("all");
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
  const haulagePickupNames = unique(pickups.map((pickup) => pickup.name || pickup.location).filter(Boolean));
  const doorCollections = unique(
    deskState.connectedRates
      .filter((rate) => isDoorRate(rate))
      .map((rate) => firstPresent(rate.place_of_receipt, rate.origin))
      .filter(Boolean)
  );
  const current = elements.collectionSelect.value || "";
  const mode = elements.routingModeSelect.value || "all";
  const pickupNames = mode === "haulage"
    ? haulagePickupNames
    : mode === "door"
      ? doorCollections
      : unique([...haulagePickupNames, ...doorCollections]);

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

function populateRoutingModes(preferred) {
  elements.routingModeSelect.innerHTML = ROUTING_MODE_OPTIONS
    .map((item) => `<option value="${item.value}">${item.label}</option>`)
    .join("");
  elements.routingModeSelect.value = ROUTING_MODE_OPTIONS.some((item) => item.value === preferred) ? preferred : "all";
  elements.routingModeSelect.disabled = false;
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
  renderDesk();
}

function renderDesk() {
  if (!deskState.loaded) return;
  hideAlert();

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
    const needsCollection = elements.routingModeSelect.value === "haulage" && !elements.collectionSelect.value;
    elements.laneSummary.textContent = isAllQuotesView()
      ? "no approved quotes match the current filters"
      : "no parsed rates on this lane";
    elements.rateRows.innerHTML = `<div class="rate-empty">${
      needsCollection
        ? "Select a collection place to see merchant-haulage options."
        : hasExpiredHidden
        ? "No current rates match these filters. Turn on Show expired to inspect expired quotes."
        : "No parsed rates match the current filters."
    }</div>`;
    return;
  }

  const best = rows.find((row) => !row.poa);
  const expiredCount = rows.filter((row) => row.expired).length;
  const hiddenExpiredCount = !elements.showExpiredToggle.checked ? countHiddenExpiredMatches() : 0;
  const scopeLabel = collection ? "routing option" : "contract rate";
  const countLabel = `${rows.length} ${scopeLabel}${rows.length === 1 ? "" : "s"}`;
  const bestLabel = best ? ` · best ${formatUsd(best.totalUsd)} all-in` : "";
  const expiredLabel = expiredCount ? ` · ${expiredCount} expired` : "";
  const hiddenLabel = hiddenExpiredCount ? ` · ${hiddenExpiredCount} expired hidden` : "";
  elements.laneSummary.textContent = `${countLabel}${bestLabel}${expiredLabel}${hiddenLabel}`;

  const showBest = rows.filter((row) => !row.poa).length > 1;
  elements.rateRows.innerHTML = rows.map((row, index) => renderRate(row, index, showBest && row.id === best?.id)).join("");
  elements.rateRows.querySelectorAll("button[data-rate-id]").forEach((button) => {
    button.addEventListener("click", () => {
      deskState.expandedId = deskState.expandedId === button.dataset.rateId ? null : button.dataset.rateId;
      renderDesk();
    });
  });
}

function buildDemoRows(quantity) {
  const quote = window.RATE_DESK_DEMO.quote;
  const origin = elements.originSelect.value;
  const destination = elements.destinationSelect.value;
  const equipment = elements.equipmentSelect.value;
  const material = elements.materialSelect.value;
  const collection = elements.collectionSelect.value;
  const mode = elements.routingModeSelect.value || "all";
  const baseRates = quote.rates.filter((rate) =>
    matchesFilter(rate.origins, origin)
    && matchesFilter(rate.destinations, destination)
    && (!equipment || canonicalEquipment(rate.equipment) === equipment)
    && (material === "All materials" || rate.materials.includes(material)));

  const rows = [];
  baseRates.forEach((rate) => {
    if (!collection && mode !== "door") {
      rows.push(makeDemoVariant(rate, "key", quantity, origin, ""));
      return;
    }
    if (mode === "all" || mode === "port") rows.push(makeDemoVariant(rate, "key", quantity, origin, ""));
    if (mode === "all" || mode === "door") rows.push(makeDemoVariant(rate, "door", quantity, origin, collection));
    if (collection && (mode === "all" || mode === "haulage")) {
      rows.push(makeDemoVariant(rate, "haulier", quantity, origin, collection));
    }
  });
  return rows.sort(compareViewRows);
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
  let routing = "CY/CY";
  let routingDetail = "CY/CY · port drop-off";
  let sourceFile = rate.sourceFile;
  let sourceTag = rate.sourceTag;
  let fineprint = "";

  if (mode === "door") {
    const uplift = quote.doorUplift[collection] || 0;
    freightLines = freightLines.map((line) => line.name === "Basic Ocean Freight"
      ? makeLineView({ ...line, name: "Basic Ocean Freight — door-to-quay", unit: line.unit + uplift }, quantity, fx)
      : line);
    inlandLines = [makeLineView({
      name: `Inland Haulage Export — ${collection}`,
      basis: "Container",
      ccy: "—",
      unit: 0,
      included: true,
    }, quantity, fx)];
    routing = "Door → quay";
    routingDetail = "Door-to-quay · carrier haulage included in freight, not itemised";
    sourceFile = "MAERSK_DOOR_299077037_JUL.xlsx";
    sourceTag = "DOOR";
    fineprint = `Inland haulage from ${collection} is included in the freight price — Maersk door rates do not itemise it.`;
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
    routing = "CY/CY + haulier";
    routingDetail = poa
      ? "CY/CY + merchant haulage · no tariff rate on this corridor"
      : `CY/CY + merchant haulage · £${formatNumber(tariff)}/ctn · separate haulier booking`;
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
  const sources = [{ tag: sourceTag, file: sourceFile }];
  if (mode === "haulier" && !poa) {
    sources.push({ tag: "HAUL·Q2", file: "UK Haulage — Export Haulage all UK POLs, Q2 2026 validity.xlsx" });
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
    sources,
    transit: extractTransit(rate.sailing),
    validity: rate.validity,
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
  const mode = elements.routingModeSelect.value || "all";
  const portRates = filterConnectedRates({ includeExpired: elements.showExpiredToggle.checked, kind: "port" })
    .map((rate) => makeConnectedRow(rate, quantity));
  const doorRates = filterConnectedRates({ includeExpired: elements.showExpiredToggle.checked, kind: "door" })
    .map((rate) => makeConnectedDoorRow(rate, quantity));
  const haulageRates = collection
    ? filterConnectedRates({ includeExpired: elements.showExpiredToggle.checked, kind: "port" })
      .filter((rate) => canAttachMerchantHaulage(rate))
      .map((rate) => makeConnectedHaulierRow(rate, quantity, collection))
    : [];

  const rows = [];
  if (mode === "port" || (mode === "all" && !collection)) rows.push(...portRates);
  if (mode === "all" || mode === "door") rows.push(...doorRates);
  if (mode === "all" || mode === "haulage") rows.push(...haulageRates);
  return rows.sort(compareViewRows);
}

function makeConnectedRow(rate, quantity) {
  const groups = connectedGroups(rate, quantity);
  const totalUsd = sumGroups(groups);
  const sourceFile = rate.source_file_name || rate.raw_sheet_name || "Approved rate";
  const tag = rate.contract_tag || rate.offer_reference || "KEY";
  const expired = isExpiredRate(rate);
  return {
    id: String(rate.offer_id || `${sourceFile}-${rate.raw_row_reference || "row"}`),
    type: "CONTRACT",
    routeLane: formatRouteLane(rateOrigin(rate), rateDestination(rate)),
    routing: formatRouting(rate),
    routingDetail: laneDetail(rate),
    sources: [{ tag, file: sourceFile }],
    transit: rate.transit_time_days ? `${rate.transit_time_days}d` : extractTransit(rate.routing_note || ""),
    validity: validityLabel(rate.valid_from, rate.valid_to, expired),
    sailing: rate.routing_note || "",
    freetime: extractFreetime(rate),
    groups,
    inlandUsd: groupTotal(groups, "inland"),
    originUsd: groupTotal(groups, "origin"),
    freightUsd: groupTotal(groups, "freight"),
    destinationUsd: groupTotal(groups, "destination"),
    totalUsd,
    poa: false,
    expired,
    zeroChargeCount: groups.reduce((sum, group) => sum + group.zeroLines.length, 0),
    fineprint: "",
    quantity,
    equipment: rate.equipment_type,
  };
}

function makeConnectedDoorRow(rate, quantity) {
  return {
    ...makeConnectedRow(rate, quantity),
    type: "CONTRACT",
    routeLane: formatRouteLane(
      firstPresent(rate.place_of_receipt, rate.origin),
      rate.pol,
      rateDestination(rate),
    ),
    routing: "Door → quay",
    routingDetail: laneDetail(rate),
  };
}

function makeConnectedHaulierRow(rate, quantity, collection) {
  const row = makeConnectedRow(rate, quantity);
  const port = merchantHaulagePort(rate);
  const tariff = deskState.haulageTariffs?.[collection]?.[port];
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
    routing: "CY/CY + haulier",
    routingDetail: poa
      ? `${collection} → ${port} → ${rateDestination(rate)} · no tariff rate for ${collection} → ${port}`
      : `${collection} → ${port} → ${rateDestination(rate)} · ${formatMoney(tariff, deskState.haulageCurrency)}/ctn · separate haulier booking`,
    sources: [...row.sources, { tag: "HAUL", file: "UK Inland Haulage" }],
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
    subtotalUsd: allLines.reduce((sum, line) => sum + line.usdExact, 0),
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
        <span class="${isBest ? "rank best-rank" : "rank"}">${index + 1}</span>
        <span class="routing-cell" title="${escapeAttr(routingTitle)}">
          <strong class="routing-lane">${escapeHtml(row.routeLane || row.routing)}</strong>
          <small class="routing-type">${escapeHtml(row.routing)}</small>
        </span>
        <span class="source-tags">${row.sources.map((source) => `<span title="${escapeAttr(source.file)}">${escapeHtml(source.tag)}</span>`).join("")}</span>
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
  if (!row.groups.some((group) => group.key === "inland") || row.groups.find((group) => group.key === "inland")?.lines.some((line) => line.included)) {
    return '<span class="muted-mono">—</span>';
  }
  return `<span class="component-value">${escapeHtml(formatUsd(row.inlandUsd))}</span>`;
}

function renderBreakdown(row) {
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

function compareViewRows(left, right) {
  if (left.expired !== right.expired) return left.expired ? 1 : -1;
  if (left.poa !== right.poa) return left.poa ? 1 : -1;
  if (left.type !== right.type) return left.type.localeCompare(right.type);
  if (left.totalUsd !== right.totalUsd) return left.totalUsd - right.totalUsd;
  return left.routing.localeCompare(right.routing);
}

function sumGroups(groups) {
  return groups.reduce((sum, group) => sum + group.subtotalUsd, 0);
}

function groupTotal(groups, key) {
  return groups.find((group) => group.key === key)?.subtotalUsd || 0;
}

function formatRouting(rate) {
  const mode = normalized(rate.service_mode);
  if (isDoorServiceMode(mode)) return "Door → quay";
  return "CY/CY";
}

function laneDetail(rate) {
  if (isDoorRate(rate)) {
    const receipt = firstPresent(rate.place_of_receipt, rate.origin);
    const delivery = firstPresent(rate.final_destination, rate.pod);
    return [receipt, delivery].filter(Boolean).join(" → ") || formatRouting(rate);
  }
  const origin = firstPresent(rate.pol, rate.place_of_receipt, rate.origin);
  const destination = firstPresent(rate.final_destination, rate.pod);
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
  return [rate.contract_tag, rate.carrier_key, rate.carrier_label, rate.carrier_name, rate.document_type]
    .filter(Boolean)
    .some((value) => normalized(value).includes("haulage") || normalized(value).includes("inland_export"));
}

function rateOrigin(rate) {
  return firstPresent(rate.pol, rate.place_of_receipt, rate.origin);
}

function rateDestination(rate) {
  return firstPresent(rate.final_destination, rate.pod);
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
  const target = normalized(value);
  return Object.values(deskState.haulageTariffs || {}).some((portMap) =>
    Object.keys(portMap || {}).some((port) => normalized(port) === target));
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
  elements.routingModeSelect.value = "all";
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
  return {
    all: "All approved quotes",
    port: "All port drop-off quotes",
    door: "All carrier door quotes",
    haulage: "All merchant-haulage quotes",
  }[elements.routingModeSelect.value || "all"] || "All approved quotes";
}

function countHiddenExpiredMatches() {
  return filterConnectedRates({ includeExpired: true, kind: "all" }).filter((rate) => isExpiredRate(rate)).length;
}

function hasExpiredMatches() {
  return countHiddenExpiredMatches() > 0;
}

function matchingConnectedRates({ includeExpired }) {
  return filterConnectedRates({ includeExpired, kind: "port" });
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
      if (kind === "port" && isDoorRate(rate)) return false;
      if (kind === "door" && !isDoorRate(rate)) return false;
      if (!includeExpired && isExpiredRate(rate)) return false;
      if (!matchesFilter(rateDestination(rate), destination)) return false;
      if (equipment && canonicalEquipment(rate.equipment_type) !== equipment) return false;
      if (!(material === "All materials" || (rate.materials || []).some((item) => sameValue(item, material)))) return false;
      if (kind === "door") {
        if (collection && !matchesFilter(firstPresent(rate.place_of_receipt, rate.origin), collection)) return false;
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
