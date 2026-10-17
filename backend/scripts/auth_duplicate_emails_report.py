#!/usr/bin/env python3
"""
AUTH-01 C01 (F-03) — READ-ONLY report of login emails that collide up to letter case.

The login identity rule is "one email = one login across the installation"
(compared ``strip().lower()``). New users can no longer be created against it,
but rows that already collide — in one organization or across organizations —
stay refused at login, forgot-password and recovery (fail closed) until a
person resolves them by hand, e.g. by changing one of the addresses in the
Users screen. This script only SHOWS them; it never writes.

    python scripts/auth_duplicate_emails_report.py

Output: one block per colliding email with each row's id, org_id, active flag
and stored spelling. Exit 0 = no collisions · 1 = collisions found ·
2 = the database could not be read.
"""
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXIT_CLEAN, EXIT_COLLISIONS, EXIT_ERROR = 0, 1, 2


async def report(db, out=print) -> int:
    """Group every user by normalized email; print and count the colliding groups."""
    groups = defaultdict(list)
    cursor = db.users.find({}, {"_id": 0, "id": 1, "org_id": 1, "email": 1, "is_active": 1})
    async for doc in cursor:
        email = doc.get("email")
        if isinstance(email, str) and email.strip():
            groups[email.strip().lower()].append(doc)
    collisions = {k: v for k, v in groups.items() if len(v) > 1}
    if not collisions:
        out("OK: no two users share an email up to letter case.")
        return EXIT_CLEAN
    out(f"FOUND {len(collisions)} email(s) shared by more than one user "
        "(login / forgot-password / recovery refuse these until fixed by hand):")
    for normalized in sorted(collisions):
        rows = collisions[normalized]
        orgs = {r.get("org_id") for r in rows}
        scope = "across organizations" if len(orgs) > 1 else "inside one organization"
        out(f"\n  {normalized!r} — {len(rows)} users, {scope}:")
        for r in sorted(rows, key=lambda d: (str(d.get("org_id")), str(d.get("id")))):
            out(f"    - id={r.get('id')} org_id={r.get('org_id')} "
                f"active={r.get('is_active', True)} stored={r.get('email')!r}")
    return EXIT_COLLISIONS


def main() -> int:
    from app.db import client, db, db_name
    print(f"Database: {db_name} (read-only)")
    try:
        return asyncio.run(report(db))
    except Exception as exc:
        print(f"ERROR: could not read users ({type(exc).__name__})")
        return EXIT_ERROR
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
