import { createContext, useContext, useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { clearTenantLocalData, noteActiveTenant } from "@/lib/pwa/clearLocalData";

// ═══════════════════════════════════════════════════════════════════════════
// Company Auth Context - uses bw_token / bw_user
// ═══════════════════════════════════════════════════════════════════════════

const AuthContext = createContext(null);

// PWA-01 D1: only a refused session ends it — 401 from any call, or 403 from /auth/me.
// A network error or a 5xx (offline, server down) keeps the token; the user is shown
// from the bw_user stored at login and the offline bar explains why nothing loads.
export function sessionRejected(err) {
  const status = err?.response?.status;
  if (status === 401) return true;
  return status === 403 && /\/auth\/me$/.test(err?.config?.url || "");
}

function storedUser() {
  try {
    const u = JSON.parse(localStorage.getItem("bw_user") || "null");
    return u && typeof u === "object" ? u : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [org, setOrg] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    const token = localStorage.getItem("bw_token");
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const [meRes, orgRes] = await Promise.all([
        API.get("/auth/me"),
        API.get("/organization"),
      ]);
      await noteActiveTenant(orgRes.data?.id);
      setUser(meRes.data);
      setOrg(orgRes.data);
    } catch (err) {
      if (sessionRejected(err)) {
        localStorage.removeItem("bw_token");
        localStorage.removeItem("bw_user");
        setUser(null);
        setOrg(null);
      } else {
        // Nothing from /api is cached: the user comes from bw_user, org stays unknown.
        setUser(storedUser());
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (email, password) => {
    const res = await API.post("/auth/login", { email, password });
    localStorage.setItem("bw_token", res.data.token);
    localStorage.setItem("bw_user", JSON.stringify(res.data.user));
    setUser(res.data.user);
    const orgRes = await API.get("/organization");
    // PWA-01: another tenant than the one this device held → clear that tenant's data.
    await noteActiveTenant(orgRes.data?.id);
    setOrg(orgRes.data);
    return res.data;
  };

  const logout = async () => {
    localStorage.removeItem("bw_token");
    localStorage.removeItem("bw_user");
    // PWA-01: no tenant data stays on the device after logout (storage + caches).
    await clearTenantLocalData();
    setUser(null);
    setOrg(null);
  };

  const refreshOrg = async () => {
    const orgRes = await API.get("/organization");
    setOrg(orgRes.data);
  };

  return (
    <AuthContext.Provider value={{ user, org, loading, login, logout, refreshOrg }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};


// ═══════════════════════════════════════════════════════════════════════════
// Platform Auth Context - uses bw_platform_token / bw_platform_user
// Completely separate from company auth
// ═══════════════════════════════════════════════════════════════════════════

const PlatformAuthContext = createContext(null);

export function PlatformAuthProvider({ children }) {
  const [platformUser, setPlatformUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchPlatformUser = useCallback(async () => {
    const token = localStorage.getItem("bw_platform_token");
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      // Use platform token for API calls
      const res = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error("Invalid token");
      const user = await res.json();
      
      // Verify this is actually a platform admin
      if (!user.is_platform_admin) {
        throw new Error("Not a platform admin");
      }
      setPlatformUser(user);
    } catch {
      localStorage.removeItem("bw_platform_token");
      localStorage.removeItem("bw_platform_user");
      setPlatformUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPlatformUser();
  }, [fetchPlatformUser]);

  const platformLogin = async (email, password) => {
    const res = await API.post("/auth/login", { email, password });
    const { token, user } = res.data;
    
    // Verify platform admin
    if (!user.is_platform_admin) {
      throw new Error("NOT_PLATFORM_ADMIN");
    }
    
    // Store in SEPARATE keys
    localStorage.setItem("bw_platform_token", token);
    localStorage.setItem("bw_platform_user", JSON.stringify(user));
    setPlatformUser(user);
    return res.data;
  };

  const platformLogout = () => {
    localStorage.removeItem("bw_platform_token");
    localStorage.removeItem("bw_platform_user");
    setPlatformUser(null);
  };

  return (
    <PlatformAuthContext.Provider value={{ 
      platformUser, 
      loading, 
      platformLogin, 
      platformLogout 
    }}>
      {children}
    </PlatformAuthContext.Provider>
  );
}

export const usePlatformAuth = () => {
  const ctx = useContext(PlatformAuthContext);
  if (!ctx) throw new Error("usePlatformAuth must be used within PlatformAuthProvider");
  return ctx;
};
