"""
AI Proposal Service - Hybrid Provider Architecture.
Supports: LLM (OpenAI via Emergent) + Rule-Based fallback.
"""
import os
import json
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Rule-Based Knowledge Base ──────────────────────────────────────

ACTIVITY_KNOWLEDGE = {
    "мазилка": {
        "type": "Мокри процеси", "subtype": "Мазилка", "unit": "m2",
        "material_price": 8.50, "labor_price": 12.00,
        "small_qty_threshold": 5, "small_qty_multiplier": 1.35,
        "related": ["Грундиране преди мазилка", "Шпакловка", "Шлайфане", "Боядисване", "Ъглови профили"],
        "materials": {
            "primary": [
                {"name": "Гипсова мазилка", "unit": "кг", "qty_per_unit": 1.2, "category": "primary", "reason": "Основен материал за мазилка"},
                {"name": "Грунд", "unit": "л", "qty_per_unit": 0.15, "category": "primary", "reason": "Подготовка на основа"},
            ],
            "secondary": [
                {"name": "Ъглови профили PVC", "unit": "бр", "qty_per_unit": 0.3, "category": "secondary", "reason": "Защита на ръбове"},
                {"name": "Мрежа за мазилка", "unit": "м", "qty_per_unit": 0.5, "category": "secondary", "reason": "Армиране"},
                {"name": "Щифтове / дюбели", "unit": "бр", "qty_per_unit": 2, "category": "secondary", "reason": "Фиксиране на мрежа"},
            ],
            "consumables": [
                {"name": "Шкурка P120", "unit": "бр", "qty_per_unit": 0.1, "category": "consumable", "reason": "Шлайфане"},
                {"name": "Тиксо хартиено", "unit": "бр", "qty_per_unit": 0.05, "category": "consumable", "reason": "Маскиране"},
                {"name": "Найлон покривен", "unit": "м", "qty_per_unit": 0.3, "category": "consumable", "reason": "Защита на подове/мебели"},
            ],
        },
    },
    "боядисване": {
        "type": "Довършителни", "subtype": "Боядисване", "unit": "m2",
        "material_price": 4.50, "labor_price": 6.00,
        "small_qty_threshold": 10, "small_qty_multiplier": 1.30,
        "related": ["Шпакловка", "Шлайфане", "Грундиране", "Мазилка", "Тапети"],
        "materials": {
            "primary": [
                {"name": "Латекс интериорен", "unit": "л", "qty_per_unit": 0.25, "category": "primary", "reason": "Основна боя"},
                {"name": "Грунд дълбокопроникващ", "unit": "л", "qty_per_unit": 0.12, "category": "primary", "reason": "Подготовка на основа"},
            ],
            "secondary": [
                {"name": "Шпакловка финишна", "unit": "кг", "qty_per_unit": 0.3, "category": "secondary", "reason": "Корекция на неравности"},
            ],
            "consumables": [
                {"name": "Четка плоска", "unit": "бр", "qty_per_unit": 0.02, "category": "consumable", "reason": "Нанасяне по ъгли"},
                {"name": "Валяк / мече", "unit": "бр", "qty_per_unit": 0.03, "category": "consumable", "reason": "Нанасяне по площ"},
                {"name": "Тиксо хартиено", "unit": "бр", "qty_per_unit": 0.05, "category": "consumable", "reason": "Маскиране"},
                {"name": "Найлон покривен", "unit": "м", "qty_per_unit": 0.4, "category": "consumable", "reason": "Защита"},
                {"name": "Вана за боя", "unit": "бр", "qty_per_unit": 0.02, "category": "consumable", "reason": "Работа с валяк"},
                {"name": "Шкурка P180", "unit": "бр", "qty_per_unit": 0.08, "category": "consumable", "reason": "Подготовка"},
            ],
        },
    },
    "шпакловка": {
        "type": "Довършителни", "subtype": "Шпакловка", "unit": "m2",
        "material_price": 5.00, "labor_price": 8.00,
        "small_qty_threshold": 5, "small_qty_multiplier": 1.35,
        "related": ["Грундиране", "Боядисване", "Мазилка", "Шлайфане", "Тапети"],
        "materials": {
            "primary": [{"name": "Шпакловка финишна", "unit": "кг", "qty_per_unit": 1.0, "category": "primary", "reason": "Основен материал"}, {"name": "Грунд", "unit": "л", "qty_per_unit": 0.12, "category": "primary", "reason": "Подготовка"}],
            "secondary": [{"name": "Бандажна лента", "unit": "м", "qty_per_unit": 0.3, "category": "secondary", "reason": "Армиране фуги"}],
            "consumables": [{"name": "Шкурка P120/P180", "unit": "бр", "qty_per_unit": 0.15, "category": "consumable", "reason": "Шлайфане"}, {"name": "Шпакла 30см", "unit": "бр", "qty_per_unit": 0.01, "category": "consumable", "reason": "Нанасяне"}, {"name": "Найлон покривен", "unit": "м", "qty_per_unit": 0.3, "category": "consumable", "reason": "Защита"}],
        },
    },
    "плочки": {
        "type": "Довършителни", "subtype": "Облицовка", "unit": "m2",
        "material_price": 25.00, "labor_price": 22.00,
        "small_qty_threshold": 3, "small_qty_multiplier": 1.40,
        "related": ["Хидроизолация", "Фугиране", "Нивелация на основа", "Силиконова фуга", "Ъглови лайсни"],
        "materials": {
            "primary": [{"name": "Плочки", "unit": "м2", "qty_per_unit": 1.1, "category": "primary", "reason": "Основен материал + 10% запас"}, {"name": "Лепило за плочки", "unit": "кг", "qty_per_unit": 4.0, "category": "primary", "reason": "Залепване"}, {"name": "Фугираща смес", "unit": "кг", "qty_per_unit": 0.5, "category": "primary", "reason": "Фугиране"}],
            "secondary": [{"name": "Хидроизолация", "unit": "кг", "qty_per_unit": 0.8, "category": "secondary", "reason": "Влагоизолация при мокри помещения"}, {"name": "Грунд", "unit": "л", "qty_per_unit": 0.15, "category": "secondary", "reason": "Подготовка на основа"}, {"name": "Кръстчета за фуги", "unit": "бр", "qty_per_unit": 15, "category": "secondary", "reason": "Еднакви фуги"}],
            "consumables": [{"name": "Силикон санитарен", "unit": "бр", "qty_per_unit": 0.05, "category": "consumable", "reason": "Уплътняване ъгли"}, {"name": "Ъглови лайсни PVC", "unit": "м", "qty_per_unit": 0.3, "category": "consumable", "reason": "Защита на ръбове"}],
        },
    },
    "гипсокартон": {
        "type": "Сухо строителство", "subtype": "Гипсокартон", "unit": "m2",
        "material_price": 15.00, "labor_price": 16.00,
        "small_qty_threshold": 5, "small_qty_multiplier": 1.30,
        "related": ["Шпакловка на ГК", "Бандажиране", "Боядисване", "Звукоизолация", "Термоизолация"],
        "materials": {
            "primary": [{"name": "Гипсокартон 12.5мм", "unit": "м2", "qty_per_unit": 1.1, "category": "primary", "reason": "Основен материал"}, {"name": "Профили CD/UD", "unit": "м", "qty_per_unit": 2.5, "category": "primary", "reason": "Конструкция"}],
            "secondary": [{"name": "Каменна вата 5см", "unit": "м2", "qty_per_unit": 1.0, "category": "secondary", "reason": "Изолация"}, {"name": "Винтове за ГК", "unit": "бр", "qty_per_unit": 20, "category": "secondary", "reason": "Монтаж"}, {"name": "Дюбели", "unit": "бр", "qty_per_unit": 5, "category": "secondary", "reason": "Фиксиране"}],
            "consumables": [{"name": "Бандажна лента", "unit": "м", "qty_per_unit": 1.5, "category": "consumable", "reason": "Армиране фуги"}, {"name": "Шпакловка за ГК", "unit": "кг", "qty_per_unit": 0.5, "category": "consumable", "reason": "Запълване фуги"}],
        },
    },
    "електро": {
        "type": "Инсталации", "subtype": "Електро", "unit": "pcs",
        "material_price": 35.00, "labor_price": 25.00,
        "small_qty_threshold": 3, "small_qty_multiplier": 1.25,
        "related": ["Окабеляване", "Пробиване на канали", "Мазилка след канали", "Монтаж табло", "Заземяване"],
        "materials": {
            "primary": [{"name": "Кабел NYM 3x2.5", "unit": "м", "qty_per_unit": 5.0, "category": "primary", "reason": "Окабеляване"}, {"name": "Кутия конзола", "unit": "бр", "qty_per_unit": 1.0, "category": "primary", "reason": "Монтаж"}, {"name": "Ключ/контакт", "unit": "бр", "qty_per_unit": 1.0, "category": "primary", "reason": "Крайно устройство"}],
            "secondary": [{"name": "Гофрирана тръба", "unit": "м", "qty_per_unit": 5.0, "category": "secondary", "reason": "Защита на кабел"}, {"name": "Клеми", "unit": "бр", "qty_per_unit": 3, "category": "secondary", "reason": "Връзки"}],
            "consumables": [{"name": "Тиксо изолирбанд", "unit": "бр", "qty_per_unit": 0.1, "category": "consumable", "reason": "Изолация"}],
        },
    },
    "вик": {
        "type": "Инсталации", "subtype": "ВиК", "unit": "pcs",
        "material_price": 45.00, "labor_price": 30.00,
        "small_qty_threshold": 2, "small_qty_multiplier": 1.30,
        "related": ["Пробиване на канали", "Хидроизолация", "Мазилка", "Плочки", "Монтаж санитария"],
        "materials": {
            "primary": [{"name": "PPR тръба 20мм", "unit": "м", "qty_per_unit": 3.0, "category": "primary", "reason": "Водоснабдяване"}, {"name": "Фитинги PPR", "unit": "бр", "qty_per_unit": 4, "category": "primary", "reason": "Връзки"}],
            "secondary": [{"name": "Скоби", "unit": "бр", "qty_per_unit": 3, "category": "secondary", "reason": "Фиксиране"}, {"name": "Тефлонова лента", "unit": "бр", "qty_per_unit": 0.2, "category": "secondary", "reason": "Уплътняване резби"}],
            "consumables": [],
        },
    },
}

