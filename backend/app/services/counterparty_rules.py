"""
CP-01 — counterparty rules (pure logic, no database access).

Package: docs/architecture/tasks/CP-01_COUNTERPARTY_IBAN_EGN_NO_DELETE.md. Decision R48
(Krum, 08.11.2026). Canon: FLOW-010 §3.1, §3.3, §8, §12; FLOW-006; FLOW-025 L146/L187;
FLOW-032 L46/L105/L109-112; FLOW-040 §9/§11; CLAUDE.md §2, §8, §14.

* who may write counterparties / clients / companies / persons (R48.5);
* who may deactivate / archive one (R48.4);
* who verifies an IBAN and approves an IBAN change (R48.1, R48.2);
* who sees a full ЕГН (R48.3) and the mask every other reader gets;
* IBAN normalisation, the ISO 13616 mod-97 check and the IBAN mask (logs/AuditEvent).
"""
import re
from typing import Any, Dict, Optional

# ── roles ─────────────────────────────────────────────────────────────────────
#: R48.5 — create / edit counterparties, clients, companies, persons (and R22: the client
#: of a project). Every other role is refused (403); a proposal flow is debt CP-01-D2.
MASTER_WRITE_ROLES = frozenset({"Owner", "Admin", "Accountant"})
#: R48.4 — "неактивен" is set and undone by Accountant / Admin (and Owner).
DEACTIVATE_ROLES = frozenset({"Owner", "Admin", "Accountant"})
#: R48.4 — "архивиран" only by Admin / Owner.
ARCHIVE_ROLES = frozenset({"Owner", "Admin"})
#: Registering a new IBAN (status "за проверка") is a master-data write (R48.5).
BANK_ACCOUNT_ENTRY_ROLES = MASTER_WRITE_ROLES
#: R48.1 — an IBAN is verified by an Accountant or the Owner who did NOT enter it;
#: R48.2 / FLOW-025 L146 — the double approval of a change is by two of them.
BANK_ACCOUNT_VERIFY_ROLES = frozenset({"Owner", "Accountant"})
#: R48.3 — the full ЕГН is shown only to the Owner and the Accountant, and only by reveal.
EGN_REVEAL_ROLES = frozenset({"Owner", "Accountant"})


def role_of(user: Dict[str, Any]) -> str:
    return (user or {}).get("role") or ""


def can_write_master(user) -> bool:
    return role_of(user) in MASTER_WRITE_ROLES


def can_deactivate(user) -> bool:
    return role_of(user) in DEACTIVATE_ROLES


def can_archive(user) -> bool:
    return role_of(user) in ARCHIVE_ROLES


def can_verify_bank_account(user) -> bool:
    return role_of(user) in BANK_ACCOUNT_VERIFY_ROLES


def can_reveal_egn(user) -> bool:
    return role_of(user) in EGN_REVEAL_ROLES


# ── lifecycle (R48.4, FLOW-010 L53) ──────────────────────────────────────────
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_INACTIVE = "inactive"      # „неактивен“ — not selectable, Accountant/Admin may undo
LIFECYCLE_ARCHIVED = "archived"      # „архивиран“ — hidden, read-only, Admin/Owner
LIFECYCLE_LABELS = {LIFECYCLE_ACTIVE: "активен", LIFECYCLE_INACTIVE: "неактивен",
                    LIFECYCLE_ARCHIVED: "архивиран"}

#: legacy collection → its legacy active flag (kept in sync with ``lifecycle_status``)
ACTIVE_FLAG = {"counterparties": "active", "clients": "is_active", "companies": "is_active",
               "persons": "is_active", "subcontractors": "active"}


def lifecycle_of(doc: Optional[Dict[str, Any]], collection: str) -> str:
    """The record's lifecycle; records written before CP-01 derive it from the legacy flag."""
    if not doc:
        return LIFECYCLE_ACTIVE
    status = doc.get("lifecycle_status")
    if status in LIFECYCLE_LABELS:
        return status
    if doc.get("archived") is True:
        return LIFECYCLE_ARCHIVED
    flag = ACTIVE_FLAG.get(collection)
    if flag and doc.get(flag) is False:
        return LIFECYCLE_INACTIVE
    return LIFECYCLE_ACTIVE


def is_selectable(doc: Optional[Dict[str, Any]], collection: str) -> bool:
    """A new document (offer, contract, invoice, payment, delivery, project client) may name it."""
    return lifecycle_of(doc, collection) == LIFECYCLE_ACTIVE


# ── ЕГН (R48.3) ──────────────────────────────────────────────────────────────
EGN_MASK_PREFIX = "******"


def mask_egn(egn: Any) -> str:
    """``******1234`` — the last 4 digits only, for every reader (lists, detail, search,
    export, AuditEvent, logs). An empty value stays empty."""
    if egn is None:
        return ""
    digits = re.sub(r"\D", "", str(egn))
    if not digits:
        return ""
    return EGN_MASK_PREFIX + digits[-4:]


