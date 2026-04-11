/**
 * EmployeeDossierSection — Worker picker that navigates to unified /employees/:id dossier.
 * Used as a tab in AllReportsPage.
 */
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Search, ChevronRight, Loader2 } from "lucide-react";

export default function EmployeeDossierSection() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [workerList, setWorkerList] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    API.get("/dashboard/personnel-today")
      .then(r => setWorkerList(r.data?.personnel || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = workerList.filter(w => {
    if (!search) return true;
    const q = search.toLowerCase();
    return `${w.first_name} ${w.last_name}`.toLowerCase().includes(q) || (w.position || "").toLowerCase().includes(q);
  });

  return (
    <div data-testid="dossier-worker-list">
      <div className="flex items-center gap-3 mb-4">
        <Search className="w-4 h-4 text-muted-foreground" />
        <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={t("dossier.searchWorker")} className="max-w-xs h-9" data-testid="dossier-search" />
        <span className="text-xs text-muted-foreground">{filtered.length} {t("dossier.people")}</span>
      </div>
      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" /></div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2" data-testid="worker-cards">
          {filtered.map(w => (
            <button key={w.id} onClick={() => navigate(`/employees/${w.id}?tab=reports`)} className="flex items-center gap-3 p-3 rounded-xl border border-border bg-card hover:border-primary/40 text-left transition-colors" data-testid={`worker-card-${w.id}`}>
              {w.avatar_url ? (
                <img src={`${process.env.REACT_APP_BACKEND_URL}${w.avatar_url}`} className="w-10 h-10 rounded-full object-cover" alt="" />
              ) : (
                <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center text-sm font-bold text-primary">
                  {(w.first_name?.[0] || "")}{(w.last_name?.[0] || "")}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{w.first_name} {w.last_name}</p>
                <p className="text-[10px] text-muted-foreground">{w.position || w.role || "—"}</p>
              </div>
              {w.day_status === "working" && <Badge variant="outline" className="text-[8px] bg-emerald-500/15 text-emerald-400 border-emerald-500/30 flex-shrink-0">{t("dossier.calWorking")}</Badge>}
              <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
