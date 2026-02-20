import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Blocks, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";

export default function PlatformModulesPage() {
  const { t } = useTranslation();
  const [modules, setModules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(null);

  useEffect(() => {
    fetchModules();
  }, []);

  const fetchModules = async () => {
    try {
      const res = await API.get("/feature-flags");
      setModules(res.data);
    } catch (err) {
      console.error("Failed to fetch modules:", err);
      toast.error("Failed to load modules");
    } finally {
      setLoading(false);
    }
  };

  const toggleModule = async (moduleCode, enabled) => {
    if (moduleCode === "M0") {
      toast.error("Core module cannot be disabled");
      return;
    }

    setToggling(moduleCode);
    try {
      await API.put("/feature-flags", { module_code: moduleCode, enabled });
      setModules(prev => 
        prev.map(m => m.module_code === moduleCode ? { ...m, enabled } : m)
      );
      toast.success(`Module ${moduleCode} ${enabled ? 'enabled' : 'disabled'}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to toggle module");
    } finally {
      setToggling(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-violet-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="platform-modules-page">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Blocks className="w-6 h-6 text-violet-500" />
          Module Toggles
        </h1>
        <p className="text-slate-400 mt-1">Enable or disable feature modules for the organization</p>
      </div>

      <div className="bg-slate-900/50 border border-slate-800 rounded-xl divide-y divide-slate-800">
        {modules.map((module) => (
          <div 
            key={module.module_code} 
            className="flex items-center justify-between p-4 hover:bg-slate-800/50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                module.enabled ? 'bg-violet-600/20 text-violet-400' : 'bg-slate-800 text-slate-500'
              }`}>
                <span className="font-mono text-sm">{module.module_code}</span>
              </div>
              <div>
                <h3 className="font-medium text-white">{module.module_name}</h3>
                <p className="text-sm text-slate-400">{module.description}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {module.enabled ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
              ) : (
                <XCircle className="w-4 h-4 text-slate-500" />
              )}
              <Switch
                checked={module.enabled}
                onCheckedChange={(checked) => toggleModule(module.module_code, checked)}
                disabled={toggling === module.module_code || module.module_code === "M0"}
                className="data-[state=checked]:bg-violet-600"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
