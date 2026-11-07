import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import AuthScreen from "@/components/AuthScreen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertCircle, ArrowLeft, Loader2, MailCheck } from "lucide-react";

// AUTH-01 — "Забравена парола?". The server answers the same sentence whether
// or not the account exists, and so does this screen: after a successful
// request it always shows the one generic confirmation.
export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await API.post("/auth/forgot-password", { email: email.trim() });
      setSent(true);
    } catch (err) {
      setError(err.response?.status === 429 ? t("auth.tooManyRequests") : t("auth.genericError"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthScreen title={t("auth.forgotTitle")} subtitle={sent ? null : t("auth.forgotSubtitle")} testId="forgot-password-page">
      {sent ? (
        <div className="space-y-5 text-center" data-testid="forgot-password-confirmation">
          <div className="mx-auto w-12 h-12 rounded-full bg-emerald-500/10 flex items-center justify-center">
            <MailCheck className="w-6 h-6 text-emerald-500" />
          </div>
          <p className="text-sm text-foreground leading-relaxed">{t("auth.forgotConfirmation")}</p>
          <p className="text-xs text-muted-foreground">{t("auth.forgotLinkValidity")}</p>
          <Button asChild variant="outline" className="w-full h-11">
            <Link to="/login" data-testid="forgot-back-to-login">{t("auth.backToLogin")}</Link>
          </Button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4" data-testid="forgot-password-form">
          {error && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm" data-testid="forgot-password-error">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="forgot-email" className="text-sm text-muted-foreground">{t("auth.email")}</Label>
            <Input
              id="forgot-email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("auth.enterEmail")}
              required
              className="bg-background border-border h-11"
              data-testid="forgot-email-input"
            />
          </div>
          <Button type="submit" className="w-full h-11 font-semibold" disabled={loading || !email.trim()} data-testid="forgot-submit-button">
            {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
            {t("auth.sendLink")}
          </Button>
          <div className="text-center">
            <Link to="/login" className="inline-flex items-center gap-1 text-sm text-primary hover:underline" data-testid="forgot-back-link">
              <ArrowLeft className="w-4 h-4" />
              {t("auth.backToLogin")}
            </Link>
          </div>
        </form>
      )}
    </AuthScreen>
  );
}
