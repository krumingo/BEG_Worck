// SEC-03 (M-5): print windows are same-origin; every interpolated name / text is
// HTML-escaped, so a stored name like <img src=x onerror=...> prints as text.
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { escapeHtml } from "@/lib/escapeHtml";
import { openGroupPrint, openIndividualPrint, openSelectedPrint } from "../PayRunPrintView";
import UnitQrBlock from "../UnitQrBlock";
import API from "@/lib/api";

jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: jest.fn() } }));

const EVIL = '<img src=x onerror="window.__pwned=1">';
const EVIL_ESCAPED = "&lt;img src=x onerror=&quot;window.__pwned=1&quot;&gt;";

function fakeWindow() {
  const written = [];
  const w = { document: { write: (h) => written.push(h), close: jest.fn() }, print: jest.fn() };
  return { w, html: () => written.join("") };
}

beforeEach(() => {
  jest.useFakeTimers();
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

test("escapeHtml escapes every markup character and maps null/undefined to empty", () => {
  expect(escapeHtml(`<>&"'\``)).toBe("&lt;&gt;&amp;&quot;&#39;&#96;");
  expect(escapeHtml(null)).toBe("");
  expect(escapeHtml(undefined)).toBe("");
  expect(escapeHtml(12.5)).toBe("12.5");
  expect(escapeHtml("Иван Петров")).toBe("Иван Петров");
});

const run = { number: `PR-1${EVIL}`, week_number: 7, period_start: "2026-11-02", period_end: "2026-11-08" };
const row = {
  employee_id: "e1", first_name: EVIL, last_name: "Петров", position: EVIL, pay_type: EVIL,
  earned_amount: 100, paid_now_amount: 100, remaining_after_payment: 0,
  adjustments: [{ type: EVIL, title: EVIL, note: EVIL, amount: 5 }],
  day_cells: [{ date: "2026-11-02", hours: 8, sites: [{ site_name: EVIL }], value: 100 }],
};

test.each([
  ["group list", () => openGroupPrint(run, [row])],
  ["individual slip", () => openIndividualPrint(run, row, null)],
  ["selected slips", () => openSelectedPrint(run, [row], null)],
])("forbidden: the %s never writes a raw stored name into the print window", (_label, open) => {
  const { w, html } = fakeWindow();
  jest.spyOn(window, "open").mockReturnValue(w);
  open();
  const out = html();
  expect(out).not.toContain("<img");
  expect(out).not.toContain('onerror="');
  expect(out).toContain(EVIL_ESCAPED);
  jest.runAllTimers();
  expect(w.print).toHaveBeenCalled();
});

test("positive: an ordinary name prints unchanged", () => {
  const { w, html } = fakeWindow();
  jest.spyOn(window, "open").mockReturnValue(w);
  openIndividualPrint(run, { ...row, first_name: "Иван", position: "Зидар", adjustments: [] }, null);
  expect(html()).toContain("СЕДМИЧЕН ФИШ — Иван Петров");
  expect(html()).toContain("Зидар");
});

test("forbidden: the QR print escapes qr id and serial and has no inline script", async () => {
  jest.useRealTimers();
  API.get.mockResolvedValue({ data: "<svg><rect/></svg>" });
  const { w, html } = fakeWindow();
  jest.spyOn(window, "open").mockReturnValue(w);
  render(<UnitQrBlock qrId="QR-1" serialNo={EVIL} />);
  await waitFor(() => expect(screen.getByTestId("unit-qr-print")).toBeInTheDocument());
  await waitFor(() => expect(document.querySelector(".asset-qr-svg svg")).not.toBeNull());
  fireEvent.click(screen.getByTestId("unit-qr-print"));
  const out = html();
  expect(out).not.toContain("<img");
  expect(out).not.toContain("<script");
  expect(out).toContain(EVIL_ESCAPED);
  expect(out).toContain("<svg><rect/></svg>");       // our own server's QR, as before
});
