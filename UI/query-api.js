const MOCK_CONFIG = {
  latencyMs: 800,
  retrievedAt: "2026-07-28T13:45:00+01:00",
  fxRatesToUsd: {
    USD: 1,
    GBP: 1.275,
    THB: 0.030215,
  },
};

const EQUIPMENT_OPTIONS = [
  { canonicalCode: "20DRY", isoCode: "22G1", label: "20' Dry Standard" },
  { canonicalCode: "40DRY", isoCode: "42G1", label: "40' Dry Standard" },
  { canonicalCode: "40HDRY", isoCode: "45G1", label: "40' High Cube Dry" },
  { canonicalCode: "20REF", isoCode: "22R1", label: "20' Reefer" },
  { canonicalCode: "40HREF", isoCode: "45R1", label: "40' High Cube Reefer" },
];

const KNOWN_LOCATIONS = [
  { displayName: "Alcester, GB", cityName: "Alcester", countryCode: "GB", locationType: "INLAND" },
  { displayName: "Felixstowe, GB", cityName: "Felixstowe", countryCode: "GB", unlocode: "GBFXT", locationType: "PORT" },
  { displayName: "London Gateway, GB", cityName: "London Gateway", countryCode: "GB", unlocode: "GBLGP", locationType: "PORT" },
  { displayName: "Bangkok, TH", cityName: "Bangkok", countryCode: "TH", unlocode: "THBKK", locationType: "INLAND" },
  { displayName: "Laem Chabang, TH", cityName: "Laem Chabang", countryCode: "TH", unlocode: "THLCH", locationType: "PORT" },
  { displayName: "Ho Chi Minh City, VN", cityName: "Ho Chi Minh City", countryCode: "VN", unlocode: "VNSGN", locationType: "INLAND" },
  { displayName: "Rotterdam, NL", cityName: "Rotterdam", countryCode: "NL", unlocode: "NLRTM", locationType: "PORT" },
];

const BASE_CHARGES = [
  { id: "origin-haulage", section: "ORIGIN", chargeName: "Inland haulage - origin", basis: "PER_CONTAINER", currency: "GBP", unitPrice: 420, usdUnitEquivalent: 535.5 },
  { id: "origin-doc", section: "ORIGIN", chargeName: "Origin documentation", basis: "PER_DOCUMENT", currency: "GBP", unitPrice: 55, usdUnitEquivalent: 70.13 },
  { id: "basic-ocean-freight", section: "FREIGHT", chargeCode: "BAS", chargeName: "Basic Ocean Freight", basis: "PER_CONTAINER", currency: "USD", unitPrice: 1650, usdUnitEquivalent: 1650 },
  { id: "bunker-adjustment", section: "FREIGHT", chargeName: "Bunker adjustment", basis: "PER_CONTAINER", currency: "USD", unitPrice: 310, usdUnitEquivalent: 310 },
  { id: "emissions-surcharge", section: "FREIGHT", chargeName: "Emissions surcharge", basis: "PER_CONTAINER", currency: "USD", unitPrice: 145, usdUnitEquivalent: 145 },
  { id: "destination-doc", section: "DESTINATION", chargeName: "Documentation fee - destination", basis: "PER_DOCUMENT", currency: "THB", unitPrice: 1500, usdUnitEquivalent: 45.3 },
  { id: "container-protect", section: "DESTINATION", chargeName: "Container Protect Essential", basis: "PER_CONTAINER", currency: "THB", unitPrice: 850, usdUnitEquivalent: 25.67, isOptional: true },
  { id: "destination-haulage", section: "DESTINATION", chargeName: "Inland haulage - destination", basis: "PER_CONTAINER", currency: "THB", unitPrice: 3120, usdUnitEquivalent: 94.37 },
];

class CarrierOffersAdapter {
  async searchOffers() {
    throw new Error("CarrierOffersAdapter.searchOffers must be implemented by a concrete adapter.");
  }
}

class MockMaerskOffersAdapter extends CarrierOffersAdapter {
  async searchOffers(query) {
    await new Promise((resolve) => setTimeout(resolve, MOCK_CONFIG.latencyMs));
    return buildMockMaerskOffers(query);
  }
}

class MaerskOffersAdapter extends CarrierOffersAdapter {
  async searchOffers() {
    throw new Error("Real Maersk adapter is pending the customer's enabled OpenAPI specification.");
  }
}

const queryState = {
  adapter: new MockMaerskOffersAdapter(),
  offers: [],
  expandedOfferId: null,
  lastQuery: null,
  loading: false,
};

