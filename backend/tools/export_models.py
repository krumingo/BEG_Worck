#!/usr/bin/env python3
"""
Export all Pydantic models and MongoDB collections to CSV inventory.

Usage:
    python tools/export_models.py

Output:
    artifacts/models_inventory.csv
"""
import ast
import csv
import os
import re
from pathlib import Path


def find_pydantic_models(file_path: str) -> list[dict]:
    """Parse a Python file and extract Pydantic BaseModel classes."""
    models = []
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if it inherits from BaseModel
                bases = [getattr(base, 'id', getattr(base, 'attr', '')) for base in node.bases]
                if any('BaseModel' in str(b) or 'Model' in str(b) for b in bases):
                    # Extract fields
                    fields = []
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            field_name = item.target.id
                            fields.append(field_name)
                    
                    # Check for special fields
                    field_names = [f.lower() for f in fields]
                    
                    models.append({
                        'model_name': node.name,
                        'collection_name': '',  # Will be inferred
                        'file_path': file_path.replace('/app/backend/', ''),
                        'required_fields': ', '.join(fields[:10]) + ('...' if len(fields) > 10 else ''),
                        'orgId_field': 'YES' if any('org' in f for f in field_names) else 'NO',
                        'createdAt_field': 'YES' if any('created' in f for f in field_names) else 'NO',
                        'updatedAt_field': 'YES' if any('updated' in f for f in field_names) else 'NO',
                        'createdBy_field': 'YES' if any('created_by' in f or 'owner' in f for f in field_names) else 'NO',
                        'indexes': 'UNKNOWN',
                        'notes': 'Pydantic model'
                    })
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
    
    return models


def find_mongo_collections(file_path: str) -> list[dict]:
    """Find MongoDB collection references in a file."""
    collections = []
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Find db.<collection> patterns
        pattern = r'db\.([a-z_]+)\.'
        matches = re.findall(pattern, content)
        
        for coll_name in set(matches):
            if coll_name not in ['users', 'organizations']:  # Skip common ones we'll add separately
                collections.append({
                    'model_name': coll_name.title().replace('_', ''),
                    'collection_name': coll_name,
                    'file_path': file_path.replace('/app/backend/', ''),
                    'required_fields': 'UNKNOWN',
                    'orgId_field': 'UNKNOWN',
                    'createdAt_field': 'UNKNOWN',
                    'updatedAt_field': 'UNKNOWN',
                    'createdBy_field': 'UNKNOWN',
                    'indexes': 'UNKNOWN',
                    'notes': 'MongoDB collection reference'
                })
    except Exception as e:
        print(f"Error scanning {file_path}: {e}")
    
    return collections


def export_models():
    """Export all models and collections."""
    backend_path = Path('/app/backend')
    models_data = []
    collections_found = set()
    
    # Scan Python files
    for py_file in backend_path.rglob('*.py'):
        if 'tools' in str(py_file) or '__pycache__' in str(py_file):
            continue
        
        # Get Pydantic models
        models = find_pydantic_models(str(py_file))
        models_data.extend(models)
        
        # Get MongoDB collections
        collections = find_mongo_collections(str(py_file))
        for coll in collections:
            if coll['collection_name'] not in collections_found:
                collections_found.add(coll['collection_name'])
                models_data.append(coll)
    
    # Add known core collections
    core_collections = [
        {
            'model_name': 'User',
            'collection_name': 'users',
            'file_path': 'app/routes/auth.py, server.py',
            'required_fields': 'id, email, password_hash, role, org_id, is_active, is_platform_admin',
            'orgId_field': 'YES',
            'createdAt_field': 'YES',
            'updatedAt_field': 'YES',
            'createdBy_field': 'NO',
            'indexes': 'email (unique)',
            'notes': 'Core user collection'
        },
        {
            'model_name': 'Organization',
            'collection_name': 'organizations',
            'file_path': 'server.py, app/routes/billing.py',
            'required_fields': 'id, name, slug, subscription_plan, subscription_status',
            'orgId_field': 'N/A (is org)',
            'createdAt_field': 'YES',
            'updatedAt_field': 'YES',
            'createdBy_field': 'NO',
            'indexes': 'slug (unique)',
            'notes': 'Core organization collection'
        },
        {
            'model_name': 'AuditLog',
            'collection_name': 'audit_logs',
            'file_path': 'app/services/audit.py',
            'required_fields': 'id, org_id, user_id, user_email, action, entity_type, entity_id, timestamp',
            'orgId_field': 'YES',
            'createdAt_field': 'YES (timestamp)',
            'updatedAt_field': 'NO',
            'createdBy_field': 'YES (user_id)',
            'indexes': 'org_id, timestamp',
            'notes': 'Audit trail collection'
        },
    ]
    
    # Remove duplicates and add core
    existing_collections = {m['collection_name'] for m in models_data if m['collection_name']}
    for core in core_collections:
        if core['collection_name'] not in existing_collections:
            models_data.append(core)
    
    # Sort by collection_name, then model_name
    models_data.sort(key=lambda x: (x['collection_name'] or 'zzz', x['model_name']))
    
    # Write CSV
    output_path = backend_path / 'artifacts' / 'models_inventory.csv'
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'model_name', 'collection_name', 'file_path', 'required_fields',
            'orgId_field', 'createdAt_field', 'updatedAt_field', 'createdBy_field',
            'indexes', 'notes'
        ])
        writer.writeheader()
        writer.writerows(models_data)
    
    print(f"Exported {len(models_data)} models/collections to {output_path}")
    return models_data


if __name__ == '__main__':
    export_models()
