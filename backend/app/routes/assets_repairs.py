"""
Routes - Asset Repairs (ремонти на активи).
Нова колекция asset_repairs. Всеки ремонт сочи към:
  - unit_id -> asset_units.id (физическата бройка)
Поток: send (актив → статус repair) → return (актив → статус available).
Гаранцията се смята от purchase_date + warranty_months на БРОЙКАТА.
Нищо съществуващо не се пипа — само нова колекция + промяна на unit.status.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, timezone, date
import uuid

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["AssetRepairs"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_name(user: dict) -> str:
    return (user.get("name")
            or f"{user.get('first_name','')} {user.get('last_name','')}".strip()
            or (user.get("email", "").split("@")[0] if user.get("email") else ""))


async def _person_by_id(org_id: str, user_id: Optional[str]) -> dict:
    """Връща {name, avatar_url} за users.id; празно ако няма id или потребител."""
    if not user_id:
        return {}
    u = await db.users.find_one(
        {"id": user_id, "org_id": org_id},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1, "email": 1, "avatar_url": 1},
    )
    if not u:
        return {}
    return {"name": _user_name(u) or None, "avatar_url": u.get("avatar_url")}


def _in_warranty(purchase_date: Optional[str], warranty_months: Optional[int]) -> bool:
    """Сметка за гаранция от датата на покупка + месеци."""
    if not purchase_date or not warranty_months:
        return False
    try:
        y, m, d = str(purchase_date)[:10].split("-")
        start = date(int(y), int(m), int(d))
        # добавяме месеците
        total = start.month - 1 + int(warranty_months)
        end_year = start.year + total // 12
        end_month = total % 12 + 1
        # ден — клампваме към края на месеца грубо (28 е безопасно)
        end = date(end_year, end_month, min(start.day, 28))
        return end > date.today()
    except Exception:
        return False


class RepairSend(BaseModel):
    sent_by: Optional[str] = None        # users.id на този, който закара
    sent_by_name: Optional[str] = None   # кой го закара (snapshot / резерва за стари записи)
    service: Optional[str] = None        # сервиз / при кого
    issue: Optional[str] = None          # повреда


class RepairReturn(BaseModel):
    returned_by: Optional[str] = None       # users.id на този, който взе
    returned_by_name: Optional[str] = None  # кой го взе (snapshot / резерва за стари записи)
    cost: Optional[float] = None            # цена
    work_done: Optional[str] = None         # какво е направено
    is_warranty: Optional[bool] = None      # гаранционен ремонт
    return_location_id: Optional[str] = None  # връща се в кой склад (по избор)


async def _unit_or_404(org_id: str, unit_id: str) -> dict:
    unit = await db.asset_units.find_one({"id": unit_id, "org_id": org_id}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.post("/assets/units/{unit_id}/repair/send")
async def repair_send(unit_id: str, data: RepairSend, user: dict = Depends(get_current_user)):
    """Изпрати актив на ремонт → нов запис asset_repairs (in_repair) + unit.status = repair."""
    org = user["org_id"]
    unit = await _unit_or_404(org, unit_id)

    # ако вече има отворен ремонт — не дублираме
    existing = await db.asset_repairs.find_one({"org_id": org, "unit_id": unit_id, "status": "in_repair"}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Този актив вече е на ремонт")

    # име + аватар се извеждат на живо по id; името пазим и като snapshot (резерва)
    sent_person = await _person_by_id(org, data.sent_by)
    sent_name = sent_person.get("name") or ((data.sent_by_name or "").strip() or None)

    rec = {
        "id": str(uuid.uuid4()),
        "org_id": org,
        "unit_id": unit_id,
        "status": "in_repair",
        "sent_at": datetime.now(timezone.utc).date().isoformat(),
        "sent_by": (data.sent_by or "").strip() or None,
        "sent_by_name": sent_name,
        "service": (data.service or "").strip() or None,
        "issue": (data.issue or "").strip() or None,
        "returned_at": None,
        "returned_by": None,
        "returned_by_name": None,
        "cost": None,
        "work_done": None,
        "is_warranty": None,
        # запазваме откъде е тръгнал, за да го върнем там по подразб.
        "from_location_type": unit.get("location_type"),
        "from_location_id": unit.get("location_id"),
        "created_at": _now(),
        "created_by": user["id"],
    }
    await db.asset_repairs.insert_one(rec)
    await db.asset_units.update_one({"id": unit_id, "org_id": org}, {"$set": {"status": "repair"}})
    rec.pop("_id", None)
    return rec


@router.post("/assets/units/{unit_id}/repair/return")
async def repair_return(unit_id: str, data: RepairReturn, user: dict = Depends(get_current_user)):
    """Върни актив от ремонт → затваря записа (done) + unit.status = available."""
    org = user["org_id"]
    unit = await _unit_or_404(org, unit_id)

    rec = await db.asset_repairs.find_one({"org_id": org, "unit_id": unit_id, "status": "in_repair"}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=400, detail="Този актив не е на ремонт")

    # гаранция по подразбиране от бройката (само МАРКЕР — НЕ заключва цената;
    # дори в гаранция често се плаща диагностика/транспорт)
    warranty = data.is_warranty
    if warranty is None:
        warranty = _in_warranty(unit.get("purchase_date"), unit.get("warranty_months"))
    cost = data.cost if data.cost is not None else None

    # къде се връща — подаден склад или там, откъдето е тръгнал
    ret_loc_type = "warehouse" if data.return_location_id else rec.get("from_location_type")
    ret_loc_id = data.return_location_id or rec.get("from_location_id")

    # име + аватар се извеждат на живо по id; името пазим и като snapshot (резерва)
    ret_person = await _person_by_id(org, data.returned_by)
    ret_name = ret_person.get("name") or ((data.returned_by_name or "").strip() or None)

    await db.asset_repairs.update_one(
        {"id": rec["id"], "org_id": org},
        {"$set": {
            "status": "done",
            "returned_at": datetime.now(timezone.utc).date().isoformat(),
            "returned_by": (data.returned_by or "").strip() or None,
            "returned_by_name": ret_name,
            "cost": cost,
            "work_done": (data.work_done or "").strip() or None,
            "is_warranty": bool(warranty),
        }},
    )
    await db.asset_units.update_one(
        {"id": unit_id, "org_id": org},
        {"$set": {"status": "available", "location_type": ret_loc_type, "location_id": ret_loc_id}},
    )
    updated = await db.asset_repairs.find_one({"id": rec["id"], "org_id": org}, {"_id": 0})
    return updated


@router.get("/assets/units/{unit_id}/repairs")
async def list_repairs(unit_id: str, user: dict = Depends(get_current_user)):
    """История на ремонтите на бройката + обща похарчена сума (само платените)."""
    org = user["org_id"]
    items = (
        await db.asset_repairs.find({"org_id": org, "unit_id": unit_id}, {"_id": 0})
        .sort("sent_at", -1)
        .to_list(500)
    )
    total_paid = sum((r.get("cost") or 0) for r in items)  # всичко платено (вкл. диагностика в гаранция)

    # обогатяване с име + аватар на живо по users.id (старите записи без id ползват snapshot)
    ids = {r.get("sent_by") for r in items if r.get("sent_by")} | \
          {r.get("returned_by") for r in items if r.get("returned_by")}
    people = {}
    if ids:
        async for u in db.users.find(
            {"id": {"$in": list(ids)}, "org_id": org},
            {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1, "email": 1, "avatar_url": 1},
        ):
            people[u["id"]] = {"name": _user_name(u) or None, "avatar_url": u.get("avatar_url")}

    for r in items:
        sp = people.get(r.get("sent_by"), {})
        rp = people.get(r.get("returned_by"), {})
        r["sent_by_name"] = sp.get("name") or r.get("sent_by_name")
        r["sent_by_avatar"] = sp.get("avatar_url")
        r["returned_by_name"] = rp.get("name") or r.get("returned_by_name")
        r["returned_by_avatar"] = rp.get("avatar_url")

    open_repair = next((r for r in items if r.get("status") == "in_repair"), None)
    return {"items": items, "total_paid": round(total_paid, 2), "open": open_repair}
