"""
Service - Resolve Worker Hourly Rate.
Single source of truth for converting employee pay into hourly rate.

Priority:
1. manual_hourly_rate (if field exists)
2. hourly_rate (from employee_profiles)
3. daily_rate / hours_per_day
4. monthly_salary / working_days_per_month / standard_hours_per_day
5. base_salary with same formula as monthly
6. None → missing_rate warning
"""
from app.db import db

DEFAULT_WORKING_DAYS = 22
DEFAULT_HOURS_PER_DAY = 8


async def resolve_worker_hourly_rate(worker_id: str, org_id: str) -> dict:
    """
    Resolve hourly rate from employee profile fields.
    Returns: { rate: float, source: str, missing_rate: bool, missing_rate_reason: str|None }
    """
    profile = await db.employee_profiles.find_one(
        {"org_id": org_id, "user_id": worker_id}, {"_id": 0}
    )

    if not profile:
        return {"rate": 0, "source": "none", "missing_rate": True, "missing_rate_reason": "Няма профил на служителя"}

    # 1. manual_hourly_rate
    manual = profile.get("manual_hourly_rate")
    if manual and float(manual) > 0:
        return {"rate": round(float(manual), 2), "source": "manual_hourly_rate", "missing_rate": False, "missing_rate_reason": None}

    pay_type = (profile.get("pay_type") or "Monthly").strip()

    # 2. hourly_rate (explicit)
    hr = profile.get("hourly_rate")
    if hr and float(hr) > 0:
        return {"rate": round(float(hr), 2), "source": "hourly_rate", "missing_rate": False, "missing_rate_reason": None}

    # 3. daily_rate / hours_per_day
    dr = profile.get("daily_rate")
    if dr and float(dr) > 0:
        hpd = int(profile.get("standard_hours_per_day") or DEFAULT_HOURS_PER_DAY)
        rate = round(float(dr) / max(hpd, 1), 2)
        return {"rate": rate, "source": "daily_rate", "missing_rate": False, "missing_rate_reason": None}

    # 4. monthly_salary / working_days / hours
    ms = profile.get("monthly_salary") or profile.get("base_salary")
    if ms and float(ms) > 0:
        days = int(profile.get("working_days_per_month") or DEFAULT_WORKING_DAYS)
        hours = int(profile.get("standard_hours_per_day") or DEFAULT_HOURS_PER_DAY)
        total_h = days * hours
        rate = round(float(ms) / max(total_h, 1), 2)
        return {"rate": rate, "source": "monthly_salary", "missing_rate": False, "missing_rate_reason": None}

    # 5. base_salary as fallback
    bs = profile.get("base_salary")
    if bs and float(bs) > 0:
        days = int(profile.get("working_days_per_month") or DEFAULT_WORKING_DAYS)
        hours = int(profile.get("standard_hours_per_day") or DEFAULT_HOURS_PER_DAY)
        rate = round(float(bs) / max(days * hours, 1), 2)
        return {"rate": rate, "source": "base_salary", "missing_rate": False, "missing_rate_reason": None}

    return {"rate": 0, "source": "none", "missing_rate": True, "missing_rate_reason": f"Профилът ({pay_type}) няма валидна ставка"}
