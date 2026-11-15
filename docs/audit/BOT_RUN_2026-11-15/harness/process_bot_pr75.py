#!/usr/bin/env python
"""Process bots for the BEG_Work demo: whole business processes through the real API,
as the right role, with a rule check after every step. Writes run/process.jsonl.

Only synthetic demo data (demo75_begwork). Mongo is READ ONLY here (verification)."""
import argparse, json, os, sys, time, uuid, threading, traceback
from datetime import date, datetime, timedelta, timezone
import requests, pymongo

B = "http://localhost:8766/api"
RUN = "/tmp/claude-0/demo75/run"
OUT = os.path.join(RUN, "process.jsonl")
STATE = os.path.join(RUN, "process_state.json")
SEED = json.load(open(os.path.join(RUN, "seed.json")))
MDB = pymongo.MongoClient("mongodb://127.0.0.1:27021/?directConnection=true&replicaSet=rs0").demo75_begwork
WH = "e8974e43-733b-4c51-9ea9-27f36b6b1c2a"
ITEM = "9fdfcec2-1ba3-41df-98ad-09d72d865cf8"
W = SEED["workers"]
WNAME = {W[0]: "Иван Работник", W[1]: "Петър Работник", W[2]: "Георги Работник"}
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

_lock = threading.Lock()
TOK = {}


def now():
    return time.time()


def rec(flow, step, role, method, path, status, expected, actual, ok, note=""):
    row = {"t": round(now(), 3), "flow": flow, "step": step, "role": role, "method": method,
           "path": path, "status": status, "expected": expected, "actual": actual, "ok": ok, "note": note}
    with _lock:
        with open(OUT, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    flag = {True: "ok ", False: "BAD", None: "?? "}[ok]
    print(f"{flag} {flow} {step} {role} {method} {path} {status} | {str(actual)[:160]}", flush=True)


def login(role):
    u = SEED["users"][role]
    r = requests.post(B + "/auth/login", json={"email": u["email"], "password": u["password"]}, timeout=30)
    r.raise_for_status()
    TOK[role] = r.json()["token"]


def api(role, method, path, body=None, key=None, params=None, retry=True):
    if role not in TOK:
        login(role)
    h = {"Authorization": "Bearer " + TOK[role], "x-bot-role": "proc-" + role}
    if method != "GET":
        h["Idempotency-Key"] = key or str(uuid.uuid4())
    r = requests.request(method, B + path, json=body, headers=h, params=params, timeout=60)
    if r.status_code == 401 and retry:
        TOK.pop(role, None)
        return api(role, method, path, body, h.get("Idempotency-Key"), params, retry=False)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, r.text[:400]


def short(txt):
    return (txt or "")[:300]


class Stop(Exception):
    """Abort the current process; continue with the next."""


def must(flow, step, role, method, path, st, txt, ok_codes=(200, 201), expected=None):
    if st not in ok_codes:
        rec(flow, step, role, method, path, st, expected or f"HTTP {ok_codes}", short(txt), None,
            "грешка от endpoint-а — процесът спира тук, продължава следващият")
        raise Stop()


def pnl(project):
    st, j, txt = api("Accountant", "GET", f"/projects/{project}/pnl")
    if st != 200:
        return None
    return j


def state_load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"day_offset": 0}


def state_save(s):
    json.dump(s, open(STATE, "w"))


# ── setup: one dedicated project per bot run (keeps P&L deltas clean of the UI bots) ──
def setup():
    tag = datetime.now().strftime("%H%M%S")
    body = {"code": f"PB-{tag}", "name": f"Процесен бот {tag}", "status": "Active", "budget_planned": 10000}
    st, j, txt = api("Admin", "POST", "/projects", body)
    rec("setup", "create_project", "Admin", "POST", "/projects", st, "201", short(txt) if st != 201 else j.get("id"),
        True if st == 201 else None)
    if st != 201:
        return SEED["projects"][0]
    pid = j["id"]
    for uid, rip in [(SEED["users"]["SiteManager"]["id"], "SiteManager"),
                     (SEED["users"]["Technician"]["id"], "Technician")] + [(w, "Technician") for w in W]:
        st, _, txt = api("Admin", "POST", f"/projects/{pid}/team", {"user_id": uid, "role_in_project": rip})
        if st not in (200, 201):
            rec("setup", "team", "Admin", "POST", f"/projects/{pid}/team", st, "201", short(txt), None)
    return pid


def cash_account():
    a = MDB.financial_accounts.find_one({"type": "Cash", "name": "Каса"}) or MDB.financial_accounts.find_one({})
    return a["id"]


