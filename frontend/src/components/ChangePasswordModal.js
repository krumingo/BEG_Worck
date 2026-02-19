import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Eye, EyeOff, Lock, Check, X } from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

// Password validation rules
const validatePassword = (password) => {
  const rules = {
    minLength: password.length >= 10,
    hasUpper: /[A-Z]/.test(password),
    hasLower: /[a-z]/.test(password),
    hasDigit: /\d/.test(password),
    hasSpecial: /[!@#$%^&*()_+\-=[\]{}|;:,.<>?]/.test(password),
  };
  const isValid = Object.values(rules).every(Boolean);
  return { isValid, rules };
};

export default function ChangePasswordModal({ open, onOpenChange }) {
  const { t } = useTranslation();
  const { token } = useAuth();
  
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const { isValid: passwordValid, rules } = validatePassword(newPassword);
  const passwordsMatch = newPassword === confirmPassword && confirmPassword !== "";

  const resetForm = () => {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setError("");
    setShowCurrent(false);
    setShowNew(false);
    setShowConfirm(false);
  };

  const handleClose = () => {
    resetForm();
    onOpenChange(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    // Client-side validation
    if (!currentPassword) {
      setError(t("auth.currentPassword") + " " + t("common.required"));
      return;
    }
    if (!passwordValid) {
      setError(t("auth.passwordRequirements"));
      return;
    }
    if (!passwordsMatch) {
      setError(t("auth.passwordMismatch"));
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/auth/change-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        // Map backend errors to i18n keys
        const detail = data.detail || "";
        if (detail.includes("Current password is incorrect")) {
          setError(t("auth.currentPasswordIncorrect"));
        } else if (detail.includes("different from current")) {
          setError(t("auth.passwordSameAsCurrent"));
        } else if (detail.includes("at least 10")) {
          setError(t("auth.passwordTooShort"));
        } else if (detail.includes("uppercase")) {
          setError(t("auth.passwordNeedsUpper"));
        } else if (detail.includes("lowercase")) {
          setError(t("auth.passwordNeedsLower"));
        } else if (detail.includes("digit")) {
          setError(t("auth.passwordNeedsDigit"));
        } else if (detail.includes("special")) {
          setError(t("auth.passwordNeedsSpecial"));
        } else {
          setError(detail || t("common.error"));
        }
        return;
      }

      toast.success(t("auth.passwordChanged"));
      handleClose();
    } catch (err) {
      setError(t("common.error"));
    } finally {
      setLoading(false);
    }
  };

  const RuleIndicator = ({ passed, label }) => (
    <div className={`flex items-center gap-2 text-xs ${passed ? "text-green-500" : "text-muted-foreground"}`}>
      {passed ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
      <span>{label}</span>
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[425px]" data-testid="change-password-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Lock className="w-5 h-5" />
            {t("auth.changePassword")}
          </DialogTitle>
          <DialogDescription>
            {t("auth.passwordRequirements")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Current Password */}
          <div className="space-y-2">
            <Label htmlFor="current-password">{t("auth.currentPassword")}</Label>
            <div className="relative">
              <Input
                id="current-password"
                type={showCurrent ? "text" : "password"}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="••••••••••"
                data-testid="current-password-input"
                autoComplete="current-password"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="absolute right-0 top-0 h-full px-3"
                onClick={() => setShowCurrent(!showCurrent)}
              >
                {showCurrent ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </Button>
            </div>
          </div>

          {/* New Password */}
          <div className="space-y-2">
            <Label htmlFor="new-password">{t("auth.newPassword")}</Label>
            <div className="relative">
              <Input
                id="new-password"
                type={showNew ? "text" : "password"}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="••••••••••"
                data-testid="new-password-input"
                autoComplete="new-password"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="absolute right-0 top-0 h-full px-3"
                onClick={() => setShowNew(!showNew)}
              >
                {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </Button>
            </div>
            
            {/* Password strength indicators */}
            {newPassword && (
              <div className="grid grid-cols-2 gap-1 mt-2 p-2 bg-muted rounded-md">
                <RuleIndicator passed={rules.minLength} label="10+ символа" />
                <RuleIndicator passed={rules.hasUpper} label="Главна буква" />
                <RuleIndicator passed={rules.hasLower} label="Малка буква" />
                <RuleIndicator passed={rules.hasDigit} label="Цифра" />
                <RuleIndicator passed={rules.hasSpecial} label="Спец. символ" />
              </div>
            )}
          </div>

          {/* Confirm Password */}
          <div className="space-y-2">
            <Label htmlFor="confirm-password">{t("auth.confirmPassword")}</Label>
            <div className="relative">
              <Input
                id="confirm-password"
                type={showConfirm ? "text" : "password"}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••••"
                data-testid="confirm-password-input"
                autoComplete="new-password"
                className={confirmPassword && !passwordsMatch ? "border-destructive" : ""}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="absolute right-0 top-0 h-full px-3"
                onClick={() => setShowConfirm(!showConfirm)}
              >
                {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </Button>
            </div>
            {confirmPassword && !passwordsMatch && (
              <p className="text-xs text-destructive">{t("auth.passwordMismatch")}</p>
            )}
          </div>

          {/* Error message */}
          {error && (
            <div className="p-3 bg-destructive/10 text-destructive text-sm rounded-md" data-testid="error-message">
              {error}
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose} disabled={loading}>
              {t("common.cancel")}
            </Button>
            <Button 
              type="submit" 
              disabled={loading || !passwordValid || !passwordsMatch || !currentPassword}
              data-testid="submit-password-change"
            >
              {loading ? t("common.loading") : t("auth.changePassword")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
