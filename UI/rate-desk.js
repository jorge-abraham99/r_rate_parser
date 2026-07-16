const deskState = {
  rates: [],
  filters: {
    origins: [],
    destinations: [],
    equipment_types: [],
    carriers: [],
    materials: [],
    door_pickups: [],
  },
  expandedOfferId: null,
  loaded: false,
};

const originSelect = document.getElementById("originSelect");
const destinationSelect = document.getElementById("destinationSelect");
const equipmentSelect = document.getElementById("equipmentSelect");
const materialSelect = document.getElementById("materialSelect");
const showExpiredToggle = document.getElementById("showExpiredToggle");
const doorSelect = document.getElementById("doorSelect");
const rateRows = document.getElementById("rateRows");
const laneTitle = document.getElementById("laneTitle");
const laneSummary = document.getElementById("laneSummary");
const refreshText = document.getElementById("refreshText");
const coverageGap = document.getElementById("coverageGap");
const doorChip = document.getElementById("doorChip");
const deskAlert = document.getElementById("deskAlert");

[originSelect, destinationSelect, equipmentSelect, materialSelect].forEach((select) => {
  select.addEventListener("change", () => {
    deskState.expandedOfferId = null;
    renderDesk();
  });
});
doorSelect.addEventListener("change", renderDesk);
showExpiredToggle.addEventListener("change", () => {
  deskState.expandedOfferId = null;
  renderDesk();
});

loadRateDesk();

async function loadRateDesk() {
  try {
    const response = await fetch("/api/rate-desk?limit=5000");
    if (!response.ok) throw new Error("The approved-rate service did not respond.");
    const payload = await response.json();
    deskState.rates = Array.isArray(payload.rates) ? payload.rates : [];
    deskState.filters = { ...deskState.filters, ...(payload.filters || {}) };
    deskState.loaded = true;
    populateFilters();
    renderRefreshText(payload.last_refreshed);
    renderDesk();
  } catch (error) {
    deskState.loaded = true;
    showDeskAlert(`Could not load approved rates: ${error.message}`, true);
    refreshText.textContent = "Rate service unavailable";
    laneTitle.textContent = "Approved rate lookup";
    laneSummary.textContent = "could not load rates";
    rateRows.innerHTML = '<div class="rate-empty">The Rate Desk could not connect to the local API.</div>';
  }
}

function populateFilters() {
  const defaultRate = deskState.rates.filter(isCurrentlyValid).sort(compareRates)[0];
  populateSelect(
    originSelect,
    deskState.filters.origins,
    "No approved origins",
    defaultRate ? rateOrigin(defaultRate) : "Felixstowe",
    displayPlace,
    "Any origin",
  );
  populateSelect(
    destinationSelect,
    deskState.filters.destinations,
    "No approved destinations",
    defaultRate ? rateDestination(defaultRate) : "Jakarta",
    displayPlace,
    "Any destination",
  );
  populateEquipmentSelect(
    equipmentSelect,
    deskState.filters.equipment_types,
    defaultRate?.equipment_type || "40HC",
  );

  const doorPickups = deskState.filters.door_pickups || [];
  if (!doorPickups.length) {
    doorSelect.innerHTML = '<option value="">No haulage rates imported</option>';
    doorSelect.disabled = true;
    return;
  }
  doorSelect.innerHTML = [
    '<option value="">Port drop-off (none)</option>',
    ...doorPickups.map((item) => {
      const name = item.name || item.location || "Unknown";
      const amount = item.amount_gbp ?? item.amount;
      const label = amount == null ? name : `${name} · £${formatNumber(amount)}`;
      return `<option value="${escapeAttr(name)}">${escapeHtml(label)}</option>`;
    }),
  ].join("");
  doorSelect.disabled = false;
}

