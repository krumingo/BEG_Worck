import { useState, useEffect } from "react";
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
  Loader2,
  Package,
  Building2,
  User,
  Car,
  AlertTriangle,
} from "lucide-react";

const WAREHOUSE_TYPES = [
  { value: "central", label: "Централен склад", icon: Package },
  { value: "project", label: "Склад на проект", icon: Building2 },
  { value: "person", label: "Склад на човек", icon: User },
  { value: "vehicle", label: "Склад в превозно средство", icon: Car },
];

export default function CreateWarehouseModal({
  open,
  onOpenChange,
  onCreated,
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("central");
  const [projectId, setProjectId] = useState("");
  const [personId, setPersonId] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  
  const [projects, setProjects] = useState([]);
  const [persons, setPersons] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      fetchData();
      resetForm();
    }
  }, [open]);

  const resetForm = () => {
    setCode("");
    setName("");
    setType("central");
    setProjectId("");
    setPersonId("");
    setVehicleId("");
    setError(null);
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectsRes, personsRes] = await Promise.all([
        API.get("/projects"),
        API.get("/persons"),
      ]);
      setProjects(projectsRes.data || []);
      setPersons(personsRes.data || []);
    } catch (err) {
      console.error("Failed to load data:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    // Validate
    if (!code.trim()) {
      setError("Кодът е задължителен");
      return;
    }
    if (!name.trim()) {
      setError("Името е задължително");
      return;
    }
    if (type === "project" && !projectId) {
      setError("Изберете проект");
      return;
    }
    if (type === "person" && !personId) {
      setError("Изберете човек");
      return;
    }

    setSaving(true);
    setError(null);
    
    try {
      const payload = {
        code: code.trim().toUpperCase(),
        name: name.trim(),
        type,
        project_id: type === "project" ? projectId : null,
        person_id: type === "person" ? personId : null,
        vehicle_id: type === "vehicle" ? vehicleId || null : null,
      };
      
      const res = await API.post("/warehouses", payload);
      
      // Call onCreated with the new warehouse
      if (onCreated) {
        onCreated(res.data);
      }
      
      onOpenChange(false);
    } catch (err) {
      const detail = err.response?.data?.detail || "Грешка при създаване";
      if (detail.includes("already exists") || detail.includes("вече съществува")) {
        setError("Този код вече съществува. Изберете друг.");
      } else {
        setError(detail);
      }
    } finally {
      setSaving(false);
    }
  };

  const getTypeIcon = (typeValue) => {
    const typeObj = WAREHOUSE_TYPES.find(t => t.value === typeValue);
    if (typeObj) {
      const Icon = typeObj.icon;
      return <Icon className="w-4 h-4" />;
    }
    return <Package className="w-4 h-4" />;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md bg-gray-900 border-gray-800">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-white flex items-center gap-2">
            <Package className="w-5 h-5 text-purple-400" />
            Създай нов склад
          </DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-yellow-500" />
          </div>
        ) : (
          <div className="space-y-4 py-2">
            {/* Code */}
            <div className="space-y-2">
              <Label className="text-gray-300">Код *</Label>
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="WH-001"
                className="bg-gray-800 border-gray-700"
                maxLength={20}
              />
              <p className="text-xs text-gray-500">Уникален код за склада (автоматично главни букви)</p>
            </div>

            {/* Name */}
            <div className="space-y-2">
              <Label className="text-gray-300">Име *</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Централен склад София"
                className="bg-gray-800 border-gray-700"
              />
            </div>

            {/* Type */}
            <div className="space-y-2">
              <Label className="text-gray-300">Тип</Label>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger className="bg-gray-800 border-gray-700">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WAREHOUSE_TYPES.map(t => (
                    <SelectItem key={t.value} value={t.value}>
                      <div className="flex items-center gap-2">
                        <t.icon className="w-4 h-4" />
                        {t.label}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Conditional: Project */}
            {type === "project" && (
              <div className="space-y-2">
                <Label className="text-gray-300">Проект *</Label>
                <Select value={projectId} onValueChange={setProjectId}>
                  <SelectTrigger className="bg-gray-800 border-gray-700">
                    <SelectValue placeholder="Изберете проект..." />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map(p => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.code} - {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Conditional: Person */}
            {type === "person" && (
              <div className="space-y-2">
                <Label className="text-gray-300">Човек *</Label>
                <Select value={personId} onValueChange={setPersonId}>
                  <SelectTrigger className="bg-gray-800 border-gray-700">
                    <SelectValue placeholder="Изберете човек..." />
                  </SelectTrigger>
                  <SelectContent>
                    {persons.map(p => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.first_name} {p.last_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Conditional: Vehicle */}
            {type === "vehicle" && (
              <div className="space-y-2">
                <Label className="text-gray-300">Превозно средство</Label>
                <Input
                  value={vehicleId}
                  onChange={(e) => setVehicleId(e.target.value)}
                  placeholder="Регистрационен номер или ID"
                  className="bg-gray-800 border-gray-700"
                />
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-3 flex items-center gap-2 text-red-400">
                <AlertTriangle className="w-5 h-5 flex-shrink-0" />
                <span className="text-sm">{error}</span>
              </div>
            )}
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
            className="border-gray-700"
          >
            Отказ
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || loading}
            className="bg-purple-600 hover:bg-purple-700"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Създаване...
              </>
            ) : (
              <>
                <Package className="w-4 h-4 mr-2" />
                Създай склад
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
