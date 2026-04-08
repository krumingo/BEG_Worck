/**
 * MaterialCatalogPage — Списък с всички материали и последни цени.
 * Route: /pricing
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { TrendingUp, Loader2, Search, RefreshCcw } from "lucide-react";
import { toast } from "sonner";

function freshness(ts) {
  if (!ts) return { dot: "bg-zinc-500", label: "-" };
  const days = (Date.now() - new Date(ts).getTime()) / 86400000;
  if (days < 7) return { dot: "bg-emerald-500", label: `${Math.floor(days)}д` };
  if (days < 30) return { dot: "bg-amber-500", label: `${Math.floor(days)}д` };
  return { dot: "bg-red-500", label: `${Math.floor(days)}д` };
}

export default function MaterialCatalogPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fCategory, setFCategory] = useState("");

  // Lookup modal
  const [showLookup, setShowLookup] = useState(false);
  const [lookupName, setLookupName] = useState("");
  const [lookupResult, setLookupResult] = useState(null);
  const [lookupLoading, setLookupLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (fCategory) p.append("category", fCategory);
      const res = await API.get(`/pricing/catalog?${p}`);
      setItems(res.data.items || []);
    } catch { /* */ }
    finally { setLoading(false); }
  }, [fCategory]);

  useEffect(() => { load(); }, [load]);

  const handleLookup = async () => {
    if (!lookupName.trim()) return;
    setLookupLoading(true);
    try {
      const res = await API.get(`/pricing/material?name=${encodeURIComponent(lookupName.trim())}&force=true`);
      setLookupResult(res.data);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
      setLookupResult(null);
    } finally { setLookupLoading(false); }
  };

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-5xl mx-auto" data-testid="material-catalog-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-teal-500/10 flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-teal-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold">{t("pricing.catalogTitle")}</h1>
            <p className="text-sm text-muted-foreground">{t("pricing.catalogSubtitle")}</p>
          </div>
        </div>
        <Button onClick={() => { setLookupName(""); setLookupResult(null); setShowLookup(true); }} data-testid="lookup-btn">
          <Search className="w-4 h-4 mr-2" /> {t("pricing.lookupPrice")}
        </Button>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex gap-4">
            <div className="flex-1">
              <Label className="text-xs mb-1 block">{t("pricing.category")}</Label>
              <Input value={fCategory} onChange={e => setFCategory(e.target.value)} placeholder={t("pricing.categoryPlaceholder")} data-testid="filter-category" />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center py-16 text-muted-foreground gap-2">
              <Search className="w-8 h-8 opacity-40" />
              <p className="text-sm">{t("pricing.noCatalog")}</p>
              <p className="text-xs">{t("pricing.noCatalogHint")}</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("pricing.materialName")}</TableHead>
                  <TableHead>{t("pricing.category")}</TableHead>
                  <TableHead>{t("pricing.unit")}</TableHead>
                  <TableHead className="text-right">{t("pricing.medianPrice")}</TableHead>
                  <TableHead className="text-right">{t("pricing.confidence")}</TableHead>
                  <TableHead className="text-center">{t("pricing.agents")}</TableHead>
                  <TableHead className="text-center">{t("pricing.fresh")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map(item => {
                  const f = freshness(item.last_refreshed_at);
                  return (
                    <TableRow key={item.material_name_normalized} data-testid={`catalog-row-${item.material_name_normalized}`}>
                      <TableCell className="font-medium">{item.material_name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{item.material_category || "-"}</TableCell>
                      <TableCell className="text-sm">{item.unit || "-"}</TableCell>
                      <TableCell className="text-right font-mono font-bold">{(item.median_price || 0).toFixed(2)} лв</TableCell>
                      <TableCell className="text-right">{Math.round((item.confidence || 0) * 100)}%</TableCell>
                      <TableCell className="text-center">{item.prices?.length || 0}</TableCell>
                      <TableCell className="text-center">
                        <span className={`inline-block w-2.5 h-2.5 rounded-full ${f.dot}`} title={f.label} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Lookup Dialog */}
      <Dialog open={showLookup} onOpenChange={setShowLookup}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("pricing.lookupPrice")}</DialogTitle>
            <DialogDescription>{t("pricing.lookupDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex gap-2">
              <Input value={lookupName} onChange={e => setLookupName(e.target.value)} placeholder={t("pricing.lookupPlaceholder")} onKeyDown={e => { if (e.key === "Enter") handleLookup(); }} data-testid="lookup-input" autoFocus />
              <Button onClick={handleLookup} disabled={lookupLoading || !lookupName.trim()} data-testid="lookup-search-btn">
                {lookupLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              </Button>
            </div>

            {lookupResult && (
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20">
                  <div>
                    <p className="text-xs text-muted-foreground">{t("pricing.recommendedPrice")}</p>
                    <p className="text-lg font-bold font-mono">{lookupResult.recommended_price?.toFixed(2) || "—"} лв</p>
                  </div>
                  <Badge variant="outline">{Math.round((lookupResult.confidence || 0) * 100)}%</Badge>
                </div>
                {lookupResult.prices?.length > 0 && (
                  <div className="space-y-1">
                    {lookupResult.prices.map((p, i) => (
                      <div key={i} className="flex items-center justify-between text-xs p-2 rounded bg-muted/10">
                        <div className="flex items-center gap-1">
                          <Badge variant="outline" className="text-[9px]">A{p.agent_id}</Badge>
                          <span>{p.source_name}</span>
                        </div>
                        <span className="font-mono font-bold">{p.price?.toFixed(2)} лв</span>
                      </div>
                    ))}
                  </div>
                )}
                {lookupResult.error && (
                  <p className="text-xs text-red-400 text-center">{lookupResult.error}</p>
                )}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
