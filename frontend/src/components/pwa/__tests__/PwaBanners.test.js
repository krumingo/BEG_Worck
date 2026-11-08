// PWA-01 — offline bar, update bar and install button.
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";

jest.mock("react-i18next", () => ({ __esModule: true, useTranslation: () => ({ t: (k, d) => (typeof d === "string" ? d : k) }) }));

import PwaBanners from "@/components/pwa/PwaBanners";
import InstallAppButton from "@/components/pwa/InstallAppButton";
import { connectivityStore } from "@/lib/pwa/connectivity";
import { updateStore } from "@/lib/pwa/serviceWorker";
import { installStore } from "@/lib/pwa/install";

const realUA = navigator.userAgent;
function setUA(ua) { Object.defineProperty(window.navigator, "userAgent", { value: ua, configurable: true }); }

beforeEach(() => {
  connectivityStore.set({ browserOnline: true, networkFailed: false });
  updateStore.set({ waiting: null });
  installStore.set({ prompt: null, installed: false });
  setUA(realUA);
});

test("online and current: no bars", () => {
  render(<PwaBanners />);
  expect(screen.queryByTestId("pwa-offline-banner")).toBeNull();
  expect(screen.queryByTestId("pwa-update-banner")).toBeNull();
});

test("offline: the Без връзка bar is shown and goes away when back online", () => {
  render(<PwaBanners />);
  act(() => connectivityStore.set({ browserOnline: false, networkFailed: false }));
  expect(screen.getByTestId("pwa-offline-banner").textContent).toContain("Без връзка — промените няма да се запишат");
  act(() => connectivityStore.set({ browserOnline: true, networkFailed: false }));
  expect(screen.queryByTestId("pwa-offline-banner")).toBeNull();
});

test("a failed request alone also shows the bar", () => {
  render(<PwaBanners />);
  act(() => connectivityStore.set({ browserOnline: true, networkFailed: true }));
  expect(screen.getByTestId("pwa-offline-banner")).toBeTruthy();
});

test("a waiting version shows Обнови; По-късно hides it without activating", () => {
  const waiting = { postMessage: jest.fn() };
  render(<PwaBanners />);
  act(() => updateStore.set({ waiting }));
  expect(screen.getByTestId("pwa-update-banner").textContent).toContain("Има нова версия");
  fireEvent.click(screen.getByTestId("pwa-update-later"));
  expect(screen.queryByTestId("pwa-update-banner")).toBeNull();
  expect(waiting.postMessage).not.toHaveBeenCalled();
});

test("Обнови sends SKIP_WAITING to the waiting worker", () => {
  const waiting = { postMessage: jest.fn() };
  const sw = { addEventListener: jest.fn() };
  Object.defineProperty(window.navigator, "serviceWorker", { value: sw, configurable: true });
  render(<PwaBanners />);
  act(() => updateStore.set({ waiting }));
  fireEvent.click(screen.getByTestId("pwa-update-apply"));
  expect(waiting.postMessage).toHaveBeenCalledWith({ type: "SKIP_WAITING" });
  delete window.navigator.serviceWorker;
});

test("install button: hidden without a browser prompt", () => {
  render(<InstallAppButton />);
  expect(screen.queryByTestId("pwa-install-button")).toBeNull();
});

test("install button: shown with a prompt and calls it", async () => {
  const prompt = { prompt: jest.fn(), userChoice: Promise.resolve({ outcome: "accepted" }) };
  render(<InstallAppButton />);
  act(() => installStore.set({ prompt, installed: false }));
  await act(async () => { fireEvent.click(screen.getByTestId("pwa-install-button")); });
  expect(prompt.prompt).toHaveBeenCalled();
  expect(screen.queryByTestId("pwa-install-button")).toBeNull();
});

test("iOS: install button opens the Share → Add to Home Screen steps", () => {
  setUA("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1");
  render(<InstallAppButton />);
  fireEvent.click(screen.getByTestId("pwa-install-button"));
  expect(screen.getByTestId("pwa-ios-steps")).toBeTruthy();
});
