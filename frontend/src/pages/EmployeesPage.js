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
  Users, Plus, Loader2, Search, UserPlus, Camera,
} from "lucide-react";
import ImageCropDialog from "@/components/ImageCropDialog";
import { toast } from "sonner";

const PAY_TYPES = [
  { value: "Monthly", label: "Месечно" },
  { value: "Daily", label: "Надница" },
  { value: "Hourly", label: "Часово" },
  { value: "Akord", label: "Акорд" },
];

function Avatar({ name, url, size = 32 }) {
  const fullUrl = url ? (url.startsWith("http") ? url : `${process.env.REACT_APP_BACKEND_URL}${url}`) : null;
  const [imgErr, setImgErr] = useState(false);
  const initials = (name || "?").split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
  if (fullUrl && !imgErr) {
    return <img src={fullUrl} alt={name} className="rounded-full object-cover" style={{ width: size, height: size }} onError={() => setImgErr(true)} />;
  }
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
    password: "", position: "",
    pay_type: "Monthly", monthly_salary: 0, daily_rate: 0, hourly_rate: 0,
    working_days: 22, hours_day: 8, akord_note: "",
  });
  const [saving, setSaving] = useState(false);
  const [avatarFile, setAvatarFile] = useState(null); // File object for upload
  const [avatarPreview, setAvatarPreview] = useState(null); // data URL preview
  const [cropSrc, setCropSrc] = useState(null); // for ImageCropDialog

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
      toast.error("Попълнете задължителните полета (име, фамилия, имейл, парола)");
      return;
    }
    setSaving(true);
    try {
      // 1. Create user
      const userRes = await API.post("/users", {
        first_name: createForm.first_name,
        last_name: createForm.last_name,
        email: createForm.email,
        password: createForm.password,
        phone: createForm.phone,
        role: createForm.role,
      });
      const newUserId = userRes.data.id;

      // 2. Create employee profile
      await API.post("/employees", {
        user_id: newUserId,
        pay_type: createForm.pay_type,
        position: createForm.position || null,
        monthly_salary: parseFloat(createForm.monthly_salary) || null,
        daily_rate: parseFloat(createForm.daily_rate) || null,
        hourly_rate: parseFloat(createForm.hourly_rate) || null,
        akord_note: createForm.akord_note || null,
        working_days_per_month: parseFloat(createForm.working_days) || 22,
        standard_hours_per_day: parseFloat(createForm.hours_day) || 8,
        active: true,
      });

      // 3. Upload avatar if selected
      if (avatarFile) {
        try {
          const fd = new FormData();
          fd.append("file", avatarFile);
          fd.append("context_type", "avatar");
          fd.append("context_id", newUserId);
          const uploadRes = await API.post("/media/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
          const url = uploadRes.data.url || uploadRes.data.file_url;
          if (url) {
            await API.put(`/users/${newUserId}`, { avatar_url: url });
          }
        } catch { /* avatar upload is optional */ }
      }

      setCreateOpen(false);
      setAvatarFile(null);
      setAvatarPreview(null);
      toast.success("Служителят е създаден");
      navigate(`/employees/${newUserId}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка при създаване");
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
          <Button onClick={() => { setCreateForm({ first_name: "", last_name: "", email: "", phone: "", role: "Technician", password: "", position: "", pay_type: "Monthly", monthly_salary: 0, daily_rate: 0, hourly_rate: 0, working_days: 22, hours_day: 8, akord_note: "" }); setCreateOpen(true); }} data-testid="new-employee-btn">
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
            {/* Photo + Basic info */}
            <div className="flex gap-4">
              {/* Avatar */}
              <div className="flex-shrink-0">
                <div className="relative w-20 h-20">
                  {avatarPreview ? (
                    <img src={avatarPreview} alt="" className="w-20 h-20 rounded-full object-cover border-2 border-primary/30" />
                  ) : (
                    <div className="w-20 h-20 rounded-full bg-primary/20 text-primary flex items-center justify-center text-xl font-bold">
                      {((createForm.first_name?.[0] || "") + (createForm.last_name?.[0] || "")).toUpperCase() || "?"}
                    </div>
                  )}
                  <label className="absolute bottom-0 right-0 w-7 h-7 rounded-full bg-primary text-primary-foreground flex items-center justify-center cursor-pointer hover:bg-primary/90">
                    <Camera className="w-3.5 h-3.5" />
                    <input type="file" accept="image/*" className="hidden" onChange={e => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = () => setCropSrc(reader.result);
                      reader.readAsDataURL(file);
                      e.target.value = "";
                    }} />
                  </label>
                </div>
              </div>
              <div className="flex-1 grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label className="text-xs">Име *</Label><Input value={createForm.first_name} onChange={e => setCreateForm({...createForm, first_name: e.target.value})} className="bg-background" data-testid="create-first-name" /></div>
                <div className="space-y-1"><Label className="text-xs">Фамилия *</Label><Input value={createForm.last_name} onChange={e => setCreateForm({...createForm, last_name: e.target.value})} className="bg-background" data-testid="create-last-name" /></div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
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
              <div className="space-y-1"><Label className="text-xs">Длъжност</Label><Input value={createForm.position} onChange={e => setCreateForm({...createForm, position: e.target.value})} placeholder="Бояджия, Майстор..." className="bg-background" data-testid="create-position" /></div>
            </div>

            {/* Pay section */}
            <div className="border-t border-border pt-3">
              <Label className="text-xs text-muted-foreground mb-2 block">Заплащане (EUR)</Label>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Тип заплащане</Label>
                  <Select value={createForm.pay_type} onValueChange={v => updateCreatePay("pay_type", v)}>
                    <SelectTrigger className="bg-background"><SelectValue /></SelectTrigger>
                    <SelectContent>{PAY_TYPES.map(pt => <SelectItem key={pt.value} value={pt.value}>{pt.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                {createForm.pay_type === "Monthly" && (
                  <div className="space-y-1">
                    <Label className="text-xs">Месечна заплата</Label>
                    <Input type="number" step="0.01" value={createForm.monthly_salary} onChange={e => updateCreatePay("monthly_salary", parseFloat(e.target.value) || 0)} className="bg-background font-mono" />
                  </div>
                )}
                {createForm.pay_type === "Daily" && (
                  <div className="space-y-1">
                    <Label className="text-xs">Дневна ставка</Label>
                    <Input type="number" step="0.01" value={createForm.daily_rate} onChange={e => updateCreatePay("daily_rate", parseFloat(e.target.value) || 0)} className="bg-background font-mono" />
                  </div>
                )}
                {(createForm.pay_type === "Hourly" || createForm.pay_type === "Akord") && (
                  <div className="space-y-1">
                    <Label className="text-xs">Часова ставка</Label>
                    <Input type="number" step="0.01" value={createForm.hourly_rate} onChange={e => updateCreatePay("hourly_rate", parseFloat(e.target.value) || 0)} className="bg-background font-mono" />
                  </div>
                )}
                <div className="space-y-1">
                  <Label className="text-xs">Дни/мес</Label>
                  <Input type="number" value={createForm.working_days} onChange={e => updateCreatePay("working_days", parseFloat(e.target.value) || 22)} className="bg-background font-mono" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Часове/ден</Label>
                  <Input type="number" value={createForm.hours_day} onChange={e => updateCreatePay("hours_day", parseFloat(e.target.value) || 8)} className="bg-background font-mono" />
                </div>
              </div>
              {/* Auto-calc preview */}
              {createForm.pay_type === "Monthly" && createForm.monthly_salary > 0 && (
                <p className="text-xs text-muted-foreground mt-2">
                  {createForm.monthly_salary} EUR / {createForm.working_days}д = <span className="text-emerald-400 font-mono">{createForm.daily_rate} EUR/ден</span>
                  {" → "}<span className="text-emerald-400 font-mono">{createForm.hourly_rate} EUR/ч</span>
                </p>
              )}
              {createForm.pay_type === "Daily" && createForm.daily_rate > 0 && (
                <p className="text-xs text-muted-foreground mt-2">
                  {createForm.daily_rate} EUR/ден ÷ {createForm.hours_day}ч = <span className="text-emerald-400 font-mono">{createForm.hourly_rate} EUR/ч</span>
                </p>
              )}
            </div>
          </div>

          {/* Image Crop Dialog */}
          {cropSrc && (
            <ImageCropDialog
              open={!!cropSrc}
              onOpenChange={() => setCropSrc(null)}
              imageSrc={cropSrc}
              onCropComplete={(blob) => {
                const file = new File([blob], "avatar.jpg", { type: "image/jpeg" });
                setAvatarFile(file);
                setAvatarPreview(URL.createObjectURL(blob));
                setCropSrc(null);
              }}
            />
          )}
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
