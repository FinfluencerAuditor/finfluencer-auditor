export function shouldRestoreAudit(status) {
  return status === "pending" || status === "running";
}

export function startupStateFor(status) {
  return shouldRestoreAudit(status) ? "recover" : "empty";
}
