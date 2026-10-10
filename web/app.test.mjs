import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { claimText, formatTime, originalText, riskText } from "./ui-utils.mjs";
import { shouldRestoreAudit, startupStateFor } from "./startup-state.mjs";

test("timestamp formatting never invents a timestamp", () => {
  assert.equal(formatTime(65.9), "1:05");
  assert.equal(formatTime("bad"), "Timestamp unavailable");
});

test("claim fields follow the implemented backend aliases", () => {
  assert.equal(claimText({ claim_english: "A normalized claim" }), "A normalized claim");
  assert.equal(claimText({ normalized_text: "Fallback claim" }), "Fallback claim");
  assert.equal(originalText({ quote_original: "मूल दावा" }), "मूल दावा");
  assert.equal(riskText({ phrase: "guaranteed" }), "guaranteed");
});

test("startup recovery only resumes genuinely in-progress audits", () => {
  assert.equal(startupStateFor("complete"), "empty");
  assert.equal(startupStateFor("failed"), "empty");
  assert.equal(startupStateFor("pending"), "recover");
  assert.equal(startupStateFor("running"), "recover");
  assert.equal(shouldRestoreAudit("complete"), false);
  assert.equal(shouldRestoreAudit("failed"), false);
  assert.equal(shouldRestoreAudit("running"), true);
});

test("frontend contract includes live routes, recovery, filters, and distinct missing evidence", async () => {
  const [html, app] = await Promise.all([readFile(new URL("./index.html", import.meta.url), "utf8"), readFile(new URL("./app.js", import.meta.url), "utf8")]);
  for (const route of ["/api/health", "/api/audits", "/events", "/export", "?format=json", "?format=md"]) assert.match(app + html, new RegExp(route.replace(/[?]/g, "\\?")));
  assert.match(app, /new EventSource/);
  assert.match(app, /pollAudit/);
  assert.match(app, /No evidence retrieved/);
  assert.match(app, /Contradicted verdict/);
  assert.match(html, /not medical or financial advice/i);
});

test("frontend guards stale and overlapping audit responses", async () => {
  const app = await readFile(new URL("./app.js", import.meta.url), "utf8");
  assert.match(app, /if \(state\.running\) return/);
  assert.match(app, /const token = \+\+state\.viewToken/);
  assert.match(app, /function currentView\(token, auditId = null\)/);
  assert.match(app, /fetchAudit\(auditId\)\.then\(\(audit\) => handleAudit\(audit, token\)\)/);
  assert.match(app, /if \(!currentView\(token, auditId\)\) return/);
  assert.match(app, /if \(!response\.ok\) await apiError/);
  assert.match(app, /metadata\.url/);
  assert.match(app, /Audit \$\{audit\.audit_id\}/);
  assert.match(app, /evidence\.map\(\(item\) => evidenceHtml/);
  assert.match(app, /evidence\.length/);
  assert.match(app, /item\.snippet/);
  assert.match(app, /item\.url/);
  assert.match(app, /item\.date/);
  assert.match(app, /item\.tier/);
  assert.match(app, /import .*startup-state\.mjs/);
  assert.match(app, /startupStateFor\(audit\.status\)/);
  assert.match(app, /localStorage\.removeItem\(STORAGE_KEY\)/);
  assert.match(app, /evidence\.filter\(isUsableEvidence\)/);
  assert.match(app, /https\?:\\\/\\\//);
  assert.match(app, /item\.title === "-"/);
});
