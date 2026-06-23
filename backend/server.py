"""
BEG_Work Backend Server — entry point.

Thin entry: assembles the FastAPI app from modular pieces in app/.
- Pydantic models live under app/models/
- Auth & module-gating dependencies live under app/deps/
- Constants live under app/constants.py
- Stripe / mobile / seed live under app/core/
- All routes live under app/routes/

Re-exports below preserve the legacy ``from server import ...`` surface so
that downstream modules (mobile.py, billing.py, app/main.py, tools/) keep
working without changes.

History:
- M16.7 (2026-05-05): removed migrate_to_production / app.migrations.
- M16.8 (2026-05-06): collapsed 1400-line monolith → ~510-line entry point.
  Removed inline Pydantic models (now in app/models/), inline auth helpers
  (now in app/deps/auth.py and app/deps/modules.py), inline log_audit
  (now in app/utils/audit.py), inline seed_data (now in app/core/seed.py),
  inline Stripe config (now in app/core/stripe_config.py), inline mobile
  constants (now in app/core/mobile_constants.py), and duplicated ROLES /
  MODULES / SUBSCRIPTION_PLANS (now in app/constants.py).
  Added missing import for run_reminder_jobs (latent NameError fixed).
"""
from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import asyncio
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# ── DB & shared state ────────────────────────────────────────────────────
from app.db import db, client

# ── Constants (re-exported for backwards compatibility) ─────────────────
from app.constants import ROLES, MODULES, SUBSCRIPTION_PLANS, LIMIT_WARNING_THRESHOLD  # noqa: F401
SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "canceled", "incomplete"]

# ── Stripe config (re-exported for app/routes/billing.py) ───────────────
from app.core.stripe_config import (  # noqa: F401
    STRIPE_API_KEY, STRIPE_MOCK_MODE, is_stripe_configured,
)

# ── Mobile constants (re-exported for app/routes/mobile.py) ─────────────
from app.core.mobile_constants import (  # noqa: F401
    MOBILE_MODULES, MOBILE_ACTIONS, MOBILE_FIELDS, DEFAULT_MOBILE_CONFIGS,
)

# ── Auth helpers (re-exported for any legacy `from server import ...`) ──
from app.deps.auth import (  # noqa: F401
    hash_password, verify_password, create_token,
    get_current_user, require_admin,
    get_user_project_ids, can_access_project, can_manage_project,
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRATION_HOURS,
    pwd_context, security,
)
from app.deps.modules import (  # noqa: F401
    check_module_access_for_org, require_module,
    require_m2, require_m4, require_m5, require_m9,
)
from app.utils.audit import log_audit  # noqa: F401

# ── Seed & background jobs ──────────────────────────────────────────────
from app.core.seed import seed_data
from app.routes.attendance import run_reminder_jobs

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── App assembly ────────────────────────────────────────────────────────
app = FastAPI(title="BEG_Work API")
api_router = APIRouter(prefix="/api")

# ── Router Registration ─────────────────────────────────────────────────

# Import health router - includes health, debug routes
from app.routes.health import router as health_router
api_router.include_router(health_router)

# Import auth router - includes auth, org, users, feature-flags, audit-logs
from app.routes.auth import router as auth_router
api_router.include_router(auth_router)

# Import projects router - includes projects, team, phases, enums
from app.routes.projects import router as projects_router
api_router.include_router(projects_router)

# Import attendance router - includes attendance, work-reports, reminders, notifications
from app.routes.attendance import router as attendance_router
api_router.include_router(attendance_router)

# Import offers router - includes offers, activity-catalog, offer-enums
from app.routes.offers import router as offers_router
api_router.include_router(offers_router)

# Import HR/payroll router - includes employees, advances, payroll-runs, payslips, payroll-enums
from app.routes.hr import router as hr_router
api_router.include_router(hr_router)

# Import finance router - includes accounts, invoices, payments, finance stats/enums
from app.routes.finance import router as finance_router
api_router.include_router(finance_router)

# Import overhead router - includes dashboard/stats, overhead categories/costs/assets/snapshots/allocations
from app.routes.overhead import router as overhead_router
api_router.include_router(overhead_router)

# Import billing router - includes plans, config, signup, checkout, webhook, subscription, usage
from app.routes.billing import router as billing_router
api_router.include_router(billing_router)

# Import mobile router - includes bootstrap, settings, view-configs
from app.routes.mobile import router as mobile_router
api_router.include_router(mobile_router)

# Import media router - includes upload, link, file serving
from app.routes.media import router as media_router
api_router.include_router(media_router)

