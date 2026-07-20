const TRACKED_CARRIERS = [
  {
    key: "maersk-contract",
    label: "Maersk — Contract",
    carrierName: "Maersk",
    carrierLabel: "Maersk · Contract",
    contractTag: "CONTRACT",
    cadence: "monthly",
    periodDays: 31,
  },
  {
    key: "maersk-spot",
    label: "Maersk — Spot",
    carrierName: "Maersk",
    carrierLabel: "Maersk · Spot",
    contractTag: "SPOT",
    cadence: "weekly",
    periodDays: 7,
  },
];

const ONBOARDING_CARRIERS = [
  { key: "msc-peute", label: "MSC — PEUTE", carrierName: "MSC", carrierLabel: "MSC — PEUTE", contractTag: "PEUTE" },
  { key: "msc-paper", label: "MSC — PAPER", carrierName: "MSC", carrierLabel: "MSC — PAPER", contractTag: "PAPER" },
  { key: "cosco", label: "COSCO", carrierName: "COSCO", carrierLabel: "COSCO", contractTag: "" },
  { key: "haulage", label: "UK Haulage", carrierName: "UK Haulage", carrierLabel: "UK Haulage", contractTag: "" },
];

const ALL_CARRIERS = [...TRACKED_CARRIERS, ...ONBOARDING_CARRIERS];

const importState = {
  imports: [],
  approvedRates: [],
  preview: null,
  busy: false,
  toastTimer: null,
};

const elements = {
  sourceFile: document.getElementById("sourceFile"),
  dropZone: document.getElementById("dropZone"),
  dropzoneBusy: document.getElementById("dropzoneBusy"),
  importAlert: document.getElementById("importAlert"),
  periodText: document.getElementById("periodText"),
  receivedCount: document.getElementById("receivedCount"),
  receivedList: document.getElementById("receivedList"),
  expectedCount: document.getElementById("expectedCount"),
  expectedList: document.getElementById("expectedList"),
  overdueCount: document.getElementById("overdueCount"),
  overdueList: document.getElementById("overdueList"),
  overdueCard: document.getElementById("overdueCard"),
  onboardingQueue: document.getElementById("onboardingQueue"),
  coverageRisk: document.getElementById("coverageRisk"),
  uploadsList: document.getElementById("uploadsList"),
  previewModal: document.getElementById("previewModal"),
  previewFile: document.getElementById("previewFile"),
  carrierSelect: document.getElementById("carrierSelect"),
  newCarrierName: document.getElementById("newCarrierName"),
  parsedFacts: document.getElementById("parsedFacts"),
  previewValidity: document.getElementById("previewValidity"),
  previewLanes: document.getElementById("previewLanes"),
  mapSection: document.getElementById("mapSection"),
  previewMapOrigin: document.getElementById("previewMapOrigin"),
  previewMapFreight: document.getElementById("previewMapFreight"),
  previewMapDestination: document.getElementById("previewMapDestination"),
  previewMapUnmatched: document.getElementById("previewMapUnmatched"),
  previewMapUnmatchedChip: document.getElementById("previewMapUnmatchedChip"),
  previewMapNote: document.getElementById("previewMapNote"),
  diffSection: document.getElementById("diffSection"),
  diffTitle: document.getElementById("diffTitle"),
  diffPreviousLabel: document.getElementById("diffPreviousLabel"),
  diffRows: document.getElementById("diffRows"),
  diffSummary: document.getElementById("diffSummary"),
  firstSheetNote: document.getElementById("firstSheetNote"),
  archiveNote: document.getElementById("archiveNote"),
  publishButton: document.getElementById("publishButton"),
  cancelPreviewButton: document.getElementById("cancelPreviewButton"),
  toast: document.getElementById("toast"),
};

elements.sourceFile.addEventListener("change", () => {
  const file = elements.sourceFile.files?.[0];
  if (file) uploadRateSheet(file);
  elements.sourceFile.value = "";
});

elements.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!importState.busy) elements.dropZone.classList.add("drag-active");
});

