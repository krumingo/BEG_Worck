"""
Core configuration and constants.
This file extracts configuration from server.py for better organization.
"""
import os

# Roles
ROLES = ["Admin", "Owner", "SiteManager", "Technician", "Accountant", "Warehousekeeper", "Driver", "Viewer"]

# Modules
MODULES = {
    "M0": {"name": "Core / SaaS", "description": "Tenants, auth, roles, settings, audit, billing"},
    "M1": {"name": "Projects", "description": "Project management and tracking"},
    "M2": {"name": "Estimates / BOQ", "description": "Offers, activities, bill of quantities"},
    "M3": {"name": "Attendance & Reports", "description": "Daily attendance, work reports, reminders"},
    "M4": {"name": "HR / Payroll", "description": "Hourly/daily/monthly pay, advances, payslips"},
    "M5": {"name": "Finance", "description": "Invoices, payments, cash/bank management"},
    "M6": {"name": "AI Invoice Capture", "description": "Upload, parse, approval queue"},
    "M7": {"name": "Inventory", "description": "Items, stock movements, warehouses"},
    "M8": {"name": "Assets & QR", "description": "Checkout/checkin, maintenance, warranty"},
    "M9": {"name": "Admin Console / BI", "description": "Statistics, alerts, overhead costs"},
}

# Subscription Plans
SUBSCRIPTION_PLANS = {
    "free": {
        "name": "Free Trial",
        "price": 0,
        "stripe_price_id": None,
        "allowed_modules": ["M0", "M1", "M3"],
        "limits": {
            "users": 3,
            "projects": 2,
            "monthly_invoices": 5,
            "storage_mb": 100
        },
        "trial_days": 14,
        "description": "14-day trial with basic features",
    },
    "pro": {
        "name": "Professional",
        "price": 49.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_PRO"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M9"],
        "limits": {
            "users": 20,
            "projects": 50,
            "monthly_invoices": 500,
            "storage_mb": 2000
        },
        "trial_days": 0,
        "description": "Full access to all features",
    },
    "enterprise": {
        "name": "Enterprise",
        "price": 149.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_ENTERPRISE"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"],
        "limits": {
            "users": 100,
            "projects": 500,
            "monthly_invoices": 5000,
            "storage_mb": 20000
        },
        "trial_days": 0,
        "description": "Unlimited users and premium support",
        "support_priority": "priority",
        "custom_integrations": True,
    }
}

LIMIT_WARNING_THRESHOLD = 0.8
SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "canceled", "incomplete"]
