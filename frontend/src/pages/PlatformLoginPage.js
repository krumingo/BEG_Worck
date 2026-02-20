import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Shield, Loader2, AlertCircle } from "lucide-react";

export default function PlatformLoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // Step 1: Login
      const loginRes = await API.post("/auth/login", { email, password });
      const { token, user } = loginRes.data;
      
      // Check if platform admin from login response
      if (!user.is_platform_admin) {
        setError(t("platform.notPlatformAdmin", "Нямате SuperAdmin достъп"));
        return;
      }
      
      // Store token and user data
      localStorage.setItem("bw_token", token);
      localStorage.setItem("bw_user", JSON.stringify(user));
      
      // Redirect to platform dashboard
      navigate("/platform");
      
    } catch (err) {
      setError(err.response?.data?.detail || t("auth.loginFailed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4" data-testid="platform-login-page">
      {/* Grid background */}
      <div className="absolute inset-0 opacity-[0.02]"
        style={{
          backgroundImage: "radial-gradient(circle at 1px 1px, #fff 1px, transparent 0)",
          backgroundSize: "32px 32px",
        }}
      />

      <div className="relative w-full max-w-[400px] animate-in">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-600 to-indigo-700 flex items-center justify-center mb-4 shadow-lg shadow-violet-500/30">
            <Shield className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Platform Admin</h1>
          <p className="text-sm text-slate-400 mt-1">BEG_Work System Management</p>
        </div>

        {/* Form */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 backdrop-blur-sm p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm" data-testid="platform-login-error">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                {error}
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="email" className="text-sm text-slate-400">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@example.com"
                required
                className="bg-slate-800/50 border-slate-700 text-white placeholder:text-slate-500"
                data-testid="platform-login-email"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password" className="text-sm text-slate-400">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••"
                required
                className="bg-slate-800/50 border-slate-700 text-white placeholder:text-slate-500"
                data-testid="platform-login-password"
              />
            </div>

            <Button
              type="submit"
              className="w-full h-11 font-semibold bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white border-0"
              disabled={loading}
              data-testid="platform-login-submit"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
              {t("auth.signIn", "Sign In")}
            </Button>
          </form>

          <div className="mt-6 pt-4 border-t border-slate-800">
            <p className="text-xs text-slate-500 text-center">
              This portal is for platform administrators only.
              <br />
              Regular users should use the <a href="/login" className="text-violet-400 hover:underline">client login</a>.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