def mask_person(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A copy of a person record with the ЕГН masked (``egn_masked`` marks it)."""
    if not doc or not isinstance(doc, dict):
        return doc
    out = dict(doc)
    if out.get("egn"):
        out["egn"] = mask_egn(out["egn"])
        out["egn_masked"] = True
    return out


# ── EIK ──────────────────────────────────────────────────────────────────────
def normalize_eik(eik: Any) -> str:
    if eik is None:
        return ""
    return re.sub(r"\D", "", str(eik))


# ── IBAN (ISO 13616) ─────────────────────────────────────────────────────────
IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")


def normalize_iban(iban: Any) -> str:
    if not isinstance(iban, str):
        return ""
    return re.sub(r"[\s\-]", "", iban).upper()


def iban_is_valid(iban: Any) -> bool:
    """Shape + mod-97 == 1. BG IBANs are 22 characters (checked when the country is BG)."""
    value = normalize_iban(iban)
    if not IBAN_RE.match(value):
        return False
    if value.startswith("BG") and len(value) != 22:
        return False
    rearranged = value[4:] + value[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def mask_iban(iban: Any) -> str:
    """``BG**…**1234``: country + last 4. Used in AuditEvent, logs and DQ rows."""
    value = normalize_iban(iban)
    if len(value) < 8:
        return "****"
    return value[:2] + "*" * (len(value) - 6) + value[-4:]


# ── VerifiedBankAccount (FLOW-010 §3.3; package statuses) ────────────────────
BA_PENDING = "pending_verification"     # „за проверка“
BA_VERIFIED = "verified"                # „проверена“
BA_REPLACED = "replaced"                # „заменена“
BA_REJECTED = "rejected"                # „отказана“
BA_LABELS = {BA_PENDING: "за проверка", BA_VERIFIED: "проверена", BA_REPLACED: "заменена",
             BA_REJECTED: "отказана"}

#: FLOW-010 §8.2 / L274 — a source whose origin is the (possibly forged) invoice itself.
SOURCE_ORIGIN_INVOICE = "invoice"
SOURCE_KINDS = frozenset({"invoice", "contract", "bank_certificate", "phone_known",
                          "email_known", "company_profile", "bank_document", "other"})
SOURCE_ORIGINS = frozenset({"invoice", "contract", "bank", "known_contact", "company_profile",
                            "in_person", "other"})


def check_sources(sources: Any) -> Optional[str]:
    """Two independent sources (FLOW-010 §8.2). Returns an error code or None.

    * fewer than two, or a source without kind/description → TWO_SOURCES_REQUIRED;
    * the same kind twice → SOURCES_NOT_INDEPENDENT;
    * both taken from the invoice (L274: phone/email only from the suspicious invoice) →
      SOURCES_NOT_INDEPENDENT."""
    if not isinstance(sources, list) or len(sources) < 2:
        return "TWO_SOURCES_REQUIRED"
    kinds, origins = [], []
    for s in sources:
        if not isinstance(s, dict):
            return "TWO_SOURCES_REQUIRED"
        kind = s.get("kind")
        desc = s.get("description")
        origin = s.get("source_origin")
        if kind not in SOURCE_KINDS or not isinstance(desc, str) or not desc.strip() \
                or origin not in SOURCE_ORIGINS:
            return "TWO_SOURCES_REQUIRED"
        kinds.append(kind)
        origins.append(origin)
    if len(set(kinds)) < 2:
        return "SOURCES_NOT_INDEPENDENT"
    if all(o == SOURCE_ORIGIN_INVOICE for o in origins):
        return "SOURCES_NOT_INDEPENDENT"
    return None


def public_bank_account(doc: Dict[str, Any], user) -> Dict[str, Any]:
    """The API view of a bank account. The full IBAN only for the roles that verify it
    (Owner / Accountant); everyone else gets the mask (FLOW-040 §9; debt CP-01-D5)."""
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["status_label"] = BA_LABELS.get(out.get("status"), out.get("status"))
    out["iban_masked"] = mask_iban(doc.get("iban"))
    if not can_verify_bank_account(user):
        out["iban"] = out["iban_masked"]
    return out


# ── payment guard mode (legacy payments that name no account) ───────────────
ENV_BANK_GUARD_MODE = "BANK_ACCOUNT_GUARD_MODE"
GUARD_OFF, GUARD_SHADOW, GUARD_ENFORCE = "off", "shadow", "enforce"


def bank_guard_mode() -> str:
    """off = log only · shadow = DQ row + metric · enforce = 409. Default shadow (debt CP-01-D1)."""
    import os
    value = (os.environ.get(ENV_BANK_GUARD_MODE) or GUARD_SHADOW).strip().lower()
    return value if value in (GUARD_OFF, GUARD_SHADOW, GUARD_ENFORCE) else GUARD_SHADOW


def is_cash_method(method: Any) -> bool:
    return str(method or "").strip().lower() in ("cash", "в брой", "вброй", "каса")
