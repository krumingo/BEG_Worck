import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { HardHat, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

export default function SignupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    org_name: "",
    owner_name: "",
    owner_email: "",
    password: "",
    confirm_password: "",
  });

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    // Validation
    if (!form.org_name.trim()) {
      setError(t("billing.companyNameRequired"));
      return;
    }
    if (!form.owner_name.trim()) {
      setError(t("billing.nameRequired"));
      return;
    }
    if (!form.owner_email.trim()) {
      setError(t("validation.invalidEmail"));
      return;
    }
    if (form.password.length < 6) {
      setError(t("validation.minLength", { min: 6 }));
      return;
    }
    if (form.password !== form.confirm_password) {
      setError(t("validation.passwordMismatch"));
      return;
    }

    setLoading(true);
    try {
      const res = await api.post("/billing/signup", {
        org_name: form.org_name.trim(),
        owner_name: form.owner_name.trim(),
        owner_email: form.owner_email.trim().toLowerCase(),
        password: form.password,
      });

      // Auto-login with returned token
      localStorage.setItem("bw_token", res.data.token);
      localStorage.setItem("bw_user", JSON.stringify(res.data.user));
      api.defaults.headers.common["Authorization"] = `Bearer ${res.data.token}`;
      
      toast.success(t("billing.signupSuccess"));
      // Reload to trigger AuthContext to fetch user data
      window.location.href = "/";
    } catch (err) {
      const msg = err.response?.data?.detail || t("toast.createFailed");
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-muted p-4" data-testid="signup-page">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1 text-center">
          <div className="flex justify-center mb-4">
            <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center">
              <HardHat className="w-6 h-6 text-primary-foreground" />
            </div>
          </div>
          <CardTitle className="text-2xl font-bold">{t("billing.createAccount")}</CardTitle>
          <CardDescription>{t("billing.startFreeTrial")}</CardDescription>
        </CardHeader>
        
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {error && (
              <div className="flex items-center gap-2 p-3 text-sm text-destructive bg-destructive/10 rounded-lg" data-testid="signup-error">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="org_name">{t("billing.companyName")}</Label>
              <Input
                id="org_name"
                name="org_name"
                placeholder={t("billing.companyNamePlaceholder")}
                value={form.org_name}
                onChange={handleChange}
                disabled={loading}
                data-testid="signup-org-name"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="owner_name">{t("billing.yourName")}</Label>
              <Input
                id="owner_name"
                name="owner_name"
                placeholder={t("billing.yourNamePlaceholder")}
                value={form.owner_name}
                onChange={handleChange}
                disabled={loading}
                data-testid="signup-owner-name"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="owner_email">{t("common.email")}</Label>
              <Input
                id="owner_email"
                name="owner_email"
                type="email"
                placeholder="you@company.com"
                value={form.owner_email}
                onChange={handleChange}
                disabled={loading}
                data-testid="signup-email"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">{t("common.password")}</Label>
              <Input
                id="password"
                name="password"
                type="password"
                placeholder="••••••••"
                value={form.password}
                onChange={handleChange}
                disabled={loading}
                data-testid="signup-password"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirm_password">{t("billing.confirmPassword")}</Label>
              <Input
                id="confirm_password"
                name="confirm_password"
                type="password"
                placeholder="••••••••"
                value={form.confirm_password}
                onChange={handleChange}
                disabled={loading}
                data-testid="signup-confirm-password"
              />
            </div>

            <div className="flex items-start gap-2 text-sm text-muted-foreground">
              <CheckCircle2 className="w-4 h-4 mt-0.5 text-green-500" />
              <span>{t("billing.trialBenefit")}</span>
            </div>
          </CardContent>

          <CardFooter className="flex flex-col gap-4">
            <Button type="submit" className="w-full" disabled={loading} data-testid="signup-submit">
              {loading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {t("billing.startTrial")}
            </Button>
            
            <p className="text-sm text-center text-muted-foreground">
              {t("billing.alreadyHaveAccount")}{" "}
              <Link to="/login" className="text-primary hover:underline" data-testid="signup-login-link">
                {t("auth.signIn")}
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
