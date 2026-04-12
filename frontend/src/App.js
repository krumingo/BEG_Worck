import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth, PlatformAuthProvider, usePlatformAuth } from "@/contexts/AuthContext";
import { ProjectProvider } from "@/contexts/ProjectContext";
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
import PayRunsPage from "@/pages/PayRunsPage";
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
import InventoryDashboardPage from "@/pages/InventoryDashboardPage";
import HistoricalOffersPage from "@/pages/HistoricalOffersPage";
import EmployeeDetailPage from "@/pages/EmployeeDetailPage";
import NovoSMRPage from "@/pages/NovoSMRPage";
import ProjectFinancialPage from "@/pages/ProjectFinancialPage";
import ProjectProgressPage from "@/pages/ProjectProgressPage";
import ProjectOperationsPage from "@/pages/ProjectOperationsPage";
import ReportsModulePage from "@/pages/ReportsModulePage";
import MissingSMRPage from "@/pages/MissingSMRPage";
import SMRAnalysisListPage from "@/pages/SMRAnalysisListPage";
import SMRAnalysisPage from "@/pages/SMRAnalysisPage";
import MaterialCatalogPage from "@/pages/MaterialCatalogPage";
import ContractPaymentsPage from "@/pages/ContractPaymentsPage";
import WorkerCalendarPage from "@/pages/WorkerCalendarPage";
import AlarmsDashboardPage from "@/pages/AlarmsDashboardPage";
import TechnicianDashboard from "@/pages/TechnicianDashboard";
import ClientDetailPage from "@/pages/ClientDetailPage";
import AllReportsPage from "@/pages/AllReportsPage";
import OCRInvoicePage from "@/pages/OCRInvoicePage";
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

