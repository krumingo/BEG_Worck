import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import "@/i18n";
import App from "@/App";
import { initPwa } from "@/lib/pwa";
import { initAnalytics } from "@/lib/analytics";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// PWA-01: install prompt capture, online/offline state, service worker (production only).
initPwa();

// R68: anonymous page views and errors only; nothing loads without REACT_APP_POSTHOG_KEY.
initAnalytics();
