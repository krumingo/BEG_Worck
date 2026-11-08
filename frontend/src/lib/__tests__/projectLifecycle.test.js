// PRJ-01 (FLOW-001 P-04, P-08; R29; R54): every lifecycle call carries an Idempotency-Key,
// archive/cancel/reopen send the reason, and the reopen kinds are the server's list.
jest.mock("@/lib/api", () => ({ __esModule: true, default: { delete: jest.fn(() => Promise.resolve({})), post: jest.fn(() => Promise.resolve({})) } }));
import API from "@/lib/api";
import { REOPEN_KINDS, LIFECYCLE_ENDPOINT, deleteProject, changeProjectStatus, reopenProject } from "@/lib/projectLifecycle";

const keyOf = (call) => call[call.length - 1].headers["Idempotency-Key"];

describe("project lifecycle", () => {
  beforeEach(() => jest.clearAllMocks());

  test("delete sends a key", async () => {
    await deleteProject("p1");
    expect(API.delete).toHaveBeenCalledWith("/projects/p1", expect.any(Object));
    expect(keyOf(API.delete.mock.calls[0])).toBeTruthy();
  });

  test("archive and cancel go to their endpoints with the reason and a fresh key", async () => {
    await changeProjectStatus("p1", "Archived", "приключен");
    await changeProjectStatus("p1", "Cancelled", "отказ");
    expect(API.post.mock.calls[0][0]).toBe("/projects/p1/archive");
    expect(API.post.mock.calls[0][1]).toEqual({ reason: "приключен" });
    expect(API.post.mock.calls[1][0]).toBe("/projects/p1/cancel");
    expect(keyOf(API.post.mock.calls[0])).not.toBe(keyOf(API.post.mock.calls[1]));
    expect(Object.keys(LIFECYCLE_ENDPOINT).sort()).toEqual(["Archived", "Cancelled"]);
  });

  test("reopen sends kind and reason; the kinds are FLOW-001 P-08's", async () => {
    await reopenProject("p1", "warranty", "теч");
    expect(API.post).toHaveBeenCalledWith("/projects/p1/reopen", { kind: "warranty", reason: "теч" }, expect.any(Object));
    expect(Object.keys(REOPEN_KINDS)).toEqual(["warranty", "defect", "completion", "additional_work", "correction"]);
  });
});