elements.dropZone.addEventListener("dragleave", () => {
  elements.dropZone.classList.remove("drag-active");
});

elements.dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.dropZone.classList.remove("drag-active");
  const file = event.dataTransfer?.files?.[0];
  if (file && !importState.busy) uploadRateSheet(file);
});

elements.carrierSelect.addEventListener("change", () => {
  if (!importState.preview) return;
  importState.preview.carrierKey = elements.carrierSelect.value;
  renderPreview();
});

elements.newCarrierName.addEventListener("input", () => {
  if (!importState.preview) return;
  importState.preview.newCarrierName = elements.newCarrierName.value;
  renderPreview();
});

elements.publishButton.addEventListener("click", publishPreview);
elements.cancelPreviewButton.addEventListener("click", cancelPreview);

elements.previewModal.addEventListener("click", (event) => {
  if (event.target === elements.previewModal) cancelPreview();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && importState.preview && !importState.busy) cancelPreview();
});

bootImportWorkspace();

async function bootImportWorkspace() {
  renderPeriodText();
  populateCarrierOptions();
  renderOnboardingQueue();
  await refreshWorkspace();
}

async function refreshWorkspace() {
  try {
    const [importsResponse, deskResponse] = await Promise.all([
      fetch("/api/imports?limit=250"),
      fetch("/api/rate-desk?limit=5000"),
    ]);
    if (!importsResponse.ok || !deskResponse.ok) throw new Error("Could not load the import workspace.");
    importState.imports = await importsResponse.json();
    const deskPayload = await deskResponse.json();
    importState.approvedRates = Array.isArray(deskPayload.rates) ? deskPayload.rates : [];
    renderStatusBoard();
    renderUploads();
    hideAlert();
  } catch (error) {
    showAlert(error.message, true);
  }
}

function populateCarrierOptions() {
  elements.carrierSelect.innerHTML = [
    '<option value="">Select…</option>',
    ...ALL_CARRIERS.map((carrier) => `<option value="${escapeAttr(carrier.key)}">${escapeHtml(carrier.label)}</option>`),
    '<option value="__new">Another source…</option>',
  ].join("");
}

function renderOnboardingQueue() {
  elements.onboardingQueue.innerHTML = ONBOARDING_CARRIERS.map((carrier) => {
    const hasImport = importState.imports.some((item) => inferCarrierKey(item) === carrier.key);
    return `<span class="onboarding-chip${hasImport ? " live" : ""}">${escapeHtml(carrier.label)}</span>`;
  }).join("");
}

async function uploadRateSheet(file) {
  hideAlert();
  setBusy(true);
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("uploaded_by", "Rate Desk operator");
    const response = await fetch("/api/imports", { method: "POST", body: form });
    if (!response.ok) {
      const error = await safeJson(response);
      throw new Error(error.detail || "The parser could not import this file.");
    }
    const imported = await response.json();
    const detailResponse = await fetch(`/api/imports/${encodeURIComponent(imported.import_id)}`);
    if (!detailResponse.ok) throw new Error("The sheet parsed, but its preview could not be loaded.");
    importState.preview = {
      importId: imported.import_id,
      fileName: file.name,
      detail: await detailResponse.json(),
      carrierKey: "",
      newCarrierName: "",
    };
    elements.previewModal.hidden = false;
    document.body.classList.add("modal-open");
    renderPreview();
  } catch (error) {
    showAlert(error.message, true);
  } finally {
    setBusy(false);
  }
}

