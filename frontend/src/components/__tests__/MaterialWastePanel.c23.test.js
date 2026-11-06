/**
 * 5C-C23 F-15 — the „Материални отклонения" card shows the canonical
 * write-offs (from GET /projects/{id}/material-waste, read by the backend
 * through the shared material-cost helper) beside the manual register
 * entries, each write-off marked „отписване от склада".
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import bg from "@/i18n/bg.json";

jest.mock("react-i18next", () => {
  const dict = require("@/i18n/bg.json");
  const t = (key) => key.split(".").reduce((o, k) => (o ? o[k] : undefined), dict) ?? key;
  return { useTranslation: () => ({ t }) };
});

const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockGet(...a), post: jest.fn() },
}));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

// eslint-disable-next-line import/first
import MaterialWastePanel from "@/components/MaterialWastePanel";

const payload = (writeoffs, manual = 0) => ({
  summary: {
    materials_count: 1,
    total_waste_items: manual + writeoffs.length,
    total_waste_qty: manual * 1.5 + writeoffs.reduce((s, w) => s + w.qty, 0),
    manual_waste_items: manual, manual_waste_qty: manual * 1.5,
    writeoff_items: writeoffs.length,
    writeoff_qty: writeoffs.reduce((s, w) => s + w.qty, 0),
    writeoff_value: 20, writeoff_label: "отписване от склада",
    overuse_count: 0,
  },
  materials: [{ material_name: "Лепило", unit: "bag", planned_qty: 0, issued_qty: 0,
                wasted_qty: 2 + manual * 1.5, manual_wasted_qty: manual * 1.5,
                written_off_qty: 2, variance_vs_planned: 0, status: "ok" }],
  writeoffs,
});

const WO = { id: "me_m1", movement_id: "m1", source: "warehouse_write_off",
             source_label: "отписване от склада", cost_label: "фира",
             material_name: "Лепило", qty: 2, unit: "bag", value: 20,
             reason: "брак", date: "2026-11-06" };

test("canonical write-off is listed and marked „отписване от склада“", async () => {
  mockGet.mockResolvedValueOnce({ data: payload([WO]) });
  render(<MaterialWastePanel projectId="p1" />);
  await waitFor(() => expect(screen.getByTestId("material-waste-panel")).toBeInTheDocument());
  expect(mockGet).toHaveBeenCalledWith("/projects/p1/material-waste");
  const rows = screen.getAllByTestId("waste-writeoff-row");
  expect(rows).toHaveLength(1);
  expect(screen.getByTestId("waste-writeoff-badge")).toHaveTextContent(bg.materialWaste.writeOffBadge);
  expect(bg.materialWaste.writeOffBadge).toBe("отписване от склада");
  expect(rows[0]).toHaveTextContent("Лепило");
  expect(rows[0]).toHaveTextContent("2 bag");
  expect(screen.getByTestId("waste-writeoff-count")).toHaveTextContent("1 · 2");
  expect(screen.getByTestId("waste-manual-count")).toHaveTextContent("0 · 0");
});

test("manual entries stay and are counted beside the write-off", async () => {
  mockGet.mockResolvedValueOnce({ data: payload([WO], 1) });
  render(<MaterialWastePanel projectId="p1" />);
  await waitFor(() => expect(screen.getByTestId("waste-manual-count")).toHaveTextContent("1 · 1.5"));
  expect(screen.getByTestId("waste-writeoff-count")).toHaveTextContent("1 · 2");
  expect(screen.getByTestId("add-waste-btn")).toBeInTheDocument();
});

test("no write-offs → no write-off list", async () => {
  mockGet.mockResolvedValueOnce({ data: payload([]) });
  render(<MaterialWastePanel projectId="p1" />);
  await waitFor(() => expect(screen.getByTestId("material-waste-panel")).toBeInTheDocument());
  expect(screen.queryByTestId("waste-writeoffs")).not.toBeInTheDocument();
});
