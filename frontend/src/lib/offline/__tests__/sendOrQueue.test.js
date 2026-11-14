// PWA-02 — sendOrQueue: online goes straight through; a connection failure (queue on) keeps the
// record on the phone; a server refusal is never queued.
const mockEnqueue = jest.fn(async () => "local-1");
let mockEnabled = true;
jest.mock("@/lib/offline/queue", () => {
  const actual = jest.requireActual("@/lib/offline/queue");
  return { ...actual, createQueue: () => ({ enqueue: (...a) => mockEnqueue(...a), isEnabled: () => mockEnabled, state: actual.createQueue({ store: { all: async () => [] } }).state }) };
});
jest.mock("@/lib/api", () => ({ __esModule: true, default: {} }));
jest.mock("@/lib/pwa/clearLocalData", () => ({ __esModule: true, clearTenantLocalData: async () => ({}) }));

import { sendOrQueue } from "@/lib/offline";

beforeEach(() => { mockEnqueue.mockClear(); mockEnabled = true; Object.defineProperty(navigator, "onLine", { value: true, configurable: true }); });

test("online: sent, not queued", async () => {
  const r = await sendOrQueue({ opType: "attendance.mark", payload: {}, send: async () => ({ data: 1 }) });
  expect(r).toEqual({ queued: false, response: { data: 1 } });
  expect(mockEnqueue).not.toHaveBeenCalled();
});

test("no connection: queued on the phone", async () => {
  const r = await sendOrQueue({ opType: "attendance.mark", payload: { s: 1 },
    send: async () => { throw Object.assign(new Error("Network Error"), { code: "ERR_NETWORK" }); } });
  expect(r.queued).toBe(true);
  expect(mockEnqueue).toHaveBeenCalledWith("attendance.mark", { s: 1 }, { projectId: null, file: null });
});

test("browser offline: queued without trying", async () => {
  Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
  const send = jest.fn();
  expect((await sendOrQueue({ opType: "attendance.mark", payload: {}, send })).queued).toBe(true);
  expect(send).not.toHaveBeenCalled();
});

test("a server refusal is shown, never queued", async () => {
  const err = Object.assign(new Error("400"), { response: { status: 400 } });
  await expect(sendOrQueue({ opType: "attendance.mark", payload: {}, send: async () => { throw err; } })).rejects.toBe(err);
  expect(mockEnqueue).not.toHaveBeenCalled();
});

test("queue switched off: the error goes to the form as before", async () => {
  mockEnabled = false;
  const err = Object.assign(new Error("Network Error"), { code: "ERR_NETWORK" });
  await expect(sendOrQueue({ opType: "attendance.mark", payload: {}, send: async () => { throw err; } })).rejects.toBe(err);
  expect(mockEnqueue).not.toHaveBeenCalled();
});
