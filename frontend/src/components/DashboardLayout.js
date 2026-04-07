import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  LayoutDashboard,
  Users,
  Building2,
  Blocks,
  ScrollText,
  LogOut,
  ChevronRight,
  ChevronDown,
  HardHat,
  FolderKanban,
  CalendarCheck,
  CalendarDays,
  ClipboardList,
  Bell,
  FileText,
  Layers,
  Receipt,
  Wallet,
  UserCog,
  Landmark,
  Calculator,
  CreditCard,
  Smartphone,
  User,
  Package,
  Truck,
  RotateCcw,
  Settings,
  HelpCircle,
  Info,
  Menu,
  X,
  Lock,
  Archive,
  Warehouse,
  TrendingUp,
  BarChart3,
  FilePlus2,
  ClipboardPen,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import NotificationBell from "@/components/NotificationBell";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ChangePasswordModal from "@/components/ChangePasswordModal";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetTrigger, SheetClose } from "@/components/ui/sheet";

// ══════════════════════════════════════════════════════════════════════════════
// DESKTOP SIDEBAR NAVIGATION
// ══════════════════════════════════════════════════════════════════════════════

// Core navigation items (visible to all admin-level users)
const ADMIN_NAV_CORE = [
  { to: "/", icon: LayoutDashboard, labelKey: "nav.dashboard" },
  { to: "/projects", icon: FolderKanban, labelKey: "nav.projects" },
  { to: "/offers", icon: FileText, labelKey: "nav.offers" },
  { to: "/activity-catalog", icon: Layers, labelKey: "nav.activities" },
  { to: "/ai-calibration", icon: Sparkles, labelKey: "nav.aiCalibration" },
  { to: "/historical-offers", icon: Archive, labelKey: "nav.historicalOffers" },
  { to: "/site-attendance", icon: ClipboardList, labelKey: "nav.siteAttendance" },
  { to: "/reports", icon: CalendarCheck, labelKey: "nav.reviewReports" },
  { to: "/reminders", icon: Bell, labelKey: "nav.reminders" },
  { to: "/employees", icon: UserCog, labelKey: "nav.employees" },
  { to: "/advances", icon: Wallet, labelKey: "nav.advances" },
  { to: "/payroll", icon: Receipt, labelKey: "nav.payroll" },
  { to: "/finance", icon: Landmark, labelKey: "nav.finance" },
  { to: "/overhead", icon: Calculator, labelKey: "nav.overhead" },
  { to: "/procurement", icon: Package, labelKey: "nav.procurement" },
  { to: "/inventory", icon: Warehouse, labelKey: "nav.inventory" },
];

// Data module navigation (collapsible section)
const DATA_NAV = [
  { to: "/data/warehouses", icon: Warehouse, labelKey: "nav.warehouses" },
  { to: "/data/counterparties", icon: Building2, labelKey: "nav.counterparties" },
  { to: "/data/clients", icon: Users, labelKey: "nav.clients" },
  { to: "/data/items", icon: Package, labelKey: "nav.items" },
  { to: "/data/prices", icon: TrendingUp, labelKey: "nav.prices" },
  { to: "/data/turnover", icon: BarChart3, labelKey: "nav.turnover" },
];

// Work Logs module navigation (Дневник + Промени СМР)
const WORK_LOGS_NAV = [
  { to: "/daily-logs", icon: ClipboardPen, labelKey: "nav.dailyLogs" },
  { to: "/change-orders", icon: FilePlus2, labelKey: "nav.changeOrders" },
  { to: "/missing-smr", icon: AlertTriangle, labelKey: "nav.missingSMR" },
];

// Settings navigation
const SETTINGS_NAV = [
  { to: "/users", icon: Users, labelKey: "nav.users" },
  { to: "/settings", icon: Settings, labelKey: "nav.companySettings" },
];

// System management items (visible ONLY to platform admins)
const PLATFORM_ADMIN_NAV = [
  { to: "/billing", icon: CreditCard, labelKey: "nav.billing" },
  { to: "/mobile-settings", icon: Smartphone, labelKey: "nav.mobileApp" },
  { to: "/modules", icon: Blocks, labelKey: "nav.modules" },
  { to: "/audit-log", icon: ScrollText, labelKey: "nav.auditLog" },
];

const WORKER_NAV = [
  { to: "/", icon: LayoutDashboard, labelKey: "nav.dashboard" },
  { to: "/my-day", icon: CalendarCheck, labelKey: "nav.myDay" },
  { to: "/attendance-history", icon: CalendarDays, labelKey: "nav.history" },
  { to: "/projects", icon: FolderKanban, labelKey: "nav.projects" },
  { to: "/my-payslips", icon: Receipt, labelKey: "nav.myPayslips" },
];

