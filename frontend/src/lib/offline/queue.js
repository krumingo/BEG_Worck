// PWA-02 (R61) — the offline queue on the phone.
//
// enqueue() seals a record (crypto.js) and stores it (store.js) under the current OWNER
// (tenant:user). flush() sends the owner's due records to POST /api/sync/batch and maps
// every answer to a FLOW-037 §9 status. Only the routing fields are plaintext; the
// envelope (with the payload) is AES-GCM ciphertext bound to the owner.
//
// Never queued here: money, approvals, contracts, IBAN, roles (R61-1) — callers use
// isOnlineOnly() and show „Това изисква интернет“ instead.
import { ownerOf, ownerKey, seal, open } from "./crypto";
import { createStore as createObservable } from "../pwa/store";

// FLOW-037 §9 L268–277 — the exact words.
export const STATUS = {
  saved: "Записано на телефона",
  pending: "Чака синхронизация",
  syncing: "Синхронизира се",
  synced: "Синхронизирано",
  conflict: "Конфликт",
  error: "Грешка",
  needs_review: "Изисква проверка",
  late: "Закъснял — чака офиса",
  waiting_file: "Чака качване на файл",
};

export const ONLINE_ONLY = ["payment", "invoice", "notice", "act", "contract", "annex",
  "approval", "approve", "iban", "counterparty", "role", "permission", "master_data"];
export const ONLINE_ONLY_MESSAGE = "Това изисква интернет";

export function isOnlineOnly(opType) {
  const head = String(opType || "").split(".")[0];
  return ONLINE_ONLY.some((p) => head.startsWith(p)) || String(opType).includes(".approve");
}

export const MAX_ATTEMPTS = 10;
export const MAX_DELAY_MS = 5 * 60 * 1000;
export const BATCH_SIZE = 20;
const SYNCED_KEEP_MS = 7 * 24 * 3600 * 1000;

export function backoffMs(attempts) {
  return Math.min(1000 * 2 ** Math.max(0, attempts - 1), MAX_DELAY_MS);
}

const uuid4 = () => (globalThis.crypto && globalThis.crypto.randomUUID
  ? globalThis.crypto.randomUUID()
  : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (c ^ (globalThis.crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));

function timezoneName() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Sofia"; } catch { return "Europe/Sofia"; }
}

