"""
W0-06B — ``GET /api/media/avatar/{filename}`` under FLOW-002 (C02).

C01 found the route served any file of the shared uploads root without a
session, and narrowed it to current profile photos — but still without a
session, so another tenant's current avatar stayed readable by name (Codex
review, coordination/REVIEWS/W0-06B.md). C02 requires an authenticated,
active session and resolves the photo only inside the session's tenant.

Every request here goes through the REAL ``app.deps.auth.get_current_user``
with genuinely signed tokens (no dependency override), over the real router,
against an in-memory database:

* no session / bad token / forged tenant / disabled account  -> 401 / 403;
* tenant A user + tenant B's filename (known URL)            -> 404;
* same-tenant colleague and the owner                         -> 200;
* invoice and every other media, stale avatar, orphan,
  avatar_url pointed at a non-profile upload                  -> 404.

    pytest tests/test_w0_06b_avatar_route.py -v --noconftest
"""
import asyncio

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

pytest.importorskip("mongomock_motor")

A, B = "BEG", "TCB"
PNG_A = b"\x89PNG\r\n\x1a\n tenant A avatar"
PNG_B = b"\x89PNG\r\n\x1a\n tenant B avatar"
INVOICE = b"%PDF supplier invoice - confidential"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def token(user_id, org_id):
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token({"user_id": user_id, "org_id": org_id})}


async def _world(tmp_path, monkeypatch):
    from mongomock_motor import AsyncMongoMockClient
    from app.deps import auth as deps_auth
    from app.routes import media
    db = AsyncMongoMockClient()["avatar_" + tmp_path.name[-6:]]
    monkeypatch.setattr(media, "db", db)
    monkeypatch.setattr(deps_auth, "db", db)
    monkeypatch.setattr(media, "AVATAR_UPLOAD_DIR", tmp_path)
    files = {"a-avatar.png": PNG_A, "a-old-avatar.png": PNG_A, "a-invoice.jpg": INVOICE,
             "a-invoice-as-avatar.jpg": INVOICE, "b-avatar.png": PNG_B,
             "b-invoice.jpg": INVOICE, "orphan.png": PNG_A}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    await db["users"].insert_many([
        {"id": "u-a", "org_id": A, "role": "Worker", "is_active": True,
         "avatar_url": "/api/media/avatar/a-avatar.png"},
        {"id": "u-a2", "org_id": A, "role": "Worker", "is_active": True},   # colleague
        {"id": "u-trick", "org_id": A, "role": "Worker", "is_active": True,
         "avatar_url": "/api/media/avatar/a-invoice-as-avatar.jpg"},
        {"id": "u-off", "org_id": A, "role": "Worker", "is_active": False},
        {"id": "u-b", "org_id": B, "role": "Owner", "is_active": True,
         "avatar_url": "/api/media/avatar/b-avatar.png"},
    ])
    await db["media_files"].insert_many([
        {"id": "m1", "org_id": A, "stored_filename": "a-avatar.png", "context_type": "profile",
         "context_id": "u-a", "content_type": "image/png"},
        {"id": "m2", "org_id": A, "stored_filename": "a-old-avatar.png",
         "context_type": "profile", "context_id": "u-a", "content_type": "image/png"},
        {"id": "m3", "org_id": A, "stored_filename": "a-invoice.jpg", "context_type": "delivery",
         "context_id": "dlv-1", "content_type": "image/jpeg"},
        {"id": "m4", "org_id": A, "stored_filename": "a-invoice-as-avatar.jpg",
         "context_type": "delivery", "context_id": "dlv-2", "content_type": "image/jpeg"},
        {"id": "m5", "org_id": B, "stored_filename": "b-avatar.png", "context_type": "profile",
         "context_id": "u-b", "content_type": "image/png"},
        {"id": "m6", "org_id": B, "stored_filename": "b-invoice.jpg", "context_type": "delivery",
         "context_id": "dlv-9", "content_type": "image/jpeg"},
    ])
    app = FastAPI()
    app.include_router(media.router, prefix="/api")
    return db, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _get(client, name, headers=None):
    return await client.get("/api/media/avatar/" + name, headers=headers or {})


# ═══════════════════════════════════════════ evidence of what was being fixed
def test_the_pre_fix_route_exposed_another_tenants_file_unauthenticated(tmp_path):
    """C01 evidence, kept: the ORIGINAL handler served any uploads file with no session."""
    async def body():
        (tmp_path / "b-invoice.jpg").write_bytes(INVOICE)
        app = FastAPI()

        @app.get("/api/media/avatar/{filename}")
        async def legacy(filename: str):
            if "/" in filename or "\\" in filename or ".." in filename:
                raise HTTPException(status_code=400, detail="Invalid filename")
            path = tmp_path / filename
            if not path.exists():
                raise HTTPException(status_code=404, detail="File not found")
            return FileResponse(path, media_type="image/jpeg")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as client:
            r = await client.get("/api/media/avatar/b-invoice.jpg")
        assert r.status_code == 200 and r.content == INVOICE
    run(body())


# ═══════════════════════════════════════════════════ no session → refused
@pytest.mark.parametrize("name", ["a-avatar.png", "b-avatar.png", "b-invoice.jpg", "missing.png"])
def test_without_a_session_nothing_is_served(tmp_path, monkeypatch, name):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, name)
        assert r.status_code in (401, 403), r.status_code
        assert r.content not in (PNG_A, PNG_B, INVOICE)
    run(body())


