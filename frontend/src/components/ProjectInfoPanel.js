/**
 * ProjectInfoPanel — Structured address, contacts, invoice details, object info.
 * Embedded in ProjectDetailPage.
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  MapPin, User, Phone, Mail, Building2, FileText, Home,
  Save, Loader2, Download, Plus, Trash2,
} from "lucide-react";
import { toast } from "sonner";

const OBJ_TYPES = [
  { value: "apartment", label: "Апартамент" },
  { value: "house", label: "Къща" },
  { value: "office", label: "Офис" },
  { value: "commercial", label: "Търговски обект" },
  { value: "industrial", label: "Производство" },
  { value: "public", label: "Обществена сграда" },
  { value: "other", label: "Друго" },
];

export default function ProjectInfoPanel({ projectId, project, onUpdated }) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);

  // Form state
  const [addr, setAddr] = useState(project?.structured_address || {});
  const [contacts, setContacts] = useState(project?.contacts || { owner: {}, responsible: {}, additional: [] });
  const [invoice, setInvoice] = useState(project?.invoice_details || {});
  const [objType, setObjType] = useState(project?.object_type || "");
  const [objDetails, setObjDetails] = useState(project?.object_details || {});

  useEffect(() => {
    setAddr(project?.structured_address || {});
    setContacts(project?.contacts || { owner: {}, responsible: {}, additional: [] });
    setInvoice(project?.invoice_details || {});
    setObjType(project?.object_type || "");
    setObjDetails(project?.object_details || {});
  }, [project]);

  const setA = (k, v) => setAddr(p => ({ ...p, [k]: v }));
  const setOwner = (k, v) => setContacts(p => ({ ...p, owner: { ...p.owner, [k]: v } }));
  const setResp = (k, v) => setContacts(p => ({ ...p, responsible: { ...p.responsible, [k]: v } }));
  const setInv = (k, v) => setInvoice(p => ({ ...p, [k]: v }));
  const setObj = (k, v) => setObjDetails(p => ({ ...p, [k]: v }));

  const addContact = () => setContacts(p => ({ ...p, additional: [...(p.additional || []), { name: "", phone: "", role: "", notes: "" }] }));
  const removeContact = (i) => setContacts(p => ({ ...p, additional: (p.additional || []).filter((_, idx) => idx !== i) }));
  const setExtraContact = (i, k, v) => setContacts(p => {
    const arr = [...(p.additional || [])];
    arr[i] = { ...arr[i], [k]: v };
    return { ...p, additional: arr };
  });

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await API.put(`/projects/${projectId}`, {
        structured_address: addr,
        contacts,
        invoice_details: invoice,
        object_type: objType || null,
        object_details: objDetails,
      });
      onUpdated?.(res.data);
      toast.success(t("projectDetails.saved"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setSaving(false); }
  };

  const handleImportInvoice = async () => {
    setImporting(true);
    try {
      const res = await API.post(`/projects/${projectId}/import-client-invoice`);
      setInvoice(res.data.invoice_details);
      toast.success(t("projectDetails.invoiceImported"));
    } catch (err) { toast.error(err.response?.data?.detail || t("common.error")); }
    finally { setImporting(false); }
  };

  return (
    <div className="space-y-6" data-testid="project-info-panel">
      {/* Address */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <MapPin className="w-4 h-4 text-blue-400" />
          <span className="font-semibold text-sm">{t("projectDetails.address")}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.city")}</Label><Input value={addr.city || ""} onChange={e => setA("city", e.target.value)} placeholder="София" data-testid="addr-city" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.district")}</Label><Input value={addr.district || ""} onChange={e => setA("district", e.target.value)} placeholder="Лозенец" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.street")}</Label><Input value={addr.street || ""} onChange={e => setA("street", e.target.value)} placeholder="ул. Цар Борис" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.block")}</Label><Input value={addr.block || ""} onChange={e => setA("block", e.target.value)} placeholder="15" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.entrance")}</Label><Input value={addr.entrance || ""} onChange={e => setA("entrance", e.target.value)} placeholder="А" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.floor")}</Label><Input value={addr.floor || ""} onChange={e => setA("floor", e.target.value)} placeholder="3" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.apartment")}</Label><Input value={addr.apartment || ""} onChange={e => setA("apartment", e.target.value)} placeholder="12" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.postalCode")}</Label><Input value={addr.postal_code || ""} onChange={e => setA("postal_code", e.target.value)} placeholder="1000" /></div>
        </div>
        <div className="mt-2 space-y-1"><Label className="text-xs">{t("projectDetails.accessNotes")}</Label><Input value={addr.notes || ""} onChange={e => setA("notes", e.target.value)} placeholder={t("projectDetails.accessNotesPlaceholder")} /></div>
      </div>

      {/* Contacts */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <User className="w-4 h-4 text-emerald-400" />
          <span className="font-semibold text-sm">{t("projectDetails.contacts")}</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2 p-3 rounded-lg bg-muted/10 border border-border">
            <p className="text-xs font-medium text-muted-foreground">{t("projectDetails.owner")}</p>
            <Input value={contacts.owner?.name || ""} onChange={e => setOwner("name", e.target.value)} placeholder={t("common.name")} data-testid="owner-name" />
            <div className="grid grid-cols-2 gap-2">
              <Input value={contacts.owner?.phone || ""} onChange={e => setOwner("phone", e.target.value)} placeholder={t("projectDetails.phone")} />
              <Input value={contacts.owner?.email || ""} onChange={e => setOwner("email", e.target.value)} placeholder={t("common.email")} />
            </div>
          </div>
          <div className="space-y-2 p-3 rounded-lg bg-muted/10 border border-border">
            <p className="text-xs font-medium text-muted-foreground">{t("projectDetails.responsible")}</p>
            <Input value={contacts.responsible?.name || ""} onChange={e => setResp("name", e.target.value)} placeholder={t("common.name")} data-testid="responsible-name" />
            <div className="grid grid-cols-2 gap-2">
              <Input value={contacts.responsible?.phone || ""} onChange={e => setResp("phone", e.target.value)} placeholder={t("projectDetails.phone")} />
              <Input value={contacts.responsible?.position || ""} onChange={e => setResp("position", e.target.value)} placeholder={t("projectDetails.position")} />
            </div>
          </div>
        </div>
        {/* Additional contacts */}
        {(contacts.additional || []).map((c, i) => (
          <div key={i} className="flex gap-2 mt-2 items-end">
            <Input value={c.name} onChange={e => setExtraContact(i, "name", e.target.value)} placeholder={t("common.name")} className="flex-1" />
            <Input value={c.phone} onChange={e => setExtraContact(i, "phone", e.target.value)} placeholder={t("projectDetails.phone")} className="w-32" />
            <Input value={c.role} onChange={e => setExtraContact(i, "role", e.target.value)} placeholder={t("projectDetails.role")} className="w-28" />
            <Button variant="ghost" size="sm" onClick={() => removeContact(i)}><Trash2 className="w-3.5 h-3.5 text-red-400" /></Button>
          </div>
        ))}
        <Button variant="outline" size="sm" onClick={addContact} className="mt-2"><Plus className="w-3.5 h-3.5 mr-1" />{t("projectDetails.addContact")}</Button>
      </div>

      {/* Invoice Details */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-amber-400" />
            <span className="font-semibold text-sm">{t("projectDetails.invoiceDetails")}</span>
          </div>
          {project?.owner_id && (
            <Button variant="outline" size="sm" onClick={handleImportInvoice} disabled={importing} data-testid="import-invoice-btn">
              {importing ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-1" />}
              {t("projectDetails.importFromClient")}
            </Button>
          )}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.companyName")}</Label><Input value={invoice.company_name || ""} onChange={e => setInv("company_name", e.target.value)} data-testid="invoice-company" /></div>
          <div className="space-y-1"><Label className="text-xs">ЕИК</Label><Input value={invoice.eik || ""} onChange={e => setInv("eik", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">МОЛ</Label><Input value={invoice.mol || ""} onChange={e => setInv("mol", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.vatNumber")}</Label><Input value={invoice.vat_number || ""} onChange={e => setInv("vat_number", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">IBAN</Label><Input value={invoice.iban || ""} onChange={e => setInv("iban", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.bankName")}</Label><Input value={invoice.bank_name || ""} onChange={e => setInv("bank_name", e.target.value)} /></div>
        </div>
        <div className="mt-2 space-y-1"><Label className="text-xs">{t("projectDetails.regAddress")}</Label><Input value={invoice.registered_address || ""} onChange={e => setInv("registered_address", e.target.value)} /></div>
        <div className="flex items-center gap-2 mt-2">
          <Checkbox checked={invoice.is_vat_registered || false} onCheckedChange={v => setInv("is_vat_registered", v)} data-testid="vat-checkbox" />
          <Label className="text-xs">{t("projectDetails.vatRegistered")}</Label>
        </div>
      </div>

      {/* Object Details */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Home className="w-4 h-4 text-purple-400" />
          <span className="font-semibold text-sm">{t("projectDetails.objectInfo")}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="space-y-1">
            <Label className="text-xs">{t("projectDetails.objectType")}</Label>
            <Select value={objType || "none"} onValueChange={v => setObjType(v === "none" ? "" : v)}>
              <SelectTrigger data-testid="object-type-select"><SelectValue placeholder="-" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">-</SelectItem>
                {OBJ_TYPES.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.area")}</Label><Input type="number" value={objDetails.total_area_m2 || ""} onChange={e => setObj("total_area_m2", parseFloat(e.target.value) || null)} placeholder="м2" /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.rooms")}</Label><Input type="number" value={objDetails.rooms_count || ""} onChange={e => setObj("rooms_count", parseInt(e.target.value) || null)} /></div>
          <div className="space-y-1"><Label className="text-xs">{t("projectDetails.floors")}</Label><Input type="number" value={objDetails.floors_count || ""} onChange={e => setObj("floors_count", parseInt(e.target.value) || null)} /></div>
        </div>
        <div className="flex flex-wrap gap-4 mt-3">
          <div className="flex items-center gap-2"><Checkbox checked={objDetails.is_inhabited || false} onCheckedChange={v => setObj("is_inhabited", v)} /><Label className="text-xs">{t("projectDetails.inhabited")}</Label></div>
          <div className="flex items-center gap-2"><Checkbox checked={objDetails.parking_available || false} onCheckedChange={v => setObj("parking_available", v)} /><Label className="text-xs">{t("projectDetails.parking")}</Label></div>
          <div className="flex items-center gap-2"><Checkbox checked={objDetails.elevator_available || false} onCheckedChange={v => setObj("elevator_available", v)} /><Label className="text-xs">{t("projectDetails.elevator")}</Label></div>
        </div>
        <div className="mt-2 space-y-1"><Label className="text-xs">{t("projectDetails.accessNotes")}</Label><Input value={objDetails.access_notes || ""} onChange={e => setObj("access_notes", e.target.value)} placeholder={t("projectDetails.accessNotesPlaceholder")} /></div>
      </div>

      {/* Save */}
      <Button onClick={handleSave} disabled={saving} className="w-full" data-testid="save-info-btn">
        {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
        {t("common.save")}
      </Button>
    </div>
  );
}
