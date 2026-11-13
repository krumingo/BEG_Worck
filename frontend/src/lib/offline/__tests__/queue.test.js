/**
 * @jest-environment node
 */
// PWA-02 — the phone side of the offline queue: encryption per owner, statuses, retries,
// idempotent resend, conflicts, late records, blocked device, online-only refusal.
import { createQueue, STATUS, backoffMs, MAX_ATTEMPTS, isOnlineOnly } from "@/lib/offline/queue";
import { memoryStore } from "@/lib/offline/store";
import { ownerOf, ownerKey, open, seal, sha256Hex } from "@/lib/offline/crypto";

// jest 27's sandbox has no WebCrypto global; Node's is the same API the browser has.
if (!globalThis.crypto || !globalThis.crypto.subtle) {
  Object.defineProperty(globalThis, "crypto", { value: require("crypto").webcrypto, configurable: true });
}

const A = { tenantId: "org-a", userId: "u-1" };
const OTHER = { tenantId: "org-a", userId: "u-2" };
const SERVER_TIME = "2026-11-09T10:00:00.000Z";

function fakeApi({ enabled = true, revoked = false } = {}) {
  const calls = [];
  const api = {
    calls,
    batchAnswer: null,
    batchError: null,
    receipts: [],
    get: jest.fn(async (url) => {
      calls.push(["GET", url]);
      if (url.startsWith("/sync/receipts")) return { data: api.receipts };
      return { data: { enabled, revoked, server_time: SERVER_TIME } };
    }),
    post: jest.fn(async (url, body) => {
      calls.push(["POST", url, body]);
      if (url === "/sync/batch") {
        if (api.batchError) throw api.batchError;
        const answer = api.batchAnswer
          ? api.batchAnswer(body)
          : { server_time: SERVER_TIME, results: body.items.map((i) => ({ local_id: i.local_id, status: "synced", result: { ok: 1 } })) };
        return { data: answer };
      }
      return { data: {} };
    }),
  };
  return api;
}

const httpError = (status, error_code) => Object.assign(new Error("http"), {
  response: { status, data: { detail: { error_code } } } });

async function setup(opts = {}) {
  const store = memoryStore();
  const api = fakeApi(opts);
  let clock = Date.parse("2026-11-09T10:00:00.000Z");
  const revoked = jest.fn();
  const q = createQueue({ store, api, now: () => clock, onRevoked: revoked });
  await q.start(A);
  return { q, store, api, revoked, tick: (ms) => { clock += ms; } };
}

test("a record is stored encrypted, bound to its owner; only routing fields are plain", async () => {
  const { q, store } = await setup();
  const id = await q.enqueue("attendance.mark", { status: "Present", note: "ЕГН-няма" });
  const row = await store.get("queue", id);
  expect(row.status).toBe("saved");
  expect(JSON.stringify(row)).not.toMatch(/Present|ЕГН/);
  expect(row.sealed.iv).toBeTruthy();
  const key = await ownerKey(store, ownerOf("org-a", "u-1"));
  const env = await open(key, ownerOf("org-a", "u-1"), row.sealed);
  expect(env).toMatchObject({ local_id: id, op_type: "attendance.mark", tenant_id: "org-a",
    user_id: "u-1", captured_tz: expect.any(String), payload: { status: "Present" } });
  expect(env.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  // the key cannot be exported, and another owner cannot open the record
  await expect(globalThis.crypto.subtle.exportKey("raw", key)).rejects.toBeTruthy();
  await expect(open(key, ownerOf("org-a", "u-2"), row.sealed)).rejects.toBeTruthy();
});

test("statuses use the FLOW-037 words", () => {
  expect(STATUS).toMatchObject({ saved: "Записано на телефона", pending: "Чака синхронизация",
    syncing: "Синхронизира се", synced: "Синхронизирано", conflict: "Конфликт", error: "Грешка",
    needs_review: "Изисква проверка", late: "Закъснял — чака офиса", waiting_file: "Чака качване на файл" });
});

test("flush sends, marks Синхронизирано and drops the payload from the phone", async () => {
  const { q, store, api } = await setup();
  const id = await q.enqueue("attendance.mark", { status: "Present" });
  await q.flush();
  const row = await store.get("queue", id);
  expect(row.status).toBe("synced");
  expect(row.sealed).toBeUndefined();
  expect(api.calls.filter((c) => c[1] === "/sync/batch")).toHaveLength(1);
  expect(q.state.get().unsent).toBe(0);
});

test("a resend carries the SAME idempotency key", async () => {
  const { q, api, tick } = await setup();
  api.batchError = Object.assign(new Error("Network Error"), { code: "ERR_NETWORK" });
  await q.enqueue("attendance.mark", { status: "Present" });
  await q.flush();
  api.batchError = null;
  tick(backoffMs(1) + 1);
  await q.flush();
  const sent = api.calls.filter((c) => c[1] === "/sync/batch").map((c) => c[2].items[0].idempotency_key);
  expect(sent).toHaveLength(2);
  expect(sent[0]).toBe(sent[1]);
});

test("network errors back off 1s → 5 min and stop after 10 attempts for a human", async () => {
  expect(backoffMs(1)).toBe(1000);
  expect(backoffMs(4)).toBe(8000);
  expect(backoffMs(30)).toBe(300000);
  const { q, store, api, tick } = await setup();
  api.batchError = Object.assign(new Error("Network Error"), { code: "ERR_NETWORK" });
  const id = await q.enqueue("attendance.mark", {});
  for (let i = 0; i < MAX_ATTEMPTS; i += 1) {
    await q.flush();
    tick(5 * 60 * 1000 + 1);
  }
  const row = await store.get("queue", id);
  expect(row.status).toBe("needs_review");
  expect(row.last_error).toBe("RETRY_LIMIT");
  // not before the backoff
  const { q: q2, store: s2, api: api2 } = await setup();
  api2.batchError = Object.assign(new Error("Network Error"), { code: "ERR_NETWORK" });
  const id2 = await q2.enqueue("attendance.mark", {});
  await q2.flush();
  await q2.flush();
  expect((await s2.get("queue", id2)).attempts).toBe(1);
  // while it waits for the network the worker reads „Чака синхронизация“, not „Грешка“
  expect((await s2.get("queue", id2)).status).toBe("pending");
  // „Изпрати сега“ / back online skips the backoff
  api2.batchError = null;
  await q2.flush({ force: true });
  expect((await s2.get("queue", id2)).status).toBe("synced");
});

test("no attempts are spent while the browser says it is offline", async () => {
  const { q, store, api } = await setup();
  const id = await q.enqueue("attendance.mark", {});
  const nav = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: { onLine: false }, configurable: true });
  try {
    await q.flush();
    await q.flush();
  } finally {
    if (nav) Object.defineProperty(globalThis, "navigator", nav); else delete globalThis.navigator;
  }
  expect(api.calls.filter((c) => c[1] === "/sync/batch")).toHaveLength(0);
  expect((await store.get("queue", id)).attempts).toBe(0);
});

