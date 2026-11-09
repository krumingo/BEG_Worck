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


#: CP83-03: the ``invoice_details`` fields that may hold a person's ЕГН. Only for a PERSON
#: owner (``eik`` / ``tax_id`` there are the ЕГН) or the explicit ``egn`` field — never a
#: company's tax id because it happens to have 10 digits (e.g. a foreign VAT number).
EGN_COPY_FIELDS = ("eik", "egn", "tax_id")


def _is_confirmed_company(owner_type: Any, owner_id: Any, company_confirmed: bool) -> bool:
    """FG-267 (pass 28): a company only when the caller confirmed that ``owner_id`` is an
    existing company record of this tenant (``company_confirmed``) — ``owner_type`` alone, an
    unknown id or a person never counts."""
    return owner_type == "company" and bool(owner_id) and company_confirmed is True


def possible_egn(value: Any) -> bool:
    """FG-267 (FLOW-040 §9, privacy-safe): exactly 10 digits — the shape of an ЕГН (an ЕИК
    has 9 or 13). Without a confirmed company owner it is treated as a possible ЕГН."""
    return len(re.sub(r"\D", "", str(value or ""))) == 10


def egn_copy_fields(details: Any, owner_type: Any, owner_id: Any = None, *,
                    include_possible: bool = True, company_confirmed: bool = False) -> list:
    """The fields of ``details`` that hold an unmasked (possible) ЕГН copy:
    * a person owner: ``eik`` / ``egn`` / ``tax_id``;
    * any owner: the explicit ``egn`` field;
    * FG-267: no confirmed company owner (none, unknown, or a person) and a 10-digit value in
      ``eik`` / ``tax_id`` → a possible ЕГН (``include_possible``);
    * a confirmed company owner's 10-digit tax id (e.g. a foreign VAT number) is not one."""
    if not isinstance(details, dict):
        return []
    out = []
    for field in EGN_COPY_FIELDS:
        value = details.get(field)
        if not value or str(value).startswith(EGN_MASK_PREFIX):
            continue
        if field == "egn" or owner_type == "person":
            out.append(field)
        elif include_possible and not _is_confirmed_company(owner_type, owner_id,
                                                            company_confirmed) \
                and possible_egn(value):
            out.append(field)
    return out


def mask_invoice_details(details: Any, owner_type: Any, fields=None, owner_id: Any = None, *,
                         include_possible: bool = True, company_confirmed: bool = False) -> Any:
    """``details`` with the ЕГН copy fields masked (all of them, or ``fields``)."""
    if not isinstance(details, dict):
        return details
    out = dict(details)
    if fields is None:
        fields = egn_copy_fields(details, owner_type, owner_id, include_possible=include_possible,
                                 company_confirmed=company_confirmed)
    for field in fields:
        out[field] = mask_egn(out[field])
    return out


