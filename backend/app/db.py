"""
Database connection and configuration.
"""
from motor.motor_asyncio import AsyncIOMotorClient
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# Database connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'begwork')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

def get_db():
    """Get database instance (for dependency injection if needed)."""
    return db
