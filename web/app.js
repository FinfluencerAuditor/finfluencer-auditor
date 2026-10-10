import { formatTime, claimText, originalText, riskText } from "./ui-utils.mjs";
import { shouldRestoreAudit, startupStateFor } from "./startup-state.mjs";

const STORAGE_KEY = "claimlens:last-audit-id";
const TERMINAL_STAGES = new Set(["complete", "failed"]);
const VERDICTS = ["Supported", "Contradicted", "Mixed", "No evidence found", "Unverifiable"];

const $ = (selector) => document.querySelector(selector);
const elements = {
  form: $("#audit-form"), url: $("#youtube-url"), formError: $("#form-error"), button: $("#audit-button"),
  health: $("#health-status"), empty: $("#empty-state"), progress: $("#progress-panel"), progressTitle: $("#progress-title"),
  progressValue: $("#progress-value"), progressBar: $("#progress-bar"), progressMessage: $("#progress-message"), recovery: $("#recovery-note"),
  error: $("#error-panel"), errorTitle: $("#error-title"), errorMessage: $("#error-message"), retry: $("#retry-button"),
  results: $("#results-panel"), resultTitle: $("#result-title"), resultSubtitle: $("#result-subtitle"), summary: $("#summary-cards"), warning: $("#audit-warning"),
  exportActions: $("#export-actions"), exportJson: $("#export-json"), exportMd: $("#export-md"), search: $("#claim-search"), filter: $("#verdict-filter"),
  claimCount: $("#claim-count"), claims: $("#claims-list"), claimsEmpty: $("#claims-empty")
};

let state = { auditId: null, audit: null, source: null, pollTimer: null, lastUrl: "", viewToken: 0, running: false };

function currentView(token, auditId = null) {
  return token === state.viewToken && (auditId === null || auditId === state.auditId);
}

