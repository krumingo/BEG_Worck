/**
 * LIVE-OPS-01 / TASK 5A — read-only LIVE-OPS Control Center.
 *
 * Desktop-first control screen over the existing requests, warehouse ledger,
 * assets, custody and repairs. This page performs ONE kind of request: a GET of
 * /live-ops/control-center. It has no approve/reject, stock, custody, repair or
 * QR action; every "go to" is a link into an existing screen.
 *
 * Honesty rules (frozen contract v6): warehouses are labelled by name, never by
 * code alone; untrusted stock totals are marked as such; an accepted custodian
 * and a pending handover are shown in separate columns; the activity preview is
 * canonical AuditEvent or an explicit "not available" — never legacy audit.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import API from "@/lib/api";
import { formatCurrency } from "@/lib/i18nUtils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Activity, AlertTriangle, ClipboardList, Clock, Eye, Loader2, Lock, RefreshCw,
  ShieldAlert, Warehouse, Wrench,
} from "lucide-react";

/** After this long the loaded snapshot is flagged as stale on screen. */
export const STALE_AFTER_MS = 5 * 60 * 1000;

const INDICATOR_STYLE = {
  in_warehouse: { dot: "bg-emerald-500", text: "text-emerald-500" },
  on_project: { dot: "bg-yellow-400", text: "text-yellow-500" },
  with_person: { dot: "bg-blue-500", text: "text-blue-500" },
  in_repair: { dot: "bg-orange-500", text: "text-orange-500" },
  written_off: { dot: "bg-zinc-800 dark:bg-zinc-300", text: "text-muted-foreground" },
  unknown: { dot: "bg-zinc-400", text: "text-muted-foreground" },
};
const INDICATOR_ORDER = ["in_warehouse", "on_project", "with_person", "in_repair", "written_off", "unknown"];
const INDICATOR_LABEL = {
  in_warehouse: "В склад",
  on_project: "На обект",
  with_person: "При човек",
  in_repair: "В ремонт",
  written_off: "Бракуван / отписан",
  unknown: "Неизвестно",
};
const SEVERITY_STYLE = {
  critical: "border-red-500/40 bg-red-500/5",
  warning: "border-amber-500/40 bg-amber-500/5",
  info: "border-border bg-card",
};

function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("bg-BG");
}

function fmtDate(iso) {
  if (!iso) return "—";
  return String(iso).slice(0, 10);
}

function fmtQty(n) {
  return Number(n || 0).toLocaleString("bg-BG", { maximumFractionDigits: 3 });
}

/** Source + freshness line shown under every card that holds loaded data. */
function SourceLine({ section, extra, testId }) {
  if (!section) return null;
  return (
    <p className="text-[11px] text-muted-foreground mt-2 flex flex-wrap gap-x-3" data-testid={testId}>
      <span>Източник: {section.source}</span>
      <span>Изчислено: {fmtDateTime(section.generated_at)}</span>
      {extra}
    </p>
  );
}

function SectionError({ section, name }) {
  return (
    <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-4 text-sm" role="alert"
      data-testid={`section-error-${name}`}>
      <p className="font-medium text-red-500 flex items-center gap-2">
        <AlertTriangle className="w-4 h-4" /> Секцията не е заредена
      </p>
      <p className="text-muted-foreground mt-1">{section?.message}</p>
    </div>
  );
}

function Kpi({ label, value, tone, hint, testId }) {
  return (
    <div className={`rounded-xl border p-4 ${tone === "bad" ? "border-red-500/30 bg-red-500/5"
      : tone === "warn" ? "border-amber-500/30 bg-amber-500/5" : "border-border bg-card"}`}
      data-testid={testId}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-bold text-foreground mt-1">{value}</p>
      {hint && <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>}
    </div>
  );
}

function Card({ title, icon: Icon, link, linkLabel, children, testId }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4" data-testid={testId}>
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-foreground flex items-center gap-2">
          {Icon && <Icon className="w-4 h-4 text-primary" />} {title}
        </h2>
        {link && (
          <Link to={link} className="text-xs text-primary hover:underline">{linkLabel || "Отвори"}</Link>
        )}
      </div>
      {children}
    </section>
  );
}

