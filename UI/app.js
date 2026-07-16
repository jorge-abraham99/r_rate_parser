const carrierRoster = [
  { key: "msc-peute", label: "MSC — PEUTE", carrierName: "MSC", contractTag: "PEUTE", cadence: "weekly", periodDays: 7 },
  { key: "msc-paper", label: "MSC — PAPER", carrierName: "MSC", contractTag: "PAPER", cadence: "weekly", periodDays: 7 },
  { key: "cosco", label: "COSCO", carrierName: "COSCO", contractTag: "", cadence: "weekly", periodDays: 7 },
  { key: "maersk", label: "Maersk", carrierName: "Maersk", contractTag: "", cadence: "monthly", periodDays: 31 },
  { key: "haulage", label: "UK Haulage", carrierName: "UK Haulage", contractTag: "", cadence: "quarterly", periodDays: 92 },
];

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
  coverageRisk: document.getElementById("coverageRisk"),
  uploadsList: document.getElementById("uploadsList"),
  previewModal: document.getElementById("previewModal"),
  previewFile: document.getElementById("previewFile"),
  carrierSelect: document.getElementById("carrierSelect"),
  newCarrierName: document.getElementById("newCarrierName"),
  parsedFacts: document.getElementById("parsedFacts"),
  previewValidity: document.getElementById("previewValidity"),
  previewLanes: document.getElementById("previewLanes"),
  diffSection: document.getElementById("diffSection"),
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
elements.dropZone.addEventListener("dragleave", () => elements.dropZone.classList.remove("drag-active"));
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
  } catch (error) {
    showAlert(error.message, true);
  }
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

function populateCarrierOptions() {
  elements.carrierSelect.innerHTML = [
    '<option value="">Select carrier…</option>',
    ...carrierRoster.map((carrier) => `<option value="${escapeAttr(carrier.key)}">${escapeHtml(carrier.label)}</option>`),
    '<option value="__new">Someone new…</option>',
  ].join("");
}

function renderPreview() {
  const preview = importState.preview;
  if (!preview) return;
  const detail = preview.detail;
  const isNew = preview.carrierKey === "__new";
  const carrier = carrierRoster.find((item) => item.key === preview.carrierKey);
  const isSelected = Boolean(carrier || (isNew && preview.newCarrierName.trim()));
  const validation = detail.validation_report?.summary || {};
  const errors = Number(validation.errors || 0);
  const warnings = Number(validation.warnings || 0);
  const laneCount = uniqueLaneCount(detail.canonical_rates || []);

  elements.previewFile.textContent = preview.fileName;
  elements.carrierSelect.value = preview.carrierKey;
  elements.newCarrierName.hidden = !isNew;
  if (isNew && elements.newCarrierName.value !== preview.newCarrierName) {
    elements.newCarrierName.value = preview.newCarrierName;
  }
  elements.parsedFacts.hidden = !preview.carrierKey;
  elements.previewValidity.textContent = formatValidity(detail.card?.valid_from, detail.card?.valid_to);
  elements.previewLanes.innerHTML = `<b>${laneCount}</b> · ${escapeHtml(equipmentSummary(detail))} · <span>${escapeHtml(validationSummary(errors, warnings))}</span>`;
  elements.publishButton.disabled = !isSelected || errors > 0 || importState.busy;

  const analysis = preview.carrierKey ? buildRateDiff(preview, carrier) : null;
  elements.diffSection.hidden = !analysis?.rows.length;
  elements.firstSheetNote.hidden = !preview.carrierKey || Boolean(analysis?.rows.length);
  elements.archiveNote.textContent = analysis?.hasPrevious ? "previous live sheet will be archived" : "";
  if (analysis?.rows.length) {
    elements.diffRows.innerHTML = analysis.rows.map(renderDiffRow).join("");
    const remaining = Math.max(0, laneCount - analysis.rows.length);
    elements.diffSummary.textContent = remaining
      ? `+ ${remaining} more parsed lane${remaining === 1 ? "" : "s"}`
      : "All comparable lanes shown.";
  } else if (preview.carrierKey) {
    elements.firstSheetNote.textContent = analysis?.hasPrevious
      ? "No matching lanes were found in the previous published sheet."
      : "First sheet from this carrier — nothing to compare against yet.";
  }
}

