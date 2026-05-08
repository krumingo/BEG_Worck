/**
 * ProjectContextBar — Shows project context header with back button.
 * Used when navigating from Project > Team tab to Присъствие/Отчети/Одобрение.
 * Reads returnTo, returnTab, projectName from URL search params.
 */
import { useSearchParams, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Building2 } from "lucide-react";

export default function ProjectContextBar({ pageTitle }) {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const returnTo = searchParams.get("returnTo");
  const returnTab = searchParams.get("returnTab");
  const projectName = searchParams.get("projectName");

  if (!returnTo || !projectName) return null;

  const backUrl = returnTab ? `${returnTo}#${returnTab}` : returnTo;

  return (
    <div className="flex items-center gap-3 mb-4 px-1" data-testid="project-context-bar">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate(backUrl)}
        className="text-gray-400 hover:text-white gap-1.5"
        data-testid="context-back-btn"
      >
        <ArrowLeft className="w-4 h-4" />
        Назад
      </Button>
      <div className="flex items-center gap-2 text-sm">
        <Building2 className="w-4 h-4 text-yellow-500" />
        <span className="text-white font-medium">{pageTitle}</span>
        <span className="text-gray-400">—</span>
        <span className="text-yellow-400 font-medium">{projectName}</span>
      </div>
    </div>
  );
}