SYNONYMS = {
    "мазилк": "мазилка", "оштукатурване": "мазилка", "щукатур": "мазилка",
    "боя": "боядисване", "латекс": "боядисване", "пребоядисва": "боядисване",
    "шпакл": "шпакловка",
    "плоч": "плочки", "фаянс": "плочки", "теракот": "плочки", "облицов": "плочки",
    "гипсокарт": "гипсокартон", "сух монтаж": "гипсокартон",
    "ел.": "електро", "електрич": "електро", "окабеля": "електро", "контакт": "електро", "ключ": "електро",
    "водопров": "вик", "канализ": "вик", "тръб": "вик", "сифон": "вик",
}

DEFAULT_KNOWLEDGE = {
    "type": "Общо", "subtype": "СМР", "unit": "pcs",
    "material_price": 10.00, "labor_price": 15.00,
    "small_qty_threshold": 5, "small_qty_multiplier": 1.25,
    "related": ["Подготовка на основа", "Почистване", "Измерване"],
    "materials": {"primary": [], "secondary": [], "consumables": [{"name": "Общи консумативи", "unit": "к-т", "qty_per_unit": 0.1, "category": "consumable", "reason": "Различни"}]},
}

# City-based price adjustments (multiplier relative to national average)
CITY_PRICE_FACTORS = {
    "софия": 1.15, "пловдив": 1.00, "варна": 1.05, "бургас": 1.02,
    "стара загора": 0.95, "русе": 0.93, "плевен": 0.90, "велико търново": 0.92,
    "благоевград": 0.93, "добрич": 0.88, "шумен": 0.88, "перник": 0.90,
}