function populateSelect(select, values, emptyLabel, preferred, formatter = displayPlace, anyLabel = null) {
  const seen = new Set();
  const uniqueValues = (values || []).filter((value) => {
    if (!value) return false;
    const key = normalized(value);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  if (!uniqueValues.length) {
    select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>`;
    select.disabled = true;
    return;
  }
  select.innerHTML = [
    anyLabel ? `<option value="">${escapeHtml(anyLabel)}</option>` : "",
    ...uniqueValues.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(formatter(value))}</option>`),
  ].join("");
  const preferredValue = uniqueValues.find((value) => normalized(value).includes(normalized(preferred)));
  select.value = preferredValue || uniqueValues[0];
  select.disabled = false;
}

function populateEquipmentSelect(select, values, preferred) {
  const equipmentTypes = [...new Set((values || []).filter(Boolean).map(canonicalEquipment))];
  if (!equipmentTypes.length) {
    select.innerHTML = '<option value="">No container sizes</option>';
    select.disabled = true;
    return;
  }
  select.innerHTML = equipmentTypes
    .map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(formatEquipment(value))}</option>`)
    .join("");
  const preferredEquipment = canonicalEquipment(preferred);
  select.value = equipmentTypes.includes(preferredEquipment) ? preferredEquipment : equipmentTypes[0];
  select.disabled = false;
}

function renderDesk() {
  if (!deskState.loaded) return;
  hideDeskAlert();
  const selectedOrigin = originSelect.value;
  const selectedDestination = destinationSelect.value;
  const selectedEquipment = equipmentSelect.value;
  const selectedMaterial = materialSelect.value;
  const selectedDoor = doorSelect.value;
  const showExpired = showExpiredToggle.checked;

  if (!deskState.rates.length) {
    renderNoApprovedRates();
    return;
  }

  const laneRates = deskState.rates.filter((rate) => (
    (!selectedOrigin || sameValue(rateOrigin(rate), selectedOrigin))
    && (!selectedDestination || sameValue(rateDestination(rate), selectedDestination))
    && sameEquipment(rate.equipment_type, selectedEquipment)
    && (!selectedMaterial || (rate.materials || []).some((material) => sameValue(material, selectedMaterial)))
  ));
  const visibleRates = laneRates
    .filter((rate) => isCurrentlyValid(rate) || (showExpired && isExpired(rate)))
    .sort(compareVisibleRates);

  laneTitle.textContent = formatSearchTitle(selectedOrigin, selectedDestination);
  renderDoorChip(selectedDoor);

  if (!visibleRates.length) {
    laneSummary.textContent = "no current approved rates on this lane";
    const message = laneRates.some(isExpired) && !showExpired
      ? "This lane only has expired published rates. Turn on Show expired rates to view them."
      : laneRates.length
        ? "Published rates exist for this lane, but none are currently within their validity dates."
        : "No parsed rates match this search and container size.";
    rateRows.innerHTML = `<div class="rate-empty">${escapeHtml(message)}</div>`;
    hideCoverageGap();
    return;
  }

  const best = visibleRates.find(isCurrentlyValid) || null;
  const expiredCount = visibleRates.filter(isExpired).length;
  laneSummary.textContent = best
    ? `${visibleRates.length} parsed rate${visibleRates.length === 1 ? "" : "s"} · best ${formatMoney(best.all_in_amount, best.base_currency)} ${carrierName(best)}${expiredCount ? ` · ${expiredCount} expired` : ""}`
    : `${visibleRates.length} expired rate${visibleRates.length === 1 ? "" : "s"} · shown for reference only`;
  const bestOfferId = best ? String(best.offer_id || "") : null;
  rateRows.innerHTML = visibleRates.map((rate, index) => renderRate(rate, index, bestOfferId)).join("");
  rateRows.querySelectorAll("button[data-offer-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const offerId = button.dataset.offerId;
      deskState.expandedOfferId = deskState.expandedOfferId === offerId ? null : offerId;
      renderDesk();
    });
  });
  renderCoverageGap(visibleRates, !selectedOrigin || !selectedDestination);
}

function renderNoApprovedRates() {
  laneTitle.textContent = "Approved rate lookup";
  laneSummary.textContent = "no approved rates available";
  rateRows.innerHTML = `
    <div class="rate-empty">
      No rates have been published yet. Import and publish a carrier file in Import to populate this desk.
    </div>
  `;
  hideCoverageGap();
  doorChip.hidden = true;
}

function renderRate(rate, index, bestOfferId) {
  const offerId = String(rate.offer_id || `${index}-${carrierName(rate)}`);
  const isBest = Boolean(bestOfferId && offerId === bestOfferId && isCurrentlyValid(rate));
  const expanded = deskState.expandedOfferId === offerId;
  const components = summarizeComponents(rate);
  const source = rate.source_file_name || rate.raw_sheet_name || "Approved rate";
  const tag = contractTag(rate);
  const validity = validityPresentation(rate.valid_to);
  const breakdown = renderBreakdown(rate);

  return `
    <article class="rate-record">
      <button
        class="rate-grid rate-row${isBest ? " best" : ""}${validity.expired ? " expired" : ""}"
        type="button"
        data-offer-id="${escapeAttr(offerId)}"
        aria-expanded="${expanded}"
        aria-controls="breakdown-${escapeAttr(offerId)}"
      >
        <span class="rank">${index + 1}</span>
        <span class="carrier-cell">
          <span class="carrier-name">${escapeHtml(carrierName(rate))}</span>
          ${isBest ? '<span class="best-badge">Best rate</span>' : ""}
        </span>
        <span class="lane-cell" title="${escapeAttr(formatRateLane(rate))}">${escapeHtml(formatRateLane(rate))}</span>
        <span class="source-cell" title="${escapeAttr(source)}">
          ${tag ? `<span class="mono-chip">${escapeHtml(tag)}</span>` : ""}
          <span class="source-name">${escapeHtml(source)}</span>
        </span>
        <span class="component-value">${formatComponent(components.base, true)}</span>
        <span class="component-value">${formatComponent(components.haulage)}</span>
        <span class="component-value">${formatComponent(components.thc)}</span>
        <span class="component-value">${formatComponent(components.docs)}</span>
        <span class="component-value">${formatComponent(components.surcharges)}</span>
        <span class="all-in-value">${escapeHtml(formatMoney(rate.all_in_amount, rate.base_currency))}</span>
        <span><span class="validity-chip${validity.warning ? " warning" : ""}${validity.expired ? " expired" : ""}">${escapeHtml(validity.label)}</span></span>
      </button>
      ${expanded ? `
        <div id="breakdown-${escapeAttr(offerId)}" class="rate-breakdown">
          <div class="breakdown-title">Breakdown · per container (from approved source)</div>
          <div class="breakdown-items">${breakdown}</div>
          <p class="fine-print">${escapeHtml(finePrint(rate))}</p>
        </div>
      ` : ""}
    </article>
  `;
}

function summarizeComponents(rate) {
  const charges = Array.isArray(rate.charges) ? rate.charges : [];
  const targetCurrency = normalized(rate.base_currency);
  const sameCurrency = charges.filter((charge) => (
    !charge.currency || !targetCurrency || normalized(charge.currency) === targetCurrency
  ));
  const buckets = { base: [], haulage: [], thc: [], docs: [], surcharges: [] };

  sameCurrency.forEach((charge) => {
    const name = normalized(charge.charge_name);
    const type = normalized(charge.charge_type);
    if (type === "base" || name.includes("ocean freight")) buckets.base.push(charge);
    else if (type === "haulage" || name.includes("haul")) buckets.haulage.push(charge);
    else if (name === "thc" || name.includes("terminal handling")) buckets.thc.push(charge);
    else if (name.includes("doc")) buckets.docs.push(charge);
    else buckets.surcharges.push(charge);
  });

  const baseFromCharges = sumCharges(buckets.base);
  return {
    base: baseFromCharges ?? (rate.all_in_flag === true ? null : toNumber(rate.base_amount)),
    haulage: sumCharges(buckets.haulage),
    thc: sumCharges(buckets.thc),
    docs: sumCharges(buckets.docs),
    surcharges: sumCharges(buckets.surcharges),
  };
}

function sumCharges(charges) {
  const amounts = charges.map((charge) => toNumber(charge.amount)).filter((value) => value != null);
  if (!amounts.length) return null;
  return amounts.reduce((total, value) => total + value, 0);
}

function renderBreakdown(rate) {
  const charges = Array.isArray(rate.charges) ? rate.charges : [];
  if (!charges.length) {
    return `<span class="breakdown-item">All-in as quoted <strong>${escapeHtml(formatMoney(rate.all_in_amount, rate.base_currency))}</strong></span>`;
  }
  return charges.map((charge) => {
    const amount = formatMoney(charge.amount, charge.currency || rate.base_currency);
    const basis = charge.basis ? ` · ${charge.basis}` : "";
    return `<span class="breakdown-item">${escapeHtml(charge.charge_name || "Charge")} <strong>${escapeHtml(amount)}</strong>${escapeHtml(basis)}</span>`;
  }).join("");
}

function finePrint(rate) {
  const parts = [];
  if (rate.transit_time_days) parts.push(`Transit ${rate.transit_time_days} days`);
  if (rate.routing_note) parts.push(rate.routing_note);
  if (rate.notes_summary) parts.push(rate.notes_summary);
  (rate.notes || []).forEach((note) => {
    if (note.note_text) parts.push(note.note_text);
  });
  const uniqueParts = [...new Set(parts.map((part) => part.trim()).filter(Boolean))];
  return uniqueParts.length ? uniqueParts.join(" · ") : "No additional source notes were recorded for this rate.";
}

function renderCoverageGap(currentRates, broadSearch = false) {
  const present = new Set(currentRates.map((rate) => normalized(carrierName(rate))));
  const missing = (deskState.filters.carriers || []).filter((carrier) => !present.has(normalized(carrier)));
  if (!missing.length) {
    hideCoverageGap();
    return;
  }
  coverageGap.querySelector("p").textContent = broadSearch
    ? `No matching rates from ${formatList(missing)} for this search.`
    : `No rate on this lane from ${formatList(missing)} in the approved sheets.`;
  coverageGap.hidden = false;
}

function hideCoverageGap() {
  coverageGap.hidden = true;
  coverageGap.querySelector("p").textContent = "";
}

function renderDoorChip(selectedDoor) {
  if (!selectedDoor) {
    doorChip.hidden = true;
    return;
  }
  const pickup = (deskState.filters.door_pickups || []).find((item) => (
    sameValue(item.name || item.location, selectedDoor)
  ));
  if (!pickup) {
    doorChip.hidden = true;
    return;
  }
  const amount = pickup.amount_gbp ?? pickup.amount;
  doorChip.textContent = amount == null
    ? `Door: ${selectedDoor}`
    : `Door: ${selectedDoor} → +£${formatNumber(amount)}/ctn to port`;
  doorChip.hidden = false;
}

function renderRefreshText(value) {
  if (!value) {
    refreshText.textContent = "No approved rates yet";
    return;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    refreshText.textContent = "Approved rates loaded";
    return;
  }
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  refreshText.textContent = sameDay
    ? `Rates refreshed today ${time}`
    : `Rates refreshed ${date.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

function showDeskAlert(message, error = false) {
  deskAlert.textContent = message;
  deskAlert.classList.toggle("error", error);
  deskAlert.hidden = false;
}

function hideDeskAlert() {
  deskAlert.hidden = true;
  deskAlert.textContent = "";
  deskAlert.classList.remove("error");
}

function rateOrigin(rate) {
  return rate.pol || rate.place_of_receipt || rate.origin || "";
}

function rateDestination(rate) {
  return rate.final_destination || rate.pod || "";
}

function formatRateLane(rate) {
  return `${displayPlace(rateOrigin(rate))} → ${displayPlace(rateDestination(rate))}`;
}

function formatSearchTitle(origin, destination) {
  if (!origin && !destination) return "All available lanes";
  if (!origin) return `Any origin → ${displayPlace(destination)}`;
  if (!destination) return `${displayPlace(origin)} → Any destination`;
  return `${displayPlace(origin)} → ${displayPlace(destination)}`;
}

function carrierName(rate) {
  return rate.carrier_name || rate.provider_name || "Unknown carrier";
}

function compareRates(left, right) {
  const leftAmount = toNumber(left.all_in_amount);
  const rightAmount = toNumber(right.all_in_amount);
  if (leftAmount == null && rightAmount == null) return carrierName(left).localeCompare(carrierName(right));
  if (leftAmount == null) return 1;
  if (rightAmount == null) return -1;
  return leftAmount - rightAmount || carrierName(left).localeCompare(carrierName(right));
}

function compareVisibleRates(left, right) {
  const leftExpired = isExpired(left);
  const rightExpired = isExpired(right);
  if (leftExpired !== rightExpired) return leftExpired ? 1 : -1;
  return compareRates(left, right);
}

function isCurrentlyValid(rate) {
  const today = startOfToday();
  const validFrom = parseDate(rate.valid_from);
  const validTo = parseDate(rate.valid_to);
  if (validFrom && validFrom > today) return false;
  if (validTo && validTo < today) return false;
  return true;
}

function isExpired(rate) {
  const validTo = parseDate(rate.valid_to);
  return Boolean(validTo && validTo < startOfToday());
}

function validityPresentation(validTo) {
  const end = parseDate(validTo);
  if (!end) return { label: "No end date", warning: false, expired: false };
  const daysRemaining = Math.ceil((end - startOfToday()) / 86400000);
  const dateLabel = end.toLocaleDateString([], { day: "numeric", month: "short" });
  if (daysRemaining < 0) {
    return { label: `expired ${dateLabel}`, warning: true, expired: true };
  }
  return {
    label: daysRemaining <= 7 ? `expires ${dateLabel}` : `to ${dateLabel}`,
    warning: daysRemaining <= 7,
    expired: false,
  };
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfToday() {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  return date;
}

function contractTag(rate) {
  if (rate.contract_tag) return String(rate.contract_tag).slice(0, 18).toUpperCase();
  if (rate.offer_reference) return String(rate.offer_reference).replace(/^Offer\s*/i, "").slice(0, 18);
  const sheet = String(rate.raw_sheet_name || "");
  const match = sheet.match(/\b(PEUTE|PAPER|QT[-\w]*)\b/i);
  return match ? match[1].toUpperCase() : "";
}

function formatComponent(value, absolute = false) {
  if (value == null) return "—";
  const number = absolute ? Math.abs(value) : value;
  if (number < 0) return `−${formatNumber(Math.abs(number))}`;
  return formatNumber(number);
}

function formatMoney(value, currency) {
  const number = toNumber(value);
  if (number == null) return "—";
  const code = String(currency || "USD").toUpperCase();
  const symbols = { USD: "$", GBP: "£", EUR: "€" };
  const symbol = symbols[code] || `${code} `;
  return `${symbol}${formatNumber(number)}`;
}

function formatNumber(value) {
  return Number(value).toLocaleString("en-GB", { maximumFractionDigits: 2 });
}

function formatEquipment(value) {
  const equipment = canonicalEquipment(value);
  if (equipment === "40HC") return "40′ HC";
  if (equipment === "40") return "40′";
  if (equipment === "20") return "20′";
  return value;
}

function canonicalEquipment(value) {
  const equipment = normalized(value).replaceAll(" ", "");
  if (["40HC", "40HDRY", "40HCDRY", "FEU"].includes(equipment)) return "40HC";
  if (["40", "40DRY", "40DV"].includes(equipment)) return "40";
  if (["20", "20DRY", "20DV", "TEU"].includes(equipment)) return "20";
  return equipment;
}

function sameEquipment(left, right) {
  return canonicalEquipment(left) === canonicalEquipment(right);
}

function displayPlace(value) {
  const text = String(value || "").trim();
  if (!text || text !== text.toUpperCase()) return text;
  const keepUpper = new Set(["UK", "USA", "UAE", "JNPT", "POL", "POD"]);
  return text.toLowerCase().replace(/[a-z]+/g, (word) => {
    const upper = word.toUpperCase();
    return keepUpper.has(upper) ? upper : word[0].toUpperCase() + word.slice(1);
  });
}

function formatList(values) {
  if (values.length <= 1) return values[0] || "";
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values.at(-1)}`;
}

function sameValue(left, right) {
  return normalized(left) === normalized(right);
}

function normalized(value) {
  return String(value || "").trim().toUpperCase();
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
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
