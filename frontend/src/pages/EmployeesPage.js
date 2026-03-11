import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Users, Plus, Loader2, Search, UserPlus,
} from "lucide-react";

const PAY_TYPES = [
  { value: "Monthly", label: "Месечно" },
  { value: "Daily", label: "Дневно" },
  { value: "Hourly", label: "Почасово" },
];

function Avatar({ name, url, size = 32 }) {
  if (url) return <img src={url} alt={name} className="rounded-full object-cover" style={{ width: size, height: size }} />;
  const initials = (name || "?").split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
  return (
    <div className="rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold" style={{ width: size, height: size, fontSize: size * 0.38 }}>
      {initials}
    </div>
  );
}

export default function EmployeesPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const isAdmin = ["Admin", "Owner"].includes(user?.role);

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({
    first_name: "", last_name: "", email: "", phone: "", role: "Technician",
    password: "",
    pay_type: "Monthly", monthly_salary: 0, daily_rate: 0, hourly_rate: 0,
    working_days: 22, hours_day: 8,
  });
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const res = await API.get("/employees");
      setEmployees(res.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-calc for create form
  const updateCreatePay = (field, value) => {
    const f = { ...createForm, [field]: value };
    if (f.pay_type === "Monthly" && field !== "daily_rate" && field !== "hourly_rate") {
      const days = parseFloat(f.working_days) || 22;
      const hours = parseFloat(f.hours_day) || 8;
      const monthly = parseFloat(f.monthly_salary) || 0;
      f.daily_rate = days > 0 ? Math.round(monthly / days * 100) / 100 : 0;
      f.hourly_rate = (days > 0 && hours > 0) ? Math.round(monthly / days / hours * 100) / 100 : 0;
    } else if (f.pay_type === "Daily" && field !== "hourly_rate") {
      const hours = parseFloat(f.hours_day) || 8;
      f.hourly_rate = hours > 0 ? Math.round((parseFloat(f.daily_rate) || 0) / hours * 100) / 100 : 0;
    }
    setCreateForm(f);
  };

  const handleCreate = async () => {
    if (!createForm.first_name || !createForm.last_name || !createForm.email || !createForm.password) {
      alert("Попълнете задължителните полета (име, фамилия, имейл, парола)");
      return;
    }
    setSaving(true);
    try {
      // Create user - correct endpoint is /users
      const userRes = await API.post("/users", {
        first_name: createForm.first_name,
        last_name: createForm.last_name,
        email: createForm.email,
        password: createForm.password,
        phone: createForm.phone,
        role: createForm.role,
      });
      const newUserId = userRes.data.id;

      // Create profile - correct endpoint is /employees (not /employees/profile)
      await API.post("/employees", {
        user_id: newUserId,
        pay_type: createForm.pay_type,
        monthly_salary: parseFloat(createForm.monthly_salary) || null,
        daily_rate: parseFloat(createForm.daily_rate) || null,
        hourly_rate: parseFloat(createForm.hourly_rate) || null,
        working_days_per_month: parseFloat(createForm.working_days) || 22,
        standard_hours_per_day: parseFloat(createForm.hours_day) || 8,
        active: true,
      });

      setCreateOpen(false);
      navigate(`/employees/${newUserId}`);
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при създаване");
    } finally { setSaving(false); }
  };

  const filtered = search
    ? employees.filter(e => {
        const name = `${e.first_name || ""} ${e.last_name || ""} ${e.name || ""}`.toLowerCase();
        return name.includes(search.toLowerCase()) || e.email?.toLowerCase().includes(search.toLowerCase());
      })
    : employees;

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  return (
    <div className="p-6 max-w-[1200px]" data-testid="employees-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2"><Users className="w-6 h-6 text-primary" /> Персонал</h1>
          <p className="text-sm text-muted-foreground mt-1">{employees.length} служители</p>
        </div>
        {isAdmin && (
          <Button onClick={() => { setCreateForm({ first_name: "", last_name: "", email: "", phone: "", role: "Technician", password: "", pay_type: "Monthly", monthly_salary: 0, daily_rate: 0, hourly_rate: 0, working_days: 22, hours_day: 8 }); setCreateOpen(true); }} data-testid="new-employee-btn">
            <UserPlus className="w-4 h-4 mr-1" /> Нов служител
          </Button>
        )}
      </div>

      <div className="relative max-w-[300px] mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input placeholder="Търсене..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9 bg-card" />
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="employees-table">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs uppercase text-muted-foreground w-10"></TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Име</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Роля</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Телефон</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Тип</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground text-right">Ставка EUR</TableHead>
              <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow><TableCell colSpan={7} className="text-center py-12 text-muted-foreground"><Users className="w-10 h-10 mx-auto mb-3 opacity-30" /><p>Няма служители</p></TableCell></TableRow>
            ) : filtered.map(emp => {
              const name = `${emp.first_name || ""} ${emp.last_name || ""}`.trim() || emp.name || emp.email;
              const prof = emp.profile;
              const rate = prof?.pay_type === "Monthly" ? prof.monthly_salary : prof?.pay_type === "Daily" ? prof.daily_rate : prof?.hourly_rate;
              const rateLabel = prof?.pay_type === "Monthly" ? "/мес" : prof?.pay_type === "Daily" ? "/ден" : "/ч";
              return (
                <TableRow key={emp.id} className="cursor-pointer hover:bg-muted/30" onClick={() => navigate(`/employees/${emp.id}`)} data-testid={`employee-row-${emp.id}`}>
                  <TableCell><Avatar name={name} url={emp.avatar_url} size={28} /></TableCell>
                  <TableCell>
                    <p className="text-sm font-medium text-foreground">{name}</p>
                    <p className="text-xs text-muted-foreground">{emp.email}</p>
                  </TableCell>
                  <TableCell><Badge variant="outline" className="text-[10px]">{emp.role}</Badge></TableCell>
                  <TableCell className="text-sm text-muted-foreground">{emp.phone || "—"}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{prof ? PAY_TYPES.find(p => p.value === prof.pay_type)?.label || prof.pay_type : "—"}</TableCell>
                  <TableCell className="text-right font-mono text-sm">{rate ? `${rate} EUR${rateLabel}` : "—"}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-[10px] ${prof?.active !== false ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}>
                      {prof?.active !== false ? "Активен" : "Неактивен"}
                    </Badge>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Create Employee Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-[600px] bg-card border-border max-h-[85vh] overflow-y-auto" data-testid="create-employee-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><UserPlus className="w-5 h-5 text-primary" /> Нов служител</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Име *</Label><Input value={createForm.first_name} onChange={e => setCreateForm({...createForm, first_name: e.target.value})} className="bg-background" data-testid="create-first-name" /></div>
              <div className="space-y-1"><Label className="text-xs">Фамилия *</Label><Input value={createForm.last_name} onChange={e => setCreateForm({...createForm, last_name: e.target.value})} className="bg-background" data-testid="create-last-name" /></div>
              <div className="space-y-1"><Label className="text-xs">Имейл *</Label><Input type="email" value={createForm.email} onChange={e => setCreateForm({...createForm, email: e.target.value})} className="bg-background" data-testid="create-email" /></div>
              <div className="space-y-1"><Label className="text-xs">Парола *</Label><Input type="password" value={createForm.password} onChange={e => setCreateForm({...createForm, password: e.target.value})} className="bg-background" data-testid="create-password" /></div>
              <div className="space-y-1"><Label className="text-xs">Телефон</Label><Input value={createForm.phone} onChange={e => setCreateForm({...createForm, phone: e.target.value})} placeholder="+359..." className="bg-background" /></div>
              <div className="space-y-1">
                <Label className="text-xs">Роля</Label>
                <Select value={createForm.role} onValueChange={v => setCreateForm({...createForm, role: v})}>
                  <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Technician">Техник</SelectItem>
                    <SelectItem value="SiteManager">Ръководител обект</SelectItem>
                    <SelectItem value="Driver">Шофьор</SelectItem>
                    <SelectItem value="Warehousekeeper">Складов</SelectItem>
                    <SelectItem value="Accountant">Счетоводител</SelectItem>
                    <SelectItem value="Viewer">Наблюдател</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="border-t border-border pt-3">
              <Label className="text-xs text-muted-foreground mb-2 block">Заплащане (EUR)</Label>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Тип</Label>
                  <Select value={createForm.pay_type} onValueChange={v => updateCreatePay("pay_type", v)}>
                    <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                    <SelectContent>{PAY_TYPES.map(pt => <SelectItem key={pt.value} value={pt.value}>{pt.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Месечна (EUR)</Label>
                  <Input type="number" step="0.01" value={createForm.monthly_salary} onChange={e => updateCreatePay("monthly_salary", parseFloat(e.target.value) || 0)} disabled={createForm.pay_type !== "Monthly"} className="bg-background font-mono" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Дневна (EUR)</Label>
                  <Input type="number" step="0.01" value={createForm.daily_rate} onChange={e => updateCreatePay("daily_rate", parseFloat(e.target.value) || 0)} disabled={createForm.pay_type === "Monthly"} className={`bg-background font-mono ${createForm.pay_type === "Monthly" ? "text-emerald-400" : ""}`} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Часова (EUR)</Label>
                  <Input type="number" step="0.01" value={createForm.hourly_rate} onChange={e => updateCreatePay("hourly_rate", parseFloat(e.target.value) || 0)} disabled={createForm.pay_type !== "Hourly"} className={`bg-background font-mono ${createForm.pay_type !== "Hourly" ? "text-emerald-400" : ""}`} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Дни/мес</Label>
                  <Input type="number" value={createForm.working_days} onChange={e => updateCreatePay("working_days", parseFloat(e.target.value) || 22)} className="bg-background font-mono" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Часове/ден</Label>
                  <Input type="number" value={createForm.hours_day} onChange={e => updateCreatePay("hours_day", parseFloat(e.target.value) || 8)} className="bg-background font-mono" />
                </div>
              </div>
              {createForm.pay_type === "Monthly" && createForm.monthly_salary > 0 && (
                <p className="text-xs text-muted-foreground mt-2">
                  {createForm.monthly_salary} EUR / {createForm.working_days} = <span className="text-emerald-400 font-mono">{createForm.daily_rate} EUR/ден</span>
                  {" → "}<span className="text-emerald-400 font-mono">{createForm.hourly_rate} EUR/ч</span>
                </p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Затвори</Button>
            <Button onClick={handleCreate} disabled={saving} data-testid="confirm-create-btn">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <UserPlus className="w-4 h-4 mr-1" />}
              Създай служител
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