// ══════════════════════════════════════════════════════════════════════════════
// MOBILE BOTTOM TAB NAVIGATION (role-based)
// ══════════════════════════════════════════════════════════════════════════════

// Technician: max 5 tabs
const TECHNICIAN_TABS = [
  { to: "/my-day", icon: ClipboardList, labelKey: "nav.requests" },
  { to: "/review-reports", icon: CalendarCheck, labelKey: "nav.reports" },
  { to: "/projects", icon: Package, labelKey: "nav.inventory" },
  { to: "/attendance-history", icon: RotateCcw, labelKey: "nav.returns" },
  { to: "/profile", icon: User, labelKey: "nav.profile" },
];

// Driver: max 4 tabs
const DRIVER_TABS = [
  { to: "/my-day", icon: Truck, labelKey: "nav.trips" },
  { to: "/projects", icon: ClipboardList, labelKey: "nav.requests" },
  { to: "/attendance-history", icon: RotateCcw, labelKey: "nav.returns" },
  { to: "/profile", icon: User, labelKey: "nav.profile" },
];

// Admin/Owner/SiteManager/Accountant: 4 tabs
const ADMIN_TABS = [
  { to: "/", icon: LayoutDashboard, labelKey: "nav.dashboard" },
  { to: "/review-reports", icon: ClipboardList, labelKey: "nav.requests" },
  { to: "/attendance-history", icon: RotateCcw, labelKey: "nav.returns" },
  { to: "/profile", icon: User, labelKey: "nav.profile" },
];

// Profile sub-menu items (shown in Profile page or sheet)
const PROFILE_MENU = [
  { to: "/settings", icon: Settings, labelKey: "nav.settings" },
  { action: "changePassword", icon: Lock, labelKey: "auth.changePassword" },
  { to: "/my-payslips", icon: Receipt, labelKey: "nav.myPayslips" },
  { to: "/notifications", icon: Bell, labelKey: "nav.notifications" },
  { action: "help", icon: HelpCircle, labelKey: "nav.help" },
  { action: "about", icon: Info, labelKey: "nav.about" },
  { action: "logout", icon: LogOut, labelKey: "auth.signOut" },
];

