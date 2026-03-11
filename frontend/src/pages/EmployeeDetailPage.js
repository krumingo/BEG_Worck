import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
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
} from "lucide-react";
import ImageCropDialog from "@/components/ImageCropDialog";

function Avatar({ name, url, size = 48 }) {
  if (url) return <img src={url} alt={name} className="rounded-full object-cover" style={{ width: size, height: size }} />;
  const initials = (name || "?").split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
  return (
    <div className="rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold" style={{ width: size, height: size, fontSize: size * 0.35 }}>
      {initials}
    </div>
  );
}

const STATUS_COLORS = { Present: "bg-emerald-500/20 text-emerald-400", Absent: "bg-red-500/20 text-red-400", Late: "bg-amber-500/20 text-amber-400" };
const STATUS_BG = { Present: "Присъства", Absent: "Отсъства", Late: "Закъснял" };
const DAYS_BG = ["Нд", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
const PAY_TYPES = [
  { value: "Monthly", label: "Месечно" },
  { value: "Akord", label: "Акорд (пазарлък)" },
];

export default function EmployeeDetailPage() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = ["Admin", "Owner"].includes(user?.role);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [calMonth, setCalMonth] = useState(new Date().toISOString().slice(0, 7));
  const [calendar, setCalendar] = useState(null);

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
      setEditBasic({ first_name: e.first_name || "", last_name: e.last_name || "", phone: e.phone || "", role: e.role || "" });
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
      setEditBasic({ first_name: e.first_name || "", last_name: e.last_name || "", phone: e.phone || "", role: e.role || "" });
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

      <Tabs defaultValue="calendar">
        <TabsList className="mb-4">
          <TabsTrigger value="calendar" data-testid="tab-calendar"><Calendar className="w-4 h-4 mr-1" /> Календар</TabsTrigger>
          <TabsTrigger value="projects" data-testid="tab-projects"><MapPin className="w-4 h-4 mr-1" /> Обекти ({project_history.length})</TabsTrigger>
          <TabsTrigger value="attendance" data-testid="tab-attendance"><Clock className="w-4 h-4 mr-1" /> Присъствия</TabsTrigger>
          <TabsTrigger value="payroll" data-testid="tab-payroll"><CreditCard className="w-4 h-4 mr-1" /> Заплащане</TabsTrigger>
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
                    return (
                      <div key={i} className={`h-16 rounded-md border text-xs p-1 ${isPresent ? "border-emerald-500/30 bg-emerald-500/10" : isAbsent ? "border-red-500/30 bg-red-500/10" : d ? "border-border bg-muted/20" : "border-transparent"}`}>
                        <span className={`text-[10px] font-mono ${isPresent ? "text-emerald-400" : isAbsent ? "text-red-400" : "text-muted-foreground"}`}>{cell.day}</span>
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

        {/* Payroll Tab */}
        <TabsContent value="payroll">
          <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="payroll-table">
            <Table>
              <TableHeader><TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase text-muted-foreground">Период</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Бруто</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground text-right">Нето</TableHead>
                <TableHead className="text-xs uppercase text-muted-foreground">Статус</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {payslips.length === 0 ? (
                  <TableRow><TableCell colSpan={4} className="text-center py-8 text-muted-foreground">Няма фишове</TableCell></TableRow>
                ) : payslips.map((ps, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-sm">{ps.period_start} — {ps.period_end}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{formatCurrency(ps.gross_pay, "EUR")}</TableCell>
                    <TableCell className="text-right font-mono text-sm font-bold">{formatCurrency(ps.net_pay, "EUR")}</TableCell>
                    <TableCell><Badge variant="outline" className={`text-[10px] ${ps.status === "Paid" ? "bg-emerald-500/20 text-emerald-400" : ""}`}>{ps.status}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="p-3 border-t border-border">
              <Button variant="outline" size="sm" onClick={() => navigate("/payroll")} className="text-xs">Към Заплати</Button>
            </div>
          </div>
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
            const avatarUrl = `/api/media/${res.data.id}/file`;
            await API.put(`/employees/${userId}/basic`, { avatar_url: avatarUrl });
            fetchData();
          } catch (err) { alert("Грешка при запис на снимка"); }
        }}
      />
    </div>
  );
}
