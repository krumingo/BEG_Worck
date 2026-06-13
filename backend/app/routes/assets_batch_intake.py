"""
Routes - Assets Batch Intake (E2: партиден прием със снимки).

Един endpoint /assets/batch-intake/recognize:
  - приема няколко снимки на ЕДНА вещ
  - AI разпознава вещта
  - намира съществуващ артикул (групиране) или подсказва нов
  - проверява дали типът съществува; ако не — подсказва нов тип
Нищо не записва. Записът минава по съществуващите endpoints
(POST /assets/items, POST /assets/units, POST /assets/item-types).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from pydantic import BaseModel
import os, json, uuid

from app.db import db
from app.deps.auth import get_current_user
from app.routes.asset_item_types import all_type_keys, BUILTIN_TYPES

router = APIRouter(tags=["AssetsBatchIntake"])

ADMIN_ROLES = ["Admin", "Owner", "SiteManager", "Accountant"]
MAX_IMG = 8_000_000
MAX_IMAGES = 4

SYSTEM_PROMPT = """Ти си експерт по строителна техника, инструменти и оборудване в България.
Получаваш една или няколко снимки на ЕДНА И СЪЩА вещ от различни ъгли (понякога и табелка).
Върни САМО валиден JSON без markdown:
{
  "name": "кратко българско име, напр. Чук",
  "type_label": "тип на български: Машина / Ръчен инструмент / Оборудване / друг подходящ",
  "group": "група за филтриране",
  "brand": "марка или null",
  "model": "модел или null",
  "serial_no": "сериен номер от табелка или null",
  "estimated_price_eur": число или null,
  "warranty_months": число или null,
  "description": "1-2 изречения",
  "activities": ["3-6 дейности"],
  "consumables": ["3-6 консуматива"],
  "confidence": 0-100
}"""


class RecognizeRequest(BaseModel):
    images_base64: List[str]


def _strip(t: str) -> str:
    t = t.strip()
    if t.startswith("```"):
        t = "\n".join(l for l in t.split("\n") if not l.strip().startswith("```"))
    return t.strip()


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def _match_existing_item(org_id: str, name: str, brand: Optional[str], model: Optional[str]):
    """Групиране: намери съществуващ артикул по име (и марка/модел ако има)."""
    if not name:
        return None
    candidates = await db.asset_items.find(
        {"org_id": org_id, "is_active": True}, {"_id": 0, "id": 1, "name": 1, "brand": 1, "model": 1, "type": 1}
    ).to_list(500)
    nl = name.strip().lower()
    bl = (brand or "").strip().lower()
    ml = (model or "").strip().lower()
    best = None
    for c in candidates:
        cn = (c.get("name") or "").strip().lower()
        if cn != nl:
            continue
        # име съвпада — ако има марка/модел, предпочети точното
        if ml and (c.get("model") or "").strip().lower() == ml:
            return c
        if bl and (c.get("brand") or "").strip().lower() == bl:
            best = best or c
        best = best or c
    return best


@router.post("/assets/batch-intake/recognize")
async def recognize(data: RecognizeRequest, user: dict = Depends(get_current_user)):
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    imgs = [i for i in (data.images_base64 or []) if i and len(i) > 100]
    if not imgs:
        raise HTTPException(status_code=400, detail="At least one image required")
    if len(imgs) > MAX_IMAGES:
        imgs = imgs[:MAX_IMAGES]
    if any(len(i) > MAX_IMG for i in imgs):
        raise HTTPException(status_code=400, detail="Image too large")

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY not configured")

    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

    chat = LlmChat(
        api_key=api_key,
        session_id=f"batch-intake-{uuid.uuid4().hex[:8]}",
        system_message=SYSTEM_PROMPT,
    ).with_model("openai", "gpt-4.1-mini")

    try:
        resp = await chat.send_message(UserMessage(
            text="Разпознай вещта от снимките и върни JSON.",
            file_contents=[ImageContent(image_base64=b) for b in imgs],
        ))
        parsed = json.loads(_strip(str(resp)))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI отговори в невалиден формат, опитай пак")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI error: {e}")

    org = user["org_id"]
    name = str(parsed.get("name") or "").strip()
    brand = (parsed.get("brand") or None)
    model = (parsed.get("model") or None)
    type_label = str(parsed.get("type_label") or "").strip()

    # групиране към съществуващ артикул
    matched = await _match_existing_item(org, name, brand, model)

    # съпоставяне на типа: ламбда срещу вградени + динамични по label
    type_keys = await all_type_keys(org)
    label_to_key = {b["label_bg"].lower(): b["key"] for b in BUILTIN_TYPES}
    async for t in db.asset_item_types.find({"org_id": org}, {"_id": 0, "key": 1, "label_bg": 1}):
        label_to_key[(t["label_bg"] or "").lower()] = t["key"]
    matched_type_key = label_to_key.get(type_label.lower())
    type_is_new = matched_type_key is None and bool(type_label)

    suggestion = {
        "name": name,
        "type_label": type_label,
        "type_key": matched_type_key,          # None ако е нов
        "type_is_new": type_is_new,
        "group": (parsed.get("group") or None),
        "brand": brand,
        "model": model,
        "serial_no": (parsed.get("serial_no") or None),
        "estimated_price_eur": _num(parsed.get("estimated_price_eur")),
        "warranty_months": int(_num(parsed.get("warranty_months")) or 0) or None,
        "description": (parsed.get("description") or None),
        "activities": [str(a).strip() for a in (parsed.get("activities") or []) if str(a).strip()][:8],
        "consumables": [str(c).strip() for c in (parsed.get("consumables") or []) if str(c).strip()][:8],
        "confidence": int(_num(parsed.get("confidence")) or 0),
    }
    return {
        "suggestion": suggestion,
        "matched_item": ({"id": matched["id"], "name": matched["name"],
                          "brand": matched.get("brand"), "model": matched.get("model")} if matched else None),
    }
