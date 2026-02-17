import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
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
  Users,
  Pencil,
  Loader2,
  DollarSign,
  Calendar,
  Clock,
} from "lucide-react";

const PAY_TYPES = ["Hourly", "Daily", "Monthly"];
const PAY_SCHEDULES = ["Weekly", "Monthly"];

export default function EmployeesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedEmployee, setSelectedEmployee] = useState(null);
  const [saving, setSaving] = useState(false);

  // Form state
  const [payType, setPayType] = useState("Daily");
  const [hourlyRate, setHourlyRate] = useState("");
  const [dailyRate, setDailyRate] = useState("");
  const [monthlySalary, setMonthlySalary] = useState("");
  const [standardHours, setStandardHours] = useState(8);
  const [paySchedule, setPaySchedule] = useState("Monthly");
  const [active, setActive] = useState(true);
  const [startDate, setStartDate] = useState("");

  const fetchEmployees = useCallback(async () => {
    try {
      const res = await API.get("/employees");
      setEmployees(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchEmployees(); }, [fetchEmployees]);

  const openEdit = (emp) => {
    setSelectedEmployee(emp);
    const p = emp.profile;
    setPayType(p?.pay_type || "Daily");
    setHourlyRate(p?.hourly_rate || "");
    setDailyRate(p?.daily_rate || "");
    setMonthlySalary(p?.monthly_salary || "");
    setStandardHours(p?.standard_hours_per_day || 8);
    setPaySchedule(p?.pay_schedule || "Monthly");
    setActive(p?.active ?? true);
    setStartDate(p?.start_date || "");
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!selectedEmployee) return;
    setSaving(true);
    try {
      await API.post("/employees", {
        user_id: selectedEmployee.id,
        pay_type: payType,
        hourly_rate: hourlyRate ? parseFloat(hourlyRate) : null,
        daily_rate: dailyRate ? parseFloat(dailyRate) : null,
        monthly_salary: monthlySalary ? parseFloat(monthlySalary) : null,
        standard_hours_per_day: standardHours,
        pay_schedule: paySchedule,
        active,
        start_date: startDate || null,
      });
      setDialogOpen(false);
      await fetchEmployees();
    } catch (err) {
      alert(err.response?.data?.detail || t("toast.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const formatCurrencyLocal = (amount) => {
    if (!amount) return "-";
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR" }).format(amount);
  };

  const getRateDisplay = (emp) => {
    const p = emp.profile;
    if (!p) return "-";
    if (p.pay_type === "Hourly") return `${formatCurrencyLocal(p.hourly_rate)}/${t("employees.hr")}`;
    if (p.pay_type === "Daily") return `${formatCurrencyLocal(p.daily_rate)}/${t("employees.day")}`;
    if (p.pay_type === "Monthly") return `${formatCurrencyLocal(p.monthly_salary)}/${t("employees.mo")}`;
    return "-";
  };

  return (
    <div className="p-8 max-w-[1200px]" data-testid="employees-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("employees.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("employees.subtitle")}</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="employees-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("employees.employee")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.role")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("employees.payType")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("employees.rate")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("employees.schedule")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">{t("common.status")}</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {employees.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    <Users className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>{t("employees.noEmployees")}</p>
                  </TableCell>
                </TableRow>
              ) : (
                employees.map((emp) => (
                  <TableRow key={emp.id} className="table-row-hover" data-testid={`employee-row-${emp.id}`}>
                    <TableCell>
                      <p className="font-medium text-foreground">{emp.name || emp.email.split("@")[0]}</p>
                      <p className="text-xs text-muted-foreground">{emp.email}</p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">{t(`users.roles.${emp.role.toLowerCase()}`, emp.role)}</Badge>
                    </TableCell>
                    <TableCell>
                      {emp.profile ? (
                        <div className="flex items-center gap-1">
                          {emp.profile.pay_type === "Hourly" && <Clock className="w-3 h-3 text-blue-400" />}
                          {emp.profile.pay_type === "Daily" && <Calendar className="w-3 h-3 text-emerald-400" />}
                          {emp.profile.pay_type === "Monthly" && <DollarSign className="w-3 h-3 text-amber-400" />}
                          <span className="text-sm">{t(`employees.payTypes.${emp.profile.pay_type.toLowerCase()}`)}</span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-sm">{t("employees.notSet")}</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-sm">{getRateDisplay(emp)}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {emp.profile?.pay_schedule ? t(`employees.schedules.${emp.profile.pay_schedule.toLowerCase()}`) : "-"}
                    </TableCell>
                    <TableCell>
                      {emp.profile ? (
                        <Badge variant="outline" className={`text-xs ${emp.profile.active ? "text-emerald-400 border-emerald-500/30" : "text-gray-400 border-gray-500/30"}`}>
                          {emp.profile.active ? t("employees.active") : t("employees.inactive")}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-xs text-gray-400 border-gray-500/30">{t("employees.noProfile")}</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => openEdit(emp)} data-testid={`edit-btn-${emp.id}`}>
                        <Pencil className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[500px] bg-card border-border" data-testid="employee-dialog">
          <DialogHeader>
            <DialogTitle>{t("employees.configurePayRate")}</DialogTitle>
          </DialogHeader>
          {selectedEmployee && (
            <div className="space-y-4 py-4">
              <div className="p-3 rounded-lg bg-muted/50">
                <p className="font-medium text-foreground">{selectedEmployee.name || selectedEmployee.email}</p>
                <p className="text-xs text-muted-foreground">{t(`users.roles.${selectedEmployee.role.toLowerCase()}`, selectedEmployee.role)}</p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t("employees.payType")}</Label>
                  <Select value={payType} onValueChange={setPayType}>
                    <SelectTrigger className="bg-background" data-testid="pay-type-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PAY_TYPES.map((pt) => <SelectItem key={pt} value={pt}>{t(`employees.payTypes.${pt.toLowerCase()}`)}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>{t("employees.paySchedule")}</Label>
                  <Select value={paySchedule} onValueChange={setPaySchedule}>
                    <SelectTrigger className="bg-background" data-testid="pay-schedule-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PAY_SCHEDULES.map((s) => <SelectItem key={s} value={s}>{t(`employees.schedules.${s.toLowerCase()}`)}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {payType === "Hourly" && (
                <div className="space-y-2">
                  <Label>{t("employees.hourlyRate")}</Label>
                  <Input type="number" value={hourlyRate} onChange={(e) => setHourlyRate(e.target.value)} placeholder="0.00" className="bg-background" data-testid="hourly-rate-input" />
                </div>
              )}
              {payType === "Daily" && (
                <div className="space-y-2">
                  <Label>{t("employees.dailyRate")}</Label>
                  <Input type="number" value={dailyRate} onChange={(e) => setDailyRate(e.target.value)} placeholder="0.00" className="bg-background" data-testid="daily-rate-input" />
                </div>
              )}
              {payType === "Monthly" && (
                <div className="space-y-2">
                  <Label>{t("employees.monthlySalary")}</Label>
                  <Input type="number" value={monthlySalary} onChange={(e) => setMonthlySalary(e.target.value)} placeholder="0.00" className="bg-background" data-testid="monthly-salary-input" />
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t("employees.standardHoursDay")}</Label>
                  <Input type="number" value={standardHours} onChange={(e) => setStandardHours(parseFloat(e.target.value) || 8)} className="bg-background" data-testid="standard-hours-input" />
                </div>
                <div className="space-y-2">
                  <Label>{t("employees.startDate")}</Label>
                  <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-background" data-testid="start-date-input" />
                </div>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <Switch checked={active} onCheckedChange={setActive} data-testid="active-switch" />
                <Label>{t("employees.activeForPayroll")}</Label>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={handleSave} disabled={saving} data-testid="save-profile-btn">
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
