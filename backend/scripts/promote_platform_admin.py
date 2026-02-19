#!/usr/bin/env python3
"""
Platform Admin Promotion Script

Usage:
    python promote_platform_admin.py <email>
    
Example:
    python promote_platform_admin.py Krumingo@gmail.com
    
This script promotes a user to platform admin status, granting them
access to system management routes:
- /api/billing/*
- /api/mobile-settings/*
- /api/modules/* (PUT)
- /api/audit-logs

SECURITY: Run this script directly on the server with database access.
Do not expose as an API endpoint.
"""
import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def promote_platform_admin(target_email: str):
    mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name = os.environ.get('DB_NAME', 'begwork')
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    print(f"Connecting to {db_name}...")
    
    # Find user
    user = await db.users.find_one({'email': target_email})
    if not user:
        print(f"ERROR: User '{target_email}' not found in database.")
        # Show similar emails
        users = await db.users.find({}, {'_id': 0, 'email': 1}).to_list(100)
        emails = [u['email'] for u in users]
        similar = [e for e in emails if target_email.lower() in e.lower()]
        if similar:
            print(f"Did you mean one of: {similar}")
        client.close()
        return False
    
    # Check if already platform admin
    if user.get('is_platform_admin', False):
        print(f"INFO: {target_email} is already a platform admin.")
        client.close()
        return True
    
    # Promote to platform admin
    now = datetime.now(timezone.utc).isoformat()
    result = await db.users.update_one(
        {'email': target_email},
        {'$set': {
            'is_platform_admin': True,
            'updated_at': now
        }}
    )
    
    if result.modified_count == 0:
        print(f"ERROR: Failed to update user.")
        client.close()
        return False
    
    # Create audit log
    await db.audit_logs.insert_one({
        'id': str(uuid.uuid4()),
        'org_id': user.get('org_id'),
        'user_id': 'system',
        'user_email': 'system',
        'action': 'platform_admin_promoted',
        'entity_type': 'user',
        'entity_id': user.get('id'),
        'changes': {
            'email': target_email,
            'is_platform_admin': True,
            'promoted_by': 'promote_platform_admin.py'
        },
        'timestamp': now
    })
    
    # Verify
    updated = await db.users.find_one(
        {'email': target_email}, 
        {'_id': 0, 'email': 1, 'role': 1, 'is_platform_admin': 1}
    )
    
    print("=" * 60)
    print("SUCCESS: Platform Admin Promotion Complete")
    print("=" * 60)
    print(f"  Email: {updated['email']}")
    print(f"  Role: {updated['role']}")
    print(f"  is_platform_admin: {updated['is_platform_admin']}")
    print("=" * 60)
    print("User now has access to:")
    print("  - /billing (Billing configuration)")
    print("  - /mobile-settings (Mobile app configuration)")
    print("  - /modules (Module toggles)")
    print("  - /audit-log (Audit logs)")
    print("=" * 60)
    
    client.close()
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python promote_platform_admin.py <email>")
        print("Example: python promote_platform_admin.py Krumingo@gmail.com")
        sys.exit(1)
    
    email = sys.argv[1]
    success = asyncio.run(promote_platform_admin(email))
    sys.exit(0 if success else 1)