function buildRateDiff(preview, carrier) {
  const selectedName = carrier?.carrierName || preview.newCarrierName.trim();
  const previousRates = importState.approvedRates.filter((rate) => {
    if (carrier && rate.carrier_key) return rate.carrier_key === carrier.key;
    return normalized(rate.carrier_name || rate.provider_name) === normalized(selectedName);
  });
  const previousByLane = new Map();
  previousRates.forEach((rate) => {
    const key = laneKey(rateOrigin(rate), rateDestination(rate));
    if (!previousByLane.has(key)) previousByLane.set(key, rate);
  });

  const seen = new Set();
  const rows = [];
  for (const rate of preview.detail.canonical_rates || []) {
    const key = laneKey(rate.from_raw, rate.to_raw);
    if (seen.has(key) || !previousByLane.has(key)) continue;
    seen.add(key);
    const previous = previousByLane.get(key);
    rows.push({
      lane: `${displayPlace(rate.from_raw)} → ${displayPlace(rate.to_raw)}`,
      previous: toNumber(previous.base_amount),
      next: toNumber(rate.amount),
      currency: rate.currency || previous.base_currency || "USD",
    });
    if (rows.length === 4) break;
  }
  return { rows, hasPrevious: previousRates.length > 0 };
}

function renderDiffRow(row) {
  const delta = row.previous == null || row.next == null ? null : row.next - row.previous;
  const deltaClass = delta == null || delta === 0 ? "neutral" : delta > 0 ? "increase" : "decrease";
  const deltaLabel = delta == null || delta === 0
    ? "—"
    : delta > 0
      ? `+${formatNumber(delta)} ▲`
      : `−${formatNumber(Math.abs(delta))} ▼`;
  return `
    <div class="diff-grid diff-row">
      <span>${escapeHtml(row.lane)}</span>
      <span>${escapeHtml(formatMoney(row.previous, row.currency))}</span>
      <span>${escapeHtml(formatMoney(row.next, row.currency))}</span>
      <span class="${deltaClass}">${escapeHtml(deltaLabel)}</span>
    </div>
  `;
}

