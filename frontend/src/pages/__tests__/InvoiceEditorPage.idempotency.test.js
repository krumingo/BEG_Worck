/**
 * Codex F-73-01 (R29): every invoice write that links / unlinks a proforma advance carries an
 * Idempotency-Key — save (PUT), cancel and delete; a retry after a network error keeps the
 * same key (the server replays it), a success takes a new one.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("react-router-dom", () => ({
  __esModule: true, useParams: () => ({ invoiceId: "inv-1" }), useNavigate: () => () => {},
  useSearchParams: () => [new URLSearchParams(), () => {}], Link: ({ children }) => children,
}), { virtual: true });
jest.mock("@/contexts/AuthContext", () => ({ __esModule: true, useAuth: () => ({ user: { id: "u", role: "Owner" } }) }));
jest.mock("react-i18next", () => ({ __esModule: true, useTranslation: () => ({ t: (k) => k, i18n: { language: "bg" } }) }));
const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPut = jest.fn();
const mockDelete = jest.fn();
jest.mock("@/lib/api", () => ({ __esModule: true, default: {
  get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), put: (...a) => mockPut(...a),
  delete: (...a) => mockDelete(...a) } }));

// eslint-disable-next-line import/first
import InvoiceEditorPage from "../InvoiceEditorPage";

const INVOICE = {
  id: "inv-1", direction: "Issued", kind: "Invoice", status: "Draft", invoice_no: "F-1", project_id: "P",
  counterparty_name: "Клиент", issue_date: "2026-11-10", due_date: "2026-11-20", currency: "EUR",
  vat_percent: 20, lines: [{ id: "l1", description: "СМР", unit: "pcs", qty: 1, unit_price: 1000 }],
  subtotal: 1000, vat_amount: 200, total: 1200, paid_amount: 0, remaining_amount: 1200,
  advance_proforma_ids: ["pf-1"],
};

let status = "Draft";
beforeEach(() => {
  status = "Draft";
  [mockGet, mockPost, mockPut, mockDelete].forEach((m) => m.mockReset());
  mockGet.mockImplementation((url) => {
    if (url === "/finance/invoices/inv-1") return Promise.resolve({ data: { ...INVOICE, status } });
    if (url === "/clients?page_size=100") return Promise.resolve({ data: { items: [] } });
    return Promise.resolve({ data: [] });
  });
  window.confirm = jest.fn(() => true);
  window.alert = jest.fn();
});

const keyOf = (call) => call[2]?.headers?.["Idempotency-Key"];

test("cancel (issued invoice) sends an Idempotency-Key", async () => {
  status = "Sent";
  mockPost.mockResolvedValue({ data: {} });
  render(<InvoiceEditorPage />);
  await waitFor(() => expect(screen.getByTestId("cancel-btn")).toBeTruthy());
  fireEvent.click(screen.getByTestId("cancel-btn"));
  await waitFor(() => expect(mockPost).toHaveBeenCalled());
  const cancel = mockPost.mock.calls.find((c) => c[0] === "/finance/invoices/inv-1/cancel");
  expect(keyOf(cancel)).toEqual(expect.any(String));
});

test("delete (draft) sends an Idempotency-Key", async () => {
  mockDelete.mockResolvedValue({ data: { ok: true } });
  render(<InvoiceEditorPage />);
  await waitFor(() => expect(screen.getByTestId("delete-btn")).toBeTruthy());
  fireEvent.click(screen.getByTestId("delete-btn"));
  await waitFor(() => expect(mockDelete).toHaveBeenCalled());
  const del = mockDelete.mock.calls[0];
  expect(del[0]).toBe("/finance/invoices/inv-1");
  expect(del[1]?.headers?.["Idempotency-Key"]).toEqual(expect.any(String));
});

test("save (PUT with advance_proforma_ids) sends a key; a network retry reuses it", async () => {
  mockPut.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValue({ data: INVOICE });
  render(<InvoiceEditorPage />);
  await waitFor(() => expect(screen.getByTestId("edit-btn")).toBeTruthy());
  fireEvent.click(screen.getByTestId("edit-btn"));
  fireEvent.click(screen.getByTestId("save-btn"));
  await waitFor(() => expect(mockPut).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByTestId("save-btn"));
  await waitFor(() => expect(mockPut.mock.calls.filter((c) => c[0] === "/finance/invoices/inv-1").length).toBe(2));
  const puts = mockPut.mock.calls.filter((c) => c[0] === "/finance/invoices/inv-1");
  expect(puts[0][1].advance_proforma_ids).toEqual(["pf-1"]);
  expect(keyOf(puts[0])).toEqual(expect.any(String));
  expect(keyOf(puts[1])).toBe(keyOf(puts[0]));          // same request → same key (a replay)
});
