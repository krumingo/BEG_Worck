import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Check, Loader2, AlertTriangle, Crown, Zap, Building2 } from "lucide-react";
import { toast } from "sonner";

const PLAN_ICONS = {
  free: Zap,
  pro: Crown,
  enterprise: Building2,
};

export default function PlanSelectionPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useAuth();
  
  const [plans, setPlans] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [billingConfig, setBillingConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [plansRes, subRes, configRes] = await Promise.all([
        api.get("/billing/plans"),
        api.get("/billing/subscription"),
        api.get("/billing/config"),
      ]);
      setPlans(plansRes.data);
      setSubscription(subRes.data);
      setBillingConfig(configRes.data);
    } catch (err) {
      toast.error(t("toast.errorOccurred"));
    } finally {
      setLoading(false);
    }
  };

  const handleSelectPlan = async (planId) => {
    if (planId === "free") {
      toast.info(t("billing.alreadyOnFreePlan"));
      return;
    }
    
    if (subscription?.plan?.id === planId) {
      toast.info(t("billing.alreadyOnPlan"));
      return;
    }

    setUpgrading(planId);
    try {
      const res = await api.post("/billing/create-checkout-session", {
        plan_id: planId,
        origin_url: window.location.origin,
      });

      if (res.data.mock_mode) {
        toast.success(t("billing.mockUpgradeSuccess"));
        navigate("/billing/success?mock=true");
      } else if (res.data.checkout_url) {
        window.location.href = res.data.checkout_url;
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setUpgrading(null);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  const currentPlanId = subscription?.plan?.id || "free";

  return (
    <div className="min-h-screen bg-gradient-to-br from-background to-muted py-12 px-4" data-testid="plan-selection-page">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-3xl font-bold mb-2">{t("billing.choosePlan")}</h1>
          <p className="text-muted-foreground">{t("billing.choosePlanSubtitle")}</p>
          
          {billingConfig?.stripe_mock_mode && (
            <div className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-yellow-500/10 text-yellow-600 rounded-lg text-sm">
              <AlertTriangle className="w-4 h-4" />
              {t("billing.mockModeWarning")}
            </div>
          )}
        </div>

        <div className="grid md:grid-cols-3 gap-6">
          {plans.map((plan) => {
            const Icon = PLAN_ICONS[plan.id] || Zap;
            const isCurrent = currentPlanId === plan.id;
            const isPopular = plan.id === "pro";
            
            return (
              <Card 
                key={plan.id} 
                className={`relative ${isPopular ? "border-primary shadow-lg" : ""} ${isCurrent ? "bg-primary/5" : ""}`}
                data-testid={`plan-card-${plan.id}`}
              >
                {isPopular && (
                  <Badge className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary">
                    {t("billing.popular")}
                  </Badge>
                )}
                
                <CardHeader>
                  <div className="flex items-center gap-3 mb-2">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${isPopular ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <div>
                      <CardTitle className="text-lg">{plan.name}</CardTitle>
                      {isCurrent && (
                        <Badge variant="secondary" className="text-xs">{t("billing.currentPlan")}</Badge>
                      )}
                    </div>
                  </div>
                  <CardDescription>{plan.description}</CardDescription>
                </CardHeader>

                <CardContent className="space-y-4">
                  <div className="flex items-baseline gap-1">
                    <span className="text-3xl font-bold">
                      {plan.price === 0 ? t("common.free") : `€${plan.price}`}
                    </span>
                    {plan.price > 0 && (
                      <span className="text-muted-foreground">/{t("common.month")}</span>
                    )}
                  </div>

                  {plan.trial_days > 0 && (
                    <p className="text-sm text-green-600 font-medium">
                      {t("billing.trialDays", { days: plan.trial_days })}
                    </p>
                  )}

                  <div className="space-y-2">
                    {plan.module_names.map((module, idx) => (
                      <div key={idx} className="flex items-center gap-2 text-sm">
                        <Check className="w-4 h-4 text-green-500" />
                        <span>{module}</span>
                      </div>
                    ))}
                  </div>

                  <div className="pt-4 border-t space-y-1 text-xs text-muted-foreground">
                    <p>{t("billing.limits.users")}: {plan.limits.users === -1 ? t("billing.unlimited") : plan.limits.users}</p>
                    <p>{t("billing.limits.projects")}: {plan.limits.projects === -1 ? t("billing.unlimited") : plan.limits.projects}</p>
                    <p>{t("billing.limits.storage")}: {plan.limits.storage_mb >= 1000 ? `${plan.limits.storage_mb / 1000} GB` : `${plan.limits.storage_mb} MB`}</p>
                  </div>
                </CardContent>

                <CardFooter>
                  <Button
                    className="w-full"
                    variant={isPopular ? "default" : "outline"}
                    disabled={isCurrent || upgrading === plan.id || plan.id === "free"}
                    onClick={() => handleSelectPlan(plan.id)}
                    data-testid={`select-plan-${plan.id}`}
                  >
                    {upgrading === plan.id && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                    {isCurrent 
                      ? t("billing.currentPlan")
                      : plan.id === "free"
                        ? t("billing.freePlan")
                        : t("billing.selectPlan")
                    }
                  </Button>
                </CardFooter>
              </Card>
            );
          })}
        </div>

        <div className="mt-8 text-center">
          <Button variant="ghost" onClick={() => navigate("/")} data-testid="back-to-dashboard">
            {t("common.back")} {t("nav.dashboard")}
          </Button>
        </div>
      </div>
    </div>
  );
}
