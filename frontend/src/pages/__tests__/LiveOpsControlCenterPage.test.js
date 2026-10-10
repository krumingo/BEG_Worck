/**
 * LIVE-OPS-01 / TASK 5A — the read-only Control Center screen.
 *
 * What these tests hold onto:
 *
 *   * the screen renders every section from one projection, and every state it
 *     can be in is reachable and honest: loading, error (with retry), forbidden,
 *     per-section error, empty;
 *   * a warehouse is labelled by its human-readable name; the code is secondary
 *     and never the label;
 *   * untrusted stock totals are marked as such, with their reasons, and every
 *     loaded card shows its source and freshness; an old snapshot is flagged;
 *   * an accepted custodian and a pending handover appear in separate columns;
 *   * the activity preview is canonical or explicitly "not available";
 *   * the page is read-only: during a whole session it issues GET requests to
 *     the projection only — never POST/PUT/PATCH/DELETE — and renders no
 *     approve/reject/issue/accept/write-off control.
 */
import React from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// react-router-dom 7 declares a "main" file it does not ship and jest 27 does
// not read "exports" (see MasterDataRoute.test.js). The page only renders
// <Link>; this stand-in is a plain anchor that keeps the target visible.
jest.mock("react-router-dom", () => ({
  __esModule: true,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}), { virtual: true });

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));

import API from "@/lib/api";
import LiveOpsControlCenterPage, { STALE_AFTER_MS } from "@/pages/LiveOpsControlCenterPage";

const NOW_ISO = "2026-10-10T12:00:00+00:00";

