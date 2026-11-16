"""Starting data for the role bots, created through the real API as the demo admin."""
import json, os, requests, uuid
B = "http://localhost:%s/api" % os.environ["BOT_PORT"]
H = {"x-bot-role": "seed"}
def login(email, pw):
    r = requests.post(B + "/auth/login", json={"email": email, "password": pw}); r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"], **H}
def post(path, body, h, ok=(200, 201)):
    r = requests.post(B + path, json=body, headers={**h, "Idempotency-Key": str(uuid.uuid4())})
    print(r.status_code, path, r.text[:140].replace("\n", " "))
    return r.json() if r.status_code in ok else None
A = login("demo@example.com", "Demo12345!")
ROLES = {"Owner": "Собственик", "SiteManager": "Техн. ръководител", "Technician": "Техник",
         "Accountant": "Счетоводител", "Warehousekeeper": "Склад", "Driver": "Шофьор", "Viewer": "Наблюдател"}
users = {"Admin": {"email": "demo@example.com", "password": "Demo12345!"}}
for role, bg in ROLES.items():
    if role == "Owner": continue  # Admin may not create Owner (ROLE_ABOVE_OWN_FORBIDDEN)
    email = f"bot.{role.lower()}@example.com"
    u = post("/users", {"email": email, "password": "Bot12345!", "first_name": "Бот", "last_name": bg, "role": role}, A)
    users[role] = {"email": email, "password": "Bot12345!", "id": (u or {}).get("id")}
workers = []
for i, (n, pt, rate) in enumerate([("Иван", "Hourly", 12), ("Петър", "Daily", 110), ("Георги", "Monthly", 2200)]):
    u = post("/users", {"email": f"worker{i}@example.com", "password": "Bot12345!", "first_name": n, "last_name": "Работник", "role": "Technician"}, A)
    if u:
        workers.append(u["id"])
        prof = {"user_id": u["id"], "pay_type": pt, "position": "Работник"}
        prof[{"Hourly": "hourly_rate", "Daily": "daily_rate", "Monthly": "monthly_salary"}[pt]] = rate
        post("/employees", prof, A)
for role in ("SiteManager", "Technician", "Accountant", "Warehousekeeper", "Driver"):
    if users[role].get("id"):
        post("/employees", {"user_id": users[role]["id"], "pay_type": "Daily", "daily_rate": 120, "position": role}, A)
cl = post("/clients", {"first_name": "Мария", "last_name": "Клиентова", "phone": "0888123456", "email": "client@example.com"}, A)
projects = []
PRE = {p["code"]: p["id"] for p in requests.get(B + "/projects", headers=A).json()} if True else {}
for code, name in (("OB-1", "Къща Бояна"), ("OB-2", "Офис Лозенец")):
    p = {"id": PRE[code]} if code in PRE else post("/projects", {"code": code, "name": name, "status": "Active", "budget_planned": 50000}, A)
    if p:
        projects.append(p["id"])
        for uid in [users["SiteManager"].get("id"), users["Technician"].get("id")] + workers:
            if uid:
                post(f"/projects/{p['id']}/team", {"user_id": uid, "role_in_project": "SiteManager" if uid == users["SiteManager"].get("id") else "Technician"}, A)
0 and post("/warehouses", {"code": "WH-1", "name": "Централен склад", "type": "central"}, A)
for sku, name, unit, price in (("M-001", "Цимент 25 кг", "торба", 8.5), ("M-002", "Плочки 60x60", "м2", 22), ("M-003", "Лепило за плочки", "торба", 12)):
    0 and post("/items", {"sku": sku, "name": name, "unit": unit, "default_price": price}, A)
post("/finance/accounts", {"name": "Каса", "type": "Cash", "opening_balance": 10000}, A)
post("/finance/accounts", {"name": "Банка", "type": "Bank", "opening_balance": 50000}, A)
# INTEGRATION: run A added the Worker role by hand in seed.json (= worker0, README §4); done here
if workers:
    users["Worker"] = {"email": "worker0@example.com", "password": "Bot12345!", "id": workers[0]}
json.dump({"users": users, "projects": projects, "workers": workers}, open(os.path.join(os.environ["BOT_RUN"], "seed.json"), "w"), ensure_ascii=False, indent=1)
