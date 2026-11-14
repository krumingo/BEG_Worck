// FG-637: the phone tells the user at capture, with the server's own limits (10 MB, image
// types only); FG-639: the button is hidden where the server would refuse the photo.
import { render, screen } from "@testing-library/react";

jest.mock("@/lib/api", () => ({ __esModule: true, default: { post: jest.fn() } }));
jest.mock("@/lib/offline", () => ({ __esModule: true, sendOrQueue: jest.fn(), STATUS: { saved: "Записано" } }));
jest.mock("@/lib/offline/crypto", () => ({ __esModule: true, sha256Hex: jest.fn() }));
jest.mock("sonner", () => ({ __esModule: true, toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("@/components/ui/button", () => ({ __esModule: true, Button: (p) => <button {...p} /> }));

import SitePhotoButton, { photoProblem, PHOTO_MAX } from "@/components/offline/SitePhotoButton";

test("the limit is the server's 10 MB and only image types pass", () => {
  expect(PHOTO_MAX).toBe(10 * 1024 * 1024);
  expect(photoProblem({ type: "image/jpeg", size: PHOTO_MAX })).toBeNull();
  expect(photoProblem({ type: "image/jpeg", size: PHOTO_MAX + 1 })).toMatch("10 MB");
  expect(photoProblem({ type: "image/svg+xml", size: 10 })).toMatch("Само снимка");
  expect(photoProblem({ type: "video/mp4", size: 10 })).toMatch("Само снимка");
});

test("hidden where the server would refuse, shown otherwise", () => {
  const { rerender } = render(<SitePhotoButton projectId="p1" allowed={false} />);
  expect(screen.queryByTestId("site-photo-button")).toBeNull();
  rerender(<SitePhotoButton projectId="p1" allowed />);
  expect(screen.getByTestId("site-photo-button")).toBeInTheDocument();
});