test("a validation refusal goes to Изисква проверка at once, without retry", async () => {
  const { q, store, api } = await setup();
  api.batchAnswer = (b) => ({ results: b.items.map((i) => ({ local_id: i.local_id, status: "rejected",
    result: { error_code: "VALIDATION" } })) });
  const id = await q.enqueue("attendance.mark", {});
  await q.flush();
  await q.flush();
  expect((await store.get("queue", id)).status).toBe("needs_review");
  expect(api.calls.filter((c) => c[1] === "/sync/batch")).toHaveLength(1);
});

test("conflict and late answers are shown, not retried", async () => {
  const { q, store, api } = await setup();
  const a = await q.enqueue("attendance.mark", {});
  const b = await q.enqueue("attendance.mark", {});
  api.batchAnswer = (body) => ({ results: [
    { local_id: a, status: "conflict", result: { conflict_id: "c1" } },
    { local_id: b, status: "late", result: { late_id: "l1", reason: "previous_day" } }].filter((r) =>
    body.items.some((i) => i.local_id === r.local_id)) });
  await q.flush();
  expect((await store.get("queue", a)).status).toBe("conflict");
  const late = await store.get("queue", b);
  expect(late.status).toBe("needs_review");
  expect(late.sub).toBe("late");
});

test("another user on the same phone does not see the first user's records", async () => {
  const { q, store, api } = await setup();
  await q.enqueue("attendance.mark", {});
  expect(q.state.get().unsent).toBe(1);
  const q2 = createQueue({ store, api });
  await q2.start(OTHER);
  expect(q2.state.get().unsent).toBe(0);
  expect(q2.state.get().items).toEqual([]);
  // the same user again sees them (R61-5)
  const q3 = createQueue({ store, api });
  await q3.start(A);
  expect(q3.state.get().unsent).toBe(1);
});

test("a blocked device wipes everything local (R61-6)", async () => {
  const { q, store, api, revoked } = await setup();
  await q.enqueue("attendance.mark", {});
  api.batchError = httpError(403, "DEVICE_REVOKED");
  await q.flush();
  expect(revoked).toHaveBeenCalled();
  expect(await store.all("queue")).toEqual([]);
  expect(await store.all("keys")).toEqual([]);
  expect(q.state.get().revoked).toBe(true);
  // also when the status call says so at start
  const store2 = memoryStore();
  const q2 = createQueue({ store: store2, api: fakeApi({ revoked: true }), onRevoked: jest.fn() });
  await store2.put("queue", "x", { owner: "org-a:u-1" });
  expect(await q2.start(A)).toBe(false);
  expect(await store2.all("queue")).toEqual([]);
});

test("money and approvals are never queued (R61-1)", async () => {
  const { q } = await setup();
  for (const op of ["payment.create", "invoice.issue", "daily_report.approve", "iban.change", "role.set"]) {
    expect(isOnlineOnly(op)).toBe(true);
    await expect(q.enqueue(op, {})).rejects.toMatchObject({ code: "ONLINE_ONLY" });
  }
  expect(isOnlineOnly("attendance.mark")).toBe(false);
});

