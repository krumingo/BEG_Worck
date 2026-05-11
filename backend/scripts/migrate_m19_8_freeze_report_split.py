#!/usr/bin/env python3
"""
M19.8 Migration: Freeze regular_hours / overtime_hours on already-APPROVED reports.

Logic:
  1. Find all employee_daily_reports with approval_status="APPROVED"
     that do NOT have regular_hours set.
  2. For each, look up the matching work_session (approved_report_id == report.id).
  3. If found: copy regular_hours, overtime_hours, overtime_coefficient,
     overtime_reason, labor_cost from the session.
  4. If not found: fallback to min(hours, 8) / max(0, hours-8), coefficient=1.0.
  5. Mark with migration_m19_8_at timestamp.

Idempotent: skips reports that already have regular_hours.
Dry-run by default. Pass --apply to write.

Usage:
  python scripts/migrate_m19_8_freeze_report_split.py          # dry-run
  python scripts/migrate_m19_8_freeze_report_split.py --apply  # write to DB
"""
import sys
import os
from datetime import datetime, timezone

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "begwork")

def main():
    apply = "--apply" in sys.argv
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== M19.8 Migration: Freeze report split ({mode}) ===\n")

    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]

    # Find APPROVED reports without frozen regular_hours
    query = {
        "regular_hours": {"$exists": False},
        "$or": [
            {"approval_status": "APPROVED"},
            {"status": "APPROVED"},
        ],
    }

    reports = list(db.employee_daily_reports.find(query, {"_id": 0}))
    print(f"Found {len(reports)} APPROVED reports without frozen split.\n")

    updated = 0
    from_session = 0
    from_fallback = 0

    for r in reports:
        rid = r.get("id", "")
        hours = float(r.get("hours", 0) or 0)
        worker = r.get("worker_name") or r.get("worker_id", "?")

        # Try to find matching work_session
        session = db.work_sessions.find_one(
            {"approved_report_id": rid},
            {"_id": 0, "regular_hours": 1, "overtime_hours": 1,
             "overtime_coefficient": 1, "overtime_reason": 1, "labor_cost": 1},
        )

        if session and session.get("regular_hours") is not None:
            reg = float(session["regular_hours"])
            ot = float(session.get("overtime_hours", 0))
            coef = session.get("overtime_coefficient")
            reason = session.get("overtime_reason")
            labor = session.get("labor_cost")
            source = "session"
            from_session += 1
        else:
            reg = min(hours, 8)
            ot = max(0, hours - 8)
            coef = 1.0 if ot > 0 else None
            reason = None
            labor = None
            source = "fallback"
            from_fallback += 1

        update_fields = {
            "regular_hours": round(reg, 2),
            "overtime_hours": round(ot, 2),
            "migration_m19_8_at": datetime.now(timezone.utc).isoformat(),
        }
        if coef is not None:
            update_fields["overtime_coefficient"] = coef
        if reason:
            update_fields["overtime_reason"] = reason
        if labor is not None:
            update_fields["labor_cost"] = labor

        print(f"  [{source}] {rid[:8]}... {worker}: {hours}h -> reg={reg:.1f} ot={ot:.1f}" +
              (f" coef={coef}" if coef else ""))

        if apply:
            db.employee_daily_reports.update_one(
                {"id": rid},
                {"$set": update_fields},
            )
        updated += 1

    print(f"\n{'Updated' if apply else 'Would update'}: {updated}")
    print(f"  From work_sessions: {from_session}")
    print(f"  From fallback (min/max 8): {from_fallback}")

    if not apply and updated > 0:
        print(f"\nRe-run with --apply to write changes.")

    client.close()


if __name__ == "__main__":
    main()
