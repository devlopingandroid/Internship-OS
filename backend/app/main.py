from contextlib import asynccontextmanager
import json
import re
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, Field, model_validator
from typing import Literal
import asyncio
from . import engine
from .normalization import valid_url, normalize
from .database import connect, init_db, get_preferences, save_preferences, reclassify_all_jobs
from .rules import evaluate_job, DEFAULT_PREFERENCES, is_internship
from .browser_agent import prepare_application

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

active_preparations: set[int] = set()
active_preparations_lock = asyncio.Lock()
reclassification_lock = asyncio.Lock()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    engine.recover_runs()
    yield

app = FastAPI(title="Internship Automation API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173","http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
PROFILE = Path(__file__).resolve().parents[1] / "profile.json"

class JobIn(BaseModel):
    url: HttpUrl
    title: str = Field(min_length=2, max_length=250)
    company: str = ""
    description: str = Field(default="", max_length=100000)
    location: str = ""
    pay_status: Literal["paid", "unpaid", "unknown"] = "unknown"
    source_work_mode: Literal["On-site", "Hybrid", "Remote", "unknown"] = "unknown"
    source: str = "Manual"

class StatusIn(BaseModel):
    status: str

class ProfileIn(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""

class PreferencesIn(BaseModel):
    primary_role: str = "Full-Stack Engineer"
    preferred_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    salary_preference: Literal["paid_only", "paid_preferred", "exclude_unpaid"] = "paid_preferred"
    minimum_score: int = Field(default=50, ge=0, le=100)
    freshness_days: int = Field(default=0, ge=0, le=3650)
    refresh_hours: int = Field(default=6, ge=1, le=168)
    ranking_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_PREFERENCES['ranking_weights']))

    @model_validator(mode='after')
    def validate_preferences(self):
        if not self.preferred_roles or self.primary_role not in self.preferred_roles:
            raise ValueError('Select at least one role and choose a primary role from it')
        if len(self.preferred_roles) > 30 or any(not x.strip() or len(x)>100 for x in self.preferred_roles):
            raise ValueError('Provide up to 30 non-empty roles, each at most 100 characters')
        if not self.preferred_locations or not set(self.preferred_locations).issubset(DEFAULT_PREFERENCES['preferred_locations']):
            raise ValueError('Select valid preferred locations')
        if not self.work_modes or not set(self.work_modes).issubset({'On-site','Hybrid','Remote','unknown'}):
            raise ValueError('Select valid work modes')
        if set(self.ranking_weights) != set(DEFAULT_PREFERENCES['ranking_weights']) or any(not 0 <= v <= 100 for v in self.ranking_weights.values()) or not sum(self.ranking_weights.values()):
            raise ValueError('Ranking weights must be between 0 and 100 with a positive total')
        return self

def profile():
    if not PROFILE.exists():
        return {}
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def score(job, prefs=None):
    """Calculate job match score (0-100) and explanation reasons."""
    eval_res = evaluate_job(job, prefs)
    return eval_res["score"], eval_res["reasons"]

def cover(job):
    p = profile()
    return f"Hello {job.get('company') or 'team'} team,\n\nI'm interested in the {job.get('title')} opportunity. My focus is full-stack and backend software development, including React, Node.js, Python, APIs, and databases. I enjoy building practical products and solving end-to-end engineering problems.\n\nI'd welcome the opportunity to discuss how I could contribute.\n\nRegards,\n{p.get('full_name','Candidate')}"

def serialize(row):
    d = {**json.loads(dict(row).get("metadata") or "{}"), **dict(row)}
    d.pop("metadata", None)
    if isinstance(d.get("reasons"), str):
        try:
            d["reasons"] = json.loads(d["reasons"])
        except Exception:
            d["reasons"] = [d["reasons"]]
    elif not d.get("reasons"):
        d["reasons"] = []
    d["work_mode"] = d.get("work_mode") or "unknown"
    d["eligibility"] = d.get("eligibility") or "unknown"
    d["section"] = d.get("section") or "other"
    if not isinstance(d.get("matched_roles"), list):
        d["matched_roles"] = []
    return d

def _role_matches(role_target: str, matched_roles: list[str]) -> bool:
    if not role_target or role_target == "all":
        return True
    if not matched_roles:
        return False
    target_norm = re.sub(r"[\s\-_/]+", "", role_target.lower())
    for r in matched_roles:
        if not r:
            continue
        r_norm = re.sub(r"[\s\-_/]+", "", str(r).lower())
        if target_norm == r_norm:
            return True
        if "backend" in target_norm and "backend" in r_norm:
            return True
        if "fullstack" in target_norm and "fullstack" in r_norm:
            return True
        if "software" in target_norm and ("software" in r_norm or "swe" in r_norm):
            return True
        if "devops" in target_norm and "devops" in r_norm:
            return True
        if "android" in target_norm and "android" in r_norm:
            return True
    return False

