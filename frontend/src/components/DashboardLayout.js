import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useActiveProject } from "@/contexts/ProjectContext";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  LayoutDashboard, Users, Building2, Blocks, ScrollText, LogOut,
  ChevronRight, ChevronDown, HardHat, FolderKanban, CalendarCheck,
  CalendarDays, ClipboardList, Bell, FileText, Layers, Receipt,
  Wallet, UserCog, Landmark, Calculator, CreditCard, Smartphone,
  User, Package, Truck, RotateCcw, Settings, HelpCircle, Info,
  Menu, X, Lock, Archive, Warehouse, TrendingUp, BarChart3,
  FilePlus2, ClipboardPen, Sparkles, AlertTriangle, Briefcase, ScanLine,
} from "lucide-react";
import NotificationBell from "@/components/NotificationBell";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ChangePasswordModal from "@/components/ChangePasswordModal";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetTrigger, SheetClose } from "@/components/ui/sheet";

// ══════════════════════════════════════════════════════════════════
// GROUPED NAVIGATION STRUCTURE
// ══════════════════════════════════════════════════════════════════

const NAV_GROUPS = [
  { id: "dashboard", to: "/", icon: LayoutDashboard, labelKey: "nav.dashboard", standalone: true },
  {
    id: "objects", icon: FolderKanban, labelKey: "nav.objects",
    children: [
      { to: "/projects", icon: FolderKanban, labelKey: "nav.projects" },
      { to: "/site-attendance", icon: ClipboardList, labelKey: "nav.siteAttendance" },
      { to: "/tech", icon: ClipboardPen, labelKey: "nav.fieldPortal" },
    ],
  },
  {
    id: "smr", icon: FileText, labelKey: "nav.smrOffers",
    children: [
      { to: "/offers", icon: FileText, labelKey: "nav.offers" },
      { to: "/smr-analyses", icon: Calculator, labelKey: "nav.smrAnalysis" },
      { to: "/pricing", icon: TrendingUp, labelKey: "nav.pricing" },
      { to: "/activity-catalog", icon: Layers, labelKey: "nav.activities" },
      { to: "/ai-calibration", icon: Sparkles, labelKey: "nav.aiCalibration" },
      { to: "/historical-offers", icon: Archive, labelKey: "nav.historicalOffers" },
    ],
  },
  {
    id: "worklogs", icon: ClipboardPen, labelKey: "nav.workLogs",
    children: [
      { to: "/all-reports", icon: FileText, labelKey: "nav.allReports" },
      { to: "/daily-logs", icon: ClipboardPen, labelKey: "nav.dailyLogs" },
      { to: "/change-orders", icon: FilePlus2, labelKey: "nav.changeOrders" },
      { to: "/missing-smr", icon: AlertTriangle, labelKey: "nav.missingSMR" },
      { to: "/reports", icon: CalendarCheck, labelKey: "nav.reviewReports" },
    ],
  },
  {
    id: "personnel", icon: UserCog, labelKey: "nav.personnel",
    children: [
      { to: "/employees", icon: UserCog, labelKey: "nav.employees" },
      { to: "/pay-runs", icon: Receipt, labelKey: "nav.payRuns" },
      { to: "/worker-calendar", icon: CalendarDays, labelKey: "nav.workerCalendar" },
      { to: "/advances", icon: Wallet, labelKey: "nav.advances" },
      { to: "/contract-payments", icon: Briefcase, labelKey: "nav.contractPayments" },
    ],
  },
  {
    id: "finances", icon: Landmark, labelKey: "nav.finances",
    children: [
      { to: "/finance", icon: Landmark, labelKey: "nav.finance" },
      { to: "/overhead", icon: Calculator, labelKey: "nav.overhead" },
      { to: "/ocr-invoices", icon: ScanLine, labelKey: "nav.ocrInvoices" },
      { to: "/reports/finance-details", icon: BarChart3, labelKey: "nav.financeDetails" },
    ],
  },
  {
    id: "warehouse", icon: Package, labelKey: "nav.warehouseGroup",
    children: [
      { to: "/procurement", icon: Package, labelKey: "nav.procurement" },
      { to: "/inventory", icon: Warehouse, labelKey: "nav.inventory" },
      { to: "/data/warehouses", icon: Warehouse, labelKey: "nav.warehouses" },
      { to: "/data/items", icon: Package, labelKey: "nav.items" },
    ],
  },
  { id: "alarms", to: "/alarms", icon: Bell, labelKey: "nav.alarms", standalone: true, badge: true },
  {
    id: "reference", icon: Archive, labelKey: "nav.reference",
    children: [
      { to: "/data/counterparties", icon: Building2, labelKey: "nav.counterparties" },
      { to: "/data/clients", icon: Users, labelKey: "nav.clients" },
      { to: "/data/prices", icon: TrendingUp, labelKey: "nav.prices" },
      { to: "/data/turnover", icon: BarChart3, labelKey: "nav.turnover" },
    ],
  },
  {
    id: "settings", icon: Settings, labelKey: "nav.settingsGroup", platformAdminOnly: false,
    children: [
      { to: "/settings", icon: Settings, labelKey: "nav.companySettings" },
      { to: "/users", icon: Users, labelKey: "nav.users" },
    ],
  },
];

