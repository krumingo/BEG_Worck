"""
W0-06B — the storage boundary rules of the file-registry guard, proven by mutation.

``W06B-CREDSTORE``: only the vault names the sealed credential collection.
``W06B-ADAPTERBUILD``: only the storage service builds operational adapters.
(``W06B-RELBYPASS`` and ``W06B-DELSCOPE`` are proven in
``tests/test_w0_06b_entry_gate.py``.) Each rule must pass the real tree and
REJECT a deliberately unsafe module.

    pytest tests/test_w0_06b_static_guard.py -v --noconftest
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import w0_06a_file_registry_guard as guard          # noqa: E402


def check(source, name="_w0_06b_probe.py", folder=("app", "routes")):
    target = BACKEND.joinpath(*folder, name)
    target.write_text(source, encoding="utf-8")
    try:
        return {v[2] for v in guard.check_files([target.relative_to(BACKEND).as_posix()])}
    finally:
        target.unlink()


def test_the_real_tree_is_clean_including_the_w0_06b_modules():
    units, violations = guard.check_active_backend()
    assert violations == [], violations
    for module in ("app/files/storage.py", "app/files/credentials.py", "app/files/access.py",
                   "app/files/integrity.py", "app/files/providers/s3.py"):
        assert module in guard.active_backend_files()
        assert module in guard.FOUNDATION_MODULES


@pytest.mark.parametrize("source", [
    "async def leak(db):\n    return await db['storage_credentials'].find_one({})\n",
    "COLL = 'storage_credentials'\n",
])
def test_a_second_reader_of_the_credential_store_is_rejected(source):
    assert "W06B-CREDSTORE" in check(source)


def test_building_an_adapter_outside_the_storage_service_is_rejected():
    source = ("from app.files.providers.base import adapter_for\n"
              "def f(b):\n    return adapter_for(b, credentials={'password': 'x'})\n")
    assert "W06B-ADAPTERBUILD" in check(source)
    assert "W06B-ADAPTERBUILD" in check(source, folder=("app", "files"))


def test_reading_bindings_through_the_service_is_fine():
    source = ("from app.files.storage import StorageProviderService\n"
              "async def f(svc, ctx):\n    return await svc.list_bindings(ctx)\n")
    assert not {r for r in check(source) if r.startswith("W06B")}