function renderPreview() {
  const preview = importState.preview;
  if (!preview) return;

  const detail = preview.detail;
  const isNew = preview.carrierKey === "__new";
  const carrier = ALL_CARRIERS.find((item) => item.key === preview.carrierKey);
  const validation = detail.validation_report?.summary || {};
  const errors = Number(validation.errors || 0);
  const warnings = Number(validation.warnings || 0);
  const laneCount = uniqueLaneCount(detail.canonical_rates || []);
  const mapping = buildChargeClassification(detail);
  const canPublish = Boolean(
    (carrier || (isNew && preview.newCarrierName.trim()))
    && errors === 0
    && !importState.busy
  );

  elements.previewFile.textContent = preview.fileName;
  elements.carrierSelect.value = preview.carrierKey;
  elements.newCarrierName.hidden = !isNew;
  if (elements.newCarrierName.value !== preview.newCarrierName) {
    elements.newCarrierName.value = preview.newCarrierName;
  }
  elements.parsedFacts.hidden = !preview.carrierKey;
  elements.previewValidity.textContent = formatValidity(detail.card?.valid_from, detail.card?.valid_to);
  elements.previewLanes.innerHTML = `<b>${laneCount}</b> · ${escapeHtml(equipmentSummary(detail))} · <span>${escapeHtml(validationSummary(errors, warnings))}</span>`;

  elements.mapSection.hidden = !preview.carrierKey;
  elements.previewMapOrigin.textContent = mapping.origin;
  elements.previewMapFreight.textContent = mapping.freight;
  elements.previewMapDestination.textContent = mapping.destination;
  elements.previewMapUnmatched.textContent = mapping.unmatched;
  elements.previewMapUnmatchedChip.className = `map-chip ${mapping.unmatched > 0 ? "warn" : "ok"}`;
  elements.previewMapNote.textContent = mapping.note;

  const diff = preview.carrierKey ? buildRateDiff(preview, carrier) : null;
  elements.diffSection.hidden = !diff?.rows.length;
  if (diff?.rows.length) {
    elements.diffTitle.textContent = `All-in USD vs. previous live sheet (${diff.previousLabel})`;
    elements.diffPreviousLabel.textContent = diff.previousLabel;
    elements.diffRows.innerHTML = diff.rows.map(renderDiffRow).join("");
    elements.diffSummary.textContent = diff.summary;
  } else {
    elements.diffRows.innerHTML = "";
    elements.diffSummary.textContent = "";
  }

  elements.firstSheetNote.hidden = !(preview.carrierKey && (!diff || !diff.rows.length));
  if (!elements.firstSheetNote.hidden) {
    if (isNew) {
      elements.firstSheetNote.textContent = "New source — its charges will need mapping to Origin / Freight / Destination before rates can go live cleanly.";
    } else if (diff?.hasPrevious) {
      elements.firstSheetNote.textContent = "No matching lanes were found in the previous published sheet.";
    } else {
      elements.firstSheetNote.textContent = "First sheet from this source — nothing to compare against yet.";
    }
  }

  elements.archiveNote.textContent = diff?.hasCurrentLive ? "previous live sheet will be archived" : "";
  elements.publishButton.disabled = !canPublish;
}

function buildChargeClassification(detail) {
  const summary = detail.charge_bucket_summary;
  if (summary && Array.isArray(summary.groups)) {
    const groupCounts = Object.fromEntries(summary.groups.map((group) => [group.key, Number(group.line_count || 0)]));
    const unmatched = Number(summary.unmatched_charge_count || 0);
    return {
      origin: groupCounts.origin || 0,
      freight: groupCounts.freight || 0,
      destination: groupCounts.destination || 0,
      unmatched,
      note: unmatched > 0
        ? `${unmatched} parsed charge line${unmatched === 1 ? "" : "s"} still need explicit mapping before this sheet is fully trustworthy.`
        : "All parsed charge lines are mapped into Origin / Freight / Destination buckets.",
    };
  }

  const charges = Array.isArray(detail.charges_preview) ? detail.charges_preview : [];
  const counts = { origin: 0, freight: 0, destination: 0, unmatched: 0 };
  charges.forEach((charge) => {
    const bucket = bucketForCharge(charge);
    if (bucket === "origin") counts.origin += 1;
    else if (bucket === "freight") counts.freight += 1;
    else if (bucket === "destination") counts.destination += 1;
    else counts.unmatched += 1;
  });
  return {
    ...counts,
    note: counts.unmatched > 0
      ? "Some visible charge lines are still heuristic and need manual review before this becomes fully trustworthy."
      : "All visible charge lines were classified into Origin / Freight / Destination buckets.",
  };
}

