const IMPORT_DEMO_MODE = Boolean(window.RATE_DESK_CONFIG?.demoMode);
const SOURCE_DEFINITIONS = [
  { key: "maersk-contract", provider: "Maersk", service: "Quay-to-quay", cadence: "monthly" },
  { key: "maersk-door", provider: "Maersk", service: "Door-to-quay", cadence: "monthly" },
  { key: "msc-inline", provider: "MSC", service: "Quay-to-quay", cadence: "monthly" },
  { key: "hapag-door", provider: "Hapag-Lloyd", service: "Quay-to-quay", cadence: "monthly" },
  { key: "haulage-q2", provider: "UK Inland Haulage", service: "Export · all UK POLs", cadence: "quarterly" },
];

const importState = {
  sources: [],
  imports: [],
  approvedRates: [],
  preview: null,
  menuId: null,
  busy: false,
  toastTimer: null,
};

const elements = {
  sourceFile: document.getElementById("sourceFile"),
  dropZone: document.getElementById("dropZone"),
  dropzoneBusy: document.getElementById("dropzoneBusy"),
  importAlert: document.getElementById("importAlert"),
  periodText: document.getElementById("periodText"),
  demoBadge: document.getElementById("demoBadge"),
  sourceRows: document.getElementById("sourceRows"),
  coverageRisk: document.getElementById("coverageRisk"),
  previewModal: document.getElementById("previewModal"),
  parseModal: document.getElementById("parseModal"),
  previewTitle: document.getElementById("previewTitle"),
  previewFile: document.getElementById("previewFile"),
  sourceChoiceRow: document.getElementById("sourceChoiceRow"),
  sourceSelect: document.getElementById("sourceSelect"),
  newSourceName: document.getElementById("newSourceName"),
  contractTypeRow: document.getElementById("contractTypeRow"),
  contractTypeSelect: document.getElementById("contractTypeSelect"),
  parsedFacts: document.getElementById("parsedFacts"),
  previewValidity: document.getElementById("previewValidity"),
  previewLanes: document.getElementById("previewLanes"),
  mapSection: document.getElementById("mapSection"),
  mappedSummary: document.getElementById("mappedSummary"),
  mapBuckets: document.getElementById("mapBuckets"),
  previewMapNote: document.getElementById("previewMapNote"),
  diffSection: document.getElementById("diffSection"),
  diffTitle: document.getElementById("diffTitle"),
  diffPreviousLabel: document.getElementById("diffPreviousLabel"),
  diffRows: document.getElementById("diffRows"),
  diffSummary: document.getElementById("diffSummary"),
  tierRateSection: document.getElementById("tierRateSection"),
  tierRateTables: document.getElementById("tierRateTables"),
  firstSheetNote: document.getElementById("firstSheetNote"),
  publishButton: document.getElementById("publishButton"),
  cancelPreviewButton: document.getElementById("cancelPreviewButton"),
  closePreviewButton: document.getElementById("closePreviewButton"),
  archiveNote: document.getElementById("archiveNote"),
  toast: document.getElementById("toast"),
};

elements.sourceFile.addEventListener("change", () => {
  const file = elements.sourceFile.files?.[0];
  if (file) receiveFile(file);
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
  if (file && !importState.busy) receiveFile(file);
});
elements.sourceSelect.addEventListener("change", () => {
  if (!importState.preview) return;
  importState.preview.source = elements.sourceSelect.value;
  importState.preview.contractType = "";
  renderPreview();
});
elements.contractTypeSelect.addEventListener("change", () => {
  if (!importState.preview) return;
  importState.preview.contractType = elements.contractTypeSelect.value;
  renderPreview();
});
elements.newSourceName.addEventListener("input", () => {
  if (!importState.preview) return;
  importState.preview.newSourceName = elements.newSourceName.value;
  renderPreview();
});
elements.publishButton.addEventListener("click", publishPreview);
elements.cancelPreviewButton.addEventListener("click", cancelPreview);
elements.closePreviewButton.addEventListener("click", cancelPreview);
elements.previewModal.addEventListener("click", (event) => {
  if (event.target === elements.previewModal) cancelPreview();
});
document.addEventListener("click", () => {
  if (importState.menuId) {
    importState.menuId = null;
    renderSources();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && importState.preview && !importState.busy) cancelPreview();
});

