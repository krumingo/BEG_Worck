/**
 * LIVE-OPS-01 / TASK 5B — Заявки за материали screen.
 *
 * Holds the screen to its promises: named commands only, an Idempotency-Key on
 * every write (the SAME key on a retry), buttons that follow the server's
 * permission answer with a visible reason, server-derived quantities, a visible
 * "чака мапване", phone and desktop layouts, and no warehouse/asset control.
 */
import React from "react";
import { render, screen, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// react-router-dom 7 cannot be loaded by jest 27 (see MasterDataRoute.test.js);
// the page only uses three hooks, so they are stood in for here.
let mockParams = {};
let mockSearch = new URLSearchParams();
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({
  __esModule: true,
  useParams: () => mockParams,
  useNavigate: () => mockNavigate,
  useSearchParams: () => [mockSearch, jest.fn()],
}), { virtual: true });

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), request: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));

import API from "@/lib/api";
import MaterialRequestsPage from "@/pages/MaterialRequestsPage";

const LINE = (over = {}) => ({
  id: "L1", item_id: "IT-1", mapping_status: "confirmed", material_name: "Лепило Baumit",
  qty_requested: 10, qty_approved: 10, qty_cancelled: 0, unit: "торба",
  facts: { accepted_qty: 3, reserved_active_qty: 0, issued_qty: 0, legacy_fulfilled_qty: 0 },
  remaining_qty: 7, over_qty: 0, ...over,
});
const REQ = (over = {}) => ({
  id: "R1", request_number: "MR-0001", project_id: "P1", project_code: "XO", project_name: "XOPark",
  request_state: "approved", legacy_status: null, needed_date: "2026-11-01", priority: "normal",
  destination_type: "project", version: 3, lines: [LINE()], unmapped_lines: 0,
  remaining_qty_total: 7, has_partial_facts: true, ...over,
});
const ALLOW = (codes) => Object.fromEntries(["edit_draft", "submit", "approve", "reject", "cancel"]
  .map((c) => [c, codes[c] || { allowed: false, reason: "INVALID_STATE" }]));

let state;
function setupApi({ requests = [REQ()], view = null, writes = true } = {}) {
  state = { requests, view, calls: [] };
  API.get.mockImplementation((url) => {
    state.calls.push(["GET", url]);
    if (url === "/material-requests") return Promise.resolve({ data: state.requests });
    if (url === "/material-requests/write-status") {
      return Promise.resolve({ data: { writes_enabled: writes, message: writes ? null : "Записът на заявки е изключен." } });
    }
    if (url === "/projects") return Promise.resolve({ data: [{ id: "P1", code: "XO", name: "XOPark" }] });
    if (url === "/material-requests/item-options") return Promise.resolve({ data: { items: [{ id: "IT-1", display_name: "Лепило Baumit" }] } });
    if (url === "/warehouses") return Promise.resolve({ data: [{ id: "W1", name: "Централен склад", code: "C1" }] });
    if (/\/material-requests\/[^/]+\/view$/.test(url)) return Promise.resolve({ data: state.view });
    return Promise.reject(new Error("unexpected GET " + url));
  });
  API.request.mockImplementation((cfg) => {
    state.calls.push([cfg.method.toUpperCase(), cfg.url, cfg.data, cfg.headers]);
    return Promise.resolve({ data: { replayed: false, result: {}, request: state.view?.request || REQ() } });
  });
}

function setWidth(w) {
  window.innerWidth = w;
}

async function renderAt(path = "/material-requests") {
  const [pathname, query] = path.split("?");
  const m = pathname.match(/^\/material-requests\/([^/]+)$/);
  mockParams = m ? { requestId: m[1] } : {};
  mockSearch = new URLSearchParams(query || "");
  render(<MaterialRequestsPage />);
  await waitFor(() => expect(screen.queryByTestId("loading")).not.toBeInTheDocument());
}

const writes = () => state.calls.filter((c) => c[0] !== "GET");

beforeEach(() => {
  jest.clearAllMocks();
  mockParams = {};
  mockSearch = new URLSearchParams();
  setWidth(1280);
});

