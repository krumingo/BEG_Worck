import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth, PlatformAuthProvider, usePlatformAuth } from "@/contexts/AuthContext";
import DashboardLayout from "@/components/DashboardLayout";
import PlatformAdminGuard from "@/components/PlatformAdminGuard";
import PlatformLayout from "@/components/PlatformLayout";
import LoginPage from "@/pages/LoginPage";
import SignupPage from "@/pages/SignupPage";
import PlanSelectionPage from "@/pages/PlanSelectionPage";
import BillingSettingsPage from "@/pages/BillingSettingsPage";
import BillingSuccessPage from "@/pages/BillingSuccessPage";
import BillingCancelPage from "@/pages/BillingCancelPage";
import DashboardPage from "@/pages/DashboardPage";
import UsersPage from "@/pages/UsersPage";
import CompanySettingsPage from "@/pages/CompanySettingsPage";
import ModuleTogglesPage from "@/pages/ModuleTogglesPage";
import MobileSettingsPage from "@/pages/MobileSettingsPage";
import AuditLogPage from "@/pages/AuditLogPage";
import ProjectsListPage from "@/pages/ProjectsListPage";
import ProjectDetailPage from "@/pages/ProjectDetailPage";
import MyDayPage from "@/pages/MyDayPage";
import AttendanceHistoryPage from "@/pages/AttendanceHistoryPage";
import SiteAttendancePage from "@/pages/SiteAttendancePage";
import WorkReportFormPage from "@/pages/WorkReportFormPage";
import WorkReportReviewPage from "@/pages/WorkReportReviewPage";
import NotificationsPage from "@/pages/NotificationsPage";
import RemindersPage from "@/pages/RemindersPage";
import OffersListPage from "@/pages/OffersListPage";
import OfferEditorPage from "@/pages/OfferEditorPage";
import ActivityCatalogPage from "@/pages/ActivityCatalogPage";
import EmployeesPage from "@/pages/EmployeesPage";
import AdvancesPage from "@/pages/AdvancesPage";
import PayrollRunsPage from "@/pages/PayrollRunsPage";
import PayrollDetailPage from "@/pages/PayrollDetailPage";
import MyPayslipsPage from "@/pages/MyPayslipsPage";
import FinanceOverviewPage from "@/pages/FinanceOverviewPage";
import FinancialAccountsPage from "@/pages/FinancialAccountsPage";
import InvoicesPage from "@/pages/InvoicesPage";
import InvoiceEditorPage from "@/pages/InvoiceEditorPage";
import InvoiceLinesPage from "@/pages/InvoiceLinesPage";
import PaymentsPage from "@/pages/PaymentsPage";
import OverheadPage from "@/pages/OverheadPage";
import OverheadSnapshotDetailPage from "@/pages/OverheadSnapshotDetailPage";
// Data Module Pages
import WarehousesPage from "@/pages/WarehousesPage";
import CounterpartiesPage from "@/pages/CounterpartiesPage";
import ItemsPage from "@/pages/ItemsPage";
import PricesPage from "@/pages/PricesPage";
import TurnoverPage from "@/pages/TurnoverPage";
import ClientsPage from "@/pages/ClientsPage";
import FinanceDetailsPage from "@/pages/FinanceDetailsPage";
// Work Logs Module (Дневник + Промени СМР)
import DailyLogsPage from "@/pages/DailyLogsPage";
import ChangeOrdersPage from "@/pages/ChangeOrdersPage";
import AICalibrationPage from "@/pages/AICalibrationPage";
import OfferReviewPage from "@/pages/OfferReviewPage";
import ProcurementPage from "@/pages/ProcurementPage";
// Platform Admin Pages
import PlatformLoginPage from "@/pages/PlatformLoginPage";
import PlatformDashboardPage from "@/pages/PlatformDashboardPage";
import PlatformBillingPage from "@/pages/PlatformBillingPage";
import PlatformModulesPage from "@/pages/PlatformModulesPage";
import PlatformAuditLogPage from "@/pages/PlatformAuditLogPage";
import PlatformMobileSettingsPage from "@/pages/PlatformMobileSettingsPage";

// ═══════════════════════════════════════════════════════════════════════════
// COMPANY Routes - Protected by bw_token
// ═══════════════════════════════════════════════════════════════════════════

function CompanyProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <DashboardLayout>{children}</DashboardLayout>;
}

function CompanyPublicRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  // If logged in as company user, redirect to company dashboard
  if (user) return <Navigate to="/" replace />;
  return children;
}

// ═══════════════════════════════════════════════════════════════════════════
// PLATFORM Routes - Protected by bw_platform_token (SEPARATE)
// ═══════════════════════════════════════════════════════════════════════════

function PlatformProtectedRoute({ children }) {
  const { platformUser, loading } = usePlatformAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!platformUser) return <Navigate to="/platform/login" replace />;
  return children;
}

