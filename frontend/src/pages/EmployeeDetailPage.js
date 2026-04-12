import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
  ArrowLeft, Calendar, Clock, MapPin, CreditCard, Loader2,
  ChevronLeft, ChevronRight, Save, X, Pencil, Camera,
  FileText, DollarSign, Banknote, AlertTriangle, Briefcase, Check, Eye,
} from "lucide-react";
import ImageCropDialog from "@/components/ImageCropDialog";
import PayslipDialog from "@/components/PayslipDialog";

function Avatar({ name, url, size = 48 }) {
  const fullUrl = url ? (url.startsWith("http") ? url : `${process.env.REACT_APP_BACKEND_URL}${url}`) : null;
  const [imgError, setImgError] = useState(false);
  const initials = (name || "?").split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
  
  if (fullUrl && !imgError) {
    return <img src={fullUrl} alt={name} className="rounded-full object-cover" style={{ width: size, height: size }} onError={() => setImgError(true)} />;
  }
  return (
    <div className="rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold" style={{ width: size, height: size, fontSize: size * 0.35 }}>
      {initials}
    </div>
  );
}

const STATUS_COLORS = { Present: "bg-emerald-500/20 text-emerald-400", Absent: "bg-red-500/20 text-red-400", Late: "bg-amber-500/20 text-amber-400", Leave: "bg-blue-500/20 text-blue-400", Sick: "bg-orange-500/20 text-orange-400" };
const STATUS_BG = { Present: "Присъства", Absent: "Отсъства", Late: "Закъснял", Leave: "Отпуск", Sick: "Болен" };
const DAYS_BG = ["Нд", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
const PAY_TYPES = [
  { value: "Monthly", label: "Месечно" },
  { value: "Akord", label: "Акорд (пазарлък)" },
];

export default function EmployeeDetailPage() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const canEdit = ["Admin", "Owner"].includes(user?.role);
  const defaultTab = searchParams.get("tab") || "calendar";

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [calMonth, setCalMonth] = useState(new Date().toISOString().slice(0, 7));
  const [calendar, setCalendar] = useState(null);

  // Dossier data (reports, payroll batches, advances, dossier calendar)
  const [dossier, setDossier] = useState(null);
  const [payslipOpen, setPayslipOpen] = useState(null); // {batchId, workerId}

  // Edit mode
  const [editMode, setEditMode] = useState(false);
  const [editBasic, setEditBasic] = useState({});
  const [editProfile, setEditProfile] = useState({});
  const [saving, setSaving] = useState(false);
  // Crop state
  const [cropOpen, setCropOpen] = useState(false);
  const [cropSrc, setCropSrc] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await API.get(`/employees/${userId}/dashboard`);
      setData(res.data);
      const e = res.data.employee || {};
      const p = res.data.profile || {};
      setEditBasic({ first_name: e.first_name || "", last_name: e.last_name || "", email: e.email || "", phone: e.phone || "", role: e.role || "" });
      setEditProfile({
        pay_type: p.pay_type || "Monthly",
        position: p.position || "",
        monthly_salary: p.monthly_salary || 0,
        daily_rate: p.daily_rate || 0,
        hourly_rate: p.hourly_rate || 0,
        akord_note: p.akord_note || "",
        working_days_per_month: p.working_days_per_month || 22,
        standard_hours_per_day: p.standard_hours_per_day || 8,
        active: p.active !== false,
      });
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [userId]);

  const fetchCalendar = useCallback(async () => {
    try {
      const res = await API.get(`/employees/${userId}/calendar?month=${calMonth}`);
      setCalendar(res.data);
    } catch (err) { console.error(err); }
  }, [userId, calMonth]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { fetchCalendar(); }, [fetchCalendar]);

  // Load dossier data (reports, payroll batches, advances)
  useEffect(() => {
    API.get(`/employee-dossier/${userId}`)
      .then(r => setDossier(r.data))
      .catch(() => {});
  }, [userId]);

  // Auto-calculation
  const updatePayField = (field, value) => {
    const p = { ...editProfile, [field]: value };
    if (p.pay_type === "Monthly" && field !== "daily_rate" && field !== "hourly_rate") {
      const days = parseFloat(p.working_days_per_month) || 22;
      const hours = parseFloat(p.standard_hours_per_day) || 8;
      const monthly = parseFloat(p.monthly_salary) || 0;
      p.daily_rate = days > 0 ? Math.round(monthly / days * 100) / 100 : 0;
      p.hourly_rate = (days > 0 && hours > 0) ? Math.round(monthly / days / hours * 100) / 100 : 0;
    } else if (p.pay_type === "Daily" && field !== "hourly_rate") {
      const hours = parseFloat(p.standard_hours_per_day) || 8;
      const daily = parseFloat(p.daily_rate) || 0;
      p.hourly_rate = hours > 0 ? Math.round(daily / hours * 100) / 100 : 0;
    }
    setEditProfile(p);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await API.put(`/employees/${userId}/basic`, editBasic);
      // Update profile via PUT
      await API.put(`/employees/${userId}`, {
        pay_type: editProfile.pay_type,
        position: editProfile.position || null,
        monthly_salary: parseFloat(editProfile.monthly_salary) || null,
        daily_rate: parseFloat(editProfile.daily_rate) || null,
        hourly_rate: parseFloat(editProfile.hourly_rate) || null,
        akord_note: editProfile.akord_note || null,
        working_days_per_month: parseFloat(editProfile.working_days_per_month) || 22,
        standard_hours_per_day: parseFloat(editProfile.standard_hours_per_day) || 8,
        active: editProfile.active,
      });
      setEditMode(false);
      setLoading(true);
      fetchData();
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при запис");
    } finally { setSaving(false); }
  };

  const handleCancel = () => {
    setEditMode(false);
    if (data) {
      const e = data.employee || {};
      const p = data.profile || {};
      setEditBasic({ first_name: e.first_name || "", last_name: e.last_name || "", email: e.email || "", phone: e.phone || "", role: e.role || "" });
      setEditProfile({
        pay_type: p.pay_type || "Monthly", monthly_salary: p.monthly_salary || 0,
        daily_rate: p.daily_rate || 0, hourly_rate: p.hourly_rate || 0,
        working_days_per_month: p.working_days_per_month || 22,
        standard_hours_per_day: p.standard_hours_per_day || 8, active: p.active !== false,
      });
    }
  };

  // Calendar
  const prevMonth = () => { const [y, m] = calMonth.split("-").map(Number); setCalMonth(m === 1 ? `${y-1}-12` : `${y}-${String(m-1).padStart(2, "0")}`); };
  const nextMonth = () => { const [y, m] = calMonth.split("-").map(Number); setCalMonth(m === 12 ? `${y+1}-01` : `${y}-${String(m+1).padStart(2, "0")}`); };

  const buildCalGrid = () => {
    if (!calendar) return [];
    const [y, m] = calMonth.split("-").map(Number);
    const firstDay = new Date(y, m - 1, 1).getDay();
    const daysInMonth = new Date(y, m, 0).getDate();
    const dayMap = {};
    (calendar.days || []).forEach(d => { dayMap[d.date] = d; });
    const grid = [];
    let week = new Array(firstDay).fill(null);
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      week.push({ day: d, date: dateStr, data: dayMap[dateStr] || null });
      if (week.length === 7) { grid.push(week); week = []; }
    }
    if (week.length > 0) { while (week.length < 7) week.push(null); grid.push(week); }
    return grid;
  };

  if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  if (!data) return <div className="p-6 text-muted-foreground">Служителят не е намерен</div>;

  const { employee: emp, profile: prof, attendance, project_history, hours_summary, payslips } = data;
  const calGrid = buildCalGrid();
  const displayDailyRate = prof?.daily_rate || (prof?.monthly_salary && prof?.working_days_per_month ? Math.round(prof.monthly_salary / prof.working_days_per_month * 100) / 100 : 0);
  const displayHourlyRate = prof?.hourly_rate || (displayDailyRate && prof?.standard_hours_per_day ? Math.round(displayDailyRate / prof.standard_hours_per_day * 100) / 100 : 0);

  return (
    <div className="p-6 max-w-[1200px]" data-testid="employee-detail-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/employees")}><ArrowLeft className="w-4 h-4 mr-1" /> Персонал</Button>
          <div className="relative group">
            <Avatar name={`${emp.first_name} ${emp.last_name}`} url={emp.avatar_url} size={48} />
            {editMode && (
              <label className="absolute inset-0 flex items-center justify-center bg-black/50 rounded-full opacity-0 group-hover:opacity-100 cursor-pointer transition-opacity">
                <Camera className="w-4 h-4 text-white" />
                <input type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
                    alert("Поддържани формати: JPG, PNG, WebP"); return;
                  }
                  if (file.size > 10 * 1024 * 1024) {
                    alert("Файлът е твърде голям (макс. 10MB)"); return;
                  }
                  const reader = new FileReader();
                  reader.onload = () => { setCropSrc(reader.result); setCropOpen(true); };
                  reader.readAsDataURL(file);
                  e.target.value = "";
                }} />
              </label>
            )}
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">{emp.first_name} {emp.last_name}</h1>
            <div className="flex items-center gap-3 text-sm text-muted-foreground mt-0.5">
              {prof?.position && <span className="text-foreground font-medium">{prof.position}</span>}
              <Badge variant="outline">{emp.role}</Badge>
              {emp.email && <span>{emp.email}</span>}
              {emp.phone && <span>{emp.phone}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right mr-4">
            <p className="text-xs text-muted-foreground">Този месец</p>
            <p className="text-lg font-bold text-foreground">{hours_summary.current_month_days} дни / {hours_summary.current_month_hours}ч</p>
          </div>
          {canEdit && !editMode && (
            <Button variant="outline" onClick={() => setEditMode(true)} data-testid="edit-employee-btn">
              <Pencil className="w-4 h-4 mr-1" /> Редактиране
            </Button>
          )}
          {editMode && (
            <>
              <Button onClick={handleSave} disabled={saving} data-testid="save-employee-btn">
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />} Запази
              </Button>
              <Button variant="ghost" onClick={handleCancel}><X className="w-4 h-4 mr-1" /> Отказ</Button>
            </>
          )}
        </div>
      </div>

      {/* Edit form OR pay info bar */}
      {editMode ? (
        <div className="rounded-xl border border-primary/30 bg-card p-5 mb-6 space-y-4" data-testid="edit-form">
          <h3 className="text-sm font-semibold text-foreground">Редактиране на служител</h3>
          
          {/* Basic info */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Име</Label>
              <Input value={editBasic.first_name} onChange={e => setEditBasic({...editBasic, first_name: e.target.value})} className="bg-background h-8 text-sm" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Фамилия</Label>
              <Input value={editBasic.last_name} onChange={e => setEditBasic({...editBasic, last_name: e.target.value})} className="bg-background h-8 text-sm" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Имейл</Label>
              <Input type="email" value={editBasic.email} onChange={e => setEditBasic({...editBasic, email: e.target.value})} className="bg-background h-8 text-sm" data-testid="email-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Длъжност</Label>
              <Input value={editProfile.position} onChange={e => setEditProfile({...editProfile, position: e.target.value})} placeholder="Бояджия, Майстор..." className="bg-background h-8 text-sm" data-testid="position-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Телефон</Label>
              <Input value={editBasic.phone} onChange={e => setEditBasic({...editBasic, phone: e.target.value})} placeholder="+359..." className="bg-background h-8 text-sm" data-testid="phone-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Активен</Label>
              <Select value={editProfile.active ? "true" : "false"} onValueChange={v => setEditProfile({...editProfile, active: v === "true"})}>
                <SelectTrigger className="bg-background h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">Да</SelectItem>
                  <SelectItem value="false">Не</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Pay settings */}
          <div className="border-t border-border pt-3">
            <Label className="text-xs text-muted-foreground mb-2 block">Заплащане (EUR)</Label>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Тип заплащане</Label>
                <Select value={editProfile.pay_type} onValueChange={v => updatePayField("pay_type", v)}>
                  <SelectTrigger className="bg-background h-8 text-sm" data-testid="pay-type-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PAY_TYPES.map(pt => <SelectItem key={pt.value} value={pt.value}>{pt.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>

              {editProfile.pay_type === "Monthly" && (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Месечна заплата (EUR)</Label>
                    <Input type="number" step="0.01" value={editProfile.monthly_salary}
                      onChange={e => updatePayField("monthly_salary", parseFloat(e.target.value) || 0)}
                      className="bg-background h-8 text-sm font-mono" data-testid="monthly-salary-input" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Работни дни/мес</Label>
                    <Input type="number" step="1" value={editProfile.working_days_per_month}
                      onChange={e => updatePayField("working_days_per_month", parseFloat(e.target.value) || 22)}
                      className="bg-background h-8 text-sm font-mono" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Часове/ден</Label>
                    <Input type="number" step="0.5" value={editProfile.standard_hours_per_day}
                      onChange={e => updatePayField("standard_hours_per_day", parseFloat(e.target.value) || 8)}
                      className="bg-background h-8 text-sm font-mono" />
                  </div>
                </>
              )}

              {editProfile.pay_type === "Akord" && (
                <div className="col-span-3 space-y-1">
                  <Label className="text-xs">Договорена основа / бележка за акорд</Label>
                  <Input value={editProfile.akord_note} onChange={e => setEditProfile({...editProfile, akord_note: e.target.value})}
                    placeholder="Напр. по обект, по задача, договорена цена..." className="bg-background h-8 text-sm" data-testid="akord-note-input" />
                </div>
              )}
            </div>

            {editProfile.pay_type === "Monthly" && editProfile.monthly_salary > 0 && (
              <div className="grid grid-cols-2 gap-3 mt-2">
                <div className="space-y-1">
                  <Label className="text-xs">Дневна (EUR) <span className="text-muted-foreground">(авто)</span></Label>
                  <Input type="number" value={editProfile.daily_rate} disabled
                    className="bg-background h-8 text-sm font-mono text-emerald-400" data-testid="daily-rate-input" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Часова (EUR) <span className="text-muted-foreground">(авто)</span></Label>
                  <Input type="number" value={editProfile.hourly_rate} disabled
                    className="bg-background h-8 text-sm font-mono text-emerald-400" data-testid="hourly-rate-input" />
                </div>
              </div>
            )}

            {editProfile.pay_type === "Monthly" && editProfile.monthly_salary > 0 && (
              <p className="text-xs text-muted-foreground mt-2">
                {editProfile.monthly_salary} EUR / {editProfile.working_days_per_month} дни = <span className="text-emerald-400 font-mono">{editProfile.daily_rate} EUR/ден</span>
                {" → "}{editProfile.daily_rate} / {editProfile.standard_hours_per_day}ч = <span className="text-emerald-400 font-mono">{editProfile.hourly_rate} EUR/ч</span>
              </p>
            )}
          </div>
        </div>
      ) : (
        /* View mode pay info bar */
        <div className="flex items-center gap-6 p-3 rounded-lg bg-muted/20 border border-border mb-6 text-sm flex-wrap" data-testid="pay-info-bar">
          {prof?.position && <div><span className="text-muted-foreground">Длъжност:</span> <span className="text-foreground font-medium">{prof.position}</span></div>}
          {emp.phone && <div><span className="text-muted-foreground">Тел:</span> <span className="text-foreground">{emp.phone}</span></div>}
          {prof && <div><span className="text-muted-foreground">Тип:</span> <span className="font-medium">{PAY_TYPES.find(p => p.value === prof.pay_type)?.label || prof.pay_type}</span></div>}
          {prof?.pay_type === "Monthly" && prof?.monthly_salary > 0 && <div><span className="text-muted-foreground">Месечна:</span> <span className="font-mono">{prof.monthly_salary} EUR</span></div>}
          {displayDailyRate > 0 && prof?.pay_type === "Monthly" && <div><span className="text-muted-foreground">Дневна:</span> <span className="font-mono">{displayDailyRate} EUR</span></div>}
          {displayHourlyRate > 0 && prof?.pay_type === "Monthly" && <div><span className="text-muted-foreground">Часова:</span> <span className="font-mono">{displayHourlyRate} EUR/ч</span></div>}
          {prof?.pay_type === "Akord" && <div><span className="text-muted-foreground">Акорд:</span> <span className="text-foreground">{prof.akord_note || "Договорено по задача"}</span></div>}
          <Badge variant="outline" className={prof?.active !== false ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}>
            {prof?.active !== false ? "Активен" : "Неактивен"}
          </Badge>
        </div>
      )}

      {/* Dossier warnings */}
      {dossier?.warnings?.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4" data-testid="dossier-warnings">
          {dossier.warnings.map((w, i) => (
            <Badge key={i} variant="outline" className={`text-[10px] ${w.type === "rate" ? "text-red-400 bg-red-500/10 border-red-500/30" : "text-amber-400 bg-amber-500/10 border-amber-500/30"}`}>
              <AlertTriangle className="w-2.5 h-2.5 mr-1" />{w.text}
            </Badge>
          ))}
        </div>
      )}

      {/* Dossier summary cards */}
      {dossier && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4" data-testid="dossier-summary-cards">
          <div className="rounded-lg bg-card border border-border p-2.5 text-center">
            <p className="text-lg font-bold font-mono">{dossier.reports?.total_hours || 0}<span className="text-xs text-muted-foreground">ч</span></p>
            <p className="text-[9px] text-muted-foreground">Общо часове</p>
          </div>
          <div className="rounded-lg bg-card border border-border p-2.5 text-center">
            <p className="text-lg font-bold font-mono text-primary">{(dossier.reports?.total_value || 0).toFixed(0)}<span className="text-xs text-muted-foreground"> EUR</span></p>
            <p className="text-[9px] text-muted-foreground">Изработено</p>
          </div>
          <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-2.5 text-center">
            <p className="text-lg font-bold font-mono text-emerald-400">{(dossier.payroll?.total_paid || 0).toFixed(0)}<span className="text-xs text-emerald-400/60"> EUR</span></p>
            <p className="text-[9px] text-emerald-400/70">Платено</p>
          </div>
          <div className="rounded-lg bg-card border border-border p-2.5 text-center">
            <p className="text-lg font-bold font-mono">{dossier.reports?.count || 0}</p>
            <p className="text-[9px] text-muted-foreground">Отчети</p>
          </div>
        </div>
      )}

      <Tabs defaultValue={defaultTab}>
        <TabsList className="mb-4 flex-wrap">
          <TabsTrigger value="calendar" data-testid="tab-calendar"><Calendar className="w-4 h-4 mr-1" /> Календар</TabsTrigger>
          <TabsTrigger value="reports" data-testid="tab-reports"><FileText className="w-4 h-4 mr-1" /> Отчети</TabsTrigger>
          <TabsTrigger value="payroll-weeks" data-testid="tab-payroll-weeks"><DollarSign className="w-4 h-4 mr-1" /> Заплати</TabsTrigger>
          <TabsTrigger value="projects" data-testid="tab-projects"><MapPin className="w-4 h-4 mr-1" /> Обекти ({project_history.length})</TabsTrigger>
          <TabsTrigger value="advances" data-testid="tab-advances"><Banknote className="w-4 h-4 mr-1" /> Заеми</TabsTrigger>
          <TabsTrigger value="attendance" data-testid="tab-attendance"><Clock className="w-4 h-4 mr-1" /> Присъствия</TabsTrigger>
          <TabsTrigger value="payroll" data-testid="tab-payroll"><CreditCard className="w-4 h-4 mr-1" /> Фишове</TabsTrigger>
        </TabsList>

        {/* Calendar Tab */}
        <TabsContent value="calendar">
          <div className="rounded-xl border border-border bg-card p-4" data-testid="calendar-view">
            <div className="flex items-center justify-between mb-4">
              <Button variant="ghost" size="sm" onClick={prevMonth}><ChevronLeft className="w-4 h-4" /></Button>
              <h3 className="text-sm font-semibold text-foreground">{calMonth}</h3>
              <Button variant="ghost" size="sm" onClick={nextMonth}><ChevronRight className="w-4 h-4" /></Button>
            </div>
            {calendar && (
              <>
                <div className="text-xs text-muted-foreground mb-1 text-right">
                  Дни: {calendar.total_present} | Часове: {calendar.total_hours}
                </div>
                <div className="grid grid-cols-7 gap-1">
                  {DAYS_BG.map(d => <div key={d} className="text-center text-[10px] text-muted-foreground font-medium py-1">{d}</div>)}
                  {calGrid.flat().map((cell, i) => {
                    if (!cell) return <div key={i} className="h-16" />;
                    const d = cell.data;
                    const att = d?.attendance;
                    const isPresent = att?.status === "Present";
                    const isAbsent = att?.status === "Absent";
                    const isLeave = att?.status === "Leave";
                    const isSick = att?.status === "Sick";
                    return (
                      <div key={i} className={`h-16 rounded-md border text-xs p-1 ${isPresent ? "border-emerald-500/30 bg-emerald-500/10" : isAbsent ? "border-red-500/30 bg-red-500/10" : isLeave ? "border-blue-500/30 bg-blue-500/10" : isSick ? "border-orange-500/30 bg-orange-500/10" : d ? "border-border bg-muted/20" : "border-transparent"}`}>
                        <span className={`text-[10px] font-mono ${isPresent ? "text-emerald-400" : isAbsent ? "text-red-400" : isLeave ? "text-blue-400" : isSick ? "text-orange-400" : "text-muted-foreground"}`}>{cell.day}</span>
                        {att && <div className="text-[9px] text-muted-foreground truncate">{att.project_code}</div>}
                        {d?.total_hours > 0 && <div className="text-[9px] font-mono text-amber-400">{d.total_hours}ч</div>}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </TabsContent>

        {/* Projects Tab */}
        <TabsContent value="projects">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="projects-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Обект</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Роля</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Дни</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Часове</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Последно</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {project_history.length === 0 ? (
                  <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Няма данни</TableCell></TableRow>
                ) : project_history.map((ph, i) => (
                  <TableRow key={i} className="cursor-pointer hover:bg-muted/30" onClick={() => navigate(`/projects/${ph.project_id}`)}>
                    <TableCell><span className="font-mono text-primary text-sm">{ph.project_code}</span> <span className="text-muted-foreground text-sm">{ph.project_name}</span></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{ph.role_in_project || "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{ph.days_present}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-amber-400">{ph.total_hours || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{ph.last_attendance ? formatDate(ph.last_attendance) : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* Attendance Tab */}
        <TabsContent value="attendance">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="attendance-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Дата</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Обект</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {attendance.length === 0 ? (
                  <TableRow><TableCell colSpan={3} className="text-center py-8 text-muted-foreground">Няма записи</TableCell></TableRow>
                ) : attendance.map((att, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-sm font-mono">{att.date}</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[att.status] || ""}`}>{STATUS_BG[att.status] || att.status}</Badge></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{att.project_code || "—"} {att.project_name || ""}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* ═══ DOSSIER: Reports Tab ═══ */}
        <TabsContent value="reports">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="dossier-reports-tab">
            {!dossier?.reports?.lines?.length ? (
              <div className="p-8 text-center text-muted-foreground text-sm">Няма отчети</div>
            ) : (
              <>
                <div className="flex items-center gap-4 p-3 border-b border-border text-xs text-muted-foreground">
                  <span>Общо: <strong className="text-foreground">{dossier.reports.total_hours}ч</strong></span>
                  <span>Стойност: <strong className="text-primary font-mono">{dossier.reports.total_value?.toFixed(0)} EUR</strong></span>
                  <span>Записи: {dossier.reports.count}</span>
                </div>
                <Table>
                  <TableHeader><TableRow>
                    <TableHead className="text-[10px]">Дата</TableHead>
                    <TableHead className="text-[10px]">Обект</TableHead>
                    <TableHead className="text-[10px]">СМР</TableHead>
                    <TableHead className="text-[10px] text-center">Часове</TableHead>
                    <TableHead className="text-[10px] text-center">Извънр.</TableHead>
                    <TableHead className="text-[10px] text-center">Стойност</TableHead>
                    <TableHead className="text-[10px]">Статус</TableHead>
                    <TableHead className="text-[10px]">Заплата</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {dossier.reports.lines.map((r, i) => (
                      <TableRow key={`${r.id}-${i}`} className="hover:bg-muted/10">
                        <TableCell className="text-xs font-mono">{r.date}</TableCell>
                        <TableCell>{r.project_name ? <button onClick={() => navigate(`/projects/${r.project_id}`)} className="text-[10px] text-primary hover:underline flex items-center gap-0.5"><MapPin className="w-2.5 h-2.5" />{r.project_name}</button> : <span className="text-[10px] text-muted-foreground">—</span>}</TableCell>
                        <TableCell className="text-xs truncate max-w-[120px]">{r.smr || "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono font-bold">{r.hours}</TableCell>
                        <TableCell className={`text-center text-xs font-mono ${r.overtime > 0 ? "text-amber-400 font-bold" : "text-muted-foreground"}`}>{r.overtime > 0 ? `+${r.overtime}` : "—"}</TableCell>
                        <TableCell className="text-center text-xs font-mono text-primary">{r.value > 0 ? r.value.toFixed(0) : "—"}</TableCell>
                        <TableCell><Badge variant="outline" className={`text-[9px] ${r.status === "APPROVED" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : r.status === "DRAFT" ? "bg-gray-500/15 text-gray-400 border-gray-500/30" : r.status === "SUBMITTED" ? "bg-blue-500/15 text-blue-400 border-blue-500/30" : "bg-red-500/15 text-red-400 border-red-500/30"}`}>{r.status === "APPROVED" ? "Одобрен" : r.status === "DRAFT" ? "Чернова" : r.status === "SUBMITTED" ? "Подаден" : r.status}</Badge></TableCell>
                        <TableCell>{r.payroll_status === "paid" ? <Badge variant="outline" className="text-[9px] bg-emerald-500/15 text-emerald-400 border-emerald-500/30">Платен</Badge> : r.payroll_status === "batched" ? <Badge variant="outline" className="text-[9px] bg-violet-500/15 text-violet-400 border-violet-500/30">В пакет</Badge> : <span className="text-[10px] text-muted-foreground">—</span>}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </>
            )}
          </div>
        </TabsContent>

        {/* ═══ DOSSIER: Payroll Weeks Tab ═══ */}
        {/* ═══ DOSSIER: Payroll Weeks Tab — real pay runs data ═══ */}
        <TabsContent value="payroll-weeks">
          <EmployeePayrollWeeks userId={userId} onViewSlip={(slipId) => {
            API.get(`/payment-slips/${slipId}`).then(r => setPayslipOpen({ slip: r.data })).catch(() => {});
          }} />
        </TabsContent>

        {/* ═══ DOSSIER: Advances Tab ═══ */}
        <TabsContent value="advances">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="dossier-advances-tab">
            {!dossier?.advances?.length ? (
              <div className="p-8 text-center text-muted-foreground text-sm">Няма записи за заеми / аванси</div>
            ) : (
              <Table>
                <TableHeader><TableRow>
                  <TableHead className="text-[10px]">Вид</TableHead>
                  <TableHead className="text-[10px]">Дата</TableHead>
                  <TableHead className="text-[10px] text-center">Сума</TableHead>
                  <TableHead className="text-[10px] text-center">Остатък</TableHead>
                  <TableHead className="text-[10px]">Статус</TableHead>
                  <TableHead className="text-[10px]">Бележка</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {dossier.advances.map(a => (
                    <TableRow key={a.id} className="hover:bg-muted/10">
                      <TableCell className="text-xs">{a.type === "advance" ? "Аванс" : a.type === "loan" ? "Заем" : a.type}</TableCell>
                      <TableCell className="text-xs font-mono">{a.date || "—"}</TableCell>
                      <TableCell className="text-center text-xs font-mono">{a.amount?.toFixed(0)} EUR</TableCell>
                      <TableCell className={`text-center text-xs font-mono ${a.remaining > 0 ? "text-amber-400" : "text-emerald-400"}`}>{a.remaining?.toFixed(0)} EUR</TableCell>
                      <TableCell><Badge variant="outline" className={`text-[9px] ${a.status === "active" || a.status === "approved" ? "text-amber-400 bg-amber-500/15 border-amber-500/30" : "text-muted-foreground"}`}>{a.status}</Badge></TableCell>
                      <TableCell className="text-[10px] text-muted-foreground truncate max-w-[150px]">{a.note || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </TabsContent>

        {/* Фишове Tab — real payment slips */}
        <TabsContent value="payroll">
          <EmployeeSlips userId={userId} />
        </TabsContent>
      </Tabs>

      {/* Image Crop Dialog */}
      <ImageCropDialog
        open={cropOpen}
        onOpenChange={setCropOpen}
        imageSrc={cropSrc}
        onCropComplete={async (blob) => {
          try {
            const fd = new FormData();
            fd.append("file", blob, "avatar.jpg");
            fd.append("context_type", "profile");
            fd.append("context_id", userId);
            const res = await API.post("/media/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
            const storedFilename = res.data.url.split("/").pop();
            const avatarUrl = `/api/media/avatar/${storedFilename}`;
            await API.put(`/employees/${userId}/basic`, { avatar_url: avatarUrl });
            fetchData();
          } catch (err) { alert("Грешка при запис на снимка"); }
        }}
      />

      {/* Official Payslip Dialog */}
      <PayslipDialog
        open={!!payslipOpen}
        onClose={() => setPayslipOpen(null)}
        batchId={payslipOpen?.batchId}
        workerId={payslipOpen?.workerId}
      />
    </div>
  );
}


function EmployeePayrollWeeks({ userId, onViewSlip }) {
  const [weeks, setWeeks] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    API.get(`/payroll-weeks?employee_id=${userId}`)
      .then(r => setWeeks(r.data?.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);

  if (loading) return <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!weeks.length) return <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground text-sm">Няма pay run записи</div>;

  const totalEarned = weeks.reduce((s, w) => s + (w.earned_amount || 0), 0);
  const totalPaid = weeks.reduce((s, w) => s + (w.paid_now_amount || 0), 0);

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="emp-payroll-weeks">
      <div className="flex items-center gap-4 p-3 border-b border-border text-xs text-muted-foreground">
        <span>Изработено: <strong className="text-primary font-mono">{totalEarned.toFixed(0)} EUR</strong></span>
        <span>Платено: <strong className="text-emerald-400 font-mono">{totalPaid.toFixed(0)} EUR</strong></span>
        <span>Записи: {weeks.length}</span>
      </div>
      <Table>
        <TableHeader><TableRow>
          <TableHead className="text-[10px]">Сед.</TableHead>
          <TableHead className="text-[10px]">Период</TableHead>
          <TableHead className="text-[10px] text-center">Дни</TableHead>
          <TableHead className="text-[10px] text-center">Часове</TableHead>
          <TableHead className="text-[10px] text-center">Изработено</TableHead>
          <TableHead className="text-[10px] text-center">Платено</TableHead>
          <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
          <TableHead className="text-[10px]">Статус</TableHead>
          <TableHead className="text-[10px]">Фиш</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {weeks.map((w, i) => {
            const isPaid = w.run_status === "paid";
            return (
              <TableRow key={i} className={isPaid ? "bg-emerald-500/3" : ""}>
                <TableCell className="text-xs font-mono font-bold">{w.week_number || "—"}</TableCell>
                <TableCell className="text-xs font-mono">{w.period_start}→{w.period_end}</TableCell>
                <TableCell className="text-center text-xs font-mono">{w.approved_days}</TableCell>
                <TableCell className="text-center text-xs font-mono font-bold">{w.approved_hours}</TableCell>
                <TableCell className="text-center text-xs font-mono text-primary">{w.earned_amount?.toFixed(0)}</TableCell>
                <TableCell className="text-center text-xs font-mono text-emerald-400">{w.paid_now_amount?.toFixed(0)}</TableCell>
                <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${w.remaining_after_payment > 0 ? "text-amber-400" : w.remaining_after_payment < 0 ? "text-red-400" : "text-emerald-400"}`}>{w.remaining_after_payment?.toFixed(0)}</TableCell>
                <TableCell><Badge variant="outline" className={`text-[9px] ${isPaid ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : "bg-violet-500/15 text-violet-400 border-violet-500/30"}`}>{isPaid ? "Платен" : "Потвърден"}</Badge></TableCell>
                <TableCell>{w.slip_number ? <Badge variant="outline" className="text-[9px] cursor-pointer" onClick={() => onViewSlip?.(w.slip_id)}>{w.slip_number}</Badge> : "—"}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function EmployeeSlips({ userId }) {
  const [slips, setSlips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    API.get(`/payment-slips?employee_id=${userId}`)
      .then(r => setSlips(r.data?.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);

  if (loading) return <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  if (!slips.length) return <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground text-sm">Няма фишове</div>;

  return (
    <>
      <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="emp-slips">
        <Table>
          <TableHeader><TableRow>
            <TableHead className="text-[10px]">Фиш №</TableHead>
            <TableHead className="text-[10px]">Период</TableHead>
            <TableHead className="text-[10px] text-center">Часове</TableHead>
            <TableHead className="text-[10px] text-center">Изработено</TableHead>
            <TableHead className="text-[10px] text-center">Удръжки</TableHead>
            <TableHead className="text-[10px] text-center">Платено</TableHead>
            <TableHead className="text-[10px] text-center bg-primary/5">Остатък</TableHead>
            <TableHead className="text-[10px]">Статус</TableHead>
            <TableHead className="text-[10px] w-[40px]" />
          </TableRow></TableHeader>
          <TableBody>
            {slips.map(s => (
              <TableRow key={s.id} className={s.status === "paid" ? "bg-emerald-500/3" : ""}>
                <TableCell className="text-xs font-mono font-bold">{s.slip_number}</TableCell>
                <TableCell className="text-xs font-mono">{s.period_start}→{s.period_end}</TableCell>
                <TableCell className="text-center text-xs font-mono">{s.approved_hours}</TableCell>
                <TableCell className="text-center text-xs font-mono text-primary">{s.earned_amount?.toFixed(0)}</TableCell>
                <TableCell className="text-center text-xs font-mono text-red-400">{s.deductions_amount > 0 ? `-${s.deductions_amount.toFixed(0)}` : "—"}</TableCell>
                <TableCell className="text-center text-xs font-mono text-emerald-400">{s.paid_now_amount?.toFixed(0)}</TableCell>
                <TableCell className={`text-center text-xs font-mono font-bold bg-primary/5 ${s.remaining_after_payment > 0 ? "text-amber-400" : s.remaining_after_payment < 0 ? "text-red-400" : "text-emerald-400"}`}>{s.remaining_after_payment?.toFixed(0)}</TableCell>
                <TableCell><Badge variant="outline" className={`text-[9px] ${s.status === "paid" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : "bg-violet-500/15 text-violet-400 border-violet-500/30"}`}>{s.status === "paid" ? "Платен" : "Потвърден"}</Badge></TableCell>
                <TableCell><Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setDetail(s)}><Eye className="w-3.5 h-3.5" /></Button></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {detail && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-card rounded-xl border border-border p-6 max-w-lg w-full max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-3">Фиш {detail.slip_number}</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">Период</span><span className="font-mono">{detail.period_start} → {detail.period_end}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Дни / Часове</span><span className="font-mono">{detail.approved_days}д / {detail.approved_hours}ч</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Ставка</span><span className="font-mono">{detail.frozen_hourly_rate} EUR/ч</span></div>
              {detail.adjustments?.length > 0 && (
                <div className="border-t border-border pt-2 mt-2">
                  <p className="text-[10px] text-muted-foreground uppercase mb-1">Корекции</p>
                  {detail.adjustments.map((a, i) => (
                    <div key={i} className="flex justify-between text-xs"><span className={a.type === "bonus" ? "text-emerald-400" : "text-red-400"}>{a.title || a.type}</span><span className="font-mono">{a.type === "bonus" ? "+" : "-"}{a.amount}</span></div>
                  ))}
                </div>
              )}
              <div className="border-t border-border pt-2 mt-2 rounded-lg bg-primary/5 p-3 space-y-1">
                <div className="flex justify-between"><span>Изработено</span><span className="font-mono">{detail.earned_amount?.toFixed(2)} EUR</span></div>
                {detail.bonuses_amount > 0 && <div className="flex justify-between text-emerald-400"><span>+ Бонуси</span><span className="font-mono">+{detail.bonuses_amount?.toFixed(2)}</span></div>}
                {detail.deductions_amount > 0 && <div className="flex justify-between text-red-400"><span>- Удръжки</span><span className="font-mono">-{detail.deductions_amount?.toFixed(2)}</span></div>}
                <div className="flex justify-between font-bold pt-1 border-t border-border"><span>Платено</span><span className="font-mono text-primary">{detail.paid_now_amount?.toFixed(2)} EUR</span></div>
                <div className="flex justify-between"><span>Остатък</span><span className={`font-mono font-bold ${detail.remaining_after_payment > 0 ? "text-amber-400" : "text-emerald-400"}`}>{detail.remaining_after_payment?.toFixed(2)} EUR</span></div>
              </div>
              {detail.paid_at && <p className="text-xs text-emerald-400 mt-2">Платено на {detail.paid_at?.slice(0, 10)}</p>}
            </div>
            <Button variant="outline" size="sm" onClick={() => setDetail(null)} className="mt-4 w-full">Затвори</Button>
          </div>
        </div>
      )}
    </>
  );
}
