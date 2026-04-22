"""
Production Data Migration Script.
Copies BEG Full Access org data from source DB to production DB.
Preserves all org_id references and document relationships.

Usage: python migrate_to_production.py
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / '.env')

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
SOURCE_DB = 'test_database'
TARGET_DB = os.environ.get('DB_NAME', 'test_database')

# BEG Full Access org
SOURCE_ORG_ID = 'ec344711-7852-4009-a9b8-622e238c6aca'
ADMIN_EMAIL = 'admin@begfull.bg'

# Collections with org_id field
ORG_COLLECTIONS = [
    'users', 'organizations', 'projects', 'employee_profiles',
    'employee_daily_reports', 'invoices', 'offers', 'work_sessions',
    'attendance_entries', 'site_daily_rosters', 'work_reports',
    'clients', 'companies', 'persons', 'extra_works', 'extra_work_drafts',
    'missing_smr', 'activity_budgets', 'smr_analyses', 'smr_groups',
    'feature_flags', 'subscriptions', 'audit_logs',
    'financial_accounts', 'finance_payments', 'payment_allocations',
    'invoice_settings', 'offer_events', 'offer_versions',
    'project_team', 'project_phases', 'project_overhead_allocations',
    'payroll_payment_allocations', 'payroll_entries',
    'warehouse_transactions', 'material_requests',
    'location_nodes', 'media_files', 'site_pulses',
    'ai_calibration_events', 'ocr_invoice_intake',
    'contract_payments', 'subcontractor_payments',
    'worker_calendar', 'notifications', 'reminder_logs',
    'module_access',
]

# Global collections (no org_id filter, copy all)
GLOBAL_COLLECTIONS = [
    'org_counters', 'settings',
]


async def migrate():
    client = AsyncIOMotorClient(MONGO_URL)
    source = client[SOURCE_DB]
    target = client[TARGET_DB]

    # Safety check
    existing_user = await target.users.find_one({'email': ADMIN_EMAIL})
    if existing_user:
        print(f'[SKIP] {ADMIN_EMAIL} already exists in {TARGET_DB}. Migration not needed.')
        return

    print(f'=== Migration: {SOURCE_DB} -> {TARGET_DB} ===')
    print(f'Organization: {SOURCE_ORG_ID}')
    print()

    total_docs = 0

    # Copy org-scoped collections
    for coll_name in ORG_COLLECTIONS:
        try:
            src_coll = source[coll_name]
            tgt_coll = target[coll_name]

            # Special case: organizations uses 'id' not 'org_id' for its own record
            if coll_name == 'organizations':
                docs = await src_coll.find({'id': SOURCE_ORG_ID}).to_list(10)
            else:
                docs = await src_coll.find({'org_id': SOURCE_ORG_ID}).to_list(10000)

            if not docs:
                continue

            # Remove MongoDB _id to avoid conflicts
            for doc in docs:
                doc.pop('_id', None)

            # Check for existing docs to avoid duplicates
            sample_id = docs[0].get('id')
            if sample_id:
                existing = await tgt_coll.find_one({'id': sample_id})
                if existing:
                    print(f'  [SKIP] {coll_name}: {len(docs)} docs (already exist)')
                    continue

            await tgt_coll.insert_many(docs)
            total_docs += len(docs)
            print(f'  [OK] {coll_name}: {len(docs)} docs copied')
        except Exception as e:
            print(f'  [ERR] {coll_name}: {e}')

    # Copy global collections
    for coll_name in GLOBAL_COLLECTIONS:
        try:
            src_coll = source[coll_name]
            tgt_coll = target[coll_name]

            existing_count = await tgt_coll.count_documents({})
            if existing_count > 0:
                print(f'  [SKIP] {coll_name}: target already has {existing_count} docs')
                continue

            docs = await src_coll.find({}).to_list(100)
            if docs:
                for doc in docs:
                    doc.pop('_id', None)
                await tgt_coll.insert_many(docs)
                total_docs += len(docs)
                print(f'  [OK] {coll_name}: {len(docs)} docs copied (global)')
        except Exception as e:
            print(f'  [ERR] {coll_name}: {e}')

    print(f'\n=== Done: {total_docs} documents migrated ===')

    # Verify
    user = await target.users.find_one({'email': ADMIN_EMAIL}, {'_id': 0, 'id': 1, 'email': 1, 'role': 1, 'org_id': 1})
    if user:
        print(f'[VERIFY] User found: {user["email"]} | role={user["role"]} | org_id={user["org_id"]}')
    else:
        print('[VERIFY] WARNING: User not found after migration!')

    org = await target.organizations.find_one({'id': SOURCE_ORG_ID}, {'_id': 0, 'id': 1, 'name': 1})
    if org:
        print(f'[VERIFY] Org found: {org["name"]} | id={org["id"]}')

    projects = await target.projects.count_documents({'org_id': SOURCE_ORG_ID})
    print(f'[VERIFY] Projects: {projects}')


if __name__ == '__main__':
    asyncio.run(migrate())