def _find_rule_knowledge(title: str) -> dict:
    title_lower = title.lower()
    for keyword, data in ACTIVITY_KNOWLEDGE.items():
        if keyword.lower() in title_lower:
            return data
    for syn, key in SYNONYMS.items():
        if syn in title_lower:
            return ACTIVITY_KNOWLEDGE.get(key, DEFAULT_KNOWLEDGE)
    return DEFAULT_KNOWLEDGE


def rule_based_proposal(title: str, unit: str, qty: float, city: str = None) -> dict:
    """Generate proposal using rule-based knowledge base"""
    knowledge = _find_rule_knowledge(title)
    material_price = knowledge["material_price"]
    labor_price = knowledge["labor_price"]

    # City adjustment
    city_factor = 1.0
    city_label = None
    if city:
        city_factor = CITY_PRICE_FACTORS.get(city.lower().strip(), 1.0)
        city_label = city.strip()
        material_price = round(material_price * city_factor, 2)
        labor_price = round(labor_price * city_factor, 2)

    # Small qty adjustment
    small_qty_adj = 0
    base_material = material_price
    base_labor = labor_price
    if qty <= knowledge["small_qty_threshold"]:
        m = knowledge["small_qty_multiplier"]
        small_qty_adj = round((m - 1) * 100, 0)
        material_price = round(material_price * m, 2)
        labor_price = round(labor_price * m, 2)

    total_price = round(material_price + labor_price, 2)

    materials = []
    for cat_key in ["primary", "secondary", "consumables"]:
        for mat in knowledge["materials"].get(cat_key, []):
            est = round(mat.get("qty_per_unit", 0) * qty, 2) if mat.get("qty_per_unit") else None
            materials.append({
                "name": mat["name"], "unit": mat.get("unit", ""), "estimated_qty": est,
                "category": mat.get("category", cat_key), "reason": mat.get("reason", ""),
            })

    return {
        "provider": "rule-based",
        "recognized": {
            "activity_type": knowledge["type"],
            "activity_subtype": knowledge["subtype"],
            "suggested_unit": knowledge["unit"],
        },
        "pricing": {
            "material_price_per_unit": material_price,
            "labor_price_per_unit": labor_price,
            "total_price_per_unit": total_price,
            "base_material_price": base_material,
            "base_labor_price": base_labor,
            "small_qty_adjustment_percent": small_qty_adj,
            "small_qty_explanation": f"Количество {qty} е под прага от {knowledge['small_qty_threshold']} — приложена корекция +{small_qty_adj}% за дребен обем" if small_qty_adj > 0 else None,
            "city_factor": city_factor if city_factor != 1.0 else None,
            "city": city_label,
            "total_estimated": round(total_price * qty, 2),
        },
        "related_smr": knowledge["related"][:5],
        "materials": materials,
        "confidence": 0.85 if knowledge != DEFAULT_KNOWLEDGE else 0.3,
        "explanation": f"Разпознато като {knowledge['type']} / {knowledge['subtype']} чрез ключови думи",
    }


