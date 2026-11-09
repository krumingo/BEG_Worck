import axios from "axios";
import { markNetworkFailure, markNetworkOk, isNetworkError } from "@/lib/pwa/connectivity";
import { clearTenantLocalData } from "@/lib/pwa/clearLocalData";

const API = axios.create({
  baseURL: `${process.env.REACT_APP_BACKEND_URL}/api`,
  headers: { "Content-Type": "application/json" },
});

API.interceptors.request.use((config) => {
  const token = localStorage.getItem("bw_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

API.interceptors.response.use(
  (res) => {
    markNetworkOk();
    return res;
  },
  (err) => {
    // PWA-01: a request that never reached the server shows the "Без връзка" bar.
    if (isNetworkError(err)) markNetworkFailure();
    else if (err.response) markNetworkOk();
    if (err.response?.status === 401) {
      localStorage.removeItem("bw_token");
      localStorage.removeItem("bw_user");
      // PWA-01: an ended session is a logout — clear tenant data before leaving.
      clearTenantLocalData().finally(() => {
        window.location.href = "/login";
      });
    }
    return Promise.reject(err);
  }
);

export default API;
