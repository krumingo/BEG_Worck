/**
 * W0-03 — the office screen for pending mapping.
 *
 * What these tests hold onto, in the order a reviewer would ask about them:
 *
 *   * every state the screen can be in is actually reachable and says
 *     something true — loading, empty, off, forbidden, misconfigured, error;
 *   * the browser never sends a tenant. D-15 puts tenant resolution on the
 *     server, and a screen that helpfully passed an org_id would quietly undo
 *     that. One test watches every request made during a whole session;
 *   * creating an official record takes an explicit human confirmation. The
 *     button is not merely labelled that way — it is disabled until a person
 *     ticks the box, and the request that goes out carries the confirmation;
 *   * mapping to an existing record and rejecting both go through the six
 *     endpoints that already exist, with the bodies the contract expects;
 *   * a resolved or rejected proposal shows who decided it and what came of it.
 */
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}));

import API from "@/lib/api";
import { toast } from "sonner";
import MasterDataReviewPage from "@/pages/MasterDataReviewPage";

const PENDING_ROW = {
  id: "p-1",
  raw_value: "Баумит ЕООД",
  entity_type: "organization",
  source_channel: "ocr",
  source_ref: "ocr-intake:inv-1",
  status: "pending",
  occurrences: 3,
  created_at: "2026-09-20T10:00:00+00:00",
};

const queue = (items, mode = "enforce") => ({
  data: { mode, count: items.length, items },
});

const matches = (candidates) => ({
  data: { mode: "enforce", count: candidates.length, candidates },
});

function httpError(status, detail) {
  return { response: { status, data: { detail } } };
}

beforeEach(() => {
  jest.clearAllMocks();
  API.get.mockResolvedValue(queue([]));
  API.post.mockResolvedValue({ data: { performed: true } });
});

async function renderQueue(response) {
  API.get.mockImplementation((url) => {
    if (url === "/master-data/pending") return Promise.resolve(response);
    return Promise.resolve(matches([]));
  });
  render(<MasterDataReviewPage />);
  await waitFor(() => expect(screen.queryByTestId("md-loading")).not.toBeInTheDocument());
}

// ------------------------------------------------------------------ states

test("it says it is loading before the first answer arrives", async () => {
  let release;
  API.get.mockReturnValue(new Promise((resolve) => { release = resolve; }));
  render(<MasterDataReviewPage />);

  expect(screen.getByTestId("md-loading")).toBeInTheDocument();
  release(queue([]));
  await waitFor(() => expect(screen.queryByTestId("md-loading")).not.toBeInTheDocument());
});

test("an empty queue says so instead of showing nothing", async () => {
  await renderQueue(queue([]));
  expect(screen.getByTestId("md-empty")).toBeInTheDocument();
});

test("while the feature is off the screen says so and shows no queue", async () => {
  await renderQueue(queue([], "off"));

  expect(screen.getByTestId("md-off")).toBeInTheDocument();
  expect(screen.getByText(/off/)).toBeInTheDocument();
  expect(screen.queryByTestId("md-list")).not.toBeInTheDocument();
});

test("a forbidden role is told it may not use this screen", async () => {
  API.get.mockRejectedValue(httpError(403, { error_code: "PERMISSION_DENIED", message: "no" }));
  render(<MasterDataReviewPage />);

  expect(await screen.findByTestId("md-forbidden")).toBeInTheDocument();
  expect(screen.queryByTestId("md-error")).not.toBeInTheDocument();
});

test("an unusable MASTER_DATA_MODE is reported as configuration, not as a client error", async () => {
  API.get.mockRejectedValue(httpError(503, "MASTER_DATA_MODE is set to 'offf'"));
  render(<MasterDataReviewPage />);

  const box = await screen.findByTestId("md-misconfigured");
  expect(within(box).getByText(/MASTER_DATA_MODE/)).toBeInTheDocument();
});

test("any other failure offers a retry that actually retries", async () => {
  const user = userEvent.setup();
  API.get.mockRejectedValueOnce(httpError(500, "boom"));
  render(<MasterDataReviewPage />);

  await screen.findByTestId("md-error");
  API.get.mockResolvedValue(queue([PENDING_ROW]));
  await user.click(screen.getByTestId("md-retry"));

  expect(await screen.findByTestId("md-row-p-1")).toBeInTheDocument();
});