# Import warehouse router
from app.routes.warehouses import router as warehouses_router
api_router.include_router(warehouses_router)
from app.routes.warehouse_batches import router as warehouse_batches_router
api_router.include_router(warehouse_batches_router)
from app.routes.sales import router as sales_router
api_router.include_router(sales_router)

# Import scan docs router
from app.routes.scan_docs import router as scan_docs_router
api_router.include_router(scan_docs_router)

# Import invoice lines router (separate collection)
from app.routes.invoice_lines import router as invoice_lines_router
api_router.include_router(invoice_lines_router)

# Import counterparties router (suppliers/clients)
from app.routes.counterparties import router as counterparties_router
api_router.include_router(counterparties_router)

# Import items router (materials/inventory items)
from app.routes.items import router as items_router
api_router.include_router(items_router)

# Import reports router (prices, turnover)
from app.routes.reports import router as reports_router
api_router.include_router(reports_router)

# Clients router
from app.routes.clients import router as clients_router
api_router.include_router(clients_router)

# Dashboard routes (activity, finance details)
from app.routes.dashboard import router as dashboard_extra_router
api_router.include_router(dashboard_extra_router)

# Import platform bootstrap router - ONE-TIME USE for production setup
from app.routes.platform import router as platform_router
app.include_router(platform_router)  # Direct to app (not under /api prefix)

# Import work logs router (Дневник + Промени СМР)
from app.routes.work_logs import router as work_logs_router
api_router.include_router(work_logs_router)

# Import activity budgets router
from app.routes.activity_budgets import router as activity_budgets_router
api_router.include_router(activity_budgets_router)

# Import offer versions router
from app.routes.offer_versions import router as offer_versions_router
api_router.include_router(offer_versions_router)

# Import extra works router - includes extra work drafts, AI proposals, create offer from drafts
from app.routes.extra_works import router as extra_works_router
api_router.include_router(extra_works_router)

# Import AI calibration router - includes analytics, calibration approval
from app.routes.ai_calibration import router as ai_calibration_router
api_router.include_router(ai_calibration_router)

# Import procurement router - includes material requests, supplier invoices, warehouse posting
from app.routes.procurement import router as procurement_router
api_router.include_router(procurement_router)

# Import historical offers router
from app.routes.historical_offers import router as historical_offers_router
api_router.include_router(historical_offers_router)

# Import revenue & expense core router
from app.routes.revenue_expense import router as revenue_expense_router
api_router.include_router(revenue_expense_router)

# Import materials baseline router
from app.routes.materials_baseline import router as materials_baseline_router
api_router.include_router(materials_baseline_router)

# Import subcontractors router
from app.routes.subcontractors import router as subcontractors_router
api_router.include_router(subcontractors_router)

# Import labor by SMR router
from app.routes.labor_smr import router as labor_smr_router
api_router.include_router(labor_smr_router)

# Import material cost by SMR router
from app.routes.material_smr import router as material_smr_router
api_router.include_router(material_smr_router)

# Import full cost / overhead / margin router
from app.routes.full_cost import router as full_cost_router
api_router.include_router(full_cost_router)

# Import revenue snapshot / profit period / procurement router
from app.routes.revenue_snapshot import router as revenue_snapshot_router
api_router.include_router(revenue_snapshot_router)

# Import budget freeze / progress router
from app.routes.budget_progress import router as budget_progress_router
api_router.include_router(budget_progress_router)

# Import employee daily reports router
from app.routes.daily_reports import router as daily_reports_router
api_router.include_router(daily_reports_router)

# Import missing SMR router
from app.routes.missing_smr import router as missing_smr_router
api_router.include_router(missing_smr_router)

# Import locations router
from app.routes.locations import router as locations_router
api_router.include_router(locations_router)

# Import SMR analysis router
from app.routes.smr_analysis import router as smr_analysis_router
api_router.include_router(smr_analysis_router)

# Import pricing router
from app.routes.pricing import router as pricing_router
api_router.include_router(pricing_router)

# Import work sessions router
from app.routes.work_sessions import router as work_sessions_router
api_router.include_router(work_sessions_router)

# Import SMR groups router
from app.routes.smr_groups import router as smr_groups_router
api_router.include_router(smr_groups_router)

# Import project P&L router
from app.routes.project_pnl import router as project_pnl_router
api_router.include_router(project_pnl_router)

# Import price modifiers router
from app.routes.price_modifiers import router as price_modifiers_router
api_router.include_router(price_modifiers_router)

# Import overhead realtime router
from app.routes.overhead_realtime import router as overhead_realtime_router
api_router.include_router(overhead_realtime_router)

