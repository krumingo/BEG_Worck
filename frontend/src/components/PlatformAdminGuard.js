import { useAuth } from "@/contexts/AuthContext";
import NotAuthorizedPage from "@/pages/NotAuthorizedPage";

/**
 * Guard component that restricts access to platform admin only.
 * 
 * Usage:
 *   <PlatformAdminGuard>
 *     <BillingPage />
 *   </PlatformAdminGuard>
 * 
 * Non-platform-admin users will see a "Not Authorized" page.
 */
export default function PlatformAdminGuard({ children }) {
  const { user } = useAuth();
  
  // Check if user is a platform admin
  if (!user?.is_platform_admin) {
    return <NotAuthorizedPage />;
  }
  
  return children;
}
