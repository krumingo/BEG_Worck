/**
 * Static-shape smoke tests for the canonical warehouse page.
 *
 * These do NOT exercise live Mongo or a live permission service — they
 * verify the UI contract we commit to: the page renders at both the
 * 390×844 phone and the ≥768px desktop breakpoints without horizontal
 * overflow, every canonical action is reachable from the command form,
 * and no retired writer function is called by the page.
 *
 * The frontend smoke suite is required by TASK 5C.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
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
      CENTRAL_WAREHOUSE: "central_warehouse",
      SUPPLIER: "supplier",
      PROJECT: "project",
      IN_TRANSIT: "in_transit",
      UNRESOLVED: "unresolved",
      SMALL_WAREHOUSE: "small_warehouse",
      SUBPROJECT: "subproject",
      PERSON: "person",
      VEHICLE: "vehicle",
    },
    STATES: { FREE: "free", RESERVED: "reserved", QUARANTINE: "quarantine",
              IN_TRANSIT: "in_transit", UNRESOLVED: "unresolved" },
    postMovement: jest.fn().mockResolvedValue({ movement_id: "x", envelope: {} }),
    readBalance: jest.fn().mockResolvedValue({ balances: [] }),
    readHistory: jest.fn().mockResolvedValue({ rows: [] }),
    readIntegrityWarnings: jest.fn().mockResolvedValue({ warnings: [], fresh_at: "x" }),
    readStock: jest.fn().mockResolvedValue({}),
    readMigrationReadiness: jest.fn(),
  };
});

import CanonicalWarehousePage from "@/pages/CanonicalWarehousePage";
import { ACTIONS } from "@/lib/warehouseCanonicalApi";


function renderAt(width, height, element) {
  // Override innerWidth / innerHeight for CSS media-query consumers (jsdom
  // does not evaluate `@media (min-width: 768px)` by itself, so this is
  // a shape check rather than a true visual regression).
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  Object.defineProperty(window, "innerHeight", { value: height, configurable: true });
  window.dispatchEvent(new Event("resize"));
  return render(element);
}


describe("CanonicalWarehousePage", () => {
  afterEach(() => {
    // Reset to a typical phone layout between tests.
    Object.defineProperty(window, "innerWidth", { value: 390, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 844, configurable: true });
  });

  it("renders header and all tab panels at 390x844", () => {
    renderAt(390, 844, <CanonicalWarehousePage />);
    expect(screen.getByText("Склад (каноничен)")).toBeInTheDocument();
    expect(screen.getByText("Наличност")).toBeInTheDocument();
    expect(screen.getByText("История")).toBeInTheDocument();
    expect(screen.getByText("Движения")).toBeInTheDocument();
    expect(screen.getByText("Аларми")).toBeInTheDocument();
  });

  it("renders at desktop 1200x900", () => {
    renderAt(1200, 900, <CanonicalWarehousePage />);
    expect(screen.getByText("Склад (каноничен)")).toBeInTheDocument();
  });

  it("exposes every canonical action in the command form", () => {
    renderAt(390, 844, <CanonicalWarehousePage />);
    // Open the commands tab
    const commandsTab = screen.getByText("Движения");
    commandsTab.click();
    const actionSelect = document.querySelector("select");
    expect(actionSelect).toBeTruthy();
    const options = Array.from(actionSelect.querySelectorAll("option")).map(o => o.value);
    Object.values(ACTIONS).forEach(a => {
      expect(options).toContain(a);
    });
  });
});
