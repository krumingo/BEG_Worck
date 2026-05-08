/**
 * WorkerDayDetail — Level 3: detailed view of a single work session / worker-day.
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Loader2, User, Calendar, Building2, Clock, DollarSign, FileText, Check, X } from "lucide-react";

const STATUS_BADGE = {
  APPROVED: "bg-emerald-500/20 text-emerald-400",
  Approved: "bg-emerald-500/20 text-emerald-400",
  Draft: "bg-slate-100 text-slate-600",
  SUBMITTED: "bg-blue-500/20 text-blue-400",
  Unknown: "bg-zinc-100 text-zinc-500",
};

export default function WorkerDayDetail({ sessionId, onBack }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!sessionId) return;
    API.get(`/work-sessions/${sessionId}/detail`)
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return <p className="text-center text-muted-foreground py-4">{t("workerDayDetail.notFound")}</p>;

  return (
    <div className="space-y-4" data-testid="worker-day-detail">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-bold flex items-center gap-2">
            <User className="w-4 h-4" /> {data.worker_name}
          </h3>
          <p className="text-xs text-muted-foreground">{data.date} | {data.project_name}</p>
        </div>
        <Badge className={STATUS_BADGE[data.status] || STATUS_BADGE.Unknown} variant="outline">{data.status}</Badge>
      </div>

      {/* Report Card */}
      <div className="rounded-lg border border-border p-3 space-y-2">
        <p className="text-[10px] text-muted-foreground uppercase font-semibold">{t("workerDayDetail.report")}</p>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="flex items-center gap-2"><Calendar className="w-3 h-3 text-muted-foreground" /><span>{t("workerDayDetail.date")}:</span><strong>{data.date}</strong></div>
          <div className="flex items-center gap-2"><User className="w-3 h-3 text-muted-foreground" /><span>{t("workerDayDetail.worker")}:</span><strong>{data.worker_name}</strong></div>
          <div className="flex items-center gap-2"><Building2 className="w-3 h-3 text-muted-foreground" /><span>{t("workerDayDetail.project")}:</span><strong>{data.project_name}</strong></div>
          <div className="flex items-center gap-2"><FileText className="w-3 h-3 text-muted-foreground" /><span>{t("workerDayDetail.smrType")}:</span><strong>{data.smr_type || "—"}</strong></div>
        </div>
      </div>

      {/* Activity Card */}
      <div className="rounded-lg border border-border p-3 space-y-2">
        <p className="text-[10px] text-muted-foreground uppercase font-semibold">{t("workerDayDetail.activity")}</p>
        <div className="flex items-center justify-between text-sm bg-muted/10 rounded p-2">
          <div>
            <span className="font-medium">{data.smr_type || "—"}</span>
            <span className="mx-2 text-muted-foreground">|</span>
            <span className="text-muted-foreground">{data.pay_type}</span>
          </div>
          <div className="font-mono text-right">
            <span>{data.hours?.toFixed(1)} × {data.hourly_rate?.toFixed(2)} = </span>
            <strong className="text-primary">{data.total_cost?.toFixed(2)} EUR</strong>
          </div>
        </div>
        {data.is_overtime && (
          <Badge variant="outline" className="text-[9px] text-orange-400 border-orange-400/30">{t("workerDayDetail.overtime")} ({data.overtime_type})</Badge>
        )}
      </div>

      {/* History Card */}
      <div className="rounded-lg border border-border p-3 space-y-2">
        <p className="text-[10px] text-muted-foreground uppercase font-semibold">{t("workerDayDetail.history")}</p>
        <div className="space-y-1.5 text-xs">
          {data.created_by_name && (
            <div className="flex justify-between"><span className="text-muted-foreground">{t("workerDayDetail.createdBy")}:</span><span>{data.created_by_name}</span></div>
          )}
          {data.created_at && (
            <div className="flex justify-between"><span className="text-muted-foreground">{t("workerDayDetail.createdAt")}:</span><span>{new Date(data.created_at).toLocaleString("bg-BG")}</span></div>
          )}
          {data.approved_by_name && (
            <div className="flex justify-between"><span className="text-muted-foreground">{t("workerDayDetail.approvedBy")}:</span><span>{data.approved_by_name}</span></div>
          )}
          {data.approved_at && (
            <div className="flex justify-between"><span className="text-muted-foreground">{t("workerDayDetail.approvedAt")}:</span><span>{new Date(data.approved_at).toLocaleString("bg-BG")}</span></div>
          )}
          <div className="flex justify-between"><span className="text-muted-foreground">{t("workerDayDetail.slip")}:</span><span className="font-mono font-bold">{data.slip_number || "—"}</span></div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">{t("workerDayDetail.paid")}:</span>
            <span>{data.is_paid ? <Check className="w-4 h-4 text-emerald-400 inline" /> : <X className="w-4 h-4 text-muted-foreground inline" />} {data.is_paid ? t("common.yes") : t("common.no")}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
