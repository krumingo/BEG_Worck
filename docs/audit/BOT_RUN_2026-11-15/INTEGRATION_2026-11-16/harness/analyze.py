"""Analyzer for the role-bot run: frontend ↔ backend ↔ database, and business rules.
Reads run/*.jsonl, writes run/summary.json and run/report.html. Read-only on the demo DB."""
import json, re, os, time, html, collections
from pymongo import MongoClient

RUN = "/tmp/claude-0/demo_int/run"
START = float(open(f"{RUN}/run_start.txt").read().strip())
SEED = json.load(open(f"{RUN}/seed.json"))
UID2ROLE = {v.get("id"): r for r, v in SEED["users"].items() if v.get("id")}

def load(name, offset_file=None):
    p = f"{RUN}/{name}"
    if not os.path.exists(p):
        return []
    lines = open(p, encoding="utf8").read().splitlines()
    if offset_file and os.path.exists(f"{RUN}/{offset_file}"):
        lines = lines[int(open(f"{RUN}/{offset_file}").read().strip()):]
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return [d for d in out if d.get("t", START) >= START - 5]

FE = [d for d in load("fe_network.jsonl") if not d.get("blocked")]
BLOCKED = [d for d in load("fe_network.jsonl") if d.get("blocked")]
BE = load("backend.jsonl", "backend_offset.txt")
DB = load("db.jsonl", "db_offset.txt")
ACT = load("fe_actions.jsonl")
ERR = load("fe_errors.jsonl")
PROC = load("process.jsonl")
_starts = [i for i, p in enumerate(PROC) if p.get("flow") == "run" and p.get("step") == "start"]
PROC = PROC[_starts[-1]:] if _starts else PROC   # only the detached run, not the trial runs

def norm(p):
    p = p.split("?")[0]
    p = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "{id}", p)
    p = re.sub(r"/\d+(?=/|$)", "/{n}", p)
    p = re.sub(r"\d{4}-\d{2}-\d{2}", "{date}", p)
    return p

def role_of_be(d):
    return d.get("bot") or UID2ROLE.get(d.get("user")) or "?"

# ── 1. frontend → backend correspondence ─────────────────────────────
be_index = collections.defaultdict(list)
for d in BE:
    be_index[(d["method"], d["path"], d.get("bot"))].append(d["t"])
unmatched = []
for d in FE:
    if d.get("status") == "FAILED":
        unmatched.append(d)
        continue
    key = (d["method"], d["url"].split("?")[0], d["role"])
    ts = be_index.get(key, [])
    if not any(abs(t - d["t"]) < 3 for t in ts):
        unmatched.append(d)

def bucket(s):
    if not isinstance(s, int):
        return str(s)
    return f"{s // 100}xx" if s not in (401, 403, 404, 405, 409, 422) else str(s)

status_by_role = collections.defaultdict(collections.Counter)
for d in FE:
    status_by_role[d["role"]][bucket(d.get("status"))] += 1

def group(rows, keyf, n=40):
    c = collections.Counter(keyf(r) for r in rows)
    return c.most_common(n)

route_missing = [d for d in FE if d.get("status") in (404, 405) and ('"Not Found"' in (d.get("resp") or "") or d.get("status") == 405)]
shape = [d for d in FE if d.get("status") == 422]
crash = [d for d in FE if isinstance(d.get("status"), int) and d["status"] >= 500]
crash_be = [d for d in BE if isinstance(d.get("status"), int) and d["status"] >= 500]
forbidden = [d for d in FE if d.get("status") == 403]
unauth = [d for d in FE if d.get("status") == 401]

# ── 2. backend → database ────────────────────────────────────────────
MUT = {"POST", "PUT", "PATCH", "DELETE"}
READ_LIKE = re.compile(r"/auth/login|/auth/refresh|mark-read|/search|/preview|/calculate|/estimate|/validate|/check|/ai/|/export|/report")
db_times = sorted((d["t"], i) for i, d in enumerate(DB))
import bisect
dt = [x[0] for x in db_times]
def changes_in(t0, t1):
    a, b = bisect.bisect_left(dt, t0), bisect.bisect_right(dt, t1)
    return [DB[db_times[k][1]] for k in range(a, b)]

