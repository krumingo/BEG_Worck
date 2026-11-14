// FG-633: the app mounts no toast container (HANDOFF D12), so „Записано на телефона“ must stay
// on screen as long as something is waiting to be sent — not a toast that nobody sees.
// FG-638: only records really waiting to SEND are counted; conflict / late / needs-review and
// waiting-for-file are shown apart.
import { render, screen } from "@testing-library/react";

// jest 27 cannot load react-router-dom 7 (see MasterDataRoute.test.js): a plain link stands in
jest.mock("react-router-dom", () => ({ __esModule: true,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a> }), { virtual: true });

let mockState = {};
jest.mock("@/lib/offline", () => ({
  __esModule: true,
  offlineQueue: {},
  STATUS: {},
  useOfflineQueue: () => mockState,
}));

import { UnsentBadge } from "@/components/offline/OfflineQueueUI";

test("records waiting to be sent show a persistent „Записано на телефона“ with their count", () => {
  mockState = { enabled: true, unsent: 2, toSend: 2, awaitingDecision: 0, waitingFile: 0 };
  render(<UnsentBadge />);
  expect(screen.getByTestId("offline-unsent-badge")).toHaveTextContent("Записано на телефона");
  expect(screen.getByTestId("offline-unsent-count")).toHaveTextContent("2");
  expect(screen.queryByTestId("offline-awaiting-decision")).toBeNull();
});

test("conflict / late and waiting-for-file are shown apart, never counted as to send", () => {
  mockState = { enabled: true, unsent: 4, toSend: 1, awaitingDecision: 2, waitingFile: 1 };
  render(<UnsentBadge />);
  expect(screen.getByTestId("offline-unsent-count")).toHaveTextContent("1");
  expect(screen.getByTestId("offline-awaiting-decision")).toHaveTextContent("чака решение · 2");
  expect(screen.getByTestId("offline-waiting-file")).toHaveTextContent("чака файл · 1");
});

test("only decisions pending: no „Записано на телефона“", () => {
  mockState = { enabled: true, unsent: 1, toSend: 0, awaitingDecision: 1, waitingFile: 0 };
  render(<UnsentBadge />);
  expect(screen.queryByTestId("offline-unsent-label")).toBeNull();
  expect(screen.getByTestId("offline-awaiting-decision")).toBeInTheDocument();
});

test("nothing is shown once everything is synced, or when the flag is off", () => {
  mockState = { enabled: true, unsent: 0, toSend: 0, awaitingDecision: 0, waitingFile: 0 };
  const { container, rerender } = render(<UnsentBadge />);
  expect(container).toBeEmptyDOMElement();
  mockState = { enabled: false, unsent: 3, toSend: 3 };
  rerender(<UnsentBadge />);
  expect(container).toBeEmptyDOMElement();
});
