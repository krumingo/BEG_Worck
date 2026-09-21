import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import DashboardLayout from "@/components/DashboardLayout";
import { canReadMasterData } from "@/lib/masterDataAccess";

/**
 * Route guard for the Master Data review screen only.
 *
 * AdminRoute admits Admin/Owner/SiteManager/Accountant, which is wrong for this
 * screen in both directions: the office (FLOW-032 "офисът мапва") holds the
 * rights to approve and reject but is not an admin role, while SiteManager and
 * Accountant may read the queue but not decide it. So this screen gets its own
 * guard, built from the canonical rights, and AdminRoute stays as it is.
 */
export default function MasterDataRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background" data-testid="md-route-loading">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!canReadMasterData(user.role)) return <Navigate to="/tech" replace />;
  return <DashboardLayout>{children}</DashboardLayout>;
}
