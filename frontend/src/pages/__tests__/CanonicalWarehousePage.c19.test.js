/**
 * 5C-C19 — canonical warehouse screen after the bot run on 639ca80.
 *
 *   F-3: a failed integrity-warnings request is an ERROR state, never the
 *        "no alarms" all-clear;
 *   F-4: the dispatch form always posts in_transit / pending and offers no
 *        other destination;
 *   F-6: tabs and the action picker follow the role's canonical rights
 *        (read-only Accountant: no write form; Warehousekeeper: write tab with
 *        exactly its actions); consume has an SMR field and posts smr_id.
 */
import React, { act } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

jest.mock("@/lib/warehouseCanonicalApi", () => {
  const ACTIONS = Object.freeze({
    RECEIVE_FROM_SUPPLIER: "receive_from_supplier",
    RECEIVE_FROM_SUPPLIER_TO_PROJECT: "receive_from_supplier_to_project",
    RESERVE: "reserve",
    RELEASE_RESERVATION: "release_reservation",
    DISPATCH_WAREHOUSE_TO_PROJECT: "dispatch_warehouse_to_project",
    ACCEPT_PROJECT_DELIVERY: "accept_project_delivery",
    TRANSFER_PROJECT_TO_WAREHOUSE: "transfer_project_to_warehouse",
    TRANSFER_PROJECT_TO_PROJECT: "transfer_project_to_project",
    TRANSFER_WAREHOUSE_TO_WAREHOUSE: "transfer_warehouse_to_warehouse",
    CONSUME_TO_SMR: "consume_to_smr",
    RETURN_TO_SUPPLIER: "return_to_supplier",
    WRITE_OFF: "write_off",
    REVISION_ADJUSTMENT: "revision_adjustment",
    QUARANTINE_ENTRY: "quarantine_entry",
    QUARANTINE_RELEASE: "quarantine_release",
  });
  return {
    ACTIONS,
    LOCATION_TYPES: {
      CENTRAL_WAREHOUSE: "central_warehouse", SMALL_WAREHOUSE: "small_warehouse",
      PROJECT: "project", SUBPROJECT: "subproject", PERSON: "person",
      VEHICLE: "vehicle", SUPPLIER: "supplier", IN_TRANSIT: "in_transit",
      UNRESOLVED: "unresolved",
    },
    STATES: { FREE: "free", RESERVED: "reserved", QUARANTINE: "quarantine",
              IN_TRANSIT: "in_transit", UNRESOLVED: "unresolved" },
    postMovement: jest.fn(),
    readBalance: jest.fn(),
    readHistory: jest.fn(),
    readIntegrityWarnings: jest.fn(),
    readStock: jest.fn(),
    readMigrationReadiness: jest.fn(),
  };
});

let mockRole = "Admin";
jest.mock("@/contexts/AuthContext", () => ({
  __esModule: true,
  useAuth: () => ({ user: { id: "u-1", role: mockRole }, loading: false }),
}));

import CanonicalWarehousePage, { WarningsPanel, visiblePanels } from "@/pages/CanonicalWarehousePage";
import * as api from "@/lib/warehouseCanonicalApi";

beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "Admin";
  api.postMovement.mockResolvedValue({ movement_id: "mv-1", replay: false, envelope: {} });
  api.readBalance.mockResolvedValue({ balances: [] });
  api.readHistory.mockResolvedValue({ rows: [] });
  api.readIntegrityWarnings.mockResolvedValue({ warnings: [], fresh_at: "t" });
});

const tabIds = () => Array.from(document.querySelectorAll("[data-testid^='wh-tab-']"))
  .map((b) => b.getAttribute("data-testid").replace("wh-tab-", ""));

function openCommands() {
  act(() => { fireEvent.click(screen.getByTestId("wh-tab-commands")); });
}

const options = () => Array.from(screen.getByTestId("wh-action-select").querySelectorAll("option"))
  .map((o) => o.value);

// ─────────────────────────────── F-3 ───────────────────────────────

