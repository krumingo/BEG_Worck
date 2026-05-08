"""
Pricing Engine — 3 AI agents for material price lookup.
Agent 1: BG retail stores (simulated with realistic data)
Agent 2: Online catalogs (simulated with realistic data)
Agent 3: Internal historical database (REAL — from historical_offers + ACTIVITY_KNOWLEDGE + calibration)
"""
import asyncio
import random
import logging
from datetime import datetime, timezone, timedelta
from statistics import median

from app.db import db
from app.services.ai_proposal import ACTIVITY_KNOWLEDGE, SYNONYMS

logger = logging.getLogger(__name__)

# ── Material Price Knowledge Base (BGN per unit) ───────────────────
# Realistic Bulgarian market prices for common construction materials
MATERIAL_PRICES_BGN = {
    # Бои и грундове
    "латекс интериорен": {"unit": "л", "price": 4.50, "category": "Бои", "stores": {"Практикер": 4.89, "Mr.Bricolage": 4.29, "Баумакс": 4.59}},
    "грунд": {"unit": "л", "price": 3.80, "category": "Грундове", "stores": {"Практикер": 3.99, "Mr.Bricolage": 3.59, "Баумакс": 3.79}},
    "грунд дълбокопроникващ": {"unit": "л", "price": 4.20, "category": "Грундове", "stores": {"Практикер": 4.49, "Mr.Bricolage": 3.99, "Баумакс": 4.19}},
    # Шпакловки и мазилки
    "шпакловка финишна": {"unit": "кг", "price": 1.80, "category": "Шпакловки", "stores": {"Практикер": 1.99, "Mr.Bricolage": 1.69, "Баумакс": 1.79}},
    "гипсова мазилка": {"unit": "кг", "price": 0.85, "category": "Мазилки", "stores": {"Практикер": 0.89, "Mr.Bricolage": 0.79, "Баумакс": 0.85}},
    "шпакловка за гк": {"unit": "кг", "price": 2.10, "category": "Шпакловки", "stores": {"Практикер": 2.29, "Mr.Bricolage": 1.99, "Баумакс": 2.09}},
    # Плочки и лепила
    "лепило за плочки": {"unit": "кг", "price": 0.95, "category": "Лепила", "stores": {"Практикер": 0.99, "Mr.Bricolage": 0.89, "Баумакс": 0.95}},
    "фугираща смес": {"unit": "кг", "price": 3.50, "category": "Фуги", "stores": {"Практикер": 3.79, "Mr.Bricolage": 3.29, "Баумакс": 3.49}},
    "хидроизолация": {"unit": "кг", "price": 5.50, "category": "Изолации", "stores": {"Практикер": 5.89, "Mr.Bricolage": 5.29, "Баумакс": 5.49}},
    # Гипсокартон
    "гипсокартон 12.5мм": {"unit": "м2", "price": 6.50, "category": "Гипсокартон", "stores": {"Практикер": 6.89, "Mr.Bricolage": 6.29, "Баумакс": 6.49}},
    "профили cd/ud": {"unit": "м", "price": 2.80, "category": "Профили", "stores": {"Практикер": 2.99, "Mr.Bricolage": 2.69, "Баумакс": 2.79}},
    "каменна вата 5см": {"unit": "м2", "price": 7.50, "category": "Изолации", "stores": {"Практикер": 7.89, "Mr.Bricolage": 7.19, "Баумакс": 7.49}},
    # Електро
    "кабел nym 3x2.5": {"unit": "м", "price": 3.20, "category": "Електро", "stores": {"Практикер": 3.49, "Mr.Bricolage": 2.99, "Баумакс": 3.19}},
    # ВиК
    "ppr тръба 20мм": {"unit": "м", "price": 2.50, "category": "ВиК", "stores": {"Практикер": 2.69, "Mr.Bricolage": 2.39, "Баумакс": 2.49}},
    # Консумативи
    "тиксо хартиено": {"unit": "бр", "price": 2.50, "category": "Консумативи", "stores": {"Практикер": 2.79, "Mr.Bricolage": 2.29, "Баумакс": 2.49}},
    "найлон покривен": {"unit": "м", "price": 0.80, "category": "Консумативи", "stores": {"Практикер": 0.89, "Mr.Bricolage": 0.69, "Баумакс": 0.79}},
    "шкурка p120": {"unit": "бр", "price": 1.20, "category": "Консумативи", "stores": {"Практикер": 1.29, "Mr.Bricolage": 1.09, "Баумакс": 1.19}},
    "шкурка p180": {"unit": "бр", "price": 1.30, "category": "Консумативи", "stores": {"Практикер": 1.39, "Mr.Bricolage": 1.19, "Баумакс": 1.29}},
    "силикон санитарен": {"unit": "бр", "price": 8.50, "category": "Уплътнители", "stores": {"Практикер": 8.99, "Mr.Bricolage": 7.99, "Баумакс": 8.49}},
    "бандажна лента": {"unit": "м", "price": 0.35, "category": "Консумативи", "stores": {"Практикер": 0.39, "Mr.Bricolage": 0.29, "Баумакс": 0.35}},
    "винтове за гк": {"unit": "бр", "price": 0.03, "category": "Крепежи", "stores": {"Практикер": 0.04, "Mr.Bricolage": 0.03, "Баумакс": 0.03}},
    "мрежа за мазилка": {"unit": "м", "price": 1.80, "category": "Армировка", "stores": {"Практикер": 1.99, "Mr.Bricolage": 1.69, "Баумакс": 1.79}},
    "плочки": {"unit": "м2", "price": 18.00, "category": "Облицовки", "stores": {"Практикер": 19.99, "Mr.Bricolage": 16.99, "Баумакс": 17.99}},
    "ъглови профили pvc": {"unit": "бр", "price": 1.50, "category": "Профили", "stores": {"Практикер": 1.69, "Mr.Bricolage": 1.39, "Баумакс": 1.49}},
    "кръстчета за фуги": {"unit": "бр", "price": 0.02, "category": "Консумативи", "stores": {"Практикер": 0.03, "Mr.Bricolage": 0.02, "Баумакс": 0.02}},
}

