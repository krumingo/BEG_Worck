import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  Building2,
  User,
  Phone,
  Hash,
  Search,
  Loader2,
  CheckCircle2,
  Plus,
  Mail,
  MapPin,
  ArrowLeft,
  UserCheck,
  AlertCircle,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function ClientPickerModal({ 
  projectId, 
  open, 
  onOpenChange, 
  onClientSelected 
}) {
  // Steps: 'type' | 'search' | 'create'
  const [step, setStep] = useState("type");
  const [clientType, setClientType] = useState(null);
  
  // Search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [hasSearched, setHasSearched] = useState(false);
  
  // Create form state
  const [companyForm, setCompanyForm] = useState({
    company_name: "",
    eik: "",
    vat_number: "",
    mol: "",
    address: "",
    email: "",
    phone: "",
    notes: "",
  });
  const [personForm, setPersonForm] = useState({
    full_name: "",
    egn: "",
    phone: "",
    email: "",
    address: "",
    notes: "",
  });
  
  const [saving, setSaving] = useState(false);

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setStep("type");
      setClientType(null);
      setSearchQuery("");
      setSearchResults([]);
      setHasSearched(false);
      setCompanyForm({
        company_name: "",
        eik: "",
        vat_number: "",
        mol: "",
        address: "",
        email: "",
        phone: "",
        notes: "",
      });
      setPersonForm({
        full_name: "",
        egn: "",
        phone: "",
        email: "",
        address: "",
        notes: "",
      });
    }
  }, [open]);

  // Handle type selection
  const handleTypeSelect = (type) => {
    setClientType(type);
    setStep("search");
    setSearchQuery("");
    setSearchResults([]);
    setHasSearched(false);
  };

  // Handle search
  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    
    setSearching(true);
    setHasSearched(true);
    
    try {
      const res = await API.get("/clients/search/unified", {
        params: {
          query: searchQuery.trim(),
          type: clientType,
          limit: 20,
        }
      });
      setSearchResults(res.data.items || []);
    } catch (err) {
      console.error(err);
      toast.error("Грешка при търсене");
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [searchQuery, clientType]);

  // Handle Enter key in search
  const handleSearchKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSearch();
    }
  };

  // Handle client selection
  const handleSelectClient = async (client) => {
    setSaving(true);
    try {
      await API.patch(`/projects/${projectId}/client-link`, {
        client_id: client.id,
        client_type: client.type,
      });
      
      toast.success("Клиентът е свързан с проекта!");
      onClientSelected?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка при запазване");
    } finally {
      setSaving(false);
    }
  };

  // Handle create new client
  const handleCreateClient = async () => {
    setSaving(true);
    
    try {
      let newClient;
      
      if (clientType === "company") {
        if (!companyForm.company_name.trim() || !companyForm.eik.trim()) {
          toast.error("Въведете име на фирмата и ЕИК");
          setSaving(false);
          return;
        }
        
        const res = await API.post("/clients/company", companyForm);
        newClient = res.data;
      } else {
        if (!personForm.full_name.trim()) {
          toast.error("Въведете име");
          setSaving(false);
          return;
        }
        
        const res = await API.post("/clients/person", personForm);
        newClient = res.data;
      }
      
      // Link to project
      await API.patch(`/projects/${projectId}/client-link`, {
        client_id: newClient.id,
        client_type: newClient.type,
      });
      
      toast.success("Клиентът е създаден и свързан с проекта!");
      onClientSelected?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Грешка при създаване");
    } finally {
      setSaving(false);
    }
  };

  // Go to create form
  const goToCreateForm = () => {
    setStep("create");
    // Pre-fill search query if it looks like a name
    if (searchQuery.trim() && !/^\d+$/.test(searchQuery.trim())) {
      if (clientType === "company") {
        setCompanyForm(prev => ({ ...prev, company_name: searchQuery.trim() }));
      } else {
        setPersonForm(prev => ({ ...prev, full_name: searchQuery.trim() }));
      }
    }
  };

  // Render type selection step
  const renderTypeStep = () => (
    <div className="space-y-4 py-4">
      <p className="text-sm text-muted-foreground text-center">
        Изберете типа клиент
      </p>
      
      <div className="grid grid-cols-2 gap-4">
        <button
          onClick={() => handleTypeSelect("company")}
          className="flex flex-col items-center gap-3 p-6 rounded-xl border-2 border-border bg-card hover:border-primary hover:bg-primary/5 transition-all"
          data-testid="select-company-type"
        >
          <div className="w-14 h-14 rounded-full bg-blue-500/10 flex items-center justify-center">
            <Building2 className="w-7 h-7 text-blue-500" />
          </div>
          <span className="font-medium text-foreground">Фирма</span>
          <span className="text-xs text-muted-foreground">ЕИК / ДДС номер</span>
        </button>
        
        <button
          onClick={() => handleTypeSelect("person")}
          className="flex flex-col items-center gap-3 p-6 rounded-xl border-2 border-border bg-card hover:border-primary hover:bg-primary/5 transition-all"
          data-testid="select-person-type"
        >
          <div className="w-14 h-14 rounded-full bg-green-500/10 flex items-center justify-center">
            <User className="w-7 h-7 text-green-500" />
          </div>
          <span className="font-medium text-foreground">Частно лице</span>
          <span className="text-xs text-muted-foreground">Име / ЕГН / Телефон</span>
        </button>
      </div>
    </div>
  );

  // Render search step
  const renderSearchStep = () => (
    <div className="space-y-4 py-2">
      {/* Back button */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setStep("type")}
        className="text-muted-foreground hover:text-foreground -ml-2"
      >
        <ArrowLeft className="w-4 h-4 mr-1" />
        Назад
      </Button>
      
      {/* Search input */}
      <div className="space-y-2">
        <Label>
          {clientType === "company" 
            ? "Търсене по име, ЕИК, ДДС или телефон" 
            : "Търсене по име, ЕГН или телефон"
          }
        </Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder={clientType === "company" ? "Фирма ЕООД или 123456789" : "Иван Петров или 0888123456"}
              className="pl-10 bg-background"
              autoFocus
              data-testid="client-search-input"
            />
          </div>
          <Button
            onClick={handleSearch}
            disabled={searching || !searchQuery.trim()}
            className="bg-primary hover:bg-primary/90"
            data-testid="search-clients-btn"
          >
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : "Търси"}
          </Button>
        </div>
      </div>

      {/* Search Results */}
      {hasSearched && (
        <div className="space-y-3">
          {searchResults.length > 0 ? (
            <>
              <p className="text-sm text-muted-foreground">
                Намерени: {searchResults.length} {searchResults.length === 1 ? "резултат" : "резултата"}
              </p>
              <div className="max-h-[300px] overflow-y-auto space-y-2">
                {searchResults.map((client) => (
                  <div
                    key={client.id}
                    className="flex items-center justify-between p-3 rounded-lg border border-border bg-card hover:border-primary/50 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div className={cn(
                        "w-10 h-10 rounded-full flex items-center justify-center",
                        client.type === "company" ? "bg-blue-500/10" : "bg-green-500/10"
                      )}>
                        {client.type === "company" ? (
                          <Building2 className="w-5 h-5 text-blue-500" />
                        ) : (
                          <User className="w-5 h-5 text-green-500" />
                        )}
                      </div>
                      <div>
                        <p className="font-medium text-foreground">{client.display_name}</p>
                        <div className="flex items-center gap-3 text-xs text-muted-foreground">
                          {client.identifier && (
                            <span className="flex items-center gap-1">
                              <Hash className="w-3 h-3" />
                              {client.identifier_label}: {client.identifier}
                            </span>
                          )}
                          {client.phone && (
                            <span className="flex items-center gap-1">
                              <Phone className="w-3 h-3" />
                              {client.phone}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <Button
                      size="sm"
                      onClick={() => handleSelectClient(client)}
                      disabled={saving}
                      className="bg-primary hover:bg-primary/90"
                      data-testid={`select-client-${client.id}`}
                    >
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : (
                        <>
                          <UserCheck className="w-4 h-4 mr-1" />
                          Избери
                        </>
                      )}
                    </Button>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="text-center py-8 space-y-4">
              <div className="w-16 h-16 mx-auto rounded-full bg-amber-500/10 flex items-center justify-center">
                <AlertCircle className="w-8 h-8 text-amber-500" />
              </div>
              <div>
                <p className="font-medium text-foreground">Не е намерен клиент</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Можете да създадете нов {clientType === "company" ? "фирма" : "частно лице"}
                </p>
              </div>
              <Button
                onClick={goToCreateForm}
                className="bg-primary hover:bg-primary/90"
                data-testid="create-new-client-btn"
              >
                <Plus className="w-4 h-4 mr-2" />
                Нов клиент
              </Button>
            </div>
          )}
          
          {/* Always show "Create new" option if there are results */}
          {searchResults.length > 0 && (
            <div className="pt-3 border-t border-border">
              <Button
                variant="outline"
                onClick={goToCreateForm}
                className="w-full"
                data-testid="create-new-client-btn"
              >
                <Plus className="w-4 h-4 mr-2" />
                Създай нов клиент
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );

  // Render create form step
  const renderCreateStep = () => (
    <div className="space-y-4 py-2">
      {/* Back button */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setStep("search")}
        className="text-muted-foreground hover:text-foreground -ml-2"
      >
        <ArrowLeft className="w-4 h-4 mr-1" />
        Назад към търсене
      </Button>
      
      <div className="flex items-center gap-2 mb-4">
        <div className={cn(
          "w-8 h-8 rounded-full flex items-center justify-center",
          clientType === "company" ? "bg-blue-500/10" : "bg-green-500/10"
        )}>
          {clientType === "company" ? (
            <Building2 className="w-4 h-4 text-blue-500" />
          ) : (
            <User className="w-4 h-4 text-green-500" />
          )}
        </div>
        <span className="font-medium">
          Нов {clientType === "company" ? "фирмен клиент" : "частен клиент"}
        </span>
      </div>

      {clientType === "company" ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2 space-y-2">
              <Label>Име на фирмата *</Label>
              <Input
                value={companyForm.company_name}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, company_name: e.target.value }))}
                placeholder="Фирма ЕООД"
                className="bg-background"
                data-testid="company-name-input"
              />
            </div>
            <div className="space-y-2">
              <Label>ЕИК *</Label>
              <Input
                value={companyForm.eik}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, eik: e.target.value }))}
                placeholder="123456789"
                className="bg-background font-mono"
                data-testid="company-eik-input"
              />
            </div>
            <div className="space-y-2">
              <Label>ДДС номер</Label>
              <Input
                value={companyForm.vat_number}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, vat_number: e.target.value }))}
                placeholder="BG123456789"
                className="bg-background font-mono"
              />
            </div>
            <div className="space-y-2">
              <Label>МОЛ</Label>
              <Input
                value={companyForm.mol}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, mol: e.target.value }))}
                placeholder="Име на представител"
                className="bg-background"
              />
            </div>
            <div className="space-y-2">
              <Label>Телефон</Label>
              <Input
                value={companyForm.phone}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, phone: e.target.value }))}
                placeholder="+359888123456"
                className="bg-background"
              />
            </div>
            <div className="col-span-2 space-y-2">
              <Label>Имейл</Label>
              <Input
                type="email"
                value={companyForm.email}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, email: e.target.value }))}
                placeholder="office@firma.bg"
                className="bg-background"
              />
            </div>
            <div className="col-span-2 space-y-2">
              <Label>Адрес</Label>
              <Input
                value={companyForm.address}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, address: e.target.value }))}
                placeholder="ул. Витоша 15, София"
                className="bg-background"
              />
            </div>
            <div className="col-span-2 space-y-2">
              <Label>Бележки</Label>
              <Textarea
                value={companyForm.notes}
                onChange={(e) => setCompanyForm(prev => ({ ...prev, notes: e.target.value }))}
                placeholder="Допълнителна информация"
                rows={2}
                className="bg-background resize-none"
              />
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2 space-y-2">
              <Label>Име и фамилия *</Label>
              <Input
                value={personForm.full_name}
                onChange={(e) => setPersonForm(prev => ({ ...prev, full_name: e.target.value }))}
                placeholder="Иван Петров"
                className="bg-background"
                data-testid="person-name-input"
              />
            </div>
            <div className="space-y-2">
              <Label>ЕГН</Label>
              <Input
                value={personForm.egn}
                onChange={(e) => setPersonForm(prev => ({ ...prev, egn: e.target.value }))}
                placeholder="0000000000"
                className="bg-background font-mono"
                data-testid="person-egn-input"
              />
            </div>
            <div className="space-y-2">
              <Label>Телефон</Label>
              <Input
                value={personForm.phone}
                onChange={(e) => setPersonForm(prev => ({ ...prev, phone: e.target.value }))}
                placeholder="+359888123456"
                className="bg-background"
                data-testid="person-phone-input"
              />
            </div>
            <div className="col-span-2 space-y-2">
              <Label>Имейл</Label>
              <Input
                type="email"
                value={personForm.email}
                onChange={(e) => setPersonForm(prev => ({ ...prev, email: e.target.value }))}
                placeholder="email@example.com"
                className="bg-background"
              />
            </div>
            <div className="col-span-2 space-y-2">
              <Label>Адрес</Label>
              <Input
                value={personForm.address}
                onChange={(e) => setPersonForm(prev => ({ ...prev, address: e.target.value }))}
                placeholder="ул. Примерна 1, София"
                className="bg-background"
              />
            </div>
            <div className="col-span-2 space-y-2">
              <Label>Бележки</Label>
              <Textarea
                value={personForm.notes}
                onChange={(e) => setPersonForm(prev => ({ ...prev, notes: e.target.value }))}
                placeholder="Допълнителна информация"
                rows={2}
                className="bg-background resize-none"
              />
            </div>
          </div>
        </div>
      )}

      <Button
        onClick={handleCreateClient}
        disabled={saving}
        className="w-full bg-primary hover:bg-primary/90"
        data-testid="save-new-client-btn"
      >
        {saving ? (
          <Loader2 className="w-4 h-4 animate-spin mr-2" />
        ) : (
          <CheckCircle2 className="w-4 h-4 mr-2" />
        )}
        Създай и свържи към проекта
      </Button>
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserCheck className="w-5 h-5 text-primary" />
            Избери клиент
          </DialogTitle>
          <DialogDescription>
            {step === "type" && "Изберете типа клиент, който искате да свържете с проекта"}
            {step === "search" && `Търсете съществуващ ${clientType === "company" ? "фирмен" : "частен"} клиент`}
            {step === "create" && `Създайте нов ${clientType === "company" ? "фирмен" : "частен"} клиент`}
          </DialogDescription>
        </DialogHeader>

        {step === "type" && renderTypeStep()}
        {step === "search" && renderSearchStep()}
        {step === "create" && renderCreateStep()}
      </DialogContent>
    </Dialog>
  );
}
