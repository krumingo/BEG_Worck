// FG-658: the console correction / void of a phone presence — reason required, the version the
// console showed (CAS on the server) and an Idempotency-Key.
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("@/lib/api", () => ({ __esModule: true, default: { post: jest.fn(() => Promise.resolve({ data: {} })), get: jest.fn() } }));
import API from "@/lib/api";
import { PresenceFix } from "@/pages/SyncConsolePage";

test("no action without a reason; void sends the version and an Idempotency-Key", async () => {
  const done = jest.fn();
  render(<PresenceFix item={{ id: "e1", status: "Present", version: 3 }} onDone={done} />);
  expect(screen.getByTestId("presence-fix-void")).toBeDisabled();
  fireEvent.change(screen.getByTestId("presence-fix-reason"), { target: { value: "грешен обект" } });
  fireEvent.click(screen.getByTestId("presence-fix-void"));
  await waitFor(() => expect(done).toHaveBeenCalled());
  const [url, body, cfg] = API.post.mock.calls[0];
  expect(url).toBe("/sync/presence/e1/fix");
  expect(body).toEqual({ action: "void", reason: "грешен обект", version: 3 });
  expect(cfg.headers["Idempotency-Key"]).toMatch(/:void$/);
});

test("correct sends the chosen status", async () => {
  API.post.mockClear();
  render(<PresenceFix item={{ id: "e2", status: "Present", version: 0 }} onDone={() => {}} />);
  fireEvent.change(screen.getByTestId("presence-fix-reason"), { target: { value: "болен" } });
  fireEvent.change(screen.getByTestId("presence-fix-status"), { target: { value: "SickLeave" } });
  fireEvent.click(screen.getByTestId("presence-fix-correct"));
  await waitFor(() => expect(API.post).toHaveBeenCalled());
  expect(API.post.mock.calls[0][1]).toEqual({ action: "correct", reason: "болен", version: 0, status: "SickLeave" });
});
