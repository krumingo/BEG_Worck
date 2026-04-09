/**
 * MorningBriefingPanel — Rule-based daily management summary.
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  AlertCircle, AlertTriangle, DollarSign, FileX, Loader2,
  ChevronRight, CheckCircle2, Building2, Receipt, Sun,
} from "lucide-react";

const SEV = {
  critical: { icon: AlertCircle, color: "text-red-400", bg: "bg-red-500/10 border-red-500/20" },
  warning: { icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
  info: { icon: CheckCircle2, color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/20" },
};

export default function MorningBriefingPanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    API.get("/morning-briefing").then(r => setData(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="rounded-xl border border-border bg-card p-4 flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const hasContent = data.top_risks?.length > 0 || data.payments?.length > 0 || data.missing_reports?.length > 0 || data.summary?.critical_alarms > 0;

  return (
    <div className="rounded-xl border border-border bg-card p-5 mb-6" data-testid="morning-briefing-panel">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center">
          <Sun className="w-5 h-5 text-amber-400" />
        </div>
        <div className="flex-1">
          <h2 className="text-sm font-bold">{t("dashboard.morningBriefing.title")}</h2>
          <p className="text-xs text-muted-foreground">{data.headline}</p>
        </div>
        {data.summary && (
          <div className="flex gap-2">
            {data.summary.critical_alarms > 0 && <Badge className="bg-red-500/20 text-red-400 border-red-500/30 text-[10px]">{data.summary.critical_alarms} critical</Badge>}
            {data.summary.warning_alarms > 0 && <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[10px]">{data.summary.warning_alarms} warning</Badge>}
          </div>
        )}
      </div>

      {!hasContent ? (
        <div className="flex items-center gap-2 text-sm text-emerald-400">
          <CheckCircle2 className="w-4 h-4" />
          {t("dashboard.morningBriefing.allClear")}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Risks */}
          {data.top_risks?.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t("dashboard.morningBriefing.risks")}</p>
              <div className="space-y-1.5">
                {data.top_risks.map((r, i) => {
                  const cfg = SEV[r.severity] || SEV.info;
                  const Icon = cfg.icon;
                  return (
                    <div key={i} onClick={() => navigate(`/projects/${r.project_id}`)} className={`rounded-lg border p-2.5 cursor-pointer hover:brightness-110 ${cfg.bg}`}>
                      <div className="flex items-center gap-2 mb-0.5">
                        <Icon className={`w-3.5 h-3.5 ${cfg.color}`} />
                        <span className="text-xs font-medium truncate">{r.project_name}</span>
                      </div>
                      <p className="text-[10px] text-muted-foreground">{r.reasons?.join(", ")}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Payments */}
          {data.payments?.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t("dashboard.morningBriefing.payments")}</p>
              <div className="space-y-1.5">
                {data.payments.map((p, i) => (
                  <div key={i} onClick={() => navigate(`/finance/invoices/${p.id}`)} className={`rounded-lg border p-2.5 cursor-pointer hover:brightness-110 ${p.urgency === "overdue" ? "bg-red-500/10 border-red-500/20" : "bg-amber-500/10 border-amber-500/20"}`}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-xs font-mono">{p.invoice_number}</span>
                      <Badge variant="outline" className={`text-[9px] ${p.urgency === "overdue" ? "text-red-400" : "text-amber-400"}`}>
                        {p.urgency === "overdue" ? t("dashboard.morningBriefing.overdue") : t("dashboard.morningBriefing.dueSoon")}
                      </Badge>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-muted-foreground truncate">{p.counterparty_name}</span>
                      <span className="font-mono font-bold">{p.unpaid?.toFixed(0)} лв</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Missing */}
          {data.missing_reports?.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t("dashboard.morningBriefing.missing")}</p>
              <div className="space-y-1.5">
                {data.missing_reports.map((m, i) => (
                  <div key={i} className="rounded-lg border border-border bg-muted/5 p-2.5">
                    <div className="flex items-center gap-2">
                      <FileX className="w-3.5 h-3.5 text-muted-foreground" />
                      <span className="text-xs truncate">{m.project}</span>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{m.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
