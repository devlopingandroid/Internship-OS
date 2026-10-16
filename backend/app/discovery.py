"""
backend/app/discovery.py

Multi-source internship discovery module:
- Greenhouse public API (boards-api.greenhouse.io)
- Lever public API (api.lever.co)
- Ashby public API (api.ashbyhq.com/posting-api)
- Arbeitnow public API (arbeitnow.com/api/job-board-api)
- Remotive public API (remotive.com/api/remote-jobs)

Also provides structured metadata and official pre-filtered deep search links for platforms
that prohibit automated collection (LinkedIn, Wellfound, YC, Internshala, Cutshort, Indeed, Glassdoor).
"""

import httpx
import re
from .rules import is_internship, detect_work_mode, detect_location_category, detect_eligibility, evaluate_job

_TAG_RE = re.compile(r"<[^>]+>")

def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()

_PAID_FALSE_POSITIVES = re.compile(
    r"paid\s+(time\s+off|leave|vacation|holiday|training|course)",
    re.IGNORECASE,
)

def _infer_pay(description: str) -> str:
    if not description:
        return "unknown"
    low = description.lower()
    unpaid_signals = ["unpaid", "volunteer position", "no stipend", "no salary", "without pay"]
    if any(w in low for w in unpaid_signals):
        return "unpaid"
    cleaned = _PAID_FALSE_POSITIVES.sub("", description)
    low_clean = cleaned.lower()
    paid_signals = ["stipend", "salary", "compensation package", "remuneration", "per month", "lpa", "ctc", "annual pay", "$", "eur", "inr"]
    if any(w in low_clean for w in paid_signals):
        return "paid"
    return "unknown"

def _is_valid_url(url: str) -> bool:
    return bool(url) and url.startswith(("http://", "https://")) and len(url) <= 2000

# ── 1. Greenhouse Job Boards ──────────────────────────────────────────────────

GREENHOUSE_COMPANIES = [
    ("Stripe", "stripe"),
    ("Cloudflare", "cloudflare"),
    ("Figma", "figma"),
    ("GitLab", "gitlab"),
    ("Automattic", "automattic"),
    ("Canonical", "canonical"),
    ("Postman", "postman"),
    ("Razorpay", "razorpay"),
    ("BrowserStack", "browserstack"),
    ("Swiggy", "swiggy"),
]

