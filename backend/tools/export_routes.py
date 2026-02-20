#!/usr/bin/env python3
"""
Export all FastAPI routes to CSV inventory.

Usage:
    python tools/export_routes.py

Output:
    artifacts/endpoints_inventory.csv
"""
import csv
import inspect
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def get_auth_dependency(route):
    """Extract auth dependency names from route dependencies."""
    deps = []
    if hasattr(route, 'dependant') and route.dependant:
        for dep in getattr(route.dependant, 'dependencies', []):
            if hasattr(dep, 'dependency'):
                dep_name = getattr(dep.dependency, '__name__', str(dep.dependency))
                if 'current_user' in dep_name.lower() or 'admin' in dep_name.lower() or 'platform' in dep_name.lower():
                    deps.append(dep_name)
    return ', '.join(deps) if deps else ''


def get_endpoint_file(endpoint):
    """Get the source file path for an endpoint function."""
    try:
        source_file = inspect.getsourcefile(endpoint)
        if source_file:
            # Make path relative to backend
            return source_file.replace('/app/backend/', '')
        return 'UNKNOWN'
    except:
        return 'UNKNOWN'


def export_routes():
    """Export all routes from the FastAPI app."""
    # Import the app
    from server import app
    
    routes_data = []
    
    for route in app.routes:
        # Skip internal routes
        if hasattr(route, 'path'):
            path = route.path
            
            # Skip OpenAPI and docs routes
            if path in ['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc']:
                continue
            
            methods = getattr(route, 'methods', {'GET'})
            if methods:
                methods = sorted([m for m in methods if m not in ['HEAD', 'OPTIONS']])
            else:
                methods = ['GET']
            
            endpoint = getattr(route, 'endpoint', None)
            func_name = getattr(endpoint, '__name__', 'UNKNOWN') if endpoint else 'UNKNOWN'
            
            # Get source file
            file_path = get_endpoint_file(endpoint) if endpoint else 'UNKNOWN'
            
            # Get tags
            tags = getattr(route, 'tags', [])
            tags_str = ', '.join(tags) if tags else ''
            
            # Get auth dependency
            auth_dep = get_auth_dependency(route)
            
            # Get docstring for notes
            notes = ''
            if endpoint and endpoint.__doc__:
                first_line = endpoint.__doc__.strip().split('\n')[0][:100]
                notes = first_line.replace('"', "'")
            
            for method in methods:
                routes_data.append({
                    'method': method,
                    'path': path,
                    'function_name': func_name,
                    'file_path': file_path,
                    'tags': tags_str,
                    'auth_dependency': auth_dep,
                    'notes': notes
                })
    
    # Sort by path, then method
    routes_data.sort(key=lambda x: (x['path'], x['method']))
    
    # Write CSV
    output_path = Path(__file__).parent.parent / 'artifacts' / 'endpoints_inventory.csv'
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'method', 'path', 'function_name', 'file_path', 'tags', 'auth_dependency', 'notes'
        ])
        writer.writeheader()
        writer.writerows(routes_data)
    
    print(f"Exported {len(routes_data)} routes to {output_path}")
    return routes_data


if __name__ == '__main__':
    export_routes()