describe("F-3 integrity warnings", () => {
  it("shows an error state on HTTP 500, never the all-clear", async () => {
    const load = jest.fn().mockRejectedValue({ response: { status: 500, data: {} }, message: "boom" });
    render(<WarningsPanel load={load} />);
    expect(await screen.findByTestId("wh-warnings-error")).toHaveTextContent("HTTP_500");
    expect(screen.queryByTestId("wh-warnings-empty")).toBeNull();
    expect(screen.queryByText(/Няма активни аларми/)).toBeNull();
  });

  it("treats a malformed answer as an error, not as zero alarms", async () => {
    render(<WarningsPanel load={jest.fn().mockResolvedValue({})} />);
    expect(await screen.findByTestId("wh-warnings-error")).toHaveTextContent("INVALID_RESPONSE");
    expect(screen.queryByTestId("wh-warnings-empty")).toBeNull();
  });

  it("shows the all-clear only for a real empty list", async () => {
    render(<WarningsPanel load={jest.fn().mockResolvedValue({ warnings: [], fresh_at: "t" })} />);
    expect(await screen.findByTestId("wh-warnings-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("wh-warnings-error")).toBeNull();
  });

  it("lists real alarms", async () => {
    render(<WarningsPanel load={jest.fn().mockResolvedValue({
      warnings: [{ code: "NEGATIVE_STOCK" }], fresh_at: "t" })} />);
    expect(await screen.findByText("NEGATIVE_STOCK")).toBeInTheDocument();
  });

  it("the page's alarms tab shows the error on a failed request", async () => {
    api.readIntegrityWarnings.mockRejectedValue({
      response: { status: 500, data: { detail: { error_code: "INTERNAL" } } } });
    render(<CanonicalWarehousePage />);
    act(() => { fireEvent.click(screen.getByTestId("wh-tab-warnings")); });
    expect(await screen.findByTestId("wh-warnings-error")).toHaveTextContent("INTERNAL");
  });
});

// ─────────────────────────────── F-6 ───────────────────────────────

describe("F-6 visibility follows the canonical rights", () => {
  it("Accountant (read-only) sees no write tab and no form", () => {
    mockRole = "Accountant";
    render(<CanonicalWarehousePage />);
    // 5C-C26j — Р35: + central warehouse (read) and price history.
    expect(tabIds()).toEqual(["stock", "history", "warnings", "central", "prices"]);
    expect(screen.queryByTestId("wh-action-select")).toBeNull();
    expect(screen.queryByText("Запиши движение")).toBeNull();
  });

  it("Warehousekeeper gets the write tab with exactly its actions (no consume)", () => {
    mockRole = "Warehousekeeper";
    render(<CanonicalWarehousePage />);
    // 5C-C26j — Р35: + central warehouse (read); no price history (Р34).
    expect(tabIds()).toEqual(["stock", "history", "commands", "warnings", "central"]);
    openCommands();
    expect(options()).toEqual([
      "receive_from_supplier", "reserve", "release_reservation",
      "dispatch_warehouse_to_project", "accept_project_delivery",
      "transfer_project_to_warehouse", "transfer_warehouse_to_warehouse",
      "quarantine_entry", "quarantine_release",
    ]);
    expect(options()).not.toContain("consume_to_smr");
  });

  it.each(["Viewer", "Driver", "", undefined])(
    "%p gets no panel at all", (role) => {
      expect(visiblePanels(role)).toEqual([]);
    });

  it("Technician gets only the Р35 read panels (central warehouse, prices)", () => {
    expect(visiblePanels("Technician").map((p) => p.id)).toEqual(["central", "prices"]);
  });

  it("SiteManager may consume — the form has an SMR field and posts smr_id", async () => {
    mockRole = "SiteManager";
    render(<CanonicalWarehousePage />);
    openCommands();
    act(() => { fireEvent.change(screen.getByTestId("wh-action-select"),
                                  { target: { value: "consume_to_smr" } }); });
    const smr = screen.getByTestId("wh-smr-id");
    const inputs = document.querySelectorAll(".wh-form input");
    act(() => {
      fireEvent.change(inputs[0], { target: { value: "item-1" } });          // item_id
      fireEvent.change(inputs[2], { target: { value: "3" } });               // quantity
    });
    const submit = screen.getByText("Запиши движение");
    expect(submit).toBeDisabled();                                           // SMR required
    act(() => { fireEvent.change(smr, { target: { value: "smr-7" } }); });
    expect(submit).not.toBeDisabled();
    await act(async () => { fireEvent.click(submit); });
    await waitFor(() => expect(api.postMovement).toHaveBeenCalledTimes(1));
    expect(api.postMovement.mock.calls[0][0]).toMatchObject(
      { action: "consume_to_smr", smr_id: "smr-7" });
  });
});

// ─────────────────────────────── F-4 ───────────────────────────────

describe("F-4 dispatch always goes in transit", () => {
  it("offers no destination picker and posts in_transit/pending", async () => {
    mockRole = "Warehousekeeper";
    render(<CanonicalWarehousePage />);
    openCommands();
    act(() => { fireEvent.change(screen.getByTestId("wh-action-select"),
                                  { target: { value: "dispatch_warehouse_to_project" } }); });
    expect(screen.getByTestId("wh-dispatch-in-transit")).toBeInTheDocument();
    const inputs = document.querySelectorAll(".wh-form input");
    act(() => {
      fireEvent.change(inputs[0], { target: { value: "item-1" } });
      fireEvent.change(inputs[2], { target: { value: "10" } });
    });
    await act(async () => { fireEvent.click(screen.getByText("Запиши движение")); });
    await waitFor(() => expect(api.postMovement).toHaveBeenCalledTimes(1));
    expect(api.postMovement.mock.calls[0][0].destination).toEqual(
      { location_type: "in_transit", location_id: "pending", state: "in_transit" });
  });
});
