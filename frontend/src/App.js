import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import DashboardLayout from "@/components/DashboardLayout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import UsersPage from "@/pages/UsersPage";
import CompanySettingsPage from "@/pages/CompanySettingsPage";
import ModuleTogglesPage from "@/pages/ModuleTogglesPage";
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
          <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
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
          <Route path="/users" element={<ProtectedRoute><UsersPage /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><CompanySettingsPage /></ProtectedRoute>} />
          <Route path="/modules" element={<ProtectedRoute><ModuleTogglesPage /></ProtectedRoute>} />
          <Route path="/audit-log" element={<ProtectedRoute><AuditLogPage /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
