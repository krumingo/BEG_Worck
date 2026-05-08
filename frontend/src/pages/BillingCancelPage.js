import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { XCircle } from "lucide-react";

export default function BillingCancelPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-muted p-4" data-testid="billing-cancel-page">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <div className="flex justify-center mb-4">
            <div className="w-16 h-16 rounded-full bg-yellow-500/10 flex items-center justify-center">
              <XCircle className="w-8 h-8 text-yellow-500" />
            </div>
          </div>
          <CardTitle className="text-2xl">{t("billing.paymentCanceled")}</CardTitle>
          <CardDescription>
            {t("billing.paymentCanceledDesc")}
          </CardDescription>
        </CardHeader>
        
        <CardContent>
          <p className="text-muted-foreground">
            {t("billing.nothingCharged")}
          </p>
        </CardContent>

        <CardFooter className="justify-center gap-3">
          <Button variant="outline" onClick={() => navigate("/plans")} data-testid="try-again">
            {t("billing.tryAgain")}
          </Button>
          <Button onClick={() => navigate("/")} data-testid="go-to-dashboard">
            {t("billing.goToDashboard")}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
