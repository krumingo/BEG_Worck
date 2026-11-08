/**
 * 5C-C26j — Р35: the central warehouse panel shows stock and prices (or says
 * the values are hidden), and the price history panel lists the purchases,
 * flags the same supplier at different prices and shows the best price.
 */
import React, { act } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { CentralStockPanel, PriceHistoryPanel } from "@/pages/CanonicalWarehousePage";

jest.mock("@/lib/warehouseCanonicalApi", () => ({
  ACTIONS: {}, LOCATION_TYPES: {}, STATES: { FREE: "free", QUARANTINE: "quarantine",
                                            IN_TRANSIT: "in_transit" },
  postMovement: jest.fn(), readBalance: jest.fn(), readHistory: jest.fn(),
  readIntegrityWarnings: jest.fn(), readStock: jest.fn(), readMigrationReadiness: jest.fn(),
  readCentralStock: jest.fn(), readPriceHistory: jest.fn(),
}));

jest.mock("@/contexts/AuthContext", () => ({
  __esModule: true,
  useAuth: () => ({ user: { id: "u-1", role: "Technician" }, loading: false }),
}));

it("central warehouse: quantity, value and priced layers", async () => {
  const load = jest.fn().mockResolvedValue({
    quantity: "10", total_value: "22.0000",
    layers: [{ quantity: "4", unit_value: "1" }, { quantity: "6", unit_value: "3" }],
  });
  render(<CentralStockPanel load={load} />);
  act(() => {
    fireEvent.change(screen.getByTestId("wh-central-item"), { target: { value: "I1" } });
    fireEvent.change(screen.getByTestId("wh-central-location"), { target: { value: "wh_1" } });
  });
  await act(async () => { fireEvent.click(screen.getByText("Покажи наличност и цени")); });
  expect(load).toHaveBeenCalledWith({ itemId: "I1", locationId: "wh_1" });
  expect(screen.getByTestId("wh-central-value")).toHaveTextContent("22.0000");
  expect(screen.getAllByTestId("wh-central-layer").map((n) => n.textContent))
    .toEqual(["4 × 1", "6 × 3"]);
});

it("central warehouse without values renders quantities only", async () => {
  const load = jest.fn().mockResolvedValue({ quantity: "10", values_hidden: true, layers: [] });
  render(<CentralStockPanel load={load} />);
  act(() => {
    fireEvent.change(screen.getByTestId("wh-central-item"), { target: { value: "I1" } });
    fireEvent.change(screen.getByTestId("wh-central-location"), { target: { value: "wh_1" } });
  });
  await act(async () => { fireEvent.click(screen.getByText("Покажи наличност и цени")); });
  expect(screen.queryByTestId("wh-central-value")).toBeNull();
  expect(screen.getByText(/Стойностите не се показват/)).toBeInTheDocument();
});

it("price history: purchases, the flag and the best price", async () => {
  const load = jest.fn().mockResolvedValue({
    project_id: "p1", flagged_articles: 1,
    articles: [{
      article: "I1", item_id: "I1", description: null, flagged: true,
      flags: [{ code: "SAME_SUPPLIER_DIFFERENT_PRICE", supplier: "sup_a" }],
      best_price: { unit_price: "9", supplier: "sup_a", date: "2026-11-01" },
      purchases: [
        { date: "2026-11-01", supplier: "sup_a", unit_price: "9", quantity: "5" },
        { date: "2026-11-03", supplier: "sup_a", unit_price: "11", quantity: "5" },
      ],
    }],
  });
  render(<PriceHistoryPanel load={load} />);
  act(() => {
    fireEvent.change(screen.getByTestId("wh-prices-project"), { target: { value: "p1" } });
  });
  await act(async () => { fireEvent.click(screen.getByText("Покажи ценова история")); });
  await waitFor(() => expect(screen.getAllByTestId("wh-price-row")).toHaveLength(2));
  expect(screen.getByTestId("wh-price-flag")).toBeInTheDocument();
  expect(screen.getByTestId("wh-price-best")).toHaveTextContent("9 (sup_a, 2026-11-01)");
});

it("price history with nothing bought twice says so", async () => {
  const load = jest.fn().mockResolvedValue({ project_id: "p1", articles: [] });
  render(<PriceHistoryPanel load={load} />);
  act(() => {
    fireEvent.change(screen.getByTestId("wh-prices-project"), { target: { value: "p1" } });
  });
  await act(async () => { fireEvent.click(screen.getByText("Покажи ценова история")); });
  expect(screen.getByTestId("wh-prices-empty")).toBeInTheDocument();
});