# ── FLOW 1: supplier invoice → line allocated to project → payment → cancel ──
def flow1(P, cyc):
    F = "F1-supplier-invoice"
    mark = f"PB-INV-{cyc}-{uuid.uuid4().hex[:6]}"
    p0 = pnl(P)
    m0 = p0["expense"]["material_cost"] if p0 else None
    v0 = p0["vat"]["input_vat"] if p0 else None
    # A) finance-UI shape: embedded line with the project as destination
    body = {"direction": "Received", "invoice_no": mark, "counterparty_name": f"Доставчик Бот ООД {mark}", "project_id": P,
            "issue_date": TODAY, "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "currency": "EUR", "vat_percent": 20, "notes": mark,
            "lines": [{"description": "Цимент 25 кг", "unit": "торба", "qty": 10, "unit_price": 8.5, "project_id": P}]}
    st, j, txt = api("Accountant", "POST", "/finance/invoices", body)
    must(F, "1.create_invoice", "Accountant", "POST", "/finance/invoices", st, txt, (201,))
    inv = j["id"]
    rec(F, "1.create_invoice", "Accountant", "POST", "/finance/invoices", st, "201 Draft, ред 10×8.5 към обекта",
        {"status": j.get("status"), "subtotal": j.get("subtotal"), "total": j.get("total"),
         "line_dest": [(l.get("project_id"), l.get("allocations")) for l in j.get("lines", [])]}, j.get("status") == "Draft")
    st, j, txt = api("Accountant", "POST", f"/finance/invoices/{inv}/send")
    must(F, "2.send", "Accountant", "POST", f"/finance/invoices/{inv}/send", st, txt)
    total = j.get("total")
    rec(F, "2.send", "Accountant", "POST", f"/finance/invoices/{inv}/send", st, "Sent", j.get("status"), j.get("status") in ("Sent", "Overdue"),
        f"total={total}")
    p1 = pnl(P)
    if p0 and p1:
        d = round(p1["expense"]["material_cost"] - m0, 2)
        rec(F, "3.pnl_after_allocation", "Accountant", "GET", f"/projects/{P}/pnl", 200, "material_cost +85.00 (веднъж)",
            {"material_cost": f"{m0} → {p1['expense']['material_cost']}", "delta": d, "invoice_cost": p1["warehouse_cost_basis"].get("invoice_cost")},
            abs(d - 85) < 0.01,
            "" if abs(d - 85) < 0.01 else ("разпределен към обекта ред на доставна фактура (вграден ред от финансовия UI) не влиза в материалния разход на обекта — P&L Path B чете само invoice_lines" if abs(d) < 0.01
                                           else "CLAUDE.md §7: материалният разход се признава само веднъж"))
    K = str(uuid.uuid4())
    pbody = {"amount": 50, "method": "BankTransfer", "date": TODAY, "note": mark}
    path = f"/finance/invoices/{inv}/payments"
    st, j, txt = api("Accountant", "POST", path, pbody, key=K)
    must(F, "4.pay", "Accountant", "POST", path, st, txt, (200, 201))
    pay_id, alloc_id = j.get("payment_id"), j.get("allocation_id")
    n_pay = MDB.finance_payments.count_documents({"id": pay_id})
    n_alloc = MDB.payment_allocations.count_documents({"invoice_id": inv})
    rec(F, "4.pay", "Accountant", "POST", path, st, "1 ред във finance_payments + 1 разпределение",
        {"payment_id": pay_id, "finance_payments": n_pay, "allocations": n_alloc}, n_pay == 1 and n_alloc == 1,
        "" if n_pay == 1 else "FLOW-006: всяко реално плащане минава през регистъра веднъж")
    st2, j2, txt2 = api("Accountant", "POST", path, pbody, key=K)
    n_alloc2 = MDB.payment_allocations.count_documents({"invoice_id": inv})
    n_fp = MDB.finance_payments.count_documents({"note": mark})
    same = (j2 or {}).get("payment_id") == pay_id
    good = same and n_alloc2 == 1 and n_fp == 1
    rec(F, "5.pay_same_key_again", "Accountant", "POST", path, st2, "същият payment_id, без второ плащане",
        {"payment_id": (j2 or {}).get("payment_id"), "allocations": n_alloc2, "finance_payments_for_invoice": n_fp,
         "body": None if st2 in (200, 201) else short(txt2)}, good,
        "" if good else "FLOW-006 / CLAUDE.md §14: повторна заявка със същия Idempotency-Key не създава второ плащане")
    inv_doc = MDB.invoices.find_one({"id": inv}, {"_id": 0, "paid_amount": 1, "status": 1})
    okp = abs((inv_doc or {}).get("paid_amount", 0) - 50) < 0.01
    rec(F, "6.invoice_paid_amount", "Accountant", "DB", "invoices", None, "paid_amount 50", inv_doc, okp,
        "" if okp else "FLOW-006: плащането се записва веднъж")
    st, j, txt = api("Accountant", "POST", f"/finance/invoices/{inv}/cancel")
    rec(F, "7.cancel_with_payment", "Accountant", "POST", f"/finance/invoices/{inv}/cancel", st, "400 (има активно плащане)", short(txt)[:200],
        st == 400, "" if st == 400 else "FLOW-006: фактура с активно плащане не се анулира без корекция на плащането")
    if st != 200:
        path = f"/finance/invoices/{inv}/payments/{alloc_id}"
        st, j, txt = api("Accountant", "DELETE", path, {"reason": "процесен бот: анулиране на фактурата"},
                         params={"reason": "процесен бот: анулиране на фактурата"})
        pdoc = MDB.finance_payments.find_one({"id": pay_id}, {"_id": 0, "status": 1})
        n_rows = MDB.finance_payments.count_documents({"$or": [{"note": mark}, {"reversal_of_payment_id": pay_id},
                                                               {"reverses_payment_id": pay_id}, {"reversal_of": pay_id}]})
        rec(F, "8.reverse_payment", "Accountant", "DELETE", path, st, "200, плащането reversed (не изтрито)",
            {"payment": pdoc, "rows_kept": n_rows, "body": short(txt)[:150]},
            (pdoc is not None and pdoc.get("status") == "reversed") if st == 200 else None,
            "CLAUDE.md §2.9: няма hard delete; корекция = reversal" if st == 200 else "грешка от endpoint-а")
        st, j, txt = api("Accountant", "POST", f"/finance/invoices/{inv}/cancel")
        rec(F, "9.cancel", "Accountant", "POST", f"/finance/invoices/{inv}/cancel", st, "200 Cancelled",
            (j or {}).get("status") if st == 200 else short(txt), (st == 200 and (j or {}).get("status") == "Cancelled") if st == 200 else None)
        if st != 200:
            raise Stop()
    p2 = pnl(P)
    if p0 and p2:
        d = round(p2["expense"]["material_cost"] - m0, 2)
        rec(F, "10.pnl_after_cancel", "Accountant", "GET", f"/projects/{P}/pnl", 200, f"material_cost = {m0} (Δ 0)",
            {"material_cost": p2["expense"]["material_cost"], "delta": d}, abs(d) < 0.01,
            "" if abs(d) < 0.01 else "CLAUDE.md §7: анулирана фактура не може да остава материален разход на обекта")
    # B) allocation-screen shape: line in invoice_lines allocated 100% to the project, then cancel
    p0 = pnl(P)
    m0 = p0["expense"]["material_cost"] if p0 else None
    v0 = p0["vat"]["input_vat"] if p0 else None
    mark2 = mark + "-B"
    body = {"direction": "Received", "invoice_no": mark2, "counterparty_name": f"Доставчик Бот ООД {mark2}", "project_id": P,
            "issue_date": TODAY, "due_date": (date.today() + timedelta(days=30)).isoformat(), "currency": "EUR", "vat_percent": 20,
            "notes": mark2, "lines": []}
    st, j, txt = api("Accountant", "POST", "/finance/invoices", body)
    must(F, "B1.create_invoice", "Accountant", "POST", "/finance/invoices", st, txt, (201,))
    inv = j["id"]
    line = {"invoice_id": inv, "line_no": 1, "description": "Плочки 60x60", "unit": "м2", "qty": 5,
            "unit_price": 22, "vat_percent": 20, "allocations": [{"type": "project", "ref_id": P, "qty": 5}]}
    st, j, txt = api("Accountant", "POST", "/invoice-lines", line)
    must(F, "B2.invoice_line_allocated", "Accountant", "POST", "/invoice-lines", st, txt, (201,))
    line_id = j["id"]
    p1 = pnl(P)
    d1 = round(p1["expense"]["material_cost"] - m0, 2) if (p0 and p1) else None
    rec(F, "B2.invoice_line_allocated", "Accountant", "POST", "/invoice-lines", st, "material_cost +110 (5×22)",
        {"delta": d1}, (abs(d1 - 110) < 0.01) if d1 is not None else None, "" if d1 is None or abs(d1 - 110) < 0.01 else "CLAUDE.md §7")
    st, j, txt = api("Accountant", "POST", f"/finance/invoices/{inv}/cancel")
    must(F, "B3.cancel", "Accountant", "POST", f"/finance/invoices/{inv}/cancel", st, txt)
    rec(F, "B3.cancel", "Accountant", "POST", f"/finance/invoices/{inv}/cancel", st, "Cancelled", (j or {}).get("status"), (j or {}).get("status") == "Cancelled")
    p2 = pnl(P)
    if p0 and p2:
        d = round(p2["expense"]["material_cost"] - m0, 2)
        dv = round(p2["vat"]["input_vat"] - v0, 2)
        ln = MDB.invoice_lines.find_one({"id": line_id}, {"_id": 0, "allocations": 1})
        rec(F, "B4.pnl_after_cancel", "Accountant", "GET", f"/projects/{P}/pnl", 200, f"material_cost Δ 0, input_vat Δ 0",
            {"material_cost_delta": d, "input_vat_delta": dv, "line_allocations_still": (ln or {}).get("allocations")},
            abs(d) < 0.01 and abs(dv) < 0.01,
            "" if abs(d) < 0.01 and abs(dv) < 0.01 else
            "CLAUDE.md §7: анулирана фактура не може да остава материален разход на обекта (Path B / project_input_vat не филтрират статуса на фактурата)")