# ── Discover helpers ──────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")

def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"&[a-z]+;", " ", text)   # basic HTML entities
    return re.sub(r"\s{2,}", " ", text).strip()

# Phrases that contain "paid" but do NOT indicate a paid internship
_PAID_FALSE_POSITIVES = re.compile(
    r"paid\s+(time\s+off|leave|vacation|holiday|training|course)",
    re.IGNORECASE,
)

def _infer_pay(description: str) -> str:
    """
    Conservative pay-status inference from description text.
    Returns 'unknown' when the signal is ambiguous to avoid mis-labelling.
    Only 'unpaid' and clearly salary-related phrases override the default.
    """
    if not description:
        return "unknown"
    low = description.lower()
    # Hard unpaid signals — checked first
    unpaid_signals = ["unpaid", "volunteer position", "no stipend", "no salary", "without pay"]
    if any(w in low for w in unpaid_signals):
        return "unpaid"
    # Remove known false-positive phrases before checking paid signals
    cleaned = _PAID_FALSE_POSITIVES.sub("", description)
    low_clean = cleaned.lower()
    # Conservative paid signals — specific salary/stipend language only
    paid_signals = ["stipend", "salary", "compensation package", "remuneration", "per month", "lpa", "ctc", "annual pay"]
    if any(w in low_clean for w in paid_signals):
        return "paid"
    return "unknown"

def _is_valid_url(url: str) -> bool:
    """Minimal sanity check: must start with http(s) and be a reasonable length."""
    return bool(url) and url.startswith(("http://", "https://")) and len(url) <= 2000

async def _fetch_remotive() -> list[dict]:
    """
    Remotive public API — no auth required.
    Docs: https://remotive.com/api/remote-jobs
    ToS: personal/non-commercial use permitted via the public API endpoint.
    Filters to software-dev category, returns up to 50 listings.
    """
    url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=50"
    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    for job in data.get("jobs", []):
        job_url = (job.get("url") or "").strip()
        title = (job.get("title") or "").strip()
        if not _is_valid_url(job_url) or not title:
            continue
        desc = _strip_html(job.get("description", ""))
        results.append({
            "url": job_url,
            "title": title,
            "company": (job.get("company_name") or "").strip(),
            "description": desc[:3000],
            # Use the API's own location field; fall back to 'Remote' only if blank
            "location": (job.get("candidate_required_location") or "Remote").strip(),
            # Pay status is unknown unless the description contains explicit salary language
            "pay_status": _infer_pay(desc),
            "source": "Remotive",
        })
    return results

async def _fetch_arbeitnow() -> list[dict]:
    """
    Arbeitnow open job board API — no auth required.
    Docs: https://www.arbeitnow.com/api/job-board-api
    ToS: free public API, no scraping — uses their official endpoint.
    """
    url = "https://www.arbeitnow.com/api/job-board-api"
    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    for job in data.get("data", []):
        job_url = (job.get("url") or "").strip()
        title = (job.get("title") or "").strip()
        if not _is_valid_url(job_url) or not title:
            continue
        desc = _strip_html(job.get("description", ""))
        # Arbeitnow sets remote=True explicitly; otherwise use the location field
        location = "Remote" if job.get("remote") else (job.get("location") or "").strip()
        results.append({
            "url": job_url,
            "title": title,
            "company": (job.get("company_name") or "").strip(),
            "description": desc[:3000],
            "location": location,
            # Pay status is unknown unless the description contains explicit salary language
            "pay_status": _infer_pay(desc),
            "source": "Arbeitnow",
        })
    return results

def _insert_job(c, job: dict) -> bool:
    """
    Insert a single normalised job dict.
    Returns True if inserted, False if it was a duplicate (UNIQUE url).
    """
    try:
        prefs = get_preferences(c)
    except Exception:
        prefs = DEFAULT_PREFERENCES
    eval_res = evaluate_job(job, prefs)
    s = eval_res["score"]
    reasons = eval_res["reasons"]
    work_mode = eval_res["work_mode"]
    eligibility = eval_res["eligibility"]
    section = eval_res["section"]

    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()]
        if "work_mode" in cols:
            c.execute(
                "INSERT INTO jobs(url,title,company,description,location,pay_status,source,score,reasons,cover_letter,work_mode,eligibility,section) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job["url"], job["title"], job["company"],
                    job["description"], job["location"], job["pay_status"],
                    job["source"], s, json.dumps(reasons), cover(job),
                    work_mode, eligibility, section,
                ),
            )
        else:
            c.execute(
                "INSERT INTO jobs(url,title,company,description,location,pay_status,source,score,reasons,cover_letter) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    job["url"], job["title"], job["company"],
                    job["description"], job["location"], job["pay_status"],
                    job["source"], s, json.dumps(reasons), cover(job),
                ),
            )
        return True
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            return False
        raise

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health(): return {"ok": True}

