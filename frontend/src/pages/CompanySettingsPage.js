import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Loader2, Save, Building2, Hash, FileText, AlertCircle, CheckCircle2 } from "lucide-react";

export default function CompanySettingsPage() {
  const { t } = useTranslation();
  const { org, refreshOrg, user } = useAuth();
  const [form, setForm] = useState({ name: "", email: "", phone: "", address: "", attendance_start: "06:00", attendance_end: "10:00" });
  const [sub, setSub] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  
  // Invoice numbering state
  const [invoiceSettings, setInvoiceSettings] = useState(null);
  const [invForm, setInvForm] = useState({
    issued_auto_numbering: true,
    issued_prefix: "INV",
    issued_next_number: 1,
    received_auto_numbering: false,
    received_prefix: "BILL",
    received_next_number: 1,
  });
  const [invSaving, setInvSaving] = useState(false);
  const [invSaved, setInvSaved] = useState(false);

  useEffect(() => {
    if (org) {
      setForm({
        name: org.name || "", email: org.email || "", phone: org.phone || "",
        address: org.address || "",
        attendance_start: org.attendance_start || "06:00",
        attendance_end: org.attendance_end || "10:00",
      });
    }
    API.get("/subscription").then((r) => setSub(r.data)).catch(() => {});
    
    // Load invoice settings
    API.get("/finance/invoice-settings").then((r) => {
      setInvoiceSettings(r.data);
      setInvForm({
        issued_auto_numbering: r.data.issued_auto_numbering ?? true,
        issued_prefix: r.data.issued_prefix || "INV",
        issued_next_number: r.data.issued_next_number || 1,
        received_auto_numbering: r.data.received_auto_numbering ?? false,
        received_prefix: r.data.received_prefix || "BILL",
        received_next_number: r.data.received_next_number || 1,
      });
    }).catch(() => {});
  }, [org]);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await API.put("/organization", form);
      await refreshOrg();
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveInvoiceSettings = async () => {
    setInvSaving(true);
    setInvSaved(false);
    try {
      const res = await API.put("/finance/invoice-settings", invForm);
      setInvoiceSettings(res.data);
      setInvForm({
        issued_auto_numbering: res.data.issued_auto_numbering ?? true,
        issued_prefix: res.data.issued_prefix || "INV",
        issued_next_number: res.data.issued_next_number || 1,
        received_auto_numbering: res.data.received_auto_numbering ?? false,
        received_prefix: res.data.received_prefix || "BILL",
        received_next_number: res.data.received_next_number || 1,
      });
      setInvSaved(true);
      setTimeout(() => setInvSaved(false), 2000);
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при запазване");
    } finally {
      setInvSaving(false);
    }
  };

  const isAdmin = user?.role === "Admin" || user?.role === "Owner";

  return (
    <div className="p-8 max-w-[800px]" data-testid="company-settings-page">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">{t("settings.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("settings.subtitle")}</p>
      </div>

      {/* Org Details */}
      <div className="rounded-xl border border-border bg-card p-6 mb-6" data-testid="org-form">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
            <Building2 className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">{t("settings.companyName")}</h2>
            <p className="text-xs text-muted-foreground">{t("settings.subtitle")}</p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("settings.companyName")}</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="bg-background"
                data-testid="org-name-input"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("common.email")}</Label>
              <Input
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className="bg-background"
                data-testid="org-email-input"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("users.phone")}</Label>
              <Input
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                className="bg-background"
                data-testid="org-phone-input"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-muted-foreground">{t("projects.location")}</Label>
              <Input
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
                className="bg-background"
                data-testid="org-address-input"
              />
            </div>
          </div>
          <Button onClick={handleSave} disabled={saving} data-testid="org-save-button">
            {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Save className="w-4 h-4 mr-2" />}
            {saved ? t("settings.savedSuccessfully") : t("common.saveChanges")}
          </Button>
        </div>
      </div>

      {/* Attendance Settings */}
      <div className="rounded-xl border border-border bg-card p-6 mb-6" data-testid="attendance-settings">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center">
            <Save className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">{t("settings.attendanceWindow")}</h2>
            <p className="text-xs text-muted-foreground">{t("settings.attendanceWindowHint")}</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label className="text-muted-foreground">{t("projects.start")}</Label>
            <Input
              type="time"
              value={form.attendance_start}
              onChange={(e) => setForm({ ...form, attendance_start: e.target.value })}
              className="bg-background"
              data-testid="attendance-start-input"
            />
          </div>
          <div className="space-y-2">
            <Label className="text-muted-foreground">{t("attendance.late")}</Label>
            <Input
              type="time"
              value={form.attendance_end}
              onChange={(e) => setForm({ ...form, attendance_end: e.target.value })}
              className="bg-background"
              data-testid="attendance-end-input"
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-3">{t("myDay.markedAsLate")}</p>
      </div>

      {/* Invoice Numbering Settings */}
      {isAdmin && (
        <div className="rounded-xl border border-border bg-card p-6 mb-6" data-testid="invoice-numbering-settings">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center">
              <Hash className="w-5 h-5 text-emerald-500" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">Номерация на фактури</h2>
              <p className="text-xs text-muted-foreground">Настройки за автоматично генериране на номера</p>
            </div>
          </div>

          <div className="space-y-6">
            {/* Sales Invoices */}
            <div className="space-y-4 p-4 rounded-lg bg-muted/30 border border-border">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-primary" />
                  <span className="font-medium text-sm">Продажби (Изходящи фактури)</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Автоматична номерация</span>
                  <Switch
                    checked={invForm.issued_auto_numbering}
                    onCheckedChange={(v) => setInvForm({ ...invForm, issued_auto_numbering: v })}
                    data-testid="issued-auto-switch"
                  />
                </div>
              </div>
              
              {invForm.issued_auto_numbering && (
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">Префикс</Label>
                    <Input
                      value={invForm.issued_prefix}
                      onChange={(e) => setInvForm({ ...invForm, issued_prefix: e.target.value.toUpperCase() })}
                      placeholder="INV"
                      className="bg-background font-mono"
                      data-testid="issued-prefix-input"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">Следващ номер</Label>
                    <Input
                      type="number"
                      min="1"
                      value={invForm.issued_next_number}
                      onChange={(e) => setInvForm({ ...invForm, issued_next_number: parseInt(e.target.value) || 1 })}
                      className="bg-background font-mono"
                      data-testid="issued-next-number-input"
                    />
                  </div>
                </div>
              )}
              
              {invoiceSettings?.issued_last_used && (
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                  Последен използван номер: <span className="font-mono">{invoiceSettings.issued_last_used}</span>
                </p>
              )}
            </div>

            {/* Purchase Invoices */}
            <div className="space-y-4 p-4 rounded-lg bg-muted/30 border border-border">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-amber-500" />
                  <span className="font-medium text-sm">Покупки (Входящи фактури)</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Автоматична номерация</span>
                  <Switch
                    checked={invForm.received_auto_numbering}
                    onCheckedChange={(v) => setInvForm({ ...invForm, received_auto_numbering: v })}
                    data-testid="received-auto-switch"
                  />
                </div>
              </div>
              
              {invForm.received_auto_numbering && (
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">Префикс</Label>
                    <Input
                      value={invForm.received_prefix}
                      onChange={(e) => setInvForm({ ...invForm, received_prefix: e.target.value.toUpperCase() })}
                      placeholder="BILL"
                      className="bg-background font-mono"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">Следващ номер</Label>
                    <Input
                      type="number"
                      min="1"
                      value={invForm.received_next_number}
                      onChange={(e) => setInvForm({ ...invForm, received_next_number: parseInt(e.target.value) || 1 })}
                      className="bg-background font-mono"
                    />
                  </div>
                </div>
              )}
              
              {!invForm.received_auto_numbering && (
                <p className="text-xs text-amber-400 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />
                  Входящите фактури се въвеждат ръчно по номер от доставчика
                </p>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button
                onClick={handleSaveInvoiceSettings}
                disabled={invSaving}
                className="bg-primary hover:bg-primary/90"
                data-testid="save-invoice-settings-btn"
              >
                {invSaving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Save className="w-4 h-4 mr-2" />}
                {invSaved ? "Запазено!" : "Запази настройките"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Subscription Info */}
      {sub && (
        <div className="rounded-xl border border-border bg-card p-6" data-testid="subscription-info">
          <h2 className="text-sm font-semibold text-foreground mb-4">{t("common.status")}</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-muted-foreground mb-1">{t("common.type")}</p>
              <Badge className="capitalize">{sub.plan}</Badge>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1">{t("common.status")}</p>
              <Badge variant={sub.status === "active" ? "default" : "destructive"} className="capitalize">{sub.status}</Badge>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1">{t("finance.dueDate")}</p>
              <p className="text-sm text-foreground">{new Date(sub.expires_at).toLocaleDateString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1">{t("common.currency")}</p>
              <p className="text-sm text-foreground">{sub.currency}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
