/**
 * SMRLocationMap — Reverse lookup: select an SMR type, see all locations where it exists.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Search, Loader2, MapPin, ArrowRightLeft } from "lucide-react";

const STATUS_COLORS = {
  draft: "bg-slate-100 text-slate-700",
  reported: "bg-blue-50 text-blue-700",
  reviewed: "bg-amber-50 text-amber-700",
  analyzed: "bg-purple-50 text-purple-700",
  offered: "bg-emerald-50 text-emerald-700",
  closed: "bg-zinc-100 text-zinc-500",
};

export default function SMRLocationMap({ projectId }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearched(true);
    try {
      const params = new URLSearchParams({ smr_type: query.trim() });
      const res = await API.get(`/projects/${projectId}/smr-reverse-lookup?${params}`);
      setResults(res.data.results || []);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-3" data-testid="smr-location-map">
      <div className="flex items-center gap-2">
        <ArrowRightLeft className="w-4 h-4 text-cyan-400" />
        <span className="font-semibold text-sm">{t("locations.reverseTitle")}</span>
      </div>

      <div className="flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("locations.reverseSearchPlaceholder")}
          className="flex-1"
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
          data-testid="reverse-search-input"
        />
        <Button size="sm" onClick={handleSearch} disabled={searching || !query.trim()} data-testid="reverse-search-btn">
          {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
        </Button>
      </div>

      {searched && (
        results.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-3">{t("locations.reverseNoResults")}</p>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">{t("locations.reverseLocation")}</TableHead>
                  <TableHead className="text-xs">{t("missingSMR.type")}</TableHead>
                  <TableHead className="text-xs text-center">{t("missingSMR.qty")}</TableHead>
                  <TableHead className="text-xs">{t("common.status")}</TableHead>
                  <TableHead className="text-xs">{t("locations.reverseSource")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((r) => (
                  <TableRow key={`${r.source}-${r.id}`} className="text-xs">
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <MapPin className="w-3 h-3 text-muted-foreground" />
                        <span>{r.location_name}</span>
                      </div>
                    </TableCell>
                    <TableCell>{r.smr_type || r.activity_type || "-"}</TableCell>
                    <TableCell className="text-center">{r.qty} {r.unit}</TableCell>
                    <TableCell>
                      <Badge className={`text-[9px] ${STATUS_COLORS[r.status] || ""}`} variant="outline">
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[9px]">
                        {r.source === "missing_smr" ? "Липсващо" : "Доп. работа"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )
      )}
    </div>
  );
}
