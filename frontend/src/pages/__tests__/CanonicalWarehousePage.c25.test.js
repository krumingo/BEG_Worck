/**
 * 5C-C25 (Р18) — every transfer form posts in_transit / pending plus a
 * `transfer_target`: a return to a warehouse targets its QUARANTINE, a
 * project→project transfer targets the other project; an acceptance can land
 * in quarantine. The target is never posted as a direct destination.
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


async function fillTransfer(action, sourceId, targetType, targetId) {
  render(<CanonicalWarehousePage />);
  act(() => { fireEvent.click(screen.getByTestId("wh-tab-commands")); });
  act(() => { fireEvent.change(screen.getByTestId("wh-action-select"),
                                { target: { value: action } }); });
  expect(screen.getByTestId("wh-dispatch-in-transit")).toBeInTheDocument();
  const inputs = document.querySelectorAll(".wh-form input");
  act(() => {
    fireEvent.change(inputs[0], { target: { value: "item-1" } });
    fireEvent.change(inputs[2], { target: { value: "3" } });
    fireEvent.change(inputs[3], { target: { value: sourceId } });
    if (targetType) {
      fireEvent.change(screen.getByTestId("wh-transfer-target-type"),
                       { target: { value: targetType } });
    }
    fireEvent.change(screen.getByTestId("wh-transfer-target-id"), { target: { value: targetId } });
  });
  await act(async () => { fireEvent.click(screen.getByText("Запиши движение")); });
  await waitFor(() => expect(api.postMovement).toHaveBeenCalledTimes(1));
  return api.postMovement.mock.calls[0][0];
}

describe("Р18 every transfer goes in transit", () => {
  it("a return to a warehouse targets its quarantine", async () => {
    const payload = await fillTransfer("transfer_project_to_warehouse", "p-1", null, "wh_1");
    expect(payload.destination).toEqual(
      { location_type: "in_transit", location_id: "pending", state: "in_transit" });
    expect(payload.transfer_target).toEqual(
      { location_type: "central_warehouse", location_id: "wh_1", state: "quarantine" });
    expect(screen.getByText(/КАРАНТИНА/)).toBeInTheDocument();
  });

  it("a project → project transfer targets the other project, in transit", async () => {
    const payload = await fillTransfer("transfer_project_to_project", "p-1", null, "p-2");
    expect(payload.destination.location_type).toBe("in_transit");
    expect(payload.transfer_target).toEqual(
      { location_type: "project", location_id: "p-2", state: "free" });
  });

  it("an acceptance can land in quarantine", async () => {
    render(<CanonicalWarehousePage />);
    act(() => { fireEvent.click(screen.getByTestId("wh-tab-commands")); });
    act(() => { fireEvent.change(screen.getByTestId("wh-action-select"),
                                  { target: { value: "accept_project_delivery" } }); });
    act(() => { fireEvent.change(screen.getByTestId("wh-accept-state"),
                                  { target: { value: "quarantine" } }); });
    const inputs = document.querySelectorAll(".wh-form input");
    act(() => {
      fireEvent.change(inputs[0], { target: { value: "item-1" } });
      fireEvent.change(inputs[2], { target: { value: "3" } });
      fireEvent.change(inputs[5], { target: { value: "wh_1" } });
    });
    await act(async () => { fireEvent.click(screen.getByText("Запиши движение")); });
    await waitFor(() => expect(api.postMovement).toHaveBeenCalledTimes(1));
    const payload = api.postMovement.mock.calls[0][0];
    expect(payload.destination.state).toBe("quarantine");
    expect(payload.destination.location_id).toBe("wh_1");
  });
});
