// PWA-01 — global "Без връзка" and "Има нова версия — Обнови" bars.
// Fixed at the bottom, above the mobile tab bar, so they never hide the header.
import { useTranslation } from "react-i18next";
import { WifiOff, RefreshCw } from "lucide-react";
import { useStore } from "@/lib/pwa/store";
import { connectivityStore, isOffline } from "@/lib/pwa/connectivity";
import { updateStore, applyUpdate } from "@/lib/pwa/serviceWorker";

export function OfflineBanner() {
  const { t } = useTranslation();
  const offline = isOffline(useStore(connectivityStore));
  if (!offline) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="pwa-offline-banner"
      className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive px-4 py-2.5 text-sm font-medium text-destructive-foreground shadow-lg"
    >
      <WifiOff className="h-4 w-4 shrink-0" />
      <span>{t("pwa.offline", "Без връзка — промените няма да се запишат")}</span>
    </div>
  );
}

export function UpdateBanner() {
  const { t } = useTranslation();
  const { waiting } = useStore(updateStore);
  if (!waiting) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="pwa-update-banner"
      className="flex items-center gap-3 rounded-lg border border-primary/40 bg-card px-4 py-2.5 text-sm text-foreground shadow-lg"
    >
      <RefreshCw className="h-4 w-4 shrink-0 text-primary" />
      <span className="flex-1">{t("pwa.updateAvailable", "Има нова версия")}</span>
      <button
        type="button"
        onClick={() => updateStore.set({ waiting: null })}
        className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
        data-testid="pwa-update-later"
      >
        {t("pwa.later", "По-късно")}
      </button>
      <button
        type="button"
        onClick={() => applyUpdate()}
        className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
        data-testid="pwa-update-apply"
      >
        {t("pwa.update", "Обнови")}
      </button>
    </div>
  );
}

export default function PwaBanners() {
  return (
    <div
      className="pointer-events-none fixed inset-x-0 z-[70] flex flex-col items-center gap-2 px-4 bottom-[calc(env(safe-area-inset-bottom)+5rem)] md:bottom-4"
      data-testid="pwa-banners"
    >
      <div className="pointer-events-auto w-full max-w-md empty:hidden"><UpdateBanner /></div>
      <div className="pointer-events-auto w-full max-w-md empty:hidden"><OfflineBanner /></div>
    </div>
  );
}
