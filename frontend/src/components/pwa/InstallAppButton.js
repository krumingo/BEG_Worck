// PWA-01 — "Инсталирай приложението": shown only when the browser offers an install
// prompt, or on iOS Safari (instructions), and never inside the installed app.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Share, PlusSquare, X } from "lucide-react";
import { useStore } from "@/lib/pwa/store";
import { installStore, promptInstall, isIOS, isStandalone } from "@/lib/pwa/install";

export function IosInstallSteps({ onClose }) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/60 p-4 sm:items-center" role="dialog" aria-modal="true" aria-labelledby="pwa-ios-title" data-testid="pwa-ios-steps">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-5 text-foreground shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="pwa-ios-title" className="text-base font-semibold">{t("pwa.iosTitle", "Инсталиране на iPhone / iPad")}</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label={t("pwa.close", "Затвори")}><X className="h-4 w-4" /></button>
        </div>
        <ol className="space-y-3 text-sm">
          <li className="flex gap-3"><Share className="h-5 w-5 shrink-0 text-primary" /><span>{t("pwa.iosStep1")}</span></li>
          <li className="flex gap-3"><PlusSquare className="h-5 w-5 shrink-0 text-primary" /><span>{t("pwa.iosStep2")}</span></li>
          <li className="flex gap-3"><Download className="h-5 w-5 shrink-0 text-primary" /><span>{t("pwa.iosStep3")}</span></li>
        </ol>
      </div>
    </div>
  );
}

export default function InstallAppButton({ className = "", testId = "pwa-install-button" }) {
  const { t } = useTranslation();
  const { prompt, installed } = useStore(installStore);
  const [showIos, setShowIos] = useState(false);
  if (installed || isStandalone()) return null;
  const ios = !prompt && isIOS();
  if (!prompt && !ios) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => (ios ? setShowIos(true) : promptInstall())}
        className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-primary hover:bg-primary/10 ${className}`}
        data-testid={testId}
      >
        <Download className="h-4 w-4 shrink-0" />
        <span>{t("pwa.install", "Инсталирай приложението")}</span>
      </button>
      {showIos && <IosInstallSteps onClose={() => setShowIos(false)} />}
    </>
  );
}
