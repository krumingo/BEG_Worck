import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Plus,
  Trash2,
  Loader2,
  Package,
  Building2,
  User,
  AlertTriangle,
  Check,
} from "lucide-react";
import CreateWarehouseModal from "./CreateWarehouseModal";

export default function AllocationModal({
  open,
  onOpenChange,
  line,
  onSave,
  requireFullAllocation = false,
}) {
  const { t } = useTranslation();
  const [allocations, setAllocations] = useState([]);
  const [projects, setProjects] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  
  // Create Warehouse Modal
  const [createWarehouseOpen, setCreateWarehouseOpen] = useState(false);
  const [pendingWarehouseAllocation, setPendingWarehouseAllocation] = useState(false);

  const qtyPurchased = line?.qty || 0;
  const qtyAllocated = allocations.reduce((sum, a) => sum + (parseFloat(a.qty) || 0), 0);
  const remaining = Math.max(0, qtyPurchased - qtyAllocated);
  const isFullyAllocated = remaining < 0.0001;

  useEffect(() => {
    if (open && line) {
      fetchData();
    }
  }, [open, line]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectsRes, warehousesRes, personsRes] = await Promise.all([
        API.get("/projects"),
        API.get("/warehouses"),
        API.get("/persons"),
      ]);
      setProjects(projectsRes.data || []);
      setWarehouses(warehousesRes.data || []);
      setClients(personsRes.data || []);
      
      // Initialize with existing allocations
      if (line?.allocations && line.allocations.length > 0) {
        setAllocations(line.allocations.map(a => ({
          type: a.type,
          ref_id: a.ref_id,
          qty: a.qty,
          note: a.note || "",
        })));
      } else {
        setAllocations([]);
      }
    } catch (err) {
      console.error("Failed to load data:", err);
      setError("Неуспешно зареждане на данни");
    } finally {
      setLoading(false);
    }
  };

  const addRow = () => {
    setAllocations([...allocations, {
      type: "project",
      ref_id: "",
      qty: 0,
      note: "",
    }]);
  };

  const removeRow = (idx) => {
    setAllocations(allocations.filter((_, i) => i !== idx));
  };

  const updateRow = (idx, field, value) => {
    const updated = [...allocations];
    updated[idx] = { ...updated[idx], [field]: value };
    // Reset ref_id when type changes
    if (field === "type") {
      updated[idx].ref_id = "";
    }
    setAllocations(updated);
  };

  const addRemainingToWarehouse = (warehouseId) => {
    if (remaining <= 0) return;
    setAllocations([...allocations, {
      type: "warehouse",
      ref_id: warehouseId,
      qty: remaining,
      note: "Остатък",
    }]);
  };

  const handleCreateWarehouse = () => {
    setPendingWarehouseAllocation(true);
    setCreateWarehouseOpen(true);
  };

  const handleWarehouseCreated = (newWarehouse) => {
    // Add to local warehouses list
    setWarehouses(prev => [...prev, newWarehouse]);
    
    // If we were pending allocation, add the remaining to new warehouse
    if (pendingWarehouseAllocation && remaining > 0) {
      setAllocations(prev => [...prev, {
        type: "warehouse",
        ref_id: newWarehouse.id,
        qty: remaining,
        note: "Остатък",
      }]);
    }
    
    setPendingWarehouseAllocation(false);
  };

  const handleSave = async () => {
    // Validate
    const totalAllocated = allocations.reduce((sum, a) => sum + (parseFloat(a.qty) || 0), 0);
    
    if (totalAllocated > qtyPurchased) {
      setError(`Разпределеното количество (${totalAllocated}) надвишава закупеното (${qtyPurchased})`);
      return;
    }

    if (requireFullAllocation && Math.abs(totalAllocated - qtyPurchased) > 0.0001) {
      setError(`Изисква се пълно разпределение. Разпределено: ${totalAllocated}, Необходимо: ${qtyPurchased}`);
      return;
    }

    // Validate all allocations have ref_id
    for (const alloc of allocations) {
      if (!alloc.ref_id) {
        setError("Моля изберете обект за всяко разпределение");
        return;
      }
      if (parseFloat(alloc.qty) <= 0) {
        setError("Количеството трябва да е положително число");
        return;
      }
    }

    setSaving(true);
    setError(null);
    try {
      // Use only ref_id (snake_case)
      await API.post(`/invoice-lines/${line.id}/allocate`, {
        allocations: allocations.map(a => ({
          type: a.type,
          ref_id: a.ref_id,
          qty: parseFloat(a.qty),
          note: a.note || null,
        })),
      });
      onSave();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.detail || "Грешка при запис");
    } finally {
      setSaving(false);
    }
  };

  const getTargetOptions = (type) => {
    switch (type) {
      case "project":
        return projects.map(p => ({ id: p.id, label: `${p.code} - ${p.name}` }));
      case "warehouse":
        return warehouses.map(w => ({ id: w.id, label: `${w.code} - ${w.name}` }));
      case "client":
        return clients.map(c => ({ id: c.id, label: `${c.first_name} ${c.last_name}` }));
      default:
        return [];
    }
  };

  const getTypeIcon = (type) => {
    switch (type) {
      case "project": return <Building2 className="w-4 h-4" />;
      case "warehouse": return <Package className="w-4 h-4" />;
      case "client": return <User className="w-4 h-4" />;
      default: return null;
    }
  };

  if (!line) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto bg-gray-900 border-gray-800">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-white">
            Разпределяне на количество
          </DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-yellow-500" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* Line Info */}
            <div className="bg-gray-800/50 rounded-lg p-4 space-y-2">
              <div className="text-sm text-gray-400">{line.description}</div>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Закупено:</span>{" "}
                  <span className="font-medium text-white">{qtyPurchased} {line.unit || "бр."}</span>
                </div>
                <div>
                  <span className="text-gray-500">Разпределено:</span>{" "}
                  <span className={`font-medium ${isFullyAllocated ? "text-emerald-400" : "text-yellow-400"}`}>
                    {qtyAllocated.toFixed(2)}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Остатък:</span>{" "}
                  <span className={`font-medium ${remaining > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                    {remaining.toFixed(2)}
                  </span>
                  {isFullyAllocated && <Check className="inline-block ml-1 w-4 h-4 text-emerald-400" />}
                </div>
              </div>
            </div>

            {/* Allocations Table */}
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <Label className="text-sm font-medium text-gray-300">Разпределения</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addRow}
                  className="border-gray-700 hover:bg-gray-800"
                >
                  <Plus className="w-4 h-4 mr-1" /> Добави ред
                </Button>
              </div>

              {allocations.length === 0 ? (
                <div className="text-center py-6 text-gray-500 border border-dashed border-gray-700 rounded-lg">
                  Няма разпределения. Кликнете "Добави ред" за да добавите.
                </div>
              ) : (
                <div className="space-y-2">
                  {allocations.map((alloc, idx) => (
                    <div 
                      key={idx} 
                      className="grid grid-cols-12 gap-2 items-center bg-gray-800/30 p-2 rounded-lg"
                    >
                      {/* Type */}
                      <div className="col-span-2">
                        <Select
                          value={alloc.type}
                          onValueChange={(v) => updateRow(idx, "type", v)}
                        >
                          <SelectTrigger className="bg-gray-800 border-gray-700">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="project">
                              <div className="flex items-center gap-2">
                                <Building2 className="w-4 h-4" /> Проект
                              </div>
                            </SelectItem>
                            <SelectItem value="warehouse">
                              <div className="flex items-center gap-2">
                                <Package className="w-4 h-4" /> Склад
                              </div>
                            </SelectItem>
                            <SelectItem value="client">
                              <div className="flex items-center gap-2">
                                <User className="w-4 h-4" /> Клиент
                              </div>
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      {/* Target */}
                      <div className="col-span-5">
                        <Select
                          value={alloc.ref_id}
                          onValueChange={(v) => updateRow(idx, "ref_id", v)}
                        >
                          <SelectTrigger className="bg-gray-800 border-gray-700">
                            <SelectValue placeholder="Изберете..." />
                          </SelectTrigger>
                          <SelectContent>
                            {getTargetOptions(alloc.type).map(opt => (
                              <SelectItem key={opt.id} value={opt.id}>
                                {opt.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      {/* Qty */}
                      <div className="col-span-2">
                        <Input
                          type="number"
                          min="0"
                          step="0.01"
                          value={alloc.qty}
                          onChange={(e) => updateRow(idx, "qty", e.target.value)}
                          className="bg-gray-800 border-gray-700"
                          placeholder="Кол."
                        />
                      </div>

                      {/* Note */}
                      <div className="col-span-2">
                        <Input
                          value={alloc.note || ""}
                          onChange={(e) => updateRow(idx, "note", e.target.value)}
                          className="bg-gray-800 border-gray-700"
                          placeholder="Бележка"
                        />
                      </div>

                      {/* Delete */}
                      <div className="col-span-1 flex justify-center">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeRow(idx)}
                          className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Quick Actions */}
            {remaining > 0 && warehouses.length > 0 && (
              <div className="border border-dashed border-gray-700 rounded-lg p-3">
                <div className="text-sm text-gray-400 mb-2">
                  Бързо действие: Добави остатъка ({remaining.toFixed(2)}) към склад:
                </div>
                <div className="flex flex-wrap gap-2">
                  {warehouses.slice(0, 5).map(wh => (
                    <Button
                      key={wh.id}
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => addRemainingToWarehouse(wh.id)}
                      className="border-gray-700 hover:bg-gray-800"
                    >
                      <Package className="w-3 h-3 mr-1" /> {wh.code}
                    </Button>
                  ))}
                </div>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-3 flex items-center gap-2 text-red-400">
                <AlertTriangle className="w-5 h-5" />
                <span className="text-sm">{error}</span>
              </div>
            )}

            {/* Full allocation warning */}
            {requireFullAllocation && !isFullyAllocated && (
              <div className="bg-amber-900/20 border border-amber-500/30 rounded-lg p-3 flex items-center gap-2 text-amber-400">
                <AlertTriangle className="w-5 h-5" />
                <span className="text-sm">Изисква се пълно разпределение на количеството</span>
              </div>
            )}
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            className="border-gray-700"
          >
            Отказ
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || loading || (requireFullAllocation && !isFullyAllocated)}
            className="bg-yellow-500 hover:bg-yellow-600 text-black"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Запис...
              </>
            ) : (
              "Запази"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
