"""
Service - Price Modifiers (cascade: org → project → line).
"""
from app.db import db

DEFAULT_MODIFIERS = {
    "waste_pct": 10,
    "floor_pct": 0,
    "center_pct": 0,
    "inhabited_pct": 0,
    "overhead_pct": 15,
    "risk_pct": 5,
    "profit_pct": 20,
}

DEFAULT_AUTO_RULES = {
    "floor_auto": True,
    "floor_per_floor_pct": 1.5,
    "inhabited_auto": True,
    "inhabited_value": 10,
}

MODIFIER_KEYS = list(DEFAULT_MODIFIERS.keys())


async def get_effective_modifiers(org_id: str, project_id: str = None, line_id: str = None) -> dict:
    """Cascade: org_default → project override → line override + auto-rules."""
    # 1. Org defaults
    org_cfg = await db.price_modifiers_config.find_one(
        {"org_id": org_id, "scope": "org_default"}, {"_id": 0}
    )
    mods = {**DEFAULT_MODIFIERS}
    auto = {**DEFAULT_AUTO_RULES}
    if org_cfg:
        for k in MODIFIER_KEYS:
            if k in (org_cfg.get("modifiers") or {}):
                mods[k] = org_cfg["modifiers"][k]
        for k in DEFAULT_AUTO_RULES:
            if k in (org_cfg.get("auto_rules") or {}):
                auto[k] = org_cfg["auto_rules"][k]

    # 2. Project override
    if project_id:
        proj_cfg = await db.price_modifiers_config.find_one(
            {"org_id": org_id, "scope": "project", "project_id": project_id}, {"_id": 0}
        )
        if proj_cfg:
            for k in MODIFIER_KEYS:
                if k in (proj_cfg.get("modifiers") or {}):
                    mods[k] = proj_cfg["modifiers"][k]
            for k in DEFAULT_AUTO_RULES:
                if k in (proj_cfg.get("auto_rules") or {}):
                    auto[k] = proj_cfg["auto_rules"][k]

        # Auto-rules from project data
        project = await db.projects.find_one(
            {"id": project_id, "org_id": org_id},
            {"_id": 0, "object_details": 1},
        )
        od = (project or {}).get("object_details") or {}

        if auto.get("floor_auto"):
            floors = od.get("floors_count") or 0
            if floors > 2:
                mods["floor_pct"] = round((floors - 2) * auto.get("floor_per_floor_pct", 1.5), 2)
            else:
                mods["floor_pct"] = 0

        if auto.get("inhabited_auto"):
            if od.get("is_inhabited"):
                mods["inhabited_pct"] = auto.get("inhabited_value", 10)
            else:
                mods["inhabited_pct"] = 0

    # 3. Line override
    if line_id:
        line_cfg = await db.price_modifiers_config.find_one(
            {"org_id": org_id, "scope": "line", "line_id": line_id}, {"_id": 0}
        )
        if line_cfg:
            for k in MODIFIER_KEYS:
                if k in (line_cfg.get("modifiers") or {}):
                    mods[k] = line_cfg["modifiers"][k]

    return {"modifiers": mods, "auto_rules": auto}


def apply_modifiers_to_price(base_cost: float, modifiers: dict) -> dict:
    """Apply all modifiers step by step."""
    steps = []
    price = base_cost
    steps.append({"label": "Себестойност", "pct": 0, "value": round(price, 2)})

    order = [
        ("waste_pct", "Фири/отпадък"),
        ("floor_pct", "Етажност"),
        ("center_pct", "Център/достъп"),
        ("inhabited_pct", "Обитаемост"),
        ("overhead_pct", "Режийни"),
        ("risk_pct", "Риск"),
        ("profit_pct", "Печалба"),
    ]

    for key, label in order:
        pct = modifiers.get(key, 0) or 0
        if pct != 0:
            price = price * (1 + pct / 100)
            steps.append({"label": label, "pct": pct, "value": round(price, 2)})

    total_markup = round((price / base_cost - 1) * 100, 2) if base_cost > 0 else 0

    return {
        "base_cost": round(base_cost, 2),
        "final_price": round(price, 2),
        "total_markup_pct": total_markup,
        "breakdown": steps,
        "modifiers_applied": modifiers,
    }
