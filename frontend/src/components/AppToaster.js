// The one toast host of the app (bot F-2): screens call sonner `toast()` for confirmations
// and errors (403 / 409 …); without a mounted <Toaster/> none of them was ever visible.
// Top-center fits a 390 px phone; rich colours tell success from error at a glance.
import { Toaster } from "@/components/ui/sonner";

export default function AppToaster() {
  return (
    <Toaster
      position="top-center"
      richColors
      closeButton
      duration={4000}
      toastOptions={{ closeButtonAriaLabel: "Затвори" }}
    />
  );
}
