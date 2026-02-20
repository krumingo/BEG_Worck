import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
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
import PaymentsPage from "@/pages/PaymentsPage";
import OverheadPage from "@/pages/OverheadPage";
import OverheadSnapshotDetailPage from "@/pages/OverheadSnapshotDetailPage";
// Platform Admin Pages
import PlatformLoginPage from "@/pages/PlatformLoginPage";
import PlatformDashboardPage from "@/pages/PlatformDashboardPage";
import PlatformBillingPage from "@/pages/PlatformBillingPage";
import PlatformModulesPage from "@/pages/PlatformModulesPage";
import PlatformAuditLogPage from "@/pages/PlatformAuditLogPage";
import PlatformMobileSettingsPage from "@/pages/PlatformMobileSettingsPage";

function ProtectedRoute({ children }) {
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

function PublicRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/" replace />;
  return children;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
          <Route path="/signup" element={<PublicRoute><SignupPage /></PublicRoute>} />
          
          {/* Platform Admin routes - protected by PlatformAdminGuard */}
          <Route path="/plans" element={<ProtectedRoute><PlatformAdminGuard><PlanSelectionPage /></PlatformAdminGuard></ProtectedRoute>} />
          <Route path="/billing" element={<ProtectedRoute><PlatformAdminGuard><BillingSettingsPage /></PlatformAdminGuard></ProtectedRoute>} />
          <Route path="/billing/success" element={<ProtectedRoute><PlatformAdminGuard><BillingSuccessPage /></PlatformAdminGuard></ProtectedRoute>} />
          <Route path="/billing/cancel" element={<BillingCancelPage />} />
          
          {/* Protected routes */}
          <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
          <Route path="/projects" element={<ProtectedRoute><ProjectsListPage /></ProtectedRoute>} />
          <Route path="/projects/:projectId" element={<ProtectedRoute><ProjectDetailPage /></ProtectedRoute>} />
          <Route path="/my-day" element={<ProtectedRoute><MyDayPage /></ProtectedRoute>} />
          <Route path="/attendance-history" element={<ProtectedRoute><AttendanceHistoryPage /></ProtectedRoute>} />
          <Route path="/site-attendance" element={<ProtectedRoute><SiteAttendancePage /></ProtectedRoute>} />
          <Route path="/work-reports/new" element={<ProtectedRoute><WorkReportFormPage /></ProtectedRoute>} />
          <Route path="/work-reports/:reportId" element={<ProtectedRoute><WorkReportFormPage /></ProtectedRoute>} />
          <Route path="/review-reports" element={<ProtectedRoute><WorkReportReviewPage /></ProtectedRoute>} />
          <Route path="/notifications" element={<ProtectedRoute><NotificationsPage /></ProtectedRoute>} />
          <Route path="/reminders" element={<ProtectedRoute><RemindersPage /></ProtectedRoute>} />
          <Route path="/offers" element={<ProtectedRoute><OffersListPage /></ProtectedRoute>} />
          <Route path="/offers/new" element={<ProtectedRoute><OfferEditorPage /></ProtectedRoute>} />
          <Route path="/offers/:offerId" element={<ProtectedRoute><OfferEditorPage /></ProtectedRoute>} />
          <Route path="/activity-catalog" element={<ProtectedRoute><ActivityCatalogPage /></ProtectedRoute>} />
          <Route path="/employees" element={<ProtectedRoute><EmployeesPage /></ProtectedRoute>} />
          <Route path="/advances" element={<ProtectedRoute><AdvancesPage /></ProtectedRoute>} />
          <Route path="/payroll" element={<ProtectedRoute><PayrollRunsPage /></ProtectedRoute>} />
          <Route path="/payroll/:runId" element={<ProtectedRoute><PayrollDetailPage /></ProtectedRoute>} />
          <Route path="/my-payslips" element={<ProtectedRoute><MyPayslipsPage /></ProtectedRoute>} />
          <Route path="/finance" element={<ProtectedRoute><FinanceOverviewPage /></ProtectedRoute>} />
          <Route path="/finance/accounts" element={<ProtectedRoute><FinancialAccountsPage /></ProtectedRoute>} />
          <Route path="/finance/invoices" element={<ProtectedRoute><InvoicesPage /></ProtectedRoute>} />
          <Route path="/finance/invoices/new" element={<ProtectedRoute><InvoiceEditorPage /></ProtectedRoute>} />
          <Route path="/finance/invoices/:invoiceId" element={<ProtectedRoute><InvoiceEditorPage /></ProtectedRoute>} />
          <Route path="/finance/payments" element={<ProtectedRoute><PaymentsPage /></ProtectedRoute>} />
          <Route path="/finance/payments/new" element={<ProtectedRoute><PaymentsPage /></ProtectedRoute>} />
          <Route path="/overhead" element={<ProtectedRoute><OverheadPage /></ProtectedRoute>} />
          <Route path="/overhead/snapshots/:snapshotId" element={<ProtectedRoute><OverheadSnapshotDetailPage /></ProtectedRoute>} />
          <Route path="/users" element={<ProtectedRoute><UsersPage /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><CompanySettingsPage /></ProtectedRoute>} />
          
          {/* Platform Admin Only routes */}
          <Route path="/mobile-settings" element={<ProtectedRoute><PlatformAdminGuard><MobileSettingsPage /></PlatformAdminGuard></ProtectedRoute>} />
          <Route path="/modules" element={<ProtectedRoute><PlatformAdminGuard><ModuleTogglesPage /></PlatformAdminGuard></ProtectedRoute>} />
          <Route path="/audit-log" element={<ProtectedRoute><PlatformAdminGuard><AuditLogPage /></PlatformAdminGuard></ProtectedRoute>} />
          
          {/* Platform Admin Portal - Separate login and layout */}
          <Route path="/platform/login" element={<PlatformLoginPage />} />
          <Route path="/platform" element={<PlatformLayout />}>
            <Route index element={<PlatformDashboardPage />} />
            <Route path="billing" element={<PlatformBillingPage />} />
            <Route path="modules" element={<PlatformModulesPage />} />
            <Route path="audit-log" element={<PlatformAuditLogPage />} />
            <Route path="mobile-settings" element={<PlatformMobileSettingsPage />} />
          </Route>
          
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
