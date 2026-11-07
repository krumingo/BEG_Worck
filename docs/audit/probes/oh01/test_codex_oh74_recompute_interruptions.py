"""Codex's probes from PR #74 comment 6705531681 (verbatim logic), kept for re-runs."""
import asyncio
import pytest
from tests.test_oh_01_overhead_no_hard_delete import run, _category, _cost, _snapshot, _h, _key, ORG, PROJ_A

async def _indexes(db):
    from scripts.w0_04_bootstrap_audit_indexes import PLANNED_INDEXES
    for coll,keys,opts in PLANNED_INDEXES:
        await db[coll].create_index(keys,**opts)

@pytest.mark.parametrize('mode',['off','shadow','enforce'])
def test_r38_reader_during_allocation_switch(monkeypatch,mode):
    from app.tenancy.data_access import TenantCollection
    from app.services.project_pnl import compute_project_pnl
    async def scenario(c,db):
        await _indexes(db)
        cat=await _category(c)
        await _cost(c,cat['id'],amount=400)
        s1=await _snapshot(c)
        r=await c.post(f"/api/overhead/snapshots/{s1['id']}/allocate",json={'method':'Hours'},headers=_h(key=_key()))
        assert r.status_code==200,r.text
        await _cost(c,cat['id'],date='2026-10-20',amount=400)
        s2=await _snapshot(c)
        before=await compute_project_pnl(ORG,PROJ_A)
        assert before['expense']['overhead']==300 and before['expense']['overhead_recalculating']
        reached,proceed=asyncio.Event(),asyncio.Event()
        original=TenantCollection.insert_many
        async def pause(self,docs):
            if self.name=='project_overhead_allocations':
                reached.set()
                await asyncio.wait_for(proceed.wait(),10)
            return await original(self,docs)
        monkeypatch.setattr(TenantCollection,'insert_many',pause)
        task=asyncio.create_task(c.post(f"/api/overhead/snapshots/{s2['id']}/allocate",json={'method':'Hours'},headers=_h(key=_key())))
        await asyncio.wait_for(reached.wait(),10)
        try:
            during=await compute_project_pnl(ORG,PROJ_A)
            rows=await c.get('/api/overhead/allocations',headers=_h())
        finally:
            proceed.set()
            response=await task
        after=await compute_project_pnl(ORG,PROJ_A)
        print('allocation visibility',mode,before['expense']['overhead'],during['expense']['overhead'],during['expense']['overhead_label'],after['expense']['overhead'])
        assert response.status_code==200,response.text
        assert during['expense']['overhead']==300 and during['expense']['overhead_recalculating']
    run(monkeypatch,'real',mode,scenario)

@pytest.mark.parametrize('mode',['off','shadow','enforce'])
def test_archive_crash_after_canonical_event(monkeypatch,mode):
    from app.routes import overhead
    from app.services import overhead_lifecycle as ol
    async def scenario(c,db):
        await _indexes(db)
        cat=await _category(c)
        key=_key()
        original=ol.audit_overhead_event
        armed=[True]
        async def after(*args,**kwargs):
            event=await original(*args,**kwargs)
            if armed[0]:
                armed[0]=False
                raise RuntimeError('synthetic interruption after canonical audit committed')
            return event
        # 6a4ac5b: the route calls audit_overhead_event_once, which calls ol.audit_overhead_event
        monkeypatch.setattr(ol,'audit_overhead_event',after)
        monkeypatch.setattr(overhead,'audit_overhead_event',after)
        url=f"/api/overhead/categories/{cat['id']}?reason=duplicate"
        with pytest.raises(RuntimeError): await c.delete(url,headers=_h(key=key))
        response=await c.delete(url,headers=_h(key=key))
        events=await db.audit_events.count_documents({'entity_id':cat['id'],'action':'overhead.overhead_category.archived'})
        print('archive post-event recovery',mode,response.status_code,'events',events)
        assert response.status_code==200 and events==1
    run(monkeypatch,'real',mode,scenario)
