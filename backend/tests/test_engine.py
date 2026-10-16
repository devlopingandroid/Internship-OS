import asyncio
import json
import sqlite3
from datetime import datetime, timezone
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import database, engine
from app.main import app
from app.normalization import clean_html, compensation, normalize, canonical_url, parse_date, valid_url, job_type
from app.rules import evaluate_job, DEFAULT_PREFERENCES, match_roles
from app.sources import Adapter, cached_request


def job(**kw):
    return dict(url='https://example.com/job/1', application_url='https://example.com/job/1', title='Full Stack Intern',
                company='Acme', description='Develop React and Node APIs. Monthly stipend of INR 20000.',
                location='Delhi', source_work_mode='On-site', pay_status='paid', source='Manual', **kw)


@pytest.mark.parametrize('location,mode,description,decision', [
    ('Delhi','On-site','','eligible'), ('Noida','Hybrid','','eligible'), ('Gurugram','Remote','','eligible'),
    ('Bengaluru','On-site','','ineligible'), ('Mumbai','Hybrid','','ineligible'),
    ('Bengaluru','Remote','','eligible'), ('Remote US','Remote','US only','ineligible'),
    ('Worldwide','Remote','Open to candidates worldwide','eligible'),
    ('Remote','Remote','','review_required'), ('Berlin','On-site','','ineligible'),
    ('London','Hybrid','','ineligible'), ('Delhi','unknown','','review_required'),
    ('India','Remote','US applicants only','ineligible'),
    ('Worldwide','Remote','Except India','ineligible'),
])
def test_location_matrix(location,mode,description,decision):
    d=job(); d.update(location=location,source_work_mode=mode,description=description)
    assert evaluate_job(d)['decision'] == decision


@pytest.mark.parametrize('text,status', [
    ('Stipend of INR 20,000 per month','paid'), ('Salary: USD 30/hour','paid'),
    ('Unpaid internship','unpaid'), ('Paid leave and paid training','unknown'),
    ('We discuss salary expectations','unknown'), ('No compensation details','unknown'),
    ('Unpaid internship. Monthly stipend of INR 20000.','unknown'),
    ('Build a $100 million business','unknown'), ('No salary','unpaid')])
def test_compensation(text,status): assert compensation(text)['pay_status']==status


def test_normalization():
    assert clean_html('&lt;p&gt;A &amp; B&lt;/p&gt;<script>secret</script>')=='A & B'
    d=normalize({'url':'https://example.com/a?utm_source=x&id=3','title':'Intern','description':None})
    assert d['url']=='https://example.com/a?id=3'
    assert d['description']=='' and d['company']=='' and d['location']==''
    assert d['publication_date'] is None
    assert parse_date('invalid') is None
    assert parse_date(1700000000000).startswith('2023-11')


@pytest.mark.parametrize('url',['file:///secret','javascript:alert(1)','http://127.0.0.1/a','http://localhost/x','https://user:pass@example.com/x','http://10.0.0.1'])
def test_invalid_urls(url): assert not valid_url(url)


def test_conservative_rules():
    d=job(); d.update(source_work_mode='unknown', description='Collaborate with remote colleagues')
    assert evaluate_job(d)['work_mode']=='unknown'
    d=job(); d.update(title='Marketing Intern',description='Python and AI are useful')
    assert not match_roles(d,DEFAULT_PREFERENCES['preferred_roles'])
    d=job(); d.update(title='Full-time Software Engineer',description='Mentor interns')
    assert evaluate_job(d)['decision']=='ineligible'
    assert job_type({'title':'Backend Engineer','employment_type':'Intern'})=='internship'
    assert job_type({'title':'Graduate Engineer'})=='graduate'
    assert job_type({'title':'Research Fellow'})=='unknown'
    d=job(); d['compensation_confidence']='conflicting'
    assert evaluate_job(d)['decision']=='review_required'
    d=job(); d['deadline']='2020-01-01'
    assert evaluate_job(d)['decision']=='ineligible'


