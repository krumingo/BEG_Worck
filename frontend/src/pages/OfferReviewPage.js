import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import API from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import {
  FileText, Check, X, RefreshCw, Loader2, MapPin, Building2, Phone, Mail,
} from "lucide-react";

const STATUS_BG = {
  Draft: "Чернова", Sent: "Изпратена", Accepted: "Одобрена",
  Rejected: "Отказана", NeedsRevision: "Изисква корекция", Archived: "Архивирана",
};
const STATUS_COLORS = {
  Sent: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Accepted: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  Rejected: "bg-red-500/20 text-red-400 border-red-500/30",
  NeedsRevision: "bg-amber-500/20 text-amber-400 border-amber-500/30",
};

export default function OfferReviewPage() {
  const { reviewToken } = useParams();
  const [offer, setOffer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [responding, setResponding] = useState(false);
  const [responded, setResponded] = useState(false);
  const [comment, setComment] = useState("");
  const [clientName, setClientName] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await API.get(`/offers/review/${reviewToken}`);
        setOffer(res.data);
      } catch (err) {
        setError(err.response?.data?.detail || "Офертата не е намерена");
      } finally { setLoading(false); }
    })();
  }, [reviewToken]);

  const handleRespond = async (action) => {
    setResponding(true);
    try {
      await API.post(`/offers/review/${reviewToken}/respond`, {
        action, comment, client_name: clientName,
      });
      setResponded(true);
      setOffer(prev => ({
        ...prev,
        status: action === "approve" ? "Accepted" : action === "reject" ? "Rejected" : "NeedsRevision",
      }));
    } catch (err) {
      alert(err.response?.data?.detail || "Грешка");
    } finally { setResponding(false); }
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center bg-[#0d1117]"><Loader2 className="w-8 h-8 animate-spin text-amber-500" /></div>;
  if (error) return <div className="min-h-screen flex items-center justify-center bg-[#0d1117]"><div className="text-center"><FileText className="w-12 h-12 mx-auto mb-4 text-gray-600" /><p className="text-gray-400">{error}</p></div></div>;
  if (!offer) return null;

  const isSent = offer.status === "Sent";

  return (
    <div className="min-h-screen bg-[#0d1117] text-gray-100" data-testid="offer-review-page">
      {/* Header */}
      <div className="border-b border-gray-800 bg-[#161b22]">
        <div className="max-w-4xl mx-auto px-6 py-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
                {offer.company_name && <span className="flex items-center gap-1"><Building2 className="w-3 h-3" />{offer.company_name}</span>}
                {offer.company_phone && <span className="flex items-center gap-1"><Phone className="w-3 h-3" />{offer.company_phone}</span>}
              </div>
              <h1 className="text-xl font-bold text-white">{offer.title || offer.offer_no}</h1>
              <p className="text-sm text-gray-400 mt-0.5">
                {offer.offer_type === "extra" ? "Допълнителна оферта" : "Оферта"} {offer.offer_no} • v{offer.version || 1}
                {offer.project_code && ` • ${offer.project_code} ${offer.project_name}`}
              </p>
            </div>
            <Badge variant="outline" className={`text-sm ${STATUS_COLORS[offer.status] || "bg-gray-500/20 text-gray-400"}`}>
              {STATUS_BG[offer.status] || offer.status}
            </Badge>
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        {/* Project info */}
        {offer.project_address && (
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <MapPin className="w-4 h-4" /> {offer.project_address}
          </div>
        )}

        {/* Lines */}
        <div className="rounded-xl border border-gray-700 bg-[#161b22] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/50">
              <tr>
                <th className="text-left p-3 text-xs uppercase text-gray-500 font-medium">Описание</th>
                <th className="text-left p-3 text-xs uppercase text-gray-500 font-medium w-16">Мярка</th>
                <th className="text-right p-3 text-xs uppercase text-gray-500 font-medium w-16">К-во</th>
                <th className="text-right p-3 text-xs uppercase text-gray-500 font-medium w-24">Мат. ед.</th>
                <th className="text-right p-3 text-xs uppercase text-gray-500 font-medium w-24">Труд ед.</th>
                <th className="text-right p-3 text-xs uppercase text-gray-500 font-medium w-28">Общо</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {offer.lines?.map((line, i) => (
                <tr key={i} className="hover:bg-gray-800/30">
                  <td className="p-3">
                    <span className="text-white">{line.activity_name}</span>
                    {line.note && <p className="text-xs text-gray-500 mt-0.5">{line.note}</p>}
                  </td>
                  <td className="p-3 text-gray-400">{line.unit}</td>
                  <td className="p-3 text-right font-mono text-gray-300">{line.qty}</td>
                  <td className="p-3 text-right font-mono text-gray-400">{(line.material_unit_cost || 0).toFixed(2)}</td>
                  <td className="p-3 text-right font-mono text-gray-400">{(line.labor_unit_cost || 0).toFixed(2)}</td>
                  <td className="p-3 text-right font-mono font-medium text-white">{(line.line_total || 0).toFixed(2)} {offer.currency}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Totals */}
        <div className="rounded-xl border border-gray-700 bg-[#161b22] p-5">
          <div className="space-y-2 max-w-xs ml-auto">
            <div className="flex justify-between text-sm"><span className="text-gray-400">Междинна сума</span><span className="font-mono text-gray-300">{(offer.subtotal || 0).toFixed(2)} {offer.currency}</span></div>
            <div className="flex justify-between text-sm"><span className="text-gray-400">ДДС ({offer.vat_percent}%)</span><span className="font-mono text-gray-300">{(offer.vat_amount || 0).toFixed(2)} {offer.currency}</span></div>
            <div className="flex justify-between pt-2 border-t border-gray-700"><span className="font-semibold text-white">Общо</span><span className="font-mono text-xl font-bold text-amber-400">{(offer.total || 0).toFixed(2)} {offer.currency}</span></div>
          </div>
        </div>

        {offer.notes && (
          <div className="rounded-xl border border-gray-700 bg-[#161b22] p-5">
            <p className="text-xs text-gray-500 mb-1">Бележки</p>
            <p className="text-sm text-gray-300">{offer.notes}</p>
          </div>
        )}

        {/* Response Section */}
        {isSent && !responded && (
          <div className="rounded-xl border-2 border-amber-500/30 bg-amber-500/5 p-6" data-testid="response-section">
            <h3 className="text-lg font-semibold text-white mb-4">Вашето решение</h3>
            <div className="space-y-3 mb-4">
              <div className="space-y-1">
                <label className="text-sm text-gray-400">Вашето име</label>
                <Input value={clientName} onChange={e => setClientName(e.target.value)} placeholder="Име и фамилия" className="bg-gray-800 border-gray-700 text-white" data-testid="client-name-input" />
              </div>
              <div className="space-y-1">
                <label className="text-sm text-gray-400">Коментар (по избор)</label>
                <Textarea value={comment} onChange={e => setComment(e.target.value)} placeholder="Допълнителен коментар..." className="bg-gray-800 border-gray-700 text-white min-h-[60px]" data-testid="client-comment-input" />
              </div>
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <Button onClick={() => handleRespond("approve")} disabled={responding} className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="approve-btn">
                {responding ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Check className="w-4 h-4 mr-2" />} Одобрявам
              </Button>
              <Button onClick={() => handleRespond("revision")} disabled={responding} variant="outline" className="flex-1 border-amber-500/50 text-amber-400 hover:bg-amber-500/10" data-testid="revision-btn">
                <RefreshCw className="w-4 h-4 mr-2" /> Искам корекция
              </Button>
              <Button onClick={() => handleRespond("reject")} disabled={responding} variant="outline" className="flex-1 border-red-500/50 text-red-400 hover:bg-red-500/10" data-testid="reject-btn">
                <X className="w-4 h-4 mr-2" /> Отказвам
              </Button>
            </div>
          </div>
        )}

        {/* Already responded */}
        {(responded || !isSent) && (
          <div className={`rounded-xl border p-6 text-center ${
            offer.status === "Accepted" ? "border-emerald-500/30 bg-emerald-500/5" :
            offer.status === "Rejected" ? "border-red-500/30 bg-red-500/5" :
            "border-amber-500/30 bg-amber-500/5"
          }`} data-testid="responded-message">
            <p className="text-lg font-semibold text-white mb-1">
              {offer.status === "Accepted" ? "Офертата е одобрена" :
               offer.status === "Rejected" ? "Офертата е отказана" :
               offer.status === "NeedsRevision" ? "Поискана е корекция" :
               STATUS_BG[offer.status] || offer.status}
            </p>
            <p className="text-sm text-gray-400">Благодарим за обратната връзка!</p>
          </div>
        )}
      </div>
    </div>
  );
}