# ── FLOW 2: contract payment of a brigade ──
def flow2(P, cyc):
    F = "F2-contract-payment"
    name = f"Бригада Бот {cyc}-{uuid.uuid4().hex[:4]}"
    p0 = pnl(P)
    c0 = p0["expense"]["contract_cost"] if p0 else None
    body = {"worker_name": name, "contract_type": "one_time", "description": "Шпакловка акорд (бот)",
            "total_amount": 1000, "site_id": P,
            "tranches": [{"amount": 400, "due_date": TODAY}, {"amount": 600, "due_date": TODAY}]}
    st, j, txt = api("Accountant", "POST", "/contract-payments", body)
    must(F, "1.create", "Accountant", "POST", "/contract-payments", st, txt, (201,))
    cid = j["id"]
    rec(F, "1.create", "Accountant", "POST", "/contract-payments", st, "201, 2 транша pending", [t.get("status") for t in j.get("tranches", [])], True)
    path = f"/contract-payments/{cid}/pay-tranche"
    K = str(uuid.uuid4())
    st, j, txt = api("Accountant", "POST", path, {"tranche_index": 0, "notes": "бот"}, key=K)
    must(F, "2.pay_tranche_0", "Accountant", "POST", path, st, txt)
    n_fp = MDB.finance_payments.count_documents({"$or": [{"counterparty_name": name}, {"reference": cid}, {"source_id": cid},
                                                        {"contract_payment_id": cid}]})
    rec(F, "2.pay_tranche_0", "Accountant", "POST", path, st, "транш paid + 1 движение във finance_payments (Outflow 400)",
        {"tranche0": j["tranches"][0]["status"], "finance_payments_rows": n_fp}, n_fp == 1,
        "" if n_fp == 1 else "FLOW-006: всяко реално плащане минава през регистъра на плащанията — платен транш без движение в Каса/Банка")
    p1 = pnl(P)
    if p0 and p1:
        d = round(p1["expense"]["contract_cost"] - c0, 2)
        rec(F, "3.pnl_contract_cost", "Accountant", "GET", f"/projects/{P}/pnl", 200, "contract_cost +400",
            f"contract_cost {c0} → {p1['expense']['contract_cost']} (Δ {d})", abs(d - 400) < 0.01,
            "" if abs(d - 400) < 0.01 else "разходът по договора не е признат в P&L")
    st, j, txt = api("Accountant", "POST", path, {"tranche_index": 0}, key=K)
    rec(F, "4.pay_same_tranche_same_key", "Accountant", "POST", path, st, "200 същият резултат или 400; без второ плащане",
        short(txt)[:200], st in (200, 400), "")
    st, j, txt = api("Accountant", "POST", path, {"tranche_index": 0})
    rec(F, "5.pay_same_tranche_new_key", "Accountant", "POST", path, st, "400 Tranche already paid", short(txt)[:200], st == 400,
        "" if st == 400 else "един транш не може да бъде платен два пъти")
    p2 = pnl(P)
    if p1 and p2:
        d = round(p2["expense"]["contract_cost"] - p1["expense"]["contract_cost"], 2)
        rec(F, "6.pnl_unchanged_after_retry", "Accountant", "GET", f"/projects/{P}/pnl", 200, "Δ 0", d, abs(d) < 0.01)