@pytest.mark.parametrize("headers", [
    {"Authorization": "Bearer not-a-jwt"},
    {"Authorization": "Basic dXNlcjpwYXNz"},
    {"Authorization": "Bearer "},
])
def test_an_invalid_credential_is_refused(tmp_path, monkeypatch, headers):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, "a-avatar.png", headers)
        assert r.status_code in (401, 403) and r.content != PNG_A
    run(body())


def test_a_token_naming_another_tenant_for_the_user_is_refused(tmp_path, monkeypatch):
    """u-a signed for tenant B: no such (user, tenant) pair → 401, nothing read."""
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, "b-avatar.png", token("u-a", B))
        assert r.status_code == 401
    run(body())


def test_a_disabled_account_is_refused(tmp_path, monkeypatch):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, "a-avatar.png", token("u-off", A))
        assert r.status_code == 403
    run(body())


# ═══════════════════════════════════════════════ cross-tenant → never served
@pytest.mark.parametrize("user,org,name", [
    ("u-a", A, "b-avatar.png"),     # A's user, B's current avatar, known filename
    ("u-a2", A, "b-avatar.png"),
    ("u-b", B, "a-avatar.png"),     # and the other direction (B is an Owner)
    ("u-a", A, "b-invoice.jpg"),
])
def test_another_tenants_avatar_is_not_found_even_by_known_url(tmp_path, monkeypatch,
                                                                user, org, name):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, name, token(user, org))
        assert r.status_code == 404 and r.json() == {"detail": "File not found"}
    run(body())


def test_a_same_named_row_in_the_callers_tenant_cannot_borrow_the_other_tenants_file(
        tmp_path, monkeypatch):
    """B forges a profile row with A's stored name and points u-b at it: still not A's bytes
    for B, because the user/row pair must match — and A is unaffected."""
    async def body():
        db, client = await _world(tmp_path, monkeypatch)
        await db["media_files"].insert_one(
            {"id": "m9", "org_id": B, "stored_filename": "a-avatar.png",
             "context_type": "profile", "context_id": "u-b", "content_type": "image/png"})
        async with client:
            r_b = await _get(client, "a-avatar.png", token("u-b", B))
            r_a = await _get(client, "a-avatar.png", token("u-a2", A))
        # B's own row and B's own user both say so, but the user's avatar_url is
        # b-avatar.png, not this file — refused.
        assert r_b.status_code == 404
        assert r_a.status_code == 200 and r_a.content == PNG_A
    run(body())


# ═══════════════════════════════════════════════════ same tenant → served
@pytest.mark.parametrize("user", ["u-a", "u-a2", "u-trick"])
def test_a_same_tenant_user_gets_the_current_avatar(tmp_path, monkeypatch, user):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, "a-avatar.png", token(user, A))
        assert r.status_code == 200 and r.content == PNG_A
        assert r.headers["content-type"] == "image/png"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "private" in r.headers["cache-control"]
        assert r.headers["vary"] == "Authorization"
    run(body())


def test_tenant_b_gets_its_own_avatar(tmp_path, monkeypatch):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, "b-avatar.png", token("u-b", B))
        assert r.status_code == 200 and r.content == PNG_B
    run(body())


# ════════════════════════════ inside the tenant, only the current profile photo
@pytest.mark.parametrize("name", [
    "a-invoice.jpg",              # the tenant's own invoice photo
    "a-old-avatar.png",           # a profile upload that is no longer the avatar
    "orphan.png",                 # on disk without a media row
    "a-invoice-as-avatar.jpg",    # avatar_url pointed at a non-profile upload
    "missing.png",
])
def test_other_media_of_the_same_tenant_stay_blocked(tmp_path, monkeypatch, name):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, name, token("u-a", A))
        assert r.status_code == 404 and r.json() == {"detail": "File not found"}
    run(body())


def test_a_non_image_content_type_is_never_served(tmp_path, monkeypatch):
    async def body():
        db, client = await _world(tmp_path, monkeypatch)
        await db["media_files"].update_one({"id": "m1"}, {"$set": {"content_type": "text/html"}})
        async with client:
            r = await _get(client, "a-avatar.png", token("u-a", A))
        assert r.status_code == 404
    run(body())


def test_two_rows_naming_one_file_in_a_tenant_fail_closed(tmp_path, monkeypatch):
    async def body():
        db, client = await _world(tmp_path, monkeypatch)
        await db["media_files"].insert_one(
            {"id": "m1b", "org_id": A, "stored_filename": "a-avatar.png",
             "context_type": "profile", "context_id": "u-a", "content_type": "image/png"})
        async with client:
            r = await _get(client, "a-avatar.png", token("u-a", A))
        assert r.status_code == 404
    run(body())


@pytest.mark.parametrize("name", ["..%2Fsecret", "a%5Cb.png", "..."])
def test_traversal_is_refused(tmp_path, monkeypatch, name):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await _get(client, name, token("u-a", A))
        assert r.status_code in (400, 404)
    run(body())


def test_the_route_declares_the_session_dependency():
    """Structural guard: the avatar route cannot silently become public again."""
    from app.deps.auth import get_current_user
    from app.routes import media
    route = next(r for r in media.router.routes if getattr(r, "path", "") ==
                 "/media/avatar/{filename}")
    calls = {d.call for d in route.dependant.dependencies}
    assert get_current_user in calls
