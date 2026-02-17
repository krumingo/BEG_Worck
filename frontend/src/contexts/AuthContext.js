import { createContext, useContext, useState, useEffect, useCallback } from "react";
import API from "@/lib/api";

const AuthContext = createContext(null);

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
      setUser(meRes.data);
      setOrg(orgRes.data);
    } catch {
      localStorage.removeItem("bw_token");
      localStorage.removeItem("bw_user");
      setUser(null);
      setOrg(null);
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
    setOrg(orgRes.data);
    return res.data;
  };

  const logout = () => {
    localStorage.removeItem("bw_token");
    localStorage.removeItem("bw_user");
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
