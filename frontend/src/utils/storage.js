const AUTH_KEY = "health_auth";
const TXN_PREFIX = "health_txn_";

export function saveAuthSession(session) {
  sessionStorage.setItem(AUTH_KEY, JSON.stringify(session));
}

export function getAuthSession() {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function clearAuthSession() {
  sessionStorage.removeItem(AUTH_KEY);
}

export function saveTxnForUser(userId, txnId) {
  if (!userId || !txnId) return;
  const key = `${TXN_PREFIX}${userId}`;
  const existing = getTxnIdsForUser(userId);
  if (!existing.includes(txnId)) {
    const next = [txnId, ...existing].slice(0, 50);
    localStorage.setItem(key, JSON.stringify(next));
  }
}

export function getTxnIdsForUser(userId) {
  if (!userId) return [];
  try {
    const key = `${TXN_PREFIX}${userId}`;
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
