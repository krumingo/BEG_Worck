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
} from "lucide-react";

export default function DashboardPage() {
  const { org } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [recentLogs, setRecentLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [dashRes, logsRes] = await Promise.all([
          API.get("/dashboard/stats"),
          API.get("/audit-logs?limit=8"),
        ]);
        setStats(dashRes.data);
        setRecentLogs(logsRes.data.logs);
      } catch (err) {
        console.error("Failed to load dashboard", err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading || !stats) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const statCards = [
    { label: "Active Projects", value: stats.active_projects, icon: PlayCircle, color: "text-emerald-400", onClick: () => navigate("/projects") },
    { label: "Paused Projects", value: stats.paused_projects, icon: PauseCircle, color: "text-amber-400", onClick: () => navigate("/projects") },
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
