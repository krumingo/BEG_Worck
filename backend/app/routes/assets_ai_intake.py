"""
Routes - Assets AI Intake (Пакет E1a: снимка -> разпознаване -> попълнени полета).

Нищо не записва в базата. Връща предложение, което фронтендът налива в
съществуващата форма за нов артикул. Реалният запис минава по стария път
(POST /assets/items + бройки + QR).

Ползва същата AI връзка като СМР предложенията (emergentintegrations, EMERGENT_LLM_KEY).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
import os
import json
import uuid

from app.deps.auth import get_current_user

router = APIRouter(tags=["AssetsAIIntake"])

ADMIN_ROLES = ["Admin", "Owner", "SiteManager", "Accountant"]
MAX_IMAGE_CHARS = 8_000_000  # ~6MB снимка в base64

SYSTEM_PROMPT = """Ти си експерт по строителна техника и инструменти в България.
Получаваш снимка на машина или инструмент (понякога и втора снимка на типовата табелка).
Върни САМО валиден JSON без markdown огради и без коментари, с точно тези ключове:
{
  "name": "кратко българско наименование, напр. Ъглошлайф",
  "type": "machine или tool",
  "group": "кратка група за филтриране, напр. Ъглошлайфи",
  "brand": "марка или null",
  "model": "модел или null",
  "serial_no": "сериен номер от табелката или null",
  "estimated_price_eur": число - примерна цена за НОВА такава в България в EUR, или null,
  "warranty_months": типична гаранция в месеци (число) или null,
  "description": "1-2 изречения: мощност, размер, предназначение",
  "activities": ["3 до 6 строителни дейности на български, за които служи"],
  "consumables": ["3 до 6 консуматива, които изисква, напр. Диск за метал 230мм"],
  "confidence": число 0-100 колко си сигурен в разпознаването
}
Ако не можеш да разпознаеш нищо смислено, върни confidence под 30 и name по най-добра преценка."""


class AIIntakeRequest(BaseModel):
    image_base64: str
    plate_image_base64: Optional[str] = None


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return text.strip()


@router.post("/assets/ai-intake")
async def ai_intake(data: AIIntakeRequest, user: dict = Depends(get_current_user)):
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    if not data.image_base64 or len(data.image_base64) < 100:
        raise HTTPException(status_code=400, detail="Image required")
    if len(data.image_base64) > MAX_IMAGE_CHARS or len(data.plate_image_base64 or "") > MAX_IMAGE_CHARS:
        raise HTTPException(status_code=400, detail="Image too large")

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY not configured")

    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

    images = [ImageContent(image_base64=data.image_base64)]
    if data.plate_image_base64:
        images.append(ImageContent(image_base64=data.plate_image_base64))

    chat = LlmChat(
        api_key=api_key,
        session_id=f"asset-intake-{uuid.uuid4().hex[:8]}",
        system_message=SYSTEM_PROMPT,
    ).with_model("openai", "gpt-4.1-mini")

    try:
        response = await chat.send_message(UserMessage(
            text="Разпознай машината/инструмента от снимката и върни JSON.",
            file_contents=images,
        ))
        parsed = json.loads(_strip_fences(str(response)))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI отговори в невалиден формат, опитай пак")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI error: {e}")

    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "name": str(parsed.get("name") or "").strip(),
        "type": parsed.get("type") if parsed.get("type") in ("machine", "tool") else "tool",
        "group": (parsed.get("group") or None),
        "brand": (parsed.get("brand") or None),
        "model": (parsed.get("model") or None),
        "serial_no": (parsed.get("serial_no") or None),
        "estimated_price_eur": _num(parsed.get("estimated_price_eur")),
        "warranty_months": int(_num(parsed.get("warranty_months")) or 0) or None,
        "description": (parsed.get("description") or None),
        "activities": [str(a).strip() for a in (parsed.get("activities") or []) if str(a).strip()][:8],
        "consumables": [str(c).strip() for c in (parsed.get("consumables") or []) if str(c).strip()][:8],
        "confidence": int(_num(parsed.get("confidence")) or 0),
    }
