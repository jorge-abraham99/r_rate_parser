const state = {
  imports: [],
  selectedImport: null,
  searchResults: [],
};

const importsTableBody = document.getElementById("importsTableBody");
const detailPane = document.getElementById("detailPane");
const searchTableBody = document.getElementById("searchTableBody");
const importAlert = document.getElementById("importAlert");
const healthText = document.getElementById("healthText");

document.getElementById("importForm").addEventListener("submit", onImportSubmit);
document.getElementById("refreshImportsBtn").addEventListener("click", () => loadImports(true));
document.getElementById("searchForm").addEventListener("submit", onSearchSubmit);
document.getElementById("clearSearchBtn").addEventListener("click", clearSearch);

boot();

async function boot() {
  await Promise.all([loadHealth(), loadImports(false)]);
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("health check failed");
    const payload = await response.json();
    healthText.textContent = payload.status === "ok" ? "Local API connected" : "API unhealthy";
  } catch (error) {
    healthText.textContent = "Local API unavailable";
    showAlert(importAlert, `Could not reach the local API: ${error.message}`, "error");
  }
}

async function loadImports(selectNewest) {
  const response = await fetch("/api/imports?limit=25");
  const payload = await response.json();
  state.imports = payload;
  renderImports();
  if (selectNewest && payload.length > 0) {
    await loadImportDetail(payload[0].import_id);
  } else if (state.selectedImport) {
    const match = payload.find((item) => item.import_id === state.selectedImport.import_id);
    if (match) {
      await loadImportDetail(match.import_id);
    }
  }
}

function renderImports() {
  if (!state.imports.length) {
    importsTableBody.innerHTML = `<tr><td colspan="8" class="empty">No imports yet.</td></tr>`;
    return;
  }
  importsTableBody.innerHTML = state.imports.map((item) => `
    <tr>
      <td class="mono">${escapeHtml(item.import_id)}</td>
      <td>${escapeHtml(item.file_name || "-")}</td>
      <td><span class="status status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></td>
      <td>${escapeHtml(item.parser_family || "-")}</td>
      <td><span class="mono-chip">${escapeHtml(item.template_id || "-")}</span></td>
      <td>${escapeHtml(String((item.validation_summary || {}).warnings ?? 0))}</td>
      <td>${formatDateTime(item.created_at)}</td>
      <td>
        <button class="btn btn-secondary tiny" data-action="view" data-id="${escapeAttr(item.import_id)}">View</button>
        ${item.status !== "approved" ? `<button class="btn btn-primary tiny" data-action="approve" data-id="${escapeAttr(item.import_id)}">Approve</button>` : ""}
        ${item.status !== "rejected" ? `<button class="btn btn-danger tiny" data-action="reject" data-id="${escapeAttr(item.import_id)}">Reject</button>` : ""}
      </td>
    </tr>
  `).join("");

  importsTableBody.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", onImportActionClick);
  });
}

async function onImportActionClick(event) {
  const button = event.currentTarget;
  const action = button.dataset.action;
  const importId = button.dataset.id;
  if (action === "view") {
    await loadImportDetail(importId);
    return;
  }
  if (action === "approve") {
    const approvedBy = window.prompt("Approve as:", "abraham");
    if (!approvedBy) return;
    const response = await fetch(`/api/imports/${encodeURIComponent(importId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: approvedBy }),
    });
    await handleMutationResponse(response, `Approved ${importId}`);
    await loadImports(false);
    await loadImportDetail(importId);
    return;
  }
  if (action === "reject") {
    const reason = window.prompt("Reject reason:", "needs review");
    if (!reason) return;
    const response = await fetch(`/api/imports/${encodeURIComponent(importId)}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
    await handleMutationResponse(response, `Rejected ${importId}`);
    await loadImports(false);
    await loadImportDetail(importId);
  }
}

async function loadImportDetail(importId) {
  const response = await fetch(`/api/imports/${encodeURIComponent(importId)}`);
  if (!response.ok) {
    const error = await safeJson(response);
    detailPane.innerHTML = `<div class="alert alert-error">${escapeHtml(error.detail || "Could not load import detail.")}</div>`;
    return;
  }
  state.selectedImport = await response.json();
  renderImportDetail();
}

function renderImportDetail() {
  const detail = state.selectedImport;
  if (!detail) {
    detailPane.innerHTML = `<div class="empty">Select an import to inspect it.</div>`;
    return;
  }
  const canonicalRows = (detail.canonical_rates || []).slice(0, 12).map((row) => `
    <tr>
      <td>${escapeHtml(row.from_raw || "-")}</td>
      <td>${escapeHtml(row.to_raw || "-")}</td>
      <td class="mono">${escapeHtml(String(row.amount ?? "-"))}</td>
      <td>${escapeHtml(row.currency || "-")}</td>
      <td>${escapeHtml(row.valid_from || "-")}</td>
      <td>${escapeHtml(row.valid_to || "-")}</td>
    </tr>
  `).join("");
  const summary = detail.summary || {};
  detailPane.innerHTML = `
    <div class="split">
      <div>
        <div class="alert alert-info" style="margin-bottom:14px">
          <b>${escapeHtml(detail.source?.file_name || detail.import_id)}</b><br>
          Status: <span class="status status-${escapeHtml(detail.rate_import.status)}">${escapeHtml(detail.rate_import.status)}</span>
          <span class="muted"> · parser ${escapeHtml(detail.rate_import.parser_family || "-")} · template ${escapeHtml(detail.rate_import.template_id || "-")}</span>
        </div>
        <table>
          <tbody>
            <tr><th>Offers</th><td>${escapeHtml(String(summary.rate_offers ?? 0))}</td></tr>
            <tr><th>Charge lines</th><td>${escapeHtml(String(summary.charge_lines ?? 0))}</td></tr>
            <tr><th>Notes</th><td>${escapeHtml(String(summary.notes ?? 0))}</td></tr>
            <tr><th>Canonical rows</th><td>${escapeHtml(String(summary.canonical_rates ?? 0))}</td></tr>
            <tr><th>Warnings</th><td>${escapeHtml(String((detail.validation_report?.summary || {}).warnings ?? 0))}</td></tr>
            <tr><th>Errors</th><td>${escapeHtml(String((detail.validation_report?.summary || {}).errors ?? 0))}</td></tr>
          </tbody>
        </table>
        <div style="margin-top:16px">
          <h3 style="margin:0 0 8px;font-size:12px;color:#16273b">Canonical Preview</h3>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>From</th><th>To</th><th>Amount</th><th>Curr.</th><th>From</th><th>To</th></tr>
              </thead>
              <tbody>
                ${canonicalRows || `<tr><td colspan="6" class="empty">No canonical rows.</td></tr>`}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div>
        <h3 style="margin:0 0 8px;font-size:12px;color:#16273b">Review Markdown</h3>
        <div class="pre">${escapeHtml(detail.review_markdown || "No review markdown found.")}</div>
      </div>
    </div>
  `;
}

async function onImportSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const response = await fetch("/api/imports", { method: "POST", body: formData });
  if (!response.ok) {
    const error = await safeJson(response);
    showAlert(importAlert, error.detail || "Import failed.", "error");
    return;
  }
  const payload = await response.json();
  showAlert(importAlert, `Import created: ${payload.import_id}`, "info");
  form.reset();
  await loadImports(true);
}

