"""
Service - Budget Formula (единна формула за ч.ч. / ч.д. / акорд).

Формула:
  akord = labor_budget / coefficient
  planned_man_days = akord / avg_daily_wage
  planned_man_hours = planned_man_days × hours_per_day

Всички consumer-и трябва да ползват тези функции вместо inline math.
See /app/memory/SOURCE_OF_TRUTH.md
"""

DEFAULT_DAILY_WAGE = 200
DEFAULT_HOURS_PER_DAY = 8
DEFAULT_COEFFICIENT = 1.0


def calculate_budget_formula_sync(
    labor_budget: float,
    coefficient: float = DEFAULT_COEFFICIENT,
    avg_daily_wage: float = DEFAULT_DAILY_WAGE,
    hours_per_day: float = DEFAULT_HOURS_PER_DAY,
) -> dict:
    """Sync version — use when avg_daily_wage is already known."""
    coefficient = coefficient if coefficient and coefficient > 0 else DEFAULT_COEFFICIENT
    avg_daily_wage = avg_daily_wage if avg_daily_wage and avg_daily_wage > 0 else DEFAULT_DAILY_WAGE
    hours_per_day = hours_per_day if hours_per_day and hours_per_day > 0 else DEFAULT_HOURS_PER_DAY

    akord = round(labor_budget / coefficient, 2) if labor_budget > 0 else 0
    planned_man_days = round(akord / avg_daily_wage, 2) if avg_daily_wage > 0 else 0
    planned_man_hours = round(planned_man_days * hours_per_day, 2)

    return {
        "akord": akord,
        "planned_man_days": planned_man_days,
        "planned_man_hours": planned_man_hours,
        "avg_daily_wage_used": round(avg_daily_wage, 2),
        "hours_per_day_used": hours_per_day,
        "coefficient_used": coefficient,
    }


async def calculate_budget_formula(
    labor_budget: float,
    coefficient: float = DEFAULT_COEFFICIENT,
    avg_daily_wage: float = None,
    hours_per_day: float = DEFAULT_HOURS_PER_DAY,
    org_id: str = None,
    project_id: str = None,
) -> dict:
    """Async version — computes avg_daily_wage from project team if not provided."""
    if avg_daily_wage is None or avg_daily_wage <= 0:
        if org_id and project_id:
            from app.routes.activity_budgets import compute_avg_daily_wage
            avg_daily_wage = await compute_avg_daily_wage(org_id, project_id)
        else:
            avg_daily_wage = DEFAULT_DAILY_WAGE

    return calculate_budget_formula_sync(labor_budget, coefficient, avg_daily_wage, hours_per_day)
