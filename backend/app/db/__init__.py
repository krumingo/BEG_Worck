"""
Database connection and collection access.
"""
from motor.motor_asyncio import AsyncIOMotorClient
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment from backend/.env
_root = Path(__file__).parent.parent
load_dotenv(_root / '.env')

mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'begwork')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# W0-03E-A2C — no pre-bound collection handles.
#
# This module used to bind every legacy collection to a module-level name
# (``users = db.users``, ``invoices = db.invoices``, ...). Nothing imported them
# (verified over ``app/``, ``server.py``, ``scripts/`` and ``tests/``), and each
# one was a ready-made bypass of the tenant predicate: ``from app.db import
# invoices`` hands a caller a raw handle with no tenant in sight, which is
# exactly the defect W0-03E-A1 removed from the protected surface and W0-03E-A2
# removed for ``project_team``.
#
# Tenant-owned collections are reached ONLY through
# ``app.tenancy.data_access.TenantData`` (rule A1-IDENTITY / A2C-READ of
# ``scripts/w0_03e_a2c_tenant_boundary_guard.py``); ``db`` itself stays exported
# for the tenancy layer, the migration/bootstrap scripts and the W0-03/W0-04
# stores that carry their own ``tenant_id`` contract.
__all__ = ["client", "db", "mongo_url", "db_name"]
