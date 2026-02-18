"""
BEG_Work Backend Application - Main Entry Point

This is a transitional main.py that imports the existing server.py
to maintain API compatibility while enabling modular refactoring.

The original server.py contains all routes and is gradually being
refactored into the app/ package structure.
"""
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

# Import the existing app and router from server.py for backwards compatibility
# This ensures all existing endpoints continue to work
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from server import app, api_router, db, ROLES, MODULES

# Re-export for compatibility
__all__ = ['app', 'api_router', 'db', 'ROLES', 'MODULES']

# The app is already configured in server.py, so we just re-export it
# In future iterations, routes will be moved to app/routes/ and registered here