function bucketForCharge(charge) {
  const name = normalized(charge.charge_name);
  const type = normalized(charge.charge_type);
  if (type === "base" || name.includes("ocean freight") || name.includes("bunker") || name.includes("emission")) return "freight";
  if (name.includes("origin") || name.includes("export") || name.includes("haulage") || name.includes("intermodal") || name.includes("pickup")) return "origin";
  if (name.includes("destination") || name.includes("import") || name.includes("terminal handling") || name.includes("documentation") || name.includes("container protect") || name.includes("thc") || name.includes("delivery")) return "destination";
  if (name.includes("doc")) return "destination";
  return "freight";
}

function buildRateDiff(preview, carrier) {
  const selectedName = carrier?.carrierName || preview.newCarrierName.trim();
  const selectedKey = carrier?.key || `custom-${slugify(selectedName)}`;
  const previousImports = importState.imports
    .filter((item) => item.import_id !== preview.importId && ["approved", "archived"].includes(item.status))
    .filter((item) => inferCarrierKey(item) === selectedKey || normalized(item.carrier_name || item.carrier_label) === normalized(selectedName))
    .sort((left, right) => dateValue(right.approved_at || right.created_at) - dateValue(left.approved_at || left.created_at));
  const currentLive = previousImports.find((item) => item.status === "approved") || null;

  const previousRates = importState.approvedRates.filter((rate) => {
    if (currentLive && currentLive.carrier_key) return rate.carrier_key === currentLive.carrier_key;
    if (carrier?.key) return rate.carrier_key === carrier.key;
    return normalized(rate.carrier_name || rate.provider_name) === normalized(selectedName);
  });

  const previousByLane = new Map();
  previousRates.forEach((rate) => {
    const key = laneKey(rateOrigin(rate), rateDestination(rate));
    if (!previousByLane.has(key)) previousByLane.set(key, rate);
  });

  const rows = [];
  const seen = new Set();
  for (const rate of preview.detail.canonical_rates || []) {
    const key = laneKey(rate.from_raw, rate.to_raw);
    if (seen.has(key)) continue;
    seen.add(key);
    const previous = previousByLane.get(key);
    if (!previous) continue;
    rows.push({
      lane: `${displayPlace(rate.from_raw)} → ${displayPlace(rate.to_raw)}`,
      previous: toNumber(previous.all_in_amount ?? previous.base_amount),
      next: toNumber(rate.amount),
      currency: rate.currency || previous.base_currency || "USD",
    });
    if (rows.length === 4) break;
  }

  const previousLabel = currentLive?.contract_tag || currentLive?.carrier_label || (carrier?.contractTag || "prev");
  const remaining = Math.max(0, uniqueLaneCount(preview.detail.canonical_rates || []) - rows.length);
  return {
    rows,
    previousLabel,
    hasPrevious: previousImports.length > 0,
    hasCurrentLive: Boolean(currentLive),
    summary: rows.length
      ? remaining
        ? `+ ${remaining} more parsed lane${remaining === 1 ? "" : "s"}`
        : "All comparable lanes shown."
      : "",
  };
}

function renderDiffRow(row) {
  const delta = row.previous == null || row.next == null ? null : row.next - row.previous;
  const deltaClass = delta == null || delta === 0 ? "neutral" : delta > 0 ? "increase" : "decrease";
  const deltaLabel = delta == null || delta === 0
    ? "—"
    : delta > 0
      ? `+${formatNumber(delta)}`
      : `−${formatNumber(Math.abs(delta))}`;
  return `
    <div class="diff-grid diff-row">
      <span>${escapeHtml(row.lane)}</span>
      <span>${escapeHtml(formatUsd(row.previous))}</span>
      <span>${escapeHtml(formatUsd(row.next))}</span>
      <span class="diff-delta ${deltaClass}">${escapeHtml(deltaLabel)}</span>
    </div>
  `;
}