const form = document.getElementById("carrierQueryForm");
const queryAlert = document.getElementById("queryAlert");
const originInput = document.getElementById("originInput");
const destinationInput = document.getElementById("destinationInput");
const departureInput = document.getElementById("departureInput");
const equipmentInput = document.getElementById("equipmentInput");
const quantityInput = document.getElementById("quantityInput");
const weightInput = document.getElementById("weightInput");
const commodityInput = document.getElementById("commodityInput");
const referenceInput = document.getElementById("referenceInput");
const currencyInput = document.getElementById("currencyInput");
const filteredInput = document.getElementById("filteredInput");
const queryResults = document.getElementById("queryResults");
const searchButton = document.getElementById("searchButton");
const locationOptions = document.getElementById("locationOptions");

bootQueryApi();

function bootQueryApi() {
  populateEquipment();
  populateLocations();
  setInitialDates();
  originInput.value = "Alcester, GB";
  destinationInput.value = "Bangkok, TH";
  form.addEventListener("submit", handleSubmit);
}

async function handleSubmit(event) {
  event.preventDefault();
  const query = buildQueryFromForm();
  const validationMessage = validateQuery(query);
  if (validationMessage) {
    showAlert(validationMessage);
    return;
  }

  hideAlert();
  queryState.loading = true;
  queryState.lastQuery = query;
  queryState.expandedOfferId = null;
  renderLoading();
  setBusy(true);

  try {
    queryState.offers = await queryState.adapter.searchOffers(query);
    renderResults();
  } catch (error) {
    renderError(error.message || "Carrier API unavailable.");
  } finally {
    queryState.loading = false;
    setBusy(false);
  }
}

function buildQueryFromForm() {
  const equipment = EQUIPMENT_OPTIONS.find((option) => option.canonicalCode === equipmentInput.value);
  return {
    carrier: "MAERSK",
    brandScac: "MAEU",
    origin: resolveLocation(originInput.value),
    destination: resolveLocation(destinationInput.value),
    originServicePoint: selectedRadioValue("originServicePoint"),
    destinationServicePoint: selectedRadioValue("destinationServicePoint"),
    earliestDepartureDate: departureInput.value,
    equipment,
    quantity: clampInteger(quantityInput.value, 1, 999),
    weightPerContainerTonnes: clampDecimal(weightInput.value, 0.1, 30),
    commodityDescription: commodityInput.value.trim() || undefined,
    customerReference: referenceInput.value.trim() || undefined,
    displayCurrency: currencyInput.value,
    includeFilteredOffers: filteredInput.checked,
  };
}

function validateQuery(query) {
  if (!query.origin.displayName || !query.origin.countryCode) return "Enter an origin with a country code, for example Alcester, GB.";
  if (!query.destination.displayName || !query.destination.countryCode) return "Enter a destination with a country code, for example Bangkok, TH.";
  if (!query.earliestDepartureDate) return "Choose an earliest departure date.";
  if (query.earliestDepartureDate < todayIso()) return "Earliest departure date cannot be in the past.";
  if (!query.equipment) return "Choose an equipment type.";
  if (query.quantity < 1) return "Quantity must be at least 1.";
  if (query.weightPerContainerTonnes <= 0) return "Weight per container must be greater than 0.";
  return "";
}

function renderLoading() {
  queryResults.className = "query-results-stack";
  queryResults.innerHTML = `
    <div class="query-loading">
      <strong>Searching Maersk offers...</strong>
      <span>Checking routes, schedules and available pricing.</span>
    </div>
    <div class="offer-skeleton"></div>
  `;
}

function renderResults() {
  if (!queryState.offers.length) {
    queryResults.className = "query-empty-state";
    queryResults.innerHTML = `
      <strong>No offers found for this search.</strong>
      <span>Try another departure date, service scope or equipment type.</span>
      <button class="cancel-button" type="button" id="editSearchButton">Edit search</button>
    `;
    document.getElementById("editSearchButton").addEventListener("click", () => originInput.focus());
    return;
  }

  const count = queryState.offers.length;
  const query = queryState.lastQuery;
  queryResults.className = "query-results-stack";
  queryResults.innerHTML = `
    <div class="results-heading api-results-heading">
      <strong>${count} live offer${count === 1 ? "" : "s"} found</strong>
      <span>${escapeHtml(query.origin.displayName)} -> ${escapeHtml(query.destination.displayName)} · ${query.quantity} x ${escapeHtml(query.equipment.label)} · ${formatWeight(query.weightPerContainerTonnes)} t</span>
    </div>
    ${queryState.offers.map(renderOffer).join("")}
  `;

  queryResults.querySelectorAll("button[data-offer-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const offerId = button.dataset.offerId;
      queryState.expandedOfferId = queryState.expandedOfferId === offerId ? null : offerId;
      renderResults();
    });
  });
}

