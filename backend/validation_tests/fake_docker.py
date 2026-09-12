#!/usr/bin/env python3
"""Test double ONLY. Never a real Docker client; saves state in a temporary file."""
import hashlib
import json
import os
import sys
from pathlib import Path

path = Path(os.environ['W002_FAKE_STATE'])
s = json.loads(path.read_text()) if path.exists() else {'containers': {}, 'volumes': {}, 'networks': {}, 'calls': []}
a = sys.argv[1:]
s['calls'].append(a)

def done(text='', code=0):
    path.write_text(json.dumps(s))
    if text: print(text)
    raise SystemExit(code)

def value(flag): return a[a.index(flag)+1]
def ident(name): return hashlib.sha256(name.encode()).hexdigest()
def kindmap(k): return s[{'container':'containers','volume':'volumes','network':'networks'}[k]]

if a[0]=='version': done('Fake Docker (test only)')
if a[0]=='pull': done('test image')
if a[:2]==['image','inspect']: done('sha256:'+ident(a[-1]))
if a[0]=='create':
    name=value('--name'); run=value('--label').split('=',1)[1]; key=ident(name)
    s['containers'][key]={'name':name,'run':run,'running':False,'exit':0}
    done(key)
if a[0]=='start':
    c=s['containers'][a[-1]]
    if '-a' in a:
        task=c['name'].rsplit('-',1)[1]
        c['exit']=int(os.environ.get('FAKE_'+task.upper()+'_EXIT','0'))
        c['running']=False
        # Intentionally return CLI 0 even for a failed container: wrapper MUST inspect.
        done('fake process '+task)
    c['running']=True;done(a[-1])
if a[0] in ('logs','exec'): done('7.0.fake')
if a[0] in ('container','volume','network'):
    kind,op=a[:2]; records=kindmap(kind)
    if op=='ls':
        if kind=='volume' and os.environ.get('FAKE_EXISTING_VOLUME')=='1' and not s['volumes']:
            runs=[v['run'] for v in s['containers'].values()]
            if runs: s['volumes'][runs[0]+'-deps']={'run':'FOREIGN'}
        done('\n'.join(records))
    if op=='inspect':
        r=records.get(a[-1])
        if r is None: done('not found',1)
        fmt=value('--format')
        if 'Running' in fmt: done(str(r['running']).lower())
        if 'ExitCode' in fmt: done(str(r['exit']))
        done(r['run'])
    if op=='create':
        name=a[-1]
        if name in records: done('exists',1)
        run=value('--label').split('=',1)[1]
        key=ident(name) if kind=='network' else name
        records[key]={'run':run};done(key)
    if op=='rm':
        key=a[-1]
        if os.environ.get('FAKE_CLEANUP_FAIL')=='1' and kind=='volume': done('injected cleanup failure',1)
        records.pop(key,None);done(key)
done('unhandled fake command '+repr(a),2)
