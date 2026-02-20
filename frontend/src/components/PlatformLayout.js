import { useState, useEffect } from "react";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { 
  Shield, 
  CreditCard, 
  Blocks, 
  ScrollText, 
  Smartphone,
  LogOut,
  ChevronRight,
  Menu,
  X
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const PLATFORM_NAV = [
  { to: "/platform", icon: Shield, label: "Dashboard", exact: true },
  { to: "/platform/billing", icon: CreditCard, label: "Billing" },
  { to: "/platform/modules", icon: Blocks, label: "Modules" },
  { to: "/platform/audit-log", icon: ScrollText, label: "Audit Log" },
  { to: "/platform/mobile-settings", icon: Smartphone, label: "Mobile App" },
];

export default function PlatformLayout() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const checkAccess = async () => {
      try {
        const token = localStorage.getItem("token");
        if (!token) {
          navigate("/platform/login");
          return;
        }

        const res = await API.get("/auth/me");
        const userData = res.data;

        if (!userData.is_platform_admin) {
          navigate("/platform/login");
          return;
        }

        setUser(userData);
      } catch (err) {
        console.error("Platform access check failed:", err);
        navigate("/platform/login");
      } finally {
        setLoading(false);
      }
    };

    checkAccess();
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem("bw_token");
    localStorage.removeItem("bw_user");
    navigate("/platform/login");
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="animate-spin w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white" data-testid="platform-layout">
      {/* Mobile header */}
      <div className="lg:hidden flex items-center justify-between p-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Shield className="w-6 h-6 text-violet-500" />
          <span className="font-semibold">Platform Admin</span>
        </div>
        <Button 
          variant="ghost" 
          size="sm" 
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="text-slate-400 hover:text-white"
        >
          {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </Button>
      </div>

      <div className="flex">
        {/* Sidebar */}
        <aside className={cn(
          "fixed lg:static inset-y-0 left-0 z-50 w-64 bg-slate-900 border-r border-slate-800 transform transition-transform lg:transform-none",
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}>
          {/* Logo */}
          <div className="hidden lg:flex items-center gap-3 p-6 border-b border-slate-800">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600 to-indigo-700 flex items-center justify-center">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="font-bold text-white">Platform Admin</h1>
              <p className="text-xs text-slate-500">BEG_Work System</p>
            </div>
          </div>

          {/* Navigation */}
          <nav className="p-4 space-y-1" data-testid="platform-nav">
            {PLATFORM_NAV.map((item) => {
              const isActive = item.exact 
                ? location.pathname === item.to 
                : location.pathname.startsWith(item.to);
              
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setSidebarOpen(false)}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                    isActive
                      ? "bg-violet-600/20 text-violet-400"
                      : "text-slate-400 hover:bg-slate-800 hover:text-white"
                  )}
                  data-testid={`platform-nav-${item.to.replace("/platform/", "").replace("/platform", "dashboard")}`}
                >
                  <item.icon className="w-4 h-4" />
                  {item.label}
                  {isActive && <ChevronRight className="w-4 h-4 ml-auto" />}
                </NavLink>
              );
            })}
          </nav>

          {/* User section */}
          <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-slate-800">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-full bg-violet-600/20 flex items-center justify-center">
                <span className="text-sm font-medium text-violet-400">
                  {user.first_name?.[0]}{user.last_name?.[0]}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">
                  {user.first_name} {user.last_name}
                </p>
                <p className="text-xs text-slate-500 truncate">{user.email}</p>
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className="w-full justify-start text-slate-400 hover:text-red-400 hover:bg-red-500/10"
              data-testid="platform-logout"
            >
              <LogOut className="w-4 h-4 mr-2" />
              {t("nav.logout", "Logout")}
            </Button>
          </div>
        </aside>

        {/* Mobile overlay */}
        {sidebarOpen && (
          <div 
            className="fixed inset-0 bg-black/50 z-40 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Main content */}
        <main className="flex-1 min-h-screen lg:min-h-[calc(100vh)]">
          <div className="p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