function renderOffer(offer) {
  const expanded = queryState.expandedOfferId === offer.id;
  return `
    <article class="api-offer-card">
      <div class="api-offer-topline">
        <div>
          <strong>${escapeHtml(offer.productName)}</strong>
          <span>${escapeHtml(routeLabel(offer))}</span>
        </div>
        <div class="api-badges">
          <span class="demo-badge">Demo API response</span>
          <span class="warn-badge">Illustrative pricing</span>
          <span class="warn-badge">Not bookable</span>
        </div>
      </div>
      <div class="api-offer-meta">
        <span>${escapeHtml(serviceLabel(offer.route.originServicePoint, offer.route.destinationServicePoint))}</span>
        <span>${offer.equipment.quantity} x ${escapeHtml(offer.equipment.label)}</span>
        <span>${formatWeight(offer.equipment.weightPerContainerTonnes)} t</span>
      </div>
      <div class="api-offer-schedule">
        <span><b>ETD</b> ${escapeHtml(formatDate(offer.schedule.departureAt))}</span>
        <span><b>ETA</b> ${escapeHtml(formatDate(offer.schedule.arrivalAt))}</span>
        <span><b>Transit</b> ${offer.schedule.transitDays} days</span>
      </div>
      <div class="api-offer-footer">
        <span>${offer.charges.length} charge lines</span>
        <strong>${escapeHtml(offer.total.currency)} ${escapeHtml(formatMoney(offer.total.amount))}</strong>
        <button class="cancel-button" type="button" data-offer-id="${escapeAttr(offer.id)}" aria-expanded="${expanded}">
          ${expanded ? "Hide details" : "View details"}
        </button>
      </div>
      ${expanded ? renderOfferDetail(offer) : ""}
    </article>
  `;
}

function renderOfferDetail(offer) {
  const groups = buildChargeGroups(offer);
  return `
    <div class="rate-breakdown api-breakdown">
      <div class="breakdown-meta">
        <span class="lane-chip">${escapeHtml(routeLabel(offer))}</span>
        <span class="source-detail"><span>Source</span><span class="mono">MAERSK OFFERS API · DEMO</span></span>
        <span class="pill">Dynamic Spot offer</span>
      </div>
      <div class="breakdown-facts">
        ${renderBreakdownFact("Origin", offer.route.origin.displayName)}
        ${renderBreakdownFact("POL", offer.route.portOfLoading?.displayName || offer.route.origin.displayName)}
        ${renderBreakdownFact("POD", offer.route.portOfDischarge?.displayName || offer.route.destination.displayName)}
        ${renderBreakdownFact("Delivery", offer.route.destination.displayName)}
        ${renderBreakdownFact("Equipment", `${offer.equipment.canonicalCode} x ${offer.equipment.quantity}`)}
        ${renderBreakdownFact("Departure", formatDate(offer.schedule.departureAt))}
        ${renderBreakdownFact("Service", serviceLabel(offer.route.originServicePoint, offer.route.destinationServicePoint))}
        ${renderBreakdownFact("Offer ID", offer.offerId || "-")}
      </div>
      <div class="breakdown-panel">
        ${groups.map(renderGroup).join("")}
        <div class="breakdown-total">
          <span>Total for ${offer.equipment.quantity} x ${escapeHtml(offer.equipment.canonicalCode)}</span>
          <span>${escapeHtml(offer.total.currency)} ${escapeHtml(formatMoney(offer.total.amount))}</span>
        </div>
      </div>
      <div class="fine-print">${escapeHtml(buildOfferFinePrint(offer))}</div>
      <div class="zero-note">Price and space are subject to carrier confirmation at booking.</div>
    </div>
  `;
}

