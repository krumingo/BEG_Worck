// FG-633: the app mounts no toast container (HANDOFF D12), so „Записано на телефона“ must stay
// on screen as long as something is unsent — not a toast that nobody sees.
import { render, screen } from "@testing-library/react";
// jest 27 cannot load react-router-dom 7 (see MasterDataRoute.test.js): a plain link stands in
jest.mock("react-router-dom", () => ({ __esModule: true,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a> }), { virtual: true });
const MemoryRouter = ({ children }) => children;

let mockState = { enabled: true, unsent: 2 };
jest.mock("@/lib/offline", () => ({
  __esModule: true,
  offlineQueue: {},
  STATUS: {},
  useOfflineQueue: () => mockState,
}));

import { UnsentBadge } from "@/components/offline/OfflineQueueUI";

test("unsent records show a persistent „Записано на телефона“ badge with the count", () => {
  mockState = { enabled: true, unsent: 2 };
  render(<MemoryRouter><UnsentBadge /></MemoryRouter>);
  const badge = screen.getByTestId("offline-unsent-badge");
  expect(badge).toHaveTextContent("Записано на телефона");
  expect(screen.getByTestId("offline-unsent-count")).toHaveTextContent("2");
});

test("nothing is shown once everything is sent, or when the flag is off", () => {
  mockState = { enabled: true, unsent: 0 };
  const { container, rerender } = render(<MemoryRouter><UnsentBadge /></MemoryRouter>);
  expect(container).toBeEmptyDOMElement();
  mockState = { enabled: false, unsent: 3 };
  rerender(<MemoryRouter><UnsentBadge /></MemoryRouter>);
  expect(container).toBeEmptyDOMElement();
});
