export function formatTime(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "Timestamp unavailable";
  const total = Math.floor(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}` : `${minutes}:${String(secs).padStart(2, "0")}`;
}

export function claimText(claim = {}) { return claim.claim_english || claim.normalized_text || claim.original_text || claim.quote_original || "Claim text unavailable"; }
export function originalText(claim = {}) { return claim.quote_original || claim.original_text || "Original quote unavailable"; }
export function riskText(flag) { return typeof flag === "string" ? flag : (flag?.phrase || flag?.category || "Risk language"); }