// Get tabs based on role
function getTabsForRole(role) {
  switch (role) {
    case "Technician":
    case "Worker":
    case "Warehousekeeper":
      return TECHNICIAN_TABS;
    case "Driver":
      return DRIVER_TABS;
    case "Admin":
    case "Owner":
    case "SiteManager":
    case "Accountant":
    default:
      return ADMIN_TABS;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// MOBILE PROFILE PAGE COMPONENT
// ══════════════════════════════════════════════════════════════════════════════

function MobileProfileMenu({ user, onLogout, onClose, onChangePassword }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const handleAction = (item) => {
    if (item.action === "logout") {
      onLogout();
    } else if (item.action === "changePassword") {
      onChangePassword?.();
      onClose?.();
    } else if (item.action === "help") {
      // TODO: Open help dialog
      alert(t("nav.helpComingSoon"));
    } else if (item.action === "about") {
      // TODO: Open about dialog
      alert("BEG_Work v1.0.0");
    } else if (item.to) {
      navigate(item.to);
      onClose?.();
    }
  };

  return (
    <div className="p-4 space-y-2">
      {/* User info */}
      <div className="flex items-center gap-3 p-4 bg-muted rounded-lg mb-4">
        <div className="w-12 h-12 rounded-full bg-primary/20 flex items-center justify-center text-lg font-bold text-primary">
          {user?.first_name?.[0]}{user?.last_name?.[0]}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-medium text-foreground truncate">
            {user?.first_name} {user?.last_name}
          </p>
          <p className="text-sm text-muted-foreground">{user?.role}</p>
          <p className="text-xs text-muted-foreground truncate">{user?.email}</p>
        </div>
      </div>

      {/* Menu items */}
      {PROFILE_MENU.map((item, idx) => (
        <button
          key={idx}
          onClick={() => handleAction(item)}
          className={`w-full flex items-center gap-3 p-3 rounded-lg text-left transition-colors ${
            item.action === "logout" 
              ? "text-destructive hover:bg-destructive/10" 
              : "hover:bg-muted"
          }`}
          data-testid={`profile-menu-${item.labelKey.split(".")[1]}`}
        >
          <item.icon className="w-5 h-5" />
          <span>{t(item.labelKey)}</span>
        </button>
      ))}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN LAYOUT COMPONENT
// ══════════════════════════════════════════════════════════════════════════════

export default function DashboardLayout({ children }) {
  const { user, org, logout } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [profileSheetOpen, setProfileSheetOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);
  const [dataExpanded, setDataExpanded] = useState(location.pathname.startsWith("/data"));
  const [workLogsExpanded, setWorkLogsExpanded] = useState(location.pathname.startsWith("/daily-logs") || location.pathname.startsWith("/change-orders") || location.pathname.startsWith("/missing-smr"));

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const mobileTabs = getTabsForRole(user?.role);
  const isProfileRoute = location.pathname === "/profile";
  const isPlatformAdmin = user?.is_platform_admin === true;
  const isAdmin = ["Admin","Owner","SiteManager","Accountant"].includes(user?.role);
  
  // Build navigation based on role and platform admin status
  const getAdminNav = () => {
    if (isPlatformAdmin) {
      return [...ADMIN_NAV_CORE, ...PLATFORM_ADMIN_NAV];
    }
    return ADMIN_NAV_CORE;
  };

  // Check if current path matches a tab (for active state)
  const isTabActive = (tabPath) => {
    if (tabPath === "/") return location.pathname === "/";
    return location.pathname.startsWith(tabPath);
  };

  // Render nav item
  const renderNavItem = (item) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === "/"}
      className={({ isActive }) =>
        `sidebar-link ${isActive ? "active" : "text-muted-foreground"}`
      }
      data-testid={`nav-${item.labelKey.split(".")[1]}`}
    >
      <item.icon className="w-[18px] h-[18px]" />
      <span className="flex-1">{t(item.labelKey)}</span>
      {location.pathname === item.to && (
        <ChevronRight className="w-4 h-4 opacity-50" />
      )}
    </NavLink>
  );

  return (
    <div className="flex h-screen overflow-hidden" data-testid="dashboard-layout">
      {/* ════════════════════════════════════════════════════════════════════ */}
      {/* DESKTOP SIDEBAR (hidden on mobile) */}
      {/* ════════════════════════════════════════════════════════════════════ */}
      <aside className="hidden md:flex w-[260px] flex-shrink-0 border-r border-border bg-card flex-col" data-testid="sidebar">
        {/* Brand */}
        <div className="flex items-center gap-3 px-5 h-16 border-b border-border">
          <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center">
            <HardHat className="w-5 h-5 text-primary-foreground" />
          </div>
          <div className="flex-1">
            <h1 className="text-sm font-bold tracking-tight text-foreground">BEG_Work</h1>
            <p className="text-[11px] text-muted-foreground truncate max-w-[150px]">{org?.name || t("common.loading")}</p>
          </div>
          <NotificationBell />
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto" data-testid="sidebar-nav">
          {/* Core nav items */}
          {(isAdmin ? getAdminNav() : WORKER_NAV).map(renderNavItem)}
          
          {/* Work Logs Section (Дневник + Промени СМР) - visible to all */}
          <Separator className="my-3" />
          <button
            onClick={() => setWorkLogsExpanded(!workLogsExpanded)}
            className="sidebar-link w-full text-muted-foreground hover:text-foreground"
            data-testid="nav-worklogs-toggle"
          >
            <ClipboardPen className="w-[18px] h-[18px]" />
            <span className="flex-1 text-left">{t("nav.workLogs") || "Дневник СМР"}</span>
            {workLogsExpanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
          {workLogsExpanded && (
            <div className="ml-4 space-y-1 border-l pl-3 border-border">
              {WORK_LOGS_NAV.map(renderNavItem)}
            </div>
          )}
          
          {/* Data Section (collapsible, only for admin roles) */}
          {isAdmin && (
            <>
              <Separator className="my-3" />
              <button
                onClick={() => setDataExpanded(!dataExpanded)}
                className="sidebar-link w-full text-muted-foreground hover:text-foreground"
                data-testid="nav-data-toggle"
              >
                <Archive className="w-[18px] h-[18px]" />
                <span className="flex-1 text-left">{t("nav.data")}</span>
                {dataExpanded ? (
                  <ChevronDown className="w-4 h-4" />
                ) : (
                  <ChevronRight className="w-4 h-4" />
                )}
              </button>
              {dataExpanded && (
                <div className="ml-4 space-y-1 border-l pl-3 border-border">
                  {DATA_NAV.map(renderNavItem)}
                </div>
              )}
            </>
          )}
          
          {/* Settings Section */}
          {isAdmin && (
            <>
              <Separator className="my-3" />
              {SETTINGS_NAV.map(renderNavItem)}
            </>
          )}
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
            <LanguageSwitcher />
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-muted-foreground hover:text-foreground"
            onClick={() => setChangePasswordOpen(true)}
            data-testid="change-password-button"
          >
            <Lock className="w-4 h-4 mr-2" />
            {t("auth.changePassword")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-muted-foreground hover:text-destructive"
            onClick={handleLogout}
            data-testid="logout-button"
          >
            <LogOut className="w-4 h-4 mr-2" />
            {t("auth.signOut")}
          </Button>
        </div>
      </aside>

      {/* ════════════════════════════════════════════════════════════════════ */}
      {/* MOBILE HEADER (visible on mobile only) */}
      {/* ════════════════════════════════════════════════════════════════════ */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 h-14 bg-card border-b border-border flex items-center justify-between px-4">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <HardHat className="w-4 h-4 text-primary-foreground" />
          </div>
          <span className="font-bold text-sm">BEG_Work</span>
        </div>
        <div className="flex items-center gap-2">
          <NotificationBell />
          <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" data-testid="mobile-menu-toggle">
                <Menu className="w-5 h-5" />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[280px] p-0">
              <div className="p-4 border-b border-border flex items-center justify-between">
                <span className="font-semibold">{t("nav.menu")}</span>
                <SheetClose asChild>
                  <Button variant="ghost" size="icon">
                    <X className="w-4 h-4" />
                  </Button>
                </SheetClose>
              </div>
              <nav className="p-2 space-y-1 overflow-y-auto max-h-[calc(100vh-120px)]">
                {(["Admin","Owner","SiteManager","Accountant"].includes(user?.role) ? getAdminNav() : WORKER_NAV).map((item) => (
                  <SheetClose asChild key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === "/"}
                      className={({ isActive }) =>
                        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm ${
                          isActive ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
                        }`
                      }
                    >
                      <item.icon className="w-4 h-4" />
                      <span>{t(item.labelKey)}</span>
                    </NavLink>
                  </SheetClose>
                ))}
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════════ */}
      {/* MAIN CONTENT */}
      {/* ════════════════════════════════════════════════════════════════════ */}
      <main 
        className="flex-1 overflow-y-auto bg-background md:pt-0 pt-14 pb-20 md:pb-0" 
        data-testid="main-content"
      >
        {children}
      </main>

      {/* ════════════════════════════════════════════════════════════════════ */}
      {/* MOBILE BOTTOM TAB BAR (visible on mobile only) */}
      {/* ════════════════════════════════════════════════════════════════════ */}
      <nav 
        className="md:hidden fixed bottom-0 left-0 right-0 z-40 h-16 bg-card border-t border-border flex items-center justify-around px-2"
        data-testid="mobile-bottom-tabs"
      >
        {mobileTabs.map((tab) => {
          const isActive = tab.to === "/profile" ? isProfileRoute : isTabActive(tab.to);
          
          // Special handling for Profile tab - opens sheet
          if (tab.to === "/profile") {
            return (
              <Sheet key={tab.to} open={profileSheetOpen} onOpenChange={setProfileSheetOpen}>
                <SheetTrigger asChild>
                  <button
                    className={`flex flex-col items-center justify-center flex-1 h-full gap-0.5 transition-colors ${
                      isActive ? "text-primary" : "text-muted-foreground"
                    }`}
                    data-testid={`tab-${tab.labelKey.split(".")[1]}`}
                  >
                    <tab.icon className={`w-5 h-5 ${isActive ? "stroke-[2.5]" : ""}`} />
                    <span className="text-[10px] font-medium">{t(tab.labelKey)}</span>
                  </button>
                </SheetTrigger>
                <SheetContent side="bottom" className="h-auto max-h-[80vh] rounded-t-xl">
                  <MobileProfileMenu 
                    user={user} 
                    onLogout={handleLogout} 
                    onClose={() => setProfileSheetOpen(false)}
                    onChangePassword={() => setChangePasswordOpen(true)}
                  />
                </SheetContent>
              </Sheet>
            );
          }

          return (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={`flex flex-col items-center justify-center flex-1 h-full gap-0.5 transition-colors ${
                isActive ? "text-primary" : "text-muted-foreground"
              }`}
              data-testid={`tab-${tab.labelKey.split(".")[1]}`}
            >
              <tab.icon className={`w-5 h-5 ${isActive ? "stroke-[2.5]" : ""}`} />
              <span className="text-[10px] font-medium">{t(tab.labelKey)}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Change Password Modal */}
      <ChangePasswordModal 
        open={changePasswordOpen} 
        onOpenChange={setChangePasswordOpen} 
      />
    </div>
  );
}