function TruncationNote({ shown, total, testId }) {
  if (!total || shown >= total) return null;
  return (
    <p className="text-[11px] text-amber-500 mt-2" data-testid={testId}>
      Показани {shown} от {total}. Броячите са изчислени върху всички записи.
    </p>
  );
}

// ── Requests ─────────────────────────────────────────────────────────────────
function RequestsCard({ section }) {
  if (section?.status !== "ok") {
    return <Card title="Заявки" icon={ClipboardList} testId="lo-requests"><SectionError section={section} name="requests" /></Card>;
  }
  const items = section.items || [];
  return (
    <Card title="Активни заявки" icon={ClipboardList} link={section.link} linkLabel="Към заявките" testId="lo-requests">
      <p className="text-[11px] text-muted-foreground mb-2">
        Просрочена = {section.overdue_rule} Частично изпълнени: <b>няма данни</b> — {section.partial?.reason}
      </p>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground py-6 text-center" data-testid="lo-requests-empty">Няма отворени заявки.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Заявка</TableHead>
              <TableHead>Обект</TableHead>
              <TableHead>Статус</TableHead>
              <TableHead>Нужна до</TableHead>
              <TableHead className="text-right">Редове</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((r) => (
              <TableRow key={r.id} data-testid={`lo-request-${r.id}`}>
                <TableCell><Link to={r.link} className="text-primary hover:underline">{r.request_number || "Без номер"}</Link></TableCell>
                <TableCell>{r.project_name || <span className="text-muted-foreground">Неизвестен обект</span>}</TableCell>
                <TableCell>{r.status_label}</TableCell>
                <TableCell>
                  {r.needed_date ? fmtDate(r.needed_date) : <span className="text-muted-foreground">без срок</span>}
                  {r.overdue && <Badge variant="destructive" className="ml-2">Просрочена</Badge>}
                </TableCell>
                <TableCell className="text-right">{r.lines_count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <TruncationNote shown={items.length} total={section.items_total} testId="lo-requests-truncated" />
      <SourceLine section={section} testId="lo-requests-source"
        extra={<span>Последна промяна: {fmtDateTime(section.last_change_at)}</span>} />
    </Card>
  );
}

// ── Warehouses ───────────────────────────────────────────────────────────────
function WarehousesCard({ section }) {
  const [openId, setOpenId] = useState(null);
  if (section?.status !== "ok") {
    return <Card title="Складове" icon={Warehouse} testId="lo-warehouses"><SectionError section={section} name="warehouses" /></Card>;
  }
  const whs = section.warehouses || [];
  return (
    <Card title="Складове и наличности" icon={Warehouse} link={section.link} linkLabel="Към складовете" testId="lo-warehouses">
      {section.trust !== "trusted" && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 mb-3 text-sm" role="status"
          data-testid="lo-stock-untrusted">
          <p className="font-medium text-amber-600 dark:text-amber-400 flex items-center gap-2">
            <ShieldAlert className="w-4 h-4" /> Наличностите са непроверени — не са доверени суми
          </p>
          <ul className="list-disc ml-5 mt-1 text-muted-foreground text-xs">
            {(section.trust_reasons || []).map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      )}
      {section.complete === false && (
        <p className="text-xs text-red-500 font-medium mb-2" role="status" data-testid="lo-stock-incomplete">
          Непълна проекция: {section.unprojectable_movements} движения не могат да се отразят в наличностите.
        </p>
      )}
      {whs.length === 0 ? (
        <p className="text-sm text-muted-foreground py-6 text-center" data-testid="lo-warehouses-empty">Няма складове.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Склад</TableHead>
              <TableHead>Тип</TableHead>
              <TableHead className="text-right">Позиции</TableHead>
              <TableHead className="text-right">Стойност (непроверена)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {whs.map((w) => (
              <WarehouseRow key={w.id} w={w} open={openId === w.id}
                onToggle={() => setOpenId(openId === w.id ? null : w.id)} />
            ))}
          </TableBody>
        </Table>
      )}
      <SourceLine section={section} testId="lo-warehouses-source"
        extra={<>
          <span>Движения: {section.movement_count} прочетени
            {section.complete === false ? `, ${section.unprojectable_movements} неотразени` : ", всички отразени"}</span>
          <span>Последно движение: {fmtDateTime(section.last_movement_at)}</span>
        </>} />
    </Card>
  );
}

function WarehouseRow({ w, open, onToggle }) {
  return (
    <>
      <TableRow data-testid={`lo-warehouse-${w.id}`}>
        <TableCell>
          <button type="button" onClick={onToggle} className="text-left" aria-expanded={open}
            data-testid={`lo-warehouse-toggle-${w.id}`}>
            <span className="font-medium text-foreground" data-testid={`lo-warehouse-name-${w.id}`}>{w.label}</span>
            {w.code && <span className="ml-2 text-[11px] text-muted-foreground font-mono"
              data-testid={`lo-warehouse-code-${w.id}`}>{w.code}</span>}
          </button>
          {w.is_legacy_main && <Badge variant="outline" className="ml-2 border-amber-500 text-amber-600">legacy „main“</Badge>}
          {w.active === false && <Badge variant="outline" className="ml-2">неактивен</Badge>}
        </TableCell>
        <TableCell className="text-muted-foreground">{w.type_label}</TableCell>
        <TableCell className="text-right">
          {w.stock_positions}
          {w.negative_positions > 0 && <Badge variant="destructive" className="ml-2">{w.negative_positions} отриц.</Badge>}
        </TableCell>
        <TableCell className="text-right text-muted-foreground">
          {formatCurrency(w.stock_value_unverified, "EUR")}
        </TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={4} className="bg-muted/30">
            {w.items.length === 0 ? (
              <p className="text-xs text-muted-foreground">Няма положителни наличности.</p>
            ) : (
              <ul className="text-xs grid grid-cols-2 gap-x-6 gap-y-1" data-testid={`lo-warehouse-items-${w.id}`}>
                {w.items.map((it) => (
                  <li key={`${it.material_name}|${it.unit}`} className="flex justify-between">
                    <span>{it.material_name || "Без име"}</span>
                    <span className="font-mono">{fmtQty(it.qty)} {it.unit}</span>
                  </li>
                ))}
              </ul>
            )}
            <TruncationNote shown={w.items.length} total={w.items_total} testId={`lo-warehouse-items-truncated-${w.id}`} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

// ── Assets ───────────────────────────────────────────────────────────────────
function AssetIndicators({ section }) {
  if (section?.status !== "ok") return null;
  return (
    <Card title="Машини и инструменти" icon={Wrench} link={section.link} linkLabel="Към активите" testId="lo-asset-indicators">
      <ul className="space-y-1 text-sm">
        {INDICATOR_ORDER.map((k) => (
          <li key={k} className="flex items-center justify-between" data-testid={`lo-indicator-${k}`}>
            <span className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${INDICATOR_STYLE[k].dot}`} /> {INDICATOR_LABEL[k]}
            </span>
            <span className="font-semibold">{section.counts?.[k] ?? 0}</span>
          </li>
        ))}
        <li className="flex items-center justify-between text-muted-foreground" data-testid="lo-indicator-overdue">
          <span className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-red-500" /> Просрочени</span>
          <span title={section.overdue?.reason}>няма данни</span>
        </li>
      </ul>
      <p className="text-[11px] text-muted-foreground mt-2">{section.overdue?.reason}</p>
      <SourceLine section={section} testId="lo-asset-indicators-source" />
    </Card>
  );
}

function AssetsCard({ section }) {
  if (section?.status !== "ok") {
    return <Card title="Активи" icon={Wrench} testId="lo-assets"><SectionError section={section} name="assets" /></Card>;
  }
  const items = section.items || [];
  return (
    <Card title="Активи — местоположение и отговорност" icon={Wrench} link={section.link} linkLabel="Към активите" testId="lo-assets">
      {section.pending_handovers > 0 && (
        <p className="text-[11px] text-amber-600 dark:text-amber-400 mb-2" data-testid="lo-legacy-handover-note">
          {section.legacy_handover_note}
        </p>
      )}
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground py-6 text-center" data-testid="lo-assets-empty">Няма активи.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Актив</TableHead>
              <TableHead>Състояние</TableHead>
              <TableHead>Местоположение</TableHead>
              <TableHead>Приет отговорник</TableHead>
              <TableHead>Чакащо предаване</TableHead>
              <TableHead>Ремонт</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((u) => (
              <TableRow key={u.id} data-testid={`lo-asset-${u.id}`}>
                <TableCell>
                  <Link to={u.link} className="text-primary hover:underline">{u.name}</Link>
                  {u.qr_id && <span className="ml-2 text-[11px] text-muted-foreground font-mono">{u.qr_id}</span>}
                </TableCell>
                <TableCell>
                  <span className={`flex items-center gap-2 ${INDICATOR_STYLE[u.indicator]?.text || ""}`}>
                    <span className={`w-2.5 h-2.5 rounded-full ${INDICATOR_STYLE[u.indicator]?.dot || "bg-zinc-400"}`} />
                    {u.indicator_label}
                  </span>
                </TableCell>
                <TableCell>
                  {u.location?.resolved
                    ? <><span className="text-muted-foreground text-xs">{u.location.type_label}: </span>{u.location.name}</>
                    : <span className="text-amber-600">{u.location?.type_label} — неразпозната</span>}
                </TableCell>
                <TableCell data-testid={`lo-asset-accepted-${u.id}`}>
                  {u.accepted_custodian
                    ? <>{u.accepted_custodian.name}<span className="block text-[11px] text-muted-foreground">от {fmtDate(u.accepted_custodian.since)}</span></>
                    : <span className="text-muted-foreground">няма потвърден</span>}
                </TableCell>
                <TableCell data-testid={`lo-asset-pending-${u.id}`}>
                  {u.pending_handover
                    ? <Badge variant="outline" className="border-amber-500 text-amber-600">
                        <Clock className="w-3 h-3 mr-1" /> Чака приемане: {u.pending_handover.to_name}
                      </Badge>
                    : <span className="text-muted-foreground">—</span>}
                </TableCell>
                <TableCell>
                  {u.repair
                    ? <span className="text-orange-500">{u.repair.service || "Сервиз"} · от {fmtDate(u.repair.since)}</span>
                    : <span className="text-muted-foreground">—</span>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <TruncationNote shown={items.length} total={section.items_total} testId="lo-assets-truncated" />
      <SourceLine section={section} testId="lo-assets-source" />
    </Card>
  );
}

// ── Integrity + audit ────────────────────────────────────────────────────────
function IntegrityCard({ warnings, generatedAt }) {
  return (
    <Card title="Предупреждения за цялост" icon={AlertTriangle} testId="lo-integrity">
      {warnings.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="lo-integrity-empty">Няма открити предупреждения.</p>
      ) : (
        <ul className="space-y-2">
          {warnings.map((w, i) => (
            <li key={`${w.code}-${i}`} className={`rounded-lg border p-2 text-xs ${SEVERITY_STYLE[w.severity] || SEVERITY_STYLE.info}`}
              data-testid={`lo-warning-${w.code}`}>
              <p className="font-medium text-foreground flex justify-between gap-2">
                <span>{w.title}</span>
                {w.count != null && <span className="font-mono">{w.count}</span>}
              </p>
              <p className="text-muted-foreground mt-0.5">{w.detail}</p>
              {w.link && <Link to={w.link} className="text-primary hover:underline">Виж</Link>}
            </li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-muted-foreground mt-2" data-testid="lo-integrity-source">
        Източник: изведено от секциите заявки, склад, активи и журнал · Изчислено: {fmtDateTime(generatedAt)}
      </p>
    </Card>
  );
}

function AuditCard({ section }) {
  return (
    <Card title="Последна активност (каноничен AuditEvent)" icon={Activity} testId="lo-audit">
      {section?.status === "available" ? (
        <ul className="text-xs space-y-1" data-testid="lo-audit-events">
          {section.events.map((e) => (
            <li key={e.event_id} className="flex justify-between gap-3">
              <span>{e.action} · {e.entity_type}</span>
              <span className="text-muted-foreground">{fmtDateTime(e.occurred_at)}</span>
            </li>
          ))}
        </ul>
      ) : section?.status === "unavailable" ? (
        <p className="text-sm text-muted-foreground" data-testid="lo-audit-unavailable">{section.message}</p>
      ) : (
        <SectionError section={section} name="audit" />
      )}
      <SourceLine section={section} testId="lo-audit-source" />
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function LiveOpsControlCenterPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await API.get("/live-ops/control-center");
      setData(res.data);
      setLoadedAt(Date.now());
    } catch (err) {
      const status = err?.response?.status;
      setError(status === 403
        ? "Нямате права за контролния център."
        : "Контролният център не можа да бъде зареден. Не са показани стари или частични данни.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  const stale = loadedAt != null && now - loadedAt > STALE_AFTER_MS;

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2" data-testid="lo-loading">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">Зареждане на контролния център…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-6 max-w-xl" data-testid="lo-error">
        <div className="rounded-xl border border-red-500/40 bg-red-500/5 p-4" role="alert">
          <p className="font-medium text-red-500 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> {error}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={load} data-testid="lo-retry">
            <RefreshCw className="w-4 h-4 mr-1" /> Опитай отново
          </Button>
        </div>
      </div>
    );
  }
  if (!data) return null;

  const rq = data.requests?.status === "ok" ? data.requests : null;
  const as = data.assets?.status === "ok" ? data.assets : null;
  const integrity = data.integrity || [];
  const critical = integrity.filter((w) => w.severity === "critical").length;

  return (
    <div className="p-6 max-w-[1600px]" data-testid="live-ops-control-center">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Eye className="w-6 h-6 text-primary" /> LIVE-OPS контролен център
            <Badge variant="outline" className="ml-1" data-testid="lo-read-only-badge">
              <Lock className="w-3 h-3 mr-1" /> Само за четене
            </Badge>
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Заявки, складове и машини на едно място. Промени се правят само в съответните екрани.
          </p>
        </div>
        <div className="text-right">
          <p className={`text-xs ${stale ? "text-amber-500 font-medium" : "text-muted-foreground"}`} data-testid="lo-freshness">
            {stale ? "Остарели данни — обновете. " : ""}Данни към {fmtDateTime(data.generated_at)}
          </p>
          <Button variant="outline" size="sm" className="mt-1" onClick={load} disabled={loading} data-testid="lo-refresh">
            {loading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1" />} Обнови
          </Button>
        </div>
      </div>

      <section className="mb-5" aria-label="Обобщени показатели" data-testid="lo-kpis">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <Kpi testId="lo-kpi-open" label="Отворени заявки" value={rq ? rq.counts.open : "—"} />
        <Kpi testId="lo-kpi-pending" label="Чакат решение" value={rq ? rq.counts.pending : "—"} tone={rq?.counts.pending ? "warn" : undefined} />
        <Kpi testId="lo-kpi-overdue" label="Просрочени заявки" value={rq ? rq.counts.overdue : "—"} tone={rq?.counts.overdue ? "bad" : undefined}
          hint={rq?.counts.open_without_needed_date ? `${rq.counts.open_without_needed_date} без срок` : undefined} />
        <Kpi testId="lo-kpi-handover" label="Чакащи предавания" value={as ? as.pending_handovers : "—"} tone={as?.pending_handovers ? "warn" : undefined} />
        <Kpi testId="lo-kpi-repair" label="В ремонт" value={as ? as.open_repairs : "—"} />
        <Kpi testId="lo-kpi-critical" label="Критични предупреждения" value={critical} tone={critical ? "bad" : undefined} />
      </div>
      <p className="text-[11px] text-muted-foreground mt-2 flex flex-wrap gap-x-3" data-testid="lo-kpi-source">
        <span>Източник: заявки — {data.requests?.source || "няма данни"}; ремонт и предавания — {data.assets?.source || "няма данни"}; предупреждения — изведени</span>
        <span>Изчислено: {fmtDateTime(data.generated_at)}</span>
      </p>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 space-y-4">
          <RequestsCard section={data.requests} />
          <WarehousesCard section={data.warehouses} />
          <AssetsCard section={data.assets} />
        </div>
        <div className="space-y-4">
          <IntegrityCard warnings={integrity} generatedAt={data.generated_at} />
          <AssetIndicators section={data.assets} />
          <AuditCard section={data.audit} />
        </div>
      </div>
    </div>
  );
}