# ── FLOW 3: attendance + daily report (two paths) → pay run ──
def flow3(P, cyc, D):
    F = "F3-report-payrun"
    p0 = pnl(P)
    h0 = p0["expense"]["labor_hours"] if p0 else None
    l0 = p0["expense"]["labor_cost"] if p0 else None
    path = f"/technician/site/{P}/attendance"
    st, j, txt = api("Technician", "POST", path, {"date": D, "workers": [
        {"worker_id": w, "worker_name": WNAME[w], "status": "Present"} for w in W]})
    must(F, "1.attendance", "Technician", "POST", path, st, txt)
    n_att = MDB.attendance_entries.count_documents({"project_id": P, "date": D, "status": "Present", "user_id": {"$in": W}})
    rec(F, "1.attendance", "Technician", "POST", path, st, "3 присъствия Present", n_att, n_att == 3)
    body = {"project_id": P, "date": D, "general_notes": f"бот цикъл {cyc}", "entries": [
        {"worker_id": w, "worker_name": WNAME[w], "smr_type": "Зидария", "hours": 8} for w in W]}
    st, j, txt = api("Technician", "POST", "/technician/daily-report", body)
    must(F, "2.tech_daily_report", "Technician", "POST", "/technician/daily-report", st, txt)
    drafts = j.get("draft_report_ids", [])
    rec(F, "2.tech_daily_report", "Technician", "POST", "/technician/daily-report", st, "3 чернови по 8 ч", {"drafts": len(drafts), "total_hours": j.get("total_hours")}, len(drafts) == 3)
    for rid in drafts:
        p = f"/daily-reports/{rid}/approve"
        st, j, txt = api("SiteManager", "POST", p, {})
        ws = MDB.work_sessions.count_documents({"approved_report_id": rid})
        rec(F, "3.approve_tech_draft", "SiteManager", "POST", p, st, "200 APPROVED + 1 work_session", {"status": (j or {}).get("approval_status") if st == 200 else short(txt), "work_sessions": ws},
            st == 200 and ws == 1 if st == 200 else None)
        st, j, txt = api("SiteManager", "POST", p, {})
        ws = MDB.work_sessions.count_documents({"approved_report_id": rid})
        rec(F, "3b.approve_again", "SiteManager", "POST", p, st, "400 вече одобрен, без втора сесия", {"body": short(txt)[:120], "work_sessions": ws},
            st == 400 and ws == 1, "" if st == 400 and ws == 1 else "FLOW-028: един отчетен ред не може да бъде платен/осчетоводен два пъти")
    # second path for worker0, same person / day / object
    body = {"employee_id": W[0], "report_date": D, "day_status": "WORKING", "notes": f"бот път 2, цикъл {cyc}",
            "day_entries": [{"project_id": P, "work_description": "Зидария", "hours_worked": 8}]}
    st, j, txt = api("SiteManager", "POST", "/daily-reports", body)
    if st == 201:
        rid2 = j["id"]
        rec(F, "4.second_path_daily_report", "SiteManager", "POST", "/daily-reports", st,
            "отказ/предупреждение: за W0 вече има 8 ч отчет за този ден и обект",
            {"created": rid2, "hours_warnings": j.get("hours_warnings")}, False,
            "същият човек, ден и обект се отчита втори път по друг път без блокиране (FLOW-013 присъствие/отчет на човек и ден)")
        st, j, txt = api("SiteManager", "POST", f"/daily-reports/{rid2}/submit")
        rec(F, "5.submit", "SiteManager", "POST", f"/daily-reports/{rid2}/submit", st, "SUBMITTED", (j or {}).get("approval_status") if st == 200 else short(txt), st == 200 or None)
        st, j, txt = api("SiteManager", "POST", f"/daily-reports/{rid2}/approve", {})
        if st == 403:  # four-eyes on #75: another person approves
            st, j, txt = api("Admin", "POST", f"/daily-reports/{rid2}/approve", {})
        ws = MDB.work_sessions.count_documents({"approved_report_id": rid2})
        rec(F, "6.approve_second_path", "SiteManager", "POST", f"/daily-reports/{rid2}/approve", st,
            "APPROVED + work_session (за да влезе трудът в P&L)", {"status": (j or {}).get("approval_status") if st == 200 else short(txt), "work_sessions": ws},
            (ws == 1) if st == 200 else None,
            "" if ws == 1 else "P&L труд чете само work_sessions — одобрен отчет по /daily-reports не създава сесия (часове в ведомост, но не в P&L)")
    else:
        rec(F, "4.second_path_daily_report", "SiteManager", "POST", "/daily-reports", st, "отказ (вече има отчет)", short(txt), True if st in (400, 409, 422) else None)
    # P&L after approvals
    p1 = pnl(P)
    dh = round(p1["expense"]["labor_hours"] - h0, 2) if (p0 and p1) else None
    dl = round(p1["expense"]["labor_cost"] - l0, 2) if (p0 and p1) else None
    # pay run preview
    st, g, txt = api("Admin", "GET", "/pay-runs/generate", params={"period_start": D, "period_end": D})
    must(F, "7.payrun_generate", "Admin", "GET", "/pay-runs/generate", st, txt)
    rows = {r["employee_id"]: r for r in g.get("rows", []) if r["employee_id"] in W}
    summary = {WNAME[w]: {"hours": rows[w]["approved_hours"], "earned": rows[w]["earned_amount"], "formula": rows[w].get("earned_formula")} for w in rows}
    rec(F, "7.payrun_generate", "Admin", "GET", "/pay-runs/generate", st, "W0 8 ч×12=96; W1 1д×110; W2 2200/22×1", summary, None if not rows else
        (rows.get(W[0], {}).get("approved_hours") == 8),
        "" if rows.get(W[0], {}).get("approved_hours") == 8 else
        "FLOW-028: един отчетен ред не може да бъде платен два пъти — същият ден/обект на W0 влиза в ведомостта с часовете и от двата пътя")
    pr_hours = round(sum(r["approved_hours"] for r in rows.values()), 2)
    if dh is not None:
        rec(F, "8.pnl_hours_vs_payrun", "Accountant", "GET", f"/projects/{P}/pnl", 200, "Δ labor_hours в P&L = часове във ведомостта",
            {"pnl_labor_hours_delta": dh, "pnl_labor_cost_delta": dl, "payrun_hours": pr_hours,
             "payrun_earned": round(sum(r["earned_amount"] for r in rows.values()), 2)},
            abs(dh - pr_hours) < 0.01,
            "" if abs(dh - pr_hours) < 0.01 else "P&L трудът (work_sessions) и ведомостта (employee_daily_reports) дават различни часове за едни и същи отчети — два source of truth (CLAUDE.md §2.12)")
    if not rows:
        raise Stop()
    prow = [{"employee_id": w, "paid_now_amount": rows[w]["earned_amount"]} for w in rows]
    st, run, txt = api("Admin", "POST", "/pay-runs", {"period_start": D, "period_end": D, "status": "confirmed",
                                                     "rows": prow, "note": f"процесен бот {cyc}"})
    must(F, "9.payrun_confirm", "Admin", "POST", "/pay-runs", st, txt)
    run_id = run["id"]
    rec(F, "9.payrun_confirm", "Admin", "POST", "/pay-runs", st, "confirmed", {"number": run.get("number"), "status": run.get("status"), "totals": run.get("totals")}, run.get("status") == "confirmed")
    K = str(uuid.uuid4())
    p = f"/pay-runs/{run_id}/mark-paid"
    st, j, txt = api("Admin", "POST", p, {"payment_method": "cash", "payment_reference": f"бот-{cyc}"}, key=K)
    n_sal = MDB.finance_payments.count_documents({"reference": run_id, "category": "Заплата"})
    n_exp = sum(1 for r in prow if r["paid_now_amount"] > 0)
    rec(F, "10.mark_paid", "Admin", "POST", p, st, f"paid + {n_exp} Outflow във finance_payments", {"status": (j or {}).get("status") if st == 200 else short(txt), "salary_payments": n_sal},
        (n_sal == n_exp) if st == 200 else None, "" if n_sal == n_exp else "FLOW-006: всяко реално плащане минава през регистъра")
    st, j, txt = api("Admin", "POST", p, {"payment_method": "cash"})
    n_sal2 = MDB.finance_payments.count_documents({"reference": run_id, "category": "Заплата"})
    rec(F, "11.mark_paid_again", "Admin", "POST", p, st, "409, без нови плащания", {"body": short(txt)[:120], "salary_payments": n_sal2},
        st == 409 and n_sal2 == n_sal, "" if st == 409 and n_sal2 == n_sal else "един Pay Run се плаща само веднъж")
    st, g2, txt = api("Admin", "GET", "/pay-runs/generate", params={"period_start": D, "period_end": D})
    rows2 = {r["employee_id"]: r for r in (g2 or {}).get("rows", []) if r["employee_id"] in W}
    left = {WNAME[w]: rows2[w]["earned_amount"] for w in rows2 if rows2[w]["earned_amount"] > 0}
    rec(F, "12.payrun_generate_after_paid", "Admin", "GET", "/pay-runs/generate", st, "няма неплатени отчети за W0..2 в периода",
        {"unpaid_earned": left or "няма", "previously_paid": {WNAME[w]: rows2[w].get("previously_paid") for w in rows2}}, not left,
        "" if not left else "FLOW-028: платен отчет трябва да е заключен — отчетът остава 'неплатен' в ведомостта след mark-paid (payroll_status не е маркиран); повторно плащане спира само проверката за надплащане")
    prow2 = [{"employee_id": w, "paid_now_amount": rows2[w]["earned_amount"]} for w in rows2 if rows2[w]["earned_amount"] > 0]
    if not prow2:
        rec(F, "13.second_payrun_same_period", "Admin", "POST", "/pay-runs", None, "няма какво да се плати повторно", "няма неплатени редове", True)
        return
    st, run2, txt = api("Admin", "POST", "/pay-runs", {"period_start": D, "period_end": D, "status": "confirmed",
                                                      "rows": prow2, "note": f"процесен бот {cyc} повторно"})
    paid2 = (run2 or {}).get("totals", {}).get("paid") if st == 200 else None
    rec(F, "13.second_payrun_same_period", "Admin", "POST", "/pay-runs", st, "отказ (4xx) — отчетите вече са платени",
        short(txt)[:200] if st != 200 else {"number": run2.get("number"), "totals": run2.get("totals")},
        st >= 400, "" if st >= 400 else "FLOW-028: един отчетен ред не може да бъде платен два пъти — втори Pay Run за същия период е приет")
    if st == 200 and run2 and run2.get("status") == "confirmed":
        p = f"/pay-runs/{run2['id']}/mark-paid"
        st, j, txt = api("Admin", "POST", p, {"payment_method": "cash", "payment_reference": f"бот-{cyc}-2"})
        n_sal = MDB.finance_payments.count_documents({"reference": run2["id"], "category": "Заплата"})
        rec(F, "14.second_payrun_mark_paid", "Admin", "POST", p, st, "не трябва да е възможно", {"status": (j or {}).get("status") if st == 200 else short(txt), "salary_payments": n_sal,
            "paid": run2.get("totals", {}).get("paid")}, False if st == 200 else None,
            "FLOW-028: един отчетен ред не може да бъде платен два пъти — същият ден/обект на W0 е платен в два Pay Run-а" if st == 200 else "")


