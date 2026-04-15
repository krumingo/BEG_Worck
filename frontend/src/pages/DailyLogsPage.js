/**
 * DailyLogsPage - Дневен отчет (Mobile-first)
 * 
 * Features:
 * - Site dropdown (my sites only)
 * - Work type selector
 * - Multi-select team members + hours
 * - Notes + photo attachment
 * - List view of my logs
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { useActiveProject } from "@/contexts/ProjectContext";
import API from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ProjectContextBar from "@/components/ProjectContextBar";
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
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ClipboardList,
  Loader2,
  Plus,
  Calendar,
  Users,
  Clock,
  Building2,
  FileText,
  Save,
  ChevronLeft,
  ChevronRight,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

const QUICK_HOURS = [1, 2, 4, 6, 8, 10, 12];

export default function DailyLogsPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const isProjectContext = !!searchParams.get("returnTo");
  const [activeTab, setActiveTab] = useState("list");
  
  // Form state
  const [sites, setSites] = useState([]);
  const [workTypes, setWorkTypes] = useState([]);
  const [teamMembers, setTeamMembers] = useState([]);
  const { activeProject } = useActiveProject();
  const initSite = searchParams.get("project") || "";
  
  const [selectedSite, setSelectedSite] = useState(initSite);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split("T")[0]);
  const [selectedWorkType, setSelectedWorkType] = useState("");
  const [selectedEntries, setSelectedEntries] = useState([]);
  const [notes, setNotes] = useState("");
  
  // List state
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  
  // Load initial data
  useEffect(() => {
    const loadData = async () => {
      try {
        const [sitesRes, workTypesRes] = await Promise.all([
          API.get("/my-sites"),
          API.get("/work-types"),
        ]);
        setSites(sitesRes.data.items || []);
        setWorkTypes(workTypesRes.data.items || []);
      } catch (err) {
        console.error("Failed to load initial data:", err);
        toast.error("Грешка при зареждане на данните");
      }
    };
    loadData();
  }, []);

  // Apply active project context
  useEffect(() => {
    if (!selectedSite && activeProject?.id && !searchParams.get("project")) {
      setSelectedSite(activeProject.id);
    }
  }, [activeProject]); // eslint-disable-line react-hooks/exhaustive-deps
  
  // Load team when site changes
  useEffect(() => {
    if (!selectedSite) {
      setTeamMembers([]);
      return;
    }
    
    const loadTeam = async () => {
      try {
        const res = await API.get(`/my-team/${selectedSite}`);
        setTeamMembers(res.data.items || []);
        setSelectedEntries([]); // Reset entries when site changes
      } catch (err) {
        console.error("Failed to load team:", err);
      }
    };
    loadTeam();
  }, [selectedSite]);
  
  // Load logs
  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, page_size: 10 });
      if (selectedSite) params.append("site_id", selectedSite);
      
      const res = await API.get(`/daily-logs?${params.toString()}`);
      setLogs(res.data.items || []);
      setTotalPages(res.data.total_pages || 1);
    } catch (err) {
      console.error("Failed to load logs:", err);
    } finally {
      setLoading(false);
    }
  }, [page, selectedSite]);
  
  useEffect(() => {
    loadLogs();
  }, [loadLogs]);
  
  // Handle entry toggle
  const toggleEntry = (userId) => {
    setSelectedEntries(prev => {
      const exists = prev.find(e => e.user_id === userId);
      if (exists) {
        return prev.filter(e => e.user_id !== userId);
      } else {
        return [...prev, { user_id: userId, hours: 8 }];
      }
    });
  };
  
  // Handle hours change
  const setEntryHours = (userId, hours) => {
    setSelectedEntries(prev => 
      prev.map(e => e.user_id === userId ? { ...e, hours } : e)
    );
  };
  
  // Quick hours button
  const setQuickHours = (userId, hours) => {
    setSelectedEntries(prev => 
      prev.map(e => e.user_id === userId ? { ...e, hours } : e)
    );
  };
  
  // Save log
  const handleSave = async () => {
    if (!selectedSite) {
      toast.error("Изберете обект");
      return;
    }
    if (!selectedWorkType) {
      toast.error("Изберете вид работа");
      return;
    }
    if (selectedEntries.length === 0) {
      toast.error("Добавете поне един работник");
      return;
    }
    
    try {
      await API.post("/daily-logs", {
        site_id: selectedSite,
        date: selectedDate,
        work_type_id: selectedWorkType,
        entries: selectedEntries,
        notes: notes || null,
        attachments: [],
      });
      
      toast.success("Дневният отчет е записан");
      
      // Reset form
      setSelectedEntries([]);
      setNotes("");
      
      // Refresh list and switch to it
      loadLogs();
      setActiveTab("list");
    } catch (err) {
      console.error("Failed to save log:", err);
      toast.error(err.response?.data?.detail || "Грешка при записване");
    }
  };
  
  // Delete log
  const handleDelete = async (logId) => {
    if (!confirm("Сигурни ли сте, че искате да изтриете този отчет?")) return;
    
    try {
      await API.delete(`/daily-logs/${logId}`);
      toast.success("Отчетът е изтрит");
      loadLogs();
    } catch (err) {
      toast.error("Грешка при изтриване");
    }
  };
  
  return (
    <div className="p-4 md:p-6 space-y-4 max-w-4xl mx-auto" data-testid="daily-logs-page">
      <ProjectContextBar pageTitle="Отчети" />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
            <ClipboardList className="w-5 h-5 text-blue-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold">Дневен отчет</h1>
            <p className="text-sm text-muted-foreground">Дневник на работата по обекти</p>
          </div>
        </div>
      </div>
      
      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className={`grid w-full ${isProjectContext ? "grid-cols-1" : "grid-cols-2"}`}>
          <TabsTrigger value="list" data-testid="tab-list">
            <FileText className="w-4 h-4 mr-2" />
            {isProjectContext ? "Отчети по обекта" : "Моите отчети"}
          </TabsTrigger>
          {!isProjectContext && (
            <TabsTrigger value="new" data-testid="tab-new">
              <Plus className="w-4 h-4 mr-2" />
              Нов отчет
            </TabsTrigger>
          )}
        </TabsList>
        
        {/* New Log Form */}
        <TabsContent value="new" className="space-y-4 mt-4">
          <Card>
            <CardContent className="p-4 space-y-4">
              {/* Site Select */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <Building2 className="w-4 h-4" />
                  Обект
                </Label>
                <Select value={selectedSite} onValueChange={setSelectedSite}>
                  <SelectTrigger data-testid="site-select">
                    <SelectValue placeholder="Изберете обект..." />
                  </SelectTrigger>
                  <SelectContent>
                    {sites.map(site => (
                      <SelectItem key={site.id} value={site.id}>
                        {site.code} - {site.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              
              {/* Date */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <Calendar className="w-4 h-4" />
                  Дата
                </Label>
                <Input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  data-testid="date-input"
                />
              </div>
              
              {/* Work Type */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  Вид работа
                </Label>
                <Select value={selectedWorkType} onValueChange={setSelectedWorkType}>
                  <SelectTrigger data-testid="work-type-select">
                    <SelectValue placeholder="Изберете вид работа..." />
                  </SelectTrigger>
                  <SelectContent>
                    {workTypes.map(wt => (
                      <SelectItem key={wt.id} value={wt.id}>
                        {wt.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              
              {/* Team Members */}
              {selectedSite && (
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Users className="w-4 h-4" />
                    Работници ({selectedEntries.length} избрани)
                  </Label>
                  
                  {teamMembers.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Няма членове на екипа за този обект</p>
                  ) : (
                    <div className="space-y-2 max-h-[300px] overflow-y-auto">
                      {teamMembers.map(member => {
                        const entry = selectedEntries.find(e => e.user_id === member.id);
                        const isSelected = !!entry;
                        
                        return (
                          <Card key={member.id} className={`p-3 ${isSelected ? "border-primary" : ""}`}>
                            <div className="flex items-center gap-3">
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={() => toggleEntry(member.id)}
                                data-testid={`member-checkbox-${member.id}`}
                              />
                              <div className="flex-1">
                                <p className="font-medium text-sm">{member.name}</p>
                                <p className="text-xs text-muted-foreground">{member.role}</p>
                              </div>
                              {isSelected && (
                                <div className="flex items-center gap-2">
                                  <Input
                                    type="number"
                                    value={entry.hours}
                                    onChange={(e) => setEntryHours(member.id, parseFloat(e.target.value) || 0)}
                                    className="w-16 h-8 text-center"
                                    min="0"
                                    max="24"
                                    step="0.5"
                                  />
                                  <span className="text-xs text-muted-foreground">ч.</span>
                                </div>
                              )}
                            </div>
                            {isSelected && (
                              <div className="flex gap-1 mt-2 flex-wrap">
                                {QUICK_HOURS.map(h => (
                                  <Button
                                    key={h}
                                    variant={entry.hours === h ? "default" : "outline"}
                                    size="sm"
                                    className="h-6 px-2 text-xs"
                                    onClick={() => setQuickHours(member.id, h)}
                                  >
                                    {h}ч
                                  </Button>
                                ))}
                              </div>
                            )}
                          </Card>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
              
              {/* Notes */}
              <div className="space-y-2">
                <Label>Бележки</Label>
                <Textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Допълнителни бележки..."
                  rows={3}
                  data-testid="notes-input"
                />
              </div>
              
              {/* Summary */}
              {selectedEntries.length > 0 && (
                <div className="bg-muted/50 rounded-lg p-3">
                  <p className="text-sm font-medium">
                    Общо: {selectedEntries.reduce((sum, e) => sum + e.hours, 0)} часа от {selectedEntries.length} работника
                  </p>
                </div>
              )}
              
              {/* Save Button */}
              <Button onClick={handleSave} className="w-full" size="lg" data-testid="save-log-btn">
                <Save className="w-4 h-4 mr-2" />
                Запиши отчета
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
        
        {/* List View */}
        <TabsContent value="list" className="space-y-4 mt-4">
          {/* Filter by site */}
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-4">
                <Label className="whitespace-nowrap">Филтър по обект:</Label>
                <Select value={selectedSite || "all"} onValueChange={(v) => { setSelectedSite(v === "all" ? "" : v); setPage(1); }}>
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder="Всички обекти" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Всички обекти</SelectItem>
                    {sites.map(site => (
                      <SelectItem key={site.id} value={site.id}>
                        {site.code} - {site.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>
          
          {/* Logs Table */}
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 animate-spin" />
                </div>
              ) : logs.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  Няма дневни отчети
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Дата</TableHead>
                      <TableHead>Обект</TableHead>
                      <TableHead>Вид работа</TableHead>
                      <TableHead className="text-right">Часове</TableHead>
                      <TableHead className="text-right">Работници</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {logs.map(log => (
                      <TableRow key={log.id}>
                        <TableCell className="font-medium">{log.date}</TableCell>
                        <TableCell>
                          <span className="text-xs text-muted-foreground">{log.site_code}</span>
                          <br />
                          {log.site_name}
                        </TableCell>
                        <TableCell>{log.work_type_name}</TableCell>
                        <TableCell className="text-right font-medium text-blue-500">
                          {log.total_hours}ч
                        </TableCell>
                        <TableCell className="text-right">
                          {log.entries?.length || 0}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(log.id)}
                          >
                            <Trash2 className="w-4 h-4 text-red-500" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
          
          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-sm">
                Страница {page} от {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page === totalPages}
                onClick={() => setPage(p => p + 1)}
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
