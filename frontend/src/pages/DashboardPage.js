import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import API from "@/lib/api";
import {
  Users,
  FolderKanban,
  PlayCircle,
  PauseCircle,
  CheckCircle2,
  ArrowUpRight,
  Clock,
  CalendarCheck,
  AlertTriangle,
  FileX,
} from "lucide-react";

export default function DashboardPage() {
  const { org, user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [recentLogs, setRecentLogs] = useState([]);
  const [missingAtt, setMissingAtt] = useState([]);
  const [missingRep, setMissingRep] = useState([]);
  const [loading, setLoading] = useState(true);
  const isManager = ["Admin", "Owner", "SiteManager"].includes(user?.role);

  useEffect(() => {
    const load = async () => {
      try {
        const [dashRes] = await Promise.all([
          API.get("/dashboard/stats"),
        ]);
        setStats(dashRes.data);
        // Audit logs may fail for non-admin users - that's OK
        try {
          const logsRes = await API.get("/audit-logs?limit=8");
          setRecentLogs(logsRes.data.logs);
        } catch {
          setRecentLogs([]);
        }
        // Missing attendance/reports for managers
        if (isManager) {
          try {
            const [attRes, repRes] = await Promise.all([
              API.get("/reminders/missing-attendance"),
              API.get("/reminders/missing-work-reports"),
            ]);
            setMissingAtt(attRes.data || []);
            setMissingRep(repRes.data || []);
          } catch {
            setMissingAtt([]);
            setMissingRep([]);
          }
        }
      } catch (err) {
        console.error("Failed to load dashboard", err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [isManager]);

  if (loading || !stats) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const statCards = [
    { label: "Active Projects", value: stats.active_projects, icon: PlayCircle, color: "text-emerald-400", onClick: () => navigate("/projects") },
    { label: "Today Checked In", value: stats.today_present, icon: CalendarCheck, color: "text-primary", onClick: () => navigate("/site-attendance") },
    { label: "Completed", value: stats.completed_projects, icon: CheckCircle2, color: "text-blue-400", onClick: () => navigate("/projects") },
    { label: "Total Users", value: stats.users_count, icon: Users, color: "text-violet-400", onClick: () => navigate("/users") },
  ];

  return (
    <div className="p-8 max-w-[1200px]" data-testid="dashboard-page">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground" data-testid="dashboard-title">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">Welcome back to {org?.name || "BEG_Work"}</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8" data-testid="stats-grid">
        {statCards.map((card, i) => (
          <div
            key={card.label}
            className="stat-card animate-in cursor-pointer"
            style={{ animationDelay: `${i * 80}ms` }}
            onClick={card.onClick}
            data-testid={`stat-${card.label.toLowerCase().replace(/\s+/g, "-")}`}
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{card.label}</span>
              <card.icon className={`w-4 h-4 ${card.color}`} />
            </div>
            <p className="text-2xl font-bold text-foreground">{card.value}</p>
          </div>
        ))}
      </div>

      {/* Projects summary row */}
      <div className="rounded-xl border border-border bg-card p-5 mb-6" data-testid="projects-summary">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <FolderKanban className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">Projects Overview</h2>
          </div>
          <button onClick={() => navigate("/projects")} className="text-xs text-primary hover:underline flex items-center gap-1">
            View all <ArrowUpRight className="w-3 h-3" />
          </button>
        </div>
        <div className="grid grid-cols-5 gap-4 text-center">
          {[
            { label: "Total", val: stats.total_projects, cls: "text-foreground" },
            { label: "Draft", val: stats.draft_projects, cls: "text-gray-400" },
            { label: "Active", val: stats.active_projects, cls: "text-emerald-400" },
            { label: "Paused", val: stats.paused_projects, cls: "text-amber-400" },
            { label: "Completed", val: stats.completed_projects, cls: "text-blue-400" },
          ].map((item) => (
            <div key={item.label}>
              <p className={`text-xl font-bold ${item.cls}`}>{item.val}</p>
              <p className="text-xs text-muted-foreground">{item.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Manager Alerts */}
      {isManager && (missingAtt.length > 0 || missingRep.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6" data-testid="manager-alerts">
          {/* Missing Attendance */}
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-5" data-testid="missing-att-widget">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <h2 className="text-sm font-semibold text-amber-400">Missing Attendance ({missingAtt.length})</h2>
              </div>
              <button onClick={() => navigate("/reminders")} className="text-xs text-amber-400 hover:underline flex items-center gap-1">
                View all <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
            {missingAtt.length === 0 ? (
              <p className="text-sm text-muted-foreground">Everyone has checked in today</p>
            ) : (
              <div className="space-y-2 max-h-[160px] overflow-y-auto">
                {missingAtt.slice(0, 5).map((m) => (
                  <div key={m.user_id} className="flex items-center gap-2 text-sm">
                    <div className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center text-[10px] text-amber-400 font-bold">
                      {m.user_name?.split(" ").map((n) => n[0]).join("")}
                    </div>
                    <span className="text-foreground">{m.user_name}</span>
                    <span className="text-muted-foreground text-xs">({m.user_role})</span>
                  </div>
                ))}
                {missingAtt.length > 5 && (
                  <p className="text-xs text-amber-400">+{missingAtt.length - 5} more</p>
                )}
              </div>
            )}
          </div>

          {/* Missing Reports */}
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-5" data-testid="missing-rep-widget">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <FileX className="w-4 h-4 text-blue-400" />
                <h2 className="text-sm font-semibold text-blue-400">Missing Reports ({missingRep.length})</h2>
              </div>
              <button onClick={() => navigate("/reminders")} className="text-xs text-blue-400 hover:underline flex items-center gap-1">
                View all <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>
            {missingRep.length === 0 ? (
              <p className="text-sm text-muted-foreground">All reports submitted</p>
            ) : (
              <div className="space-y-2 max-h-[160px] overflow-y-auto">
                {missingRep.slice(0, 5).map((m, i) => (
                  <div key={`${m.user_id}-${m.project_id}-${i}`} className="flex items-center gap-2 text-sm">
                    <div className="w-6 h-6 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px] text-blue-400 font-bold">
                      {m.user_name?.split(" ").map((n) => n[0]).join("")}
                    </div>
                    <span className="text-foreground">{m.user_name}</span>
                    <span className="text-primary text-xs font-mono">{m.project_code}</span>
                  </div>
                ))}
                {missingRep.length > 5 && (
                  <p className="text-xs text-blue-400">+{missingRep.length - 5} more</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Recent Activity */}
      <div className="rounded-xl border border-border bg-card" data-testid="recent-activity">
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Recent Activity</h2>
          <a href="/audit-log" className="text-xs text-primary hover:underline flex items-center gap-1">
            View all <ArrowUpRight className="w-3 h-3" />
          </a>
        </div>
        <div className="divide-y divide-border">
          {recentLogs.length === 0 ? (
            <p className="p-5 text-sm text-muted-foreground">No activity yet.</p>
          ) : (
            recentLogs.map((log) => (
              <div key={log.id} className="flex items-center gap-4 px-5 py-3 table-row-hover" data-testid={`activity-${log.id}`}>
                <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center flex-shrink-0">
                  <Clock className="w-3.5 h-3.5 text-muted-foreground" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-foreground">
                    <span className="font-medium">{log.user_email}</span>{" "}
                    <span className="text-muted-foreground">{log.action}</span>{" "}
                    <span className="text-foreground">{log.entity_type}</span>
                  </p>
                </div>
                <span className="text-xs text-muted-foreground flex-shrink-0">
                  {new Date(log.timestamp).toLocaleString()}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
