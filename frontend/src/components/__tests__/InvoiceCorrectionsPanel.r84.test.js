/**
 * R84 (refund before the credit note) + FG-599 (Р49(4)): on a supplier invoice that
 * awaits a credit, the Accountant registers the supplier's refund against the NAMED
 * awaited row (money IN, FLOW-006); the Owner / Admin see no such action and no
 * note-creation buttons.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) },
}));

// eslint-disable-next-line import/first
import InvoiceCorrectionsPanel from "@/components/InvoiceCorrectionsPanel";

const INVOICE = { id: "inv-1", direction: "Received", status: "Paid", lines: [{ id: "l1" }] };
const VIEW = {
  invoice_id: "inv-1", remaining_amount: 0, credit_balance: 0, notes: [], offsets: [],
  expected_credit_notes: [{ id: "ecn-1", amount: 36, status: "open",
                            coverage: { refunded: 24, noted: 0, uncovered: 24, open: 12 } }],
};

beforeEach(() => {
  mockGet.mockReset().mockResolvedValue({ data: VIEW });
  mockPost.mockReset().mockResolvedValue({ data: {} });
});

test("the Accountant registers a refund against the named awaited row", async () => {
  const prompt = jest.spyOn(window, "prompt").mockReturnValueOnce("12").mockReturnValueOnce("банка 13.11");
  render(<InvoiceCorrectionsPanel invoice={INVOICE} user={{ id: "a", role: "Accountant" }} />);
  await waitFor(() => expect(screen.getByTestId("expected-credit-ecn-1")).toHaveTextContent("върнати 24, остава 12"));
  expect(screen.getByTestId("credit-note-btn")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("refund-before-note-ecn-1"));
  await waitFor(() => expect(mockPost).toHaveBeenCalled());
  const [url, body, opts] = mockPost.mock.calls[0];
  expect(url).toBe("/finance/invoices/inv-1/refund");
  expect(body).toEqual({ amount: 12, reason: "банка 13.11", method: "BankTransfer",
                         expected_credit_rows: [{ id: "ecn-1", amount: 12 }] });
  expect(opts.headers["Idempotency-Key"]).toBeTruthy();
  prompt.mockRestore();
});

test.each(["Owner", "Admin"])("%s sees neither the refund action nor the note buttons", async (role) => {
  render(<InvoiceCorrectionsPanel invoice={INVOICE} user={{ id: "o", role }} />);
  await waitFor(() => expect(screen.getByTestId("expected-credit-ecn-1")).toBeInTheDocument());
  expect(screen.queryByTestId("refund-before-note-ecn-1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("credit-note-btn")).not.toBeInTheDocument();
});