const PLATFORM_ADMIN_CHILDREN = [
  { to: "/billing", icon: CreditCard, labelKey: "nav.billing" },
  { to: "/mobile-settings", icon: Smartphone, labelKey: "nav.mobileApp" },
  { to: "/modules", icon: Blocks, labelKey: "nav.modules" },
  { to: "/audit-log", icon: ScrollText, labelKey: "nav.auditLog" },
];

const WORKER_NAV = [
  { to: "/tech", icon: ClipboardList, labelKey: "nav.techDashboard" },
  { to: "/", icon: LayoutDashboard, labelKey: "nav.dashboard" },
  { to: "/my-day", icon: CalendarCheck, labelKey: "nav.myDay" },
  { to: "/attendance-history", icon: CalendarDays, labelKey: "nav.history" },
  { to: "/projects", icon: FolderKanban, labelKey: "nav.projects" },
  { to: "/my-payslips", icon: Receipt, labelKey: "nav.myPayslips" },
];

// Mobile tabs (unchanged)
const TECHNICIAN_TABS = [
  { to: "/my-day", icon: ClipboardList, labelKey: "nav.requests" },
  { to: "/review-reports", icon: CalendarCheck, labelKey: "nav.reports" },
  { to: "/projects", icon: Package, labelKey: "nav.inventory" },
  { to: "/attendance-history", icon: RotateCcw, labelKey: "nav.returns" },
  { to: "/profile", icon: User, labelKey: "nav.profile" },
];
const DRIVER_TABS = [
  { to: "/my-day", icon: Truck, labelKey: "nav.trips" },
  { to: "/projects", icon: ClipboardList, labelKey: "nav.requests" },
  { to: "/attendance-history", icon: RotateCcw, labelKey: "nav.returns" },
  { to: "/profile", icon: User, labelKey: "nav.profile" },
];
const ADMIN_TABS = [
  { to: "/", icon: LayoutDashboard, labelKey: "nav.dashboard" },
  { to: "/review-reports", icon: ClipboardList, labelKey: "nav.requests" },
  { to: "/attendance-history", icon: RotateCcw, labelKey: "nav.returns" },
  { to: "/profile", icon: User, labelKey: "nav.profile" },
];

const PROFILE_MENU = [
  { to: "/settings", icon: Settings, labelKey: "nav.settings" },
  { action: "changePassword", icon: Lock, labelKey: "auth.changePassword" },
  { to: "/my-payslips", icon: Receipt, labelKey: "nav.myPayslips" },
  { to: "/notifications", icon: Bell, labelKey: "nav.notifications" },
  { action: "help", icon: HelpCircle, labelKey: "nav.help" },
  { action: "about", icon: Info, labelKey: "nav.about" },
  { action: "logout", icon: LogOut, labelKey: "auth.signOut" },
];

