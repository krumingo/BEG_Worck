import { useAuth } from "@/contexts/AuthContext";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Users,
  Building2,
  Blocks,
  ScrollText,
  LogOut,
  ChevronRight,
  HardHat,
  FolderKanban,
  CalendarCheck,
  CalendarDays,
  ClipboardList,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

const ADMIN_NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/projects", icon: FolderKanban, label: "Projects" },
  { to: "/site-attendance", icon: ClipboardList, label: "Site Attendance" },
  { to: "/users", icon: Users, label: "Users & Roles" },
  { to: "/settings", icon: Building2, label: "Company Settings" },
  { to: "/modules", icon: Blocks, label: "Modules" },
  { to: "/audit-log", icon: ScrollText, label: "Audit Log" },
];

const WORKER_NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/my-day", icon: CalendarCheck, label: "My Day" },
  { to: "/attendance-history", icon: CalendarDays, label: "History" },
  { to: "/projects", icon: FolderKanban, label: "Projects" },
];

export default function DashboardLayout({ children }) {
  const { user, org, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="flex h-screen overflow-hidden" data-testid="dashboard-layout">
      {/* Sidebar */}
      <aside className="w-[260px] flex-shrink-0 border-r border-border bg-card flex flex-col" data-testid="sidebar">
        {/* Brand */}
        <div className="flex items-center gap-3 px-5 h-16 border-b border-border">
          <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center">
            <HardHat className="w-5 h-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-foreground">BEG_Work</h1>
            <p className="text-[11px] text-muted-foreground truncate max-w-[150px]">{org?.name || "Loading..."}</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto" data-testid="sidebar-nav">
          {(["Admin","Owner","SiteManager"].includes(user?.role) ? ADMIN_NAV : WORKER_NAV).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `sidebar-link ${isActive ? "active" : "text-muted-foreground"}`
              }
              data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
            >
              <item.icon className="w-[18px] h-[18px]" />
              <span className="flex-1">{item.label}</span>
              {location.pathname === item.to && (
                <ChevronRight className="w-4 h-4 opacity-50" />
              )}
            </NavLink>
          ))}
        </nav>

        <Separator />

        {/* User section */}
        <div className="px-4 py-4" data-testid="sidebar-user">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-xs font-bold text-primary">
              {user?.first_name?.[0]}{user?.last_name?.[0]}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">
                {user?.first_name} {user?.last_name}
              </p>
              <p className="text-[11px] text-muted-foreground truncate">{user?.role}</p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-muted-foreground hover:text-destructive"
            onClick={handleLogout}
            data-testid="logout-button"
          >
            <LogOut className="w-4 h-4 mr-2" />
            Sign Out
          </Button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto bg-background" data-testid="main-content">
        {children}
      </main>
    </div>
  );
}