def test_preferences_and_ranking():
    d=job(); d['location']='Noida'
    p={**DEFAULT_PREFERENCES,'preferred_locations':['Delhi']}
    assert evaluate_job(d,p)['decision']=='ineligible'
    d=job(); paid=evaluate_job(d)['score']; d['pay_status']='unknown'
    assert evaluate_job(d)['score']<paid
    assert evaluate_job(d,{**DEFAULT_PREFERENCES,'salary_preference':'exclude_unpaid'})['decision']=='eligible'
    d['pay_status']='unpaid'
    assert evaluate_job(d,{**DEFAULT_PREFERENCES,'salary_preference':'exclude_unpaid'})['decision']=='ineligible'


@pytest.mark.parametrize('source,payload', [
    ('Greenhouse',{'jobs':[{'id':1,'title':'Backend Intern','absolute_url':'https://example.com/job','location':{'name':'Delhi'},'content':'<p>Build APIs</p>'}]}),
    ('Lever',[{'id':'one','text':'Backend Intern','hostedUrl':'https://example.com/job','categories':{'location':'Delhi','commitment':'Intern'},'workplaceType':'remote'}]),
    ('Ashby',{'jobs':[{'title':'Backend Intern','jobUrl':'https://example.com/job','location':'Delhi','isRemote':True,'employmentType':'Intern'}]}),
    ('Arbeitnow',{'data':[{'slug':'one','title':'Backend Intern','url':'https://example.com/job','company_name':'Acme','location':'Berlin','remote':True}]}),
    ('Remotive',{'jobs':[{'id':1,'title':'Backend Intern','url':'https://example.com/job','company_name':'Acme','candidate_required_location':'Worldwide'}]}),
])
@pytest.mark.asyncio
async def test_adapters(source,payload):
    async def request(*args): return payload,'2026-10-15T00:00:00+00:00',False
    async with httpx.AsyncClient() as client:
        result=await Adapter(source,[('Acme','acme')]).fetch(client,request)
    assert result['fetched']==1 and len(result['jobs'])==1
    assert result['jobs'][0]['source_id'] and result['jobs'][0]['application_url']
    if source=='Arbeitnow': assert result['jobs'][0]['location']=='Berlin' and result['jobs'][0]['source_work_mode']=='Remote'


@pytest.mark.asyncio
async def test_pagination_and_partial_failure():
    calls=[]
    async def request(client,url,source):
        calls.append(url)
        if 'broken' in url: raise httpx.ConnectError('down')
        if 'skip=0' in url:
            rows=[{'id':i,'text':'Intern','hostedUrl':f'https://example.com/{i}'} for i in range(100)]
        else: rows=[]
        return rows,'2026-10-15T00:00:00+00:00',False
    result=await Adapter('Lever',[('Good','good'),('Bad','broken')]).fetch(None,request)
    assert result['status']=='partial' and result['fetched']==100 and len(calls)==3


@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[{}, {'jobs':None}, {'jobs':'bad'}])
async def test_malformed_response(payload):
    async def request(*args): return payload,'2026-10-15',False
    result=await Adapter('Greenhouse',[('Acme','acme')]).fetch(None,request)
    assert result['status']=='failed'


@pytest.mark.asyncio
async def test_empty_and_missing_fields():
    async def request(*args): return {'jobs':[{},None]},'2026-10-15',False
    result=await Adapter('Greenhouse',[('Acme','acme')]).fetch(None,request)
    assert result['skipped']==1 and result['failed']==1
    async def empty(*args): return {'jobs':[]},'2026-10-15',False
    assert (await Adapter('Greenhouse',[('Acme','acme')]).fetch(None,empty))['status']=='success'


@pytest.mark.asyncio
@pytest.mark.parametrize('code',[429,500,404])
async def test_http_errors(code,monkeypatch):
    calls=[]
    async def sleep(_): pass
    monkeypatch.setattr(asyncio,'sleep',sleep)
    def handler(request): calls.append(request); return httpx.Response(code,json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError): await cached_request(client,'https://example.com/feed','Remotive')
    assert len(calls)==(2 if code==500 else 1)