function PlatformPublicRoute({ children }) {
  const { platformUser, loading } = usePlatformAuth();
  if (loading) return null;
  // If logged in as platform user, redirect to platform dashboard
  if (platformUser) return <Navigate to="/platform" replace />;
  return children;
}

// ═══════════════════════════════════════════════════════════════════════════
// Main App with DUAL Auth Providers
// ═══════════════════════════════════════════════════════════════════════════

function AppRoutes() {
  return (
    <Routes>
      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* COMPANY Routes - use bw_token */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      
      {/* Public company routes */}
      <Route path="/login" element={<CompanyPublicRoute><LoginPage /></CompanyPublicRoute>} />
      <Route path="/signup" element={<CompanyPublicRoute><SignupPage /></CompanyPublicRoute>} />
      <Route path="/billing/cancel" element={<BillingCancelPage />} />
      {/* Public offer review - no auth needed */}
      <Route path="/offers/review/:reviewToken" element={<OfferReviewPage />} />
      
      {/* Protected company routes */}
      <Route path="/" element={<CompanyProtectedRoute><DashboardPage /></CompanyProtectedRoute>} />
      <Route path="/projects" element={<CompanyProtectedRoute><ProjectsListPage /></CompanyProtectedRoute>} />
      <Route path="/projects/:projectId" element={<CompanyProtectedRoute><ProjectDetailPage /></CompanyProtectedRoute>} />
      {/* Redirect old /sites routes to /projects */}
      <Route path="/sites" element={<Navigate to="/projects" replace />} />
      <Route path="/sites/:siteId" element={<Navigate to="/projects" replace />} />
      <Route path="/my-day" element={<CompanyProtectedRoute><MyDayPage /></CompanyProtectedRoute>} />
      <Route path="/attendance-history" element={<CompanyProtectedRoute><AttendanceHistoryPage /></CompanyProtectedRoute>} />
      <Route path="/site-attendance" element={<CompanyProtectedRoute><SiteAttendancePage /></CompanyProtectedRoute>} />
      <Route path="/work-reports/new" element={<CompanyProtectedRoute><WorkReportFormPage /></CompanyProtectedRoute>} />
      <Route path="/work-reports/:reportId" element={<CompanyProtectedRoute><WorkReportFormPage /></CompanyProtectedRoute>} />
      <Route path="/review-reports" element={<CompanyProtectedRoute><WorkReportReviewPage /></CompanyProtectedRoute>} />
      <Route path="/notifications" element={<CompanyProtectedRoute><NotificationsPage /></CompanyProtectedRoute>} />
      <Route path="/reminders" element={<CompanyProtectedRoute><RemindersPage /></CompanyProtectedRoute>} />
      <Route path="/offers" element={<CompanyProtectedRoute><OffersListPage /></CompanyProtectedRoute>} />
      <Route path="/offers/new" element={<CompanyProtectedRoute><OfferEditorPage /></CompanyProtectedRoute>} />
      <Route path="/offers/:offerId" element={<CompanyProtectedRoute><OfferEditorPage /></CompanyProtectedRoute>} />
      <Route path="/activity-catalog" element={<CompanyProtectedRoute><ActivityCatalogPage /></CompanyProtectedRoute>} />
      <Route path="/ai-calibration" element={<CompanyProtectedRoute><AICalibrationPage /></CompanyProtectedRoute>} />
      <Route path="/procurement" element={<CompanyProtectedRoute><ProcurementPage /></CompanyProtectedRoute>} />
      <Route path="/employees" element={<CompanyProtectedRoute><EmployeesPage /></CompanyProtectedRoute>} />
      <Route path="/advances" element={<CompanyProtectedRoute><AdvancesPage /></CompanyProtectedRoute>} />
      <Route path="/payroll" element={<CompanyProtectedRoute><PayrollRunsPage /></CompanyProtectedRoute>} />
      <Route path="/payroll/:runId" element={<CompanyProtectedRoute><PayrollDetailPage /></CompanyProtectedRoute>} />
      <Route path="/my-payslips" element={<CompanyProtectedRoute><MyPayslipsPage /></CompanyProtectedRoute>} />
      <Route path="/finance" element={<CompanyProtectedRoute><FinanceOverviewPage /></CompanyProtectedRoute>} />
      <Route path="/finance/accounts" element={<CompanyProtectedRoute><FinancialAccountsPage /></CompanyProtectedRoute>} />
      <Route path="/finance/invoices" element={<CompanyProtectedRoute><InvoicesPage /></CompanyProtectedRoute>} />
      <Route path="/finance/invoices/new" element={<CompanyProtectedRoute><InvoiceEditorPage /></CompanyProtectedRoute>} />
      <Route path="/finance/invoices/:invoiceId" element={<CompanyProtectedRoute><InvoiceEditorPage /></CompanyProtectedRoute>} />
      <Route path="/finance/invoices/:invoiceId/lines" element={<CompanyProtectedRoute><InvoiceLinesPage /></CompanyProtectedRoute>} />
      <Route path="/finance/payments" element={<CompanyProtectedRoute><PaymentsPage /></CompanyProtectedRoute>} />
      <Route path="/finance/payments/new" element={<CompanyProtectedRoute><PaymentsPage /></CompanyProtectedRoute>} />
      <Route path="/overhead" element={<CompanyProtectedRoute><OverheadPage /></CompanyProtectedRoute>} />
      <Route path="/overhead/snapshots/:snapshotId" element={<CompanyProtectedRoute><OverheadSnapshotDetailPage /></CompanyProtectedRoute>} />
      {/* Data Module Routes */}
      <Route path="/data/warehouses" element={<CompanyProtectedRoute><WarehousesPage /></CompanyProtectedRoute>} />
      <Route path="/data/counterparties" element={<CompanyProtectedRoute><CounterpartiesPage /></CompanyProtectedRoute>} />
      <Route path="/data/items" element={<CompanyProtectedRoute><ItemsPage /></CompanyProtectedRoute>} />
      <Route path="/data/prices" element={<CompanyProtectedRoute><PricesPage /></CompanyProtectedRoute>} />
      <Route path="/data/turnover" element={<CompanyProtectedRoute><TurnoverPage /></CompanyProtectedRoute>} />
      <Route path="/data/clients" element={<CompanyProtectedRoute><ClientsPage /></CompanyProtectedRoute>} />
      <Route path="/reports/finance-details" element={<CompanyProtectedRoute><FinanceDetailsPage /></CompanyProtectedRoute>} />
      {/* Work Logs Module (Дневник + Промени СМР) */}
      <Route path="/daily-logs" element={<CompanyProtectedRoute><DailyLogsPage /></CompanyProtectedRoute>} />
      <Route path="/change-orders" element={<CompanyProtectedRoute><ChangeOrdersPage /></CompanyProtectedRoute>} />
      <Route path="/users" element={<CompanyProtectedRoute><UsersPage /></CompanyProtectedRoute>} />
      <Route path="/settings" element={<CompanyProtectedRoute><CompanySettingsPage /></CompanyProtectedRoute>} />
      
      {/* Company routes that also require platform admin (hybrid) */}
      <Route path="/plans" element={<CompanyProtectedRoute><PlatformAdminGuard><PlanSelectionPage /></PlatformAdminGuard></CompanyProtectedRoute>} />
      <Route path="/billing" element={<CompanyProtectedRoute><PlatformAdminGuard><BillingSettingsPage /></PlatformAdminGuard></CompanyProtectedRoute>} />
      <Route path="/billing/success" element={<CompanyProtectedRoute><PlatformAdminGuard><BillingSuccessPage /></PlatformAdminGuard></CompanyProtectedRoute>} />
      <Route path="/mobile-settings" element={<CompanyProtectedRoute><PlatformAdminGuard><MobileSettingsPage /></PlatformAdminGuard></CompanyProtectedRoute>} />
      <Route path="/modules" element={<CompanyProtectedRoute><PlatformAdminGuard><ModuleTogglesPage /></PlatformAdminGuard></CompanyProtectedRoute>} />
      <Route path="/audit-log" element={<CompanyProtectedRoute><PlatformAdminGuard><AuditLogPage /></PlatformAdminGuard></CompanyProtectedRoute>} />
      
      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* PLATFORM Routes - use bw_platform_token (SEPARATE) */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      
      {/* Platform login - public */}
      <Route path="/platform/login" element={<PlatformPublicRoute><PlatformLoginPage /></PlatformPublicRoute>} />
      
      {/* Platform dashboard - protected by platform token */}
      <Route path="/platform" element={<PlatformProtectedRoute><PlatformLayout /></PlatformProtectedRoute>}>
        <Route index element={<PlatformDashboardPage />} />
        <Route path="billing" element={<PlatformBillingPage />} />
        <Route path="modules" element={<PlatformModulesPage />} />
        <Route path="audit-log" element={<PlatformAuditLogPage />} />
        <Route path="mobile-settings" element={<PlatformMobileSettingsPage />} />
      </Route>
      
      {/* Platform logout */}
      <Route path="/platform/logout" element={<PlatformLogoutRoute />} />
      
      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function PlatformLogoutRoute() {
  const { platformLogout } = usePlatformAuth();
  platformLogout();
  return <Navigate to="/platform/login" replace />;
}

function App() {
  return (
    <AuthProvider>
      <PlatformAuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </PlatformAuthProvider>
    </AuthProvider>
  );
}

export default App;
