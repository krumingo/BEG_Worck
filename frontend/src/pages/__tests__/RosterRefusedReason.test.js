// FG-661: the field user is told, per worker, why a removal from today's list was refused.
jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
jest.mock("react-router-dom", () => ({ __esModule: true, useNavigate: () => jest.fn(), Link: () => null }), { virtual: true });
import { refusedReasonText } from "@/pages/TechnicianDashboard";

test("each refusal reads as its reason", () => {
  expect(refusedReasonText({ error_code: "ENTRY_IN_USE", relies_on: "daily_report" })).toBe("има отчет");
  expect(refusedReasonText({ error_code: "ENTRY_IN_USE", relies_on: "offline_sync" })).toBe("офлайн запис");
  expect(refusedReasonText({ error_code: "CORRECTION_OR_REVERSAL_REQUIRED", relies_on: "pay_run_paid" }))
    .toMatch("денят е затворен");
});

import { askRemovalReason } from "@/pages/TechnicianDashboard";

test("FG-665: a removal reason is asked for; too short or cancelled means no removal", () => {
  expect(askRemovalReason(() => "  прехвърлен  ")).toBe("прехвърлен");
  expect(askRemovalReason(() => "ок")).toBeNull();
  expect(askRemovalReason(() => null)).toBeNull();
});