async def fetch_greenhouse_internships(client: httpx.AsyncClient) -> list[dict]:
    results = []
    for company_name, board in GREENHOUSE_COMPANIES:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        try:
            r = await client.get(url, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            for j in data.get("jobs", []):
                title = (j.get("title") or "").strip()
                if not is_internship({"title": title}):
                    continue
                job_url = (j.get("absolute_url") or "").strip()
                if not _is_valid_url(job_url):
                    continue
                location = (j.get("location", {}).get("name") or "").strip()
                desc = _strip_html(j.get("content", ""))
                results.append({
                    "url": job_url,
                    "title": title,
                    "company": company_name,
                    "description": desc[:3000],
                    "location": location or "Remote",
                    "pay_status": _infer_pay(desc),
                    "source": "Greenhouse",
                })
        except Exception:
            continue
    return results

# ── 2. Lever Job Boards ───────────────────────────────────────────────────────

LEVER_COMPANIES = [
    ("Palantir", "palantir"),
    ("Spotify", "spotify"),
    ("Docker", "docker"),
    ("Atlassian", "atlassian"),
    ("Urban Company", "urbancompany"),
]

async def fetch_lever_internships(client: httpx.AsyncClient) -> list[dict]:
    results = []
    for company_name, site in LEVER_COMPANIES:
        url = f"https://api.lever.co/v0/postings/{site}?mode=json"
        try:
            r = await client.get(url, timeout=10)
            if r.status_code != 200:
                continue
            postings = r.json()
            if not isinstance(postings, list):
                continue
            for p in postings:
                title = (p.get("text") or "").strip()
                if not is_internship({"title": title}):
                    continue
                job_url = (p.get("hostedUrl") or p.get("applyUrl") or "").strip()
                if not _is_valid_url(job_url):
                    continue
                location = (p.get("categories", {}).get("location") or "").strip()
                desc = _strip_html(p.get("descriptionPlain", "") or p.get("description", ""))
                results.append({
                    "url": job_url,
                    "title": title,
                    "company": company_name,
                    "description": desc[:3000],
                    "location": location or "Remote",
                    "pay_status": _infer_pay(desc),
                    "source": "Lever",
                })
        except Exception:
            continue
    return results

# ── 3. Ashby Job Boards ───────────────────────────────────────────────────────

ASHBY_COMPANIES = [
    ("Ramp", "ramp"),
    ("Notion", "notion"),
    ("Perplexity", "perplexity"),
    ("Linear", "linear"),
    ("OpenAI", "openai"),
    ("Sentry", "sentry"),
]

async def fetch_ashby_internships(client: httpx.AsyncClient) -> list[dict]:
    results = []
    for company_name, board in ASHBY_COMPANIES:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        try:
            r = await client.get(url, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            for j in data.get("jobs", []):
                title = (j.get("title") or "").strip()
                if not is_internship({"title": title}):
                    continue
                job_url = (j.get("jobUrl") or j.get("applyUrl") or "").strip()
                if not _is_valid_url(job_url):
                    continue
                location = (j.get("location") or "").strip()
                desc = _strip_html(j.get("descriptionHtml", "") or j.get("descriptionPlain", ""))
                results.append({
                    "url": job_url,
                    "title": title,
                    "company": company_name,
                    "description": desc[:3000],
                    "location": location or "Remote",
                    "pay_status": _infer_pay(desc),
                    "source": "Ashby",
                })
        except Exception:
            continue
    return results

# ── 4. Arbeitnow Public API ───────────────────────────────────────────────────

async def fetch_arbeitnow_internships(client: httpx.AsyncClient) -> list[dict]:
    url = "https://www.arbeitnow.com/api/job-board-api"
    results = []
    try:
        r = await client.get(url, timeout=15)
        if r.status_code != 200:
            return results
        for j in r.json().get("data", []):
            title = (j.get("title") or "").strip()
            if not is_internship({"title": title}):
                continue
            job_url = (j.get("url") or "").strip()
            if not _is_valid_url(job_url):
                continue
            desc = _strip_html(j.get("description", ""))
            loc = "Remote" if j.get("remote") else (j.get("location") or "").strip()
            results.append({
                "url": job_url,
                "title": title,
                "company": (j.get("company_name") or "").strip(),
                "description": desc[:3000],
                "location": loc,
                "pay_status": _infer_pay(desc),
                "source": "Arbeitnow",
            })
    except Exception:
        pass
    return results

# ── 5. Remotive Public API ────────────────────────────────────────────────────

async def fetch_remotive_internships(client: httpx.AsyncClient) -> list[dict]:
    url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=50"
    results = []
    try:
        r = await client.get(url, timeout=15)
        if r.status_code != 200:
            return results
        for j in r.json().get("jobs", []):
            title = (j.get("title") or "").strip()
            if not is_internship({"title": title}):
                continue
            job_url = (j.get("url") or "").strip()
            if not _is_valid_url(job_url):
                continue
            desc = _strip_html(j.get("description", ""))
            results.append({
                "url": job_url,
                "title": title,
                "company": (j.get("company_name") or "").strip(),
                "description": desc[:3000],
                "location": (j.get("candidate_required_location") or "Remote").strip(),
                "pay_status": _infer_pay(desc),
                "source": "Remotive",
            })
    except Exception:
        pass
    return results

# ── Master Discovery Aggregator ───────────────────────────────────────────────

async def discover_all_internships() -> tuple[list[dict], list[str]]:
    """
    Fetches genuine internships across Greenhouse, Lever, Ashby, Arbeitnow, and Remotive.
    Returns (all_internships, errors).
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    all_internships: list[dict] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        # Greenhouse
        try:
            gh_jobs = await fetch_greenhouse_internships(client)
            all_internships.extend(gh_jobs)
        except Exception as e:
            errors.append(f"Greenhouse: {e}")

        # Lever
        try:
            lever_jobs = await fetch_lever_internships(client)
            all_internships.extend(lever_jobs)
        except Exception as e:
            errors.append(f"Lever: {e}")

        # Ashby
        try:
            ashby_jobs = await fetch_ashby_internships(client)
            all_internships.extend(ashby_jobs)
        except Exception as e:
            errors.append(f"Ashby: {e}")

        # Arbeitnow
        try:
            an_jobs = await fetch_arbeitnow_internships(client)
            all_internships.extend(an_jobs)
        except Exception as e:
            errors.append(f"Arbeitnow: {e}")

        # Remotive
        try:
            rem_jobs = await fetch_remotive_internships(client)
            all_internships.extend(rem_jobs)
        except Exception as e:
            errors.append(f"Remotive: {e}")

    return all_internships, errors


# ── Platforms Status and Permitted Search Links Hub ───────────────────────────

PLATFORM_INTEGRATIONS = [
    {
        "name": "Greenhouse Job Boards",
        "category": "ATS Company Boards",
        "status": "connected",
        "mode": "Official Public API (boards-api.greenhouse.io)",
        "companies": "Stripe, Cloudflare, Figma, GitLab, Automattic, Canonical, Postman, Razorpay, etc.",
        "description": "Direct automated discovery of verified internships via official Greenhouse public API feeds.",
        "url": None,
    },
    {
        "name": "Lever Job Boards",
        "category": "ATS Company Boards",
        "status": "connected",
        "mode": "Official Public API (api.lever.co)",
        "companies": "Palantir, Spotify, Docker, Atlassian, Urban Company, etc.",
        "description": "Direct automated discovery of verified internships via official Lever public API postings.",
        "url": None,
    },
    {
        "name": "Ashby Job Boards",
        "category": "ATS Company Boards",
        "status": "connected",
        "mode": "Official Public API (api.ashbyhq.com)",
        "companies": "Ramp, Notion, Perplexity, Linear, OpenAI, Sentry, etc.",
        "description": "Direct automated discovery of verified internships via official Ashby public job-board API.",
        "url": None,
    },
    {
        "name": "Arbeitnow",
        "category": "Open Job Board",
        "status": "connected",
        "mode": "Official Public API Feed",
        "companies": "European & Global Tech Employers",
        "description": "Direct automated discovery of internships via official Arbeitnow REST API.",
        "url": None,
    },
    {
        "name": "Remotive",
        "category": "Remote Job Board",
        "status": "connected",
        "mode": "Official Public API Feed",
        "companies": "Worldwide Remote Companies",
        "description": "Direct automated discovery via official Remotive public API.",
        "url": None,
    },
    {
        "name": "LinkedIn Jobs",
        "category": "Professional Network",
        "status": "permitted_links",
        "mode": "Permitted Pre-Filtered Search Hub",
        "companies": "All Global & Indian Employers",
        "description": "Automated scraping restricted by LinkedIn User Agreement & login wall. Use official deep-search link; import any URL with + Add Job.",
        "url": "https://www.linkedin.com/jobs/search/?keywords=software%20engineer%20intern&location=India&f_E=1&f_WT=2%2C1",
    },
    {
        "name": "Wellfound (AngelList)",
        "category": "Startup Platform",
        "status": "permitted_links",
        "mode": "Permitted Pre-Filtered Search Hub",
        "companies": "Y Combinator & High-Growth Startups",
        "description": "Protected by Cloudflare & authenticated session. Use official pre-filtered startup search link.",
        "url": "https://wellfound.com/jobs?role=Software+Engineer&job_type=internship",
    },
    {
        "name": "Y Combinator (Work at a Startup)",
        "category": "Startup Incubator",
        "status": "permitted_links",
        "mode": "Permitted Pre-Filtered Search Hub",
        "companies": "YC Backed Startups",
        "description": "Requires YC account authentication. Use official deep-search link to explore engineering internships.",
        "url": "https://www.workatastartup.com/jobs?demographic=any&role=eng&job_type=intern",
    },
    {
        "name": "Internshala",
        "category": "Student Internship Portal",
        "status": "permitted_links",
        "mode": "Permitted Pre-Filtered Search Hub",
        "companies": "Indian Tech Companies & Startups",
        "description": "Protected by Cloudflare & login sessions. Use official search link for Delhi NCR & Remote Tech Internships.",
        "url": "https://internshala.com/internships/software-development-internship/matching-preferences/",
    },
    {
        "name": "Cutshort",
        "category": "Tech Hiring Platform",
        "status": "permitted_links",
        "mode": "Permitted Pre-Filtered Search Hub",
        "companies": "Fast-growing Indian tech companies",
        "description": "Protected by login session. Use official link to view tech student/intern roles.",
        "url": "https://cutshort.io/jobs/software-engineer-internships",
    },
    {
        "name": "Indeed",
        "category": "Global Job Engine",
        "status": "permitted_links",
        "mode": "Permitted Pre-Filtered Search Hub",
        "companies": "All Enterprise & Startup Employers",
        "description": "Automated collection prohibited by robots.txt / Cloudflare. Use official pre-filtered search link.",
        "url": "https://in.indeed.com/jobs?q=software+developer+intern&l=Delhi%2C+Delhi",
    },
    {
        "name": "Glassdoor",
        "category": "Company Reviews & Jobs",
        "status": "permitted_links",
        "mode": "Permitted Pre-Filtered Search Hub",
        "companies": "All Major Employers",
        "description": "Automated collection prohibited by CAPTCHA & ToS. Use official internship search link.",
        "url": "https://www.glassdoor.co.in/Job/india-software-engineer-intern-jobs-SRCH_IL.0,5_IN115_KO6,30.htm",
    },
]
