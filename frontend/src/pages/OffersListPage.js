import { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/contexts/AuthContext";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
  FileText,
  Plus,
  Search,
  ArrowRight,
  Filter,
} from "lucide-react";

const STATUS_COLORS = {
  Draft: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Accepted: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
  Archived: "bg-violet-500/20 text-violet-400 border-violet-500/30",
};

export default function OffersListPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const projectIdParam = searchParams.get("projectId") || "";

  const [offers, setOffers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState(projectIdParam);

  const canCreate = ["Admin", "Owner", "SiteManager"].includes(user?.role);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [offersRes, projectsRes] = await Promise.all([
        API.get(`/offers${projectFilter ? `?project_id=${projectFilter}` : ""}${statusFilter ? `${projectFilter ? "&" : "?"}status=${statusFilter}` : ""}`),
        API.get("/projects"),
      ]);
      setOffers(offersRes.data);
      setProjects(projectsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [projectFilter, statusFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filteredOffers = search
    ? offers.filter(o => 
        o.offer_no?.toLowerCase().includes(search.toLowerCase()) ||
        o.title?.toLowerCase().includes(search.toLowerCase()) ||
        o.project_code?.toLowerCase().includes(search.toLowerCase())
      )
    : offers;

  const formatCurrency = (amount, currency = "EUR") => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount || 0);
  };

  return (
    <div className="p-8 max-w-[1400px]" data-testid="offers-list-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Estimates & Offers</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage quotes and bill of quantities</p>
        </div>
        {canCreate && (
          <Button onClick={() => navigate("/offers/new")} data-testid="create-offer-btn">
            <Plus className="w-4 h-4 mr-2" /> New Offer
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6 flex-wrap" data-testid="offers-filters">
        <div className="relative flex-1 min-w-[200px] max-w-[300px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search offers..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-card"
            data-testid="search-input"
          />
        </div>
        <Select value={projectFilter} onValueChange={(v) => {
          setProjectFilter(v === "all" ? "" : v);
          if (v === "all") searchParams.delete("projectId");
          else searchParams.set("projectId", v);
          setSearchParams(searchParams);
        }}>
          <SelectTrigger className="w-[200px] bg-card" data-testid="project-filter">
            <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
            <SelectValue placeholder="All Projects" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Projects</SelectItem>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.code} - {p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[150px] bg-card" data-testid="status-filter">
            <SelectValue placeholder="All Statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="Draft">Draft</SelectItem>
            <SelectItem value="Sent">Sent</SelectItem>
            <SelectItem value="Accepted">Accepted</SelectItem>
            <SelectItem value="Rejected">Rejected</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="offers-table">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Offer</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Project</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Status</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Version</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground">Lines</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Total</TableHead>
                <TableHead className="text-xs uppercase tracking-wider text-muted-foreground text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredOffers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    <FileText className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p>No offers found</p>
                    {canCreate && (
                      <Button variant="outline" className="mt-4" onClick={() => navigate("/offers/new")}>
                        Create your first offer
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                filteredOffers.map((offer) => (
                  <TableRow 
                    key={offer.id} 
                    className="table-row-hover cursor-pointer"
                    onClick={() => navigate(`/offers/${offer.id}`)}
                    data-testid={`offer-row-${offer.id}`}
                  >
                    <TableCell>
                      <p className="font-mono text-sm text-primary">{offer.offer_no}</p>
                      <p className="text-sm text-foreground truncate max-w-[200px]">{offer.title}</p>
                    </TableCell>
                    <TableCell>
                      <p className="font-mono text-xs text-primary">{offer.project_code}</p>
                      <p className="text-xs text-muted-foreground truncate max-w-[150px]">{offer.project_name}</p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${STATUS_COLORS[offer.status] || ""}`}>
                        {offer.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">v{offer.version}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{offer.line_count}</TableCell>
                    <TableCell className="text-right font-mono text-sm text-foreground">
                      {formatCurrency(offer.total, offer.currency)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/offers/${offer.id}`); }}>
                        <ArrowRight className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
