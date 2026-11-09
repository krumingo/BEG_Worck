/**
 * WH-FIX-01 (FG-159 / WHFIX81-02) — the add-waste form sends what the canonical
 * write-off needs: the Master item (picked from the materials on the project),
 * photo evidence (uploaded first → file_ids) and an Idempotency-Key; a refusal is
 * shown in Bulgarian.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import bg from "@/i18n/bg.json";

jest.mock("react-i18next", () => {
  const dict = require("@/i18n/bg.json");
  const t = (key) => key.split(".").reduce((o, k) => (o ? o[k] : undefined), dict) ?? key;
  return { useTranslation: () => ({ t }) };
});

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) },
}));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

// eslint-disable-next-line import/first
import MaterialWastePanel from "@/components/MaterialWastePanel";
// eslint-disable-next-line import/first
import { toast as mockToast } from "sonner";

const SUMMARY = { summary: { materials_count: 0, total_waste_items: 0, total_waste_qty: 0,
                             overuse_count: 0 }, materials: [], writeoffs: [] };
const LEDGER = { ledger: [
  { item_id: "item-1", material_name: "Лепило", unit: "bag", remaining_on_project: 8 },
  { item_id: null, material_name: "Свободен текст", unit: "бр", remaining_on_project: 3 },
  { item_id: "item-2", material_name: "Изразходван", unit: "бр", remaining_on_project: 0 },
] };

beforeEach(() => {
  jest.clearAllMocks();
  mockGet.mockImplementation((url) => Promise.resolve(
    { data: url.startsWith("/project-material-ledger/") ? LEDGER : SUMMARY }));
});

async function openAndFill() {
  render(<MaterialWastePanel projectId="p1" />);
  await waitFor(() => expect(screen.getByTestId("add-waste-btn")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("add-waste-btn"));
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/project-material-ledger/p1"));
  const select = await screen.findByTestId("waste-material");
  // only Master items with stock on the project are offered
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: "item-1" } });
  fireEvent.change(screen.getByTestId("waste-qty"), { target: { value: "2" } });
  const file = new File(["x"], "broken.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByTestId("waste-evidence"), { target: { files: [file] } });
}

test("the UI sends item_id, file evidence and an Idempotency-Key", async () => {
  mockPost.mockImplementation((url) => Promise.resolve(
    url === "/media/upload" ? { data: { id: "media-1" } } : { data: { movement_id: "m1" } }));
  await openAndFill();
  fireEvent.click(screen.getByTestId("submit-waste"));
  await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
  expect(mockPost.mock.calls[0][0]).toBe("/media/upload");
  const [url, body, cfg] = mockPost.mock.calls[1];
  expect(url).toBe("/projects/p1/material-waste");
  expect(body).toMatchObject({ item_id: "item-1", material_name: "Лепило", unit: "bag", qty: 2,
                               file_ids: ["media-1"], reason: "Повреден" });
  expect(cfg.headers["Idempotency-Key"]).toBeTruthy();
  expect(mockToast.success).toHaveBeenCalledWith(bg.materialWaste.added);
});

test("a refusal is shown in Bulgarian", async () => {
  mockPost.mockImplementation((url) => (url === "/media/upload"
    ? Promise.resolve({ data: { id: "media-1" } })
    : Promise.reject({ response: { data: { detail: { error_code: "PERMISSION_DENIED",
                                                      message: "permission denied" } } } })));
  await openAndFill();
  fireEvent.click(screen.getByTestId("submit-waste"));
  await waitFor(() => expect(mockToast.error).toHaveBeenCalledWith(bg.materialWaste.errors.forbidden));
});

test("no evidence → nothing is sent", async () => {
  render(<MaterialWastePanel projectId="p1" />);
  await waitFor(() => expect(screen.getByTestId("add-waste-btn")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("add-waste-btn"));
  const select = await screen.findByTestId("waste-material");
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: "item-1" } });
  fireEvent.change(screen.getByTestId("waste-qty"), { target: { value: "2" } });
  fireEvent.click(screen.getByTestId("submit-waste"));
  expect(mockToast.error).toHaveBeenCalledWith(bg.materialWaste.evidenceRequired);
  expect(mockPost).not.toHaveBeenCalled();
});