export function createQueue({ store, api, subtle = globalThis.crypto && globalThis.crypto.subtle,
  now = () => Date.now(), onRevoked = () => {}, newId = uuid4 } = {}) {
  let session = null; // { tenantId, userId }
  let clockOffsetMs = 0; // device - server
  let enabled = false;
  let flushing = null;
  const state = createObservable({ enabled: false, unsent: 0, revoked: false, lastSyncAt: null, items: [] });

  const owner = () => (session ? ownerOf(session.tenantId, session.userId) : null);

  async function deviceId() {
    let id = await store.get("meta", "device_id");
    if (!id) {
      id = newId();
      await store.put("meta", "device_id", id);
    }
    return id;
  }

  async function rows() {
    const o = owner();
    if (!o) return [];
    return (await store.all("queue")).map(([, v]) => v).filter((r) => r.owner === o);
  }

  async function refresh() {
    const mine = await rows();
    const unsent = mine.filter((r) => r.status !== "synced").length;
    state.set((s) => ({ ...s, enabled, unsent, items: mine
      .map(({ sealed, ...plain }) => plain) // never expose ciphertext to the UI
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)) }));
    return unsent;
  }

  async function wipe() {
    await store.destroy();
    state.set({ enabled: false, unsent: 0, revoked: true, lastSyncAt: null, items: [] });
    onRevoked();
  }

  async function start(nextSession) {
    session = nextSession;
    if (!session) {
      state.set({ enabled: false, unsent: 0, revoked: false, lastSyncAt: null, items: [] });
      return false;
    }
    try {
      const id = await deviceId();
      const t0 = now();
      const st = (await api.get(`/sync/status?device_id=${id}`)).data;
      const t1 = now();
      // device - server, at the midpoint of the request
      clockOffsetMs = Math.round((t0 + t1) / 2 - Date.parse(st.server_time));
      enabled = st.enabled === true;
      if (st.revoked) {
        await wipe();
        return false;
      }
      if (enabled) await api.post("/sync/devices/register", { device_id: id, label: navigatorLabel() });
    } catch (err) {
      if (isRevoked(err)) {
        await wipe();
        return false;
      }
      // offline at start: keep what we knew; records are still captured if enabled before
      enabled = enabled || (await store.get("meta", `enabled:${owner()}`)) === true;
    }
    await store.put("meta", `enabled:${owner()}`, enabled);
    await refresh();
    return enabled;
  }

  async function enqueue(opType, payload, { projectId = null, baseVersion = null } = {}) {
    if (!session) throw new Error("no session");
    if (isOnlineOnly(opType)) {
      const e = new Error(ONLINE_ONLY_MESSAGE);
      e.code = "ONLINE_ONLY";
      throw e;
    }
    const o = owner();
    const key = await ownerKey(store, o, subtle);
    const localId = newId();
    const capturedAt = new Date(now()).toISOString();
    const envelope = {
      local_id: localId, idempotency_key: newId(), op_type: opType, captured_at: capturedAt,
      captured_tz: timezoneName(), device_clock_offset_ms: clockOffsetMs,
      user_id: session.userId, tenant_id: session.tenantId, device_id: await deviceId(),
      project_id: projectId, base_version: baseVersion, payload,
    };
    const row = { owner: o, local_id: localId, op_type: opType, status: "saved", captured_at: capturedAt,
      created_at: capturedAt, attempts: 0, next_at: 0, last_error: null,
      sealed: await seal(key, o, envelope, subtle) };
    await store.put("queue", localId, row);
    await refresh();
    return localId;
  }

  async function update(row, patch) {
    const next = { ...row, ...patch };
    if (next.status === "synced") {
      delete next.sealed; // the payload leaves the phone once the server holds it
      next.synced_at = now();
    }
    await store.put("queue", row.local_id, next);
    return next;
  }

  async function sendOnce() {
    if (!session || !enabled) return { sent: 0 };
    const o = owner();
    const key = await ownerKey(store, o, subtle);
    const t = now();
    const due = (await rows())
      .filter((r) => ["saved", "pending", "error"].includes(r.status) && (r.next_at || 0) <= t && r.sealed)
      .slice(0, BATCH_SIZE);
    // housekeeping: forget synced rows after 7 days
    for (const r of await rows()) {
      if (r.status === "synced" && t - (r.synced_at || t) > SYNCED_KEEP_MS) await store.del("queue", r.local_id);
    }
    if (!due.length) {
      await refresh();
      return { sent: 0 };
    }
    const envelopes = [];
    for (const r of due) {
      envelopes.push(await open(key, o, r.sealed, subtle));
      await update(r, { status: "syncing" });
    }
    await refresh();
    let answer;
    try {
      answer = (await api.post("/sync/batch", { device_id: await deviceId(), items: envelopes })).data;
    } catch (err) {
      if (isRevoked(err)) {
        await wipe();
        return { sent: 0, revoked: true };
      }
      const status = err && err.response && err.response.status;
      for (const r of due) {
        const fresh = await store.get("queue", r.local_id);
        if (!status) {
          // network: retry with backoff, then a human looks at it
          const attempts = (fresh.attempts || 0) + 1;
          await update(fresh, attempts >= MAX_ATTEMPTS
            ? { status: "needs_review", attempts, last_error: "RETRY_LIMIT" }
            : { status: "error", attempts, next_at: now() + backoffMs(attempts), last_error: "NETWORK" });
        } else if (status === 403 && code(err) === "OFFLINE_QUEUE_DISABLED") {
          await update(fresh, { status: "pending", last_error: "DISABLED" });
        } else {
          await update(fresh, { status: "needs_review", last_error: code(err) || `HTTP_${status}` });
        }
      }
      await refresh();
      return { sent: 0, error: true };
    }
    const byId = new Map((answer.results || []).map((x) => [x.local_id, x]));
    for (const r of due) {
      const fresh = await store.get("queue", r.local_id);
      const res = byId.get(r.local_id);
      if (!res) {
        await update(fresh, { status: "pending", next_at: now() + 1000 });
        continue;
      }
      if (res.status === "synced") await update(fresh, { status: "synced", result: res.result, last_error: null });
      else if (res.status === "processing") await update(fresh, { status: "pending", next_at: now() + 2000 });
      else if (res.status === "conflict") await update(fresh, { status: "conflict", result: res.result });
      else if (res.status === "late") await update(fresh, { status: "needs_review", sub: "late", result: res.result });
      else await update(fresh, { status: "needs_review", result: res.result,
        last_error: (res.result && res.result.error_code) || "REJECTED" });
    }
    state.set((s) => ({ ...s, lastSyncAt: answer.server_time || null }));
    await refresh();
    return { sent: due.length };
  }

  async function flush() {
    if (flushing) return flushing;
    flushing = (async () => {
      let total = 0;
      for (let i = 0; i < 20; i += 1) {
        const r = await sendOnce();
        total += r.sent || 0;
        if (!r.sent || r.revoked || r.error) break;
      }
      return total;
    })().finally(() => { flushing = null; });
    return flushing;
  }

  async function retry(localId) {
    const r = await store.get("queue", localId);
    if (r && r.owner === owner() && r.sealed) await update(r, { status: "pending", next_at: 0, attempts: 0 });
    await refresh();
  }

  return {
    state, start, enqueue, flush, retry, wipe, refresh, deviceId,
    unsentCount: async () => (await rows()).filter((r) => r.status !== "synced").length,
    isEnabled: () => enabled,
    _clockOffset: () => clockOffsetMs,
  };
}

function code(err) {
  const d = err && err.response && err.response.data && err.response.data.detail;
  return d && typeof d === "object" ? d.error_code : null;
}

function isRevoked(err) {
  return !!(err && err.response && err.response.status === 403 && code(err) === "DEVICE_REVOKED");
}

function navigatorLabel() {
  try {
    const ua = navigator.userAgent || "";
    if (/iphone/i.test(ua)) return "iPhone";
    if (/ipad/i.test(ua)) return "iPad";
    if (/android/i.test(ua)) return "Android";
    return "Компютър";
  } catch { return ""; }
}
