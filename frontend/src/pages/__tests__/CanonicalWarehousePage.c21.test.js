/**
 * 5C-C21 F-13 (Р11) — the warehouse→warehouse transfer form posts in_transit /
 * pending plus a `transfer_target` warehouse; it never posts the target as a
 * direct destination (the server refuses that).
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
  api.postMovement.mockResolvedValue({ movement_id: "mv-1", replay: false, envelope: {} });
  api.readBalance.mockResolvedValue({ balances: [] });
  api.readHistory.mockResolvedValue({ rows: [] });
  api.readIntegrityWarnings.mockResolvedValue({ warnings: [], fresh_at: "t" });
});

describe("F-13 warehouse transfer goes in transit", () => {
  it("posts in_transit/pending and the target warehouse as transfer_target", async () => {
    render(<CanonicalWarehousePage />);
    act(() => { fireEvent.click(screen.getByTestId("wh-tab-commands")); });
    act(() => { fireEvent.change(screen.getByTestId("wh-action-select"),
                                  { target: { value: "transfer_warehouse_to_warehouse" } }); });
    expect(screen.getByTestId("wh-dispatch-in-transit")).toBeInTheDocument();
    const inputs = document.querySelectorAll(".wh-form input");
    act(() => {
      fireEvent.change(inputs[0], { target: { value: "item-1" } });
      fireEvent.change(inputs[2], { target: { value: "10" } });
      fireEvent.change(inputs[3], { target: { value: "wh_a" } });
      fireEvent.change(screen.getByTestId("wh-transfer-target-type"),
                       { target: { value: "small_warehouse" } });
      fireEvent.change(screen.getByTestId("wh-transfer-target-id"), { target: { value: "wh_b" } });
    });
    await act(async () => { fireEvent.click(screen.getByText("Запиши движение")); });
    await waitFor(() => expect(api.postMovement).toHaveBeenCalledTimes(1));
    const payload = api.postMovement.mock.calls[0][0];
    expect(payload.destination).toEqual(
      { location_type: "in_transit", location_id: "pending", state: "in_transit" });
    expect(payload.transfer_target).toEqual(
      { location_type: "small_warehouse", location_id: "wh_b", state: "free" });
  });
});
