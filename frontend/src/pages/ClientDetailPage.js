/**
 * ClientDetailPage — Unified client card with projects, invoices, totals.
 * Route: /clients/:clientId
 */
import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  ArrowLeft, User, Building2, Phone, Mail, Loader2,
  FolderKanban, Receipt, DollarSign, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_COLORS = {
  Active: "text-emerald-400", Draft: "text-gray-400", Completed: "text-blue-400",
  Finished: "text-blue-400", Paused: "text-amber-400", Cancelled: "text-red-400",
};

export default function ClientDetailPage() {
  const { clientId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});

  const load = useCallback(async () => {
    try {
      const res = await API.get(`/clients/${clientId}/summary`);
      setData(res.data);
      setForm(res.data.client || {});
    } catch { /* */ }
    finally { setLoading(false); }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    try {
      await API.put(`/clients/${clientId}`, form);
      toast.success(t("clientDetail.saved"));
      setEditing(false);
      load();
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
  };

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin" /></div>;
  if (!data) return <div className="p-6 text-center text-muted-foreground">{t("clientDetail.notFound")}</div>;

  const { client, projects, totals, invoices } = data;
  const isCompany = client.type === "company";
  const name = isCompany ? (client.companyName || client.name) : (client.fullName || client.name || `${client.first_name || ""} ${client.last_name || ""}`);

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4" data-testid="client-detail-page">
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate("/data/clients")}><ArrowLeft className="w-4 h-4 mr-1" /> {t("clientDetail.back")}</Button>
        <div className="flex items-center gap-2 flex-1">
          {isCompany ? <Building2 className="w-6 h-6 text-blue-400" /> : <User className="w-6 h-6 text-emerald-400" />}
          <div>
            <h1 className="text-xl font-bold" data-testid="client-name">{name}</h1>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <Badge variant="outline" className="text-[10px]">{isCompany ? t("clientDetail.company") : t("clientDetail.person")}</Badge>
              {client.phone && <span className="flex items-center gap-1"><Phone className="w-3 h-3" />{client.phone}</span>}
              {client.email && <span className="flex items-center gap-1"><Mail className="w-3 h-3" />{client.email}</span>}
              {client.eik && <span>ЕИК: {client.eik}</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-lg border border-border bg-card p-3 text-center">
          <FolderKanban className="w-5 h-5 mx-auto mb-1 text-primary" />
          <p className="text-2xl font-bold">{totals.projects_count}</p>
          <p className="text-[10px] text-muted-foreground">{t("clientDetail.projects")}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-3 text-center">
          <Receipt className="w-5 h-5 mx-auto mb-1 text-blue-400" />
          <p className="text-2xl font-bold font-mono">{totals.total_revenue.toFixed(0)}</p>
          <p className="text-[10px] text-muted-foreground">{t("clientDetail.totalRevenue")}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-3 text-center">
          <DollarSign className="w-5 h-5 mx-auto mb-1 text-emerald-400" />
          <p className="text-2xl font-bold font-mono text-emerald-400">{totals.total_paid.toFixed(0)}</p>
          <p className="text-[10px] text-muted-foreground">{t("clientDetail.totalPaid")}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-3 text-center">
          <AlertTriangle className={`w-5 h-5 mx-auto mb-1 ${totals.total_outstanding > 0 ? "text-red-400" : "text-emerald-400"}`} />
          <p className={`text-2xl font-bold font-mono ${totals.total_outstanding > 0 ? "text-red-400" : "text-emerald-400"}`}>{totals.total_outstanding.toFixed(0)}</p>
          <p className="text-[10px] text-muted-foreground">{t("clientDetail.outstanding")}</p>
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="bg-card border border-border">
          <TabsTrigger value="overview">{t("clientDetail.tabOverview")}</TabsTrigger>
          <TabsTrigger value="invoices">{t("clientDetail.tabInvoices")}</TabsTrigger>
          <TabsTrigger value="data">{t("clientDetail.tabData")}</TabsTrigger>
        </TabsList>

        {/* Overview */}
        <TabsContent value="overview" className="mt-4">
          {projects.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">{t("clientDetail.noProjects")}</p>
          ) : (
            <Table>
              <TableHeader><TableRow>
                <TableHead>{t("clientDetail.projectName")}</TableHead>
                <TableHead>{t("common.status")}</TableHead>
                <TableHead className="text-right">{t("clientDetail.invoiced")}</TableHead>
                <TableHead className="text-right">{t("clientDetail.paid")}</TableHead>
                <TableHead className="text-right">{t("clientDetail.due")}</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {projects.map(p => {
                  const dueDot = p.balance_due > 0 ? "bg-red-500" : "bg-emerald-500";
                  return (
                    <TableRow key={p.id} className="cursor-pointer hover:bg-muted/30" onClick={() => navigate(`/projects/${p.id}`)}>
                      <TableCell className="font-medium">{p.name}</TableCell>
                      <TableCell><span className={STATUS_COLORS[p.status] || ""}>{p.status}</span></TableCell>
                      <TableCell className="text-right font-mono">{p.total_invoiced.toFixed(0)}</TableCell>
                      <TableCell className="text-right font-mono text-emerald-400">{p.total_paid.toFixed(0)}</TableCell>
                      <TableCell className="text-right">
                        <span className={`inline-block w-2 h-2 rounded-full ${dueDot} mr-1`} />
                        <span className="font-mono">{p.balance_due.toFixed(0)}</span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </TabsContent>

        {/* Invoices */}
        <TabsContent value="invoices" className="mt-4">
          {invoices.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">{t("clientDetail.noInvoices")}</p>
          ) : (
            <Table>
              <TableHeader><TableRow>
                <TableHead>#</TableHead>
                <TableHead>{t("clientDetail.project")}</TableHead>
                <TableHead className="text-right">{t("clientDetail.amount")}</TableHead>
                <TableHead className="text-right">{t("clientDetail.paid")}</TableHead>
                <TableHead>{t("common.status")}</TableHead>
                <TableHead>{t("common.date")}</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {invoices.map(inv => (
                  <TableRow key={inv.id}>
                    <TableCell className="font-mono text-primary">{inv.invoice_no}</TableCell>
                    <TableCell>{inv.project_name}</TableCell>
                    <TableCell className="text-right font-mono">{(inv.total || 0).toFixed(2)}</TableCell>
                    <TableCell className="text-right font-mono text-emerald-400">{(inv.paid || 0).toFixed(2)}</TableCell>
                    <TableCell><Badge variant="outline" className="text-[10px]">{inv.status}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{inv.issue_date ? formatDate(inv.issue_date) : "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </TabsContent>

        {/* Data (editable) */}
        <TabsContent value="data" className="mt-4">
          <div className="bg-card border border-border rounded-lg p-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {isCompany && <>
                <div className="space-y-1"><Label className="text-xs">{t("clientDetail.companyName")}</Label><Input value={form.companyName || form.name || ""} onChange={e => setForm(f => ({ ...f, companyName: e.target.value, name: e.target.value }))} disabled={!editing} /></div>
                <div className="space-y-1"><Label className="text-xs">ЕИК</Label><Input value={form.eik || ""} onChange={e => setForm(f => ({ ...f, eik: e.target.value }))} disabled={!editing} /></div>
                <div className="space-y-1"><Label className="text-xs">МОЛ</Label><Input value={form.mol || ""} onChange={e => setForm(f => ({ ...f, mol: e.target.value }))} disabled={!editing} /></div>
                <div className="space-y-1"><Label className="text-xs">{t("clientDetail.vatNumber")}</Label><Input value={form.vatNumber || ""} onChange={e => setForm(f => ({ ...f, vatNumber: e.target.value }))} disabled={!editing} /></div>
              </>}
              {!isCompany && <>
                <div className="space-y-1"><Label className="text-xs">{t("common.name")}</Label><Input value={form.fullName || form.name || ""} onChange={e => setForm(f => ({ ...f, fullName: e.target.value, name: e.target.value }))} disabled={!editing} /></div>
              </>}
              <div className="space-y-1"><Label className="text-xs">{t("clientDetail.phone")}</Label><Input value={form.phone || ""} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} disabled={!editing} /></div>
              <div className="space-y-1"><Label className="text-xs">{t("common.email")}</Label><Input value={form.email || ""} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} disabled={!editing} /></div>
              <div className="col-span-2 space-y-1"><Label className="text-xs">{t("clientDetail.address")}</Label><Input value={form.address || ""} onChange={e => setForm(f => ({ ...f, address: e.target.value }))} disabled={!editing} /></div>
            </div>
            <div className="flex gap-2">
              {editing ? (
                <><Button size="sm" onClick={handleSave}>{t("common.save")}</Button><Button variant="outline" size="sm" onClick={() => { setEditing(false); setForm(client); }}>{t("common.cancel")}</Button></>
              ) : (
                <Button variant="outline" size="sm" onClick={() => setEditing(true)}>{t("clientDetail.edit")}</Button>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