async function publishPreview() {
  const preview = importState.preview;
  if (!preview || elements.publishButton.disabled) return;
  const isNew = preview.carrierKey === "__new";
  const carrier = carrierRoster.find((item) => item.key === preview.carrierKey);
  const carrierName = isNew ? preview.newCarrierName.trim() : carrier.carrierName;
  const carrierLabel = isNew ? carrierName : carrier.label;
  const carrierKey = isNew ? `custom-${slugify(carrierName)}` : carrier.key;
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
        contract_tag: carrier?.contractTag || null,
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
  carrierRoster.forEach((carrier) => {
    const matches = importState.imports
      .filter((item) => inferCarrierKey(item) === carrier.key && ["approved", "archived"].includes(item.status))
      .sort((left, right) => dateValue(right.approved_at || right.created_at) - dateValue(left.approved_at || left.created_at));
    const live = matches.find((item) => item.status === "approved");
    if (live && isCurrentPeriod(live, carrier.periodDays)) {
      received.push({ carrier, item: live });
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
    : '<p class="status-empty">Nothing received yet.</p>';
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
    .slice(0, 15);
  if (!visible.length) {
    elements.uploadsList.innerHTML = '<div class="uploads-empty">No published sheets yet.</div>';
    return;
  }
  elements.uploadsList.innerHTML = visible.map((item) => `
    <div class="upload-grid upload-row">
      <span class="upload-file mono" title="${escapeAttr(item.file_name || "")}">${escapeHtml(item.file_name || "Unknown file")}</span>
      <strong>${escapeHtml(importCarrierLabel(item))}</strong>
      <span class="upload-when">${escapeHtml(shortDateTime(item.approved_at || item.created_at))}</span>
      <span class="upload-lanes mono">${escapeHtml(String(item.lane_count ?? 0))}</span>
      <span><span class="live-chip${item.status === "archived" ? " archived" : ""}">${item.status === "archived" ? "archived" : "live"}</span></span>
      <button class="delete-upload" type="button" data-import-id="${escapeAttr(item.import_id)}" data-file-name="${escapeAttr(item.file_name || "this file")}" title="Delete — re-upload a corrected file" aria-label="Delete ${escapeAttr(item.file_name || "upload")}">×</button>
    </div>
  `).join("");
  elements.uploadsList.querySelectorAll("button[data-import-id]").forEach((button) => {
    button.addEventListener("click", () => deleteUpload(button.dataset.importId, button.dataset.fileName));
  });
}

async function deleteUpload(importId, fileName) {
  if (!window.confirm(`Delete ${fileName}? Its published rates will be removed from Quote.`)) return;
  const response = await fetch(`/api/imports/${encodeURIComponent(importId)}`, { method: "DELETE" });
  if (!response.ok) {
    const error = await safeJson(response);
    showAlert(error.detail || "The upload could not be deleted.", true);
    return;
  }
  showToast(`${fileName} deleted — drop the corrected sheet when ready`);
  await refreshWorkspace();
}

function setBusy(value) {
  importState.busy = value;
  elements.dropZone.classList.toggle("is-busy", value);
  elements.dropzoneBusy.hidden = !value;
  elements.sourceFile.disabled = value;
  if (value) elements.publishButton.disabled = true;
  else if (importState.preview) renderPreview();
}

function renderPeriodText() {
  const now = new Date();
  elements.periodText.textContent = `Week ${isoWeek(now)} · ${now.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}`;
}

function showAlert(message, isError = false) {
  elements.importAlert.textContent = message;
  elements.importAlert.classList.toggle("error", isError);
  elements.importAlert.hidden = false;
}

function hideAlert() {
  elements.importAlert.hidden = true;
  elements.importAlert.textContent = "";
  elements.importAlert.classList.remove("error");
}

function showToast(message) {
  clearTimeout(importState.toastTimer);
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  importState.toastTimer = setTimeout(() => {
    elements.toast.hidden = true;
  }, 3200);
}

function uniqueLaneCount(rates) {
  return new Set(rates.map((rate) => laneKey(rate.from_raw, rate.to_raw))).size;
}

function equipmentSummary(detail) {
  const equipment = [...new Set((detail.offers_preview || []).map((offer) => offer.equipment_type).filter(Boolean))];
  return equipment.length ? equipment.map(formatEquipment).join(" / ") : "container rates";
}

function validationSummary(errors, warnings) {
  if (errors) return `${errors} blocking error${errors === 1 ? "" : "s"}`;
  return `${warnings} parser warning${warnings === 1 ? "" : "s"}`;
}

function formatValidity(from, to) {
  if (!from && !to) return "No validity dates found";
  return `${formatDate(from) || "open"} → ${formatDate(to) || "open"}`;
}

function isCurrentPeriod(item, periodDays) {
  const today = startOfToday();
  const validTo = parseDate(item.valid_to);
  if (validTo) return validTo >= today;
  const approved = new Date(item.approved_at || item.created_at || 0);
  return Number.isFinite(approved.getTime()) && (today - approved) / 86400000 <= periodDays;
}

function isOverdue(item, periodDays) {
  const validTo = parseDate(item.valid_to);
  if (validTo) return validTo < startOfToday();
  const approved = new Date(item.approved_at || item.created_at || 0);
  return Number.isFinite(approved.getTime()) && (startOfToday() - approved) / 86400000 > periodDays;
}

function daysLate(item, periodDays) {
  const validTo = parseDate(item.valid_to);
  if (validTo) return Math.max(1, Math.floor((startOfToday() - validTo) / 86400000));
  const approved = new Date(item.approved_at || item.created_at || 0);
  return Math.max(1, Math.floor((startOfToday() - approved) / 86400000 - periodDays));
}

function dueSoon(item) {
  const validTo = parseDate(item?.valid_to);
  if (!validTo) return false;
  const days = Math.ceil((validTo - startOfToday()) / 86400000);
  return days >= 0 && days <= 2;
}

function expectedLabel(carrier, item) {
  if (item?.valid_to) return `${carrier.cadence} · current sheet valid to ${formatDate(item.valid_to)}`;
  return `${carrier.cadence} · waiting for this period's sheet`;
}

function overdueLabel(item) {
  return item.valid_to ? `previous sheet expired ${formatDate(item.valid_to)}` : "latest sheet is outside its expected cadence";
}

function inferCarrierKey(item) {
  if (item.carrier_key) return item.carrier_key;
  const text = normalized([item.file_name, item.template_id, item.carrier_name, item.carrier_label].filter(Boolean).join(" "));
  if (text.includes("MSC") && text.includes("PAPER")) return "msc-paper";
  if (text.includes("MSC")) return "msc-peute";
  if (text.includes("COSCO")) return "cosco";
  if (text.includes("MAERSK")) return "maersk";
  if (text.includes("HAUL")) return "haulage";
  return "";
}

function importCarrierLabel(item) {
  if (item.carrier_label) return item.carrier_label;
  const rosterItem = carrierRoster.find((carrier) => carrier.key === inferCarrierKey(item));
  return rosterItem?.label || item.carrier_name || "Unknown carrier";
}

function rateOrigin(rate) {
  return rate.pol || rate.place_of_receipt || rate.origin || "";
}

function rateDestination(rate) {
  return rate.final_destination || rate.pod || "";
}

function laneKey(origin, destination) {
  return `${normalized(origin)}|${normalized(destination)}`;
}

function shortDateTime(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "date unknown";
  return date.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function dateValue(value) {
  const date = new Date(value || "");
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

function formatDate(value) {
  const date = parseDate(value);
  return date ? date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
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

function isoWeek(date) {
  const copy = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  copy.setUTCDate(copy.getUTCDate() + 4 - (copy.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(copy.getUTCFullYear(), 0, 1));
  return Math.ceil((((copy - yearStart) / 86400000) + 1) / 7);
}

function formatEquipment(value) {
  const equipment = normalized(value).replaceAll(" ", "");
  if (["40HC", "40HDRY", "40HCDRY", "FEU"].includes(equipment)) return "40′ HC";
  if (["40", "40DRY", "40DV"].includes(equipment)) return "40′";
  if (["20", "20DRY", "20DV", "TEU"].includes(equipment)) return "20′";
  return value;
}

function displayPlace(value) {
  const text = String(value || "").trim();
  if (!text || text !== text.toUpperCase()) return text;
  return text.toLowerCase().replace(/[a-z]+/g, (word) => word[0].toUpperCase() + word.slice(1));
}

function formatMoney(value, currency) {
  const number = toNumber(value);
  if (number == null) return "—";
  const symbols = { USD: "$", GBP: "£", EUR: "€" };
  const code = String(currency || "USD").toUpperCase();
  return `${symbols[code] || `${code} `}${formatNumber(number)}`;
}

function formatNumber(value) {
  return Number(value).toLocaleString("en-GB", { maximumFractionDigits: 2 });
}

function formatList(values) {
  if (values.length <= 1) return values[0] || "";
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values.at(-1)}`;
}

function slugify(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "carrier";
}

function normalized(value) {
  return String(value || "").trim().toUpperCase();
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
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