# ── LLM Provider ───────────────────────────────────────────────────

LLM_SYSTEM_PROMPT = """Ти си експерт по строително-монтажни работи (СМР) в България.
Анализираш описание на СМР и връщаш структурирано JSON предложение.

Отговори САМО с валиден JSON (без markdown, без обяснения извън JSON):
{
  "activity_type": "тип дейност (напр. Мокри процеси, Довършителни, Инсталации, Сухо строителство)",
  "activity_subtype": "подтип (напр. Мазилка, Боядисване, Облицовка)",
  "suggested_unit": "м2 или бр или м или часа",
  "material_price_per_unit": число_лв,
  "labor_price_per_unit": число_лв,
  "small_qty_note": "бележка ако количеството е малко",
  "explanation": "кратко обяснение на предложението",
  "related_smr": ["свързана работа 1", "свързана работа 2", "...до 5 позиции"],
  "materials": [
    {"name": "име", "unit": "ед", "qty_per_unit": число, "category": "primary/secondary/consumable", "reason": "защо"}
  ]
}

Правила:
- Цените са в лв (BGN), ориентировъчни за България
- При малко количество (под 5 м2 или под 3 бр) добави 25-40% надбавка
- materials трябва да включват: основни, спомагателни и консумативи
- Бъди конкретен за материалите, не пропускай нищо очевидно
- Всеки материал трябва да има reason"""