// Admin-only route guard: redirects non-admin roles to /tech
const ADMIN_ROLES = ["Admin", "Owner", "SiteManager", "Accountant"];
function AdminRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!ADMIN_ROLES.includes(user.role)) return <Navigate to="/tech" replace />;
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
      
      {/* Routes accessible to ALL authenticated users (including Technician/Worker) */}
      <Route path="/" element={<CompanyProtectedRoute><DashboardPage /></CompanyProtectedRoute>} />
      <Route path="/projects" element={<CompanyProtectedRoute><ProjectsListPage /></CompanyProtectedRoute>} />
      <Route path="/projects/:projectId" element={<CompanyProtectedRoute><ProjectDetailPage /></CompanyProtectedRoute>} />
      <Route path="/sites" element={<Navigate to="/projects" replace />} />
      <Route path="/sites/:siteId" element={<Navigate to="/projects" replace />} />
      <Route path="/my-day" element={<CompanyProtectedRoute><MyDayPage /></CompanyProtectedRoute>} />
      <Route path="/attendance-history" element={<CompanyProtectedRoute><AttendanceHistoryPage /></CompanyProtectedRoute>} />
      <Route path="/my-payslips" element={<CompanyProtectedRoute><MyPayslipsPage /></CompanyProtectedRoute>} />
      <Route path="/tech" element={<CompanyProtectedRoute><TechnicianDashboard /></CompanyProtectedRoute>} />
      <Route path="/notifications" element={<CompanyProtectedRoute><NotificationsPage /></CompanyProtectedRoute>} />

      {/* Admin-only routes — Technician/Worker/Driver redirected to /tech */}
      <Route path="/site-attendance" element={<AdminRoute><SiteAttendancePage /></AdminRoute>} />
      <Route path="/work-reports/new" element={<AdminRoute><WorkReportFormPage /></AdminRoute>} />
      <Route path="/work-reports/:reportId" element={<AdminRoute><WorkReportFormPage /></AdminRoute>} />
      <Route path="/review-reports" element={<AdminRoute><WorkReportReviewPage /></AdminRoute>} />
      <Route path="/reports" element={<AdminRoute><ReportsModulePage /></AdminRoute>} />
      <Route path="/reminders" element={<AdminRoute><RemindersPage /></AdminRoute>} />
      <Route path="/offers" element={<AdminRoute><OffersListPage /></AdminRoute>} />
      <Route path="/offers/new" element={<AdminRoute><OfferEditorPage /></AdminRoute>} />
      <Route path="/offers/:offerId" element={<AdminRoute><OfferEditorPage /></AdminRoute>} />
      <Route path="/activity-catalog" element={<AdminRoute><ActivityCatalogPage /></AdminRoute>} />
      <Route path="/ai-calibration" element={<AdminRoute><AICalibrationPage /></AdminRoute>} />
      <Route path="/procurement" element={<AdminRoute><ProcurementPage /></AdminRoute>} />
      <Route path="/inventory" element={<AdminRoute><InventoryDashboardPage /></AdminRoute>} />
      <Route path="/historical-offers" element={<AdminRoute><HistoricalOffersPage /></AdminRoute>} />
      <Route path="/employees" element={<AdminRoute><EmployeesPage /></AdminRoute>} />
      <Route path="/employees/:userId" element={<AdminRoute><EmployeeDetailPage /></AdminRoute>} />
      <Route path="/projects/:projectId/novo-smr" element={<AdminRoute><NovoSMRPage /></AdminRoute>} />
      <Route path="/projects/:projectId/financial" element={<AdminRoute><ProjectFinancialPage /></AdminRoute>} />
      <Route path="/projects/:projectId/progress" element={<AdminRoute><ProjectProgressPage /></AdminRoute>} />
      <Route path="/projects/:projectId/operations" element={<AdminRoute><ProjectOperationsPage /></AdminRoute>} />
      <Route path="/advances" element={<AdminRoute><AdvancesPage /></AdminRoute>} />
      <Route path="/payroll" element={<AdminRoute><PayrollRunsPage /></AdminRoute>} />
      <Route path="/payroll/:runId" element={<AdminRoute><PayrollDetailPage /></AdminRoute>} />
      <Route path="/pay-runs" element={<AdminRoute><PayRunsPage /></AdminRoute>} />
      <Route path="/finance" element={<AdminRoute><FinanceOverviewPage /></AdminRoute>} />
      <Route path="/finance/accounts" element={<AdminRoute><FinancialAccountsPage /></AdminRoute>} />
      <Route path="/finance/invoices" element={<AdminRoute><InvoicesPage /></AdminRoute>} />
      <Route path="/finance/invoices/new" element={<AdminRoute><InvoiceEditorPage /></AdminRoute>} />
      <Route path="/finance/invoices/:invoiceId" element={<AdminRoute><InvoiceEditorPage /></AdminRoute>} />
      <Route path="/finance/invoices/:invoiceId/lines" element={<AdminRoute><InvoiceLinesPage /></AdminRoute>} />
      <Route path="/finance/payments" element={<AdminRoute><PaymentsPage /></AdminRoute>} />
      <Route path="/finance/payments/new" element={<AdminRoute><PaymentsPage /></AdminRoute>} />
      <Route path="/overhead" element={<AdminRoute><OverheadPage /></AdminRoute>} />
      <Route path="/overhead/snapshots/:snapshotId" element={<AdminRoute><OverheadSnapshotDetailPage /></AdminRoute>} />
      {/* Data Module Routes */}
      <Route path="/data/warehouses" element={<AdminRoute><WarehousesPage /></AdminRoute>} />
      <Route path="/data/counterparties" element={<AdminRoute><CounterpartiesPage /></AdminRoute>} />
      <Route path="/data/items" element={<AdminRoute><ItemsPage /></AdminRoute>} />
      <Route path="/data/prices" element={<AdminRoute><PricesPage /></AdminRoute>} />
      <Route path="/data/turnover" element={<AdminRoute><TurnoverPage /></AdminRoute>} />
      <Route path="/data/clients" element={<AdminRoute><ClientsPage /></AdminRoute>} />
      <Route path="/reports/finance-details" element={<AdminRoute><FinanceDetailsPage /></AdminRoute>} />
      {/* Work Logs Module */}
      <Route path="/daily-logs" element={<AdminRoute><DailyLogsPage /></AdminRoute>} />
      <Route path="/change-orders" element={<AdminRoute><ChangeOrdersPage /></AdminRoute>} />
      <Route path="/missing-smr" element={<AdminRoute><MissingSMRPage /></AdminRoute>} />
      <Route path="/smr-analyses" element={<AdminRoute><SMRAnalysisListPage /></AdminRoute>} />
      <Route path="/projects/:projectId/smr-analysis/:analysisId" element={<AdminRoute><SMRAnalysisPage /></AdminRoute>} />
      <Route path="/pricing" element={<AdminRoute><MaterialCatalogPage /></AdminRoute>} />
      <Route path="/contract-payments" element={<AdminRoute><ContractPaymentsPage /></AdminRoute>} />
      <Route path="/worker-calendar" element={<AdminRoute><WorkerCalendarPage /></AdminRoute>} />
      <Route path="/alarms" element={<AdminRoute><AlarmsDashboardPage /></AdminRoute>} />
      <Route path="/all-reports" element={<AdminRoute><AllReportsPage /></AdminRoute>} />
      <Route path="/clients/:clientId" element={<AdminRoute><ClientDetailPage /></AdminRoute>} />
      <Route path="/ocr-invoices" element={<AdminRoute><OCRInvoicePage /></AdminRoute>} />
      <Route path="/users" element={<AdminRoute><UsersPage /></AdminRoute>} />
      <Route path="/settings" element={<AdminRoute><CompanySettingsPage /></AdminRoute>} />
      
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
        <ProjectProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </ProjectProvider>
      </PlatformAuthProvider>
    </AuthProvider>
  );
}

export default App;
