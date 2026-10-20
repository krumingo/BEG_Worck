/**
 * AUTH-01 — login link, Forgot Password and Reset Password screens.
 *
 *   * the login page offers "Забравена парола?" and no longer shows the stale
 *     admin@begwork.com / admin123 demo credentials;
 *   * forgot-password sends the email and always shows the ONE generic
 *     confirmation — the screen cannot tell an existing account from a missing
 *     one because the server does not;
 *   * reset-password shows the policy live, refuses a mismatch or a weak password
 *     before any request, sends {token, new_password}, turns an invalid/expired
 *     link into "request a new link", and on success leads to the login page;
 *   * both screens render inside a phone-width viewport with the page gutter.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@/i18n";

// react-router-dom 7 does not load under jest 27 (see MasterDataRoute.test.js);
// these stand-ins record where a link points and where navigation goes.
const mockNavigate = jest.fn();
let mockSearch = "";
jest.mock("react-router-dom", () => ({
  __esModule: true,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
  useNavigate: () => mockNavigate,
  useSearchParams: () => [new URLSearchParams(mockSearch)],
}), { virtual: true });
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));
const mockLogin = jest.fn();
jest.mock("@/contexts/AuthContext", () => ({
  __esModule: true,
  useAuth: () => ({ login: mockLogin }),
}));

import API from "@/lib/api";
import LoginPage from "@/pages/LoginPage";
import ForgotPasswordPage from "@/pages/ForgotPasswordPage";
import ResetPasswordPage from "@/pages/ResetPasswordPage";

const GOOD = "Brand-New-Pass-77!";
const CONFIRMATION = "Ако има активен акаунт с този имейл, изпратихме линк за смяна на паролата.";

function httpError(status, detail) {
  return { response: { status, data: { detail } } };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSearch = "";
  window.innerWidth = 1280;
});

// ───────────────────────────────────────────────────────────────── login
test("login offers the forgot-password link", () => {
  render(<LoginPage />);
  const link = screen.getByTestId("forgot-password-link");
  expect(link).toHaveTextContent("Забравена парола?");
  expect(link).toHaveAttribute("href", "/forgot-password");
});

test("login no longer shows the stale demo credentials", () => {
  const { container } = render(<LoginPage />);
  expect(container.innerHTML).not.toMatch(/admin123/);
  expect(container.innerHTML).not.toMatch(/admin@begwork\.com/);
  expect(screen.getByTestId("login-email-input")).toHaveAttribute("placeholder", "Въведете имейл");
});

// ───────────────────────────────────────────────────────────────── forgot
test("forgot-password sends the email and shows the generic confirmation", async () => {
  API.post.mockResolvedValue({ data: { ok: true } });
  render(<ForgotPasswordPage />);
  await userEvent.type(screen.getByTestId("forgot-email-input"), "  Krum@begfull.bg ");
  await userEvent.click(screen.getByTestId("forgot-submit-button"));
  await waitFor(() => expect(screen.getByTestId("forgot-password-confirmation")).toBeInTheDocument());
  expect(API.post).toHaveBeenCalledWith("/auth/forgot-password", { email: "Krum@begfull.bg" });
  expect(screen.getByTestId("forgot-password-confirmation")).toHaveTextContent(CONFIRMATION);
  expect(screen.getByTestId("forgot-back-to-login")).toHaveAttribute("href", "/login");
});

test("the confirmation is the same for any email the server accepted", async () => {
  const texts = [];
  for (const email of ["nobody@nowhere.bg", "krum@begfull.bg"]) {
    API.post.mockResolvedValue({ data: { ok: true } });
    const { unmount } = render(<ForgotPasswordPage />);
    await userEvent.type(screen.getByTestId("forgot-email-input"), email);
    await userEvent.click(screen.getByTestId("forgot-submit-button"));
    texts.push((await screen.findByTestId("forgot-password-confirmation")).textContent);
    unmount();
  }
  expect(texts[0]).toBe(texts[1]);
});

test("forgot-password: send button is labelled and a rate limit is explained", async () => {
  API.post.mockRejectedValue(httpError(429, "Too many requests. Try again later."));
  render(<ForgotPasswordPage />);
  expect(screen.getByTestId("forgot-submit-button")).toHaveTextContent("Изпрати линк");
  expect(screen.getByTestId("forgot-submit-button")).toBeDisabled();
  await userEvent.type(screen.getByTestId("forgot-email-input"), "krum@begfull.bg");
  await userEvent.click(screen.getByTestId("forgot-submit-button"));
  expect(await screen.findByTestId("forgot-password-error")).toHaveTextContent("Твърде много опити");
  expect(screen.queryByTestId("forgot-password-confirmation")).not.toBeInTheDocument();
});

// ───────────────────────────────────────────────────────────────── reset
async function fill(password, confirm = password) {
  await userEvent.type(screen.getByTestId("reset-new-password"), password);
  await userEvent.type(screen.getByTestId("reset-confirm-password"), confirm);
}

test("reset without a token shows the invalid-link state", () => {
  mockSearch = "";
  render(<ResetPasswordPage />);
  expect(screen.getByTestId("reset-link-invalid")).toBeInTheDocument();
  expect(screen.getByTestId("reset-request-new-link")).toHaveAttribute("href", "/forgot-password");
});

test("reset shows the requirements live and blocks a weak password", async () => {
  mockSearch = "?token=tok-123456789012345678901234567890";
  render(<ResetPasswordPage />);
  expect(screen.getByTestId("req-length")).toHaveAttribute("data-ok", "false");
  await fill("weak");
  expect(screen.getByTestId("req-length")).toHaveAttribute("data-ok", "false");
  expect(screen.getByTestId("req-lower")).toHaveAttribute("data-ok", "true");
  expect(screen.getByTestId("reset-submit-button")).toBeDisabled();
  await userEvent.clear(screen.getByTestId("reset-new-password"));
  await userEvent.type(screen.getByTestId("reset-new-password"), GOOD);
  for (const key of ["length", "upper", "lower", "digit", "special"]) {
    expect(screen.getByTestId(`req-${key}`)).toHaveAttribute("data-ok", "true");
  }
  expect(API.post).not.toHaveBeenCalled();
});

test("reset refuses a mismatched confirmation before any request", async () => {
  mockSearch = "?token=tok-123456789012345678901234567890";
  render(<ResetPasswordPage />);
  await fill(GOOD, GOOD + "x");
  expect(screen.getByTestId("reset-mismatch")).toHaveTextContent("Паролите не съвпадат");
  expect(screen.getByTestId("reset-submit-button")).toBeDisabled();
  expect(API.post).not.toHaveBeenCalled();
});

test("reset success leads back to the login page", async () => {
  mockSearch = "?token=tok-123456789012345678901234567890";
  API.post.mockResolvedValue({ data: { ok: true } });
  render(<ResetPasswordPage />);
  await fill(GOOD);
  await userEvent.click(screen.getByTestId("reset-submit-button"));
  await screen.findByTestId("reset-password-success");
  expect(API.post).toHaveBeenCalledWith("/auth/reset-password", {
    token: "tok-123456789012345678901234567890",
    new_password: GOOD,
  });
  const go = screen.getByTestId("reset-go-to-login");
  expect(go).toHaveTextContent("Към вход");
  await userEvent.click(go);
  expect(mockNavigate).toHaveBeenCalledWith("/login", { replace: true });
});

test("an invalid or expired link turns into 'request a new link'", async () => {
  mockSearch = "?token=tok-123456789012345678901234567890";
  API.post.mockRejectedValue(httpError(400, {
    error_code: "RESET_TOKEN_INVALID",
    message: "This password reset link is invalid or has expired.",
  }));
  render(<ResetPasswordPage />);
  await fill(GOOD);
  await userEvent.click(screen.getByTestId("reset-submit-button"));
  expect(await screen.findByTestId("reset-link-invalid")).toBeInTheDocument();
  expect(screen.getByTestId("reset-request-new-link")).toHaveAttribute("href", "/forgot-password");
});

test("a server-side policy message is shown as it came", async () => {
  mockSearch = "?token=tok-123456789012345678901234567890";
  API.post.mockRejectedValue(httpError(400, "Password must contain at least one digit"));
  render(<ResetPasswordPage />);
  await fill(GOOD);
  await userEvent.click(screen.getByTestId("reset-submit-button"));
  expect(await screen.findByTestId("reset-error")).toHaveTextContent("at least one digit");
});

test("a reset the server could not commit keeps the form and says to try again", async () => {
  mockSearch = "?token=tok-123456789012345678901234567890";
  API.post.mockRejectedValue(httpError(503, {
    error_code: "RESET_NOT_COMPLETED",
    message: "The password was not changed. Please try again.",
  }));
  render(<ResetPasswordPage />);
  await fill(GOOD);
  await userEvent.click(screen.getByTestId("reset-submit-button"));
  expect(await screen.findByTestId("reset-error")).toHaveTextContent("Опитайте отново");
  expect(screen.queryByTestId("reset-link-invalid")).not.toBeInTheDocument();
  expect(screen.queryByTestId("reset-password-success")).not.toBeInTheDocument();
});

// ───────────────────────────────────────────────────────────────── mobile
test.each([
  ["forgot", () => <ForgotPasswordPage />, "forgot-password-page"],
  ["reset", () => <ResetPasswordPage />, "reset-password-page"],
  ["login", () => <LoginPage />, "login-page"],
])("%s renders at phone width with the page gutter", (_name, ui, testId) => {
  mockSearch = "?token=tok-123456789012345678901234567890";
  window.innerWidth = 375;
  window.dispatchEvent(new Event("resize"));
  const { container } = render(ui());
  const page = screen.getByTestId(testId);
  expect(page.className).toMatch(/\bpx-4\b/);
  expect(page.className).toMatch(/\bmin-h-screen\b/);
  // the card is fluid (w-full) and only capped on wide screens
  expect(container.querySelector(".max-w-\\[400px\\]").className).toMatch(/\bw-full\b/);
  // no fixed pixel width that could force a horizontal scroll on a phone
  expect(container.innerHTML).not.toMatch(/\bw-\[(?:[5-9]\d\d|\d{4,})px\]/);
  expect(container.querySelectorAll("input").length).toBeGreaterThan(0);
});
