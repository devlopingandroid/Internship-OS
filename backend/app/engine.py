"""Transactional imports and durable single-process background discovery."""
import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
import httpx
from .database import connect, get_preferences
from .normalization import normalize, canonical_url
from .rules import evaluate_job
from .sources import adapters, cached_request

tasks = {}


def upsert(c, incoming, prefs):
    job = normalize(incoming)
    # A canonical application URL is strong identity evidence; company/title alone is not.
    candidates = c.execute('SELECT * FROM jobs WHERE url=? OR application_url=? OR (source=? AND source_id=? AND source_id IS NOT NULL)',
                           (job['url'], job['application_url'], job['source'], job.get('source_id'))).fetchall()
    if not candidates:
        # Legacy URLs may still contain tracking parameters. Do not rewrite original URLs.
        candidates = [r for r in c.execute('SELECT * FROM jobs WHERE lower(company)=lower(?) AND lower(title)=lower(?)', (job['company'],job['title']))
                      if canonical_url(r['url']) == job['url']]
    existing = candidates[0] if candidates else None
    if existing:
        previous = json.loads(existing['metadata'] or '{}')
        refs = previous.get('source_references', [{'source': existing['source'], 'url': existing['url'], 'source_id':existing['source_id']}])
        reference = {k: job.get(k) for k in ('source','url','source_id')}
        if reference not in refs: refs.append(reference)
        if existing['source'] == 'Manual' or existing['source'] != job['source']:
            # Preserve manual facts and original attribution; add alternate source references only.
            previous['source_references'] = refs
            c.execute('UPDATE jobs SET metadata=? WHERE id=?', (json.dumps(previous), existing['id']))
            return 'skipped', existing['section'], existing['id']
        job['source_references'] = refs
        kind = 'updated'
    else:
        similar = c.execute('SELECT id FROM jobs WHERE lower(company)=lower(?) AND lower(title)=lower(?) AND lower(location)=lower(?)',
                            (job['company'],job['title'],job['location'])).fetchall()
        job['duplicate_candidates'] = [r['id'] for r in similar]
        job['source_references'] = [{k:job.get(k) for k in ('source','url','source_id')}]
        kind = 'imported'
    job['work_mode'] = job.get('source_work_mode', '')
    result = evaluate_job(job, prefs)
    job.update(result)
    stamp = datetime.now(timezone.utc).isoformat()
    fields = {k:job.get(k) for k in ('url','title','company','description','location','pay_status','source','source_id','application_url','publication_date','last_verified_at')}
    fields.update({k:result[k] for k in ('work_mode','eligibility','section','score','decision')})
    fields.update(reasons=json.dumps(result['reasons']), metadata=json.dumps(job), updated_at=stamp)
    if existing:
        fields.pop('url'); fields.pop('source')
        c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?', (*fields.values(),existing['id']))
        job_id = existing['id']
    else:
        cur = c.execute('INSERT INTO jobs('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',tuple(fields.values()))
        job_id = cur.lastrowid
    return kind, result['section'], job_id


def save_run(run_id, summary):
    with connect() as c:
        c.execute('UPDATE discovery_runs SET status=?,summary=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                  (summary['status'],json.dumps(summary),run_id))


def read_run(run_id):
    with connect() as c: row = c.execute('SELECT * FROM discovery_runs WHERE id=?',(run_id,)).fetchone()
    if not row: raise HTTPException(404,'Discovery run not found')
    return {**json.loads(row['summary']), 'id':run_id, 'status':row['status']}


def import_source(summary, result, listings, prefs):
    sections = {'best_matches':'eligible','needs_review':'review_required','other':'ineligible'}
    with connect() as c:
        for job in listings:
            c.execute('SAVEPOINT listing')
            try:
                outcome,section,_ = upsert(c,job,prefs)
                key = 'duplicates_skipped' if outcome == 'skipped' else outcome
                result[key] += 1; summary[key] += 1
                summary[sections[section]] += 1
                c.execute('RELEASE listing')
            except (ValueError, TypeError, sqlite3.IntegrityError):
                c.execute('ROLLBACK TO listing'); c.execute('RELEASE listing')
                result['failed'] += 1
        # Absence is evidence only for complete, successful board responses.
        complete = {b['board'] for b in result['boards'] if b['status']=='success' and not b['truncated']}
        seen = {j.get('source_id') for j in listings}
        for old in c.execute('SELECT * FROM jobs WHERE source=? AND source_id IS NOT NULL',(result['source'],)).fetchall():
            board = old['source_id'].split(':',1)[0]
            if board in complete and old['source_id'] not in seen:
                meta = json.loads(old['metadata'] or '{}')
                meta['availability'] = 'possibly_unavailable'
                evaluated = evaluate_job({**dict(old),**meta},prefs)
                meta.update(evaluated)
                c.execute('UPDATE jobs SET metadata=?,section=?,decision=?,reasons=? WHERE id=?',
                          (json.dumps(meta),evaluated['section'],evaluated['decision'],json.dumps(evaluated['reasons']),old['id']))


async def run_discovery(run_id, configured=None, request=None):
    summary = read_run(run_id)
    prefs = get_preferences()
    configured = configured or adapters()
    semaphore = asyncio.Semaphore(2)
    async def fetch(adapter, client):
        async with semaphore:
            async def get(client, url, source):
                return await cached_request(client,url,source,prefs['refresh_hours'])
            return await adapter.fetch(client, request or get)
    try:
        async with httpx.AsyncClient(headers={'User-Agent':'InternshipOS/0.2 personal discovery'}, follow_redirects=False) as client:
            pending = [asyncio.create_task(fetch(a,client)) for a in configured]
            try:
                for future in asyncio.as_completed(pending):
                    result = await future
                    if read_run(run_id)['status'] == 'cancelling':
                        summary['status'] = 'cancelled'; break
                    listings = result.pop('jobs')
                    result.update(imported=0,updated=0,duplicates_skipped=0)
                    await asyncio.to_thread(import_source, summary, result, listings, prefs)
                    summary['sources'].append(result)
                    summary['total_fetched'] += result['fetched']
                    summary['errors'] += [result['source']+': '+e for e in result['errors']]
                    summary['sources_completed'] += 1
                    save_run(run_id,summary)
            finally:
                for task in pending:
                    if not task.done(): task.cancel()
                await asyncio.gather(*pending,return_exceptions=True)
        if summary['status'] != 'cancelled':
            successful = sum(r['status'] != 'failed' for r in summary['sources'])
            summary['status'] = 'failed' if not successful else 'partial' if summary['errors'] or any(r['failed'] for r in summary['sources']) else 'completed'
    except asyncio.CancelledError:
        summary['status'] = 'interrupted'
    except Exception as exc:
        summary['status'] = 'failed'; summary['errors'].append(type(exc).__name__)
    finally:
        save_run(run_id,summary)
        tasks.pop(run_id,None)
    return summary


def new_run():
    run_id = str(uuid.uuid4())
    summary = dict(id=run_id,status='running',total_fetched=0,imported=0,updated=0,duplicates_skipped=0,
                   eligible=0,review_required=0,ineligible=0,sources=[],errors=[],sources_attempted=len(adapters()),sources_completed=0)
    with connect() as c:
        try: c.execute('INSERT INTO discovery_runs(id,status,summary) VALUES(?,?,?)',(run_id,'running',json.dumps(summary)))
        except sqlite3.IntegrityError: raise HTTPException(409,'A discovery run is already active')
    return summary


def recover_runs():
    with connect() as c:
        c.execute("UPDATE discovery_runs SET status='interrupted' WHERE status IN ('running','cancelling')")