# Import pulse router
from app.routes.pulse import router as pulse_router
api_router.include_router(pulse_router)

# Import alarms router
from app.routes.alarms import router as alarms_router
api_router.include_router(alarms_router)

# Import technician router
from app.routes.technician import router as technician_router
api_router.include_router(technician_router)

# Import morning briefing router
from app.routes.morning_briefing import router as morning_briefing_router
api_router.include_router(morning_briefing_router)

# Import cashflow forecast router
from app.routes.cashflow_forecast import router as cashflow_forecast_router
api_router.include_router(cashflow_forecast_router)

# Import expected vs actual router
from app.routes.expected_actual import router as expected_actual_router
api_router.include_router(expected_actual_router)

# Import material waste router
from app.routes.material_waste import router as material_waste_router
api_router.include_router(material_waste_router)

# Import excel import v2 router
from app.routes.excel_import_v2 import router as excel_import_v2_router
api_router.include_router(excel_import_v2_router)

# Import subcontractor performance router
from app.routes.subcontractor_performance import router as subcontractor_perf_router
api_router.include_router(subcontractor_perf_router)

# Import centralized reports router
from app.routes.centralized_reports import router as centralized_reports_router
api_router.include_router(centralized_reports_router)

# Import resource model router
from app.routes.resource_model import router as resource_model_router
api_router.include_router(resource_model_router)

# Import financial results router
from app.routes.financial_results import router as financial_results_router
api_router.include_router(financial_results_router)

# Import OCR invoice router
from app.routes.ocr_invoice import router as ocr_invoice_router
api_router.include_router(ocr_invoice_router)

from app.routes.all_reports import router as all_reports_router
api_router.include_router(all_reports_router)

from app.routes.weekly_matrix import router as weekly_matrix_router
api_router.include_router(weekly_matrix_router)



from app.routes.employee_dossier import router as employee_dossier_router
api_router.include_router(employee_dossier_router)

from app.routes.brigades import router as brigades_router
api_router.include_router(brigades_router)

from app.routes.pay_runs import router as pay_runs_router
api_router.include_router(pay_runs_router)

from app.routes.settings import router as settings_router
api_router.include_router(settings_router)

from app.routes.assets_qr import router as assets_qr_router
api_router.include_router(assets_qr_router)

from app.routes.assets_items import router as assets_items_router
api_router.include_router(assets_items_router)

from app.routes.assets_units import router as assets_units_router
api_router.include_router(assets_units_router)
from app.routes.assets_custody import router as assets_custody_router
api_router.include_router(assets_custody_router)
from app.routes.assets_ai_intake import router as assets_ai_intake_router
api_router.include_router(assets_ai_intake_router)
from app.routes.asset_item_types import router as asset_item_types_router
api_router.include_router(asset_item_types_router)
from app.routes.assets_batch_intake import router as assets_batch_intake_router
api_router.include_router(assets_batch_intake_router)
from app.routes.assets_intake_pending import router as assets_intake_pending_router
api_router.include_router(assets_intake_pending_router)
from app.routes.assets_repairs import router as assets_repairs_router
api_router.include_router(assets_repairs_router)

# ── App Setup ────────────────────────────────────────────────────

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global error handler (catches unhandled exceptions)
from app.middleware.error_handler import ErrorHandlerMiddleware
app.add_middleware(ErrorHandlerMiddleware)