async function onSearchSubmit(event) {
  event.preventDefault();
  const params = new URLSearchParams();
  const fieldIds = ["providerName", "carrierName", "pol", "pod", "equipmentType", "validOn"];
  const queryNames = {
    providerName: "provider_name",
    carrierName: "carrier_name",
    pol: "pol",
    pod: "pod",
    equipmentType: "equipment_type",
    validOn: "valid_on",
  };
  fieldIds.forEach((id) => {
    const value = document.getElementById(id).value.trim();
    if (value) params.set(queryNames[id], value);
  });
  params.set("limit", "100");
  const response = await fetch(`/api/search?${params.toString()}`);
  state.searchResults = await response.json();
  renderSearchResults();
}

function clearSearch() {
  ["providerName", "carrierName", "pol", "pod", "equipmentType", "validOn"].forEach((id) => {
    document.getElementById(id).value = "";
  });
  state.searchResults = [];
  renderSearchResults();
}

function renderSearchResults() {
  if (!state.searchResults.length) {
    searchTableBody.innerHTML = `<tr><td colspan="8" class="empty">No approved offers matched the current search.</td></tr>`;
    return;
  }
  searchTableBody.innerHTML = state.searchResults.map((row) => `
    <tr>
      <td><b>${escapeHtml(row.carrier_name || row.provider_name || "-")}</b><div class="tiny muted">${escapeHtml(row.provider_name || "-")}</div></td>
      <td>${escapeHtml(row.pol || row.place_of_receipt || "-")}</td>
      <td>${escapeHtml(row.pod || row.final_destination || "-")}</td>
      <td>${escapeHtml(row.equipment_type || "-")}</td>
      <td class="mono">${escapeHtml(formatMoney(row.base_amount, row.base_currency))}</td>
      <td class="mono">${escapeHtml(formatMoney(row.all_in_amount, row.base_currency))}</td>
      <td>${escapeHtml(compactValidity(row.valid_from, row.valid_to))}</td>
      <td><span class="mono-chip">${escapeHtml(row.raw_sheet_name || "-")}</span><div class="tiny muted">${escapeHtml(row.raw_row_reference || "-")}</div></td>
    </tr>
  `).join("");
}

async function handleMutationResponse(response, successMessage) {
  if (!response.ok) {
    const error = await safeJson(response);
    window.alert(error.detail || "Action failed.");
    return;
  }
  window.alert(successMessage);
}

function showAlert(container, message, tone) {
  container.innerHTML = `<div class="alert alert-${tone === "error" ? "error" : "info"}">${escapeHtml(message)}</div>`;
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}

function formatMoney(value, currency) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return `${value} ${currency || ""}`.trim();
  return `${currency || "USD"} ${number.toLocaleString("en-US")}`;
}

function compactValidity(validFrom, validTo) {
  if (validFrom && validTo) return `${validFrom} to ${validTo}`;
  if (validTo) return `to ${validTo}`;
  if (validFrom) return `from ${validFrom}`;
  return "-";
}

function formatDateTime(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
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