// ------------------------------------------------------------------ the queue

test("a proposal shows the original text, its type, its source and how often it was seen", async () => {
  await renderQueue(queue([PENDING_ROW]));

  const row = screen.getByTestId("md-row-p-1");
  expect(screen.getByTestId("md-raw-p-1")).toHaveTextContent("Баумит ЕООД");
  // scoped to the row: the same words are also filter options
  expect(within(row).getByText("Фирма")).toBeInTheDocument();
  expect(within(row).getByText("OCR")).toBeInTheDocument();
  expect(screen.getByTestId("md-occurrences-p-1")).toHaveTextContent("3×");
});

test("the filters are sent to the existing endpoint as its own parameters", async () => {
  const user = userEvent.setup();
  await renderQueue(queue([]));

  await user.selectOptions(screen.getByTestId("md-filter-status"), "resolved");
  await user.selectOptions(screen.getByTestId("md-filter-type"), "activity");
  await user.selectOptions(screen.getByTestId("md-filter-source"), "excel");

  await waitFor(() => {
    const last = API.get.mock.calls.filter((c) => c[0] === "/master-data/pending").pop();
    expect(last[1].params).toEqual({
      status: "resolved", entity_type: "activity", source_channel: "excel",
    });
  });
});

test("the browser never sends a tenant of its own", async () => {
  const user = userEvent.setup();
  API.get.mockImplementation((url) => {
    if (url === "/master-data/pending") return Promise.resolve(queue([PENDING_ROW]));
    return Promise.resolve(matches([{ entity_id: "e-1", display_name: "Баумит България ЕООД" }]));
  });
  render(<MasterDataReviewPage />);

  await user.click(await screen.findByTestId("md-expand-p-1"));
  await screen.findByTestId("md-candidates");
  await user.click(screen.getByTestId("md-link-e-1"));

  const everything = JSON.stringify([API.get.mock.calls, API.post.mock.calls]);
  expect(everything).not.toMatch(/tenant_id/);
  expect(everything).not.toMatch(/org_id/);
});

// ------------------------------------------------------------------ deciding

test("expanding a proposal loads its candidates and links to one on request", async () => {
  const user = userEvent.setup();
  API.get.mockImplementation((url) => {
    if (url === "/master-data/pending") return Promise.resolve(queue([PENDING_ROW]));
    return Promise.resolve(matches([
      { entity_id: "e-1", display_name: "Баумит България ЕООД", match_type: "exact_normalized", score: 1.0 },
    ]));
  });
  render(<MasterDataReviewPage />);

  await user.click(await screen.findByTestId("md-expand-p-1"));
  expect(await screen.findByTestId("md-candidate-e-1")).toHaveTextContent("Баумит България ЕООД");

  await user.click(screen.getByTestId("md-link-e-1"));

  expect(API.post).toHaveBeenCalledWith("/master-data/pending/p-1/approve",
    { confirmation: true, canonical_entity_id: "e-1" });
  await waitFor(() => expect(screen.queryByTestId("md-row-p-1")).not.toBeInTheDocument());
});

test("when nothing matches, the office can look the record up by typing a spelling", async () => {
  const user = userEvent.setup();
  API.get.mockImplementation((url, config) => {
    if (url === "/master-data/pending") return Promise.resolve(queue([PENDING_ROW]));
    if (config?.params?.q) {
      return Promise.resolve(matches([
        { entity_id: "e-9", display_name: "Баумит България ЕООД", match_type: "human_lookup", score: null },
      ]));
    }
    return Promise.resolve(matches([]));
  });
  render(<MasterDataReviewPage />);

  await user.click(await screen.findByTestId("md-expand-p-1"));
  expect(await screen.findByTestId("md-candidates-empty")).toBeInTheDocument();

  await user.type(screen.getByTestId("md-search-input"), "Баумит");
  await user.click(screen.getByTestId("md-search-btn"));

  const found = await screen.findByTestId("md-candidate-e-9");
  expect(within(found).getByText(/намерено от човек/)).toBeInTheDocument();
});