function projection(overrides = {}) {
  return {
    read_only: true,
    generated_at: NOW_ISO,
    requests: {
      status: "ok", source: "material_requests (legacy заявки, пълно четене)",
      generated_at: NOW_ISO, last_change_at: NOW_ISO, total: 3,
      counts: { open: 2, pending: 1, overdue: 1, open_without_needed_date: 0, fulfilled_legacy: 1, by_status: {} },
      partial: { derivable: false, value: null, reason: "Частичното изпълнение не се записва." },
      overdue_rule: "Отворена заявка с „нужна до“ преди днес.",
      items: [
        { id: "r1", request_number: "MR-0001", status: "submitted", status_label: "Подадена — чака решение",
          project_name: "Обект Витоша", needed_date: "2026-10-01", overdue: true, lines_count: 2, link: "/procurement" },
      ],
      items_total: 1, items_truncated: false, link: "/procurement",
    },
    warehouses: {
      status: "ok", source: "warehouse_transactions (legacy регистър, пълно четене без лимит)",
      generated_at: NOW_ISO, last_movement_at: NOW_ISO, movement_count: 1205, complete: true,
      unprojectable_movements: 0,
      trust: "untrusted",
      trust_reasons: ["Материалите в склада се разпознават по свободен текст (име|мярка), не по Master артикул."],
      warehouses: [
        { id: "w1", label: "Централен склад Хаджи Димитър", name: "Централен склад Хаджи Димитър", code: "CS-01",
          type: "central", type_label: "Централен склад", active: true, is_legacy_main: false,
          stock_positions: 1, negative_positions: 0, stock_value_unverified: 120,
          items: [{ material_name: "Цимент", unit: "торба", qty: 1200, value_unverified: 120 }],
          items_total: 1, items_truncated: false },
        { id: "w2", label: "Склад без име", name: "", code: "ONLYCODE", type: "main",
          type_label: "Основен склад (legacy „main“)", active: true, is_legacy_main: true,
          stock_positions: 0, negative_positions: 1, stock_value_unverified: 0, items: [], items_total: 0 },
      ],
      legacy_main_count: 1, diagnostics: {}, link: "/data/warehouses",
    },
    assets: {
      status: "ok", source: "asset_units + asset_custody + asset_repairs (пълно четене)",
      generated_at: NOW_ISO, total: 3,
      counts: { in_warehouse: 0, on_project: 1, with_person: 1, in_repair: 1, written_off: 0, unknown: 0 },
      pending_handovers: 1, accepted_custody: 1, open_repairs: 1, unresolved_location: 0, multiple_active_custody: 0,
      overdue: { supported: false, value: null, reason: "Текущите данни нямат срок за връщане." },
      legacy_handover_note: "При текущия legacy поток създаването на предаване затваря предишния отговорник.",
      items: [
        { id: "u-pen", name: "Перфоратор", qr_id: "QR2", indicator: "on_project", indicator_label: "На обект",
          location: { type: "project", type_label: "Обект", name: "Обект Витоша", resolved: true },
          accepted_custodian: null,
          pending_handover: { to_name: "Иван Петров", from_name: "Мария", since: "2026-10-09" },
          repair: null, link: "/assets/units/u-pen" },
        { id: "u-acc", name: "Бормашина", qr_id: "QR1", indicator: "with_person", indicator_label: "При човек",
          location: { type: "employee", type_label: "Служител", name: "Георги Георгиев", resolved: true },
          accepted_custodian: { name: "Георги Георгиев", since: "2026-10-01" },
          pending_handover: null, repair: null, link: "/assets/units/u-acc" },
      ],
      items_total: 2, items_truncated: false, link: "/assets/units",
    },
    audit: {
      status: "unavailable", source: "audit_events (каноничен AuditEvent, FLOW-040)", generated_at: NOW_ISO,
      legacy_audit_used: false, events: [],
      message: "Каноничен AuditEvent не е наличен за записите в склад, заявки и активи.",
    },
    integrity: [
      { code: "LEGACY_MAIN_WAREHOUSE", severity: "warning", title: "Открит legacy склад тип „main“",
        detail: "Каноничният тип е „central“.", count: 1, link: "/data/warehouses" },
      { code: "STOCK_UNRECONCILED", severity: "critical", title: "Наличностите не са равнени",
        detail: "Има партиди, които не са равнени.", count: 3, link: "/inventory" },
      { code: "PENDING_CUSTODY", severity: "warning", title: "Предавания чакат приемане",
        detail: "Отговорността не е приета.", count: 1, link: "/assets/units" },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(<LiveOpsControlCenterPage />);
}

beforeEach(() => {
  jest.clearAllMocks();
  API.get.mockResolvedValue({ data: projection() });
});

afterEach(() => {
  jest.useRealTimers();
});

test("renders all sections from the single read projection", async () => {
  renderPage();
  expect(screen.getByTestId("lo-loading")).toBeInTheDocument();
  expect(await screen.findByTestId("live-ops-control-center")).toBeInTheDocument();
  expect(API.get).toHaveBeenCalledWith("/live-ops/control-center");
  for (const id of ["lo-requests", "lo-warehouses", "lo-assets", "lo-integrity", "lo-asset-indicators", "lo-audit"]) {
    expect(screen.getByTestId(id)).toBeInTheDocument();
  }
  expect(screen.getByTestId("lo-read-only-badge")).toHaveTextContent("Само за четене");
  expect(screen.getByTestId("lo-kpi-overdue")).toHaveTextContent("1");
  expect(screen.getByTestId("lo-request-r1")).toHaveTextContent("Просрочена");
  expect(screen.getByTestId("lo-requests")).toHaveTextContent("няма данни");
});

test("warehouses are labelled by name; the code is secondary and never the label", async () => {
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  expect(screen.getByTestId("lo-warehouse-name-w1")).toHaveTextContent("Централен склад Хаджи Димитър");
  expect(screen.getByTestId("lo-warehouse-code-w1")).toHaveTextContent("CS-01");
  expect(screen.getByTestId("lo-warehouse-name-w1")).not.toHaveTextContent("CS-01");
  // A nameless warehouse is not presented by its code.
  expect(screen.getByTestId("lo-warehouse-name-w2")).toHaveTextContent("Склад без име");
  expect(screen.getByTestId("lo-warehouse-name-w2")).not.toHaveTextContent("ONLYCODE");
  expect(within(screen.getByTestId("lo-warehouse-w2")).getByText("legacy „main“")).toBeInTheDocument();
  // Expanding a warehouse is a local view toggle, not a request.
  await userEvent.click(screen.getByTestId("lo-warehouse-toggle-w1"));
  expect(screen.getByTestId("lo-warehouse-items-w1")).toHaveTextContent("Цимент");
  expect(API.get).toHaveBeenCalledTimes(1);
});

test("untrusted stock is marked, and every section shows source and freshness", async () => {
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  expect(screen.getByTestId("lo-stock-untrusted")).toHaveTextContent("непроверени");
  expect(screen.getByTestId("lo-stock-untrusted")).toHaveTextContent("свободен текст");
  for (const id of ["lo-requests-source", "lo-warehouses-source", "lo-assets-source", "lo-audit-source"]) {
    expect(screen.getByTestId(id)).toHaveTextContent("Източник:");
    expect(screen.getByTestId(id)).toHaveTextContent("Изчислено:");
  }
  expect(screen.getByTestId("lo-warehouses-source")).toHaveTextContent("1205");
  expect(screen.getByTestId("lo-warning-STOCK_UNRECONCILED")).toHaveTextContent("не са равнени");
  expect(screen.getByTestId("lo-warning-LEGACY_MAIN_WAREHOUSE")).toBeInTheDocument();
  expect(screen.getByTestId("lo-freshness")).not.toHaveTextContent("Остарели");
});

test("an old snapshot is flagged as stale", async () => {
  jest.useFakeTimers();
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  act(() => { jest.advanceTimersByTime(STALE_AFTER_MS + 31000); });
  expect(screen.getByTestId("lo-freshness")).toHaveTextContent("Остарели данни");
});

test("a pending handover is shown apart from the accepted custodian", async () => {
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  expect(screen.getByTestId("lo-asset-pending-u-pen")).toHaveTextContent("Чака приемане: Иван Петров");
  expect(screen.getByTestId("lo-asset-accepted-u-pen")).toHaveTextContent("няма потвърден");
  expect(screen.getByTestId("lo-asset-accepted-u-pen")).not.toHaveTextContent("Иван Петров");
  expect(screen.getByTestId("lo-asset-accepted-u-acc")).toHaveTextContent("Георги Георгиев");
  expect(screen.getByTestId("lo-asset-pending-u-acc")).toHaveTextContent("—");
  expect(screen.getByTestId("lo-legacy-handover-note")).toBeInTheDocument();
  expect(screen.getByTestId("lo-indicator-overdue")).toHaveTextContent("няма данни");
  expect(screen.getByTestId("lo-asset-u-pen")).toHaveTextContent("Обект Витоша");
});

test("audit preview says canonical audit is unavailable instead of showing legacy audit", async () => {
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  expect(screen.getByTestId("lo-audit-unavailable")).toHaveTextContent("Каноничен AuditEvent не е наличен");
});

test("canonical events are listed when available", async () => {
  API.get.mockResolvedValue({ data: projection({
    audit: { status: "available", source: "audit_events", generated_at: NOW_ISO, legacy_audit_used: false,
      events: [{ event_id: "e1", action: "asset_unit.viewed", entity_type: "asset_unit", occurred_at: NOW_ISO }] },
  }) });
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  expect(screen.getByTestId("lo-audit-events")).toHaveTextContent("asset_unit.viewed");
});

test("load failure is an explicit error with retry, not stale data", async () => {
  API.get.mockRejectedValueOnce({ response: { status: 500 } });
  renderPage();
  expect(await screen.findByTestId("lo-error")).toHaveTextContent("не можа да бъде зареден");
  expect(screen.queryByTestId("live-ops-control-center")).not.toBeInTheDocument();
  await userEvent.click(screen.getByTestId("lo-retry"));
  expect(await screen.findByTestId("live-ops-control-center")).toBeInTheDocument();
});

test("forbidden is explained", async () => {
  API.get.mockRejectedValueOnce({ response: { status: 403 } });
  renderPage();
  expect(await screen.findByTestId("lo-error")).toHaveTextContent("Нямате права");
});

test("a failing section is reported and empty sections say so", async () => {
  API.get.mockResolvedValue({ data: projection({
    assets: { status: "error", message: "Секцията не можа да бъде заредена." },
    requests: { ...projection().requests, items: [], items_total: 0 },
    warehouses: { ...projection().warehouses, warehouses: [] },
  }) });
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  expect(screen.getByTestId("section-error-assets")).toHaveTextContent("не е заредена");
  expect(screen.getByTestId("lo-kpi-handover")).toHaveTextContent("—");
  expect(screen.getByTestId("lo-requests-empty")).toBeInTheDocument();
  expect(screen.getByTestId("lo-warehouses-empty")).toBeInTheDocument();
});

test("read-only: only GETs the projection and renders no mutation control", async () => {
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  await userEvent.click(screen.getByTestId("lo-refresh"));
  await waitFor(() => expect(API.get).toHaveBeenCalledTimes(2));
  for (const call of API.get.mock.calls) expect(call[0]).toBe("/live-ops/control-center");
  for (const m of ["post", "put", "patch", "delete"]) expect(API[m]).not.toHaveBeenCalled();

  const forbidden = /одобр|отхвърл|изпиши|изписване|резервир|приеми|откажи|предай|бракувай|отпиши|заприходи|изпрати за ремонт/i;
  for (const btn of screen.getAllByRole("button")) {
    expect(btn.textContent).not.toMatch(forbidden);
  }
  expect(document.querySelectorAll("form, input, select, textarea")).toHaveLength(0);
  // Every link points into an existing screen.
  for (const a of document.querySelectorAll("a")) {
    expect(a.getAttribute("href")).toMatch(/^\/(procurement|data\/warehouses|data\/master-data|inventory|assets\/units)/);
  }
});

test("direct URL /live-ops is behind AdminRoute and the page source only reads", () => {
  const fs = require("fs");
  const path = require("path");
  const app = fs.readFileSync(path.join(__dirname, "..", "..", "App.js"), "utf8");
  expect(app).toMatch(
    /<Route path="\/live-ops" element={<AdminRoute><LiveOpsControlCenterPage \/><\/AdminRoute>} \/>/);
  const page = fs.readFileSync(path.join(__dirname, "..", "LiveOpsControlCenterPage.js"), "utf8");
  expect(page).not.toMatch(/API\.(post|put|patch|delete)\b/);
  expect(page.match(/API\.get\(/g)).toHaveLength(1);
  expect(page).toContain('API.get("/live-ops/control-center")');
});

test("every derived card shows source and freshness (KPIs, indicators, integrity)", async () => {
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  for (const id of ["lo-kpi-source", "lo-asset-indicators-source", "lo-integrity-source"]) {
    expect(screen.getByTestId(id)).toHaveTextContent("Източник:");
    expect(screen.getByTestId(id)).toHaveTextContent("Изчислено:");
  }
  expect(screen.getByTestId("lo-kpi-source")).toHaveTextContent("material_requests");
  expect(screen.getByTestId("lo-kpi-source")).toHaveTextContent("asset_units");
  expect(within(screen.getByTestId("lo-kpis")).getByTestId("lo-kpi-open")).toBeInTheDocument();
  expect(screen.queryByTestId("lo-stock-incomplete")).not.toBeInTheDocument();
  expect(screen.getByTestId("lo-warehouses-source")).toHaveTextContent("всички отразени");
});

test("an incomplete stock projection is shown as incomplete", async () => {
  const base = projection();
  API.get.mockResolvedValue({ data: projection({
    warehouses: { ...base.warehouses, complete: false, unprojectable_movements: 2 },
  }) });
  renderPage();
  await screen.findByTestId("live-ops-control-center");
  expect(screen.getByTestId("lo-stock-incomplete")).toHaveTextContent("Непълна проекция: 2 движения");
  expect(screen.getByTestId("lo-warehouses-source")).toHaveTextContent("2 неотразени");
  expect(screen.getByTestId("lo-warehouses-source")).not.toHaveTextContent("всички отразени");
});