# Online catalog prices (slightly different from retail)
ONLINE_CATALOG = {
    "латекс интериорен": {"Зора Строй": 4.19, "СтройМаркет БГ": 4.39, "Строймат.бг": 4.09},
    "грунд": {"Зора Строй": 3.59, "СтройМаркет БГ": 3.79, "Строймат.бг": 3.49},
    "грунд дълбокопроникващ": {"Зора Строй": 3.89, "СтройМаркет БГ": 4.09, "Строймат.бг": 3.79},
    "шпакловка финишна": {"Зора Строй": 1.59, "СтройМаркет БГ": 1.79, "Строймат.бг": 1.49},
    "гипсова мазилка": {"Зора Строй": 0.75, "СтройМаркет БГ": 0.82, "Строймат.бг": 0.72},
    "лепило за плочки": {"Зора Строй": 0.85, "СтройМаркет БГ": 0.92, "Строймат.бг": 0.82},
    "гипсокартон 12.5мм": {"Зора Строй": 6.09, "СтройМаркет БГ": 6.39, "Строймат.бг": 5.99},
    "кабел nym 3x2.5": {"Зора Строй": 2.89, "СтройМаркет БГ": 3.09, "Строймат.бг": 2.79},
    "плочки": {"Зора Строй": 15.99, "СтройМаркет БГ": 17.49, "Строймат.бг": 14.99},
}


def _normalize_name(name: str) -> str:
    return name.lower().strip()


def _find_in_knowledge(name: str) -> dict:
    """Find material in MATERIAL_PRICES_BGN by fuzzy match."""
    norm = _normalize_name(name)
    if norm in MATERIAL_PRICES_BGN:
        return MATERIAL_PRICES_BGN[norm]
    for key, data in MATERIAL_PRICES_BGN.items():
        if key in norm or norm in key:
            return data
    return None


# ── Agent 1: BG Retail Stores ──────────────────────────────────────

