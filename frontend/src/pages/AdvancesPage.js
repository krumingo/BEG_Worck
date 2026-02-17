import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Wallet,
  Plus,
  Loader2,
  Filter,
} from "lucide-react";

const ADVANCE_TYPES = ["Advance", "Loan"];

export default function AdvancesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [advances, setAdvances] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusFilter, setStatusFilter] = useState("Open");
  const [userFilter, setUserFilter] = useState("");

  // Form state
  const [formUserId, setFormUserId] = useState("");
  const [formType, setFormType] = useState("Advance");
  const [formAmount, setFormAmount] = useState("");
  const [formDate, setFormDate] = useState(new Date().toISOString().slice(0, 10));
  const [formNote, setFormNote] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [advRes, empRes] = await Promise.all([
        API.get(`/advances${statusFilter ? `?status=${statusFilter}` : ""}${userFilter ? `${statusFilter ? "&" : "?"}user_id=${userFilter}` : ""}`),
        API.get("/employees"),
      ]);
      setAdvances(advRes.data);
      setEmployees(empRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, userFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openCreate = () => {
    setFormUserId("");
    setFormType("Advance");
    setFormAmount("");
    setFormDate(new Date().toISOString().slice(0, 10));
    setFormNote("");
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formUserId || !formAmount) {
      alert(t("validation.required"));
      return;
    }
    setSaving(true);
    try {
      await API.post("/advances", {
        user_id: formUserId,
        type: formType,
        amount: parseFloat(formAmount),
        issued_date: formDate,
        note: formNote || null,
      });
      setDialogOpen(false);
      await fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(amount || 0);
  };

  return (
    <div className="p-8 max-w-[1200px]" data-testid="advances-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("advances.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("advances.subtitle")}</p>
        </div>
        <Button onClick={openCreate} data-testid="create-advance-btn">
          <Plus className="w-4 h-4 mr-2" /> {t("advances.newAdvance")}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6" data-testid="advances-filters">
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="status-filter">
            <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
            <SelectValue placeholder={t("common.allStatuses")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("common.allStatuses")}</SelectItem>
            <SelectItem value="Open">{t("advances.statusLabels.open")}</SelectItem>
            <SelectItem value="Closed">{t("advances.statusLabels.closed")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={userFilter} onValueChange={(v) => setUserFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[200px] bg-card" data-testid="user-filter">
            <SelectValue placeholder={t("employees.allEmployees")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("employees.allEmployees")}</SelectItem>
            {employees.map((e) => (
              <SelectItem key={e.id} value={e.id}>{e.name || e.email}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="advances-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("employees.employee")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.type")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.date")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.amount")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("advances.remaining")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.status")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.note")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {advances.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    <Wallet className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>{t("advances.noAdvances")}</p>
                  </TableCell>
                </TableRow>
              ) : (
                advances.map((adv) => (
                  <TableRow key={adv.id} className="table-row-hover" data-testid={`advance-row-${adv.id}`}>
                    <TableCell className="font-medium text-foreground">{adv.user_name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${adv.type === "Loan" ? "text-blue-400 border-blue-500/30" : "text-amber-400 border-amber-500/30"}`}>
                        {t(`advances.typeLabels.${adv.type.toLowerCase()}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{adv.issued_date}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{formatCurrency(adv.amount)}</TableCell>
                    <TableCell className="text-right font-mono text-sm font-medium text-foreground">{formatCurrency(adv.remaining_amount)}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${adv.status === "Open" ? "text-emerald-400 border-emerald-500/30" : "text-gray-400 border-gray-500/30"}`}>
                        {t(`advances.statusLabels.${adv.status.toLowerCase()}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground truncate max-w-[150px]">{adv.note || "-"}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[450px] bg-card border-border" data-testid="advance-dialog">
          <DialogHeader>
            <DialogTitle>{t("advances.newAdvance")} / {t("advances.loan")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>{t("employees.employee")} *</Label>
              <Select value={formUserId} onValueChange={setFormUserId}>
                <SelectTrigger className="bg-background" data-testid="form-user-select">
                  <SelectValue placeholder={t("advances.selectEmployee")} />
                </SelectTrigger>
                <SelectContent>
                  {employees.map((e) => (
                    <SelectItem key={e.id} value={e.id}>{e.name || e.email}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("common.type")}</Label>
                <Select value={formType} onValueChange={setFormType}>
                  <SelectTrigger className="bg-background" data-testid="form-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ADVANCE_TYPES.map((type) => <SelectItem key={type} value={type}>{t(`advances.typeLabels.${type.toLowerCase()}`)}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("common.amount")} (€) *</Label>
                <Input type="number" value={formAmount} onChange={(e) => setFormAmount(e.target.value)} placeholder="0.00" className="bg-background" data-testid="form-amount-input" />
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("advances.issueDate")}</Label>
              <Input type="date" value={formDate} onChange={(e) => setFormDate(e.target.value)} className="bg-background" data-testid="form-date-input" />
            </div>
            <div className="space-y-2">
              <Label>{t("common.note")}</Label>
              <Textarea value={formNote} onChange={(e) => setFormNote(e.target.value)} placeholder={t("common.optionalNote")} className="bg-background" data-testid="form-note-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleSave} disabled={saving} data-testid="form-save-btn">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              {t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
