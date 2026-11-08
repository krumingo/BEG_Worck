/**
 * FG-271 (Q007 / Р58): the company result shows the FINAL result (projects − company
 * losses) and the losses line is VISIBLE (label, amount, what it includes) on every
 * company-result screen — the Финансов pulse tile („Текущ фирмен резултат“), the
 * profit-attribution heading, the Финансов анализ profit card.
 */
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockGet(...a), post: jest.fn() },
}));
// jest 27 cannot load react-router-dom 7 (see MasterDataRoute.test.js)
jest.mock("react-router-dom", () => ({ __esModule: true, useNavigate: () => () => {} }), { virtual: true });
jest.mock("recharts", () => {
  const Box = ({ children }) => <div>{children}</div>;
  return { PieChart: Box, Pie: Box, Cell: Box, Tooltip: Box, ResponsiveContainer: Box,
           BarChart: Box, Bar: Box, XAxis: Box, YAxis: Box, CartesianGrid: Box, Legend: Box };
});

// eslint-disable-next-line import/first
import CompanyLossesLine from "@/components/CompanyLossesLine";
// eslint-disable-next-line import/first
import FinancePulseCard from "@/components/FinancePulseCard";
// eslint-disable-next-line import/first
import ProfitAttributionWidget from "@/components/ProfitAttributionWidget";
// eslint-disable-next-line import/first
import FinanceAnalysisPage from "@/pages/FinanceAnalysisPage";

const BLOCK = {
  label: "Фирмени загуби (не се разпределят)",
  includes: "Приети разлики по кредитни известия на доставчици за стока, приета в склада (загуба от връщане, Р58)",
  scope: { period: null, basis: "cumulative" },
  amount: 300,
  lines: [{ ref: "cn1", posting_id: "dp1", posting: "booking", invoice_line_id: "il1",
            period: "2026-11", note_number: "CN-1", reason: "доставчикът не коригира", value: 300 }],
};
const TOTALS = { revenue: 10000, expense: 8000, profit: 2000, margin_pct: 20,
                 company_losses: 300, final_profit: 1700 };

beforeEach(() => mockGet.mockReset());

test("the losses line is visible — label, amount, what it includes — not only in a fold", () => {
  render(<CompanyLossesLine block={BLOCK} finalProfit={1700} />);
  expect(screen.getByTestId("company-losses-label")).toBeVisible();
  expect(screen.getByTestId("company-losses-label")).toHaveTextContent("Фирмени загуби (не се разпределят)");
  expect(screen.getByTestId("company-losses-amount")).toBeVisible();
  expect(screen.getByTestId("company-losses-amount").textContent).toMatch(/300/);
  expect(screen.getByTestId("company-losses-includes")).toHaveTextContent("приета в склада");
  expect(screen.getByTestId("company-final-result").textContent).toMatch(/1[\s ]?700/);
  expect(screen.getAllByTestId("company-loss-line")).toHaveLength(1);
});

test("„Текущ фирмен резултат“ tile shows final_profit, not the project sum", async () => {
  mockGet.mockImplementation((url) => Promise.resolve({ data:
    url === "/org/pnl-overview" ? { totals: TOTALS, company_losses: BLOCK, projects: [] }
    : url === "/finance/stats" ? { receivables_total: 0, company_losses: BLOCK }
    : { totals: {} } }));
  render(<FinancePulseCard />);
  await waitFor(() => expect(screen.getByTestId("pulse-final-profit")).toBeInTheDocument());
  expect(screen.getByText("Текущ фирмен резултат")).toBeInTheDocument();
  expect(screen.getByTestId("pulse-final-profit").textContent).toMatch(/1[\s ]?700/);
  expect(screen.getByTestId("pulse-profit-split").textContent).toMatch(/2[\s ]?000/);
  expect(screen.getByTestId("company-losses-label")).toBeVisible();
});

test("profit-attribution heading is the final result", async () => {
  mockGet.mockResolvedValue({ data: { totals: TOTALS, company_losses: BLOCK, top_winners: [],
                                      top_losers: [], expense_breakdown: {} } });
  render(<ProfitAttributionWidget />);
  await waitFor(() => expect(screen.getByTestId("attribution-heading")).toBeInTheDocument());
  expect(screen.getByTestId("attribution-heading").textContent).toMatch(/1[\s ]?700/);
  expect(screen.getByTestId("company-losses-amount")).toBeVisible();
});

test("Финансов анализ profit card shows the final result and the losses, visibly", async () => {
  mockGet.mockImplementation((url) => Promise.resolve({ data:
    url === "/org/pnl-attribution" ? { totals: TOTALS, company_losses: BLOCK, expense_breakdown: {} }
    : { totals: TOTALS, company_losses: BLOCK, projects: [] } }));
  render(<FinanceAnalysisPage />);
  await waitFor(() => expect(screen.getByTestId("analysis-profit-card")).toBeInTheDocument());
  const card = screen.getByTestId("analysis-profit-card");
  expect(within(card).getByTestId("analysis-final-profit").textContent).toMatch(/1[\s ]?700/);
  expect(within(card).getByTestId("analysis-profit-split").textContent).toMatch(/300/);
  expect(screen.getByTestId("company-losses-label")).toBeVisible();
});