async def fetch_price_agent_1(material_name: str) -> dict:
    """Simulate BG retail store price lookup."""
    known = _find_in_knowledge(material_name)
    if known and known.get("stores"):
        stores = known["stores"]
        store_name = random.choice(list(stores.keys()))
        base_price = stores[store_name]
        variance = random.uniform(-0.03, 0.05)
        price = round(base_price * (1 + variance), 2)
        return {
            "agent_id": 1,
            "source_name": store_name,
            "price": price,
            "currency": "BGN",
            "url": f"https://{store_name.lower().replace(' ', '').replace('.', '')}.bg/search?q={material_name.replace(' ', '+')}",
            "confidence": round(random.uniform(0.80, 0.92), 2),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    # Fallback: estimate from ACTIVITY_KNOWLEDGE
    base = _estimate_from_knowledge(material_name)
    if base:
        variance = random.uniform(-0.15, 0.15)
        price = round(base * (1 + variance), 2)
        return {
            "agent_id": 1,
            "source_name": "Практикер (оценка)",
            "price": max(price, 0.01),
            "currency": "BGN",
            "url": None,
            "confidence": round(random.uniform(0.45, 0.65), 2),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    return None


# ── Agent 2: Online Catalogs ───────────────────────────────────────

async def fetch_price_agent_2(material_name: str) -> dict:
    """Simulate online catalog price lookup."""
    norm = _normalize_name(material_name)
    catalogs = ONLINE_CATALOG.get(norm)
    if not catalogs:
        for key, cat in ONLINE_CATALOG.items():
            if key in norm or norm in key:
                catalogs = cat
                break
    if catalogs:
        source = random.choice(list(catalogs.keys()))
        base_price = catalogs[source]
        variance = random.uniform(-0.04, 0.06)
        price = round(base_price * (1 + variance), 2)
        return {
            "agent_id": 2,
            "source_name": source,
            "price": price,
            "currency": "BGN",
            "url": f"https://{source.lower().replace(' ', '')}.bg/{norm.replace(' ', '-')}",
            "confidence": round(random.uniform(0.70, 0.85), 2),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    base = _estimate_from_knowledge(material_name)
    if base:
        variance = random.uniform(-0.20, 0.10)
        price = round(base * (1 + variance), 2)
        return {
            "agent_id": 2,
            "source_name": "Зора Строй (оценка)",
            "price": max(price, 0.01),
            "currency": "BGN",
            "url": None,
            "confidence": round(random.uniform(0.40, 0.60), 2),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    return None


# ── Agent 3: Internal Historical Database (REAL) ──────────────────

async def fetch_price_agent_3(material_name: str, org_id: str) -> dict:
    """REAL agent — searches historical_offers, ACTIVITY_KNOWLEDGE, calibration."""
    norm = _normalize_name(material_name)
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Search historical_offer_rows for material references
    hist_prices = []
    pipeline = [
        {"$match": {"org_id": org_id}},
        {"$limit": 500},
    ]
    rows = await db.historical_offer_rows.find(
        {"org_id": org_id, "material_price_per_unit": {"$gt": 0}},
        {"_id": 0, "normalized_activity_subtype": 1, "material_price_per_unit": 1, "raw_text": 1},
    ).to_list(200)
    for r in rows:
        raw = (r.get("raw_text") or "").lower()
        sub = (r.get("normalized_activity_subtype") or "").lower()
        if norm in raw or norm in sub:
            hist_prices.append(r["material_price_per_unit"])

    # 2. Search ACTIVITY_KNOWLEDGE
    knowledge_price = _estimate_from_knowledge(material_name)

    # 3. Search calibration events
    cal_prices = []
    cal_events = await db.ai_calibration_events.find(
        {"org_id": org_id, "was_manually_edited": True},
        {"_id": 0, "original_material_price": 1, "final_material_price": 1, "activity_subtype": 1},
    ).to_list(100)
    for ev in cal_events:
        sub = (ev.get("activity_subtype") or "").lower()
        if norm in sub:
            fp = ev.get("final_material_price")
            if fp and fp > 0:
                cal_prices.append(fp)

    # Combine all sources
    all_prices = hist_prices + cal_prices
    if knowledge_price:
        all_prices.append(knowledge_price)

    if not all_prices:
        return None

    med = round(sorted(all_prices)[len(all_prices) // 2], 2)
    conf = min(0.95, 0.60 + len(all_prices) * 0.05)

    source_parts = []
    if hist_prices:
        source_parts.append(f"история ({len(hist_prices)})")
    if knowledge_price:
        source_parts.append("база знания")
    if cal_prices:
        source_parts.append(f"калибрация ({len(cal_prices)})")

    return {
        "agent_id": 3,
        "source_name": f"Вътрешна база: {', '.join(source_parts)}",
        "price": med,
        "currency": "BGN",
        "url": None,
        "confidence": round(conf, 2),
        "fetched_at": now_iso,
        "sample_count": len(all_prices),
    }


def _estimate_from_knowledge(material_name: str) -> float:
    """Estimate material unit price from ACTIVITY_KNOWLEDGE."""
    norm = _normalize_name(material_name)
    for act_key, act_data in ACTIVITY_KNOWLEDGE.items():
        for cat in ["primary", "secondary", "consumables"]:
            for mat in act_data.get("materials", {}).get(cat, []):
                mat_name = mat.get("name", "").lower()
                if norm in mat_name or mat_name in norm:
                    qpu = mat.get("qty_per_unit", 1)
                    mat_price_total = act_data.get("material_price", 10)
                    if qpu > 0:
                        return round(mat_price_total / max(qpu, 0.1) * 0.3, 2)
    return None


# ── Main Pricing Engine ────────────────────────────────────────────

CACHE_TTL_DAYS = 7

async def get_material_price(material_name: str, org_id: str, force_refresh: bool = False) -> dict:
    """Get material price from 3 agents with caching."""
    norm = _normalize_name(material_name)
    now = datetime.now(timezone.utc)

    # Check cache
    if not force_refresh:
        cached = await db.material_prices.find_one(
            {"org_id": org_id, "material_name_normalized": norm},
            {"_id": 0},
        )
        if cached:
            cached_until = cached.get("cached_until", "")
            try:
                exp = datetime.fromisoformat(cached_until.replace("Z", "+00:00"))
                if now < exp:
                    cached["from_cache"] = True
                    return cached
            except (ValueError, TypeError):
                pass

    # Fetch from 3 agents in parallel
    results = await asyncio.gather(
        fetch_price_agent_1(material_name),
        fetch_price_agent_2(material_name),
        fetch_price_agent_3(material_name, org_id),
        return_exceptions=True,
    )

    prices = []
    valid_results = []
    for r in results:
        if isinstance(r, dict) and r is not None and r.get("price"):
            valid_results.append(r)
            prices.append(r["price"])

    if not prices:
        return {
            "material_name": material_name,
            "material_name_normalized": norm,
            "prices": [],
            "median_price": None,
            "recommended_price": None,
            "confidence": 0,
            "from_cache": False,
            "error": "No pricing data available",
        }

    med = round(median(prices), 2)
    # Weighted avg confidence (agent 3 gets more weight)
    total_w = 0
    conf_sum = 0
    for r in valid_results:
        w = 2.0 if r.get("agent_id") == 3 else 1.0
        conf_sum += r.get("confidence", 0.5) * w
        total_w += w
    avg_conf = round(conf_sum / total_w, 2) if total_w > 0 else 0.5

    # Detect category from knowledge
    known = _find_in_knowledge(material_name)
    category = known.get("category", "Общо") if known else "Общо"
    unit = known.get("unit", "") if known else ""

    doc = {
        "material_name": material_name,
        "material_name_normalized": norm,
        "material_category": category,
        "unit": unit,
        "prices": valid_results,
        "median_price": med,
        "recommended_price": med,
        "confidence": avg_conf,
        "cached_until": (now + timedelta(days=CACHE_TTL_DAYS)).isoformat(),
        "last_refreshed_at": now.isoformat(),
        "from_cache": False,
    }

    # Upsert cache
    await db.material_prices.update_one(
        {"org_id": org_id, "material_name_normalized": norm},
        {"$set": {**doc, "org_id": org_id, "updated_at": now.isoformat()},
         "$setOnInsert": {"created_at": now.isoformat()}},
        upsert=True,
    )

    return doc


async def batch_get_prices(materials: list, org_id: str, force_refresh: bool = False) -> list:
    """Get prices for multiple materials in parallel."""
    tasks = [get_material_price(m, org_id, force_refresh) for m in materials]
    return await asyncio.gather(*tasks)
