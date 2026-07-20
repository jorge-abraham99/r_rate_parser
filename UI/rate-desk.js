const FX_RATES = {
  USD: 1,
  GBP: 1.29,
  EUR: 1.09,
  INR: 0.0104,
  THB: 0.0302,
};

const EQUIPMENT_OPTIONS = [
  { value: "20GP", label: "20′" },
  { value: "40GP", label: "40′" },
  { value: "40HC", label: "40′ HC" },
];

const MATERIAL_OPTIONS = ["All materials", "Paper", "Metal", "Tyres"];
const ANY_ORIGIN = "__any_origin__";
const ANY_DESTINATION = "__any_destination__";
const ANY_EQUIPMENT = "__any_equipment__";

const deskState = {
  rates: [],
  filters: {
    origins: [],
    destinations: [],
    equipment_types: [],
    materials: [],
    door_pickups: [],
  },
  loaded: false,
  expandedOfferId: null,
};

const originSelect = document.getElementById("originSelect");
const destinationSelect = document.getElementById("destinationSelect");
const equipmentSelect = document.getElementById("equipmentSelect");
const qtyInput = document.getElementById("qtyInput");
const materialSelect = document.getElementById("materialSelect");
const doorSelect = document.getElementById("doorSelect");
const showExpiredToggle = document.getElementById("showExpiredToggle");
const rateRows = document.getElementById("rateRows");
const laneTitle = document.getElementById("laneTitle");
const laneSummary = document.getElementById("laneSummary");
const refreshText = document.getElementById("refreshText");
const doorChip = document.getElementById("doorChip");
const deskAlert = document.getElementById("deskAlert");
const figuresNote = document.getElementById("figuresNote");

[originSelect, destinationSelect, equipmentSelect, materialSelect].forEach((select) => {
  select.addEventListener("change", () => {
    deskState.expandedOfferId = null;
    renderDesk();
  });
});

qtyInput.addEventListener("change", () => {
  qtyInput.value = clampQuantity(qtyInput.value);
  deskState.expandedOfferId = null;
  renderDesk();
});

