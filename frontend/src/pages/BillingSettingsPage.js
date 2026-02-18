import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { 
  CreditCard, 
  Loader2, 
  AlertTriangle, 
  Crown, 
  Calendar, 
  ExternalLink,
  CheckCircle2,
  XCircle,
  Clock
} from "lucide-react";
import { toast } from "sonner";

const STATUS_CONFIG = {
  trialing: { icon: Clock, color: "text-blue-500", bg: "bg-blue-500/10" },
  active: { icon: CheckCircle2, color: "text-green-500", bg: "bg-green-500/10" },
  past_due: { icon: AlertTriangle, color: "text-yellow-500", bg: "bg-yellow-500/10" },
  canceled: { icon: XCircle, color: "text-red-500", bg: "bg-red-500/10" },
  incomplete: { icon: AlertTriangle, color: "text-orange-500", bg: "bg-orange-500/10" },
};

export default function BillingSettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  
  const [subscription, setSubscription] = useState(null);
  const [billingConfig, setBillingConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [portalLoading, setPortalLoading] = useState(false);

  // Show success message if coming from checkout
  useEffect(() => {
    const sessionId = searchParams.get("session_id");
    const isMock = searchParams.get("mock") === "true";
    
    if (sessionId) {
      if (isMock) {
        toast.success(t("billing.mockUpgradeSuccess"));
      } else {
        toast.success(t("billing.upgradeSuccess"));
      }
    }
  }, [searchParams, t]);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [subRes, configRes] = await Promise.all([
        api.get("/billing/subscription"),
        api.get("/billing/config"),
      ]);
      setSubscription(subRes.data);
      setBillingConfig(configRes.data);
    } catch (err) {
      toast.error(t("toast.errorOccurred"));
    } finally {
      setLoading(false);
    }
  };

  const handleOpenPortal = async () => {
    setPortalLoading(true);
    try {
      const res = await api.post("/billing/create-portal-session");
      if (res.data.mock_mode) {
        toast.info(t("billing.portalNotAvailableMock"));
      } else if (res.data.portal_url) {
        window.location.href = res.data.portal_url;
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setPortalLoading(false);
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "-";
    return new Date(dateStr).toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  const plan = subscription?.plan;
  const status = subscription?.status || "inactive";
  const StatusIcon = STATUS_CONFIG[status]?.icon || AlertTriangle;
  const statusColor = STATUS_CONFIG[status]?.color || "text-gray-500";
  const statusBg = STATUS_CONFIG[status]?.bg || "bg-gray-500/10";

  return (
    <div className="p-6 max-w-4xl mx-auto" data-testid="billing-settings-page">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{t("billing.billingSettings")}</h1>
        <p className="text-muted-foreground">{t("billing.billingSettingsSubtitle")}</p>
      </div>

      {billingConfig?.stripe_mock_mode && (
        <Alert className="mb-6 border-yellow-500/50 bg-yellow-500/10">
          <AlertTriangle className="w-4 h-4 text-yellow-500" />
          <AlertDescription className="text-yellow-700">
            {t("billing.mockModeActive")}
          </AlertDescription>
        </Alert>
      )}

      {/* Current Plan Card */}
      <Card className="mb-6" data-testid="current-plan-card">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                <Crown className="w-5 h-5 text-primary" />
              </div>
              <div>
                <CardTitle>{t("billing.currentPlan")}</CardTitle>
                <CardDescription>{plan?.name || "Free"}</CardDescription>
              </div>
            </div>
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${statusBg}`}>
              <StatusIcon className={`w-4 h-4 ${statusColor}`} />
              <span className={`text-sm font-medium ${statusColor}`}>
                {t(`billing.status.${status}`)}
              </span>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Trial Info */}
          {subscription?.trial_active && (
            <div className="flex items-center gap-2 p-3 bg-blue-500/10 rounded-lg">
              <Clock className="w-5 h-5 text-blue-500" />
              <div>
                <p className="font-medium text-blue-700">{t("billing.trialActive")}</p>
                <p className="text-sm text-blue-600">
                  {t("billing.daysRemaining", { days: subscription.trial_days_remaining })}
                </p>
              </div>
            </div>
          )}

          {subscription?.trial_expired && (
            <div className="flex items-center gap-2 p-3 bg-yellow-500/10 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-yellow-500" />
              <div>
                <p className="font-medium text-yellow-700">{t("billing.trialExpired")}</p>
                <p className="text-sm text-yellow-600">{t("billing.upgradeToAccess")}</p>
              </div>
            </div>
          )}

          <Separator />

          {/* Plan Details */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-muted-foreground">{t("billing.price")}</p>
              <p className="font-medium">
                {plan?.price === 0 ? t("common.free") : `€${plan?.price}/${t("common.month")}`}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("billing.billingCycle")}</p>
              <p className="font-medium">{plan?.price > 0 ? t("billing.monthly") : "-"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("billing.periodStart")}</p>
              <p className="font-medium">{formatDate(subscription?.current_period_start)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("billing.periodEnd")}</p>
              <p className="font-medium">{formatDate(subscription?.current_period_end)}</p>
            </div>
          </div>

          <Separator />

          {/* Included Modules */}
          <div>
            <p className="text-sm text-muted-foreground mb-2">{t("billing.includedModules")}</p>
            <div className="flex flex-wrap gap-2">
              {plan?.allowed_modules?.map((mod) => (
                <Badge key={mod} variant="secondary">{mod}</Badge>
              ))}
            </div>
          </div>

          {/* Limits */}
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div className="p-3 bg-muted rounded-lg text-center">
              <p className="text-muted-foreground">{t("billing.limits.users")}</p>
              <p className="font-bold text-lg">
                {plan?.limits?.users === -1 ? "∞" : plan?.limits?.users}
              </p>
            </div>
            <div className="p-3 bg-muted rounded-lg text-center">
              <p className="text-muted-foreground">{t("billing.limits.projects")}</p>
              <p className="font-bold text-lg">
                {plan?.limits?.projects === -1 ? "∞" : plan?.limits?.projects}
              </p>
            </div>
            <div className="p-3 bg-muted rounded-lg text-center">
              <p className="text-muted-foreground">{t("billing.limits.storage")}</p>
              <p className="font-bold text-lg">{plan?.limits?.storage_gb} GB</p>
            </div>
          </div>
        </CardContent>

        <CardFooter className="flex gap-3">
          <Button onClick={() => navigate("/plans")} data-testid="change-plan-btn">
            {subscription?.plan?.id === "free" ? t("billing.upgrade") : t("billing.changePlan")}
          </Button>
          
          {subscription?.stripe_customer_id && !billingConfig?.stripe_mock_mode && (
            <Button 
              variant="outline" 
              onClick={handleOpenPortal}
              disabled={portalLoading}
              data-testid="manage-billing-btn"
            >
              {portalLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              <CreditCard className="w-4 h-4 mr-2" />
              {t("billing.manageBilling")}
              <ExternalLink className="w-3 h-3 ml-2" />
            </Button>
          )}
        </CardFooter>
      </Card>

      {/* Payment Method Card (only for paid plans) */}
      {subscription?.stripe_customer_id && (
        <Card data-testid="payment-method-card">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <CreditCard className="w-5 h-5" />
              {t("billing.paymentMethod")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {billingConfig?.stripe_mock_mode ? (
              <p className="text-muted-foreground">{t("billing.mockPaymentMethod")}</p>
            ) : (
              <div className="flex items-center gap-3">
                <div className="w-12 h-8 bg-muted rounded flex items-center justify-center">
                  <CreditCard className="w-5 h-5 text-muted-foreground" />
                </div>
                <div>
                  <p className="font-medium">{t("billing.manageInPortal")}</p>
                  <p className="text-sm text-muted-foreground">{t("billing.usePortalToUpdate")}</p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