bootImport();

async function bootImport() {
  elements.demoBadge.hidden = !IMPORT_DEMO_MODE;
  renderPeriod();
  if (IMPORT_DEMO_MODE) {
    importState.sources = clone(window.RATE_DESK_DEMO.sources);
    renderSources();
    return;
  }
  await refreshConnectedWorkspace();
}

async function refreshConnectedWorkspace() {
  try {
    const [importsResponse, deskResponse] = await Promise.all([
      fetch("/api/imports?limit=500"),
      fetch("/api/rate-desk?limit=5000"),
    ]);
    if (!importsResponse.ok || !deskResponse.ok) throw new Error("Could not load the import workspace.");
    importState.imports = (await importsResponse.json()).filter((item) => !isSpotImport(item));
    const desk = await deskResponse.json();
    importState.approvedRates = Array.isArray(desk.rates) ? desk.rates.filter((rate) => !isSpotImport(rate)) : [];
    importState.sources = adaptConnectedSources(importState.imports);
    hideAlert();
    renderSources();
  } catch (error) {
    showAlert(error.message);
  }
}

function adaptConnectedSources(imports) {
  const known = SOURCE_DEFINITIONS.map((definition) => buildConnectedSource(definition, imports));
  const knownKeys = new Set(SOURCE_DEFINITIONS.map((source) => source.key));
  const customKeys = unique(imports.map(inferSourceKey).filter((key) => key && !knownKeys.has(key)));
  return [
    ...known,
    ...customKeys.map((key) => {
      const matching = imports.filter((item) => inferSourceKey(item) === key);
      const provider = matching.find((item) => item.carrier_name)?.carrier_name
        || matching.find((item) => item.carrier_label)?.carrier_label
        || "Another source";
      const service = inferServiceLabel(matching[0]);
      return buildConnectedSource({ key, provider, service, cadence: "—" }, imports);
    }),
  ];
}

function buildConnectedSource(definition, imports) {
  const matching = imports
    .filter((item) => inferSourceKey(item) === definition.key)
    .sort((left, right) => dateValue(right.approved_at || right.created_at) - dateValue(left.approved_at || left.created_at));
  const current = matching.find((item) => item.status === "approved");
  const archived = matching.filter((item) => item.status === "archived");
  return {
    ...definition,
    current: current ? connectedFileView(current, false) : null,
    archived: archived.map((item) => connectedFileView(item, true)),
  };
}

function connectedFileView(item, archived) {
  return {
    id: item.import_id,
    file: item.file_name || "Uploaded sheet",
    uploaded: shortDateTime(item.approved_at || item.created_at),
    validFrom: item.valid_from,
    validTo: item.valid_to,
    lanes: item.lane_count ?? "—",
    status: archived ? "archived" : statusFromValidity(item.valid_to),
    connectedItem: item,
  };
}

function renderSources() {
  const rows = [];
  let lastProvider = "";
  importState.sources.forEach((source) => {
    const provider = source.provider || source.name || "Another provider";
    const startsProviderGroup = normalized(provider) !== normalized(lastProvider);
    rows.push(renderSourceRow(source, source.current, false, startsProviderGroup));
    (source.archived || []).forEach((file) => rows.push(renderSourceRow(source, file, true)));
    lastProvider = provider;
  });
  elements.sourceRows.innerHTML = rows.join("") || '<div class="sources-empty">No sources configured.</div>';
  elements.coverageRisk.hidden = !importState.sources.some((source) => source.current?.status === "overdue");

  elements.sourceRows.querySelectorAll("button[data-menu-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      importState.menuId = importState.menuId === button.dataset.menuId ? null : button.dataset.menuId;
      renderSources();
    });
  });
  elements.sourceRows.querySelectorAll("button[data-action='summary']").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openSummary(button.dataset.sourceKey, button.dataset.fileId);
    });
  });
  elements.sourceRows.querySelectorAll("button[data-action='delete']").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteFile(button.dataset.sourceKey, button.dataset.fileId);
    });
  });
}

