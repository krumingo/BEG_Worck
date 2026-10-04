"""
W0-06B — ``GET /api/media/avatar/{filename}``: the confirmed exposure, and its fix.

Before W0-06B the route served ANY file in the shared uploads directory without
authentication and without a media row. The first test below reproduces that
exposure on the pre-fix code (kept here verbatim as ``_legacy_serve_avatar``)
so the finding is evidence, not an assertion; the rest prove the fixed route
serves only a user's current profile photo and gives the same 404 for
everything else — another tenant's invoice photo included.

HTTP-level: the real router, mounted on a FastAPI app, over an in-memory db.

    pytest tests/test_w0_06b_avatar_route.py -v --noconftest
"""
import asyncio

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

pytest.importorskip("mongomock_motor")

A, B = "BEG", "TCB"
PNG = b"\x89PNG\r\n\x1a\n fake avatar bytes"
INVOICE = b"%PDF tenant B supplier invoice - confidential"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def _legacy_serve_avatar(upload_dir, filename):
    """The PRE-FIX handler body, verbatim apart from the directory parameter."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = upload_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type="image/jpeg")


async def _world(tmp_path, monkeypatch):
    from mongomock_motor import AsyncMongoMockClient
    from app.routes import media
    db = AsyncMongoMockClient()["avatar_" + tmp_path.name[-6:]]
    monkeypatch.setattr(media, "db", db)
    monkeypatch.setattr(media, "AVATAR_UPLOAD_DIR", tmp_path)
    files = {
        "a-avatar.png": PNG,            # tenant A user's current avatar
        "a-old-avatar.png": PNG,        # A's PREVIOUS avatar (still a profile upload)
        "b-invoice.jpg": INVOICE,       # tenant B: an invoice photo, not a profile
        "b-avatar.png": PNG,            # tenant B user's current avatar
        "orphan.png": PNG,              # on disk, no media row at all
        "a-invoice-as-avatar.jpg": INVOICE,
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    await db["users"].insert_many([
        {"id": "u-a", "org_id": A, "avatar_url": "/api/media/avatar/a-avatar.png"},
        {"id": "u-b", "org_id": B, "avatar_url": "/api/media/avatar/b-avatar.png"},
        # A user who pointed their avatar_url at an invoice photo of their tenant
        {"id": "u-trick", "org_id": A, "avatar_url": "/api/media/avatar/a-invoice-as-avatar.jpg"},
    ])
    await db["media_files"].insert_many([
        {"id": "m1", "org_id": A, "stored_filename": "a-avatar.png", "context_type": "profile",
         "context_id": "u-a", "content_type": "image/png"},
        {"id": "m2", "org_id": A, "stored_filename": "a-old-avatar.png",
         "context_type": "profile", "context_id": "u-a", "content_type": "image/png"},
        {"id": "m3", "org_id": B, "stored_filename": "b-invoice.jpg", "context_type": "delivery",
         "context_id": "dlv-1", "content_type": "image/jpeg"},
        {"id": "m4", "org_id": B, "stored_filename": "b-avatar.png", "context_type": "profile",
         "context_id": "u-b", "content_type": "image/png"},
        {"id": "m5", "org_id": A, "stored_filename": "a-invoice-as-avatar.jpg",
         "context_type": "delivery", "context_id": "dlv-2", "content_type": "image/jpeg"},
    ])
    app = FastAPI()
    app.include_router(media.router, prefix="/api")
    return db, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def test_the_pre_fix_route_exposed_another_tenants_file_unauthenticated(tmp_path):
    """EVIDENCE of the confirmed exposure: no session, no media row check."""
    async def body():
        (tmp_path / "b-invoice.jpg").write_bytes(INVOICE)
        app = FastAPI()

        @app.get("/api/media/avatar/{filename}")
        async def legacy(filename: str):
            return await _legacy_serve_avatar(tmp_path, filename)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as client:
            r = await client.get("/api/media/avatar/b-invoice.jpg")
        assert r.status_code == 200 and r.content == INVOICE
    run(body())


def test_a_current_profile_photo_is_still_served_without_a_session(tmp_path, monkeypatch):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            for name in ("a-avatar.png", "b-avatar.png"):
                r = await client.get("/api/media/avatar/" + name)
                assert r.status_code == 200 and r.content == PNG
                assert r.headers["content-type"] == "image/png"
                assert r.headers["x-content-type-options"] == "nosniff"
    run(body())


@pytest.mark.parametrize("name", [
    "b-invoice.jpg",              # another tenant's non-profile media
    "a-old-avatar.png",           # a profile upload that is no longer the avatar
    "orphan.png",                 # on disk without a media row
    "a-invoice-as-avatar.jpg",    # avatar_url pointed at a non-profile upload
    "missing.png",                # nothing at all
])
def test_everything_else_is_the_same_404(tmp_path, monkeypatch, name):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await client.get("/api/media/avatar/" + name)
        assert r.status_code == 404 and r.json() == {"detail": "File not found"}
    run(body())


def test_a_stored_name_shared_by_two_tenants_is_refused(tmp_path, monkeypatch):
    async def body():
        db, client = await _world(tmp_path, monkeypatch)
        await db["media_files"].insert_one(
            {"id": "m9", "org_id": B, "stored_filename": "a-avatar.png",
             "context_type": "profile", "context_id": "u-b", "content_type": "image/png"})
        async with client:
            r = await client.get("/api/media/avatar/a-avatar.png")
        assert r.status_code == 404
    run(body())


def test_a_profile_row_of_another_tenant_cannot_borrow_a_user(tmp_path, monkeypatch):
    """B's media row names A's user id: the user must exist in B, so it does not."""
    async def body():
        db, client = await _world(tmp_path, monkeypatch)
        (tmp_path / "b-forged.png").write_bytes(PNG)
        await db["media_files"].insert_one(
            {"id": "m8", "org_id": B, "stored_filename": "b-forged.png",
             "context_type": "profile", "context_id": "u-a", "content_type": "image/png"})
        await db["users"].update_one({"id": "u-a"},
                                     {"$set": {"avatar_url": "/api/media/avatar/b-forged.png"}})
        async with client:
            r = await client.get("/api/media/avatar/b-forged.png")
        assert r.status_code == 404
    run(body())


def test_a_non_image_content_type_is_never_served(tmp_path, monkeypatch):
    async def body():
        db, client = await _world(tmp_path, monkeypatch)
        await db["media_files"].update_one({"id": "m1"},
                                           {"$set": {"content_type": "text/html"}})
        async with client:
            r = await client.get("/api/media/avatar/a-avatar.png")
        assert r.status_code == 404
    run(body())


@pytest.mark.parametrize("name", ["..%2Fsecret", "a%5Cb.png", "..."])
def test_traversal_is_refused(tmp_path, monkeypatch, name):
    async def body():
        _, client = await _world(tmp_path, monkeypatch)
        async with client:
            r = await client.get("/api/media/avatar/" + name)
        assert r.status_code in (400, 404)
    run(body())
