import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import AuthScreen from "@/components/AuthScreen";
import { passwordChecks } from "@/lib/passwordPolicy";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertCircle, CheckCircle2, Circle, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";

// AUTH-01 — /reset-password?token=… from the e-mailed link. New password twice,
// the policy shown live, and on success one way on: back to the login page.
export default function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = (searchParams.get("token") || "").trim();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [linkInvalid, setLinkInvalid] = useState(!token);
  const [done, setDone] = useState(false);

  const checks = passwordChecks(password);
  const policyOk = checks.every((c) => c.ok);
  const mismatch = confirm.length > 0 && confirm !== password;
  const canSubmit = policyOk && confirm === password && !saving;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!policyOk) {
      setError(t("auth.passwordRequirements"));
      return;
    }
    if (password !== confirm) {
      setError(t("auth.passwordMismatch"));
      return;
    }
    setSaving(true);
    try {
      await API.post("/auth/reset-password", { token, new_password: password });
      setDone(true);
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;
      if (detail && typeof detail === "object" && detail.error_code === "RESET_TOKEN_INVALID") {
        setLinkInvalid(true);
      } else if (status === 429) {
        setError(t("auth.tooManyRequests"));
      } else if (status === 400 && typeof detail === "string") {
        setError(detail);
      } else {
        setError(t("auth.genericError"));
      }
    } finally {
      setSaving(false);
    }
  };

  if (done) {
    return (
      <AuthScreen title={t("auth.resetTitle")} testId="reset-password-page">
        <div className="space-y-5 text-center" data-testid="reset-password-success">
          <div className="mx-auto w-12 h-12 rounded-full bg-emerald-500/10 flex items-center justify-center">
            <ShieldCheck className="w-6 h-6 text-emerald-500" />
          </div>
          <p className="text-sm text-foreground">{t("auth.resetSuccess")}</p>
          <Button className="w-full h-11 font-semibold" onClick={() => navigate("/login", { replace: true })} data-testid="reset-go-to-login">
            {t("auth.goToLogin")}
          </Button>
        </div>
      </AuthScreen>
    );
  }

  if (linkInvalid) {
    return (
      <AuthScreen title={t("auth.resetTitle")} testId="reset-password-page">
        <div className="space-y-5 text-center" data-testid="reset-link-invalid">
          <div className="mx-auto w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center">
            <AlertCircle className="w-6 h-6 text-destructive" />
          </div>
          <p className="text-sm text-foreground">{t("auth.resetLinkInvalid")}</p>
          <Button asChild className="w-full h-11 font-semibold">
            <Link to="/forgot-password" data-testid="reset-request-new-link">{t("auth.requestNewLink")}</Link>
          </Button>
          <Link to="/login" className="block text-sm text-primary hover:underline">{t("auth.backToLogin")}</Link>
        </div>
      </AuthScreen>
    );
  }

  return (
    <AuthScreen title={t("auth.resetTitle")} subtitle={t("auth.resetSubtitle")} testId="reset-password-page">
      <form onSubmit={handleSubmit} className="space-y-4" data-testid="reset-password-form" noValidate>
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm" data-testid="reset-error">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="reset-new" className="text-sm text-muted-foreground">{t("auth.newPassword")}</Label>
          <div className="relative">
            <Input
              id="reset-new"
              type={show ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-background border-border h-11 pr-11"
              data-testid="reset-new-password"
            />
            <button
              type="button"
              onClick={() => setShow((v) => !v)}
              aria-label={t("auth.showPassword")}
              className="absolute right-0 top-0 h-11 w-11 flex items-center justify-center text-muted-foreground hover:text-foreground"
              data-testid="reset-toggle-visibility"
            >
              {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1.5 text-xs" data-testid="reset-requirements">
          {checks.map((c) => (
            <li
              key={c.key}
              className={`flex items-center gap-1.5 ${c.ok ? "text-emerald-500" : "text-muted-foreground"}`}
              data-testid={`req-${c.key}`}
              data-ok={String(c.ok)}
            >
              {c.ok ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0" /> : <Circle className="w-3.5 h-3.5 shrink-0" />}
              {t(c.labelKey)}
            </li>
          ))}
        </ul>

        <div className="space-y-2">
          <Label htmlFor="reset-confirm" className="text-sm text-muted-foreground">{t("auth.confirmPassword")}</Label>
          <Input
            id="reset-confirm"
            type={show ? "text" : "password"}
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="bg-background border-border h-11"
            data-testid="reset-confirm-password"
          />
          {mismatch && (
            <p className="text-xs text-destructive" data-testid="reset-mismatch">{t("auth.passwordMismatch")}</p>
          )}
        </div>

        <Button type="submit" className="w-full h-11 font-semibold" disabled={!canSubmit} data-testid="reset-submit-button">
          {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
          {t("auth.savePassword")}
        </Button>
        <div className="text-center">
          <Link to="/login" className="text-sm text-primary hover:underline">{t("auth.backToLogin")}</Link>
        </div>
      </form>
    </AuthScreen>
  );
}