@app.on_event("startup")
async def startup():
    await seed_data()

    # FIFO indexes (warehouse_batches)
    from app.services.fifo_service import ensure_indexes as ensure_fifo_indexes
    await ensure_fifo_indexes()

    await db.users.create_index("email")
    await db.users.create_index("org_id")
    await db.organizations.create_index("id", unique=True)
    await db.feature_flags.create_index([("org_id", 1), ("module_code", 1)])
    await db.audit_logs.create_index([("org_id", 1), ("timestamp", -1)])
    await db.projects.create_index([("org_id", 1), ("code", 1)], unique=True)
    await db.projects.create_index([("org_id", 1), ("status", 1)])
    await db.project_team.create_index([("project_id", 1), ("user_id", 1)])
    await db.project_team.create_index("user_id")
    await db.project_phases.create_index("project_id")
    await db.attendance_entries.create_index([("org_id", 1), ("date", 1), ("user_id", 1)], unique=True)
    await db.attendance_entries.create_index([("org_id", 1), ("date", 1)])
    await db.work_reports.create_index([("org_id", 1), ("date", 1), ("user_id", 1), ("project_id", 1)], unique=True)
    await db.work_reports.create_index([("org_id", 1), ("date", 1)])
    await db.work_reports.create_index([("org_id", 1), ("user_id", 1)])
    await db.reminder_logs.create_index([("org_id", 1), ("type", 1), ("date", 1), ("user_id", 1)])
    await db.notifications.create_index([("org_id", 1), ("user_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("org_id", 1), ("user_id", 1), ("is_read", 1)])
    # M2 Estimates indexes
    await db.offers.create_index([("org_id", 1), ("offer_no", 1)])
    await db.offers.create_index([("org_id", 1), ("project_id", 1)])
    await db.offers.create_index([("org_id", 1), ("status", 1)])
    await db.activity_catalog.create_index([("org_id", 1), ("project_id", 1)])
    await db.activity_catalog.create_index([("org_id", 1), ("project_id", 1), ("active", 1)])
    # M4 Payroll indexes
    await db.employee_profiles.create_index([("org_id", 1), ("user_id", 1)], unique=True)
    await db.advances.create_index([("org_id", 1), ("user_id", 1)])
    await db.advances.create_index([("org_id", 1), ("status", 1)])
    await db.payroll_runs.create_index([("org_id", 1), ("status", 1)])
    await db.payslips.create_index([("org_id", 1), ("payroll_run_id", 1)])
    await db.payslips.create_index([("org_id", 1), ("user_id", 1)])
    await db.payroll_payments.create_index([("org_id", 1), ("payroll_run_id", 1)])
    # M9 Overhead indexes
    await db.overhead_categories.create_index([("org_id", 1)])
    await db.overhead_costs.create_index([("org_id", 1), ("date_incurred", -1)])
    await db.overhead_costs.create_index([("org_id", 1), ("category_id", 1)])
    await db.overhead_assets.create_index([("org_id", 1), ("active", 1)])
    await db.overhead_snapshots.create_index([("org_id", 1), ("computed_at", -1)])
    await db.overhead_snapshots.create_index([("org_id", 1), ("period_start", 1), ("period_end", 1)])
    await db.project_overhead_allocations.create_index([("org_id", 1), ("overhead_snapshot_id", 1)])
    await db.project_overhead_allocations.create_index([("org_id", 1), ("project_id", 1)])
    # Billing indexes
    await db.subscriptions.create_index([("org_id", 1)], unique=True)
    await db.subscriptions.create_index([("stripe_subscription_id", 1)])
    await db.subscriptions.create_index([("stripe_customer_id", 1)])
    # Mobile integration indexes
    await db.org_mobile_settings.create_index([("org_id", 1)], unique=True)
    await db.mobile_view_configs.create_index([("org_id", 1), ("role", 1), ("module_code", 1)], unique=True)
    await db.media_files.create_index([("org_id", 1), ("owner_user_id", 1)])
    await db.media_files.create_index([("org_id", 1), ("context_type", 1), ("context_id", 1)])
    
    # Warehouses indexes
    await db.warehouses.create_index([("org_id", 1), ("code", 1)], unique=True)
    await db.warehouses.create_index([("org_id", 1), ("type", 1)])
    await db.warehouses.create_index([("org_id", 1), ("project_id", 1)])
    await db.warehouses.create_index([("org_id", 1), ("active", 1)])
    
    # Scan docs indexes
    await db.scan_docs.create_index([("org_id", 1), ("linked_invoice_id", 1)])
    await db.scan_docs.create_index([("org_id", 1), ("uploaded_by_user_id", 1)])
    await db.scan_docs.create_index([("org_id", 1), ("created_at", -1)])
    
    # Invoice lines indexes (separate collection)
    await db.invoice_lines.create_index([("org_id", 1), ("invoice_id", 1)])
    await db.invoice_lines.create_index([("org_id", 1), ("allocation_type", 1), ("allocation_ref_id", 1)])
    await db.invoice_lines.create_index([("org_id", 1), ("purchased_by_user_id", 1)])
    await db.invoice_lines.create_index([("invoice_id", 1), ("line_no", 1)], unique=True)
    
    # Counterparties indexes
    await db.counterparties.create_index([("org_id", 1), ("name", 1)])
    await db.counterparties.create_index([("org_id", 1), ("eik", 1)], sparse=True)  # Non-unique - check manually in code
    await db.counterparties.create_index([("org_id", 1), ("type", 1)])
    await db.counterparties.create_index([("org_id", 1), ("active", 1)])
    
    # Items indexes
    await db.items.create_index([("org_id", 1), ("sku", 1)], unique=True)
    await db.items.create_index([("org_id", 1), ("name", 1)])
    await db.items.create_index([("org_id", 1), ("category", 1)])
    await db.items.create_index([("org_id", 1), ("is_active", 1)])
    
    # Cash transactions indexes
    await db.cash_transactions.create_index([("org_id", 1), ("date", -1)])
    await db.cash_transactions.create_index([("org_id", 1), ("type", 1)])
    
    # Overhead transactions indexes
    await db.overhead_transactions.create_index([("org_id", 1), ("date", -1)])
    
    # Bonus payments indexes
    await db.bonus_payments.create_index([("org_id", 1), ("date", -1)])
    
    # Clients indexes
    await db.clients.create_index([("org_id", 1), ("phone_normalized", 1)], unique=True)
    await db.clients.create_index([("org_id", 1), ("last_name", 1)])
    await db.clients.create_index([("org_id", 1), ("is_active", 1)])
    await db.bonus_payments.create_index([("org_id", 1), ("user_id", 1)])
    
    # Payroll payments indexes (if not already exists)
    await db.payroll_payments.create_index([("org_id", 1), ("payment_date", -1)])
    
    # Work Logs & Change Orders indexes (Дневник + Промени СМР)
    await db.work_types.create_index([("org_id", 1), ("name", 1)], unique=True)
    await db.daily_work_logs.create_index([("org_id", 1), ("site_id", 1), ("date", -1)])
    await db.daily_work_logs.create_index([("org_id", 1), ("date", -1)])
    await db.change_orders.create_index([("org_id", 1), ("site_id", 1), ("status", 1)])
    await db.change_orders.create_index([("org_id", 1), ("status", 1), ("requested_at", -1)])
    await db.change_orders.create_index([("org_id", 1), ("site_id", 1), ("work_type_id", 1)])
    
    # Activity budgets indexes
    await db.activity_budgets.create_index([("org_id", 1), ("project_id", 1), ("type", 1), ("subtype", 1)], unique=True)
    await db.activity_budgets.create_index([("org_id", 1), ("project_id", 1)])
    
    # Offer versions indexes
    await db.offer_versions.create_index([("org_id", 1), ("offer_id", 1), ("version_number", 1)], unique=True)
    await db.offer_versions.create_index([("org_id", 1), ("project_id", 1), ("offer_id", 1)])

    # Missing SMR indexes
    await db.missing_smr.create_index([("org_id", 1), ("project_id", 1), ("status", 1)])
    await db.missing_smr.create_index([("org_id", 1), ("status", 1), ("created_at", -1)])
    await db.missing_smr.create_index([("org_id", 1), ("project_id", 1), ("floor", 1)])

    # Location nodes indexes
    await db.location_nodes.create_index([("org_id", 1), ("project_id", 1)])
    await db.location_nodes.create_index([("org_id", 1), ("project_id", 1), ("parent_id", 1)])
    await db.location_nodes.create_index([("org_id", 1), ("project_id", 1), ("type", 1)])

    # SMR analyses indexes
    await db.smr_analyses.create_index([("org_id", 1), ("project_id", 1), ("version", -1)])
    await db.smr_analyses.create_index([("org_id", 1), ("status", 1)])

    # Material prices indexes
    await db.material_prices.create_index([("org_id", 1), ("material_name_normalized", 1)], unique=True)
    await db.material_prices.create_index([("org_id", 1), ("material_category", 1)])

    # Work sessions indexes
    await db.work_sessions.create_index([("org_id", 1), ("worker_id", 1), ("ended_at", 1)])
    await db.work_sessions.create_index([("org_id", 1), ("site_id", 1), ("started_at", -1)])
    await db.work_sessions.create_index([("org_id", 1), ("worker_id", 1), ("started_at", -1)])

    # SMR groups indexes
    await db.smr_groups.create_index([("org_id", 1), ("project_id", 1), ("location_id", 1)])
    await db.smr_groups.create_index([("org_id", 1), ("project_id", 1), ("sort_order", 1)])


    # Invoice unique number index (prevents duplicates)
    try:
        await db.invoices.create_index([("org_id", 1), ("invoice_no", 1)], unique=True, sparse=True)
    except Exception:
        pass  # Index may already exist or have conflicts with existing data

    # Start background reminder scheduler
    async def reminder_loop():
        while True:
            await asyncio.sleep(900)  # 15 minutes
            try:
                await run_reminder_jobs()
                logger.info("Reminder jobs completed")
            except Exception as e:
                logger.error(f"Reminder job error: {e}")
    asyncio.create_task(reminder_loop())

@app.on_event("shutdown")
async def shutdown():
    client.close()