@app.get("/api/preferences")
def get_user_preferences():
    with connect() as c:
        return get_preferences(c)

@app.put("/api/preferences")
async def update_user_preferences(body: PreferencesIn):
    data = body.model_dump()
    async with reclassification_lock:
        with connect() as c:
            saved = save_preferences(data, c)
            counts = reclassify_all_jobs(c, saved)
    return {"preferences": saved, "counts": counts}

@app.post("/api/jobs/reclassify")
async def reclassify_jobs():
    async with reclassification_lock:
        with connect() as c:
            counts = reclassify_all_jobs(c)
    return {"ok": True, "counts": counts}

@app.get("/api/profile")
def get_user_profile():
    return profile()

@app.put("/api/profile")
def update_user_profile(body: ProfileIn):
    data = body.model_dump()
    cur = profile()
    cur.update(data)
    PROFILE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return cur

@app.delete("/api/jobs")
def clear_all_jobs():
    """Clear all job listings from the database."""
    with connect() as c:
        c.execute("DELETE FROM jobs")
    return {"ok": True, "message": "All jobs cleared"}

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    """Delete a single job by id."""
    with connect() as c:
        cur = c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        if not cur.rowcount:
            raise HTTPException(404, "Job not found")
    return {"ok": True, "deleted_id": job_id}

@app.get("/api/jobs")
def jobs(
    section: str | None = None,
    work_mode: str | None = None,
    pay_status: str | None = None,
    eligibility: str | None = None,
    status: str | None = None,
    query: str | None = None,
    role: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    paginate: bool = False,
    response: Response = None,
):
    with connect() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY score DESC, publication_date DESC, id DESC").fetchall()
    all_jobs = [serialize(r) for r in rows]
    if section:
        all_jobs = [j for j in all_jobs if j.get("section") == section]
    if work_mode and work_mode != "all":
        all_jobs = [j for j in all_jobs if j.get("work_mode") == work_mode]
    if pay_status and pay_status != "all":
        all_jobs = [j for j in all_jobs if j.get("pay_status") == pay_status]
    if eligibility and eligibility != "all":
        all_jobs = [j for j in all_jobs if j.get("eligibility") == eligibility]
    if status and status != "all":
        all_jobs = [j for j in all_jobs if j.get("status") == status]
    if role and role != "all":
        all_jobs = [
            j for j in all_jobs
            if _role_matches(role, j.get("matched_roles") or [])
        ]
    if query:
        q = query.lower().strip()
        all_jobs = [
            j for j in all_jobs
            if q in f"{j.get('title','')} {j.get('company','')} {j.get('description','')} {j.get('source','')} {j.get('location','')} {' '.join(j.get('reasons') or [])}".lower()
        ]

    total = len(all_jobs)
    if response:
        response.headers["X-Total-Count"] = str(total)

    # For full backwards compatibility with unpaginated callers (e.g. existing tests):
    if not paginate and limit is None and offset == 0:
        return all_jobs

    page_limit = limit if limit is not None else DEFAULT_PAGE_SIZE
    paged = all_jobs[offset : offset + page_limit]
    return {
        "items": paged,
        "total": total,
        "limit": page_limit,
        "offset": offset,
    }

@app.post("/api/jobs")
def add_job(body: JobIn):
    d = body.model_dump(); d['url'] = str(d['url'])
    if not valid_url(d['url']): raise HTTPException(422, 'Use a public HTTP(S) listing URL without embedded credentials')
    # A user supplied record is manual even when they identify its discovery platform.
    original_source = d['source']; d['source'] = 'Manual'
    d = normalize(d); d['source_label'] = original_source
    with connect() as c:
        outcome, _, job_id = engine.upsert(c,d,get_preferences(c))
        if outcome == 'skipped': raise HTTPException(409, 'This vacancy is already tracked')
        c.execute('UPDATE jobs SET cover_letter=? WHERE id=?',(cover(d),job_id))
        row = c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
    return serialize(row)