// ─────────────────────────────────────────────────────────── create / edit / submit
test("phone: create a draft through the named command with an Idempotency-Key", async () => {
  setWidth(390);
  setupApi({ requests: [] });
  await renderAt();
  expect(screen.getByTestId("material-requests-page")).toHaveAttribute("data-layout", "phone");
  await userEvent.click(screen.getByTestId("new-request"));
  expect(screen.getByTestId("request-form")).toHaveAttribute("data-layout", "phone");
  await userEvent.selectOptions(screen.getByTestId("form-project"), "P1");
  await userEvent.type(screen.getByTestId("form-needed-date"), "2026-11-01");
  await userEvent.type(screen.getByTestId("line-name-0"), "Лепило за фасада");
  await userEvent.type(screen.getByTestId("line-qty-0"), "40");
  expect(within(screen.getByTestId("line-editor-0")).getByTestId("unmapped-badge")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("form-save"));

  await waitFor(() => expect(writes()).toHaveLength(1));
  const [method, url, body, headers] = writes()[0];
  expect([method, url]).toEqual(["POST", "/material-requests"]);
  expect(headers["Idempotency-Key"]).toMatch(/^mr-/);
  expect(headers["X-Client-Channel"]).toBe("phone");
  expect(body.project_id).toBe("P1");
  expect(body.lines).toEqual([{ material_name: "Лепило за фасада", qty_requested: 40, unit: "бр" }]);
  for (const forbidden of ["status", "request_state", "approved_by", "org_id", "tenant_id", "remaining_qty"]) {
    expect(body).not.toHaveProperty(forbidden);
  }
});

test("a line mapped to a Master material sends item_id; free text stays pending", async () => {
  setupApi({ requests: [] });
  await renderAt();
  await userEvent.click(screen.getByTestId("new-request"));
  await userEvent.selectOptions(screen.getByTestId("form-project"), "P1");
  await userEvent.type(screen.getByTestId("line-search-0"), "лепило");
  await userEvent.click(screen.getByTestId("line-search-btn-0"));
  await userEvent.click(await screen.findByTestId("line-option-IT-1"));
  await userEvent.type(screen.getByTestId("line-qty-0"), "5");
  await userEvent.click(screen.getByTestId("form-save"));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][2].lines[0]).toMatchObject({ item_id: "IT-1", qty_requested: 5 });
});

test("edit a draft (expected_version, stable line ids) and submit it", async () => {
  const draft = REQ({ request_state: "draft", version: 1, lines: [LINE({ qty_approved: null, facts: { accepted_qty: 0 }, remaining_qty: 10 })], has_partial_facts: false });
  setupApi({ requests: [draft], view: { request: draft, allowed_actions: ALLOW({
    edit_draft: { allowed: true }, submit: { allowed: true }, cancel: { allowed: true } }),
    history: { status: "ok", events: [] } } });
  await renderAt("/material-requests/R1");
  await userEvent.click(await screen.findByTestId("action-edit_draft"));
  const qty = screen.getByTestId("line-qty-0");
  await userEvent.clear(qty);
  await userEvent.type(qty, "12");
  await userEvent.click(screen.getByTestId("form-save"));
  await waitFor(() => expect(writes()).toHaveLength(1));
  const [m, url, body] = writes()[0];
  expect([m, url]).toEqual(["PATCH", "/material-requests/R1/draft"]);
  expect(body.expected_version).toBe(1);
  expect(body.lines[0]).toMatchObject({ id: "L1", qty_requested: 12, item_id: "IT-1" });
  expect(body).not.toHaveProperty("project_id");

  await userEvent.click(await screen.findByTestId("action-submit"));
  await waitFor(() => expect(writes()).toHaveLength(2));
  expect(writes()[1].slice(0, 2)).toEqual(["POST", "/material-requests/R1/submit"]);
  expect(writes()[1][3]["Idempotency-Key"]).not.toBe(writes()[0][3]["Idempotency-Key"]);
});