@pytest.mark.asyncio
async def test_timeout_and_cache(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr(asyncio,'sleep',sleep)
    calls=[]
    def handler(request): calls.append(request); raise httpx.ReadTimeout('timeout')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout): await cached_request(client,'https://example.com/feed','Remotive')
    assert len(calls)==2
    def success(request): return httpx.Response(200,json={'jobs':[]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(success)) as client:
        first=await cached_request(client,'https://example.com/feed','Remotive')
        second=await cached_request(client,'https://example.com/feed','Remotive')
    assert not first[2] and second[2] and first[1]==second[1]


def test_dedup_and_history():
    with database.connect() as c:
        d=job(); d.update(source='Greenhouse',source_id='acme:1')
        _,_,id=engine.upsert(c,d,DEFAULT_PREFERENCES)
        c.execute("UPDATE jobs SET status='interview',cover_letter='keep' WHERE id=?",(id,))
        d['description']+=' New details.'
        assert engine.upsert(c,d,DEFAULT_PREFERENCES)[0]=='updated'
        d.update(source='Lever',source_id='acme:2',url='https://example.com/alternate')
        assert engine.upsert(c,d,DEFAULT_PREFERENCES)[0]=='skipped'
        r=c.execute('SELECT * FROM jobs').fetchone()
        assert r['status']=='interview' and r['cover_letter']=='keep'
        assert len(json.loads(r['metadata'])['source_references'])==2
        assert c.execute('SELECT count(*) FROM jobs').fetchone()[0]==1
        d.update(url='https://example.com/different',application_url='https://example.com/different',source_id='acme:3')
        _,section,_=engine.upsert(c,d,DEFAULT_PREFERENCES)
        assert section=='needs_review'


def test_migration_preserves_records(tmp_path,monkeypatch):
    path=tmp_path/'legacy.db'
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY,url TEXT UNIQUE,title TEXT,company TEXT,description TEXT,location TEXT,pay_status TEXT,source TEXT,status TEXT,score INTEGER,reasons TEXT,cover_letter TEXT,created_at TEXT)")
        c.execute("INSERT INTO jobs VALUES(1,'https://example.com/old','Intern','Acme','','Delhi','unknown','Manual','applied',30,'[]','keep','2020-01-01')")
    monkeypatch.setattr(database,'DB_PATH',path)
    database.init_db(); database.init_db(); database.reclassify_all_jobs()
    with database.connect() as c:
        r=c.execute('SELECT * FROM jobs').fetchone()
        assert r['status']=='applied' and r['cover_letter']=='keep' and r['url']=='https://example.com/old'


@pytest.mark.asyncio
async def test_real_pipeline_partial_repeat_and_restart():
    async def request(client,url,source):
        if source=='Remotive': raise httpx.ConnectError('offline')
        return {'jobs':[{'id':1,'title':'Full Stack Intern','absolute_url':'https://example.com/job','location':{'name':'Delhi (on-site)'},'content':'Monthly stipend of INR 20000'}]},'2026-10-15T00:00:00+00:00',False
    configured=[Adapter('Greenhouse',[('Acme','acme')]),Adapter('Remotive',[('','remotive')])]
    first=engine.new_run()
    with pytest.raises(HTTPException): engine.new_run()
    result=await engine.run_discovery(first['id'],configured,request)
    assert result['status']=='partial' and result['imported']==1 and result['eligible']==1
    second=engine.new_run(); result=await engine.run_discovery(second['id'],configured,request)
    assert result['updated']==1 and result['imported']==0
    third=engine.new_run(); engine.recover_runs()
    assert engine.read_run(third['id'])['status']=='interrupted'


def test_api_regression_and_persistence():
    with TestClient(app) as client:
        assert client.get('/api/health').json()['ok']
        d=job(); created=client.post('/api/jobs',json=d)
        assert created.status_code==200,created.text
        id=created.json()['id']
        assert client.patch(f'/api/jobs/{id}/status',json={'status':'applied'}).json()['status']=='applied'
        prefs=client.get('/api/preferences').json(); prefs['minimum_score']=65
        assert client.put('/api/preferences',json=prefs).status_code==200
        assert client.get('/api/preferences').json()['minimum_score']==65
        prefs['primary_role']='Not selected'
        assert client.put('/api/preferences',json=prefs).status_code==422
        assert client.get('/api/jobs').json()[0]['status']=='applied'
        assert client.post('/api/jobs',json=d).status_code==409
        assert client.get('/api/statistics').json()['applied']==1