function buildMockMaerskOffers(query) {
  const charges = BASE_CHARGES.map((charge) => expandCharge(charge, query.quantity));
  const subtotals = {
    originUsd: subtotalFor(charges, "ORIGIN"),
    freightUsd: subtotalFor(charges, "FREIGHT"),
    destinationUsd: subtotalFor(charges, "DESTINATION"),
  };
  const totalUsd = roundMoney(subtotals.originUsd + subtotals.freightUsd + subtotals.destinationUsd);
  const portOfLoading = query.originServicePoint === "PORT" ? query.origin : KNOWN_LOCATIONS.find((location) => location.unlocode === "GBFXT");
  const portOfDischarge = query.destinationServicePoint === "PORT" ? query.destination : KNOWN_LOCATIONS.find((location) => location.unlocode === "THLCH");

  return [{
    id: "mock-maersk-offer-1",
    carrier: { code: "MAEU", name: "Maersk" },
    productName: "Maersk Spot",
    sourceType: "MOCK_API",
    isDemo: true,
    offerId: "O_DEMO_MAEU_50823359",
    retrievedAt: MOCK_CONFIG.retrievedAt,
    rateType: "SPOT",
    rateStatus: "DYNAMIC",
    route: {
      origin: query.originServicePoint === "PORT" ? portOfLoading : query.origin,
      portOfLoading,
      portOfDischarge,
      destination: query.destinationServicePoint === "PORT" ? portOfDischarge : query.destination,
      originServicePoint: query.originServicePoint,
      destinationServicePoint: query.destinationServicePoint,
    },
    equipment: {
      canonicalCode: query.equipment.canonicalCode,
      isoCode: query.equipment.isoCode,
      label: query.equipment.label,
      quantity: query.quantity,
      weightPerContainerTonnes: query.weightPerContainerTonnes,
    },
    schedule: {
      departureAt: buildDepartureDate(query.earliestDepartureDate),
      arrivalAt: buildArrivalDate(query.earliestDepartureDate, 54),
      transitDays: 54,
      vesselName: "Demo Vessel",
      voyageNumber: "626E",
      serviceCode: "DEMO1",
    },
    charges,
    subtotals,
    total: {
      amount: totalUsd,
      currency: "USD",
      usdEquivalent: totalUsd,
    },
    conditions: {
      originFreeDays: 5,
      destinationFreeDays: 7,
      notes: [
        "Illustrative demo only - not a bookable Maersk quotation.",
        "Final pricing and space are subject to carrier confirmation.",
      ],
    },
  }];
}

function expandCharge(charge, containerQuantity) {
  const quantity = charge.basis === "PER_CONTAINER" ? containerQuantity : 1;
  const amount = roundMoney(charge.unitPrice * quantity);
  const usdEquivalent = roundMoney(
    charge.usdUnitEquivalent == null
      ? amount * fxRate(charge.currency)
      : charge.usdUnitEquivalent * quantity
  );
  return {
    ...charge,
    quantity,
    amount,
    usdEquivalent,
  };
}

function buildChargeGroups(offer) {
  return [
    { key: "ORIGIN", label: "Origin charges", subLabel: "Origin subtotal (USD)" },
    { key: "FREIGHT", label: "Freight charges", subLabel: "Freight subtotal (USD)" },
    { key: "DESTINATION", label: "Destination charges", subLabel: "Destination subtotal (USD)" },
  ].map((group) => {
    const lines = offer.charges.filter((charge) => charge.section === group.key);
    const subtotal = lines.reduce((sum, line) => sum + (line.usdEquivalent || 0), 0);
    return {
      ...group,
      lines,
      subtotalUsd: `USD ${formatMoney(subtotal)}`,
    };
  });
}

function renderGroup(group) {
  return `
    <div class="breakdown-group-header">
      <span>${escapeHtml(group.label)}</span>
      <span>Basis</span>
      <span style="text-align:right">Qty</span>
      <span>Ccy</span>
      <span style="text-align:right">Unit price</span>
      <span style="text-align:right" title="Converted to USD where the source charge uses another currency">USD equiv.</span>
    </div>
    ${group.lines.map(renderLine).join("")}
    <div class="breakdown-subtotal">
      <span>${escapeHtml(group.subLabel)}</span>
      <span>${escapeHtml(group.subtotalUsd)}</span>
    </div>
  `;
}

function renderLine(line) {
  return `
    <div class="breakdown-row">
      <span>${escapeHtml(line.chargeName)}</span>
      <span class="dim">${escapeHtml(formatBasis(line.basis))}</span>
      <span class="qty">${escapeHtml(String(line.quantity))}</span>
      <span class="ccy">${escapeHtml(line.currency)}</span>
      <span class="money">${escapeHtml(formatMoney(line.unitPrice))}</span>
      <span class="money">${escapeHtml(formatMoney(line.usdEquivalent || 0))}</span>
    </div>
  `;
}