function isUsableEvidence(item) {
  if (!item || typeof item !== "object" || typeof item.id !== "string" || !item.id.trim()) return false;
  if (typeof item.url !== "string" || !/^https?:\/\//i.test(item.url.trim())) return false;
  if (item.title === "-" || item.source === "-") return false;
  const hasContent = typeof item.title === "string" && item.title.trim() && item.title.trim() !== "-"
    || typeof item.snippet === "string" && item.snippet.trim()
    || item.metadata && typeof item.metadata.summary === "object";
  return Boolean(hasContent);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function apiError(response, fallback) {
  return response.json().catch(() => ({})).then((body) => { throw new Error(body.detail || body.error || fallback); });
}

function youtubeTimestamp(url, seconds) {
  try { const parsed = new URL(url); parsed.searchParams.set("t", `${Math.max(0, Math.floor(Number(seconds) || 0))}s`); return parsed.toString(); } catch { return ""; }
}

function setVisible(element, visible) { element.hidden = !visible; }
function setBusy(busy) { elements.button.disabled = busy; elements.button.querySelector("span").textContent = busy ? "Auditing…" : "Audit video"; }

function setProgress(event = {}) {
  const progress = Number(event.progress);
  elements.progressTitle.textContent = event.stage === "complete" ? "Audit complete" : (event.stage === "failed" ? "Audit stopped" : "Auditing your video");
  elements.progressMessage.textContent = event.message || "Working through the audit pipeline…";
  elements.progressValue.textContent = Number.isFinite(progress) ? `${Math.round(progress * 100)}%` : "In progress";
  elements.progressBar.style.width = Number.isFinite(progress) ? `${Math.max(0, Math.min(100, progress * 100))}%` : "0%";
}

function showError(title, message, retry = true) {
  state.running = false;
  setVisible(elements.progress, false); setVisible(elements.results, false); setVisible(elements.empty, false); setVisible(elements.error, true);
  elements.errorTitle.textContent = title; elements.errorMessage.textContent = message || "Please try again."; setVisible(elements.retry, retry); setBusy(false);
}

function showProgress(message = "Connecting to the audit pipeline…") {
  setVisible(elements.empty, false); setVisible(elements.error, false); setVisible(elements.results, false); setVisible(elements.progress, true);
  elements.progressMessage.textContent = message; setBusy(true);
}

function labelFor(value) { return value || "Unavailable"; }
function summaryCounts(audit) {
  const counts = audit?.summary?.verdict_counts || {};
  return VERDICTS.map((label) => ({ label, count: Number(counts[label] || 0) }));
}

function renderSummary(audit) {
  const summary = audit.summary || {}; const counts = summaryCounts(audit);
  elements.summary.innerHTML = `<div class="summary-card summary-total"><span>Total claims</span><strong>${Number(summary.total_claims || audit.claims?.length || 0)}</strong><small>${Number(summary.checkable_claims || 0)} checkable</small></div>${counts.map(({ label, count }) => `<div class="summary-card verdict-${label.toLowerCase().replace(/[^a-z]+/g, "-")}"><span>${escapeHtml(label)}</span><strong>${count}</strong><small>claim${count === 1 ? "" : "s"}</small></div>`).join("")}<div class="summary-card summary-risk"><span>Risk flags</span><strong>${Number(summary.risk_flags || 0)}</strong><small>language flags</small></div>`;
  elements.filter.innerHTML = `<option value="all">All verdicts</option>${counts.filter(({ count }) => count > 0).map(({ label }) => `<option value="${escapeHtml(label)}">${escapeHtml(label)}</option>`).join("")}`;
}

function evidenceHtml(item, cited) {
  const date = item.date ? `<span>${escapeHtml(item.date)}</span>` : "";
  const source = item.source ? `<span>${escapeHtml(item.source)}</span>` : "";
  const tier = item.tier ? `<span>Tier ${escapeHtml(item.tier)}</span>` : "";
  const link = item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">Open source <span aria-hidden="true">↗</span></a>` : "";
  return `<li class="evidence-item ${cited ? "evidence-cited" : ""}"><div class="evidence-top"><strong>${escapeHtml(item.title || "Untitled source")}</strong>${cited ? '<span class="cited-badge">Cited</span>' : ""}</div><div class="evidence-meta">${source}${tier}${date}</div>${item.snippet ? `<p>${escapeHtml(item.snippet)}</p>` : ""}${link}</li>`;
}

function renderClaim(result, metadata) {
  const claim = result.claim || {}; const judgment = result.judgment; const label = judgment?.label || (result.error ? "Unavailable" : "Pending");
  const evidence = Array.isArray(result.evidence) ? result.evidence.filter(isUsableEvidence) : []; const cited = new Set(judgment?.evidence_ids || []);
  const timestamp = formatTime(claim.start_seconds); const timestampUrl = metadata?.url ? youtubeTimestamp(metadata.url, claim.start_seconds) : "";
  const timestampLink = timestampUrl ? `<a class="timestamp" href="${escapeHtml(timestampUrl)}" target="_blank" rel="noopener noreferrer"><span aria-hidden="true">▶</span> ${timestamp}</a>` : `<span class="timestamp">${timestamp}</span>`;
  const risk = Array.isArray(claim.risk_flags) ? claim.risk_flags : [];
  const evidenceBlock = evidence.length ? `<ul class="evidence-list">${evidence.map((item) => evidenceHtml(item, cited.has(item.id))).join("")}</ul>` : `<div class="no-evidence"><strong>No evidence retrieved</strong><span>This is different from a Contradicted verdict: the search did not return relevant evidence for this claim.</span></div>`;
  return `<article class="claim-card" data-search="${escapeHtml([claimText(claim), originalText(claim), claim.domain, label, ...evidence.map((item) => `${item.title} ${item.source}`)].join(" ").toLowerCase())}" data-verdict="${escapeHtml(label)}"><div class="claim-card-head"><div class="claim-index">Claim ${escapeHtml(claim.id || "")}</div><div class="claim-head-right">${timestampLink}<span class="verdict-badge verdict-${label.toLowerCase().replace(/[^a-z]+/g, "-")}">${escapeHtml(label)}</span></div></div><h4>${escapeHtml(claimText(claim))}</h4><blockquote>${escapeHtml(originalText(claim))}</blockquote><div class="claim-tags"><span>${escapeHtml(claim.domain || "other")}</span><span>${escapeHtml(claim.claim_type || "claim")}</span>${risk.map((flag) => `<span class="risk-tag">⚠ ${escapeHtml(riskText(flag))}</span>`).join("")}</div>${judgment?.rationale ? `<p class="rationale">${escapeHtml(judgment.rationale)}</p>` : ""}${result.error ? `<p class="claim-error">This claim could not be checked: ${escapeHtml(result.error)}</p>` : ""}<details><summary>Evidence details <span>(${evidence.length})</span></summary>${evidenceBlock}</details></article>`;
}

function renderResults(audit) {
  state.running = false;
  state.audit = audit; setVisible(elements.progress, false); setVisible(elements.error, false); setVisible(elements.empty, false); setVisible(elements.results, true); setBusy(false);
  const metadata = audit.metadata || {}; elements.resultTitle.textContent = metadata.title || "Untitled video";
  elements.resultSubtitle.textContent = [metadata.url, metadata.channel, metadata.published_at ? `Published ${metadata.published_at}` : "", audit.audit_id ? `Audit ${audit.audit_id}` : ""].filter(Boolean).join(" · ");
  renderSummary(audit);
  const usedFallback = (audit.claims || []).some((item) => item.judgment?.analysis_mode === "deterministic_fallback");
  elements.warning.textContent = audit.error || (usedFallback
    ? "Gemini analysis was unavailable for part of this audit; deterministic evidence checks were used."
    : "Results reflect retrieved evidence at the time of this audit. A missing citation is not proof that a claim is false.");
  setVisible(elements.warning, true);
  const url = `/api/audits/${encodeURIComponent(audit.audit_id)}/export`; elements.exportJson.href = `${url}?format=json`; elements.exportMd.href = `${url}?format=md`; setVisible(elements.exportActions, true);
  renderClaims();
}

function renderClaims() {
  if (!state.audit) return; const query = elements.search.value.trim().toLowerCase(); const verdict = elements.filter.value;
  const results = (state.audit.claims || []).filter((result) => { const cardText = [claimText(result.claim || {}), originalText(result.claim || {}), result.claim?.domain, result.judgment?.label, ...(result.evidence || []).flatMap((e) => [e.title, e.source, e.snippet])].join(" ").toLowerCase(); return (!query || cardText.includes(query)) && (verdict === "all" || (result.judgment?.label || "Unavailable") === verdict); });
  elements.claimCount.textContent = `${results.length} of ${(state.audit.claims || []).length} shown`; elements.claims.innerHTML = results.map((result) => renderClaim(result, state.audit.metadata)).join(""); setVisible(elements.claimsEmpty, !results.length);
}

async function fetchAudit(auditId) {
  const response = await fetch(`/api/audits/${encodeURIComponent(auditId)}`, { headers: { Accept: "application/json" } });
  if (!response.ok) return apiError(response, "Could not retrieve this audit."); return response.json();
}

function stopLiveUpdates() { if (state.source) { state.source.close(); state.source = null; } if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; } }

function pollAudit(auditId, attempts = 0, token = state.viewToken) {
  if (!currentView(token, auditId)) return;
  stopLiveUpdates(); elements.recovery.textContent = "Live updates are unavailable. Checking the saved audit status…"; setVisible(elements.recovery, true);
  const check = async () => {
    if (!currentView(token, auditId)) return;
    try {
      const audit = await fetchAudit(auditId);
      if (!currentView(token, auditId)) return;
      if (["complete", "failed"].includes(audit.status)) { handleAudit(audit, token); return; }
      setProgress({ message: "The audit is still running. We’ll keep checking its saved status.", progress: NaN });
    } catch (error) {
      if (!currentView(token, auditId)) return;
      if (attempts >= 15) { showError("Audit status unavailable", error.message, true); return; }
    }
    if (!currentView(token, auditId)) return;
    if (attempts < 60) state.pollTimer = setTimeout(() => pollAudit(auditId, attempts + 1, token), 2000);
    else showError("Audit is taking longer than expected", "Refresh or retry to check the saved audit again.", true);
  }; check();
}

function handleAudit(audit, token = state.viewToken) {
  if (!currentView(token, audit.audit_id)) return;
  stopLiveUpdates(); setVisible(elements.recovery, false);
  if (audit.status === "complete") renderResults(audit);
  else showError("Audit could not be completed", audit.error || "The backend reported an error while processing this video.", true);
}

function connectEvents(auditId, token = state.viewToken) {
  if (!currentView(token, auditId)) return;
  stopLiveUpdates(); if (!window.EventSource) { pollAudit(auditId, 0, token); return; }
  try {
    state.source = new EventSource(`/api/audits/${encodeURIComponent(auditId)}/events`);
    state.source.onmessage = (message) => {
      if (!currentView(token, auditId)) return;
      try {
        const event = JSON.parse(message.data); setProgress(event);
        if (TERMINAL_STAGES.has(event.stage)) fetchAudit(auditId).then((audit) => handleAudit(audit, token)).catch((error) => { if (currentView(token, auditId)) showError("Could not load results", error.message); });
      } catch { /* Ignore malformed progress messages; GET remains authoritative. */ }
    };
    state.source.onerror = () => { if (!currentView(token, auditId)) return; if (state.source) state.source.close(); state.source = null; pollAudit(auditId, 0, token); };
  } catch { pollAudit(auditId, 0, token); }
}

async function startAudit(url) {
  if (state.running) return;
  stopLiveUpdates(); const token = ++state.viewToken; state.running = true; state.audit = null; state.auditId = null; showProgress(); state.lastUrl = url; elements.formError.hidden = true;
  try {
    const response = await fetch("/api/audits", { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify({ url }) });
    if (!currentView(token)) return;
    if (!response.ok) await apiError(response, "The audit could not be started.");
    const body = await response.json();
    if (!body.audit_id) throw new Error("The audit service returned no audit ID.");
    if (!currentView(token)) return;
    state.auditId = body.audit_id; localStorage.setItem(STORAGE_KEY, body.audit_id); setProgress({ stage: "queued", message: "Audit queued. Connecting to live progress…", progress: NaN }); connectEvents(body.audit_id, token);
  } catch (error) { if (currentView(token)) showError("Could not start audit", error.message, true); }
}

async function recoverAudit(auditId) {
  if (state.running) return;
  const token = state.viewToken;
  try {
    const audit = await fetchAudit(auditId);
    if (!currentView(token)) return;
    state.auditId = auditId;
    if (startupStateFor(audit.status) === "empty") {
      // Completed and failed audits are historical data, not default landing-page
      // state. Keep them retrievable by ID, but do not silently present them.
      localStorage.removeItem(STORAGE_KEY); state.auditId = null; state.audit = null;
      setVisible(elements.progress, false); setVisible(elements.results, false); setVisible(elements.error, false); setVisible(elements.empty, true);
    } else if (shouldRestoreAudit(audit.status)) {
      showProgress("Recovering this audit…"); connectEvents(auditId, token);
    }
  } catch {
    if (!currentView(token)) return;
    localStorage.removeItem(STORAGE_KEY); state.auditId = null; setVisible(elements.empty, true);
  }
}

elements.form.addEventListener("submit", (event) => { event.preventDefault(); if (state.running) return; const url = elements.url.value.trim(); if (!url || !/^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\//i.test(url)) { elements.formError.textContent = "Enter a valid public YouTube URL."; elements.formError.hidden = false; elements.url.focus(); return; } startAudit(url); });
elements.retry.addEventListener("click", () => state.lastUrl ? startAudit(state.lastUrl) : (state.auditId ? recoverAudit(state.auditId) : elements.url.focus()));
elements.search.addEventListener("input", renderClaims); elements.filter.addEventListener("change", renderClaims);

fetch("/api/health", { headers: { Accept: "application/json" } }).then((response) => response.ok ? response.json() : Promise.reject()).then((health) => { elements.health.innerHTML = `<span class="status-dot online"></span> ${health.demo_mode ? "Demo mode" : "Live analysis ready"}`; }).catch(() => { elements.health.innerHTML = '<span class="status-dot offline"></span> Service unavailable'; });
const savedAuditId = localStorage.getItem(STORAGE_KEY); if (savedAuditId) recoverAudit(savedAuditId);

export { formatTime, claimText, renderClaim, summaryCounts, currentView, shouldRestoreAudit, isUsableEvidence };
