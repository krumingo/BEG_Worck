"""
W0-03B1 — Master Data configuration and context guard.

Two jobs, both fail-closed:

  * decide ``MASTER_DATA_MODE`` (off | shadow | enforce), default **off**;
  * hand out a tenant context only when it was resolved server-side.

**Deliberate difference from W0-02.** ``app/permissions/deps.py`` silently
falls back to ``off`` when ``PERMISSION_SERVICE_MODE`` holds a typo. Here an
invalid value **raises**: the W0-10A review established that a guard a typo can
switch off is not a guard, and the same reasoning applies to a mode switch that
decides whether a write happens at all. Falling back would hide an operator
mistake behind a safe-looking default.

Canon: TENANCY_MODEL.md §2 (the active tenant is decided server-side; a
tenant_id arriving in a body is never trusted), D-15.
"""
import os
from typing import Any, Optional

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"
VALID_MODES = (MODE_OFF, MODE_SHADOW, MODE_ENFORCE)

ENV_MODE = "MASTER_DATA_MODE"


class MasterDataConfigError(Exception):
    """The Master Data configuration is unusable; refuse rather than guess."""


class MasterDataTenantContextMissing(Exception):
    """No server-side tenant context — the operation is refused."""


def current_mode(env: Optional[dict] = None) -> str:
    """Return the configured mode.

    Unset -> ``off``. Set to anything that is not a valid mode -> raise; note
    that ``MASTER_DATA_MODE=""`` is a value an operator set, not an absent one,
    so it is refused rather than defaulted (the ``${VAR-default}`` lesson from
    the W0-10A tooling).
    """
    source = os.environ if env is None else env
    if ENV_MODE not in source:
        return MODE_OFF
    raw = source[ENV_MODE]
    mode = raw.strip().lower() if isinstance(raw, str) else raw
    if mode not in VALID_MODES:
        raise MasterDataConfigError(
            "invalid %s=%r — only %s are allowed; refusing rather than guessing"
            % (ENV_MODE, raw, "/".join(VALID_MODES))
        )
    return mode


def validate_config(env: Optional[dict] = None) -> str:
    """Startup hook: validate the configuration once and report the mode."""
    return current_mode(env)


def is_off(mode: Optional[str] = None) -> bool:
    return (mode or current_mode()) == MODE_OFF


def require_tenant_context(ctx: Any) -> Any:
    """Return ``ctx`` only if it is a server-side resolved tenant context.

    Refused, in order:
      * no context at all;
      * a legacy/compat context (``enforced`` False) — that path carries a
        legacy org identity, not a resolved tenant, and must never be used to
        write canonical Master Data;
      * a context without a usable ``tenant_id``.

    This function never reads a request, a body or an environment variable to
    obtain a tenant. There is exactly one source: the W0-01 resolver, through
    the context the Tenant Guard produced.
    """
    if ctx is None:
        raise MasterDataTenantContextMissing("no tenant context: refusing (fail closed)")
    if not getattr(ctx, "enforced", False):
        raise MasterDataTenantContextMissing(
            "legacy/compat context is not a resolved tenant: refusing to touch Master Data"
        )
    tenant_id = getattr(ctx, "tenant_id", None)
    if not tenant_id or not isinstance(tenant_id, str):
        raise MasterDataTenantContextMissing("tenant context carries no usable tenant_id")
    return ctx
