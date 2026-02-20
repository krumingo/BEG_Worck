import { useState, useEffect } from "react";
import API from "@/lib/api";
import { Smartphone, Loader2 } from "lucide-react";

export default function PlatformMobileSettingsPage() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      const res = await API.get("/mobile/settings");
      setSettings(res.data);
    } catch (err) {
      console.error("Failed to fetch mobile settings:", err);
      setError(err.response?.data?.detail || "Failed to load mobile settings");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-violet-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-6 text-red-400">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="platform-mobile-settings-page">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Smartphone className="w-6 h-6 text-violet-500" />
          Mobile App Settings
        </h1>
        <p className="text-slate-400 mt-1">Configure mobile application behavior</p>
      </div>

      {/* Available Modules */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Available Mobile Modules</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {settings.availableModules?.map((module) => (
            <div key={module} className="p-3 bg-slate-800/50 rounded-lg">
              <span className="text-sm text-slate-300">{module}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Current Settings */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Current Configuration</h2>
        <pre className="bg-slate-800 rounded-lg p-4 text-sm text-slate-300 overflow-x-auto">
          {JSON.stringify(settings, null, 2)}
        </pre>
      </div>
    </div>
  );
}