function renderSourceRow(source, file, archived, startsProviderGroup = false) {
  const rowId = file?.id || `${source.key}-expected`;
  const status = archived ? "archived" : file?.status || "expected";
  const validity = file ? formatValidity(file.validFrom, file.validTo, status === "overdue") : "—";
  const menuOpen = importState.menuId === rowId;
  const provider = source.provider || source.name || "Another provider";
  const service = source.service || "—";
  return `
    <div class="sources-grid source-row${archived ? " archived-row" : ""}${startsProviderGroup ? " provider-group" : " service-group"}">
      <span class="provider-name" title="${escapeAttr(provider)}">${archived || !startsProviderGroup ? "" : escapeHtml(provider)}</span>
      <span class="service-name" title="${escapeAttr(archived ? "Previous sheet" : service)}">${archived ? "↳ previous" : escapeHtml(service)}</span>
      <span class="source-file mono">${file ? escapeHtml(file.file) : "—"}</span>
      <span>${file ? escapeHtml(file.uploaded) : "—"}</span>
      <span>${escapeHtml(source.cadence || "—")}</span>
      <span class="${status === "overdue" ? "overdue-text" : ""}">${escapeHtml(validity)}</span>
      <span class="number mono">${file ? escapeHtml(String(file.lanes ?? "—")) : "—"}</span>
      <span><span class="source-status ${escapeAttr(status)}">${escapeHtml(statusLabel(status))}</span></span>
      <span class="row-menu">
        ${file ? `
          <button class="menu-trigger" type="button" data-menu-id="${escapeAttr(rowId)}" aria-label="Actions for ${escapeAttr(file.file)}" aria-expanded="${menuOpen}">⋯</button>
          ${menuOpen ? `
            <span class="menu-popover">
              ${archived ? "" : `<button type="button" data-action="summary" data-source-key="${escapeAttr(source.key)}" data-file-id="${escapeAttr(file.id)}">View parse summary</button>`}
              <button class="danger" type="button" data-action="delete" data-source-key="${escapeAttr(source.key)}" data-file-id="${escapeAttr(file.id)}">Delete upload</button>
            </span>` : ""}` : ""}
      </span>
    </div>
  `;
}

