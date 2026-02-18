"""
Database connection and collection access.
"""
from motor.motor_asyncio import AsyncIOMotorClient
import os

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Collection accessors for type hints and easy refactoring
users = db.users
organizations = db.organizations
subscriptions = db.subscriptions
feature_flags = db.feature_flags
audit_logs = db.audit_logs
projects = db.projects
project_team = db.project_team
project_phases = db.project_phases
offers = db.offers
activity_catalog = db.activity_catalog
attendance_entries = db.attendance_entries
work_reports = db.work_reports
notifications = db.notifications
reminder_logs = db.reminder_logs
employee_profiles = db.employee_profiles
advances = db.advances
payroll_runs = db.payroll_runs
payslips = db.payslips
payroll_payments = db.payroll_payments
financial_accounts = db.financial_accounts
invoices = db.invoices
finance_payments = db.finance_payments
payment_allocations = db.payment_allocations
overhead_categories = db.overhead_categories
overhead_costs = db.overhead_costs
overhead_assets = db.overhead_assets
overhead_snapshots = db.overhead_snapshots
project_overhead_allocations = db.project_overhead_allocations
org_mobile_settings = db.org_mobile_settings
mobile_view_configs = db.mobile_view_configs
media_files = db.media_files
