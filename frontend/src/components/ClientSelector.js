import { useState } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  Building2,
  User,
  Phone,
  Hash,
  Search,
  Loader2,
  CheckCircle,
  Plus,
  Mail,
} from "lucide-react";

export default function ClientSelector({ projectId, currentClient, onClientUpdated, open, onOpenChange }) {
  const [clientType, setClientType] = useState(currentClient?.owner_type || "person");
  const [searchValue, setSearchValue] = useState("");
  const [searching, setSearching] = useState(false);
  const [foundClient, setFoundClient] = useState(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [saving, setSaving] = useState(false);

  // New client form data
  const [newPerson, setNewPerson] = useState({ firstName: "", lastName: "", email: "" });
  const [newCompany, setNewCompany] = useState({ name: "", vatNumber: "", phone: "", email: "", addressText: "", contactPerson: "" });

  const resetState = () => {
    setSearchValue("");
    setFoundClient(null);
    setShowCreateForm(false);
    setNewPerson({ firstName: "", lastName: "", email: "" });
    setNewCompany({ name: "", vatNumber: "", phone: "", email: "", addressText: "", contactPerson: "" });
  };

  const handleTypeChange = (type) => {
    setClientType(type);
    resetState();
  };

  const handleSearch = async () => {
    if (!searchValue.trim()) return;
    
    setSearching(true);
    setFoundClient(null);
    setShowCreateForm(false);

    try {
      const endpoint = clientType === "person"
        ? `/persons/find-by-phone?phone=${encodeURIComponent(searchValue)}`
        : `/companies/find-by-eik?eik=${encodeURIComponent(searchValue)}`;

      const res = await API.get(endpoint);
      
      if (res.data.found) {
        setFoundClient(res.data.person || res.data.company);
        toast.success("Клиентът е намерен!");
      } else {
        setShowCreateForm(true);
        toast.info("Не е намерен. Можете да създадете нов.");
      }
    } catch (err) {
      toast.error("Грешка при търсене");
    } finally {
      setSearching(false);
    }
  };

  const handleCreateClient = async () => {
    setSaving(true);
    try {
      let newClient;
      
      if (clientType === "person") {
        if (!newPerson.firstName || !newPerson.lastName) {
          toast.error("Въведете име и фамилия");
          setSaving(false);
          return;
        }
        const res = await API.post("/persons", {
          phone: searchValue,
          first_name: newPerson.firstName,
          last_name: newPerson.lastName,
          email: newPerson.email || null,
        });
        newClient = res.data;
      } else {
        if (!newCompany.name) {
          toast.error("Въведете име на фирмата");
          setSaving(false);
          return;
        }
        const res = await API.post("/companies", {
          eik: searchValue,
          name: newCompany.name,
          phone: newCompany.phone || null,
          email: newCompany.email || null,
          address: newCompany.addressText || null,
          mol: newCompany.contactPerson || null,
        });
        newClient = res.data;
      }

      setFoundClient(newClient);
      setShowCreateForm(false);
      toast.success("Клиентът е създаден!");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка при създаване");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveToProject = async () => {
    if (!foundClient) return;
    
    setSaving(true);
    try {
      await API.put(`/projects/${projectId}`, {
        owner_type: clientType,
        owner_id: foundClient.id,
      });
      
      toast.success("Клиентът е свързан с проекта!");
      onClientUpdated?.();
      onOpenChange(false);
    } catch (err) {
      toast.error("Грешка при запазване");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-gray-900 border-gray-700 text-white max-w-md">
        <DialogHeader>
          <DialogTitle>Избери клиент</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Client Type Selection */}
          <div className="space-y-2">
            <Label>Тип клиент</Label>
            <Select value={clientType} onValueChange={handleTypeChange}>
              <SelectTrigger className="bg-gray-800 border-gray-700">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-gray-800 border-gray-700">
                <SelectItem value="person">
                  <span className="flex items-center gap-2">
                    <User className="w-4 h-4" /> Частно лице
                  </span>
                </SelectItem>
                <SelectItem value="company">
                  <span className="flex items-center gap-2">
                    <Building2 className="w-4 h-4" /> Фирма
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Search Field */}
          <div className="space-y-2">
            <Label>{clientType === "person" ? "Телефон" : "ЕИК"}</Label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                {clientType === "person" ? (
                  <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                ) : (
                  <Hash className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                )}
                <Input
                  value={searchValue}
                  onChange={(e) => setSearchValue(e.target.value)}
                  placeholder={clientType === "person" ? "0888123456" : "123456789"}
                  className="bg-gray-800 border-gray-700 pl-10"
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                />
              </div>
              <Button
                onClick={handleSearch}
                disabled={searching || !searchValue.trim()}
                className="bg-yellow-500 hover:bg-yellow-600 text-black"
              >
                {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              </Button>
            </div>
          </div>

          {/* Found Client Display */}
          {foundClient && (
            <div className="p-4 bg-green-900/20 border border-green-700/30 rounded-lg space-y-2">
              <div className="flex items-center gap-2 text-green-400">
                <CheckCircle className="w-5 h-5" />
                <span className="font-medium">Намерен клиент</span>
              </div>
              
              {clientType === "person" ? (
                <div className="text-sm space-y-1">
                  <p className="text-white font-medium">{foundClient.first_name} {foundClient.last_name}</p>
                  <p className="text-gray-400 flex items-center gap-1">
                    <Phone className="w-3 h-3" /> {foundClient.phone}
                  </p>
                  {foundClient.email && (
                    <p className="text-gray-400 flex items-center gap-1">
                      <Mail className="w-3 h-3" /> {foundClient.email}
                    </p>
                  )}
                </div>
              ) : (
                <div className="text-sm space-y-1">
                  <p className="text-white font-medium">{foundClient.name}</p>
                  <p className="text-gray-400 flex items-center gap-1">
                    <Hash className="w-3 h-3" /> ЕИК: {foundClient.eik}
                  </p>
                  {foundClient.phone && (
                    <p className="text-gray-400 flex items-center gap-1">
                      <Phone className="w-3 h-3" /> {foundClient.phone}
                    </p>
                  )}
                </div>
              )}

              <Button
                onClick={handleSaveToProject}
                disabled={saving}
                className="w-full mt-3 bg-green-600 hover:bg-green-700"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
                Запази към проекта
              </Button>
            </div>
          )}

          {/* Create New Client Form */}
          {showCreateForm && (
            <div className="p-4 bg-gray-800/50 border border-gray-700 rounded-lg space-y-3">
              <div className="flex items-center gap-2 text-yellow-400">
                <Plus className="w-4 h-4" />
                <span className="text-sm font-medium">Създай нов клиент</span>
              </div>

              {clientType === "person" ? (
                <>
                  <p className="text-xs text-gray-400">Телефон: {searchValue}</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-xs">Име *</Label>
                      <Input
                        value={newPerson.firstName}
                        onChange={(e) => setNewPerson({ ...newPerson, firstName: e.target.value })}
                        placeholder="Иван"
                        className="bg-gray-700 border-gray-600 h-9"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Фамилия *</Label>
                      <Input
                        value={newPerson.lastName}
                        onChange={(e) => setNewPerson({ ...newPerson, lastName: e.target.value })}
                        placeholder="Петров"
                        className="bg-gray-700 border-gray-600 h-9"
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Имейл (незадължително)</Label>
                    <Input
                      value={newPerson.email}
                      onChange={(e) => setNewPerson({ ...newPerson, email: e.target.value })}
                      placeholder="email@example.com"
                      className="bg-gray-700 border-gray-600 h-9"
                    />
                  </div>
                </>
              ) : (
                <>
                  <p className="text-xs text-gray-400">ЕИК: {searchValue}</p>
                  <div className="space-y-1">
                    <Label className="text-xs">Име на фирмата *</Label>
                    <Input
                      value={newCompany.name}
                      onChange={(e) => setNewCompany({ ...newCompany, name: e.target.value })}
                      placeholder="Фирма ЕООД"
                      className="bg-gray-700 border-gray-600 h-9"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-xs">Телефон</Label>
                      <Input
                        value={newCompany.phone}
                        onChange={(e) => setNewCompany({ ...newCompany, phone: e.target.value })}
                        placeholder="0888..."
                        className="bg-gray-700 border-gray-600 h-9"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Имейл</Label>
                      <Input
                        value={newCompany.email}
                        onChange={(e) => setNewCompany({ ...newCompany, email: e.target.value })}
                        placeholder="email@..."
                        className="bg-gray-700 border-gray-600 h-9"
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">МОЛ / Контакт</Label>
                    <Input
                      value={newCompany.contactPerson}
                      onChange={(e) => setNewCompany({ ...newCompany, contactPerson: e.target.value })}
                      placeholder="Име на лице за контакт"
                      className="bg-gray-700 border-gray-600 h-9"
                    />
                  </div>
                </>
              )}

              <Button
                onClick={handleCreateClient}
                disabled={saving}
                className="w-full bg-yellow-500 hover:bg-yellow-600 text-black"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Plus className="w-4 h-4 mr-2" />}
                Създай и запази към проекта
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