ok_no_write, mut_no_audit = [], []
covered = set()
for d in BE:
    if d["method"] not in MUT or not isinstance(d["status"], int) or not (200 <= d["status"] < 300):
        continue
    ch = changes_in(d["t"] - 0.05, d["t"] + d["ms"] / 1000 + 1.0)
    for c in ch:
        covered.add(id(c))
    real = [c for c in ch if c["coll"] not in ("audit_logs", "audit_events", "idempotency_keys", "money_write_keys")]
    if not ch and not READ_LIKE.search(d["path"]):
        ok_no_write.append(d)
    if real and not any(c["coll"] in ("audit_logs", "audit_events") for c in ch):
        mut_no_audit.append((d, sorted({c["coll"] for c in real})))

# DB changes with no write request around them (reads that write, or jobs)
mut_windows = sorted((d["t"] - 0.05, d["t"] + d["ms"] / 1000 + 1.0) for d in BE if d["method"] in MUT)
def in_mut(t):
    k = bisect.bisect_right([w[0] for w in mut_windows], t) - 1
    for j in range(max(0, k - 30), k + 1):
        if mut_windows[j][0] <= t <= mut_windows[j][1]:
            return True
    return False
writes_without_mut = [c for c in DB if not in_mut(c["t"])]
no_org = [c for c in DB if c.get("has_org") is False and c["op"] in ("insert", "replace") and c["coll"] not in ("audit_events", "audit_idempotency")]  # these carry tenant_id by design
deletes = [c for c in DB if c["op"] == "delete"]

# ── 3. business rules on the final demo database ─────────────────────
cli = MongoClient("mongodb://127.0.0.1:27161/?directConnection=true", serverSelectionTimeoutMS=5000)
db = cli["demoint_begwork"]
def agg(coll, pipe):
    try:
        return list(db[coll].aggregate(pipe, maxTimeMS=20000))
    except Exception as e:
        return [{"error": str(e)[:200]}]
