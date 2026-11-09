"""
OFF-01 OFF79-05 — the collections an offer transaction writes, created OUTSIDE it.

Same class as ACT77-01 (``app/services/client_acts.py`` on the ACT-01 branch): MongoDB
creates a missing collection implicitly inside a transaction, and concurrent first writes
on a fresh tenant then fail with "namespace … is already in use". Called at startup
(``server.py``), at onboarding (``app.tenancy.onboarding``) and before every offer
transaction (``app.routes.offers._in_transaction``). Database API only — no document is
read or written here.
"""

#: Every collection an offer transaction writes (OFF79-05).
#: MongoDB creates a missing collection implicitly INSIDE a transaction, and concurrent
#: first writes on a fresh tenant then fail with "namespace … is already in use". So they
#: are created outside it — at startup, at onboarding, and before every transaction.
OFFER_TXN_COLLECTIONS = ("offers", "offer_events", "offer_versions", "audit_logs", "audit_events")
MAX_TXN_ATTEMPTS = 5


async def ensure_offer_collections(database) -> None:
    """Create the missing offer-transaction collections outside any transaction (with the
    ``audit_logs`` index the startup creates). Idempotent; one ``listCollections`` round
    trip when they all exist. The audit chain index is ensured by ``run_in_transaction``."""
    from pymongo.errors import CollectionInvalid, OperationFailure
    present = set(await database.list_collection_names())    # no filter: mongomock too
    missing = [name for name in OFFER_TXN_COLLECTIONS if name not in present]
    for name in missing:
        try:
            await database.create_collection(name)
        except CollectionInvalid:
            pass                                    # created concurrently — fine
        except OperationFailure as exc:
            if exc.code != 48:                      # NamespaceExists
                raise
    if "audit_logs" in missing:
        await database.audit_logs.create_index([("org_id", 1), ("timestamp", -1)])
