/**
 * FG-710 (FG-698a, R86): the final invoice names its proforma advances — only issued
 * proformas of the project that no other invoice already uses.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("react-router-dom", () => ({
  __esModule: true, useParams: () => ({}), useNavigate: () => () => {},
  useSearchParams: () => [new URLSearchParams(), () => {}], Link: ({ children }) => children,
}), { virtual: true });
jest.mock("@/contexts/AuthContext", () => ({ __esModule: true, useAuth: () => ({ user: { id: "u", role: "Owner" } }) }));
jest.mock("react-i18next", () => ({ __esModule: true, useTranslation: () => ({ t: (k) => k, i18n: { language: "bg" } }) }));
const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: (...a) => mockGet(...a) } }));

// eslint-disable-next-line import/first
import { AdvanceProformasField } from "../InvoiceEditorPage";

function Harness({ invoiceId = "inv-1", onChange = () => {} }) {
  const [proformas, setProformas] = React.useState([]);
  const [value, setValue] = React.useState([]);
  return <AdvanceProformasField projectId="P" invoiceId={invoiceId} value={value}
    onChange={(v) => { setValue(v); onChange(v); }} disabled={false}
    proformas={proformas} setProformas={setProformas} />;
}

test("lists only the project's issued, unused proformas and toggles the advance", async () => {
  mockGet.mockResolvedValue({ data: [
    { id: "pf-ok", kind: "Proforma", status: "Sent", invoice_no: "PF-1", total: 600, paid_amount: 600 },
    { id: "pf-mine", kind: "Proforma", status: "Paid", invoice_no: "PF-2", total: 100, advance_used_by_invoice_id: "inv-1" },
    { id: "pf-used", kind: "Proforma", status: "Sent", invoice_no: "PF-3", total: 50, advance_used_by_invoice_id: "inv-9" },
    { id: "pf-draft", kind: "Proforma", status: "Draft", invoice_no: "PF-4", total: 50 },
    { id: "inv-x", kind: "Invoice", status: "Sent", invoice_no: "F-1", total: 1200 },
  ] });
  const onChange = jest.fn();
  render(<Harness onChange={onChange} />);
  await waitFor(() => expect(screen.getByTestId("advance-proforma-pf-ok")).toBeTruthy());
  expect(mockGet).toHaveBeenCalledWith("/finance/invoices", { params: { direction: "Issued", project_id: "P" } });
  expect(screen.getByTestId("advance-proforma-pf-mine")).toBeTruthy();
  for (const id of ["pf-used", "pf-draft", "inv-x"]) expect(screen.queryByTestId(`advance-proforma-${id}`)).toBeNull();
  fireEvent.click(screen.getByTestId("advance-proforma-pf-ok"));
  expect(onChange).toHaveBeenLastCalledWith(["pf-ok"]);
  fireEvent.click(screen.getByTestId("advance-proforma-pf-ok"));
  expect(onChange).toHaveBeenLastCalledWith([]);
});
