/**
 * Bot F-2 — a toast is visible: <AppToaster/> is mounted once at the app root and the
 * sonner `toast()` calls of the screens (confirmations, 403/409 errors) render text.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";
import { toast } from "sonner";
import AppToaster from "@/components/AppToaster";

beforeAll(() => {
  // jsdom has no matchMedia; sonner / next-themes ask for it
  window.matchMedia = window.matchMedia || ((q) => ({
    matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }));
});

test("a success toast renders its Bulgarian text", async () => {
  render(<AppToaster />);
  act(() => { toast.success("Количеството е одобрено"); });
  expect(await screen.findByText("Количеството е одобрено")).toBeInTheDocument();
});

test("an error toast renders (e.g. a 403 from the server)", async () => {
  render(<AppToaster />);
  act(() => { toast.error("Не можете да одобрите собствената си работа"); });
  expect(await screen.findByText("Не можете да одобрите собствената си работа")).toBeInTheDocument();
});

test("the app root mounts exactly one toaster", () => {
  const fs = require("fs");
  const path = require("path");
  const app = fs.readFileSync(path.join(__dirname, "..", "..", "App.js"), "utf8");
  expect((app.match(/<AppToaster\s*\/>/g) || []).length).toBe(1);
});
