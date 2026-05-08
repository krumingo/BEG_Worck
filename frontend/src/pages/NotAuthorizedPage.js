import { useTranslation } from "react-i18next";
import { ShieldX, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";

export default function NotAuthorizedPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center p-8" data-testid="not-authorized-page">
      <div className="text-center space-y-4 max-w-md">
        <div className="w-20 h-20 mx-auto rounded-full bg-destructive/10 flex items-center justify-center">
          <ShieldX className="w-10 h-10 text-destructive" />
        </div>
        
        <h1 className="text-2xl font-bold text-foreground">
          {t("errors.notAuthorized", "Not Authorized")}
        </h1>
        
        <p className="text-muted-foreground">
          {t("errors.platformAdminRequired", "This section requires platform administrator access. Contact your system administrator if you need access.")}
        </p>
        
        <Button
          variant="outline"
          onClick={() => navigate("/")}
          className="mt-4"
          data-testid="go-back-button"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          {t("common.backToDashboard", "Back to Dashboard")}
        </Button>
      </div>
    </div>
  );
}