rules = {
  "Q1 фактурни редове към обект по статус на фактурата (CLAUDE §7)": agg("invoice_lines", [
      {"$match": {"$or": [{"allocations.type": "project"}, {"allocation_type": "project"}]}},
      {"$lookup": {"from": "invoices", "localField": "invoice_id", "foreignField": "id", "pipeline": [{"$project": {"_id": 0, "status": 1}}], "as": "inv"}},
      {"$project": {"_id": 0, "a": "$line_total_ex_vat", "st": {"$ifNull": [{"$first": "$inv.status"}, "MISSING_INVOICE"]}}},
      {"$group": {"_id": "$st", "lines": {"$sum": 1}, "sum_ex_vat": {"$sum": "$a"}}}]),
  "Q2 траншове по договори с бригади (FLOW-006)": agg("contract_payments", [
      {"$unwind": "$tranches"}, {"$group": {"_id": "$tranches.status", "n": {"$sum": 1}, "sum": {"$sum": "$tranches.amount"}}}]),
  "Q3 одобрени дневни отчети: формат × статус на плащане (FLOW-028)": agg("employee_daily_reports", [
      {"$match": {"approval_status": "APPROVED"}},
      {"$group": {"_id": {"format": {"$cond": [{"$ifNull": ["$worker_id", False]}, "нов (worker_id)", "стар (employee_id)"]}, "payroll": {"$ifNull": ["$payroll_status", "none"]}}, "n": {"$sum": 1}}}]),
  "Q4 ръчни редове за труд (Р96)": agg("labor_entries", [
      {"$group": {"_id": {"source": {"$ifNull": ["$source", "none"]}, "approval": {"$ifNull": ["$approval_status", "none"]}}, "n": {"$sum": 1}, "hours": {"$sum": "$hours"}}}]),
  "Двойни дневни отчети за човек и ден": agg("employee_daily_reports", [
      {"$group": {"_id": {"p": {"$ifNull": ["$worker_id", "$employee_id"]}, "d": {"$ifNull": ["$report_date", "$date"]}}, "n": {"$sum": 1}}},
      {"$match": {"n": {"$gt": 1}}}, {"$count": "people_days_with_more_than_one_report"}]),
  "Повтарящ се номер на фактура": agg("invoices", [
      {"$group": {"_id": {"no": "$invoice_no", "dir": "$direction"}, "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}, {"$count": "duplicate_numbers"}]),
  "Повтарящ се код на обект": agg("projects", [
      {"$group": {"_id": "$code", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}, {"$count": "duplicate_codes"}]),
  "Аванси по човек и ден, повече от един": agg("advances", [
      {"$group": {"_id": {"u": "$user_id", "d": {"$substr": [{"$ifNull": ["$created_at", ""]}, 0, 10]}, "a": "$amount"}, "n": {"$sum": 1}}},
      {"$match": {"n": {"$gt": 1}}}, {"$count": "same_person_day_amount_more_than_once"}]),
  "Плащания в регистъра по вид": agg("finance_payments", [
      {"$group": {"_id": {"dir": "$direction", "status": {"$ifNull": ["$status", "?"]}}, "n": {"$sum": 1}, "sum": {"$sum": "$amount"}}}]),
}

# ── 4. UI ────────────────────────────────────────────────────────────
js_crash = [e for e in ERR if e["kind"] == "pageerror"]
console = [e for e in ERR if e["kind"] == "console" and "ERR_FAILED" not in e["text"]]
bot_err = [e for e in ERR if e["kind"].startswith("bot")]
pages = collections.defaultdict(set)
acts = collections.defaultdict(collections.Counter)
for a in ACT:
    if a["kind"] == "visit":
        pages[a["role"]].add(norm(a["label"]))
    acts[a["role"]][a["kind"]] += 1

proc_bad = [p for p in PROC if p.get("ok") is False]
proc_unknown = [p for p in PROC if p.get("ok") is None]

S = {
  "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "minutes": round(((json.load(open(f"{RUN}/bots_done.json"))["done"] if os.path.exists(f"{RUN}/bots_done.json") else time.time()) - START) / 60),
  "fe_requests": len(FE), "be_requests": len(BE), "db_changes": len(DB), "actions": len(ACT),
  "fe_not_reaching_backend": len(unmatched), "route_missing": len(route_missing), "422": len(shape), "5xx_fe": len(crash), "5xx_be": len(crash_be),
  "403": len(forbidden), "401": len(unauth), "ok_without_db_write": len(ok_no_write), "write_without_audit": len(mut_no_audit),
  "db_change_without_write_request": len(writes_without_mut), "insert_without_org_id": len(no_org), "hard_deletes": len(deletes),
  "js_crashes": len(js_crash), "console_errors": len(console), "process_violations": len(proc_bad), "process_unverified": len(proc_unknown),
}
json.dump({"summary": S, "rules": rules}, open(f"{RUN}/summary.json", "w"), ensure_ascii=False, indent=1, default=str)

# ── report ───────────────────────────────────────────────────────────
E = lambda s: html.escape(str(s))
def table(head, rows):
    if not rows:
        return '<p class="none">Няма.</p>'
    return ('<div class="tbl"><table><thead><tr>' + "".join(f"<th>{E(h)}</th>" for h in head) + "</tr></thead><tbody>" +
            "".join("<tr>" + "".join(f"<td>{E(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")
def sec(title, why, body, sev="data", n=None):
    chip = f'<span class="chip {sev}">{n}</span>' if n is not None else ""
    return f'<section class="box"><h3>{E(title)} {chip}</h3><p class="why">{E(why)}</p>{body}</section>'

def _grouped(rows):
    g = collections.OrderedDict()
    for p in rows:
        g.setdefault((p["flow"], p["step"]), []).append(p)
    return table(["Процес", "Стъпка", "Роля", "Заявка", "Пъти", "Очаквано", "Получено (първи път)", "Правило"],
                 [[k[0], k[1], v[0].get("role"), f'{v[0].get("method","")} {norm(v[0].get("path",""))}', len(v), v[0].get("expected"), v[0].get("actual"), v[0].get("note")] for k, v in g.items()])
parts = []
parts.append(sec("Процеси под лупа: нарушени правила", "Процесните ботове минават цял процес през сървъра и след всяка стъпка сравняват резултата с правилото.",
  _grouped(proc_bad), "pay", f"{len(proc_bad)} пъти, {len({(p['flow'], p['step']) for p in proc_bad})} правила"))
parts.append(sec("Процеси: какво не можах да проверя", "Стъпки без отговор „да/не“: или не са нарушение по дефиниция, или средата не позволява проверка.",
  table(["Процес", "Стъпка", "Брой", "Бележка"], [[k[0], k[1], v, k[2]] for k, v in collections.Counter((p["flow"], p["step"], str(p.get("note"))) for p in proc_unknown).most_common()]), "low", len(proc_unknown)))
VER = [
 ("F4-advance", "Аванс без защита от повторна заявка и директен запис в плащанията", "routes/hr.py:237 create_advance"),
 ("F2 / PARI-02", "„Платен транш“ само сменя статуса, сумата влиза в печалбата", "routes/hr.py:900-930, services/project_pnl.py:103-112"),
 ("F1-B4 / SKLAD-01", "Материалният разход брои редове на анулирани фактури", "services/canonical_material_cost.py:301-315, routes/finance.py:1240-1271"),
 ("F3 / TRUD-02", "Отчетите по втория път се пишат с employee_id, маркирането „платен“ търси worker_id", "routes/daily_reports.py:217, services/payroll_sync.py:105-120"),
 ("Без одит", "Създаване на липсващо СМР не пише одитен запис", "app/routes/missing_smr.py:101-150"),
 ("Без одит", "Генериране на QR код не пише одитен запис", "app/routes/assets_qr.py:156-180"),
 ("Права екран↔сървър", "Екраните „Служители“, „Служител“ и „Календар на работниците“ се отварят за SiteManager, сървърът му отказва (празен екран)", "frontend/src/App.js:151 ADMIN_ROLES срещу app/routes/hr.py:30-32 payroll_permission"),
]
parts.append(sec("Проверено лично в кода", "Тези находки от ботовете са сверени с реда в кода (main de720f94). Останалите са кандидати.",
  table(["Находка", "Какво", "Къде"], VER), "pay", len(VER)))
parts.append(sec("Сървърът се срива (5xx)", "Екранът е поискал нещо и сървърът е върнал вътрешна грешка.",
  table(["Заявка", "Брой", "Роли"], [[k, v, ", ".join(sorted({d["role"] for d in crash if f'{d["method"]} {norm(d["url"])}' == k}))] for k, v in group(crash, lambda d: f'{d["method"]} {norm(d["url"])}')]), "pay", len(crash)))
parts.append(sec("Екранът вика адрес, който сървърът няма (404/405)", "Несъответствие между frontend и backend: бутонът или страницата сочи към несъществуващ endpoint.",
  table(["Заявка", "Брой", "Страница (пример)"], [[k, v, next(d["page"] for d in route_missing if f'{d["method"]} {norm(d["url"])}' == k)] for k, v in group(route_missing, lambda d: f'{d["method"]} {norm(d["url"])}')]), "data", len(route_missing)))
parts.append(sec("Екранът праща данни в грешен вид (422)", "Формата изпраща полета, които сървърът не приема.",
  table(["Заявка", "Брой", "Отговор (пример)"], [[k, v, next((d.get("resp") or "")[:160] for d in shape if f'{d["method"]} {norm(d["url"])}' == k)] for k, v in group(shape, lambda d: f'{d["method"]} {norm(d["url"])}')]), "data", len(shape)))
parts.append(sec("Екранът показва действие, което ролята няма право да прави (403)", "Бутонът е видим, но сървърът отказва. Или правата в екрана и в сървъра се разминават, или ботът е стигнал до чужд екран.",
  table(["Роля", "Заявка", "Брой"], [[k.split(" | ")[0], k.split(" | ")[1], v] for k, v in group(forbidden, lambda d: f'{d["role"]} | {d["method"]} {norm(d["url"])}', 60)]), "sec", len(forbidden)))
parts.append(sec("Сървърът казва „готово“, но в базата няма промяна", "Успешна заявка за запис (2xx), след която в базата не се появява нищо. Кандидати: при едновременна работа е възможна грешна връзка.",
  table(["Заявка", "Брой"], group(ok_no_write, lambda d: f'{d["method"]} {norm(d["path"])}')), "data", len(ok_no_write)))
parts.append(sec("Запис без одитен запис", "Промяна в бизнес таблица, без запис в audit_logs/audit_events в същия момент (CLAUDE.md §2.8, FLOW-040).",
  table(["Заявка", "Таблици", "Брой"], [[k.split(" → ")[0], k.split(" → ")[1], v] for k, v in group(mut_no_audit, lambda x: f'{x[0]["method"]} {norm(x[0]["path"])} → {", ".join(x[1])}')]), "data", len(mut_no_audit)))
parts.append(sec("Физическо изтриване", "Записи, изтрити от базата (CLAUDE.md §2.9: без hard delete на използвани, финансови или одобрени записи).",
  table(["Таблица", "Брой"], group(deletes, lambda c: c["coll"])), "data", len(deletes)))
parts.append(sec("Промени в базата без заявка за запис", "Промяна в базата, когато никой не е изпращал запис: четене, което пише, или фонова задача.",
  table(["Таблица и операция", "Брой"], group(writes_without_mut, lambda c: f'{c["coll"]} {c["op"]}')), "low", len(writes_without_mut)))
parts.append(sec("Записи без фирма (org_id)", "Нов запис без org_id (Tenant Guard).",
  table(["Таблица", "Брой"], group(no_org, lambda c: c["coll"])), "sec", len(no_org)))
parts.append(sec("Сривове в екрана (JavaScript)", "Грешка в браузъра, която спира част от екрана.",
  table(["Грешка", "Брой", "Страница"], [[k[:160], v, next(e["url"] for e in js_crash if e["text"] == k).replace("http://localhost:8767", "")] for k, v in group(js_crash, lambda e: e["text"])]), "data", len(js_crash)))
parts.append(sec("Правила върху крайната демо база", "Заявките от одобрения план (само бройки и суми), пуснати върху демо базата, плюс проверки за двойни записи.",
  "".join(f"<h4>{E(k)}</h4>" + table(["Група", "Стойности"], [[json.dumps(r.get("_id", ""), ensure_ascii=False), json.dumps({x: y for x, y in r.items() if x != "_id"}, ensure_ascii=False)] for r in v]) for k, v in rules.items()), "pay"))
parts.append(sec("Отговори по роля (от екрана)", "Колко заявки е изпратил всеки бот и с какъв резултат.",
  table(["Роля"] + ["2xx", "401", "403", "404", "405", "409", "422", "5xx", "FAILED"], [[r] + [c.get(k, 0) for k in ["2xx", "401", "403", "404", "405", "409", "422", "5xx", "FAILED"]] for r, c in sorted(status_by_role.items())]), "low"))
parts.append(sec("Покритие по роля", "Колко различни екрана е отворил всеки бот и какво е правил.",
  table(["Роля", "Екрани", "Действия"], [[r, len(pages[r]), ", ".join(f"{k} {v}" for k, v in acts[r].most_common())] for r in sorted(acts)]), "low"))
parts.append(sec("Заявки от екрана, които не са стигнали до сървъра", "Екранът е изпратил заявка, но сървърът няма запис за нея (прекъсната връзка, CORS, спрян процес).",
  table(["Заявка", "Брой"], group(unmatched, lambda d: f'{d["method"]} {norm(d["url"])} [{d.get("status")}]')), "low", len(unmatched)))

stalled = [r for r in sorted(acts) if acts[r]["visit"] < 20]
if stalled:
    parts.insert(0, sec("Граница на проверката: ботове, които спряха", "Тези ботове блокираха в първите секунди и не работиха 3 часа. Резултатите за техните роли не са проверка. Реално през екрана работиха само: " + ", ".join(r for r in sorted(acts) if r not in stalled) + ". Причината е в бота (действие без краен срок), не е доказано, че е в програмата: същият екран се отваря нормално при отделна проба.",
      table(["Роля", "Последно действие", "Екран"], [[r, next((a["kind"] + " " + a["label"]) for a in reversed(ACT) if a["role"] == r), next(a["url"].replace("http://localhost:8767", "") for a in reversed(ACT) if a["role"] == r)] for r in stalled]), "data", len(stalled)))
tiles = [("минути работа", S["minutes"]), ("заявки от екраните", S["fe_requests"]), ("промени в базата", S["db_changes"]), ("нарушени правила в процесите", S["process_violations"]),
         ("сривове на сървъра", S["5xx_fe"]), ("адреси, които сървърът няма", S["route_missing"]), ("грешен вид данни (422)", S["422"]), ("отказани права (403)", S["403"]),
         ("„готово“ без запис", S["ok_without_db_write"]), ("запис без одит", S["write_without_audit"]), ("физически изтривания", S["hard_deletes"]), ("сривове в екрана", S["js_crashes"])]
page = open("/tmp/claude-0/demo_int/report_tpl.html", encoding="utf8").read()
page = page.replace("{{GEN}}", E(S["generated"])).replace("{{TILES}}", "".join(f'<div class="tile"><div class="num">{v}</div><div class="cap">{E(k)}</div></div>' for k, v in tiles)).replace("{{PARTS}}", "\n".join(parts))
open(f"{RUN}/report.html", "w", encoding="utf8").write(page)
print(json.dumps(S, ensure_ascii=False))
