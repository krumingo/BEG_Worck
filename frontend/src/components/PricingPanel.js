/**
 * PricingPanel — Material pricing breakdown embedded in SMRAnalysisPage.
 * Shows per-material live prices from 3 agents.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { RefreshCcw, Loader2, Check, TrendingUp } from "lucide-react";
import { toast } from "sonner";

function freshness(fetchedAt) {
  if (!fetchedAt) return { dot: "bg-red-500", label: "> 30д" };
  const days = (Date.now() - new Date(fetchedAt).getTime()) / 86400000;
  if (days < 7) return { dot: "bg-emerald-500", label: `${Math.floor(days)}д` };
  if (days < 30) return { dot: "bg-amber-500", label: `${Math.floor(days)}д` };
  return { dot: "bg-red-500", label: `${Math.floor(days)}д` };
}

export default function PricingPanel({ analysisId, lineId, materials, onUpdated, disabled }) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [detailMat, setDetailMat] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Fetch prices for all materials in the line
  const handleFetchAll = async () => {
    setLoading(true);
    try {
      const res = await API.post(`/smr-analyses/${analysisId}/lines/${lineId}/fetch-prices`);
      onUpdated?.(res.data.analysis);
      toast.success(`${t("pricing.pricesUpdated")}: ${res.data.materials_updated} ${t("pricing.materials")}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || t("common.error"));
    } finally {
      setLoading(false);
    }
  };

  // Show pricing detail for a single material
  const handleShowDetail = async (mat) => {
    setDetailMat(mat);
    setShowDetail(true);
    setDetailLoading(true);
    try {
      const res = await API.get(`/pricing/material?name=${encodeURIComponent(mat.name)}`);
      setDetailData(res.data);
    } catch {
      setDetailData(null);
    } finally {
      setDetailLoading(false);
    }
  };

  if (!materials || materials.length === 0) return null;

  return (
    <div data-testid="pricing-panel">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-xs font-medium">{t("pricing.liveTitle")}</span>
        </div>
        {!disabled && (
          <Button size="sm" variant="outline" onClick={handleFetchAll} disabled={loading} data-testid="fetch-all-prices-btn">
            {loading ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <RefreshCcw className="w-3.5 h-3.5 mr-1" />}
            {t("pricing.refreshAll")}
          </Button>
        )}
      </div>

      <div className="space-y-1">
        {materials.map((m, i) => {
          const f = freshness(m.price_fetched_at);
          return (
            <div key={i} className="flex items-center justify-between text-xs p-1.5 rounded bg-muted/10 hover:bg-muted/20 cursor-pointer" onClick={() => handleShowDetail(m)}>
              <span className="truncate flex-1 min-w-0">{m.name}</span>
              <div className="flex items-center gap-2 flex-shrink-0">
                {m.unit_price > 0 && (
                  <span className="font-mono">{m.unit_price.toFixed(2)} лв/{m.unit}</span>
                )}
                {m.price_confidence > 0 && (
                  <Badge variant="outline" className="text-[9px]">{Math.round(m.price_confidence * 100)}%</Badge>
                )}
                {m.price_fetched_at && (
                  <span className={`w-2 h-2 rounded-full ${f.dot}`} title={f.label} />
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Detail Dialog */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{detailMat?.name}</DialogTitle>
            <DialogDescription>{t("pricing.breakdown")}</DialogDescription>
          </DialogHeader>
          {detailLoading ? (
            <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : detailData ? (
            <div className="space-y-3">
              {/* Summary */}
              <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20">
                <div>
                  <p className="text-xs text-muted-foreground">{t("pricing.recommendedPrice")}</p>
                  <p className="text-lg font-bold font-mono">{detailData.recommended_price?.toFixed(2) || "—"} лв</p>
                </div>
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">{t("pricing.confidence")}</p>
                  <Badge variant="outline" className="text-sm">{Math.round((detailData.confidence || 0) * 100)}%</Badge>
                </div>
              </div>

              {/* Agent breakdown */}
              {detailData.prices?.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">{t("pricing.source")}</TableHead>
                      <TableHead className="text-xs text-right">{t("pricing.price")}</TableHead>
                      <TableHead className="text-xs text-right">{t("pricing.confidence")}</TableHead>
                      <TableHead className="text-xs text-right">{t("pricing.fresh")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detailData.prices.map((p, i) => {
                      const f = freshness(p.fetched_at);
                      return (
                        <TableRow key={i} className="text-xs">
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <Badge variant="outline" className="text-[9px]">A{p.agent_id}</Badge>
                              <span>{p.source_name}</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right font-mono font-bold">{p.price?.toFixed(2)} лв</TableCell>
                          <TableCell className="text-right">{Math.round((p.confidence || 0) * 100)}%</TableCell>
                          <TableCell className="text-right">
                            <span className={`inline-block w-2 h-2 rounded-full ${f.dot}`} />
                            <span className="ml-1">{f.label}</span>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}

              {detailData.from_cache && (
                <p className="text-xs text-muted-foreground text-center">{t("pricing.fromCache")}</p>
              )}
            </div>
          ) : (
            <p className="text-center text-muted-foreground py-4">{t("pricing.noData")}</p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