function getTabsForRole(role) {
  switch (role) {
    case "Technician": case "Worker": case "Warehousekeeper": return TECHNICIAN_TABS;
    case "Driver": return DRIVER_TABS;
    default: return ADMIN_TABS;
  }
}

// ══════════════════════════════════════════════════════════════════
// MOBILE PROFILE MENU
// ══════════════════════════════════════════════════════════════════

function MobileProfileMenu({ user, onLogout, onClose, onChangePassword }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const handleAction = (item) => {
    if (item.action === "logout") { onLogout(); }
    else if (item.action === "changePassword") { onChangePassword?.(); onClose?.(); }
    else if (item.action === "help") { alert(t("nav.helpComingSoon")); }
    else if (item.action === "about") { alert("BEG_Work v1.0.0"); }
    else if (item.to) { navigate(item.to); onClose?.(); }
  };
  return (
    <div className="py-4 px-2 space-y-1">
      <div className="px-3 mb-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-primary/20 flex items-center justify-center text-lg font-bold text-primary">{user?.first_name?.[0]}{user?.last_name?.[0]}</div>
          <div><p className="font-semibold">{user?.first_name} {user?.last_name}</p><p className="text-sm text-muted-foreground">{user?.email}</p></div>
        </div>
      </div>
      {PROFILE_MENU.map((item, i) => (
        <button key={i} onClick={() => handleAction(item)} className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm ${item.action === "logout" ? "text-destructive hover:bg-destructive/10" : "text-muted-foreground hover:bg-muted"}`}>
          <item.icon className="w-4 h-4" /><span>{t(item.labelKey)}</span>
        </button>
      ))}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// MAIN LAYOUT
// ══════════════════════════════════════════════════════════════════

export default function DashboardLayout({ children }) {
  const { user, org, logout } = useAuth();
  const { activeProject, clearActiveProject } = useActiveProject();
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [profileSheetOpen, setProfileSheetOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  // Expand state: auto-expand group containing current path
  const [expanded, setExpanded] = useState(() => {
    const saved = {};
    for (const g of NAV_GROUPS) {
      if (g.children) {
        const active = g.children.some(c => location.pathname === c.to || location.pathname.startsWith(c.to + "/"));
        if (active) saved[g.id] = true;
      }
    }
    return saved;
  });

  const toggleGroup = (id) => setExpanded(prev => ({ ...prev, [id]: !prev[id] }));

  const handleLogout = () => { logout(); navigate("/login"); };
  const mobileTabs = getTabsForRole(user?.role);
  const isProfileRoute = location.pathname === "/profile";
  const isPlatformAdmin = user?.is_platform_admin === true;
  const isAdmin = ["Admin", "Owner", "SiteManager", "Accountant"].includes(user?.role);

  const isTabActive = (tabPath) => tabPath === "/" ? location.pathname === "/" : location.pathname.startsWith(tabPath);

  // Build effective groups for admin (add platform admin children to settings)
  const getGroups = () => {
    return NAV_GROUPS.map(g => {
      if (g.id === "settings" && isPlatformAdmin) {
        return { ...g, children: [...(g.children || []), ...PLATFORM_ADMIN_CHILDREN] };
      }
      return g;
    });
  };

  const renderNavItem = (item, inGroup = false) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === "/"}
      className={({ isActive }) => `sidebar-link ${isActive ? "active" : "text-muted-foreground"}`}
      data-testid={`nav-${item.labelKey.split(".")[1]}`}
    >
      <item.icon className="w-[18px] h-[18px]" />
      <span className="flex-1">{t(item.labelKey)}</span>
      {location.pathname === item.to && <ChevronRight className="w-4 h-4 opacity-50" />}
    </NavLink>
  );

  const renderGroupedNav = () => {
    const groups = getGroups();
    return groups.map((g, gi) => {
      if (g.standalone) {
        return (
          <div key={g.id}>
            {gi > 0 && <Separator className="my-2" />}
            {renderNavItem({ to: g.to, icon: g.icon, labelKey: g.labelKey })}
          </div>
        );
      }

      const isOpen = expanded[g.id];
      const hasActive = g.children?.some(c => location.pathname === c.to || location.pathname.startsWith(c.to + "/"));
      const Icon = g.icon;

      return (
        <div key={g.id}>
          {gi > 0 && gi !== 1 && <Separator className="my-2" />}
          <button
            onClick={() => toggleGroup(g.id)}
            className={`sidebar-link w-full ${hasActive ? "text-foreground" : "text-muted-foreground"} hover:text-foreground`}
            data-testid={`nav-group-${g.id}`}
          >
            <Icon className="w-[18px] h-[18px]" />
            <span className="flex-1 text-left text-[13px] font-medium">{t(g.labelKey)}</span>
            {isOpen ? <ChevronDown className="w-3.5 h-3.5 opacity-50" /> : <ChevronRight className="w-3.5 h-3.5 opacity-50" />}
          </button>
          {isOpen && (
            <div className="ml-4 space-y-0.5 border-l pl-3 border-border/50">
              {g.children.map(c => renderNavItem(c, true))}
            </div>
          )}
        </div>
      );
    });
  };

  return (
    <div className="flex h-screen overflow-hidden" data-testid="dashboard-layout">
      {/* DESKTOP SIDEBAR */}
      <aside className="hidden md:flex w-[260px] flex-shrink-0 border-r border-border bg-card flex-col" data-testid="sidebar">
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

        {/* Active Project Banner */}
        {activeProject && (
          <div className="mx-3 mb-1 px-3 py-2 rounded-lg bg-primary/10 border border-primary/20 flex items-center gap-2" data-testid="active-project-banner">
            <Building2 className="w-3.5 h-3.5 text-primary flex-shrink-0" />
            <span className="text-[11px] text-primary truncate flex-1">{activeProject.name}</span>
            <button onClick={clearActiveProject} className="text-muted-foreground hover:text-foreground p-0.5"><X className="w-3 h-3" /></button>
          </div>
        )}

        <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto" data-testid="sidebar-nav">
          {isAdmin ? renderGroupedNav() : WORKER_NAV.map(item => renderNavItem(item))}
        </nav>

        <Separator />
        <div className="px-4 py-4" data-testid="sidebar-user">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-xs font-bold text-primary">{user?.first_name?.[0]}{user?.last_name?.[0]}</div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">{user?.first_name} {user?.last_name}</p>
              <p className="text-[11px] text-muted-foreground truncate">{user?.role}</p>
            </div>
            <LanguageSwitcher />
          </div>
          <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground hover:text-foreground" onClick={() => setChangePasswordOpen(true)} data-testid="change-password-button">
            <Lock className="w-4 h-4 mr-2" />{t("auth.changePassword")}
          </Button>
          <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground hover:text-destructive" onClick={handleLogout} data-testid="logout-button">
            <LogOut className="w-4 h-4 mr-2" />{t("auth.signOut")}
          </Button>
        </div>
      </aside>

      {/* MOBILE HEADER */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 h-14 bg-card border-b border-border flex items-center justify-between px-4">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center"><HardHat className="w-4 h-4 text-primary-foreground" /></div>
          <span className="font-bold text-sm">BEG_Work</span>
        </div>
        <div className="flex items-center gap-2">
          <NotificationBell />
          <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
            <SheetTrigger asChild><Button variant="ghost" size="icon" data-testid="mobile-menu-toggle"><Menu className="w-5 h-5" /></Button></SheetTrigger>
            <SheetContent side="right" className="w-[280px] p-0">
              <div className="p-4 border-b border-border flex items-center justify-between">
                <span className="font-semibold">{t("nav.menu")}</span>
                <SheetClose asChild><Button variant="ghost" size="icon"><X className="w-4 h-4" /></Button></SheetClose>
              </div>
              <nav className="p-2 space-y-1 overflow-y-auto max-h-[calc(100vh-120px)]">
                {isAdmin ? getGroups().map(g => {
                  if (g.standalone) {
                    return (
                      <SheetClose asChild key={g.id}>
                        <NavLink to={g.to} end={g.to === "/"} className={({ isActive }) => `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm ${isActive ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}>
                          <g.icon className="w-4 h-4" /><span>{t(g.labelKey)}</span>
                        </NavLink>
                      </SheetClose>
                    );
                  }
                  return (
                    <div key={g.id}>
                      <p className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold mt-2">{t(g.labelKey)}</p>
                      {g.children?.map(c => (
                        <SheetClose asChild key={c.to}>
                          <NavLink to={c.to} className={({ isActive }) => `flex items-center gap-3 px-3 py-2 rounded-lg text-sm ${isActive ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}>
                            <c.icon className="w-4 h-4" /><span>{t(c.labelKey)}</span>
                          </NavLink>
                        </SheetClose>
                      ))}
                    </div>
                  );
                }) : WORKER_NAV.map(item => (
                  <SheetClose asChild key={item.to}>
                    <NavLink to={item.to} end={item.to === "/"} className={({ isActive }) => `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm ${isActive ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}>
                      <item.icon className="w-4 h-4" /><span>{t(item.labelKey)}</span>
                    </NavLink>
                  </SheetClose>
                ))}
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>

      {/* MAIN CONTENT */}
      <main className="flex-1 overflow-y-auto bg-background md:pt-0 pt-14 pb-20 md:pb-0" data-testid="main-content">{children}</main>

      {/* MOBILE BOTTOM TABS */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 h-16 bg-card border-t border-border flex items-center justify-around px-2" data-testid="mobile-bottom-tabs">
        {mobileTabs.map((tab) => {
          const isActive = tab.to === "/profile" ? isProfileRoute : isTabActive(tab.to);
          if (tab.to === "/profile") {
            return (
              <Sheet key={tab.to} open={profileSheetOpen} onOpenChange={setProfileSheetOpen}>
                <SheetTrigger asChild>
                  <button className={`flex flex-col items-center justify-center flex-1 h-full gap-0.5 transition-colors ${isActive ? "text-primary" : "text-muted-foreground"}`} data-testid={`tab-${tab.labelKey.split(".")[1]}`}>
                    <tab.icon className={`w-5 h-5 ${isActive ? "stroke-[2.5]" : ""}`} />
                    <span className="text-[10px] font-medium">{t(tab.labelKey)}</span>
                  </button>
                </SheetTrigger>
                <SheetContent side="bottom" className="h-auto max-h-[80vh] rounded-t-xl">
                  <MobileProfileMenu user={user} onLogout={handleLogout} onClose={() => setProfileSheetOpen(false)} onChangePassword={() => setChangePasswordOpen(true)} />
                </SheetContent>
              </Sheet>
            );
          }
          return (
            <NavLink key={tab.to} to={tab.to} className={`flex flex-col items-center justify-center flex-1 h-full gap-0.5 transition-colors ${isActive ? "text-primary" : "text-muted-foreground"}`} data-testid={`tab-${tab.labelKey.split(".")[1]}`}>
              <tab.icon className={`w-5 h-5 ${isActive ? "stroke-[2.5]" : ""}`} />
              <span className="text-[10px] font-medium">{t(tab.labelKey)}</span>
            </NavLink>
          );
        })}
      </nav>

      <ChangePasswordModal open={changePasswordOpen} onOpenChange={setChangePasswordOpen} />
    </div>
  );
}
