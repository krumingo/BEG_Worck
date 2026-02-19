import { useState } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Loader2, KeyRound, Eye, EyeOff, AlertCircle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

export default function AdminResetPasswordModal({ open, onOpenChange, user, onSuccess }) {
  const { t } = useTranslation();
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleClose = () => {
    setNewPassword("");
    setConfirmPassword("");
    setShowPassword(false);
    setError("");
    onOpenChange(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (newPassword !== confirmPassword) {
      setError(t("users.passwordMismatch"));
      return;
    }

    setSaving(true);
    try {
      await API.post(`/admin/set-password/${user.id}`, {
        new_password: newPassword,
      });
      toast.success(t("users.passwordResetSuccess"));
      handleClose();
      if (onSuccess) onSuccess();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === "string" ? detail : t("users.passwordResetFailed"));
    } finally {
      setSaving(false);
    }
  };

  if (!user) return null;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[420px] bg-card border-border" data-testid="reset-password-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="w-5 h-5 text-primary" />
            {t("users.resetPasswordTitle")}
          </DialogTitle>
          <DialogDescription>
            {t("users.resetPasswordFor")} <strong>{user.first_name} {user.last_name}</strong> ({user.email})
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          {error && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 text-destructive text-sm" data-testid="reset-password-error">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          <div className="space-y-2">
            <Label className="text-muted-foreground">{t("users.newPassword")}</Label>
            <div className="relative">
              <Input
                type={showPassword ? "text" : "password"}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Min. 10 chars, A-Z, a-z, 0-9, !@#..."
                className="bg-background pr-10"
                data-testid="new-password-input"
                required
                minLength={10}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-muted-foreground">{t("users.confirmNewPassword")}</Label>
            <div className="relative">
              <Input
                type={showPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder={t("users.confirmNewPassword")}
                className="bg-background pr-10"
                data-testid="confirm-password-input"
                required
                minLength={10}
              />
              {confirmPassword && newPassword === confirmPassword && (
                <CheckCircle2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-emerald-500" />
              )}
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            {t("auth.passwordRequirements")}
          </p>

          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              className="flex-1"
              disabled={saving}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              className="flex-1"
              disabled={saving || !newPassword || !confirmPassword}
              data-testid="reset-password-submit"
            >
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              {t("users.resetPassword")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
