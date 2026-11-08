"""CLAUDE AUDIT probe — #83 CP-01 (ea51030). Copy into backend/tests/; mongomock and real Mongo
(W0_03_REAL_MONGO_URL), off / shadow / enforce. Reuses the PR's own harness.
  K1  IBAN CHANGE with only TWO people: Accountant acct-a ENTERS the new IBAN, Owner verifies,
      then acct-a (the entrant) approves and the Owner (the verifier) approves → is the changed
      account activated (status verified, the old one replaced, payments go to it)?
  K2  ×10 the second approval (activation) ∥ a manual payment → the payment goes to the old OR the
      new verified account, never to a pending one, never refused for two verified accounts.
"""
import asyncio

import pytest

from tests.test_cp_01_counterparty_iban_egn import (  # noqa: F401
    IBAN_NEW, IBAN_OLD, backend, hdr, manual_pay, mode, register, rows, run, verify)


def test_k1_entrant_and_verifier_are_the_two_approvers(monkeypatch, backend, mode):
    async def scenario(c, op):
        old = (await register(c, IBAN_OLD, who="acct2-a")).json()
        assert (await verify(c, old, who="owner-a")).status_code == 200
        new = (await register(c, IBAN_NEW, who="acct-a")).json()          # acct-a ENTERS
        new = (await verify(c, new, who="owner-a")).json()                # owner VERIFIES
        a1 = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("acct-a"),
                          json={"version": new["version"]})                # the ENTRANT approves
        v = a1.json().get("version", new["version"]) if a1.status_code == 200 else new["version"]
        a2 = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("owner-a"),
                          json={"version": v})                             # the VERIFIER approves
        accs = {a["id"]: a for a in await rows(op, "verified_bank_accounts")}
        pay = await manual_pay(c, counterparty_id="cp1")
        people = {"entered": accs[new["id"]].get("entered_by"),
                  "verified": (accs[new["id"]].get("verification") or {}).get("verified_by"),
                  "approvers": [x["approver_id"] for x in accs[new["id"]].get("approvals") or []]}
        print("K1 %s/%s: approve(entrant) %s approve(verifier) %s | new %s old %s | people %s | payment -> %s" % (
            backend, mode, a1.status_code, a2.status_code, accs[new["id"]]["status"], accs[old["id"]]["status"],
            people, pay.json().get("bank_account_id") == new["id"] and "NEW" or pay.status_code))
        distinct = {people["entered"], people["verified"], *people["approvers"]}
        assert not (accs[new["id"]]["status"] == "verified" and len(distinct) < 3), \
            "an IBAN change was activated by only %d people (entrant approved)" % len(distinct)
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(10))
def test_k2_activation_races_payment(monkeypatch, backend, mode, rep):
    async def scenario(c, op):
        old = (await register(c, IBAN_OLD, who="acct-a")).json()
        assert (await verify(c, old, who="owner-a")).status_code == 200
        new = (await register(c, IBAN_NEW, who="admin-a")).json()
        new = (await verify(c, new, who="acct-a")).json()
        new = (await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("owner-a"),
                            json={"version": new["version"]})).json()
        a2, pay = await asyncio.gather(
            c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("acct2-a"),
                   json={"version": new["version"]}),
            manual_pay(c, counterparty_id="cp1"))
        accs = {a["id"]: a for a in await rows(op, "verified_bank_accounts")}
        target = pay.json().get("bank_account_id") if pay.status_code == 201 else None
        print("K2 %s/%s/%d: approve %s | payment %s -> %s | statuses old %s new %s" % (
            backend, mode, rep, a2.status_code, pay.status_code,
            {old["id"]: "OLD", new["id"]: "NEW"}.get(target, target), accs[old["id"]]["status"],
            accs[new["id"]]["status"]))
        assert pay.status_code == 201 and target in (old["id"], new["id"]), pay.text
    run(monkeypatch, backend, mode, scenario)