async def llm_proposal(title: str, unit: str, qty: float, city: str = None) -> dict:
    """Generate proposal using LLM (OpenAI via Emergent)"""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not configured")

    from emergentintegrations.llm.chat import LlmChat, UserMessage

    city_hint = f" в град {city}" if city else " в България"
    user_text = f"""Анализирай следното СМР:
Описание: {title}
Мярка: {unit}
Количество: {qty}{city_hint}

Върни JSON предложение за цена, материали и свързани работи."""

    chat = LlmChat(
        api_key=api_key,
        session_id=f"ai-proposal-{uuid.uuid4().hex[:8]}",
        system_message=LLM_SYSTEM_PROMPT,
    ).with_model("openai", "gpt-4.1-mini")

    response = await chat.send_message(UserMessage(text=user_text))

    # Parse JSON from response
    response_text = str(response).strip()
    # Remove markdown code fences if present
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        response_text = "\n".join(lines)

    data = json.loads(response_text)

    # Build standardized response
    material_price = float(data.get("material_price_per_unit", 10))
    labor_price = float(data.get("labor_price_per_unit", 15))
    total_price = round(material_price + labor_price, 2)

    # City adjustment from our data
    city_factor = 1.0
    if city:
        city_factor = CITY_PRICE_FACTORS.get(city.lower().strip(), 1.0)
        material_price = round(material_price * city_factor, 2)
        labor_price = round(labor_price * city_factor, 2)
        total_price = round(material_price + labor_price, 2)

    materials = []
    for mat in data.get("materials", []):
        est = round(float(mat.get("qty_per_unit", 0)) * qty, 2) if mat.get("qty_per_unit") else None
        materials.append({
            "name": mat.get("name", ""),
            "unit": mat.get("unit", ""),
            "estimated_qty": est,
            "category": mat.get("category", "primary"),
            "reason": mat.get("reason", ""),
        })

    return {
        "provider": "llm",
        "recognized": {
            "activity_type": data.get("activity_type", "Общо"),
            "activity_subtype": data.get("activity_subtype", "СМР"),
            "suggested_unit": data.get("suggested_unit", unit),
        },
        "pricing": {
            "material_price_per_unit": material_price,
            "labor_price_per_unit": labor_price,
            "total_price_per_unit": total_price,
            "base_material_price": float(data.get("material_price_per_unit", 10)),
            "base_labor_price": float(data.get("labor_price_per_unit", 15)),
            "small_qty_adjustment_percent": 0,
            "small_qty_explanation": data.get("small_qty_note"),
            "city_factor": city_factor if city_factor != 1.0 else None,
            "city": city.strip() if city else None,
            "total_estimated": round(total_price * qty, 2),
        },
        "related_smr": data.get("related_smr", [])[:7],
        "materials": materials,
        "confidence": 0.90,
        "explanation": data.get("explanation", "Анализирано от AI"),
    }


# ── Hybrid Provider ────────────────────────────────────────────────

async def get_ai_proposal(title: str, unit: str, qty: float, city: str = None) -> dict:
    """
    Hybrid AI proposal: tries LLM first, falls back to rule-based.
    Returns standardized proposal dict.
    """
    # Try LLM first
    try:
        result = await llm_proposal(title, unit, qty, city)
        logger.info(f"LLM proposal succeeded for: {title[:50]}")
        return result
    except Exception as e:
        logger.warning(f"LLM proposal failed ({type(e).__name__}: {e}), falling back to rule-based")

    # Fallback to rule-based
    result = rule_based_proposal(title, unit, qty, city)
    result["fallback_reason"] = "LLM недостъпен, използван rule-based engine"
    return result
