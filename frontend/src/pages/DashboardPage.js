import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDateTime } from "@/lib/i18nUtils";
import {
  Users, FolderKanban, PlayCircle, CheckCircle2, ArrowUpRight, Clock,
  CalendarCheck, AlertTriangle, FileX, ChevronDown, ChevronUp, Loader2,
  Bell, AlertCircle, DollarSign, TrendingUp, Building2, RefreshCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import FinanceSummaryWidget from "@/components/FinanceSummaryWidget";
import SitePulseCard from "@/components/SitePulseCard";
import MorningBriefingPanel from "@/components/MorningBriefingPanel";

export default function DashboardPage() {
  const { t } = useTranslation();
  const { org, user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [recentLogs, setRecentLogs] = useState([]);
  const [allLogs, setAllLogs] = useState([]);
  const [missingAtt, setMissingAtt] = useState([]);
  const [missingRep, setMissingRep] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activityExpanded, setActivityExpanded] = useState(false);
  const [activityPage, setActivityPage] = useState(1);
  const [activityTotal, setActivityTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  // New state
  const [alarms, setAlarms] = useState(null);
  const [pulses, setPulses] = useState(null);
  const [pnlOverview, setPnlOverview] = useState(null);
  const [overhead, setOverhead] = useState(null);

  const isManager = ["Admin", "Owner", "SiteManager"].includes(user?.role);

  useEffect(() => {
    const load = async () => {
      try {
        const [dashRes] = await Promise.all([API.get("/dashboard/stats")]);
        setStats(dashRes.data);
        try {
          const logsRes = await API.get("/dashboard/activity?limit=3&page=1");
          setRecentLogs(logsRes.data.items || []);
          setActivityTotal(logsRes.data.total || 0);
        } catch { setRecentLogs([]); }
        if (isManager) {
          try {
            const [attRes, repRes] = await Promise.all([
              API.get("/reminders/missing-attendance"),
              API.get("/reminders/missing-work-reports"),
            ]);
            setMissingAtt(attRes.data || []);
            setMissingRep(repRes.data || []);
          } catch { setMissingAtt([]); setMissingRep([]); }
        }
        // Load new data (non-blocking)
        Promise.all([
          API.get("/alarms/count").catch(() => ({ data: null })),
          API.get("/pulse/today").catch(() => ({ data: null })),
          API.get("/org/pnl-overview").catch(() => ({ data: null })),
          API.get("/overhead/realtime").catch(() => ({ data: null })),
        ]).then(([aR, pR, plR, oR]) => {
          setAlarms(aR.data);
          setPulses(pR.data);
          setPnlOverview(plR.data);
          setOverhead(oR.data);
        });
      } catch (err) { console.error("Failed to load dashboard", err); }
      finally { setLoading(false); }
    };
    load();
  }, [isManager]);

  const loadMoreActivity = async () => {
    setLoadingMore(true);
    try {
      const res = await API.get(`/dashboard/activity?limit=20&page=${activityPage}`);
      if (activityPage === 1) setAllLogs(res.data.items || []);
      else setAllLogs(prev => [...prev, ...(res.data.items || [])]);
      setActivityPage(p => p + 1);
    } catch { /* */ }
    finally { setLoadingMore(false); }
  };

  const toggleActivityExpand = () => {
    if (!activityExpanded) { setActivityPage(1); setAllLogs([]); loadMoreActivity(); }
    setActivityExpanded(!activityExpanded);
  };

  const displayedLogs = activityExpanded ? allLogs : recentLogs;

  if (loading || !stats) return <div className="flex items-center justify-center h-full"><div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" /></div>;

  const statCards = [
    { labelKey: "dashboard.activeProjects", value: stats.active_projects, icon: PlayCircle, color: "text-emerald-400", onClick: () => navigate("/projects") },
    { labelKey: "dashboard.todayCheckedIn", value: stats.today_present, icon: CalendarCheck, color: "text-primary", onClick: () => navigate("/site-attendance") },
    { labelKey: "dashboard.completed", value: stats.completed_projects, icon: CheckCircle2, color: "text-blue-400", onClick: () => navigate("/projects") },
    { labelKey: "dashboard.totalUsers", value: stats.users_count, icon: Users, color: "text-violet-400", onClick: () => navigate("/users") },
  ];

  const projectStats = [
    { labelKey: "common.total", val: stats.total_projects, cls: "text-foreground" },
    { labelKey: "dashboard.draft", val: stats.draft_projects, cls: "text-gray-400" },
    { labelKey: "projects.status.active", val: stats.active_projects, cls: "text-emerald-400" },
    { labelKey: "dashboard.paused", val: stats.paused_projects, cls: "text-amber-400" },
    { labelKey: "dashboard.completed", val: stats.completed_projects, cls: "text-blue-400" },
  ];

  return (
    <div className="p-8 max-w-[1200px]" data-testid="dashboard-page">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground" data-testid="dashboard-title">{t("dashboard.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("dashboard.welcomeBack")} {org?.name || "BEG_Work"}</p>
      </div>

      {/* SECTION 1: Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6" data-testid="stats-grid">
        {statCards.map((card, i) => (
          <div key={card.labelKey} className="stat-card animate-in cursor-pointer" style={{ animationDelay: `${i * 80}ms` }} onClick={card.onClick} data-testid={`stat-${card.labelKey}`}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{t(card.labelKey)}</span>
              <card.icon className={`w-4 h-4 ${card.color}`} />
            </div>
            <p className="text-2xl font-bold text-foreground">{card.value}</p>
          </div>
        ))}
      </div>

      {/* MORNING BRIEFING */}
      {isManager && <MorningBriefingPanel />}

      {/* SECTION 2: Alarms Banner */}
      {isManager && alarms && (
        <div className="mb-6" data-testid="alarms-section">
          {alarms.total > 0 ? (
            <div className={`rounded-xl border p-4 ${alarms.critical > 0 ? "border-red-500/40 bg-red-500/5" : "border-amber-500/30 bg-amber-500/5"}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <Bell className={`w-5 h-5 ${alarms.critical > 0 ? "text-red-400" : "text-amber-400"}`} />
                  <h2 className="text-sm font-semibold">{t("dashboard.activeAlarms")}</h2>
                  <div className="flex gap-2">
                    {alarms.critical > 0 && <Badge className="bg-red-500/20 text-red-400 border-red-500/30 text-xs">Critical: {alarms.critical}</Badge>}
                    {alarms.warning > 0 && <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-xs">Warning: {alarms.warning}</Badge>}
                    {alarms.info > 0 && <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/30 text-xs">Info: {alarms.info}</Badge>}
                  </div>
                </div>
                <button onClick={() => navigate("/alarms")} className="text-xs text-primary hover:underline flex items-center gap-1">{t("common.viewAll")} <ArrowUpRight className="w-3 h-3" /></button>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-sm text-emerald-400">{t("dashboard.noAlarms")}</span>
            </div>
          )}
        </div>
      )}

      {/* SECTION 3: Overhead Snapshot */}
      {isManager && overhead && overhead.fixed_total > 0 && (
        <div className="rounded-xl border border-border bg-card p-4 mb-6 flex items-center gap-6" data-testid="overhead-snapshot">
          <div className="flex items-center gap-2">
            <DollarSign className="w-5 h-5 text-cyan-400" />
            <div>
              <p className="text-[10px] text-muted-foreground uppercase">{t("dashboard.overheadPerDay")}</p>
              <p className="text-xl font-bold font-mono text-primary">{overhead.overhead_per_person_day?.toFixed(2)} лв</p>
            </div>
          </div>
          <div className="text-sm text-muted-foreground">
            <span>{t("dashboard.workingToday")}: <strong className="text-foreground">{overhead.avg_working_per_day?.toFixed(0)}</strong> / {overhead.total_employees}</span>
          </div>
          {overhead.alerts?.length > 0 && <span className="text-xs text-amber-400">{overhead.alerts[0]}</span>}
        </div>
      )}

      {/* SECTION 4: Site Pulse */}
      {isManager && pulses && pulses.items?.length > 0 && (
        <div className="mb-6" data-testid="pulse-section">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-primary" />
              <h2 className="text-sm font-semibold">{t("dashboard.todayPulse")}</h2>
              <Badge variant="outline" className="text-[10px]">{pulses.total}</Badge>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {pulses.items.slice(0, 6).map(p => <SitePulseCard key={p.site_id} pulse={p} />)}
          </div>
        </div>
      )}

      {/* Projects summary row */}
      <div className="rounded-xl border border-border bg-card p-5 mb-6" data-testid="projects-summary">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2"><FolderKanban className="w-4 h-4 text-primary" /><h2 className="text-sm font-semibold text-foreground">{t("dashboard.projectsOverview")}</h2></div>
          <button onClick={() => navigate("/projects")} className="text-xs text-primary hover:underline flex items-center gap-1">{t("common.viewAll")} <ArrowUpRight className="w-3 h-3" /></button>
        </div>
        <div className="grid grid-cols-5 gap-4 text-center">
          {projectStats.map(item => <div key={item.labelKey}><p className={`text-xl font-bold ${item.cls}`}>{item.val}</p><p className="text-xs text-muted-foreground">{t(item.labelKey)}</p></div>)}
        </div>
      </div>

      {/* SECTION 5: P&L Overview */}
      {isManager && pnlOverview && pnlOverview.projects?.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-5 mb-6" data-testid="pnl-overview-section">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2"><TrendingUp className="w-4 h-4 text-emerald-400" /><h2 className="text-sm font-semibold">{t("dashboard.pnlOverview")}</h2></div>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">{t("dashboard.pnlSite")}</TableHead>
                  <TableHead className="text-xs text-right">{t("dashboard.pnlBudget")}</TableHead>
                  <TableHead className="text-xs text-right">{t("dashboard.pnlRevenue")}</TableHead>
                  <TableHead className="text-xs text-right">{t("dashboard.pnlExpense")}</TableHead>
                  <TableHead className="text-xs text-right">{t("dashboard.pnlProfit")}</TableHead>
                  <TableHead className="text-xs text-right">%</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pnlOverview.projects.map(p => {
                  const color = p.margin_pct > 10 ? "text-emerald-400" : p.margin_pct > 0 ? "text-amber-400" : "text-red-400";
                  const dot = p.margin_pct > 10 ? "bg-emerald-500" : p.margin_pct > 0 ? "bg-amber-500" : "bg-red-500";
                  return (
                    <TableRow key={p.id} className="cursor-pointer hover:bg-muted/30" onClick={() => navigate(`/projects/${p.id}#finance`)} data-testid={`pnl-row-${p.id}`}>
                      <TableCell className="text-sm font-medium">{p.name}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{p.budget?.toFixed(0) || 0}</TableCell>
                      <TableCell className="text-right font-mono text-xs text-blue-400">{p.revenue?.toFixed(0) || 0}</TableCell>
                      <TableCell className="text-right font-mono text-xs text-orange-400">{p.expense?.toFixed(0) || 0}</TableCell>
                      <TableCell className={`text-right font-mono text-xs font-bold ${color}`}>{p.profit?.toFixed(0) || 0}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <span className={`w-2 h-2 rounded-full ${dot}`} />
                          <span className={`text-xs font-mono ${color}`}>{p.margin_pct}%</span>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {/* Totals */}
                <TableRow className="border-t-2 border-border">
                  <TableCell className="font-bold text-sm">{t("common.total")}</TableCell>
                  <TableCell className="text-right font-mono text-xs font-bold">{pnlOverview.totals.budget?.toFixed(0)}</TableCell>
                  <TableCell className="text-right font-mono text-xs font-bold text-blue-400">{pnlOverview.totals.revenue?.toFixed(0)}</TableCell>
                  <TableCell className="text-right font-mono text-xs font-bold text-orange-400">{pnlOverview.totals.expense?.toFixed(0)}</TableCell>
                  <TableCell className={`text-right font-mono text-xs font-bold ${pnlOverview.totals.profit >= 0 ? "text-emerald-400" : "text-red-400"}`}>{pnlOverview.totals.profit?.toFixed(0)}</TableCell>
                  <TableCell className="text-right font-mono text-xs font-bold">{pnlOverview.totals.margin_pct}%</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* Manager Alerts (missing attendance/reports) */}
      {isManager && (missingAtt.length > 0 || missingRep.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6" data-testid="manager-alerts">
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-5" data-testid="missing-att-widget">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-amber-400" /><h2 className="text-sm font-semibold text-amber-400">{t("dashboard.missingAttendance")} ({missingAtt.length})</h2></div>
              <button onClick={() => navigate("/reminders")} className="text-xs text-amber-400 hover:underline flex items-center gap-1">{t("common.viewAll")} <ArrowUpRight className="w-3 h-3" /></button>
            </div>
            {missingAtt.length === 0 ? <p className="text-sm text-muted-foreground">{t("dashboard.everyoneCheckedIn")}</p> : (
              <div className="space-y-2 max-h-[160px] overflow-y-auto">
                {missingAtt.slice(0, 5).map(m => (
                  <div key={m.user_id} className="flex items-center gap-2 text-sm">
                    <div className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center text-[10px] text-amber-400 font-bold">{m.user_name?.split(" ").map(n => n[0]).join("")}</div>
                    <span className="text-foreground">{m.user_name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-5" data-testid="missing-rep-widget">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2"><FileX className="w-4 h-4 text-blue-400" /><h2 className="text-sm font-semibold text-blue-400">{t("dashboard.missingReports")} ({missingRep.length})</h2></div>
              <button onClick={() => navigate("/reminders")} className="text-xs text-blue-400 hover:underline flex items-center gap-1">{t("common.viewAll")} <ArrowUpRight className="w-3 h-3" /></button>
            </div>
            {missingRep.length === 0 ? <p className="text-sm text-muted-foreground">{t("dashboard.allReportsSubmitted")}</p> : (
              <div className="space-y-2 max-h-[160px] overflow-y-auto">
                {missingRep.slice(0, 5).map((m, i) => (
                  <div key={`${m.user_id}-${m.project_id}-${i}`} className="flex items-center gap-2 text-sm">
                    <div className="w-6 h-6 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px] text-blue-400 font-bold">{m.user_name?.split(" ").map(n => n[0]).join("")}</div>
                    <span className="text-foreground">{m.user_name}</span>
                    <span className="text-primary text-xs font-mono">{m.project_code}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Finance Summary */}
      {isManager && (
        <div className="rounded-xl border border-border bg-card p-5 mb-6" data-testid="finance-summary-section"><FinanceSummaryWidget /></div>
      )}

      {/* Recent Activity */}
      <div className="rounded-xl border border-border bg-card" data-testid="recent-activity">
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">{t("dashboard.recentActivity")}</h2>
          <Button variant="ghost" size="sm" onClick={toggleActivityExpand} data-testid="expand-activity-btn">
            {activityExpanded ? <><ChevronUp className="w-4 h-4 mr-1" />{t("common.collapse") || "Скрий"}</> : <><ChevronDown className="w-4 h-4 mr-1" />{t("common.showAll") || "Покажи всички"} ({activityTotal})</>}
          </Button>
        </div>
        <div className="divide-y divide-border max-h-[400px] overflow-y-auto">
          {displayedLogs.length === 0 ? <p className="p-5 text-sm text-muted-foreground">{t("dashboard.noActivity")}</p> : displayedLogs.map(log => (
            <div key={log.id} className="flex items-center gap-4 px-5 py-3 table-row-hover" data-testid={`activity-${log.id}`}>
              <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center flex-shrink-0"><Clock className="w-3.5 h-3.5 text-muted-foreground" /></div>
              <div className="flex-1 min-w-0"><p className="text-sm text-foreground"><span className="font-medium">{log.user_email}</span> <span className="text-muted-foreground">{t(`auditLog.actions.${log.action?.toLowerCase()}`) || log.action}</span> {log.entity_type && <span className="text-foreground">{log.entity_type}</span>}</p></div>
              <span className="text-xs text-muted-foreground flex-shrink-0">{formatDateTime(log.timestamp)}</span>
            </div>
          ))}
        </div>
        {activityExpanded && allLogs.length < activityTotal && (
          <div className="p-4 border-t border-border flex justify-center">
            <Button variant="outline" size="sm" onClick={loadMoreActivity} disabled={loadingMore}>{loadingMore && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}{t("common.loadMore") || "Зареди още"}</Button>
          </div>
        )}
      </div>
    </div>
  );
}