test("a new official record cannot be created without an explicit confirmation", async () => {
  const user = userEvent.setup();
  await renderQueue(queue([PENDING_ROW]));
  await user.click(screen.getByTestId("md-expand-p-1"));

  const create = await screen.findByTestId("md-create-btn");
  expect(create).toBeDisabled();

  await user.click(screen.getByTestId("md-create-confirm"));
  expect(create).toBeEnabled();

  await user.click(create);
  expect(API.post).toHaveBeenCalledWith("/master-data/pending/p-1/approve",
    { confirmation: true, create_new: true, display_name: "Баумит ЕООД" });
});

test("the office can correct the name before the record becomes official", async () => {
  const user = userEvent.setup();
  await renderQueue(queue([PENDING_ROW]));
  await user.click(screen.getByTestId("md-expand-p-1"));

  const name = await screen.findByTestId("md-create-name");
  await user.clear(name);
  await user.type(name, "Баумит България ЕООД");
  await user.click(screen.getByTestId("md-create-confirm"));
  await user.click(screen.getByTestId("md-create-btn"));

  expect(API.post).toHaveBeenCalledWith("/master-data/pending/p-1/approve",
    expect.objectContaining({ display_name: "Баумит България ЕООД", create_new: true }));
});

test("a rejection without a reason is refused before it reaches the server", async () => {
  const user = userEvent.setup();
  await renderQueue(queue([PENDING_ROW]));
  await user.click(screen.getByTestId("md-expand-p-1"));

  await user.click(await screen.findByTestId("md-reject-btn"));

  expect(API.post).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith("Отказът иска причина.");
});

test("a rejection with a reason sends it", async () => {
  const user = userEvent.setup();
  await renderQueue(queue([PENDING_ROW]));
  await user.click(screen.getByTestId("md-expand-p-1"));

  await user.type(await screen.findByTestId("md-reject-reason"), "не е фирма");
  await user.click(screen.getByTestId("md-reject-btn"));

  expect(API.post).toHaveBeenCalledWith("/master-data/pending/p-1/reject", { reason: "не е фирма" });
});

test("a refusal from the server is shown and the proposal stays in the queue", async () => {
  const user = userEvent.setup();
  await renderQueue(queue([PENDING_ROW]));
  await user.click(screen.getByTestId("md-expand-p-1"));
  API.post.mockRejectedValue(httpError(409, "another reviewer claimed it first"));

  await user.click(await screen.findByTestId("md-create-confirm"));
  await user.click(screen.getByTestId("md-create-btn"));

  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("another reviewer claimed it first"));
  expect(screen.getByTestId("md-row-p-1")).toBeInTheDocument();
});

// ------------------------------------------------------------------ outcomes

test("a resolved proposal shows who decided it and what it became", async () => {
  await renderQueue(queue([{
    ...PENDING_ROW, status: "resolved", resolved_by: "office-1", resolved_entity_id: "e-1",
  }]));

  const outcome = screen.getByTestId("md-outcome-p-1");
  expect(outcome).toHaveTextContent("office-1");
  expect(outcome).toHaveTextContent("e-1");
});

test("a rejected proposal shows who rejected it and why", async () => {
  await renderQueue(queue([{
    ...PENDING_ROW, status: "rejected", resolved_by: "office-2", rejection_reason: "не е фирма",
  }]));

  const outcome = screen.getByTestId("md-outcome-p-1");
  expect(outcome).toHaveTextContent("office-2");
  expect(outcome).toHaveTextContent("не е фирма");
});

test("a decided proposal offers no decision buttons", async () => {
  const user = userEvent.setup();
  await renderQueue(queue([{ ...PENDING_ROW, status: "resolved", resolved_by: "office-1" }]));

  await user.click(screen.getByTestId("md-expand-p-1"));

  expect(screen.queryByTestId("md-create-btn")).not.toBeInTheDocument();
  expect(screen.queryByTestId("md-reject-btn")).not.toBeInTheDocument();
});