// ─────────────────────────────────────────────────────────── approve / reject
test("authorized approve and reject go through their commands", async () => {
  const sub = REQ({ request_state: "submitted", lines: [LINE({ qty_approved: null, facts: { accepted_qty: 0 }, remaining_qty: 10 })] });
  setupApi({ requests: [sub], view: { request: sub, allowed_actions: ALLOW({
    approve: { allowed: true }, reject: { allowed: true }, cancel: { allowed: true } }),
    history: { status: "ok", events: [] } } });
  await renderAt("/material-requests/R1");
  await userEvent.click(await screen.findByTestId("action-approve"));
  const q = screen.getByTestId("approve-qty-L1");
  await userEvent.clear(q);
  await userEvent.type(q, "8");
  await userEvent.click(screen.getByTestId("approve-confirm"));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0].slice(0, 3)).toEqual(["POST", "/material-requests/R1/approve",
    { lines: [{ line_id: "L1", qty_approved: 8 }] }]);

  await userEvent.click(await screen.findByTestId("action-reject"));
  expect(screen.getByTestId("reason-confirm")).toBeDisabled();          // reason is mandatory
  await userEvent.type(screen.getByTestId("reason-input"), "няма бюджет");
  await userEvent.click(screen.getByTestId("reason-confirm"));
  await waitFor(() => expect(writes()).toHaveLength(2));
  expect(writes()[1].slice(0, 3)).toEqual(["POST", "/material-requests/R1/reject", { reason: "няма бюджет" }]);
});

// ─────────────────────────────────────────────────────────── denial UX
test("denied actions are visible with the Permission Service reason", async () => {
  const sub = REQ({ request_state: "submitted" });
  setupApi({ requests: [sub], view: { request: sub, allowed_actions: ALLOW({
    approve: { allowed: false, reason: "SCOPE_MISMATCH" }, reject: { allowed: false, reason: "SCOPE_MISMATCH" },
    cancel: { allowed: false, reason: "ACTION_NOT_ALLOWED" } }), history: { status: "ok", events: [] } } });
  await renderAt("/material-requests/R1");
  expect(await screen.findByTestId("action-approve")).toBeDisabled();
  expect(screen.getByTestId("denied-approve")).toHaveTextContent("Правата ви са за друг обект.");
  expect(screen.getByTestId("denied-cancel")).toHaveTextContent("Ролята ви в обекта не позволява");
  expect(screen.queryByTestId("action-submit")).not.toBeInTheDocument();   // not valid in this state
});

test("a server refusal is shown with its reason, not swallowed", async () => {
  const sub = REQ({ request_state: "submitted" });
  setupApi({ requests: [sub], view: { request: sub, allowed_actions: ALLOW({ approve: { allowed: true } }),
    history: { status: "ok", events: [] } } });
  API.request.mockRejectedValueOnce({ response: { status: 403, data: { detail: {
    error_code: "PERMISSION_DENIED", reason: "ASSIGNMENT_REVOKED" } } } });
  await renderAt("/material-requests/R1");
  await userEvent.click(await screen.findByTestId("action-approve"));
  await userEvent.click(screen.getByTestId("approve-confirm"));
  expect(await screen.findByTestId("action-error")).toHaveTextContent("Отказано: Правата ви са оттеглени.");
  expect(screen.queryByTestId("action-retry")).not.toBeInTheDocument();     // a definitive answer
});

test("writes disabled outside enforce: create is off and the reason is shown", async () => {
  setupApi({ writes: false });
  await renderAt();
  expect(screen.getByTestId("new-request")).toBeDisabled();
  expect(screen.getByTestId("writes-disabled")).toHaveTextContent("изключен");
});

// ─────────────────────────────────────────────────────────── retry safety
test("a retry after a lost response reuses the same Idempotency-Key", async () => {
  const sub = REQ({ request_state: "submitted" });
  setupApi({ requests: [sub], view: { request: sub, allowed_actions: ALLOW({ reject: { allowed: true } }),
    history: { status: "ok", events: [] } } });
  API.request.mockRejectedValueOnce(new Error("Network Error"));
  await renderAt("/material-requests/R1");
  await userEvent.click(await screen.findByTestId("action-reject"));
  await userEvent.type(screen.getByTestId("reason-input"), "x");
  await userEvent.click(screen.getByTestId("reason-confirm"));
  await userEvent.click(await screen.findByTestId("action-retry"));
  await waitFor(() => expect(API.request).toHaveBeenCalledTimes(2));
  const [first, second] = API.request.mock.calls.map((c) => c[0]);
  expect(second.headers["Idempotency-Key"]).toBe(first.headers["Idempotency-Key"]);
  expect(second.url).toBe(first.url);
  expect(second.data).toEqual(first.data);
});