doorSelect.addEventListener("change", () => {
  deskState.expandedOfferId = null;
  renderDesk();
});

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
  const defaultRate = deskState.rates
    .filter(isCurrentlyValid)
    .sort(compareRates)
    [0] || deskState.rates.sort(compareRates)[0];

  populateSelect(
    originSelect,
    deskState.filters.origins,
    "No approved origins",
    ANY_ORIGIN,
    displayPlace,
    [{ value: ANY_ORIGIN, label: "Any origin" }],
  );
  populateSelect(
    destinationSelect,
    deskState.filters.destinations,
    "No approved destinations",
    ANY_DESTINATION,
    displayPlace,
    [{ value: ANY_DESTINATION, label: "Any destination" }],
  );

  equipmentSelect.innerHTML = [
    `<option value="${escapeAttr(ANY_EQUIPMENT)}">Any size</option>`,
    ...EQUIPMENT_OPTIONS.map((option) => `<option value="${escapeAttr(option.value)}">${escapeHtml(option.label)}</option>`),
  ]
    .join("");
  equipmentSelect.value = ANY_EQUIPMENT;
  equipmentSelect.disabled = false;

  const materials = deskState.filters.materials?.length
    ? ["All materials", ...deskState.filters.materials.filter((value) => value && value !== "All materials")]
    : MATERIAL_OPTIONS;
  materialSelect.innerHTML = materials
    .map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`)
    .join("");
  materialSelect.value = "All materials";
  materialSelect.disabled = false;

  const doorPickups = deskState.filters.door_pickups || [];
  if (!doorPickups.length) {
    doorSelect.innerHTML = '<option value="">Port drop-off (none)</option>';
    doorSelect.disabled = true;
  } else {
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
}

function populateSelect(select, values, emptyLabel, preferred, formatter = (value) => value, leadingOptions = []) {
  const uniqueValues = unique(values || []);
  if (!uniqueValues.length) {
    select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>`;
    select.disabled = true;
    return;
  }
  select.innerHTML = [
    ...leadingOptions.map((option) => `<option value="${escapeAttr(option.value)}">${escapeHtml(option.label)}</option>`),
    ...uniqueValues.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(formatter(value))}</option>`),
  ].join("");
  if (preferred && [...leadingOptions.map((option) => option.value), ...uniqueValues].some((value) => sameValue(value, preferred))) {
    select.value = [...leadingOptions.map((option) => option.value), ...uniqueValues].find((value) => sameValue(value, preferred));
  } else {
    select.value = leadingOptions[0]?.value || uniqueValues[0];
  }
  select.disabled = false;
}

function renderDesk() {
  if (!deskState.loaded) return;
  hideDeskAlert();

  if (!deskState.rates.length) {
    laneTitle.textContent = "Approved rate lookup";
    laneSummary.textContent = "no approved rates available";
    rateRows.innerHTML = '<div class="rate-empty">No rates have been published yet. Import and publish a carrier file in Import to populate this desk.</div>';
    figuresNote.textContent = "Origin / Freight / Destination columns are USD equivalents per container.";
    doorChip.hidden = true;
    return;
  }

  const selectedOrigin = originSelect.value;
  const selectedDestination = destinationSelect.value;
  const selectedEquipment = equipmentSelect.value;
  const selectedMaterial = materialSelect.value;
  const selectedDoor = doorSelect.value;
  const showExpired = showExpiredToggle.checked;
  const quantity = clampQuantity(qtyInput.value);
  qtyInput.value = quantity;

  const laneRates = deskState.rates.filter((rate) => {
    const originMatches = selectedOrigin === ANY_ORIGIN || sameValue(rateOrigin(rate), selectedOrigin);
    const destinationMatches = selectedDestination === ANY_DESTINATION || sameValue(rateDestination(rate), selectedDestination);
    const equipmentMatches = selectedEquipment === ANY_EQUIPMENT || sameEquipment(rate.equipment_type, selectedEquipment);
    return originMatches
      && destinationMatches
      && equipmentMatches
      && (selectedMaterial === "All materials" || (rate.materials || []).some((material) => sameValue(material, selectedMaterial)));
  });

  const visibleRates = laneRates
    .filter((rate) => isCurrentlyValid(rate) || (showExpired && isExpired(rate)))
    .map((rate) => enrichRate(rate, quantity, selectedDoor))
    .sort(compareEnrichedRates);

  laneTitle.textContent = buildResultsTitle(selectedOrigin, selectedDestination, selectedEquipment, selectedMaterial);
  renderDoorChip(selectedDoor);
  const sizeLabel = selectedEquipment === ANY_EQUIPMENT ? "mixed container sizes" : formatEquipment(selectedEquipment);
  figuresNote.textContent = quantity > 1
    ? `Origin / Freight / Destination columns are USD equivalents for the whole booking (${quantity} × ${sizeLabel}) — per-B/L charges are not multiplied.`
    : selectedEquipment === ANY_EQUIPMENT
      ? "Origin / Freight / Destination columns are USD equivalents per container, using each rate's own equipment size."
      : "Origin / Freight / Destination columns are USD equivalents per container.";

  if (!visibleRates.length) {
    laneSummary.textContent = "no parsed rates for this filter";
    const onlyExpired = laneRates.some(isExpired) && !showExpired;
    rateRows.innerHTML = `<div class="rate-empty">${escapeHtml(
      onlyExpired
        ? "These filters only match expired published rates. Turn on Show expired rates to view them."
        : "No parsed rates match the current filters."
    )}</div>`;
    return;
  }

  const bestLive = visibleRates.find((rate) => isCurrentlyValid(rate.originalRate)) || null;
  const bestSummary = bestLive
    ? `${visibleRates.length} rate${visibleRates.length === 1 ? "" : "s"} · best ${formatUsd(bestLive.totalUsd)} ${bestLive.product}`
    : `${visibleRates.length} expired rate${visibleRates.length === 1 ? "" : "s"} · shown for reference only`;
  laneSummary.textContent = bestSummary;

  rateRows.innerHTML = visibleRates.map((rate, index) => renderRate(rate, index, bestLive?.offerId || null)).join("");
  rateRows.querySelectorAll("button[data-offer-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const offerId = button.dataset.offerId;
      deskState.expandedOfferId = deskState.expandedOfferId === offerId ? null : offerId;
      renderDesk();
    });
  });
}

function enrichRate(rate, quantity, selectedDoor) {
  const offerId = String(rate.offer_id || `${carrierName(rate)}-${rate.raw_row_reference || "row"}`);
  const groups = buildChargeGroups(rate, quantity, selectedDoor);
  const totalUsdExact = groups.reduce((sum, group) => sum + group.subtotalUsdExact, 0);
  const product = formatProduct(rate);
  const tag = rate.contract_tag || contractTag(rate) || inferTagFromProduct(product);
  const flag = inferFlag(rate, product);
  const transit = formatTransit(rate);
  const sailing = formatSailing(rate);
  const freetime = formatFreetime(rate);
  const validity = validityPresentation(rate.valid_to);
  const totalLabel = quantity > 1
    ? `Total per booking (${quantity} × ${formatEquipment(canonicalEquipment(rate.equipment_type))})`
    : `Total per ${formatEquipment(canonicalEquipment(rate.equipment_type))}`;

  return {
    offerId,
    originalRate: rate,
    product,
    tag,
    flag,
    transit,
    sailing,
    freetime,
    validity,
    totalLabel,
    groups,
    originUsd: groups[0]?.subtotalUsdExact || 0,
    freightUsd: groups[1]?.subtotalUsdExact || 0,
    destinationUsd: groups[2]?.subtotalUsdExact || 0,
    totalUsd: totalUsdExact,
    totalUsdRounded: roundMoney(totalUsdExact),
    zeroNote: buildZeroNote(groups),
    fineprint: buildFinePrint(rate, groups),
  };
}

function buildChargeGroups(rate, quantity, selectedDoor) {
  const analysisGroups = buildGroupsFromAnalysis(rate.charge_analysis, quantity);
  if (analysisGroups) {
    return applyDoorCharges(analysisGroups, quantity, selectedDoor);
  }

  const rawCharges = Array.isArray(rate.charges) ? rate.charges : [];
  const lines = [];
  const seenBase = rawCharges.some((charge) => isBaseCharge(charge));

  if (!seenBase && rate.base_amount != null) {
    lines.push(makeLine("freight", {
      charge_name: rate.all_in_flag === true ? "All-in as quoted" : "Basic Ocean Freight",
      basis: "Container",
      currency: rate.base_currency || "USD",
      amount: rate.base_amount,
      synthetic: true,
    }, quantity));
  }

  rawCharges.forEach((charge) => {
    lines.push(makeLine(bucketForCharge(charge), charge, quantity));
  });

  if (!rawCharges.length && rate.all_in_amount != null && rate.base_amount == null) {
    lines.push(makeLine("freight", {
      charge_name: "All-in as quoted",
      basis: "Container",
      currency: rate.base_currency || "USD",
      amount: rate.all_in_amount,
      synthetic: true,
    }, quantity));
  }

  const grouped = [
    { key: "origin", label: "Origin charges" },
    { key: "freight", label: "Freight charges" },
    { key: "destination", label: "Destination charges" },
  ].map((group) => {
    const groupLines = lines.filter((line) => line.bucket === group.key);
    const subtotalUsdExact = groupLines.reduce((sum, line) => sum + line.usdExact, 0);
    return {
      key: group.key,
      label: group.label,
      lines: groupLines.filter((line) => !line.zeroRated),
      zeroLines: groupLines.filter((line) => line.zeroRated),
      subtotalUsdExact,
      subtotalUsd: formatUsd(subtotalUsdExact),
      subLabel: `${group.label.replace(" charges", "")} subtotal (USD)`,
    };
  });

  return applyDoorCharges(grouped, quantity, selectedDoor);
}

function buildGroupsFromAnalysis(analysis, quantity) {
  if (!analysis || !Array.isArray(analysis.groups)) return null;

  const groups = analysis.groups.map((group) => {
    const rawLines = Array.isArray(group.lines) ? group.lines : [];
    const normalizedLines = rawLines.map((line) => makeAnalysisLine(group.key, line, quantity));
    const visibleLines = normalizedLines.filter((line) => !line.zeroRated);
    const zeroLines = normalizedLines.filter((line) => line.zeroRated);
    const subtotalUsdExact = normalizedLines.reduce((sum, line) => sum + line.usdExact, 0);
    return {
      key: group.key,
      label: group.label || `${capitalize(group.key)} charges`,
      lines: visibleLines,
      zeroLines,
      subtotalUsdExact,
      subtotalUsd: formatUsd(subtotalUsdExact),
      subLabel: group.key === "unmatched"
        ? "Unmapped subtotal (USD)"
        : `${(group.label || `${capitalize(group.key)} charges`).replace(" charges", "")} subtotal (USD)`,
    };
  });

  const unmatchedLines = Array.isArray(analysis.unmatched_lines)
    ? analysis.unmatched_lines.map((line) => makeAnalysisLine("unmatched", line, quantity))
    : [];
  if (unmatchedLines.length) {
    const visibleLines = unmatchedLines.filter((line) => !line.zeroRated);
    const zeroLines = unmatchedLines.filter((line) => line.zeroRated);
    const subtotalUsdExact = unmatchedLines.reduce((sum, line) => sum + line.usdExact, 0);
    groups.push({
      key: "unmatched",
      label: "Unmapped charges",
      lines: visibleLines,
      zeroLines,
      subtotalUsdExact,
      subtotalUsd: formatUsd(subtotalUsdExact),
      subLabel: "Unmapped subtotal (USD)",
    });
  }

  return groups;
}

function makeAnalysisLine(bucket, line, quantity) {
  const basis = formatBasis(line.basis);
  const qty = quantityForRule(line.quantity_rule, basis, quantity);
  const ccy = (line.currency || "USD").toUpperCase();
  const unit = toNumber(line.unit_amount) || 0;
  const usdUnit = toNumber(line.usd_unit_amount) || 0;
  const usdExact = usdUnit * qty;
  return {
    bucket,
    name: line.name || "Charge",
    basis,
    qty,
    ccy,
    unit,
    usdExact,
    usdDisplay: formatUsdWithApprox(usdExact, ccy !== "USD" && unit !== 0),
    unitDisplay: formatUnit(unit),
    zeroRated: Boolean(line.zero_rated) || unit === 0,
    matchedBy: line.matched_by || "",
  };
}

function applyDoorCharges(groups, quantity, selectedDoor) {
  const clonedGroups = groups.map((group) => ({
    ...group,
    lines: [...group.lines],
    zeroLines: [...(group.zeroLines || [])],
  }));
  const doorCharge = selectedDoor ? selectedDoorRate(selectedDoor) : null;
  if (!doorCharge) return clonedGroups;

  const originGroup = clonedGroups.find((group) => group.key === "origin");
  if (!originGroup) return clonedGroups;

  const fuelUnit = roundMoney(doorCharge.amount_gbp * 0.057);
  originGroup.lines = originGroup.lines.filter((line) => normalized(line.name) !== normalized("Export Intermodal Fuel Fee"));
  originGroup.zeroLines = originGroup.zeroLines.filter((line) => normalized(line.name) !== normalized("Export Intermodal Fuel Fee"));

  const inland = makeSyntheticLine("origin", "Inland Haulage Export", "Container", "GBP", doorCharge.amount_gbp, quantity);
  const fuel = makeSyntheticLine("origin", "Export Intermodal Fuel Fee", "Percent", "GBP", fuelUnit, quantity);
  const target = fuel.zeroRated ? originGroup.zeroLines : originGroup.lines;
  originGroup.lines.push(inland);
  target.push(fuel);
  const allOriginLines = [...originGroup.lines, ...originGroup.zeroLines];
  originGroup.subtotalUsdExact = allOriginLines.reduce((sum, line) => sum + line.usdExact, 0);
  originGroup.subtotalUsd = formatUsd(originGroup.subtotalUsdExact);

  return clonedGroups;
}

function makeLine(bucket, charge, quantity) {
  const basis = formatBasis(charge.basis);
  const qty = quantityForBasis(basis, quantity);
  const ccy = (charge.currency || charge.ccy || "USD").toUpperCase();
  const unit = toNumber(charge.amount ?? charge.unit) || 0;
  const usdExact = unit * qty * fxRate(ccy);
  return {
    bucket,
    name: charge.charge_name || charge.name || "Charge",
    basis,
    qty,
    ccy,
    unit,
    usdExact,
    usdDisplay: formatUsdWithApprox(usdExact, ccy !== "USD" && unit !== 0),
    unitDisplay: formatUnit(unit),
    zeroRated: unit === 0,
  };
}

function makeSyntheticLine(bucket, name, basis, ccy, unit, quantity) {
  return makeLine(bucket, {
    charge_name: name,
    basis,
    currency: ccy,
    amount: unit,
  }, quantity);
}

function bucketForCharge(charge) {
  const name = normalized(charge.charge_name);
  const type = normalized(charge.charge_type);
  if (type === "base" || name.includes("ocean freight") || name.includes("bunker") || name.includes("emission") || name.includes("fuel eu")) {
    return "freight";
  }
  if (
    name.includes("origin")
    || name.includes("export")
    || name.includes("haulage")
    || name.includes("intermodal")
    || name.includes("rail")
    || name.includes("truck")
    || name.includes("pick")
  ) {
    return "origin";
  }
  if (
    name.includes("destination")
    || name.includes("import")
    || name.includes("terminal handling")
    || name.includes("documentation")
    || name.includes("container protect")
    || name.includes("dthc")
    || name.includes("thc")
    || name.includes("delivery")
  ) {
    return "destination";
  }
  if (name.includes("doc")) return "destination";
  return "freight";
}

function formatBasis(value) {
  const text = (value || "Container").trim();
  if (!text) return "Container";
  return text;
}

function quantityForBasis(basis, quantity) {
  const text = normalized(basis);
  if (text.includes("bill of lading") || text.includes("b/l") || text.includes("bl") || text.includes("booking")) return 1;
  if (text.includes("percent")) return 1;
  return quantity;
}

function quantityForRule(rule, basis, quantity) {
  if (rule === "per_bill_of_lading" || rule === "percent") return 1;
  return quantityForBasis(basis, quantity);
}

function renderRate(rate, index, bestOfferId) {
  const expanded = deskState.expandedOfferId === rate.offerId;
  const isBest = Boolean(bestOfferId && bestOfferId === rate.offerId && isCurrentlyValid(rate.originalRate));
  return `
    <article class="rate-record">
      <button
        class="quote-grid quote-row${isBest ? " best" : ""}${rate.validity.expired ? " expired" : ""}"
        type="button"
        data-offer-id="${escapeAttr(rate.offerId)}"
        aria-expanded="${expanded}"
      >
        <span class="rank">${index + 1}</span>
        <span class="rate-cell">
          <span class="rate-name">${escapeHtml(rate.product)}</span>
          ${isBest ? '<span class="best-badge">Best rate</span>' : ""}
          ${rate.flag ? `<span class="flag-badge">${escapeHtml(rate.flag)}</span>` : ""}
        </span>
        <span class="source-cell" title="${escapeAttr(rate.originalRate.source_file_name || rate.originalRate.raw_sheet_name || "Approved rate")}">
          ${rate.tag ? `<span class="mono-chip">${escapeHtml(rate.tag)}</span>` : ""}
          <span class="source-name">${escapeHtml(rate.originalRate.source_file_name || rate.originalRate.raw_sheet_name || "Approved rate")}</span>
        </span>
        <span class="transit-value">${escapeHtml(rate.transit)}</span>
        <span class="component-value">${escapeHtml(formatUsd(rate.originUsd))}</span>
        <span class="component-value">${escapeHtml(formatUsd(rate.freightUsd))}</span>
        <span class="component-value">${escapeHtml(formatUsd(rate.destinationUsd))}</span>
        <span class="all-in-value">${escapeHtml(formatUsd(rate.totalUsd))}</span>
        <span><span class="validity-chip${rate.validity.warning ? " warning" : ""}${rate.validity.expired ? " expired" : ""}">${escapeHtml(rate.validity.label)}</span></span>
      </button>
      ${expanded ? renderBreakdown(rate) : ""}
    </article>
  `;
}

function renderBreakdown(rate) {
  return `
    <div class="rate-breakdown">
      <div class="breakdown-meta">
        ${rate.sailing ? `<span class="mono">${escapeHtml(rate.sailing)}</span>` : ""}
        ${rate.freetime ? `<span class="pill">${escapeHtml(rate.freetime)}</span>` : ""}
      </div>
      <div class="breakdown-panel">
        ${rate.groups.map(renderGroup).join("")}
        <div class="breakdown-total">
          <span>${escapeHtml(rate.totalLabel)}</span>
          <span>${escapeHtml(formatUsd(rate.totalUsd))}</span>
        </div>
      </div>
      ${rate.zeroNote ? `<div class="zero-note">${escapeHtml(rate.zeroNote)}</div>` : ""}
      <div class="fine-print">${escapeHtml(rate.fineprint)}</div>
    </div>
  `;
}

function renderGroup(group) {
  return `
    <div class="breakdown-group-header">
      <span>${escapeHtml(group.label)}</span>
      <span>Basis</span>
      <span style="text-align:right">Qty</span>
      <span>Ccy</span>
      <span style="text-align:right">Unit price</span>
      <span style="text-align:right">USD</span>
    </div>
    ${group.lines.length ? group.lines.map(renderLine).join("") : `
      <div class="breakdown-row">
        <span>No mapped charges</span><span class="dim">—</span><span class="qty">—</span><span class="ccy">—</span><span class="money">—</span><span class="money">—</span>
      </div>
    `}
    <div class="breakdown-subtotal">
      <span>${escapeHtml(group.subLabel)}</span>
      <span>${escapeHtml(group.subtotalUsd)}</span>
    </div>
  `;
}

function renderLine(line) {
  return `
    <div class="breakdown-row">
      <span>${escapeHtml(line.name)}</span>
      <span class="dim">${escapeHtml(line.basis)}</span>
      <span class="qty">${escapeHtml(String(line.qty))}</span>
      <span class="ccy">${escapeHtml(line.ccy)}</span>
      <span class="money">${escapeHtml(line.unitDisplay)}</span>
      <span class="money">${escapeHtml(line.usdDisplay)}</span>
    </div>
  `;
}

function buildZeroNote(groups) {
  const zeroCount = groups.reduce((sum, group) => sum + group.zeroLines.length, 0);
  if (!zeroCount) return "";
  return `${zeroCount} zero-rated charge${zeroCount === 1 ? "" : "s"} collapsed into a footnote by default.`;
}

function buildFinePrint(rate, groups) {
  const parts = [];
  if (rate.transit_time_days) parts.push(`Transit ${rate.transit_time_days} days`);
  if (rate.routing_note) parts.push(rate.routing_note);
  if (rate.notes_summary) parts.push(rate.notes_summary);
  (rate.notes || []).forEach((note) => {
    if (note.note_text) parts.push(note.note_text);
  });
  if (!parts.length && groups.every((group) => group.lines.every((line) => line.zeroRated))) {
    parts.push("No additional source notes were recorded for this rate.");
  }
  return unique(parts.map((value) => value.trim()).filter(Boolean)).join(" · ") || "No additional source notes were recorded for this rate.";
}

function rateOrigin(rate) {
  return firstPresent(rate.pol, rate.place_of_receipt, rate.origin);
}

function rateDestination(rate) {
  return firstPresent(rate.final_destination, rate.pod);
}

function formatProduct(rate) {
  const carrier = carrierName(rate);
  if (normalized(rate.contract_tag) === "spot") return `${carrier} · Spot`;
  if (rate.contract_tag) return `${carrier} · Contract`;
  if (rate.offer_reference) return `${carrier} · Spot`;
  return carrier;
}

function inferTagFromProduct(product) {
  if (product.toLowerCase().includes("spot")) return "SPOT";
  return "";
}

function inferFlag(rate, product) {
  if (product.toLowerCase().includes("spot")) return "spot";
  return "";
}

function formatTransit(rate) {
  if (rate.transit_time_days) return `${rate.transit_time_days}d`;
  const note = `${rate.routing_note || ""} ${(rate.notes || []).map((item) => item.note_text || "").join(" ")}`.toLowerCase();
  const match = note.match(/(\d+)\s*d/);
  return match ? `${match[1]}d` : "—";
}

function formatSailing(rate) {
  if (rate.routing_note) return rate.routing_note;
  return "";
}

function formatFreetime(rate) {
  const notes = [rate.notes_summary, ...(rate.notes || []).map((note) => note.note_text)].filter(Boolean).join(" ");
  const match = notes.match(/(\d+\s*d[^·,.]*)/i);
  return match ? match[1] : "";
}

function carrierName(rate) {
  return rate.carrier_label || rate.carrier_name || rate.provider_name || "Carrier";
}

function contractTag(rate) {
  if (rate.contract_tag) return rate.contract_tag;
  if (rate.offer_reference) return rate.offer_reference;
  return "";
}

function renderDoorChip(selectedDoor) {
  if (!selectedDoor) {
    doorChip.hidden = true;
    return;
  }
  const pickup = selectedDoorRate(selectedDoor);
  if (!pickup) {
    doorChip.hidden = true;
    return;
  }
  doorChip.hidden = false;
  doorChip.textContent = `Door: ${pickup.name} → inland haulage £${formatNumber(pickup.amount_gbp)} / ctn added to origin charges`;
}

function selectedDoorRate(selectedDoor) {
  return (deskState.filters.door_pickups || []).find((item) => sameValue(item.name || item.location, selectedDoor)) || null;
}

function renderRefreshText(value) {
  if (!value) {
    refreshText.textContent = "Rates refreshed from approved data";
    return;
  }
  refreshText.textContent = `Rates refreshed ${shortDateTime(value)}`;
}

function showDeskAlert(message, error = false) {
  deskAlert.hidden = false;
  deskAlert.className = `desk-alert${error ? " error" : ""}`;
  deskAlert.textContent = message;
}

function hideDeskAlert() {
  deskAlert.hidden = true;
}

function compareRates(left, right) {
  const leftLive = isCurrentlyValid(left);
  const rightLive = isCurrentlyValid(right);
  if (leftLive !== rightLive) return leftLive ? -1 : 1;
  return (toNumber(left.all_in_usd) ?? Number.MAX_SAFE_INTEGER) - (toNumber(right.all_in_usd) ?? Number.MAX_SAFE_INTEGER);
}

function buildResultsTitle(selectedOrigin, selectedDestination, selectedEquipment, selectedMaterial) {
  const lane = `${selectedOrigin === ANY_ORIGIN ? "Any origin" : displayPlace(selectedOrigin)} → ${selectedDestination === ANY_DESTINATION ? "Any destination" : displayPlace(selectedDestination)}`;
  const tags = [];
  if (selectedEquipment !== ANY_EQUIPMENT) tags.push(formatEquipment(selectedEquipment));
  if (selectedMaterial !== "All materials") tags.push(selectedMaterial);
  return tags.length ? `${lane} · ${tags.join(" · ")}` : lane;
}

function compareEnrichedRates(left, right) {
  const leftLive = isCurrentlyValid(left.originalRate);
  const rightLive = isCurrentlyValid(right.originalRate);
  if (leftLive !== rightLive) return leftLive ? -1 : 1;
  if (left.totalUsdRounded !== right.totalUsdRounded) return left.totalUsdRounded - right.totalUsdRounded;
  return left.product.localeCompare(right.product);
}

function isCurrentlyValid(rate) {
  const today = todayUtc();
  const start = parseDate(rate.valid_from);
  const end = parseDate(rate.valid_to);
  if (start && start > today) return false;
  if (end && end < today) return false;
  return true;
}

function isExpired(rate) {
  const end = parseDate(rate.valid_to);
  return Boolean(end && end < todayUtc());
}

function validityPresentation(validTo) {
  const end = parseDate(validTo);
  if (!end) return { label: "open", warning: false, expired: false };
  const diffDays = Math.round((end.getTime() - todayUtc().getTime()) / 86400000);
  if (diffDays < 0) return { label: `expired ${formatDate(end)}`, warning: false, expired: true };
  if (diffDays <= 7) return { label: `expires ${formatDate(end)}`, warning: true, expired: false };
  return { label: `to ${formatDate(end)}`, warning: false, expired: false };
}

function sameEquipment(left, right) {
  return canonicalEquipment(left) === canonicalEquipment(right);
}

function canonicalEquipment(value) {
  const text = normalized(value);
  if (text === "20" || text === "20gp" || text === "20ft" || text === "20dv") return "20GP";
  if (text === "40" || text === "40gp") return "40GP";
  if (text === "40hc" || text === "40hq" || text === "40'hc" || text === "40′hc" || text === "feu") return "40HC";
  return (value || "").toUpperCase();
}

function formatEquipment(value) {
  const canonical = canonicalEquipment(value);
  return EQUIPMENT_OPTIONS.find((option) => option.value === canonical)?.label || canonical || "—";
}

function normalized(value) {
  return String(value || "").trim().toLowerCase();
}

function capitalize(value) {
  const text = String(value || "");
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

function sameValue(left, right) {
  return normalized(left) === normalized(right);
}

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function todayUtc() {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

function formatDate(dateValue) {
  return dateValue.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function shortDateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function displayPlace(value) {
  if (!value) return "—";
  return String(value)
    .replace(/\bGB([A-Z]{3,4})\b/g, (_, code) => code)
    .replace(/\b([A-Z]{5})\b/g, (_, code) => code)
    .replace(/\s+/g, " ")
    .trim();
}

function firstPresent(...values) {
  return values.find((value) => value) || "";
}

function formatUsd(value) {
  return `$${roundMoney(value).toLocaleString("en-US")}`;
}

function formatUsdWithApprox(value, approximate) {
  const rounded = roundMoney(value);
  if (rounded === 0 && value > 0) return "≈ 0";
  return `${approximate ? "≈ " : ""}${rounded.toLocaleString("en-US")}`;
}

function formatUnit(value) {
  const number = toNumber(value) || 0;
  if (number === 0) return "0";
  if (Number.isInteger(number)) return number.toLocaleString("en-US");
  return number.toFixed(2);
}

function formatNumber(value) {
  const number = toNumber(value);
  if (number == null) return "0";
  if (Number.isInteger(number)) return number.toLocaleString("en-US");
  return number.toFixed(2);
}

function roundMoney(value) {
  return Math.round((toNumber(value) || 0) * 100) / 100;
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isNaN(number) ? null : number;
}

function fxRate(ccy) {
  return FX_RATES[(ccy || "USD").toUpperCase()] || 1;
}

function clampQuantity(value) {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed) || parsed < 1) return 1;
  return Math.min(999, parsed);
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

function isBaseCharge(charge) {
  const name = normalized(charge.charge_name || charge.name);
  const type = normalized(charge.charge_type);
  return type === "base" || name === "ocean freight" || name.includes("basic ocean freight");
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