# ── FLOW 4: advance double submit ──
def flow4(P, cyc):
    F = "F4-advance"
    acc = cash_account()
    mark = f"PB-ADV-{cyc}-{uuid.uuid4().hex[:6]}"
    body = {"user_id": W[1], "type": "Advance", "amount": 20, "account_id": acc, "issued_date": TODAY, "note": mark + "-a"}
    res = []
    def go(k):
        res.append(api("Accountant", "POST", "/advances", body, key=k))
    ts = [threading.Thread(target=go, args=(str(uuid.uuid4()),)) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    n_adv = MDB.advances.count_documents({"note": mark + "-a"})
    n_fp = MDB.finance_payments.count_documents({"category": "Аванс", "id": {"$in": [d.get("payment_id") for d in MDB.advances.find({"note": mark + "-a"})]}})
    rec(F, "1.double_click_two_keys", "Accountant", "POST", "/advances", [r[0] for r in res],
        "2 различни ключа = 2 заявки; всеки аванс с 1 Outflow", {"advances": n_adv, "finance_payments": n_fp}, None,
        "две бързи заявки с различни ключове → %d аванса; сървърът няма защита от двоен клик (не е нарушение по дефиниция — различни ключове)" % n_adv)
    body2 = dict(body, note=mark + "-b")
    K = str(uuid.uuid4())
    res = []
    ts = [threading.Thread(target=go2, args=(K, body2, res)) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    st3, _, _ = api("Accountant", "POST", "/advances", body2, key=K)
    n_adv = MDB.advances.count_documents({"note": mark + "-b"})
    ids = [d.get("payment_id") for d in MDB.advances.find({"note": mark + "-b"})]
    n_fp = MDB.finance_payments.count_documents({"id": {"$in": ids}})
    rec(F, "2.same_key_x3", "Accountant", "POST", "/advances", [r[0] for r in res] + [st3], "1 аванс + 1 Outflow (същият Idempotency-Key)",
        {"advances": n_adv, "finance_payments": n_fp}, n_adv == 1,
        "" if n_adv == 1 else "CLAUDE.md §14: idempotency key за всеки consequential write — същият ключ създаде %d аванса и %d плащания (FLOW-006)" % (n_adv, n_fp))


def go2(k, body, res):
    res.append(api("Accountant", "POST", "/advances", body, key=k))


# ── FLOW 5: warehouse receive → dispatch → accept → consume ──
def flow5(P, cyc):
    F = "F5-warehouse"
    p0 = pnl(P)
    def stock(lt, lid):
        st, j, _ = api("Warehousekeeper", "GET", f"/warehouse/canonical/stock/{ITEM}", params={"location_type": lt, "location_id": lid})
        return j.get("quantity") if st == 200 else None
    s0 = stock("central_warehouse", WH)
    k = str(uuid.uuid4())
    body = {"action": "receive_from_supplier", "item_id": ITEM, "unit": "торба", "quantity": "10", "idempotency_key": k,
            "unit_value": "8.5", "currency": "EUR", "source": {"location_type": "supplier", "location_id": "sup-bot"},
            "destination": {"location_type": "central_warehouse", "location_id": WH}, "notes": f"бот {cyc}"}
    st, j, txt = api("Warehousekeeper", "POST", "/warehouse/canonical/movements", body, key=k)
    if st not in (200, 201):
        rec(F, "1.receive_from_supplier", "Warehousekeeper", "POST", "/warehouse/canonical/movements", st, "200 приемане 10 торби",
            short(txt), None, "не можах да проверя склада: каноничният endpoint отказва (артикулът не е в Master Data, MASTER_DATA_MODE=off не позволява регистрация през API)")
        raise Stop()
    rec(F, "1.receive_from_supplier", "Warehousekeeper", "POST", "/warehouse/canonical/movements", st, "200", short(txt)[:200], True)
    s1 = stock("central_warehouse", WH)
    rec(F, "2.stock_after_receive", "Warehousekeeper", "GET", f"/warehouse/canonical/stock/{ITEM}", 200, f"{s0}+10", s1,
        s0 is not None and s1 is not None and abs(float(s1) - float(s0) - 10) < 1e-6)
    st, j2, txt = api("Warehousekeeper", "POST", "/warehouse/canonical/movements", body, key=k)
    s1b = stock("central_warehouse", WH)
    rec(F, "3.receive_same_key", "Warehousekeeper", "POST", "/warehouse/canonical/movements", st, "без второ приемане", s1b, s1b == s1,
        "" if s1b == s1 else "Idempotency: второ приемане със същия ключ")
    k = str(uuid.uuid4())
    body = {"action": "dispatch_warehouse_to_project", "item_id": ITEM, "unit": "торба", "quantity": "4", "idempotency_key": k,
            "source": {"location_type": "central_warehouse", "location_id": WH},
            "destination": {"location_type": "in_transit", "location_id": P, "state": "in_transit"}, "project_id": P}
    st, j, txt = api("Warehousekeeper", "POST", "/warehouse/canonical/movements", body, key=k)
    must(F, "4.dispatch_to_project", "Warehousekeeper", "POST", "/warehouse/canonical/movements", st, txt)
    rec(F, "4.dispatch_to_project", "Warehousekeeper", "POST", "/warehouse/canonical/movements", st, "200", short(txt)[:200], True)
    mid = (j or {}).get("movement_id") or (j or {}).get("id")
    k = str(uuid.uuid4())
    body = {"action": "accept_project_delivery", "item_id": ITEM, "unit": "торба", "quantity": "4", "idempotency_key": k,
            "source": {"location_type": "in_transit", "location_id": P, "state": "in_transit"},
            "destination": {"location_type": "project", "location_id": P}, "project_id": P, "dispatch_movement_id": mid}
    st, j, txt = api("SiteManager", "POST", "/warehouse/canonical/movements", body, key=k)
    must(F, "5.accept_on_project", "SiteManager", "POST", "/warehouse/canonical/movements", st, txt)
    p1 = pnl(P)
    d = round(p1["expense"]["material_cost"] - p0["expense"]["material_cost"], 2)
    rec(F, "6.pnl_after_accept", "Accountant", "GET", f"/projects/{P}/pnl", 200, "material_cost +34 (4×8.5) веднъж", d, abs(d - 34) < 0.01,
        "" if abs(d - 34) < 0.01 else "CLAUDE.md §7: материалният разход се признава само веднъж")


# ── FLOW 6: forbidden writes ──
def flow6(P, cyc, report_id=None):
    F = "F6-permissions"
    acc = cash_account()
    for role in ("Viewer", "Driver", "Worker"):
        mark = f"PB-PERM-{role}-{cyc}-{uuid.uuid4().hex[:5]}"
        tries = [
            ("POST", "/finance/invoices", {"direction": "Received", "counterparty_name": mark, "issue_date": TODAY, "due_date": TODAY, "lines": []},
             lambda: MDB.invoices.count_documents({"counterparty_name": mark})),
            ("POST", "/finance/payments", {"direction": "Outflow", "amount": 1, "date": TODAY, "method": "Cash", "account_id": acc, "note": mark},
             lambda: MDB.finance_payments.count_documents({"note": mark})),
            ("POST", "/advances", {"user_id": W[1], "amount": 1, "account_id": acc, "note": mark},
             lambda: MDB.advances.count_documents({"note": mark})),
            ("POST", "/contract-payments", {"worker_name": mark, "total_amount": 1, "site_id": P},
             lambda: MDB.contract_payments.count_documents({"worker_name": mark})),
            ("POST", "/pay-runs", {"period_start": "2020-01-01", "period_end": "2020-01-01", "rows": [], "note": mark},
             lambda: MDB.pay_runs.count_documents({"note": mark})),
            ("POST", "/projects", {"code": mark, "name": mark},
             lambda: MDB.projects.count_documents({"code": mark})),
            ("POST", "/finance/other-expense", {"amount": 1, "account_id": acc, "project_id": P, "note": mark, "description": mark, "date": TODAY},
             lambda: MDB.finance_payments.count_documents({"$or": [{"note": mark}, {"description": mark}]})),
            ("POST", "/warehouse/canonical/movements", {"action": "receive_from_supplier", "item_id": ITEM, "unit": "торба", "quantity": "1",
             "idempotency_key": mark, "unit_value": "1", "source": {"location_type": "supplier", "location_id": "x"},
             "destination": {"location_type": "central_warehouse", "location_id": WH}},
             lambda: MDB.warehouse_transactions.count_documents({"idempotency_key": mark})),
        ]
        if report_id:
            tries.append(("POST", f"/daily-reports/{report_id}/reject", {"reason": mark},
                          lambda: MDB.employee_daily_reports.count_documents({"id": report_id, "reject_reason": mark})))
        for method, path, body, cnt in tries:
            st, j, txt = api(role, method, path, body)
            n = cnt()
            ok = (st in (401, 403)) and n == 0
            if n > 0:
                note = f"забранен запис е създаден ({n} док.) — CLAUDE.md §16: не заобикаляй Tenant Guard/Permission"
            elif st not in (401, 403):
                note = f"очакван 403, върнат {st} (нищо не е записано)"
                ok = None if st in (400, 404, 409, 422, 428) else False
            else:
                note = ""
            rec(F, f"{role}:{path}", role, method, path, st, "403 + 0 записа", {"db_rows": n, "body": short(txt)[:120]}, ok, note)


def latest_report():
    d = MDB.employee_daily_reports.find_one({"approval_status": "APPROVED"}, {"_id": 0, "id": 1}, sort=[("created_at", -1)])
    return d and d["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=3)
    ap.add_argument("--until", type=float, default=None, help="unix seconds")
    ap.add_argument("--pause", type=float, default=60)
    a = ap.parse_args()
    end = a.until or (now() + a.minutes * 60)
    rec("run", "start", "-", "-", "-", None, None, {"end": end, "pid": os.getpid()}, True)
    P = setup()
    S = state_load()
    cyc = 0
    while now() < end:
        cyc += 1
        S["day_offset"] = S.get("day_offset", 0) + 1
        state_save(S)
        D = (date(2026, 3, 1) + timedelta(days=S["day_offset"])).isoformat()
        for name, fn in (("F1", lambda: flow1(P, cyc)), ("F2", lambda: flow2(P, cyc)), ("F3", lambda: flow3(P, cyc, D)),
                         ("F4", lambda: flow4(P, cyc)), ("F5", lambda: flow5(P, cyc)), ("F6", lambda: flow6(P, cyc, latest_report()))):
            if now() >= end:
                break
            try:
                fn()
            except Stop:
                pass
            except Exception as e:
                rec(name, "exception", "-", "-", "-", None, None, traceback.format_exc()[-400:], None, "бот грешка — продължава")
        rec("run", f"cycle_end_{cyc}", "-", "-", "-", None, None, {"project": P, "date": D}, True)
        if now() + a.pause < end:
            time.sleep(a.pause)
        else:
            break
    rec("run", "end", "-", "-", "-", None, None, {"cycles": cyc}, True)


if __name__ == "__main__":
    main()