async function receiveFile(file) {
  hideAlert();
  if (IMPORT_DEMO_MODE) {
    openReview({ fileName: file.name, source: "", contractType: "", newSourceName: "", detail: null, importId: null });
    return;
  }

  setBusy(true);
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("uploaded_by", "Rate Desk operator");
    const response = await fetch("/api/imports", { method: "POST", body: form });
    if (!response.ok) throw new Error((await safeJson(response)).detail || "The parser could not import this file.");
    const imported = await response.json();
    const detailResponse = await fetch(`/api/imports/${encodeURIComponent(imported.import_id)}`);
    if (!detailResponse.ok) throw new Error("The sheet parsed, but its preview could not be loaded.");
    const detail = await detailResponse.json();
    openReview({
      fileName: file.name,
      source: suggestedSource(detail),
      contractType: "",
      newSourceName: "",
      detail,
      importId: imported.import_id,
    });
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

function openReview(preview) {
  importState.preview = { ...preview, readOnly: false };
  elements.previewModal.hidden = false;
  document.body.classList.add("modal-open");
  renderPreview();
}

async function openSummary(sourceKey, fileId) {
  importState.menuId = null;
  renderSources();
  const source = importState.sources.find((item) => item.key === sourceKey);
  const file = [source?.current, ...(source?.archived || [])].find((item) => item?.id === fileId);
  if (!source || !file) return;

  if (IMPORT_DEMO_MODE) {
    importState.preview = {
      fileName: file.file,
      source: sourceChoiceForKey(sourceKey),
      contractType: sourceKey === "maersk-door" ? "d2k" : sourceKey === "maersk-contract" ? "k2k" : "",
      newSourceName: "",
      summary: demoSummary(sourceKey),
      readOnly: true,
      importId: null,
    };
    showPreviewModal();
    return;
  }

  setBusy(true);
  try {
    const response = await fetch(`/api/imports/${encodeURIComponent(fileId)}`);
    if (!response.ok) throw new Error("The parse summary could not be loaded.");
    const detail = await response.json();
    importState.preview = {
      fileName: file.file,
      source: sourceChoiceForKey(sourceKey),
      contractType: sourceKey === "maersk-door" ? "d2k" : sourceKey === "maersk-contract" ? "k2k" : "",
      newSourceName: "",
      summary: connectedSummary(detail, sourceKey),
      detail,
      readOnly: true,
      importId: fileId,
    };
    showPreviewModal();
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

function showPreviewModal() {
  elements.previewModal.hidden = false;
  document.body.classList.add("modal-open");
  renderPreview();
}

function renderPreview() {
  const preview = importState.preview;
  if (!preview) return;
  const sourceKey = selectedSourceKey(preview);
  const ready = preview.readOnly || Boolean(sourceKey);
  const summary = preview.summary || (ready
    ? IMPORT_DEMO_MODE
      ? demoSummary(sourceKey)
      : connectedSummary(preview.detail, sourceKey)
    : null);
  const isNew = preview.source === "__new";
  const isMaersk = preview.source === "maersk";

  elements.previewTitle.textContent = preview.readOnly ? "Parse summary" : "Review parsed sheet";
  elements.previewFile.textContent = preview.fileName;
  elements.sourceChoiceRow.hidden = preview.readOnly;
  elements.sourceSelect.value = preview.source;
  elements.newSourceName.hidden = !isNew || preview.readOnly;
  elements.newSourceName.value = preview.newSourceName || "";
  elements.contractTypeRow.hidden = preview.readOnly || !isMaersk;
  elements.contractTypeSelect.value = preview.contractType || "";
  elements.parsedFacts.hidden = !ready;
  elements.mapSection.hidden = !ready;

  if (summary) {
    elements.previewValidity.textContent = summary.validity || "—";
    elements.previewLanes.innerHTML = `<b>${escapeHtml(String(summary.lanes ?? "—"))}</b> · <span>${escapeHtml(summary.skipped || "")}</span>`;
    elements.mappedSummary.textContent = summary.unmatchedCount
      ? `${summary.unmatchedCount} charge${summary.unmatchedCount === 1 ? "" : "s"} unmatched`
      : `✓ All ${summary.mappedCount || 0} charges mapped`;
    elements.mappedSummary.className = `mapped-summary${summary.unmatchedCount ? " warning" : ""}`;
    elements.mapBuckets.hidden = !summary.unmatchedCount;
    elements.mapBuckets.innerHTML = summary.unmatchedCount
      ? [
          ...(summary.buckets || []).map((bucket) => `<span class="map-chip"><b>${bucket.count}</b> ${escapeHtml(bucket.label)}</span>`),
          `<span class="map-chip warn"><b>${summary.unmatchedCount}</b> unmatched</span>`,
        ].join("")
      : "";
    elements.previewMapNote.textContent = summary.note || "";
    renderDifferences(summary);
  } else {
    elements.diffSection.hidden = true;
  }
  renderTierRateTables(preview.detail?.tier_rate_tables || {});

  const hasCurrent = sourceKey && importState.sources.find((source) => source.key === sourceKey)?.current;
  elements.archiveNote.textContent = !preview.readOnly && hasCurrent ? "current sheet will be archived" : "";
  elements.firstSheetNote.hidden = !(ready && !summary?.differences?.length);
  elements.firstSheetNote.textContent = isNew
    ? "New source — its charges need mapping before rates can go live. It will show as Needs mapping."
    : "First sheet from this source — nothing to compare against yet.";

  elements.publishButton.hidden = preview.readOnly;
  elements.publishButton.disabled = preview.readOnly || !ready || importState.busy;
  elements.cancelPreviewButton.textContent = preview.readOnly ? "Close" : "Cancel";
}

function renderDifferences(summary) {
  const differences = summary.differences || [];
  elements.diffSection.hidden = !differences.length;
  if (!differences.length) return;
  elements.diffTitle.textContent = summary.deltaLabel || "All-in vs. previous sheet";
  elements.diffPreviousLabel.textContent = summary.previousLabel || "previous";
  elements.diffRows.innerHTML = differences.map((difference) => {
    const [lane, previous, next] = difference;
    const delta = next - previous;
    const deltaClass = delta === 0 ? "neutral" : delta > 0 ? "increase" : "decrease";
    const prefix = delta > 0 ? "+" : delta < 0 ? "−" : "";
    const symbol = summary.currencySymbol || "$";
    return `
      <div class="diff-grid diff-row">
        <span>${escapeHtml(lane)}</span>
        <span>${symbol}${formatNumber(previous)}</span>
        <span>${symbol}${formatNumber(next)}</span>
        <span class="diff-delta ${deltaClass}">${prefix}${delta ? formatNumber(Math.abs(delta)) : "—"}</span>
      </div>
    `;
  }).join("");
  elements.diffSummary.textContent = summary.remaining || "";
}

function renderTierRateTables(tables) {
  const tiers = ["SPECIAL", "TARIFF"].filter((tier) => Array.isArray(tables?.[tier]) && tables[tier].length);
  elements.tierRateSection.hidden = !tiers.length;
  elements.parseModal.classList.toggle("has-tier-tables", Boolean(tiers.length));
  if (!tiers.length) {
    elements.tierRateTables.innerHTML = "";
    return;
  }
  elements.tierRateTables.innerHTML = tiers.map((tier) => {
    const rows = tables[tier];
    return `
      <details class="tier-rate-table" open>
        <summary><span>${escapeHtml(tier)}</span><small>${rows.length} workbook rows</small></summary>
        <div class="tier-table-scroll">
          <table>
            <thead><tr>
              <th>Zone</th><th>POL</th><th>POD</th><th>Final destination</th><th>Size</th>
              <th class="number">All-in</th><th>Docs</th><th>Freetime</th><th>Validity</th>
            </tr></thead>
            <tbody>${rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.zone || "—")}</td>
                <td>${escapeHtml(row.pol || "—")}</td>
                <td>${escapeHtml(row.pod || "—")}</td>
                <td>${escapeHtml(row.final_destination || "—")}</td>
                <td>${escapeHtml(row.equipment_type || "—")}</td>
                <td class="number mono">${escapeHtml(`${row.currency || ""} ${formatNumber(row.amount)}`.trim())}</td>
                <td>${escapeHtml(row.documentation || "—")}</td>
                <td>${escapeHtml(row.freetime || "—")}</td>
                <td class="mono">${escapeHtml(compactValidity(row.valid_from, row.valid_to))}</td>
              </tr>`).join("")}</tbody>
          </table>
        </div>
      </details>`;
  }).join("");
}

function compactValidity(validFrom, validTo) {
  const start = parseDate(validFrom);
  const end = parseDate(validTo);
  if (start && end) return `${shortDate(start)} – ${shortDate(end)}`;
  if (start) return `from ${shortDate(start)}`;
  if (end) return `to ${shortDate(end)}`;
  return "—";
}

function demoSummary(sourceKey) {
  if (sourceKey?.startsWith("custom-")) {
    return {
      validity: "—",
      lanes: 0,
      skipped: "charges not yet mapped",
      mappedCount: 0,
      unmatchedCount: 1,
      buckets: [],
      note: "This source needs mapping before its rates can feed Quote.",
      differences: [],
    };
  }
  return clone(window.RATE_DESK_DEMO.parseSummaries[sourceKey] || {
    validity: "—",
    lanes: 0,
    skipped: "charges not yet mapped",
    mappedCount: 0,
    unmatchedCount: 1,
    buckets: [],
    note: "This source needs mapping before its rates can feed Quote.",
    differences: [],
  });
}

function connectedSummary(detail, sourceKey) {
  const validation = detail?.validation_report?.summary || {};
  const classification = detail?.charge_bucket_summary || {};
  const groups = Array.isArray(classification.groups) ? classification.groups : [];
  const buckets = groups.map((group) => ({ label: group.key, count: Number(group.line_count || group.lines?.length || 0) }));
  const unmatchedCount = Number(classification.unmatched_charge_count || validation.warnings || 0);
  const mappedCount = Number(classification.matched_charge_count || buckets.reduce((sum, bucket) => sum + bucket.count, 0));
  const rates = detail?.canonical_rates || [];
  const validFrom = detail?.card?.valid_from;
  const validTo = detail?.card?.valid_to;
  return {
    validity: formatValidity(validFrom, validTo),
    lanes: sourceKey === "msc-inline" ? Number(detail?.summary?.rate_offers || 0) : uniqueLaneCount(rates),
    skipped: validation.errors ? `${validation.errors} validation error${validation.errors === 1 ? "" : "s"}` : "no blocking validation errors",
    mappedCount,
    unmatchedCount,
    buckets,
    note: unmatchedCount ? "Unmatched charges need review before this source is fully trustworthy." : "",
    differences: sourceKey === "msc-inline" ? [] : connectedDifferences(rates, sourceKey),
    previousLabel: "previous",
    deltaLabel: sourceKey === "haulage-q2" ? "Haulage rate vs. previous sheet" : "All-in vs. previous sheet",
    remaining: "",
  };
}

function connectedDifferences(rates, sourceKey) {
  const previous = importState.approvedRates.filter((rate) => inferSourceKey(rate) === sourceKey);
  const previousByLane = new Map(previous.map((rate) => [laneKey(rateOrigin(rate), rateDestination(rate)), rate]));
  const rows = [];
  const seen = new Set();
  rates.forEach((rate) => {
    const key = laneKey(rate.from_raw, rate.to_raw);
    if (seen.has(key) || !previousByLane.has(key) || rows.length >= 4) return;
    seen.add(key);
    const prior = previousByLane.get(key);
    const oldValue = numberValue(prior.all_in_usd ?? prior.all_in_amount ?? prior.base_amount);
    const newValue = numberValue(rate.amount);
    if (oldValue != null && newValue != null) rows.push([`${displayPlace(rate.from_raw)} → ${displayPlace(rate.to_raw)}`, oldValue, newValue]);
  });
  return rows;
}

async function publishPreview() {
  const preview = importState.preview;
  if (!preview || elements.publishButton.disabled) return;
  const sourceKey = selectedSourceKey(preview);
  const summary = IMPORT_DEMO_MODE ? demoSummary(sourceKey) : connectedSummary(preview.detail, sourceKey);

  if (IMPORT_DEMO_MODE) {
    publishDemo(preview, sourceKey, summary);
    return;
  }

  const payload = sourcePayload(preview, sourceKey);
  setBusy(true);
  try {
    const response = await fetch(`/api/imports/${encodeURIComponent(preview.importId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error((await safeJson(response)).detail || "The rates could not be published.");
    closePreviewImmediately();
    showToast(`${payload.carrier_label} published — ${summary.lanes} lanes live in Quote`);
    await refreshConnectedWorkspace();
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

function publishDemo(preview, sourceKey, summary) {
  let source = importState.sources.find((item) => item.key === sourceKey);
  if (!source) {
    source = {
      key: sourceKey,
      provider: preview.newSourceName.trim(),
      service: "—",
      cadence: "ad hoc",
      current: null,
      archived: [],
    };
    importState.sources.push(source);
  }
  if (source.current) {
    source.archived.unshift({ ...source.current, status: "archived", id: `${source.current.id}-archived-${Date.now()}` });
  }
  source.current = {
    id: `demo-${sourceKey}-${Date.now()}`,
    file: preview.fileName,
    uploaded: "just now",
    validFrom: summary.validFrom || null,
    validTo: summary.validTo || null,
    lanes: summary.lanes || "—",
    status: preview.source === "__new" ? "needs-mapping" : "current",
    summaryKey: sourceKey,
  };
  closePreviewImmediately();
  renderSources();
  showToast(preview.source === "__new"
    ? `${source.provider} saved — charges need mapping before rates go live`
    : `${source.provider} ${source.service} published — ${summary.lanes} lanes live in Quote`);
}

function sourcePayload(preview, sourceKey) {
  if (preview.source === "__new") {
    const name = preview.newSourceName.trim();
    return {
      approved_by: "Rate Desk operator",
      carrier_name: name,
      carrier_key: sourceKey,
      carrier_label: name,
      contract_tag: null,
    };
  }
  if (sourceKey === "haulage-q2") {
    return {
      approved_by: "Rate Desk operator",
      carrier_name: "UK Inland Haulage",
      carrier_key: sourceKey,
      carrier_label: "UK Inland Haulage",
      contract_tag: "HAUL",
    };
  }
  if (sourceKey === "msc-inline") {
    return {
      approved_by: "Rate Desk operator",
      carrier_name: "MSC",
      carrier_key: sourceKey,
      carrier_label: "MSC · Quay-to-quay",
      contract_tag: null,
    };
  }
  if (sourceKey === "hapag-door") {
    return {
      approved_by: "Rate Desk operator",
      carrier_name: "Hapag-Lloyd",
      carrier_key: sourceKey,
      carrier_label: "Hapag-Lloyd · Quay-to-quay",
      contract_tag: null,
    };
  }
  const door = sourceKey === "maersk-door";
  return {
    approved_by: "Rate Desk operator",
    carrier_name: "Maersk",
    carrier_key: sourceKey,
    carrier_label: door ? "Maersk · Door-to-quay" : "Maersk · Quay-to-quay",
    contract_tag: door ? "DOOR" : "KEY",
  };
}

async function cancelPreview() {
  const preview = importState.preview;
  if (!preview || importState.busy) return;
  if (preview.readOnly || IMPORT_DEMO_MODE || !preview.importId) {
    closePreviewImmediately();
    return;
  }
  const importId = preview.importId;
  closePreviewImmediately();
  try {
    await fetch(`/api/imports/${encodeURIComponent(importId)}`, { method: "DELETE" });
  } finally {
    await refreshConnectedWorkspace();
  }
}

function closePreviewImmediately() {
  importState.preview = null;
  elements.previewModal.hidden = true;
  document.body.classList.remove("modal-open");
  elements.sourceSelect.value = "";
  elements.contractTypeSelect.value = "";
  elements.newSourceName.value = "";
}

async function deleteFile(sourceKey, fileId) {
  const source = importState.sources.find((item) => item.key === sourceKey);
  if (!source || !window.confirm("Delete this upload?")) return;
  importState.menuId = null;

  if (IMPORT_DEMO_MODE) {
    if (source.current?.id === fileId) source.current = null;
    source.archived = (source.archived || []).filter((file) => file.id !== fileId);
    renderSources();
    showToast("Upload deleted");
    return;
  }

  try {
    const response = await fetch(`/api/imports/${encodeURIComponent(fileId)}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await safeJson(response)).detail || "The upload could not be deleted.");
    showToast("Upload deleted");
    await refreshConnectedWorkspace();
  } catch (error) {
    showAlert(error.message);
  }
}

function selectedSourceKey(preview) {
  if (preview.source === "msc") return "msc-inline";
  if (preview.source === "hapag") return "hapag-door";
  if (preview.source === "maersk") {
    if (preview.contractType === "k2k") return "maersk-contract";
    if (preview.contractType === "d2k") return "maersk-door";
    return "";
  }
  if (preview.source === "haulage") return "haulage-q2";
  if (preview.source === "__new" && preview.newSourceName.trim()) return `custom-${slugify(preview.newSourceName)}`;
  return "";
}

function inferSourceKey(item) {
  if (item.carrier_key) {
    const key = normalized(item.carrier_key);
    if (key.includes("hapag")) return "hapag-door";
    if (key.includes("door")) return "maersk-door";
    if (key.includes("haulage")) return "haulage-q2";
    if (key.includes("msc")) return "msc-inline";
    if (key.includes("maersk")) return "maersk-contract";
    return item.carrier_key;
  }
  const text = normalized(`${item.carrier_label || ""} ${item.carrier_name || ""} ${item.file_name || ""} ${item.contract_tag || ""}`);
  if (text.includes("hapag")) return "hapag-door";
  if (text.includes("haulage")) return "haulage-q2";
  if (text.includes("msc")) return "msc-inline";
  if (text.includes("maersk") && text.includes("door")) return "maersk-door";
  if (text.includes("maersk")) return "maersk-contract";
  return item.carrier_name ? `custom-${slugify(item.carrier_name)}` : "";
}

function inferServiceLabel(item) {
  const text = normalized(`${item?.carrier_label || ""} ${item?.service_mode || ""} ${item?.contract_tag || ""}`);
  if (text.includes("door") || text.includes("sd / cy") || text.includes("sd/cy")) return "Door-to-quay";
  if (text.includes("haulage")) return "Export · all UK POLs";
  return "Quay-to-quay";
}

function suggestedSource(detail) {
  if (detail?.rate_import?.parser_family === "msc_zoned_inline") return "msc";
  if (detail?.rate_import?.parser_family === "hapag_door_matrix") return "hapag";
  return "";
}

function sourceChoiceForKey(sourceKey) {
  if (sourceKey === "msc-inline") return "msc";
  if (sourceKey === "hapag-door") return "hapag";
  if (sourceKey === "haulage-q2") return "haulage";
  return "maersk";
}

function isSpotImport(item) {
  return [item.carrier_key, item.carrier_label, item.carrier_name, item.file_name, item.contract_tag]
    .filter(Boolean)
    .some((value) => normalized(value).includes("spot"));
}

function statusFromValidity(validTo) {
  const end = parseDate(validTo);
  if (!end) return "current";
  const days = Math.ceil((end.getTime() - todayUtc().getTime()) / 86400000);
  if (days < 0) return "overdue";
  if (days <= 2) return "due-soon";
  return "current";
}

function statusLabel(status) {
  return {
    current: "Current",
    expected: "Expected",
    "due-soon": "Due in 2 days",
    overdue: "Overdue",
    "needs-mapping": "Needs mapping",
    archived: "Archived",
  }[status] || capitalize(status);
}

function formatValidity(validFrom, validTo, expired = false) {
  const start = parseDate(validFrom);
  const end = parseDate(validTo);
  if (expired && end) return `expired ${fullDate(end)}`;
  if (start && end) return `${shortDate(start)} → ${fullDate(end)}`;
  if (end) return `to ${fullDate(end)}`;
  if (start) return `from ${fullDate(start)}`;
  return "—";
}

function renderPeriod() {
  const now = new Date();
  elements.periodText.textContent = `Week ${isoWeek(now)} · ${now.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  })}`;
}

function setBusy(value) {
  importState.busy = value;
  elements.dropzoneBusy.hidden = !value;
  if (importState.preview) renderPreview();
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  clearTimeout(importState.toastTimer);
  importState.toastTimer = setTimeout(() => {
    elements.toast.hidden = true;
  }, 3200);
}

function showAlert(message) {
  elements.importAlert.hidden = false;
  elements.importAlert.className = "desk-alert error";
  elements.importAlert.textContent = message;
}

function hideAlert() {
  elements.importAlert.hidden = true;
}

function uniqueLaneCount(rows) {
  return new Set((rows || []).map((row) => laneKey(row.from_raw, row.to_raw))).size;
}

function laneKey(from, to) {
  return `${normalized(from)}::${normalized(to)}`;
}

function rateOrigin(rate) {
  return rate.pol || rate.place_of_receipt || rate.origin || "";
}

function rateDestination(rate) {
  return rate.final_destination || rate.pod || "";
}

function displayPlace(value) {
  return String(value || "—").replace(/\bGB([A-Z]{3,4})\b/g, "$1").replace(/\s+/g, " ").trim();
}

function shortDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value || "—")
    : date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function dateValue(value) {
  const date = new Date(value || 0);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
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

function shortDate(date) {
  return `${date.getUTCDate()} ${monthName(date)}`;
}

function fullDate(date) {
  return `${date.getUTCDate()} ${monthName(date)} ${date.getUTCFullYear()}`;
}

function monthName(date) {
  return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][date.getUTCMonth()];
}

function formatNumber(value) {
  const number = numberValue(value) || 0;
  return Number.isInteger(number)
    ? number.toLocaleString("en-US")
    : number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function numberValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function isoWeek(date) {
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = (target.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - day + 3);
  const first = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const firstDay = (first.getUTCDay() + 6) % 7;
  first.setUTCDate(first.getUTCDate() - firstDay + 3);
  return 1 + Math.round((target - first) / 604800000);
}

function slugify(value) {
  return normalized(value).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "source";
}

function normalized(value) {
  return String(value || "").trim().toLowerCase();
}

function capitalize(value) {
  const text = String(value || "");
  return text ? text[0].toUpperCase() + text.slice(1) : "";
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

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch (_error) {
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
