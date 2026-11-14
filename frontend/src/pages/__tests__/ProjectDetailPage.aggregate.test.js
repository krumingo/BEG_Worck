/**
 * FG-591 (FG-566 / R20): the parent aggregate carries money only for the finance roles. For a
 * member (SiteManager / Technician) the money blocks are absent — the summary must not show
 * them as "0 €": no money rows, no revenue / labor on the cards, no revenue / cost chart.
 */
import React from "react";
import { render, screen } from "@testing-library/react";

// react-router-dom 7 does not load under jest 27 (see MasterDataRoute.test.js)
jest.mock("react-router-dom", () => ({
  useParams: () => ({}), useNavigate: () => () => {}, useLocation: () => ({ pathname: "/", search: "" }),
  __esModule: true, Link: ({ children }) => children, NavLink: ({ children }) => children,
}), { virtual: true });
jest.mock("@/contexts/AuthContext", () => ({ __esModule: true, useAuth: () => ({ user: { id: "u", role: "Owner" } }) }));
jest.mock("@/contexts/ProjectContext", () => ({ __esModule: true, useActiveProject: () => ({ activeProject: null }) }));
jest.mock("react-i18next", () => ({ __esModule: true, useTranslation: () => ({ t: (k) => k, i18n: { language: "bg" } }) }));
jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: jest.fn(() => Promise.resolve({ data: {} })) } }));
jest.mock("recharts", () => {
  const Stub = ({ children }) => <div data-testid="recharts-stub">{children}</div>;
  return { ResponsiveContainer: Stub, BarChart: Stub, Bar: () => null, XAxis: () => null,
           YAxis: () => null, Tooltip: () => null, PieChart: Stub, Pie: () => null, Cell: () => null,
           LineChart: Stub, Line: () => null, CartesianGrid: () => null, Legend: () => null,
           AreaChart: Stub, Area: () => null };
});

// eslint-disable-next-line import/first
import { SubProjectsSummaryView } from "../ProjectDetailPage";

const subs = [{ id: "c1", code: "P-A", name: "A", status: "Active" }, { id: "c2", code: "P-B", name: "B", status: "Active" }];
const counts = (id) => ({ id, code: id === "c1" ? "P-A" : "P-B", name: id, status: "Active",
  team: { count: 2, hours: 8 }, offers: { count: 1 }, reports: { count: 3, hours: 24 }, work: { hours: 24 } });

const memberView = {           // what /aggregate answers to a member without the finance right
  has_children: true, children: [counts("c1"), counts("c2")],
  team: { total: { count: 4, hours: 16 } }, offers: { total: { count: 2 } },
  reports: { total: { count: 6, hours: 48 } }, work: { total: { hours: 48 } },
};
const financeView = {
  ...memberView,
  children: memberView.children.map(c => ({ ...c, invoices: { count: 1, invoiced: 1200, paid: 480, unpaid: 720, issued_net: 1000,
                                                                  received_net: 400, awaiting_payment_net: 600 },
                                            work: { hours: 24, labor_cost: 180 }, materials: { ex_vat: 50 },
                                            paid_labor: { gross_labor: 99 } })),
  invoices: { total: { count: 2, invoiced: 2400, paid: 600, unpaid: 1800 } },
  work: { total: { hours: 48, labor_cost: 360 } }, materials: { total: { ex_vat: 100 } },
  paid_labor: { total: { gross_labor: 198 } }, pnl: { revenue: 800, invoiced_net: 2000, awaiting_payment_net: 1200, expenses: 460, profit: 340 },
};

test("a member sees counts and hours, but no money row, card value or chart — never 0 €", () => {
  const { container } = render(<SubProjectsSummaryView sub_projects={subs} aggregate={memberView} navigate={() => {}} />);
  expect(container.textContent).not.toMatch(/€/);
  for (const label of ["Фактурирано", "Платено", "Неплатено", "Труд (одобрен)", "Материали", "Платен труд", "Приход:", "Труд:",
                       "Фактурирано, чака плащане", "Приход (получени"]) {
    expect(screen.queryByText(label, { exact: false })).toBeNull();
  }
  expect(screen.queryByTestId("sub-chart")).toBeNull();
  expect(screen.getByText("Хора")).toBeTruthy();
  expect(screen.getByText("Общо часове")).toBeTruthy();
});

test("a finance role sees the money rows, the card values and the chart", () => {
  const { container } = render(<SubProjectsSummaryView sub_projects={subs} aggregate={financeView} navigate={() => {}} />);
  expect(container.textContent).toMatch(/€/);
  expect(screen.getByText("Фактурирано")).toBeTruthy();
  expect(screen.getByText("Труд (одобрен)")).toBeTruthy();
  expect(screen.getAllByText("Приход:", { exact: false }).length).toBe(2);
  expect(screen.getByTestId("sub-chart")).toBeTruthy();
});

test("R86: revenue is the payments received, net — the issued amount waits apart", () => {
  const { container } = render(<SubProjectsSummaryView sub_projects={subs} aggregate={financeView} navigate={() => {}} />);
  expect(screen.getByText("Фактурирано, чака плащане")).toBeTruthy();
  expect(screen.getByText("Приход (получени, без ДДС)")).toBeTruthy();
  expect(screen.queryByText("Неплатено")).toBeNull();
  // each card's "Приход" is the received 400, never the issued 1000
  const cards = [...container.querySelectorAll("button")].map(b => b.textContent);
  expect(cards.filter(t => /Приход:\s*400/.test(t)).length).toBe(2);
  expect(cards.some(t => /Приход:\s*1[\s.,]?000/.test(t))).toBe(false);
});