def mask_for_log(value: Any) -> Any:
    """FG-266: what a log row / audit detail may hold — every IBAN as ``****1234`` and every
    ЕГН or possible ЕГН (``egn`` / ``eik`` / ``tax_id`` with 10 digits, recursively) masked,
    for every role (a log is read by people who may not see the value)."""
    if isinstance(value, list):
        return [mask_for_log(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in IBAN_KEYS and isinstance(v, str) and v and not v.startswith("****"):
                out[k] = mask_iban(v)
            elif k in EGN_COPY_FIELDS and isinstance(v, (str, int)) and v \
                    and not str(v).startswith(EGN_MASK_PREFIX) and (k == "egn" or possible_egn(v)):
                out[k] = mask_egn(v)
            elif k in VAT_KEYS and vat_is_egn(v):        # FG-429
                out[k] = mask_vat(v)
            else:
                out[k] = mask_for_log(v)
        return out
    return value


#: FG-294: the invoice fields that may hold a person's ЕГН (an invoice to a natural person)
INVOICE_EGN_KEYS = ("counterparty_eik", "egn")
#: FG-429 (R71): VAT number fields — a natural person's Bulgarian VAT number is BG + ЕГН
VAT_KEYS = ("counterparty_vat_no", "vat_number", "vat_no")


def vat_is_egn(value: Any) -> bool:
    """FG-429: ``BG`` + 10 digits — a natural person's VAT number, i.e. an ЕГН (a company's
    is BG + its 9 / 13-digit ЕИК). An already masked value is not one."""
    if not isinstance(value, str):
        return False
    v = re.sub(r"[\s.-]", "", value).upper()
    return v.startswith("BG") and v[2:].isdigit() and len(v) == 12


def mask_vat(value: Any) -> str:
    """``BG******1234``."""
    return "BG" + mask_egn(str(value)[2:])


def mask_invoice_egn(value: Any) -> Any:
    """FG-294 (R48.3): an invoice (or a list of them, or a version snapshot — recursively)
    with every possible ЕГН masked — a 10-digit ``counterparty_eik`` (a Bulgarian ЕИК has 9 or
    13 digits) or an ``egn`` field — for EVERY role. The full value only via the audited
    invoice reveal."""
    if isinstance(value, list):
        return [mask_invoice_egn(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in INVOICE_EGN_KEYS and isinstance(v, (str, int)) and v \
                    and not str(v).startswith(EGN_MASK_PREFIX) and (k == "egn" or possible_egn(v)):
                out[k] = mask_egn(v)
            elif k in VAT_KEYS and vat_is_egn(v):        # FG-429
                out[k] = mask_vat(v)
            else:
                out[k] = mask_invoice_egn(v)
        return out
    return value


def is_masked_vat(value: Any) -> bool:
    """FG-429: ``BG******1234`` — a masked BG + ЕГН VAT number."""
    return isinstance(value, str) and value.upper().startswith("BG" + EGN_MASK_PREFIX)


def is_masked_egn(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(EGN_MASK_PREFIX)


def same_egn(a: Any, b: Any) -> bool:
    da, db_ = re.sub(r"\D", "", str(a or "")), re.sub(r"\D", "", str(b or ""))
    return bool(da) and da == db_


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
    """``****1234`` — the last 4 characters only (R50 / Q005, FLOW-040 §9). Used for every
    reader without the full-IBAN right, and always in AuditEvent, DQ rows, logs, exports."""
    value = normalize_iban(iban)
    if len(value) < 4:
        return "****"
    return "****" + value[-4:]


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


#: Addendum A / R50 (Q005): the explicit sensitive right an Admin needs to see a full IBAN.
#: It is a permission on the Admin's own active RoleAssignment (``permissions``), never part
#: of a role's default set — by default no Admin has it (FLOW-040 §9/§11).
SENSITIVE_IBAN_PERMISSION = "sensitive.iban.read"
IBAN_FULL_ROLES = frozenset({"Owner", "Accountant"})


#: FG-245: every field that can carry an IBAN in a response (legacy and CP-01).
IBAN_KEYS = frozenset({"iban", "IBAN", "bank_iban", "bank_account", "bank_account_iban",
                       "counterparty_iban"})


async def full_iban_allowed(user) -> bool:
    """Q005 / D5: Owner and Accountant see a full IBAN; an Admin only with the explicit
    ``sensitive.iban.read`` permission on one of their own active RoleAssignments in this
    tenant (none by default); everyone else ``****1234``."""
    role = role_of(user)
    if role in IBAN_FULL_ROLES:
        return True
    if role != "Admin":
        return False
    from app.tenancy import registry
    row = await registry.tenant_role_assignments.find_one(
        {"user_id": user["id"], "tenant_id": user["org_id"], "status": "active",
         "permissions": SENSITIVE_IBAN_PERMISSION}, {"_id": 0, "id": 1})
    return row is not None


def mask_iban_fields(value: Any, full: bool) -> Any:
    """FG-245: a copy of ``value`` (dict / list, recursively) with every IBAN field shown as
    ``****1234`` unless ``full``. Non-IBAN text in such a field is masked the same way.
    FG-429 (R71): a VAT number that is BG + ЕГН is an ЕГН — masked here for EVERY reader,
    ``full`` or not (the full IBAN right is not an ЕГН right)."""
    if isinstance(value, list):
        return [mask_iban_fields(v, full) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not full and k in IBAN_KEYS and isinstance(v, str) and v and not v.startswith("****"):
                out[k] = mask_iban(v)
            elif k in VAT_KEYS and vat_is_egn(v):
                out[k] = mask_vat(v)
            else:
                out[k] = mask_iban_fields(v, full)
        return out
    return value


def keep_stored_if_masked(incoming: Any, stored: Any,
                          keys=("iban", "eik", "egn", "tax_id", "vat_number")) -> Any:
    """A form that sends back a masked value (``****1234`` / ``******1234``) never overwrites
    the stored one with the mask (CLAUDE.md §2: no data destroyed by a masked read)."""
    if not isinstance(incoming, dict) or not isinstance(stored, dict):
        return incoming
    out = dict(incoming)
    for k in keys:
        v = out.get(k)
        if isinstance(v, str) and (v.startswith("****") or is_masked_vat(v)) and stored.get(k):
            out[k] = stored[k]
    return out


def public_bank_account(doc: Dict[str, Any], full_allowed: bool) -> Dict[str, Any]:
    """The API view of a bank account: the full IBAN only when ``full_allowed``
    (Owner / Accountant, or an Admin with the sensitive right); otherwise ``****1234``."""
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["status_label"] = BA_LABELS.get(out.get("status"), out.get("status"))
    out["iban_masked"] = mask_iban(doc.get("iban"))
    if not full_allowed:
        out["iban"] = out["iban_masked"]
    return out


# ── payment guard mode (legacy payments that name no account) ───────────────
ENV_BANK_GUARD_MODE = "BANK_ACCOUNT_GUARD_MODE"
GUARD_OFF, GUARD_SHADOW, GUARD_ENFORCE = "off", "shadow", "enforce"


#: Р15: only a non-production environment may relax the guard (staging starts in shadow).
RELAXABLE_ENVS = ("staging", "development", "test")


def bank_guard_mode() -> str:
    """Addendum A / D1 (Q005; FLOW-010 L250/L254/L385, FLOW-025 L187): production is
    ``enforce``. ``BANK_ACCOUNT_GUARD_MODE`` = off / shadow is honoured ONLY when ``ENV`` is
    staging / development / test; production, an unknown or a missing ``ENV`` → enforce
    (fail closed). off = log only · shadow = DQ row + metric · enforce = 409."""
    import os
    from app.core.build_info import environment_label
    if environment_label() not in RELAXABLE_ENVS:
        return GUARD_ENFORCE
    value = (os.environ.get(ENV_BANK_GUARD_MODE) or GUARD_ENFORCE).strip().lower()
    return value if value in (GUARD_OFF, GUARD_SHADOW, GUARD_ENFORCE) else GUARD_ENFORCE


def is_cash_method(method: Any) -> bool:
    return str(method or "").strip().lower() in ("cash", "в брой", "вброй", "каса")
