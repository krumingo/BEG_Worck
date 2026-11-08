import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import DashboardLayout from "@/components/DashboardLayout";
import { canOpenCanonicalWarehouse } from "@/lib/warehouseCanonicalAccess";

/**
 * Route guard for the canonical warehouse screen only (5C-C19 F-6).
 *
 * AdminRoute (Admin/Owner/SiteManager/Accountant) was wrong for this screen in
 * both directions: the Warehousekeeper, who may receive / dispatch / accept on
 * the API, was sent to /tech, while the read-only Accountant got the write
 * form. The guard follows the canonical catalog instead; what the screen then
 * shows (read tabs, write tab, action list) follows the same rights.
 */
export default function CanonicalWarehouseRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background" data-testid="wh-route-loading">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!canOpenCanonicalWarehouse(user.role)) return <Navigate to="/tech" replace />;
  return <DashboardLayout>{children}</DashboardLayout>;
}
