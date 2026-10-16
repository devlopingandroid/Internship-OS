"""Public feed adapters. No profile data or browser access is used here."""
import asyncio
import json
import time
import os
from urllib.parse import quote
from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
from .normalization import normalize
from .discovery import GREENHOUSE_COMPANIES, LEVER_COMPANIES, ASHBY_COMPANIES

DOCS = {
    'Jobicy': 'https://jobicy.com/jobs-rss-feed',
    'Greenhouse': 'https://docs.greenhouse.io/job-board.html',
    'Lever': 'https://github.com/lever/postings-api',
    'Ashby': 'https://developers.ashbyhq.com/docs/public-job-posting-api',
    'Arbeitnow': 'https://www.arbeitnow.com/api/job-board-api',
    'Remotive': 'https://github.com/remotive-com/remote-jobs-api',
}


@dataclass
class Adapter:
    name: str
    boards: list
    max_pages: int = 3

    def url(self, board, page):
        if self.name == 'Greenhouse': return f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true'
        if self.name == 'Lever': return f'https://api.lever.co/v0/postings/{board}?mode=json&skip={(page-1)*100}&limit=100'
        if self.name == 'Ashby': return f'https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true'
        if self.name == 'Arbeitnow': return f'https://www.arbeitnow.com/api/job-board-api?page={page}'
        if self.name == 'Jobicy': return 'https://jobicy.com/api/v2/remote-jobs?count=100&industry=dev'
        return 'https://remotive.com/api/remote-jobs?category=software-dev'

    def unpack(self, data):
        if self.name == 'Lever': rows = data
        elif isinstance(data, dict): rows = data.get('data' if self.name == 'Arbeitnow' else 'jobs')
        else: rows = None
        if not isinstance(rows, list): raise ValueError('Malformed response: expected listings array')
        return rows

    def record(self, row, company, board, verified_at):
        if not isinstance(row, dict): raise ValueError('Malformed listing')
        name = self.name
        if name == 'Ashby' and row.get('isListed') is False: return None
        if name == 'Jobicy':
            row = {**row, 'title':row.get('jobTitle'), 'company_name':row.get('companyName'),
                   'location':row.get('jobGeo'), 'description':row.get('jobDescription'),
                   'job_type':' '.join(row.get('jobType') or []), 'publication_date':row.get('pubDate'),
                   'salary': ('Salary: '+str(row.get('salaryMin'))+' '+str(row.get('salaryCurrency'))) if row.get('salaryMin') is not None else ''}
        categories = row.get('categories') or {}
        loc = row.get('location') or ''
        if isinstance(loc, dict): loc = loc.get('name', '')
        description = row.get('descriptionPlain') or row.get('content') or row.get('description') or row.get('descriptionHtml') or ''
        if name == 'Lever':
            description += ' ' + ' '.join(str(x.get('content','')) for x in row.get('lists',[]) if isinstance(x,dict)) + ' ' + str(row.get('additionalPlain') or '')
            loc = categories.get('location', '')
        if name == 'Remotive': loc = row.get('candidate_required_location') or ''
        mode = row.get('workplaceType') or ''
        if row.get('remote') is True or row.get('isRemote') is True or name in ('Remotive','Jobicy'): mode = 'Remote'
        elif row.get('remote') is False and name == 'Arbeitnow': mode = ''  # false may still be hybrid
        salary = row.get('salary') or ''
        if row.get('compensation'): salary = (row['compensation'].get('compensationTierSummary') or '')
        if row.get('salaryRange'): salary = 'Salary: ' + json.dumps(row['salaryRange'])
        url = row.get('absolute_url') or row.get('hostedUrl') or row.get('jobUrl') or row.get('url') or ''
        record = normalize(dict(
            url=url, application_url=row.get('applyUrl') or url,
            title=row.get('text') if name == 'Lever' else row.get('title'),
            company=company or row.get('company_name'), description=description, location=loc,
            source=name, source_id=f'{board}:{row.get("id") or row.get("slug") or url}',
            source_work_mode=mode, employment_type=row.get('employmentType') or categories.get('commitment') or row.get('job_type'),
            compensation_text=salary, publication_date=row.get('publishedAt') or row.get('publication_date') or row.get('created_at'),
            source_updated_at=row.get('updated_at'), availability='active', last_verified_at=verified_at,
            eligible_region=(row.get('candidate_required_location') if name=='Remotive' else row.get('jobGeo') if name=='Jobicy' else None),
            country=((row.get('address') or {}).get('postalAddress') or {}).get('addressCountry'),
        ))
        return record

    async def fetch(self, client, request):
        result = dict(source=self.name, fetched=0, skipped=0, failed=0, jobs=[], errors=[], boards=[], cached_requests=0)
        for company, board in self.boards:
            info = dict(board=board, status='success', fetched=0, pages=0, truncated=False)
            cursor = None
            try:
                for page in range(1, self.max_pages + 1):
                    url = self.url(board, page)
                    if self.name == 'Jobicy' and cursor: url += '&cursor=' + quote(str(cursor), safe='')
                    data, stamp, cached = await request(client, url, self.name)
                    rows = self.unpack(data)
                    result['cached_requests'] += int(cached)
                    result['fetched'] += len(rows); info['fetched'] += len(rows); info['pages'] += 1
                    for row in rows:
                        try:
                            job = await asyncio.to_thread(self.record, row, company, board, stamp)
                            if job and job['url'] and job['title']: result['jobs'].append(job)
                            else: result['skipped'] += 1
                        except (ValueError, TypeError, AttributeError): result['failed'] += 1
                    more = (len(rows) == 100) if self.name == 'Lever' else bool((data.get('links') or {}).get('next')) if self.name == 'Arbeitnow' else False
                    if self.name == 'Jobicy':
                        cursor = data.get('nextCursor'); more = bool(cursor)
                    if not more: break
                    if page == self.max_pages: info['truncated'] = True
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                info['status'] = 'failed'
                # Do not include request headers, credentials, or response content in errors.
                message = f'{board}: HTTP {exc.response.status_code}' if isinstance(exc, httpx.HTTPStatusError) else f'{board}: {type(exc).__name__}'
                result['errors'].append(message)
            result['boards'].append(info)
        successes = sum(x['status'] == 'success' for x in result['boards'])
        result['status'] = 'success' if not result['errors'] else 'partial' if successes or result['jobs'] else 'failed'
        return result


