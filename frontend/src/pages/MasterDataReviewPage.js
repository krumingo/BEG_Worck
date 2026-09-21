import { useState, useEffect, useCallback } from "react";
import API from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { canApproveMasterData, canRejectMasterData } from "@/lib/masterDataAccess";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  Loader2, Inbox, Search, Check, X, AlertTriangle, ShieldAlert,
  PowerOff, RefreshCw, Link2, PlusCircle, ChevronDown, ChevronRight,
} from "lucide-react";

// Тези списъци огледалват каноничните стойности на бекенда
// (app/master_data/models.py и app/master_data/pending.py).
const ENTITY_TYPES = [
  { value: "organization", label: "Фирма" },
  { value: "person", label: "Лице" },
  { value: "activity", label: "СМР дейност" },
  { value: "item", label: "Артикул" },
  { value: "asset_type", label: "Вид техника" },
  { value: "physical_asset", label: "Единица техника" },
  { value: "unit", label: "Мерна единица" },
  { value: "location", label: "Локация" },
  { value: "tag", label: "Етикет" },
];

const SOURCES = [
  { value: "ocr", label: "OCR" },
  { value: "excel", label: "Excel" },
  { value: "ai", label: "AI" },
  { value: "import", label: "Импорт" },
];

const STATUSES = [
  { value: "pending", label: "За мапване" },
  { value: "resolving", label: "В процес" },
  { value: "resolved", label: "Решени" },
  { value: "rejected", label: "Отказани" },
];

const labelOf = (list, value) =>
  (list.find((x) => x.value === value) || {}).label || value || "—";

function errorStateFrom(err) {
  const status = err?.response?.status;
  if (status === 403) return "forbidden";
  if (status === 503) return "misconfigured";
  return "error";
}

function detailText(err) {
  const d = err?.response?.data?.detail;
  if (!d) return "Неуспешна заявка.";
  if (typeof d === "string") return d;
  return d.message || JSON.stringify(d);
}

