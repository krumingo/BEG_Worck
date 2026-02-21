import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ArrowLeft,
  Loader2,
  Check,
  AlertTriangle,
  Package,
  Users,
  Building2,
  User,
  SplitSquareVertical,
} from "lucide-react";
import AllocationModal from "@/components/AllocationModal";

export default function InvoiceLinesPage() {
  const { t } = useTranslation();
  const { invoiceId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [invoice, setInvoice] = useState(null);
  const [lines, setLines] = useState([]);
  const [users, setUsers] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Selection
  const [selectedLines, setSelectedLines] = useState(new Set());
  
  // Modal
  const [allocationModalOpen, setAllocationModalOpen] = useState(false);
  const [selectedLine, setSelectedLine] = useState(null);

  // Bulk actions
  const [bulkPurchaser, setBulkPurchaser] = useState("");
  const [bulkWarehouse, setBulkWarehouse] = useState("");
  const [bulkProcessing, setBulkProcessing] = useState(false);

  const canManage = ["Admin", "Owner", "Accountant"].includes(user?.role);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [invoiceRes, linesRes, usersRes, warehousesRes] = await Promise.all([
        API.get(`/finance/invoices/${invoiceId}`),
        API.get(`/invoice-lines?invoice_id=${invoiceId}`),
        API.get("/users"),
        API.get("/warehouses"),
      ]);
      setInvoice(invoiceRes.data);
      setLines(linesRes.data || []);
      setUsers(usersRes.data || []);
      setWarehouses(warehousesRes.data || []);
    } catch (err) {
      console.error(err);
      setError("Грешка при зареждане на данни");
    } finally {
      setLoading(false);
    }
  }, [invoiceId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openAllocationModal = (line) => {
    setSelectedLine(line);
    setAllocationModalOpen(true);
  };

  const handleAllocationSaved = () => {
    fetchData();
  };

  const toggleLineSelection = (lineId) => {
    const newSelection = new Set(selectedLines);
    if (newSelection.has(lineId)) {
      newSelection.delete(lineId);
    } else {
      newSelection.add(lineId);
    }
    setSelectedLines(newSelection);
  };

  const toggleAllSelection = () => {
    if (selectedLines.size === lines.length) {
      setSelectedLines(new Set());
    } else {
      setSelectedLines(new Set(lines.map(l => l.id)));
    }
  };

  const handleBulkSetPurchaser = async () => {
    if (!bulkPurchaser || selectedLines.size === 0) return;
    setBulkProcessing(true);
    try {
      for (const lineId of selectedLines) {
        await API.put(`/invoice-lines/${lineId}`, {
          purchased_by_user_id: bulkPurchaser,
        });
      }
      await fetchData();
      setSelectedLines(new Set());
      setBulkPurchaser("");
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при обновяване");
    } finally {
      setBulkProcessing(false);
    }
  };

  const handleBulkAllocateToWarehouse = async () => {
    if (!bulkWarehouse || selectedLines.size === 0) return;
    setBulkProcessing(true);
    try {
      for (const lineId of selectedLines) {
        const line = lines.find(l => l.id === lineId);
        if (!line) continue;
        
        const remaining = (line.qty || 0) - (line.qty_allocated || 0);
        if (remaining <= 0) continue;
        
        // Add remaining qty to warehouse
        const existingAllocations = line.allocations || [];
        const newAllocations = [
          ...existingAllocations,
          {
            type: "warehouse",
            ref_id: bulkWarehouse,
            qty: remaining,
            note: "Bulk остатък",
          },
        ];
        
        await API.post(`/invoice-lines/${lineId}/allocate`, {
          allocations: newAllocations,
        });
      }
      await fetchData();
      setSelectedLines(new Set());
      setBulkWarehouse("");
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка при разпределяне");
    } finally {
      setBulkProcessing(false);
    }
  };

  const renderAllocationSummary = (line) => {
    const allocations = line.allocations || [];
    if (allocations.length === 0) {
      return <span className="text-gray-500 text-sm">—</span>;
    }
    
    return (
      <div className="flex flex-wrap gap-1">
        {allocations.map((a, idx) => {
          let icon, color, prefix;
          switch (a.type) {
            case "project":
              icon = <Building2 className="w-3 h-3" />;
              color = "bg-blue-500/20 text-blue-400 border-blue-500/30";
              prefix = "P:";
              break;
            case "warehouse":
              icon = <Package className="w-3 h-3" />;
              color = "bg-purple-500/20 text-purple-400 border-purple-500/30";
              prefix = "W:";
              break;
            case "client":
              icon = <User className="w-3 h-3" />;
              color = "bg-green-500/20 text-green-400 border-green-500/30";
              prefix = "C:";
              break;
            default:
              color = "bg-gray-500/20 text-gray-400 border-gray-500/30";
              prefix = "";
          }
          
          const refName = a.ref_name?.split(" - ")[0] || a.ref_id?.substring(0, 8);
          
          return (
            <Badge 
              key={idx} 
              variant="outline" 
              className={`${color} text-xs px-1.5 py-0.5`}
            >
              {icon}
              <span className="ml-1">{refName}: {a.qty}</span>
            </Badge>
          );
        })}
      </div>
    );
  };

  const getPurchaserName = (userId) => {
    const u = users.find(u => u.id === userId);
    return u ? `${u.first_name} ${u.last_name}` : "—";
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-8 h-8 animate-spin text-yellow-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center text-red-400">
        {error}
      </div>
    );
  }

  const unallocatedCount = lines.filter(l => !l.is_fully_allocated).length;

  return (
    <div className="p-4 md:p-6 space-y-6" data-testid="invoice-lines-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/finance/invoices/${invoiceId}`)}
            className="text-gray-400 hover:text-white"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Назад
          </Button>
          <div>
            <h1 className="text-xl font-semibold text-white">
              Редове на фактура {invoice?.invoice_no}
            </h1>
            <p className="text-sm text-gray-400">
              Разпределение на количества по проекти, складове и клиенти
            </p>
          </div>
        </div>
        {unallocatedCount > 0 && (
          <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30">
            <AlertTriangle className="w-4 h-4 mr-1" />
            {unallocatedCount} неразпределени
          </Badge>
        )}
      </div>

      {/* Bulk Actions */}
      {selectedLines.size > 0 && canManage && (
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="flex flex-wrap items-center gap-4">
            <span className="text-sm text-gray-400">
              Избрани: {selectedLines.size} реда
            </span>
            
            {/* Bulk Set Purchaser */}
            <div className="flex items-center gap-2">
              <Select value={bulkPurchaser} onValueChange={setBulkPurchaser}>
                <SelectTrigger className="w-48 bg-gray-800 border-gray-700">
                  <SelectValue placeholder="Изберете купувач..." />
                </SelectTrigger>
                <SelectContent>
                  {users.map(u => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.first_name} {u.last_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                onClick={handleBulkSetPurchaser}
                disabled={!bulkPurchaser || bulkProcessing}
                className="bg-blue-600 hover:bg-blue-700"
              >
                <Users className="w-4 h-4 mr-1" />
                Задай купувач
              </Button>
            </div>

            {/* Bulk Allocate to Warehouse */}
            <div className="flex items-center gap-2">
              <Select value={bulkWarehouse} onValueChange={setBulkWarehouse}>
                <SelectTrigger className="w-48 bg-gray-800 border-gray-700">
                  <SelectValue placeholder="Изберете склад..." />
                </SelectTrigger>
                <SelectContent>
                  {warehouses.map(w => (
                    <SelectItem key={w.id} value={w.id}>
                      {w.code} - {w.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                onClick={handleBulkAllocateToWarehouse}
                disabled={!bulkWarehouse || bulkProcessing}
                className="bg-purple-600 hover:bg-purple-700"
              >
                <Package className="w-4 h-4 mr-1" />
                Остатък към склад
              </Button>
            </div>

            {bulkProcessing && (
              <Loader2 className="w-5 h-5 animate-spin text-yellow-500" />
            )}
          </div>
        </div>
      )}

      {/* Lines Table */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-lg overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-gray-800 hover:bg-gray-800/50">
              {canManage && (
                <TableHead className="w-10">
                  <Checkbox
                    checked={selectedLines.size === lines.length && lines.length > 0}
                    onCheckedChange={toggleAllSelection}
                  />
                </TableHead>
              )}
              <TableHead className="text-gray-400">Описание</TableHead>
              <TableHead className="text-gray-400 text-right w-24">Закупено</TableHead>
              <TableHead className="text-gray-400 text-right w-24">Разпределено</TableHead>
              <TableHead className="text-gray-400 text-right w-24">Остатък</TableHead>
              <TableHead className="text-gray-400 w-36">Купувач</TableHead>
              <TableHead className="text-gray-400">Разпределения</TableHead>
              <TableHead className="text-gray-400 w-28">Действия</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {lines.length === 0 ? (
              <TableRow>
                <TableCell 
                  colSpan={canManage ? 8 : 7} 
                  className="text-center py-12 text-gray-500"
                >
                  Няма редове в тази фактура
                </TableCell>
              </TableRow>
            ) : (
              lines.map((line) => {
                const isFullyAllocated = line.is_fully_allocated;
                const remaining = line.qty_unallocated || 0;
                
                return (
                  <TableRow 
                    key={line.id}
                    className={`border-gray-800 hover:bg-gray-800/30 ${
                      !isFullyAllocated ? "bg-amber-900/5" : ""
                    }`}
                  >
                    {canManage && (
                      <TableCell>
                        <Checkbox
                          checked={selectedLines.has(line.id)}
                          onCheckedChange={() => toggleLineSelection(line.id)}
                        />
                      </TableCell>
                    )}
                    <TableCell>
                      <div className="font-medium text-white">{line.description}</div>
                      {line.unit && (
                        <div className="text-xs text-gray-500">
                          Единица: {line.unit} | Цена: {formatCurrency(line.unit_price || 0, "BGN")}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-medium text-white">
                      {line.qty || 0}
                    </TableCell>
                    <TableCell className="text-right">
                      <span className={isFullyAllocated ? "text-emerald-400" : "text-yellow-400"}>
                        {(line.qty_allocated || 0).toFixed(2)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      {remaining > 0 ? (
                        <span className="text-amber-400 font-medium">
                          {remaining.toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-emerald-400 flex items-center justify-end gap-1">
                          <Check className="w-4 h-4" /> OK
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      {line.purchased_by_user_id ? (
                        <span className="text-gray-300 text-sm">
                          {getPurchaserName(line.purchased_by_user_id)}
                        </span>
                      ) : (
                        <span className="text-gray-500 text-sm">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {renderAllocationSummary(line)}
                    </TableCell>
                    <TableCell>
                      {canManage && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openAllocationModal(line)}
                          className={`border-gray-700 hover:bg-gray-800 ${
                            !isFullyAllocated ? "border-amber-500/50 text-amber-400" : ""
                          }`}
                        >
                          <SplitSquareVertical className="w-4 h-4 mr-1" />
                          Разпредели
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Summary */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
        <div className="grid grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Общо редове:</span>{" "}
            <span className="text-white font-medium">{lines.length}</span>
          </div>
          <div>
            <span className="text-gray-500">Напълно разпределени:</span>{" "}
            <span className="text-emerald-400 font-medium">
              {lines.filter(l => l.is_fully_allocated).length}
            </span>
          </div>
          <div>
            <span className="text-gray-500">Частично разпределени:</span>{" "}
            <span className="text-amber-400 font-medium">
              {unallocatedCount}
            </span>
          </div>
          <div>
            <span className="text-gray-500">Обща стойност:</span>{" "}
            <span className="text-white font-medium">
              {formatCurrency(invoice?.total || 0, invoice?.currency || "BGN")}
            </span>
          </div>
        </div>
      </div>

      {/* Allocation Modal */}
      <AllocationModal
        open={allocationModalOpen}
        onOpenChange={setAllocationModalOpen}
        line={selectedLine}
        onSave={handleAllocationSaved}
        requireFullAllocation={false}
      />
    </div>
  );
}