def adapters():
    configured = [Adapter('Remotive', [('', 'remotive')]), Adapter('Arbeitnow', [('', 'arbeitnow')]), Adapter('Jobicy', [('', 'jobicy')]),
            Adapter('Greenhouse', GREENHOUSE_COMPANIES), Adapter('Lever', LEVER_COMPANIES), Adapter('Ashby', ASHBY_COMPANIES)]
    # Optional local configuration uses board tokens, never arbitrary request URLs.
    from pathlib import Path
    import re
    config_path = Path(__file__).resolve().parents[1] / 'sources.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
        for adapter in configured:
            setting = config.get(adapter.name, {})
            if 'boards' in setting and adapter.name in ('Greenhouse','Lever','Ashby'):
                boards = setting['boards']
                if not isinstance(boards, list) or len(boards)>100 or any(not isinstance(x,list) or len(x)!=2 or not re.fullmatch(r'[A-Za-z0-9_-]+',str(x[1])) for x in boards):
                    raise ValueError('Invalid source board configuration')
                adapter.boards = boards
            adapter.max_pages = max(1,min(10,int(setting.get('max_pages',3))))
        configured = [a for a in configured if config.get(a.name,{}).get('enabled',True)]
    return configured


async def cached_request(client, url, source, refresh_hours=6):
    from .database import connect
    ttl = max(6 if source == 'Remotive' else 1, refresh_hours) * 3600
    with connect() as c:
        cached = c.execute('SELECT * FROM source_cache WHERE url=?', (url,)).fetchone()
        backoff = c.execute('SELECT retry_at FROM source_backoff WHERE url=?', (url,)).fetchone()
    if cached and time.time() - cached['fetched_at'] < ttl:
        return json.loads(cached['payload']), cached['verified_at'], True
    if backoff and backoff['retry_at'] > time.time(): raise ValueError('Source cooldown active')
    for attempt in range(2):
        try:
            response = await client.get(url, timeout=20)
            if response.status_code == 429:
                # No rapid retry after rate limiting. Honor the provider's refusal.
                try: delay = max(3600, float(response.headers.get('Retry-After', '3600')))
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    try: delay = max(3600, parsedate_to_datetime(response.headers['Retry-After']).timestamp() - time.time())
                    except (ValueError, TypeError, KeyError): delay = 3600
                with connect() as c: c.execute('INSERT OR REPLACE INTO source_backoff VALUES(?,?)', (url,time.time()+delay))
                response.raise_for_status()
            if response.status_code >= 500 and attempt == 0:
                await asyncio.sleep(1); continue
            response.raise_for_status()
            payload = response.json()
            stamp = datetime.now(timezone.utc).isoformat()
            with connect() as c:
                c.execute('INSERT OR REPLACE INTO source_cache(url,payload,fetched_at,verified_at) VALUES(?,?,?,?)',
                          (url, json.dumps(payload), time.time(), stamp))
            return payload, stamp, False
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt: raise
            await asyncio.sleep(1)
