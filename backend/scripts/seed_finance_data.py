"""
Seed script for financial data (DEV only).
Creates sample data for cash_transactions, overhead_transactions, bonus_payments
for testing the finance dashboard charts.
"""
import asyncio
import random
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import os
import uuid

# MongoDB connection
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


async def seed_finance_data():
    """Seed financial transaction data for 2024, 2025, 2026"""
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    
    # Get organization ID (use first org found)
    org = await db.organizations.find_one({})
    if not org:
        print("ERROR: No organization found. Please create an organization first.")
        return
    
    org_id = org["id"]
    print(f"Seeding finance data for org: {org.get('name', org_id)}")
    
    # Get a user ID for created_by field
    user = await db.users.find_one({"org_id": org_id})
    user_id = user["id"] if user else "system"
    
    # Categories for transactions
    cash_income_categories = ["Продажби", "Услуги", "Консултации", "Наем"]
    cash_expense_categories = ["Доставки", "Транспорт", "Дребни разходи", "Офис консумативи"]
    overhead_categories = ["Наем офис", "Електричество", "Вода", "Интернет", "Телефон", "Застраховки"]
    
    # Time period: 2024-01 to 2026-12
    years = [2024, 2025, 2026]
    
    # Clear existing data
    print("Clearing existing finance test data...")
    await db.cash_transactions.delete_many({"org_id": org_id, "description": {"$regex": "^SEED:"}})
    await db.overhead_transactions.delete_many({"org_id": org_id, "description": {"$regex": "^SEED:"}})
    await db.bonus_payments.delete_many({"org_id": org_id, "description": {"$regex": "^SEED:"}})
    
    cash_count = 0
    overhead_count = 0
    bonus_count = 0
    
    for year in years:
        for month in range(1, 13):
            # Skip future months in 2026
            if year == 2026 and month > 3:
                continue
                
            # Generate 4-8 cash transactions per month (mix of income/expense)
            num_cash = random.randint(4, 8)
            for _ in range(num_cash):
                day = random.randint(1, 28)
                is_income = random.random() > 0.4  # 60% income, 40% expense
                
                txn = {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "type": "income" if is_income else "expense",
                    "amount": round(random.uniform(100, 5000) if is_income else random.uniform(50, 2000), 2),
                    "category": random.choice(cash_income_categories if is_income else cash_expense_categories),
                    "description": f"SEED: {'Приход' if is_income else 'Разход'} {year}/{month:02d}",
                    "created_by": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.cash_transactions.insert_one(txn)
                cash_count += 1
            
            # Generate 2-4 overhead transactions per month
            num_overhead = random.randint(2, 4)
            for _ in range(num_overhead):
                day = random.randint(1, 15)  # Overhead usually in first half of month
                
                txn = {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "amount": round(random.uniform(200, 3000), 2),
                    "category": random.choice(overhead_categories),
                    "description": f"SEED: Режийни {year}/{month:02d}",
                    "created_by": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.overhead_transactions.insert_one(txn)
                overhead_count += 1
            
            # Generate 0-2 bonus payments per month
            num_bonus = random.randint(0, 2)
            for _ in range(num_bonus):
                day = random.randint(20, 28)  # Bonuses usually end of month
                
                payment = {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "amount": round(random.uniform(500, 3000), 2),
                    "user_id": user_id,
                    "description": f"SEED: Бонус {year}/{month:02d}",
                    "created_by": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.bonus_payments.insert_one(payment)
                bonus_count += 1
    
    print(f"✓ Created {cash_count} cash transactions")
    print(f"✓ Created {overhead_count} overhead transactions")
    print(f"✓ Created {bonus_count} bonus payments")
    print("\nSeed complete! Finance dashboard should now show data for 2024-2026.")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(seed_finance_data())
