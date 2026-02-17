import { useEffect, useState, useCallback } from "react";
import API from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  Shield,
  FolderKanban,
  Calculator,
  CalendarCheck,
  Wallet,
  Receipt,
  ScanLine,
  Package,
  QrCode,
  BarChart3,
  Lock,
} from "lucide-react";

const MODULE_ICONS = {
  M0: Shield, M1: FolderKanban, M2: Calculator, M3: CalendarCheck,
  M4: Wallet, M5: Receipt, M6: ScanLine, M7: Package, M8: QrCode, M9: BarChart3,
};

export default function ModuleTogglesPage() {
  const [flags, setFlags] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState("");

  const fetchFlags = useCallback(async () => {
    try {
      const res = await API.get("/feature-flags");
      setFlags(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchFlags(); }, [fetchFlags]);

  const handleToggle = async (code, currentValue) => {
    setToggling(code);
    try {
      const res = await API.put("/feature-flags", { module_code: code, enabled: !currentValue });
      setFlags(res.data);
    } catch (err) {
      alert(err.response?.data?.detail || "Toggle failed");
    } finally {
      setToggling("");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1200px]" data-testid="modules-page">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Module Management</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Enable or disable platform modules for your organization
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="modules-grid">
        {flags
          .sort((a, b) => a.module_code.localeCompare(b.module_code))
          .map((flag, i) => {
            const Icon = MODULE_ICONS[flag.module_code] || Shield;
            const isCore = flag.module_code === "M0";

            return (
              <div
                key={flag.module_code}
                className={`module-card animate-in ${isCore ? "locked" : flag.enabled ? "enabled" : ""}`}
                style={{ animationDelay: `${i * 60}ms` }}
                data-testid={`module-card-${flag.module_code}`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      flag.enabled ? "bg-primary/20" : "bg-accent"
                    }`}>
                      <Icon className={`w-5 h-5 ${flag.enabled ? "text-primary" : "text-muted-foreground"}`} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground">{flag.module_code}</span>
                        {isCore && (
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-primary/40 text-primary">
                            <Lock className="w-2.5 h-2.5 mr-1" /> CORE
                          </Badge>
                        )}
                      </div>
                      <h3 className="text-sm font-semibold text-foreground">{flag.module_name}</h3>
                    </div>
                  </div>
                </div>

                <p className="text-xs text-muted-foreground mb-4 leading-relaxed">
                  {flag.description}
                </p>

                <div className="flex items-center justify-between">
                  <span className={`text-xs font-medium ${flag.enabled ? "text-primary" : "text-muted-foreground"}`}>
                    {flag.enabled ? "Enabled" : "Disabled"}
                  </span>
                  <Switch
                    checked={flag.enabled}
                    onCheckedChange={() => handleToggle(flag.module_code, flag.enabled)}
                    disabled={isCore || toggling === flag.module_code}
                    data-testid={`module-toggle-${flag.module_code}`}
                  />
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
}
