import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CheckCircle2 } from "lucide-react";

export default function BillingSuccessPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  
  const isMock = searchParams.get("mock") === "true";

  useEffect(() => {
    // Redirect to dashboard after 5 seconds
    const timer = setTimeout(() => {
      navigate("/");
    }, 5000);
    return () => clearTimeout(timer);
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-muted p-4" data-testid="billing-success-page">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <div className="flex justify-center mb-4">
            <div className="w-16 h-16 rounded-full bg-green-500/10 flex items-center justify-center">
              <CheckCircle2 className="w-8 h-8 text-green-500" />
            </div>
          </div>
          <CardTitle className="text-2xl">{t("billing.paymentSuccess")}</CardTitle>
          <CardDescription>
            {isMock ? t("billing.mockUpgradeComplete") : t("billing.upgradeComplete")}
          </CardDescription>
        </CardHeader>
        
        <CardContent>
          <p className="text-muted-foreground">
            {t("billing.redirectingToDashboard")}
          </p>
        </CardContent>

        <CardFooter className="justify-center">
          <Button onClick={() => navigate("/")} data-testid="go-to-dashboard">
            {t("billing.goToDashboard")}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
