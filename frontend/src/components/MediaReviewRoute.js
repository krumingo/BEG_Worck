import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import DashboardLayout from "@/components/DashboardLayout";
import { canOpenMediaReview } from "@/lib/mediaReviewAccess";

/**
 * Route guard for "Файлове за преглед" only (MEDIA-SEC-01). AdminRoute also admits
 * SiteManager and Accountant, whom the server refuses on these lists (FG-558: Owner/Admin),
 * so the screen gets its own guard and AdminRoute stays as it is. Others land on "/".
 */
export default function MediaReviewRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background" data-testid="media-review-route-loading">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!canOpenMediaReview(user.role)) return <Navigate to="/" replace />;
  return <DashboardLayout>{children}</DashboardLayout>;
}
