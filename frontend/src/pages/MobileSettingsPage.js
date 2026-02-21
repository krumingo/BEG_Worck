import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  Smartphone, 
  Loader2, 
  Save, 
  RotateCcw,
  CheckCircle2,
  Eye,
  List,
  Settings2,
  Filter
} from "lucide-react";
import { toast } from "sonner";

export default function MobileSettingsPage() {
  const { t } = useTranslation();
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState(null);
  const [viewConfigs, setViewConfigs] = useState([]);
  const [selectedRole, setSelectedRole] = useState("");
  const [selectedModule, setSelectedModule] = useState("");
  const [editingConfig, setEditingConfig] = useState(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [settingsRes, configsRes] = await Promise.all([
        api.get("/mobile/settings"),
        api.get("/mobile/view-configs"),
      ]);
      setSettings(settingsRes.data);
      setViewConfigs(configsRes.data);
    } catch (err) {
      toast.error(t("toast.errorOccurred"));
    } finally {
      setLoading(false);
    }
  };

  const handleModuleToggle = async (moduleCode, enabled) => {
    const newModules = enabled
      ? [...settings.enabled_modules, moduleCode]
      : settings.enabled_modules.filter(m => m !== moduleCode);
    
    setSaving(true);
    try {
      await api.put("/mobile/settings", { enabled_modules: newModules });
      setSettings({ ...settings, enabled_modules: newModules });
      toast.success(t("mobile.configSaved"));
    } catch (err) {
      toast.error(t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  const handleSelectConfig = (role, module) => {
    setSelectedRole(role);
    setSelectedModule(module);
    const config = viewConfigs.find(c => c.role === role && c.module_code === module);
    setEditingConfig(config ? { ...config } : null);
  };

  const handleFieldToggle = (fieldType, field, enabled) => {
    if (!editingConfig) return;
    const fieldKey = fieldType === "list" ? "list_fields" : "detail_fields";
    const newFields = enabled
      ? [...editingConfig[fieldKey], field]
      : editingConfig[fieldKey].filter(f => f !== field);
    setEditingConfig({ ...editingConfig, [fieldKey]: newFields });
  };

  const handleActionToggle = (action, enabled) => {
    if (!editingConfig) return;
    const newActions = enabled
      ? [...editingConfig.allowed_actions, action]
      : editingConfig.allowed_actions.filter(a => a !== action);
    setEditingConfig({ ...editingConfig, allowed_actions: newActions });
  };

  const handleSaveConfig = async () => {
    if (!editingConfig) return;
    
    setSaving(true);
    try {
      await api.put("/mobile/view-configs", {
        role: selectedRole,
        module_code: selectedModule,
        list_fields: editingConfig.list_fields,
        detail_fields: editingConfig.detail_fields,
        allowed_actions: editingConfig.allowed_actions,
        default_filters: editingConfig.default_filters || {},
      });
      
      // Refresh configs
      const configsRes = await api.get("/mobile/view-configs");
      setViewConfigs(configsRes.data);
      toast.success(t("mobile.configSaved"));
    } catch (err) {
      toast.error(err.response?.data?.detail || t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  const handleResetConfig = async () => {
    if (!selectedRole || !selectedModule) return;
    
    setSaving(true);
    try {
      const res = await api.delete(`/mobile/view-configs/${selectedRole}/${selectedModule}`);
      setEditingConfig(res.data);
      
      // Refresh configs
      const configsRes = await api.get("/mobile/view-configs");
      setViewConfigs(configsRes.data);
      toast.success(t("mobile.configReset"));
    } catch (err) {
      toast.error(t("toast.errorOccurred"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="p-6 flex items-center justify-center min-h-[400px]">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
        </div>
      </DashboardLayout>
    );
  }

  const availableModules = settings?.availableModules || [];
  const availableFields = settings?.availableFields || {};
  const availableActions = settings?.availableActions || {};
  const roles = ["Admin", "Owner", "SiteManager", "Technician", "Driver", "Accountant", "Worker"];

  return (
    <DashboardLayout>
      <div className="p-6" data-testid="mobile-settings-page">
        <div className="mb-6">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Smartphone className="w-6 h-6" />
            {t("mobile.title")}
          </h1>
          <p className="text-muted-foreground">{t("mobile.subtitle")}</p>
        </div>

        <Tabs defaultValue="modules" className="space-y-6">
          <TabsList>
            <TabsTrigger value="modules" data-testid="tab-modules">
              <CheckCircle2 className="w-4 h-4 mr-2" />
              {t("mobile.enabledModules")}
            </TabsTrigger>
            <TabsTrigger value="configs" data-testid="tab-configs">
              <Settings2 className="w-4 h-4 mr-2" />
              {t("mobile.viewConfigs")}
            </TabsTrigger>
          </TabsList>

          {/* Enabled Modules Tab */}
          <TabsContent value="modules">
            <Card>
              <CardHeader>
                <CardTitle>{t("mobile.enabledModules")}</CardTitle>
                <CardDescription>{t("mobile.enabledModulesDesc")}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {availableModules.map((module) => (
                    <div
                      key={module}
                      className="flex items-center space-x-3 p-3 rounded-lg border"
                      data-testid={`module-toggle-${module}`}
                    >
                      <Checkbox
                        id={`module-${module}`}
                        checked={settings?.enabled_modules?.includes(module)}
                        onCheckedChange={(checked) => handleModuleToggle(module, checked)}
                        disabled={saving}
                      />
                      <Label htmlFor={`module-${module}`} className="cursor-pointer">
                        {t(`mobile.modules.${module}`)}
                      </Label>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* View Configs Tab */}
          <TabsContent value="configs">
            <div className="grid lg:grid-cols-3 gap-6">
              {/* Role/Module Selector */}
              <Card className="lg:col-span-1">
                <CardHeader>
                  <CardTitle className="text-lg">{t("mobile.selectRole")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Select value={selectedRole} onValueChange={(v) => { setSelectedRole(v); setSelectedModule(""); setEditingConfig(null); }}>
                    <SelectTrigger data-testid="role-select">
                      <SelectValue placeholder={t("mobile.selectRole")} />
                    </SelectTrigger>
                    <SelectContent>
                      {roles.map((role) => (
                        <SelectItem key={role} value={role}>{role}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {selectedRole && (
                    <>
                      <Separator />
                      <p className="text-sm font-medium">{t("mobile.selectModule")}</p>
                      <div className="space-y-2">
                        {availableModules.map((module) => {
                          const config = viewConfigs.find(c => c.role === selectedRole && c.module_code === module);
                          const isSelected = selectedModule === module;
                          
                          return (
                            <button
                              key={module}
                              onClick={() => handleSelectConfig(selectedRole, module)}
                              className={`w-full flex items-center justify-between p-2 rounded-lg text-left text-sm ${
                                isSelected ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                              }`}
                              data-testid={`module-select-${module}`}
                            >
                              <span>{t(`mobile.modules.${module}`)}</span>
                              {config?.is_custom && (
                                <Badge variant="secondary" className="text-xs">{t("mobile.isCustom")}</Badge>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>

              {/* Config Editor */}
              <Card className="lg:col-span-2">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="text-lg">
                        {selectedRole && selectedModule 
                          ? `${selectedRole} - ${t(`mobile.modules.${selectedModule}`)}`
                          : t("mobile.viewConfigs")
                        }
                      </CardTitle>
                      <CardDescription>{t("mobile.viewConfigsDesc")}</CardDescription>
                    </div>
                    {editingConfig && (
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={handleResetConfig} disabled={saving}>
                          <RotateCcw className="w-4 h-4 mr-1" />
                          {t("mobile.resetToDefault")}
                        </Button>
                        <Button size="sm" onClick={handleSaveConfig} disabled={saving}>
                          {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
                          {t("mobile.saveChanges")}
                        </Button>
                      </div>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  {!editingConfig ? (
                    <p className="text-muted-foreground text-center py-8">{t("mobile.noConfigsYet")}</p>
                  ) : (
                    <div className="space-y-6">
                      {/* List Fields */}
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <List className="w-4 h-4" />
                          <h4 className="font-medium">{t("mobile.listFields")}</h4>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {(availableFields[selectedModule]?.list || []).map((field) => (
                            <Badge
                              key={field}
                              variant={editingConfig.list_fields.includes(field) ? "default" : "outline"}
                              className="cursor-pointer"
                              onClick={() => handleFieldToggle("list", field, !editingConfig.list_fields.includes(field))}
                            >
                              {field}
                            </Badge>
                          ))}
                        </div>
                      </div>

                      <Separator />

                      {/* Detail Fields */}
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <Eye className="w-4 h-4" />
                          <h4 className="font-medium">{t("mobile.detailFields")}</h4>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {(availableFields[selectedModule]?.detail || []).map((field) => (
                            <Badge
                              key={field}
                              variant={editingConfig.detail_fields.includes(field) ? "default" : "outline"}
                              className="cursor-pointer"
                              onClick={() => handleFieldToggle("detail", field, !editingConfig.detail_fields.includes(field))}
                            >
                              {field}
                            </Badge>
                          ))}
                        </div>
                      </div>

                      <Separator />

                      {/* Allowed Actions */}
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <Settings2 className="w-4 h-4" />
                          <h4 className="font-medium">{t("mobile.allowedActions")}</h4>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {(availableActions[selectedModule] || []).map((action) => (
                            <Badge
                              key={action}
                              variant={editingConfig.allowed_actions.includes(action) ? "default" : "outline"}
                              className="cursor-pointer"
                              onClick={() => handleActionToggle(action, !editingConfig.allowed_actions.includes(action))}
                            >
                              {t(`mobile.actions.${action}`) || action}
                            </Badge>
                          ))}
                        </div>
                      </div>

                      <Separator />

                      {/* Default Filters */}
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <Filter className="w-4 h-4" />
                          <h4 className="font-medium">{t("mobile.defaultFilters")}</h4>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(editingConfig.default_filters || {}).map(([key, value]) => (
                            <Badge key={key} variant="secondary">
                              {t(`mobile.filters.${key}`) || key}: {String(value)}
                            </Badge>
                          ))}
                          {Object.keys(editingConfig.default_filters || {}).length === 0 && (
                            <span className="text-sm text-muted-foreground">{t("common.none")}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </DashboardLayout>
  );
}
