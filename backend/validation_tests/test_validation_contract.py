"""Local regression tests for the PATCHED harness. No real DB or Docker used.

Run: python -m unittest discover -s backend/validation_tests -v
"""
import asyncio
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from w0_02_validation_env import VALIDATION_ENV, require_runtime_env
from scripts import w0_02_validation_run as run
from scripts import w0_02_validation_seed as seed
from scripts.w0_02_validation_snapshot import inspect_snapshot

SPY='''
import sys, importlib.abc, runpy
class Stop(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('motor', 'pymongo', 'dotenv') or name.startswith('app.tenancy'):
            print('FORBIDDEN_IMPORT:'+name, file=sys.stderr)
            raise RuntimeError('Driver/application import happened before guard')
sys.meta_path.insert(0, Stop())
'''

class ImportGuardTests(unittest.TestCase):
    def proc(self, code, extra=None):
        env=run.child_env(extra)
        return subprocess.run([sys.executable,'-c',SPY+code],cwd=BACKEND,env=env,capture_output=True,text=True,timeout=20)
    def test_pure_and_compat_imports_no_database_import(self):
        p=self.proc('import w0_02_validation_env; import app.permissions.validation_env; import scripts.w0_02_validation_seed; import scripts.w0_02_bootstrap_permissions')
        self.assertEqual(p.returncode,0,p.stderr)
    def test_migration_rejects_each_wrong_target_before_imports(self):
        for key in VALIDATION_ENV:
            with self.subTest(key=key):
                p=self.proc("sys.argv=['migration'];runpy.run_module('scripts.w0_02_bootstrap_permissions',run_name='__main__')", {key:'invalid'})
                self.assertEqual(p.returncode,3,p.stderr);self.assertIn('FAIL-CLOSED',p.stderr);self.assertNotIn('FORBIDDEN_IMPORT',p.stderr)
    def test_seed_rejects_each_wrong_target_before_imports(self):
        for key in VALIDATION_ENV:
            with self.subTest(key=key):
                p=self.proc("sys.argv=['seed'];runpy.run_module('scripts.w0_02_validation_seed',run_name='__main__')", {key:'invalid'})
                self.assertEqual(p.returncode,3,p.stderr);self.assertNotIn('FORBIDDEN_IMPORT',p.stderr)
    def test_core_test_collection_rejects_before_application_imports(self):
        for key in VALIDATION_ENV:
            with self.subTest(key=key):
                p=self.proc("runpy.run_path('tests/test_w0_02_permission_core.py')", {key:'invalid','W0_02_REAL_MONGO':'1'})
                self.assertEqual(p.returncode,3,p.stderr);self.assertNotIn('FORBIDDEN_IMPORT',p.stderr)
    def test_help_needs_no_driver_or_database(self):
        p=self.proc("sys.argv=['migration','--help'];runpy.run_module('scripts.w0_02_bootstrap_permissions',run_name='__main__')", {'DB_NAME':'invalid'})
        self.assertEqual(p.returncode,0,p.stderr)
    def test_runtime_guard_does_not_compare_expected_to_itself(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(SystemExit):require_runtime_env()
    def test_lazy_package_preserves_public_exports(self):
        import app.permissions as package
        self.assertIn('require_permission',package.__all__)
        self.assertIn('PermissionDecision',package.__all__)
        self.assertEqual(set(package.__all__),set(package._EXPORTS))


def good_report(nodes):
    return {'schema':1,'selected':list(nodes),'deselected':[],'collection_errors':[],
            'internal_errors':[],'exit_code':0,
            'reports':[{'nodeid':n,'when':w,'outcome':'passed','wasxfail':None}
                       for n in nodes for w in ('setup','call','teardown')]}

class ReportTests(unittest.TestCase):
    def test_exact_report_accepted(self):run.verify_test_report(good_report(['a','b']),['a','b'])
    def test_one_passed_47_deselected_rejected(self):
        nodes=[str(i) for i in range(48)]; r=good_report(nodes[:1]); r['deselected']=nodes[1:]
        with self.assertRaises(run.ValidationFailure):run.verify_test_report(r,nodes)
    def test_collection_mismatch_or_missing_teardown_rejected(self):
        for mutate in (lambda r:r['selected'].pop(),lambda r:r['reports'].pop()):
            r=good_report(['a','b']);mutate(r)
            with self.assertRaises(run.ValidationFailure):run.verify_test_report(r,['a','b'])
    def test_skips_xfails_errors_duplicates_rejected(self):
        mutations=[lambda r:r['reports'][0].update(outcome='skipped'),
                   lambda r:r['reports'][1].update(wasxfail='known issue'),
                   lambda r:r['collection_errors'].append({'nodeid':'a'}),
                   lambda r:r['reports'].append(r['reports'][0]),
                   lambda r:r.update(exit_code=1)]
        for m in mutations:
            r=good_report(['a']);m(r)
            with self.assertRaises(run.ValidationFailure):run.verify_test_report(r,['a'])
    def test_real_pytest_plugin_produces_complete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test_smoke.py').write_text('def test_one():\n    assert True\n')
            env=run.child_env({'W002_PYTEST_EVIDENCE':str(p/'report.json')})
            cp=subprocess.run([sys.executable,'-m','pytest','--noconftest','-c',os.devnull,'--rootdir',tmp,
                               '-p','no:cacheprovider','-p','scripts.w0_02_validation_pytest_plugin',str(p/'test_smoke.py')],
                              env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
            r=json.loads((p/'report.json').read_text());run.verify_test_report(r,['test_smoke.py::test_one'])

class RunnerTests(unittest.TestCase):
    def test_env_drops_inherited_pytest_and_connection_overrides(self):
        with patch.dict(os.environ,{'PYTEST_ADDOPTS':'-k nothing','MONGO_URL':'bad','PYTHONPATH':'bad','W0_02_REAL_MONGO':'1'}):
            env=run.child_env()
        self.assertEqual(env['MONGO_URL'],VALIDATION_ENV['MONGO_URL']);self.assertEqual(env['W0_02_REAL_MONGO'],'0')
        self.assertEqual(env['PYTEST_ADDOPTS'],'');self.assertEqual(env['PYTHONPATH'],str(BACKEND))
    def test_nonzero_preserves_full_stdout_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            h=run.Harness(Path(d)/'ev')
            with self.assertRaises(run.ValidationFailure):
                h.command('fault',[sys.executable,'-c',"import sys; print('OUTPUT'); print('ERROR',file=sys.stderr); sys.exit(17)"])
            self.assertIn('OUTPUT',(h.evidence/'001-fault.stdout.txt').read_text())
            self.assertIn('ERROR',(h.evidence/'001-fault.stderr.txt').read_text())
            self.assertEqual(json.loads((h.evidence/'001-fault.json').read_text())['exit_code'],17)
    def test_timeout_is_failure_not_expected_guard(self):
        with tempfile.TemporaryDirectory() as d:
            h=run.Harness(Path(d)/'ev')
            with self.assertRaises(run.ValidationFailure):h.command('timeout',[sys.executable,'-c','import time;time.sleep(3)'],expected=124,timeout=.1)
            self.assertTrue(json.loads((h.evidence/'001-timeout.json').read_text())['timed_out'])
    def test_actual_negative_cli_probes_pass(self):
        with tempfile.TemporaryDirectory() as d:run.Harness(Path(d)/'ev').negatives()
    def test_failure_stops_subsequent_db_phases(self):
        for fail in ('NEGATIVES','MOCK SUITE','REAL-MONGO SUITE'):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as d:
                h=run.Harness(Path(d)/'ev');calls=[]
                def call(name):
                    calls.append(name)
                    if name==fail:raise run.ValidationFailure('injected')
                h.negatives=lambda:call('NEGATIVES')
                h.suite=lambda x:call('MOCK SUITE' if x=='mock' else 'REAL-MONGO SUITE')
                async def migration():call('MIGRATION CHECKS')
                h.migration=migration
                with patch.dict(os.environ,dict(VALIDATION_ENV)):
                    code=run.execute(h,'all')
                self.assertEqual(code,1);self.assertEqual(calls,list(run.PHASES[:run.PHASES.index(fail)+1]))
    def test_existing_evidence_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileExistsError):run.Harness(d)

# Minimal in-memory doubles. These test HARNESS control flow, not MongoDB behavior.
class Cursor:
    def __init__(self,docs):self.docs=copy.deepcopy(docs)
    async def to_list(self,n):return self.docs
class Collection:
    def __init__(self,db,name):self.db=db;self.name=name
    @property
    def docs(self):return self.db.data.setdefault(self.name,[])
    def find(self,q=None):return Cursor([d for d in self.docs if all(d.get(k)==v for k,v in (q or {}).items())])
    async def find_one(self,q):return next(iter((await self.find(q).to_list(None))),None)
    async def insert_one(self,d):
        d.setdefault('_id',len(self.docs)+1);self.docs.append(copy.deepcopy(d))
    async def insert_many(self,docs):
        for d in docs:await self.insert_one(d)
    async def update_one(self,q,u):
        for d in self.docs:
            if all(d.get(k)==v for k,v in q.items()):d.update(copy.deepcopy(u['$set']));return
    async def drop(self):self.db.data.pop(self.name,None)
class DB:
    def __init__(self,name,client):self.name=name;self.client=client;self.data={}
    def __getitem__(self,n):return Collection(self,n)
    def __getattr__(self,n):return self[n]
    async def list_collection_names(self):return list(self.data)
class Client:
    def __init__(self):self.dbs={};self.closed=False
    def __getitem__(self,n):return self.dbs.setdefault(n,DB(n,self))
    def close(self):self.closed=True

class MigrationControlTests(unittest.TestCase):
    def migration_case(self,fail=None,mutate_reapply=False):
        client=Client(); sy=client[VALIDATION_ENV['BEG_SYSTEM_DB']];calls=[];original={}
        with tempfile.TemporaryDirectory() as d:
            h=run.Harness(Path(d)/'ev')
            def migrate(label,args):
                calls.append(label)
                if label==fail:
                    return h.command('fault-'+label,[sys.executable,'-c','raise SystemExit(17)'])
                docs=sy.tenant_role_assignments.docs
                if label=='apply':
                    for row in list(docs):
                        if row.get('migrated_from')=='users.role':
                            original[row['id']]=copy.deepcopy(row)
                            row['role_id']={'Admin':'admin','Viewer':'LEGACY_VIEWER','Technician':'LEGACY_TECHNICIAN','SiteManager':'site_manager'}[row['role']]
                    for uid,perms in (('u_view',['budget.read']),('u_sm',['budget.read','budget.write'])):
                        docs.append({'id':'proj-'+uid,'user_id':uid,'scope_type':'project','scope_id':'P1','permissions':perms,'status':'active'})
                if label=='reapply' and mutate_reapply:docs[0]['updated_at']='changed'
            def correct_migrate(label,args):
                if label=='revert' and label!=fail:
                    calls.append(label)
                    for i,row in enumerate(sy.tenant_role_assignments.docs):
                        if row['id'] in original:sy.tenant_role_assignments.docs[i]=copy.deepcopy(original[row['id']])
                    return
                return migrate(label,args)
            h.migrate=correct_migrate
            async def snap(db):return copy.deepcopy(db.data)
            with patch.dict(os.environ,dict(VALIDATION_ENV)), patch.object(seed,'guarded_client',return_value=client),patch.object(run,'snapshot',snap):
                if fail or mutate_reapply:
                    with self.assertRaises(run.ValidationFailure):asyncio.run(h.migration())
                else:asyncio.run(h.migration())
            self.assertTrue(client.closed)
        return calls
    def test_harness_accepts_a_contract_satisfying_fake_migration(self):
        self.assertEqual(self.migration_case(),['dry','apply','reapply','reapply-protected','verify','revert'])
    def test_each_migration_process_failure_stops_later_phases(self):
        order=['dry','apply','reapply','reapply-protected','verify','revert']
        for label in order:
            with self.subTest(label=label):self.assertEqual(self.migration_case(fail=label),order[:order.index(label)+1])
    def test_reapply_state_change_is_detected(self):
        self.assertEqual(self.migration_case(mutate_reapply=True),['dry','apply','reapply'])

class SnapshotTests(unittest.TestCase):
    def make(self,p,files):
        sha='a'*40;(p/'code').mkdir();(p/'COMMIT').write_text(sha)
        with tarfile.open(p/'snapshot.tar','w') as tf:
            for name,data in files.items():
                f=p/'code'/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
                tf.add(f,arcname=name)
        (p/'snapshot.sha256').write_text(hashlib.sha256((p/'snapshot.tar').read_bytes()).hexdigest())
        return sha
    def test_clean_snapshot_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);sha=self.make(p,{'a.py':b'print(1)\n'})
            self.assertEqual(inspect_snapshot(p,sha)['errors'],[])
    def test_dotenv_production_blocked_without_printing_secret(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);sha=self.make(p,{'.env.production':b'password=privatevalue'})
            r=inspect_snapshot(p,sha);self.assertTrue(r['errors']);self.assertNotIn('privatevalue',str(r))
    def test_stale_or_modified_extraction_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);sha=self.make(p,{'a.py':b'original'});(p/'code/a.py').write_text('changed')
            self.assertTrue(inspect_snapshot(p,sha)['errors'])
    def test_credential_content_is_flagged_without_echo(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);sha=self.make(p,{'conf.py':b'url="' + b'mongodb://' + b'synthetic' + b':' + b'do-not-use@example.invalid/db"'})
            r=inspect_snapshot(p,sha);self.assertTrue(r['errors']);self.assertNotIn('do-not-use',str(r))