async function publishPreview() {
  const preview = importState.preview;
  if (!preview || elements.publishButton.disabled) return;

  const isNew = preview.carrierKey === "__new";
  const carrier = ALL_CARRIERS.find((item) => item.key === preview.carrierKey);
  const carrierName = isNew ? preview.newCarrierName.trim() : carrier.carrierName;
  const carrierLabel = isNew ? carrierName : carrier.carrierLabel;
  const carrierKey = isNew ? `custom-${slugify(carrierName)}` : carrier.key;
  const contractTag = isNew ? "" : carrier.contractTag;

  setBusy(true);
  try {
    const response = await fetch(`/api/imports/${encodeURIComponent(preview.importId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved_by: "Rate Desk operator",
        carrier_name: carrierName,
        carrier_key: carrierKey,
        carrier_label: carrierLabel,
        contract_tag: contractTag || null,
      }),
    });
    if (!response.ok) {
      const error = await safeJson(response);
      throw new Error(error.detail || "The rates could not be published.");
    }
    const lanes = uniqueLaneCount(preview.detail.canonical_rates || []);
    closePreviewImmediately();
    showToast(`${carrierLabel} published — ${lanes} lane${lanes === 1 ? "" : "s"} live in Quote`);
    await refreshWorkspace();
  } catch (error) {
    showAlert(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function cancelPreview() {
  const preview = importState.preview;
  if (!preview || importState.busy) return;
  closePreviewImmediately();
  try {
    await fetch(`/api/imports/${encodeURIComponent(preview.importId)}`, { method: "DELETE" });
  } finally {
    await refreshWorkspace();
  }
}

function closePreviewImmediately() {
  importState.preview = null;
  elements.previewModal.hidden = true;
  document.body.classList.remove("modal-open");
  elements.carrierSelect.value = "";
  elements.newCarrierName.value = "";
  elements.newCarrierName.hidden = true;
}

function renderStatusBoard() {
  const received = [];
  const expected = [];
  const overdue = [];

  TRACKED_CARRIERS.forEach((carrier) => {
    const matches = importState.imports
      .filter((item) => inferCarrierKey(item) === carrier.key && ["approved", "archived"].includes(item.status))
      .sort((left, right) => dateValue(right.approved_at || right.created_at) - dateValue(left.approved_at || left.created_at));
    const latestApproved = matches.find((item) => item.status === "approved") || null;
    if (latestApproved && isCurrentPeriod(latestApproved, carrier.periodDays)) {
      received.push({ carrier, item: latestApproved });
      return;
    }
    if (matches.length && isOverdue(matches[0], carrier.periodDays)) {
      overdue.push({ carrier, item: matches[0] });
      return;
    }
    expected.push({ carrier, item: matches[0] || null });
  });

  elements.receivedCount.textContent = received.length;
  elements.expectedCount.textContent = expected.length;
  elements.overdueCount.textContent = overdue.length;

  elements.receivedList.innerHTML = received.length
    ? received.map(({ carrier, item }) => `
        <div class="status-received-row">
          <strong>${escapeHtml(carrier.label)}</strong>
          <span class="mono">${escapeHtml(shortDateTime(item.approved_at || item.created_at))} · ${escapeHtml(item.approved_by || item.uploaded_by || "operator")}</span>
        </div>`).join("")
    : '<p class="status-empty">Nothing in yet.</p>';

  elements.expectedList.innerHTML = expected.length
    ? expected.map(({ carrier, item }) => `
        <div class="status-item">
          <strong>${escapeHtml(carrier.label)}${dueSoon(item) ? '<span class="due-chip">due in 2 days</span>' : ""}</strong>
          <span>${escapeHtml(expectedLabel(carrier, item))}</span>
        </div>`).join("")
    : '<p class="status-empty">Nothing outstanding.</p>';

  elements.overdueList.innerHTML = overdue.length
    ? overdue.map(({ carrier, item }) => `
        <div class="status-item">
          <strong>${escapeHtml(carrier.label)} <small>· ${daysLate(item, carrier.periodDays)} days late</small></strong>
          <span>${escapeHtml(overdueLabel(item))}</span>
        </div>`).join("")
    : '<p class="status-empty">No one is late.</p>';

  elements.overdueCard.classList.toggle("has-overdue", overdue.length > 0);
  renderCoverageRisk(overdue);
  renderOnboardingQueue();
}

function renderCoverageRisk(overdue) {
  if (!overdue.length) {
    elements.coverageRisk.hidden = true;
    return;
  }
  const names = formatList(overdue.map(({ carrier }) => carrier.label));
  elements.coverageRisk.querySelector("p").innerHTML = `<b>Coverage at risk:</b> ${escapeHtml(names)} ${overdue.length === 1 ? "is" : "are"} overdue. Quote coverage may be incomplete until the new sheet${overdue.length === 1 ? " is" : "s are"} published.`;
  elements.coverageRisk.hidden = false;
}

function renderUploads() {
  const visible = importState.imports
    .filter((item) => ["approved", "archived"].includes(item.status))
    .slice(0, 20);

  if (!visible.length) {
    elements.uploadsList.innerHTML = '<div class="uploads-empty">No published sheets yet.</div>';
    return;
  }

  elements.uploadsList.innerHTML = visible.map((item) => {
    const mapping = mappingSummaryForImport(item);
    const statusClass = item.status === "approved" ? "live" : "archived";
    return `
      <div class="uploads-grid upload-row">
        <span class="upload-file">${escapeHtml(item.file_name || "file")}</span>
        <span class="upload-source">${escapeHtml(item.carrier_label || item.carrier_name || item.carrier_key || "Source")}</span>
        <span class="upload-time">${escapeHtml(shortDateTime(item.approved_at || item.created_at))}</span>
        <span class="upload-lanes">${escapeHtml(String(item.lane_count || 0))}</span>
        <span class="upload-mapped">${escapeHtml(mapping)}</span>
        <span><span class="upload-status ${statusClass}">${escapeHtml(item.status === "approved" ? "live" : "archived")}</span></span>
        <button class="upload-delete" type="button" data-import-id="${escapeAttr(item.import_id)}" title="Delete upload">×</button>
      </div>
    `;
  }).join("");

  elements.uploadsList.querySelectorAll("button[data-import-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const importId = button.dataset.importId;
      await deleteImport(importId);
    });
  });
}

async function deleteImport(importId) {
  if (!window.confirm("Delete this upload and remove its published rows?")) return;
  try {
    const response = await fetch(`/api/imports/${encodeURIComponent(importId)}`, { method: "DELETE" });
    if (!response.ok) {
      const error = await safeJson(response);
      throw new Error(error.detail || "The upload could not be deleted.");
    }
    showToast("Upload deleted — drop the corrected sheet when ready");
    await refreshWorkspace();
  } catch (error) {
    showAlert(error.message, true);
  }
}

function mappingSummaryForImport(item) {
  const warnings = Number(item.validation_summary?.warnings || 0);
  if (!warnings) return "mapped";
  return `mapped · ${warnings} warning${warnings === 1 ? "" : "s"}`;
}

function renderPeriodText() {
  const now = new Date();
  const week = isoWeek(now);
  elements.periodText.textContent = `Week ${week} · ${now.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" })}`;
}

function setBusy(value) {
  importState.busy = value;
  elements.dropzoneBusy.hidden = !value;
  elements.publishButton.disabled = value || elements.publishButton.disabled;
}

function showAlert(message, error = false) {
  elements.importAlert.hidden = false;
  elements.importAlert.className = `desk-alert${error ? " error" : ""}`;
  elements.importAlert.textContent = message;
}

function hideAlert() {
  elements.importAlert.hidden = true;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  clearTimeout(importState.toastTimer);
  importState.toastTimer = setTimeout(() => {
    elements.toast.hidden = true;
  }, 3200);
}

function inferCarrierKey(item) {
  if (item.carrier_key) return item.carrier_key;
  const text = `${item.carrier_label || ""} ${item.carrier_name || ""} ${item.file_name || ""}`.toLowerCase();
  if (text.includes("spot")) return "maersk-spot";
  if (text.includes("maersk")) return "maersk-contract";
  if (text.includes("peute")) return "msc-peute";
  if (text.includes("paper")) return "msc-paper";
  if (text.includes("cosco")) return "cosco";
  if (text.includes("haulage")) return "haulage";
  return "";
}

function uniqueLaneCount(rows) {
  return new Set((rows || []).map((row) => laneKey(row.from_raw, row.to_raw))).size;
}

function laneKey(fromRaw, toRaw) {
  return `${normalized(fromRaw)}::${normalized(toRaw)}`;
}

function displayPlace(value) {
  if (!value) return "—";
  return String(value)
    .replace(/\bGB([A-Z]{3,4})\b/g, (_, code) => code)
    .replace(/\s+/g, " ")
    .trim();
}

function rateOrigin(rate) {
  return firstPresent(rate.pol, rate.place_of_receipt, rate.origin);
}

function rateDestination(rate) {
  return firstPresent(rate.final_destination, rate.pod);
}

function firstPresent(...values) {
  return values.find((value) => value) || "";
}

function formatValidity(validFrom, validTo) {
  if (validFrom && validTo) return `${validFrom} → ${validTo}`;
  if (validTo) return `to ${validTo}`;
  if (validFrom) return `from ${validFrom}`;
  return "open-ended";
}

function validationSummary(errors, warnings) {
  if (errors > 0) return `${errors} error${errors === 1 ? "" : "s"} · ${warnings} warning${warnings === 1 ? "" : "s"}`;
  if (warnings > 0) return `${warnings} warning${warnings === 1 ? "" : "s"}`;
  return "no validation warnings";
}

function equipmentSummary(detail) {
  const offers = detail.offers_preview || [];
  const equipment = unique(offers.map((offer) => offer.equipment_type).filter(Boolean));
  return equipment.length ? equipment.join(" / ") : "equipment not detected";
}

function expectedLabel(carrier, item) {
  if (!item) return `${carrier.cadence} source not received yet`;
  return `${carrier.cadence} · last approved ${shortDateTime(item.approved_at || item.created_at)}`;
}

function overdueLabel(item) {
  return `last approved ${shortDateTime(item.approved_at || item.created_at)}`;
}

function isCurrentPeriod(item, periodDays) {
  const value = dateValue(item.approved_at || item.created_at);
  if (!value) return false;
  return (Date.now() - value.getTime()) / 86400000 <= periodDays;
}

function isOverdue(item, periodDays) {
  const value = dateValue(item.approved_at || item.created_at);
  if (!value) return false;
  return (Date.now() - value.getTime()) / 86400000 > periodDays;
}

function dueSoon(item) {
  if (!item) return false;
  const value = dateValue(item.approved_at || item.created_at);
  if (!value) return false;
  const days = (Date.now() - value.getTime()) / 86400000;
  return days >= 5 && days < 7;
}

function daysLate(item, periodDays) {
  const value = dateValue(item.approved_at || item.created_at);
  if (!value) return 0;
  return Math.max(0, Math.round((Date.now() - value.getTime()) / 86400000 - periodDays));
}

function dateValue(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function shortDateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value || "—";
  return parsed.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function formatUsd(value) {
  const number = toNumber(value);
  if (number == null) return "—";
  return `$${Math.round(number).toLocaleString("en-US")}`;
}

function formatNumber(value) {
  const number = toNumber(value);
  if (number == null) return "0";
  if (Number.isInteger(number)) return number.toLocaleString("en-US");
  return number.toFixed(2);
}

function normalized(value) {
  return String(value || "").trim().toLowerCase();
}

function slugify(value) {
  return normalized(value).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "source";
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

function formatList(values) {
  if (!values.length) return "";
  if (values.length === 1) return values[0];
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values[values.length - 1]}`;
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isNaN(number) ? null : number;
}

function isoWeek(date) {
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNr = (target.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - dayNr + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const firstDayNr = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstDayNr + 3);
  return 1 + Math.round((target - firstThursday) / 604800000);
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
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
