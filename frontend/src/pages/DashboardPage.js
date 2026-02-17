import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import {
  Users,
  Blocks,
  ScrollText,
  CreditCard,
  ArrowUpRight,
  Clock,
} from "lucide-react";

export default function DashboardPage() {
  const { org } = useAuth();
  const [stats, setStats] = useState({ users: 0, modules: 0, logs: 0, plan: "" });
  const [recentLogs, setRecentLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [usersRes, flagsRes, logsRes, subRes] = await Promise.all([
          API.get("/users"),
          API.get("/feature-flags"),
          API.get("/audit-logs?limit=8"),
          API.get("/subscription"),
        ]);
        setStats({
          users: usersRes.data.length,
          modules: flagsRes.data.filter((f) => f.enabled).length,
          logs: logsRes.data.total,
          plan: subRes.data?.plan || "N/A",
        });
        setRecentLogs(logsRes.data.logs);
      } catch (err) {
        console.error("Failed to load dashboard", err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const statCards = [
    { label: "Total Users", value: stats.users, icon: Users, color: "text-blue-400" },
    { label: "Active Modules", value: `${stats.modules}/10`, icon: Blocks, color: "text-primary" },
    { label: "Audit Events", value: stats.logs, icon: ScrollText, color: "text-emerald-400" },
    { label: "Plan", value: stats.plan.charAt(0).toUpperCase() + stats.plan.slice(1), icon: CreditCard, color: "text-violet-400" },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1200px]" data-testid="dashboard-page">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground" data-testid="dashboard-title">
          Dashboard
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Welcome back to {org?.name || "BEG_Work"}
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8" data-testid="stats-grid">
        {statCards.map((card, i) => (
          <div
            key={card.label}
            className="stat-card animate-in"
            style={{ animationDelay: `${i * 80}ms` }}
            data-testid={`stat-${card.label.toLowerCase().replace(/\s+/g, "-")}`}
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                {card.label}
              </span>
              <card.icon className={`w-4 h-4 ${card.color}`} />
            </div>
            <p className="text-2xl font-bold text-foreground">{card.value}</p>
          </div>
        ))}
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