@app.get("/api/platforms")
def get_platforms():
    """Returns integration status and permitted deep search links for all platforms."""
    from .discovery import PLATFORM_INTEGRATIONS
    from .sources import DOCS
    with connect() as c: latest = c.execute('SELECT summary FROM discovery_runs ORDER BY created_at DESC, rowid DESC LIMIT 1').fetchone()
    reports = {r['source']:r for r in json.loads(latest['summary']).get('sources',[])} if latest else {}
    result = []
    configured_platforms = [*PLATFORM_INTEGRATIONS, dict(name='Jobicy', category='Remote Job Board', status='configured', mode='Public API', companies='Remote employers', url=None)]
    for p in configured_platforms:
        p = dict(p)
        name = p['name'].replace(' Job Boards','')
        if name in DOCS:
            p.update(status='configured', description='Public feed adapter; see last run for actual access and coverage.', documentation=DOCS[name], last_run=reports.get(name))
        else:
            p.update(description='Manual search link only. No automated collection or authorized API integration is configured.', mode='Manual search link')
        result.append(p)
    return result

@app.get('/api/preferences/defaults')
def default_preferences(): return DEFAULT_PREFERENCES

@app.get('/api/discovery/latest')
def latest_discovery():
    with connect() as c: row = c.execute('SELECT id FROM discovery_runs ORDER BY created_at DESC, rowid DESC LIMIT 1').fetchone()
    return engine.read_run(row['id']) if row else None

@app.get('/api/discovery/{run_id}')
def discovery_status(run_id: str): return engine.read_run(run_id)

@app.post('/api/discovery/{run_id}/cancel')
def cancel_discovery(run_id: str):
    summary = engine.read_run(run_id)
    if summary['status'] == 'running':
        summary['status'] = 'cancelling'; engine.save_run(run_id,summary)
    return summary

@app.post('/api/jobs/discover')
async def discover_jobs(relevant_only: bool = False, background: bool = True):
    # relevant_only is accepted for older clients; records are retained in Other Jobs.
    summary = engine.new_run()
    if background:
        engine.tasks[summary['id']] = asyncio.create_task(engine.run_discovery(summary['id']))
        return summary
    return await engine.run_discovery(summary['id'])

@app.get('/api/statistics')
def statistics():
    with connect() as c:
        rows = c.execute('SELECT section,pay_status,status FROM jobs').fetchall()
    return dict(total=len(rows), eligible=sum(r['section']=='best_matches' for r in rows),
                paid_eligible=sum(r['section']=='best_matches' and r['pay_status']=='paid' for r in rows),
                review_required=sum(r['section']=='needs_review' for r in rows),
                ineligible=sum(r['section']=='other' for r in rows),
                prepared=sum(r['status']=='prepared' for r in rows),applied=sum(r['status']=='applied' for r in rows),
                interview=sum(r['status']=='interview' for r in rows))


@app.patch("/api/jobs/{job_id}/status")
def update_status(job_id: int, body: StatusIn):
    allowed = {"saved","shortlisted","prepared","applied","interview","rejected","closed"}
    if body.status not in allowed: raise HTTPException(400,"Invalid status")
    with connect() as c:
        old = c.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()
        cur = c.execute("UPDATE jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (body.status,job_id))
        if old and old['status'] != body.status:
            c.execute('INSERT INTO status_history(job_id,old_status,new_status) VALUES(?,?,?)',(job_id,old['status'],body.status))
        if not cur.rowcount: raise HTTPException(404,"Job not found")
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return serialize(row)

@app.post("/api/jobs/{job_id}/prepare")
async def prepare(job_id: int):
    async with active_preparations_lock:
        if job_id in active_preparations:
            raise HTTPException(409, f"Preparation is already in progress for job {job_id}")
        active_preparations.add(job_id)
    try:
        with connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        # Intentionally does not submit. Browser remains open until the user closes it.
        job_dict = serialize(row)
        target = job_dict.get('application_url') or job_dict['url']
        if not valid_url(target):
            raise HTTPException(422, 'Invalid public application URL')
        result = await prepare_application(target, job_dict)
        with connect() as c:
            if job_dict['status'] in ('saved', 'shortlisted'):
                c.execute("UPDATE jobs SET status='prepared' WHERE id=?", (job_id,))
                c.execute('INSERT INTO status_history(job_id,old_status,new_status) VALUES(?,?,?)', (job_id, job_dict['status'], 'prepared'))
        return result
    finally:
        async with active_preparations_lock:
            active_preparations.discard(job_id)


