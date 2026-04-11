/**
 * CentralizedProjectView — Three projections from one data source.
 * Tabs: Дейности | Персонал | Финанси
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Loader2, Clock, Users, DollarSign, AlertTriangle,
} from "lucide-react";

const STATUS_DOT = { green: "bg-emerald-500", yellow: "bg-amber-500", red: "bg-red-500" };
function fmt(n) { return n == null || n === 0 ? "—" : n.toLocaleString("bg-BG", { maximumFractionDigits: 0 }); }
function fmt2(n) { return n == null || n === 0 ? "—" : n.toLocaleString("bg-BG", { maximumFractionDigits: 2 }); }

export default function CentralizedProjectView({ projectId, tab = "activities" }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState(tab);

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/projects/${projectId}/centralized-reports`);
      setData(res.data);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!data) return null;

  const { activities, personnel, finance } = data;

  return (
    <div data-testid="centralized-project-view" className="space-y-3">
      {/* Tab selector */}
      <div className="flex gap-1 border-b border-border pb-1">
        {[
          { key: "activities", icon: Clock, label: t("centralReports.activities") },
          { key: "personnel", icon: Users, label: t("centralReports.personnel") },
          { key: "finance", icon: DollarSign, label: t("centralReports.finance") },
        ].map(tb => (
          <button key={tb.key} onClick={() => setActiveTab(tb.key)}
            className={`flex items-center gap-1 px-3 py-1.5 text-xs rounded-t ${activeTab === tb.key ? "bg-muted text-foreground font-bold" : "text-muted-foreground hover:text-foreground"}`}>
            <tb.icon className="w-3.5 h-3.5" /> {tb.label}
          </button>
        ))}
      </div>

      {/* ── ACTIVITIES ────────────────────────────────────────── */}
      {activeTab === "activities" && (
        <div className="overflow-x-auto border border-border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow className="text-[10px]">
                <TableHead className="w-6"></TableHead>
                <TableHead>{t("centralReports.section")}</TableHead>
                <TableHead>{t("centralReports.activity")}</TableHead>
                <TableHead className="text-right">{t("centralReports.planned")}</TableHead>
                <TableHead className="text-right">{t("centralReports.draftHrs")}</TableHead>
                <TableHead className="text-right">{t("centralReports.approvedHrs")}</TableHead>
                <TableHead className="text-right">{t("centralReports.totalHrs")}</TableHead>
                <TableHead className="text-right">{t("centralReports.cleanLabor")}</TableHead>
                <TableHead className="text-right">{t("centralReports.laborOH")}</TableHead>
                <TableHead className="text-right">%</TableHead>
                <TableHead>{t("centralReports.label")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {activities.map((a, i) => {
                const dot = STATUS_DOT[a.risk_status] || STATUS_DOT.green;
                const color = a.risk_status === "red" ? "text-red-400" : a.risk_status === "yellow" ? "text-amber-400" : "text-emerald-400";
                return (
                  <TableRow key={i} className="text-xs">
                    <TableCell><span className={`w-2.5 h-2.5 rounded-full inline-block ${dot}`} /></TableCell>
                    <TableCell className="text-muted-foreground">{a.category}</TableCell>
                    <TableCell className="font-medium truncate max-w-[160px]">{a.activity_name}</TableCell>
                    <TableCell className="text-right font-mono">{a.planned_hours > 0 ? a.planned_hours.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-right font-mono text-blue-400">{a.draft_hours > 0 ? a.draft_hours.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-right font-mono text-emerald-400">{a.approved_hours > 0 ? a.approved_hours.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-right font-mono font-bold">{a.total_reported_hours > 0 ? a.total_reported_hours.toFixed(0) : "—"}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(a.clean_labor_cost)}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(a.labor_cost_with_overhead)}</TableCell>
                    <TableCell className="text-right"><span className={`font-mono font-bold ${color}`}>{a.burn_pct_total > 0 ? `${a.burn_pct_total.toFixed(0)}%` : "—"}</span></TableCell>
                    <TableCell>{a.is_extra && <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-400">{t("centralReports.extra")}</Badge>}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ── PERSONNEL ─────────────────────────────────────────── */}
      {activeTab === "personnel" && (
        <div className="overflow-x-auto border border-border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow className="text-[10px]">
                <TableHead>{t("centralReports.worker")}</TableHead>
                <TableHead className="text-center">{t("centralReports.today")}</TableHead>
                <TableHead className="text-right">{t("centralReports.draftCount")}</TableHead>
                <TableHead className="text-right">{t("centralReports.approvedCount")}</TableHead>
                <TableHead className="text-right">{t("centralReports.hours")}</TableHead>
                <TableHead className="text-right">{t("centralReports.cleanAmount")}</TableHead>
                <TableHead className="text-right">{t("centralReports.ohAmount")}</TableHead>
                <TableHead className="text-right">{t("centralReports.totalAmount")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {personnel.length === 0 ? (
                <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-6">{t("centralReports.noPersonnel")}</TableCell></TableRow>
              ) : personnel.map((p, i) => (
                <TableRow key={i} className="text-xs cursor-pointer hover:bg-muted/20" onClick={() => navigate(`/projects/${projectId}#team`)}>
                  <TableCell className="font-medium">{p.worker_name}</TableCell>
                  <TableCell className="text-center">{p.today_present ? <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> : <span className="w-2 h-2 rounded-full bg-zinc-600 inline-block" />}</TableCell>
                  <TableCell className="text-right font-mono text-blue-400">{p.draft_reports_count || "—"}</TableCell>
                  <TableCell className="text-right font-mono text-emerald-400">{p.approved_reports_count || "—"}</TableCell>
                  <TableCell className="text-right font-mono">{p.total_hours}</TableCell>
                  <TableCell className="text-right font-mono">{fmt2(p.clean_amount)}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">{fmt2(p.overhead_amount)}</TableCell>
                  <TableCell className="text-right font-mono font-bold">{fmt2(p.total_amount)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ── FINANCE ───────────────────────────────────────────── */}
      {activeTab === "finance" && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: t("centralReports.cleanLabor"), val: finance.total_clean_labor, color: "text-blue-400" },
            { label: t("centralReports.overhead"), val: finance.total_overhead, color: "text-muted-foreground" },
            { label: t("centralReports.laborOH"), val: finance.total_labor_with_overhead, color: "text-foreground" },
            { label: t("centralReports.materials"), val: finance.total_materials, color: "text-orange-400" },
            { label: t("centralReports.totalExpense"), val: finance.total_expense, color: "text-red-400" },
            { label: t("centralReports.revenue"), val: finance.total_revenue, color: "text-emerald-400" },
            { label: t("centralReports.balance"), val: finance.balance, color: finance.balance >= 0 ? "text-emerald-400" : "text-red-400" },
            { label: t("centralReports.margin"), val: finance.margin_pct, color: "text-primary", suffix: "%" },
          ].map(({ label, val, color, suffix }) => (
            <div key={label} className="rounded-lg border border-border p-3 text-center">
              <p className="text-[10px] text-muted-foreground mb-1">{label}</p>
              <p className={`font-mono font-bold text-lg ${color}`}>{fmt2(val)}{suffix || ""}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
