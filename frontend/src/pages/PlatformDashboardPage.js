import { useTranslation } from "react-i18next";
import { Shield, Activity, Users, Database } from "lucide-react";

export default function PlatformDashboardPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-6" data-testid="platform-dashboard">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Platform Dashboard</h1>
        <p className="text-slate-400 mt-1">System management overview</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Shield}
          label="System Status"
          value="Online"
          color="emerald"
        />
        <StatCard
          icon={Users}
          label="Total Organizations"
          value="—"
          color="violet"
        />
        <StatCard
          icon={Database}
          label="Database"
          value="Connected"
          color="blue"
        />
        <StatCard
          icon={Activity}
          label="API Status"
          value="Healthy"
          color="amber"
        />
      </div>

      {/* Quick Actions */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <QuickActionCard
            title="Billing Config"
            description="Manage Stripe and payment settings"
            href="/platform/billing"
          />
          <QuickActionCard
            title="Module Toggles"
            description="Enable/disable feature modules"
            href="/platform/modules"
          />
          <QuickActionCard
            title="Audit Log"
            description="View system audit trail"
            href="/platform/audit-log"
          />
          <QuickActionCard
            title="Mobile Settings"
            description="Configure mobile app behavior"
            href="/platform/mobile-settings"
          />
        </div>
      </div>

      {/* Info */}
      <div className="bg-violet-600/10 border border-violet-500/20 rounded-xl p-6">
        <h3 className="text-violet-400 font-medium mb-2">Platform Admin Access</h3>
        <p className="text-slate-400 text-sm">
          You have full platform administrator access. This dashboard is separate from the client console
          and provides system-wide management capabilities. Changes made here affect all organizations.
        </p>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }) {
  const colors = {
    emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    violet: "bg-violet-500/10 text-violet-400 border-violet-500/20",
    blue: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    amber: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  };

  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <Icon className="w-5 h-5 mb-2" />
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className="text-sm opacity-80">{label}</p>
    </div>
  );
}

function QuickActionCard({ title, description, href }) {
  return (
    <a
      href={href}
      className="block p-4 rounded-lg bg-slate-800/50 border border-slate-700 hover:border-violet-500/50 hover:bg-slate-800 transition-colors"
    >
      <h4 className="font-medium text-white">{title}</h4>
      <p className="text-sm text-slate-400 mt-1">{description}</p>
    </a>
  );
}
