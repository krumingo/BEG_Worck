/**
 * 5C-C26 Addendum A — the warehouse screen shows in_transit / quarantine as
 * „в път" / „карантина", and does not break when FG-23 (Р20) hides the money
 * values from a non-finance role (quantities only, values_hidden).
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

import CanonicalWarehousePage from "@/pages/CanonicalWarehousePage";
import * as api from "@/lib/warehouseCanonicalApi";

beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "Admin";
  api.readHistory.mockResolvedValue({ rows: [], values_hidden: true });
  api.readIntegrityWarnings.mockResolvedValue({ warnings: [], fresh_at: "t" });
});

it("stock rows show „в път“ and „карантина“, quantities only (no values)", async () => {
  api.readBalance.mockResolvedValue({
    values_hidden: true,
    balances: [
      { location_type: "in_transit", location_id: "pending", state: "in_transit", quantity: "3" },
      { location_type: "central_warehouse", location_id: "wh_1", state: "quarantine", quantity: "2" },
    ],
  });
  render(<CanonicalWarehousePage />);
  act(() => { fireEvent.click(screen.getByTestId("wh-tab-stock")); });
  const input = document.querySelector(".wh-panel input");
  act(() => { fireEvent.change(input, { target: { value: "item-1" } }); });
  await act(async () => { fireEvent.click(screen.getByText("Прочети наличност")); });
  await waitFor(() => expect(screen.getAllByTestId("wh-stock-state")).toHaveLength(2));
  const states = screen.getAllByTestId("wh-stock-state").map((n) => n.textContent);
  expect(states).toEqual(["(в път)", "(карантина)"]);
  expect(screen.getByText(/в път:pending/)).toBeInTheDocument();
  expect(screen.queryByText(/in_transit/)).toBeNull();
  expect(screen.getByText("3")).toBeInTheDocument();
});

it("a dispatch form names the transit state „в път“", () => {
  render(<CanonicalWarehousePage />);
  act(() => { fireEvent.click(screen.getByTestId("wh-tab-commands")); });
  act(() => { fireEvent.change(screen.getByTestId("wh-action-select"),
                                { target: { value: "dispatch_warehouse_to_project" } }); });
  expect(screen.getByTestId("wh-dispatch-in-transit").textContent).toMatch(/^в път/);
});

it("history without values (FG-23) renders", async () => {
  api.readHistory.mockResolvedValue({ values_hidden: true, rows: [
    { movement_id: "m1", recorded_at: "t1", action: "receive_from_supplier",
      quantity: "4", unit: "bag" }] });
  render(<CanonicalWarehousePage />);
  act(() => { fireEvent.click(screen.getByTestId("wh-tab-history")); });
  await act(async () => { fireEvent.click(screen.getByText("Покажи история")); });
  await waitFor(() => expect(screen.getByText("4 bag")).toBeInTheDocument());
});