@unittest.skipUnless(shutil.which('bash'), 'Bash unavailable')
class ShellTests(unittest.TestCase):
    def execute(self,vars):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);parent=base/'w002_val_test';scripts=parent/'code/backend/scripts';scripts.mkdir(parents=True)
            (scripts/'w0_02_validation_run.py').write_text('test-double-only')
            sha='a'*40;(parent/'COMMIT').write_text(sha)
            bins=base/'bin';bins.mkdir();docker=bins/'docker'
            docker.write_text('#!/usr/bin/env bash\nexec '+__import__('shlex').quote(sys.executable.replace('\\','/'))+' -S '+__import__('shlex').quote((BACKEND/'validation_tests/fake_docker.py').as_posix())+' \"$@\"\n');docker.chmod(0o700)
            env=dict(os.environ,PATH=str(bins)+os.pathsep+os.environ['PATH'],
                     W002_FAKE_STATE=str(base/'docker.json'),W002_VALIDATION_ROOT=str(base),**vars)
            p=subprocess.run(['bash',(BACKEND/'scripts/w0_02_validate_synology.sh').as_posix(),parent.as_posix(),sha],env=env,capture_output=True,text=True,timeout=20)
            state=json.loads((base/'docker.json').read_text())
            dirs=list(base.glob('*-evidence')); self.assertEqual(len(dirs),1,p.stderr)
            self.assertTrue((dirs[0]/'cleanup.log').exists())
            self.assertTrue(parent.exists())
            return p,state,(dirs[0]/'final.exit').read_text().strip()
    def test_container_exit_7_preserved_and_cleanup_completes(self):
        p,s,rc=self.execute({'FAKE_TEST_EXIT':'7'})
        self.assertEqual(p.returncode,7,p.stdout+p.stderr);self.assertEqual(rc,'7')
        for key in ('containers','volumes','networks'):self.assertEqual(s[key],{})
    def test_success_and_zero_resources_is_success(self):
        p,s,rc=self.execute({});self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(rc,'0');self.assertEqual(s['volumes'],{})
    def test_cleanup_failure_does_not_become_success(self):
        p,s,rc=self.execute({'FAKE_CLEANUP_FAIL':'1'});self.assertEqual(p.returncode,70,p.stdout+p.stderr)
    def test_cleanup_failure_preserves_prior_test_failure(self):
        p,s,rc=self.execute({'FAKE_CLEANUP_FAIL':'1','FAKE_TEST_EXIT':'7'});self.assertEqual(p.returncode,7,p.stdout+p.stderr)
    def test_scan_failure_prevents_database_creation(self):
        p,s,rc=self.execute({'FAKE_SCAN_EXIT':'2'});self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertFalse(any(c[:2]==['network','create'] for c in s['calls']))
    def test_dependencies_failure_prevents_database_creation(self):
        p,s,rc=self.execute({'FAKE_DEPS_EXIT':'5'});self.assertEqual(p.returncode,5,p.stdout+p.stderr)
        self.assertFalse(any(c[:2]==['network','create'] for c in s['calls']))
    def test_preexisting_foreign_volume_not_adopted_or_deleted(self):
        p,s,rc=self.execute({'FAKE_EXISTING_VOLUME':'1'});self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertTrue(s['volumes']);self.assertTrue(all(v['run']=='FOREIGN' for v in s['volumes'].values()))

if __name__=='__main__':unittest.main(verbosity=2)
