"""
Routes package - API endpoint routers.

Note: Routes are currently in server.py (monolith).
This package provides the structure for gradual migration.

Future structure:
- auth.py: /api/auth/* 
- org.py: /api/organization
- users.py: /api/users/*
- projects.py: /api/projects/*
- offers.py: /api/offers/*, /api/activity-catalog/*
- attendance.py: /api/attendance/*
- work_reports.py: /api/work-reports/*
- hr.py: /api/employees/*, /api/advances/*, /api/payroll-runs/*, /api/payslips/*
- finance.py: /api/finance/*
- overhead.py: /api/overhead/*
- billing.py: /api/billing/*
- mobile.py: /api/mobile/*
- media.py: /api/media/*
- notifications.py: /api/notifications/*, /api/reminders/*
"""