test("the queue keeps records when the flag is switched off and sends nothing", async () => {
  const { q, store, api } = await setup();
  const id = await q.enqueue("attendance.mark", {});
  api.batchError = httpError(403, "OFFLINE_QUEUE_DISABLED");
  await q.flush();
  const row = await store.get("queue", id);
  expect(row.status).toBe("pending");
  expect(row.sealed).toBeTruthy();
});

test("the clock offset is measured against the server and sent with each record", async () => {
  const store = memoryStore();
  const api = fakeApi();
  const q = createQueue({ store, api, now: () => Date.parse("2026-11-09T10:12:00.000Z") });
  await q.start(A);
  expect(q._clockOffset()).toBe(12 * 60 * 1000);
  const id = await q.enqueue("attendance.mark", {});
  const env = await open(await ownerKey(store, ownerOf("org-a", "u-1")), ownerOf("org-a", "u-1"),
    (await store.get("queue", id)).sealed);
  expect(env.device_clock_offset_ms).toBe(12 * 60 * 1000);
});

test("sha256 of a file is computed on the phone", async () => {
  const bytes = new TextEncoder().encode("abc");
  expect(await sha256Hex(bytes.buffer)).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  const key = await globalThis.crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  const sealed = await seal(key, "o", { a: 1 });
  expect(await open(key, "o", sealed)).toEqual({ a: 1 });
});


test("the office's decisions come back to the phone through the receipts (R61-3)", async () => {
  const { q, store, api } = await setup();
  const late = await q.enqueue("attendance.mark", {});
  const conf = await q.enqueue("attendance.mark", {});
  api.batchAnswer = (body) => ({ results: body.items.map((i) => (i.local_id === late
    ? { local_id: late, status: "late", result: { late_id: "l1" } }
    : { local_id: conf, status: "conflict", result: { conflict_id: "c1" } })) });
  await q.flush();
  expect((await store.get("queue", late)).sub).toBe("late");
  // the office confirms the late record and keeps its own version in the conflict
  api.receipts = [
    { local_id: late, status: "synced", result: { entity_id: "att-1" } },
    { local_id: conf, status: "rejected", result: { error_code: "CONFLICT_KEPT_OFFICE" } },
  ];
  expect(await q.refreshReceipts()).toBe(2);
  const l = await store.get("queue", late);
  expect(l.status).toBe("synced");
  expect(l.sealed).toBeUndefined();
  const c = await store.get("queue", conf);
  expect(c.status).toBe("needs_review");
  expect(c.last_error).toBe("CONFLICT_KEPT_OFFICE");
});

test("a photo keeps its original sealed on the phone while it waits for the file registry", async () => {
  const { q, store, api } = await setup();
  const blob = new (require("buffer").Blob)([new Uint8Array([1, 2, 3, 4])], { type: "image/jpeg" });
  const id = await q.enqueue("media.upload", { sha256: "ab".repeat(32), size: 4, mime: "image/jpeg" }, { file: blob });
  api.batchAnswer = (body) => ({ results: body.items.map((i) => ({ local_id: i.local_id, status: "waiting_file",
    result: { file_registry: "unavailable" } })) });
  await q.flush();
  const row = await store.get("queue", id);
  expect(row.status).toBe("waiting_file");
  expect(row.file_sealed).toBeTruthy();
  expect(JSON.stringify(row.file_sealed)).not.toMatch(/AQIDBA/); // base64 of 1,2,3,4 is not in clear
  // the bytes are not sent to the server in this build
  const sent = api.calls.find((c) => c[1] === "/sync/batch")[2];
  expect(JSON.stringify(sent)).not.toMatch(/b64/);
  // and they open again with the owner's key
  const f = await open(await ownerKey(store, ownerOf("org-a", "u-1")), ownerOf("org-a", "u-1"), row.file_sealed);
  expect(f.b64).toBe("AQIDBA==");
  expect(q.state.get().unsent).toBe(1); // still on the phone
});

test("records are sent in the order they were captured, whatever their ids", async () => {
  // IndexedDB returns rows by KEY order — the memory store is made to do the same here
  const mem = memoryStore();
  const store = { ...mem, all: async (st) => (await mem.all(st)).sort(([a], [b]) => (a < b ? -1 : 1)) };
  const api = fakeApi({});
  const ids = ["ffffffff-0000-4000-8000-000000000001", "eeeeeeee-0000-4000-8000-000000000002",
    "11111111-0000-4000-8000-000000000003", "dddddddd-0000-4000-8000-000000000004"];
  let n = 0;
  const q = createQueue({ store, api, now: () => Date.parse("2026-11-09T10:00:00.000Z"), newId: () => ids[n++] });
  await q.start(A);
  api.calls.length = 0;
  await q.enqueue("attendance.mark", { status: "Present" });       // first, same millisecond
  await q.enqueue("technician.daily_report", { entries: [] });     // depends on the mark
  await q.flush();
  const items = api.calls.find((c) => c[1] === "/sync/batch")[2].items;
  expect(items.map((i) => i.op_type)).toEqual(["attendance.mark", "technician.daily_report"]);
});