export default function MasterDataReviewPage() {
  // Кой какво може решава сървърът при всяка заявка; тук само не показваме
  // бутони, които ролята няма право да натисне (канонични права, FLOW-032).
  const { user } = useAuth();
  const rights = {
    canApprove: canApproveMasterData(user?.role),
    canReject: canRejectMasterData(user?.role),
  };
  const readOnly = !rights.canApprove && !rights.canReject;
  const [items, setItems] = useState([]);
  const [mode, setMode] = useState(null);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState(null); // forbidden | misconfigured | error
  const [problemText, setProblemText] = useState("");
  const [expanded, setExpanded] = useState(null);

  const [status, setStatus] = useState("pending");
  const [entityType, setEntityType] = useState("");
  const [source, setSource] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setProblem(null);
    // Само филтрите на потребителя. Tenant-ът се определя от сесията на
    // сървъра (D-15) — браузърът никога не го изпраща.
    const params = { status };
    if (entityType) params.entity_type = entityType;
    if (source) params.source_channel = source;

    API.get("/master-data/pending", { params })
      .then((r) => {
        setMode(r.data?.mode || null);
        setItems(r.data?.items || []);
      })
      .catch((err) => {
        setItems([]);
        setProblem(errorStateFrom(err));
        setProblemText(detailText(err));
      })
      .finally(() => setLoading(false));
  }, [status, entityType, source]);

  useEffect(() => { load(); }, [load]);

  const onResolved = (id) => {
    setExpanded(null);
    setItems((prev) => prev.filter((x) => x.id !== id));
  };

  const isOff = mode === "off";

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Inbox className="w-5 h-5" />За мапване
          </h1>
          <p className="text-sm text-muted-foreground">
            Текст от OCR, Excel и AI, който още не е свързан с официален запис.
            Машината предлага — решава човек.
          </p>
          {readOnly && (
            <p className="text-xs text-amber-500 mt-1" data-testid="md-readonly">
              Само преглед: свързването, създаването и отказът са за офиса и администраторите.
            </p>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={load} data-testid="md-refresh">
          <RefreshCw className="w-4 h-4 mr-1" />Обнови
        </Button>
      </div>

      <div className="flex flex-wrap gap-2" data-testid="md-filters">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="Статус"
          data-testid="md-filter-status"
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
        >
          {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select
          value={entityType}
          onChange={(e) => setEntityType(e.target.value)}
          aria-label="Тип"
          data-testid="md-filter-type"
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
        >
          <option value="">Всички типове</option>
          {ENTITY_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          aria-label="Източник"
          data-testid="md-filter-source"
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
        >
          <option value="">Всички източници</option>
          {SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-12" data-testid="md-loading">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
        </div>
      ) : problem === "forbidden" ? (
        <StateBox testId="md-forbidden" icon={ShieldAlert} title="Нямате право за този екран">
          Мапването на Master Data е за офиса и администраторите (FLOW-032).
        </StateBox>
      ) : problem === "misconfigured" ? (
        <StateBox testId="md-misconfigured" icon={AlertTriangle} title="Функцията е конфигурирана невалидно">
          {problemText}
        </StateBox>
      ) : problem ? (
        <StateBox testId="md-error" icon={AlertTriangle} title="Нещо се обърка">
          {problemText}
          <div className="mt-3">
            <Button size="sm" variant="outline" onClick={load} data-testid="md-retry">Опитай пак</Button>
          </div>
        </StateBox>
      ) : isOff ? (
        <StateBox testId="md-off" icon={PowerOff} title="Мапването е изключено">
          Master Data работи в режим <code>off</code>. Автоматичните канали не записват
          предложения и няма какво да се преглежда.
        </StateBox>
      ) : items.length === 0 ? (
        <StateBox testId="md-empty" icon={Inbox} title="Няма записи">
          Нищо не чака решение с тези филтри.
        </StateBox>
      ) : (
        <div className="space-y-3" data-testid="md-list">
          {items.map((it) => (
            <PendingRow
              key={it.id}
              row={it}
              expanded={expanded === it.id}
              onToggle={() => setExpanded(expanded === it.id ? null : it.id)}
              onResolved={() => onResolved(it.id)}
              rights={rights}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function StateBox({ testId, icon: Icon, title, children }) {
  return (
    <div className="text-center py-12 text-muted-foreground" data-testid={testId}>
      <Icon className="w-10 h-10 mx-auto mb-2 opacity-40" />
      <p className="font-medium text-foreground">{title}</p>
      <div className="text-sm mt-1">{children}</div>
    </div>
  );
}

function PendingRow({ row, expanded, onToggle, onResolved, rights }) {
  const open = row.status === "pending";
  // Един ред събира всички срещания на текста: пазим всеки канал, който го е
  // видял, и първия и последния източник, за да не подвежда филтърът.
  const channels = row.source_channels?.length ? row.source_channels : [row.source_channel];
  return (
    <div className="rounded-2xl border border-border bg-card" data-testid={`md-row-${row.id}`}>
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left p-4 flex items-start gap-3"
        data-testid={`md-expand-${row.id}`}
      >
        {expanded ? <ChevronDown className="w-4 h-4 mt-1 shrink-0" />
          : <ChevronRight className="w-4 h-4 mt-1 shrink-0" />}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold break-words" data-testid={`md-raw-${row.id}`}>
              {row.raw_value}
            </span>
            <Badge variant="outline" className="text-[10px]">{labelOf(ENTITY_TYPES, row.entity_type)}</Badge>
            <span className="flex gap-1" data-testid={`md-sources-${row.id}`}>
              {channels.map((ch) => (
                <Badge key={ch} variant="outline" className="text-[10px]">{labelOf(SOURCES, ch)}</Badge>
              ))}
            </span>
            {row.occurrences > 1 && (
              <Badge className="bg-amber-500/20 text-amber-500 text-[10px]"
                     data-testid={`md-occurrences-${row.id}`}>
                {row.occurrences}× срещнато
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {row.source_ref || "без източник"} · {(row.created_at || "").slice(0, 16).replace("T", " ")}
            {row.last_source_ref && row.last_source_ref !== row.source_ref && (
              <span data-testid={`md-lastref-${row.id}`}>
                {" "}· последно: {row.last_source_ref}
                {row.last_seen_at ? ` (${row.last_seen_at.slice(0, 16).replace("T", " ")})` : ""}
              </span>
            )}
          </p>
          {!open && <ResolutionLine row={row} />}
        </div>
      </button>

      {expanded && open && <ReviewPanel row={row} onResolved={onResolved} rights={rights} />}
    </div>
  );
}

function ResolutionLine({ row }) {
  if (row.status === "rejected") {
    return (
      <p className="text-xs mt-1 text-rose-400" data-testid={`md-outcome-${row.id}`}>
        Отказано от {row.resolved_by || "—"}: {row.rejection_reason || "без причина"}
      </p>
    );
  }
  if (row.status === "resolved") {
    return (
      <p className="text-xs mt-1 text-emerald-400" data-testid={`md-outcome-${row.id}`}>
        Свързано от {row.resolved_by || "—"} със запис {row.resolved_entity_id || "—"}
      </p>
    );
  }
  if (row.status === "resolving") {
    return (
      <p className="text-xs mt-1 text-muted-foreground" data-testid={`md-outcome-${row.id}`}>
        В процес на решаване от {row.claimed_by || "—"}
      </p>
    );
  }
  return null;
}

function ReviewPanel({ row, onResolved, rights = {} }) {
  const { canApprove = false, canReject = false } = rights;
  const [candidates, setCandidates] = useState([]);
  const [loadingCandidates, setLoadingCandidates] = useState(true);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [displayName, setDisplayName] = useState(row.raw_value || "");
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoadingCandidates(true);
    API.get(`/master-data/pending/${row.id}/matches`)
      .then((r) => { if (alive) setCandidates(r.data?.candidates || []); })
      .catch(() => { if (alive) setCandidates([]); })
      .finally(() => { if (alive) setLoadingCandidates(false); });
    return () => { alive = false; };
  }, [row.id]);

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const r = await API.get(`/master-data/pending/${row.id}/matches`, { params: { q: query } });
      setCandidates(r.data?.candidates || []);
      if (!(r.data?.candidates || []).length) toast.info("Няма намерени записи.");
    } catch (err) {
      toast.error(detailText(err));
    } finally {
      setSearching(false);
    }
  };

  const approve = async (body, successText) => {
    setBusy(true);
    try {
      const r = await API.post(`/master-data/pending/${row.id}/approve`, body);
      if (r.data?.performed) {
        toast.success(successText);
        onResolved();
      } else {
        toast.error(r.data?.detail || "Операцията не беше извършена.");
      }
    } catch (err) {
      toast.error(detailText(err));
    } finally {
      setBusy(false);
    }
  };

  const linkTo = (entityId) =>
    approve({ confirmation: true, canonical_entity_id: entityId }, "Свързано със съществуващ запис.");

  const createNew = () =>
    approve({ confirmation: true, create_new: true, display_name: displayName.trim() },
      "Създаден е нов официален запис.");

  const reject = async () => {
    if (!reason.trim()) { toast.error("Отказът иска причина."); return; }
    setBusy(true);
    try {
      const r = await API.post(`/master-data/pending/${row.id}/reject`, { reason: reason.trim() });
      if (r.data?.performed) { toast.success("Отказано."); onResolved(); }
      else toast.error(r.data?.detail || "Операцията не беше извършена.");
    } catch (err) {
      toast.error(detailText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-border p-4 space-y-4" data-testid={`md-panel-${row.id}`}>
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Предложени съвпадения</h3>
        {loadingCandidates ? (
          <div className="py-3" data-testid="md-candidates-loading">
            <Loader2 className="w-4 h-4 animate-spin" />
          </div>
        ) : candidates.length === 0 ? (
          <p className="text-xs text-muted-foreground" data-testid="md-candidates-empty">
            Няма кандидат със същия нормализиран текст. Потърсете записа или създайте нов.
          </p>
        ) : (
          <ul className="space-y-2" data-testid="md-candidates">
            {candidates.map((c) => (
              <li key={c.entity_id}
                  className="flex items-center justify-between gap-2 rounded-xl border border-border p-2"
                  data-testid={`md-candidate-${c.entity_id}`}>
                <div className="min-w-0">
                  <p className="text-sm truncate">{c.display_name || c.entity_id}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {c.match_type === "human_lookup" ? "намерено от човек"
                      : `${c.match_type || "съвпадение"}${c.score != null ? ` · ${c.score}` : ""}`}
                  </p>
                </div>
                {canApprove && (
                  <Button size="sm" variant="outline" disabled={busy}
                          onClick={() => linkTo(c.entity_id)}
                          data-testid={`md-link-${c.entity_id}`}>
                    <Link2 className="w-4 h-4 mr-1" />Свържи
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <Input value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="Потърсете съществуващ запис по име"
                 aria-label="Търсене на съществуващ запис"
                 data-testid="md-search-input" className="h-9" />
          <Button size="sm" variant="outline" onClick={runSearch} disabled={searching}
                  data-testid="md-search-btn">
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          </Button>
        </div>
      </section>

      {canApprove && (
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Създай нов официален запис</h3>
        <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
               aria-label="Име на новия запис"
               data-testid="md-create-name" className="h-9" />
        <label className="flex items-start gap-2 text-xs text-muted-foreground">
          <input type="checkbox" checked={confirmed} className="mt-0.5"
                 onChange={(e) => setConfirmed(e.target.checked)}
                 data-testid="md-create-confirm" />
          <span>
            Потвърждавам, че този запис трябва да стане официален Master запис.
            Свободен текст не става официален запис без това потвърждение.
          </span>
        </label>
        <Button size="sm" disabled={busy || !confirmed || !displayName.trim()}
                onClick={createNew} data-testid="md-create-btn"
                className="bg-emerald-600 hover:bg-emerald-700">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" />
            : <><PlusCircle className="w-4 h-4 mr-1" />Създай нов</>}
        </Button>
      </section>
      )}

      {canReject && (
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Откажи</h3>
        <Textarea value={reason} onChange={(e) => setReason(e.target.value)}
                  placeholder="Защо този текст не е идентичност?"
                  aria-label="Причина за отказ"
                  data-testid="md-reject-reason" rows={2} />
        <Button size="sm" variant="outline" disabled={busy} onClick={reject}
                data-testid="md-reject-btn">
          <X className="w-4 h-4 mr-1" />Откажи
        </Button>
      </section>
      )}

      {!canApprove && !canReject && (
        <p className="text-xs text-muted-foreground" data-testid="md-panel-readonly">
          Можете да разгледате кандидатите; решението е за офиса и администраторите.
        </p>
      )}

      <p className="text-[11px] text-muted-foreground flex items-center gap-1">
        <Check className="w-3 h-3" />
        Нито един от тези бутони не слива записи — сливането е отделна операция.
      </p>
    </div>
  );
}