// ─────────────────────────────────────────────────────────── quantities & mapping
test("desktop: partial facts and remaining are shown per line, from the server", async () => {
  const r = REQ({ lines: [LINE(), LINE({ id: "L2", material_name: "Мрежа", qty_requested: 6, qty_approved: 6,
    qty_cancelled: 2, facts: { accepted_qty: 0 }, remaining_qty: 4 })] });
  setupApi({ requests: [r], view: { request: r, allowed_actions: ALLOW({ cancel: { allowed: true } }),
    history: { status: "ok", events: [{ event_id: "e1", action: "material_request.approve", result: "success", actor_id: "u-sm" }] } } });
  await renderAt("/material-requests/R1");
  const detail = await screen.findByTestId("request-detail");
  expect(detail).toHaveAttribute("data-layout", "desktop");
  expect(screen.getByTestId("partial-info")).toBeInTheDocument();
  expect(screen.getByTestId("remaining-L1")).toHaveTextContent("7");
  expect(screen.getByTestId("remaining-L2")).toHaveTextContent("4");
  expect(within(screen.getByTestId("dline-L2")).getByText("2")).toBeInTheDocument();   // cancelled
  expect(screen.getByTestId("facts-source")).toHaveTextContent("складовия регистър (само четене)");
  expect(screen.getAllByTestId("history-event")).toHaveLength(1);
  expect(screen.getByTestId("filters")).toBeInTheDocument();
  expect(screen.getByTestId("request-table")).toBeInTheDocument();
});

test("unmapped lines are marked and approval context warns", async () => {
  const r = REQ({ request_state: "submitted", unmapped_lines: 1, lines: [LINE({ item_id: null,
    mapping_status: "pending_mapping", material_name: "Баумит леп. бяло 25", qty_approved: null })] });
  setupApi({ requests: [r], view: { request: r, allowed_actions: ALLOW({ approve: { allowed: true } }),
    history: { status: "ok", events: [] } } });
  await renderAt("/material-requests/R1");
  expect(await screen.findByTestId("unmapped-warning")).toHaveTextContent("чакат мапване");
  expect(within(screen.getByTestId("dline-L1")).getByTestId("unmapped-badge")).toBeInTheDocument();
});

test("phone: list renders as cards and the detail is full screen", async () => {
  setWidth(375);
  const r = REQ();
  setupApi({ requests: [r], view: { request: r, allowed_actions: ALLOW({}), history: { status: "unavailable", message: "x" } } });
  await renderAt("/material-requests/R1");
  expect(screen.getByTestId("request-cards")).toBeInTheDocument();
  expect(screen.queryByTestId("request-table")).not.toBeInTheDocument();
  expect(screen.queryByTestId("filters")).not.toBeInTheDocument();
  expect(await screen.findByTestId("request-detail")).toHaveAttribute("data-layout", "phone");
  expect(screen.getByTestId("remaining-L1")).toHaveTextContent("7");
});

test("the offer button path opens a prefilled new request (no from-offer writer)", async () => {
  setupApi({ requests: [] });
  await renderAt("/material-requests?new=1&project=P1");
  expect(screen.getByTestId("request-form")).toBeInTheDocument();
  expect(screen.getByTestId("form-project")).toHaveValue("P1");
  expect(writes()).toHaveLength(0);
});

test("a legacy stored status is shown as unverified, not as a control state", async () => {
  setupApi({ requests: [REQ({ request_state: null, legacy_status: "fulfilled" })] });
  await renderAt();
  expect(screen.getByTestId("legacy-status")).toHaveTextContent("Стар статус: fulfilled (непотвърден)");
});

// ─────────────────────────────────────────────────────────── scope boundary
test("no warehouse, asset, QR or migration control and no raw status write", async () => {
  const r = REQ();
  setupApi({ requests: [r], view: { request: r, allowed_actions: ALLOW({ cancel: { allowed: true } }),
    history: { status: "ok", events: [] } } });
  await renderAt("/material-requests/R1");
  await screen.findByTestId("request-detail");
  const text = document.body.textContent;
  for (const word of ["Изпиши", "Резервирай", "Приеми в склад", "Върни", "Карантина", "QR", "Миграция",
    "Отпиши", "Предай", "Ремонт"]) {
    expect(text).not.toContain(word);
  }
  const buttons = screen.getAllByRole("button").map((b) => b.textContent);
  expect(buttons.join("|")).not.toMatch(/статус/i);
  // the session never sends PUT/DELETE or a tenant
  await act(async () => {});
  for (const c of state.calls) {
    expect(["GET", "POST", "PATCH"]).toContain(c[0]);
    if (c[2]) expect(JSON.stringify(c[2])).not.toMatch(/tenant_id|org_id/);
  }
});