function renderBreakdownFact(label, value) {
  return `
    <div class="breakdown-fact">
      <span class="breakdown-fact-label">${escapeHtml(label)}</span>
      <span class="breakdown-fact-value">${escapeHtml(value || "-")}</span>
    </div>
  `;
}

function populateEquipment() {
  equipmentInput.innerHTML = EQUIPMENT_OPTIONS.map((option) => (
    `<option value="${escapeAttr(option.canonicalCode)}">${escapeHtml(option.label)}</option>`
  )).join("");
  equipmentInput.value = "40HDRY";
}

function populateLocations() {
  locationOptions.innerHTML = KNOWN_LOCATIONS.map((location) => (
    `<option value="${escapeAttr(location.displayName)}"></option>`
  )).join("");
}

function setInitialDates() {
  const minimum = todayIso();
  const demoDeparture = "2026-08-12";
  departureInput.min = minimum;
  departureInput.value = demoDeparture >= minimum ? demoDeparture : minimum;
}

function resolveLocation(value) {
  const displayName = value.trim();
  const known = KNOWN_LOCATIONS.find((location) => normalized(location.displayName) === normalized(displayName));
  if (known) return { ...known };

  const match = displayName.match(/^(.*?),\s*([A-Za-z]{2})$/);
  return {
    displayName,
    cityName: match ? match[1].trim() : undefined,
    countryCode: match ? match[2].toUpperCase() : "",
    locationType: "CITY",
  };
}

function selectedRadioValue(name) {
  return form.querySelector(`input[name="${name}"]:checked`)?.value || "";
}

function serviceLabel(originServicePoint, destinationServicePoint) {
  const labels = { DOOR: "Door", PORT: "Port" };
  return `${labels[originServicePoint] || originServicePoint}-to-${(labels[destinationServicePoint] || destinationServicePoint).toLowerCase()}`;
}

function routeLabel(offer) {
  return `${offer.route.origin.displayName} -> ${offer.route.destination.displayName}`;
}

function buildOfferFinePrint(offer) {
  return [
    `Transit ${offer.schedule.transitDays} days`,
    `Offer ID ${offer.offerId}`,
    `Retrieved ${formatDateTime(offer.retrievedAt)}`,
    "Dynamic Spot offer",
    ...(offer.conditions?.notes || []),
  ].join(" · ");
}

function buildDepartureDate(earliestDepartureDate) {
  const parsed = new Date(`${earliestDepartureDate}T10:00:00Z`);
  return parsed.toISOString();
}

function buildArrivalDate(earliestDepartureDate, transitDays) {
  const parsed = new Date(`${earliestDepartureDate}T08:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + transitDays);
  return parsed.toISOString();
}

function subtotalFor(charges, section) {
  return roundMoney(charges
    .filter((charge) => charge.section === section)
    .reduce((sum, charge) => sum + (charge.usdEquivalent || 0), 0));
}

function formatBasis(value) {
  const labels = {
    PER_CONTAINER: "Per container",
    PER_SHIPMENT: "Per shipment",
    PER_DOCUMENT: "Per document",
    OTHER: "Other",
  };
  return labels[value] || value || "Other";
}

function formatDate(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value || "-";
  return parsed.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function formatDateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value || "-";
  return parsed.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function formatMoney(value) {
  return roundMoney(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatWeight(value) {
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 1 });
}

function fxRate(currency) {
  return MOCK_CONFIG.fxRatesToUsd[(currency || "USD").toUpperCase()] || 1;
}

function todayIso() {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}

function clampInteger(value, min, max) {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return min;
  return Math.min(max, Math.max(min, parsed));
}

function clampDecimal(value, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return min;
  return Math.min(max, Math.max(min, parsed));
}

function roundMoney(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

function normalized(value) {
  return String(value || "").trim().toLowerCase();
}

function setBusy(isBusy) {
  searchButton.disabled = isBusy;
  searchButton.textContent = isBusy ? "Searching..." : "Search Maersk offers";
}

function showAlert(message) {
  queryAlert.hidden = false;
  queryAlert.textContent = message;
}

function hideAlert() {
  queryAlert.hidden = true;
}

function renderError(message) {
  queryResults.className = "query-empty-state";
  queryResults.innerHTML = `
    <strong>Carrier API unavailable.</strong>
    <span>${escapeHtml(message)}</span>
  `;
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
