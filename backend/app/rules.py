import re
import json

DEFAULT_PREFERENCES = {
    "primary_role": "Full-Stack Engineer",
    "preferred_roles": [
        "Full-Stack Engineer",
        "Software Engineer",
        "Backend Engineer",
        "Python/AI Engineer",
        "Python Developer",
        "AI Engineer",
        "Machine Learning Engineer",
        "DevOps Engineer",
        "Android Developer",
    ],
    "preferred_locations": [
        "Delhi",
        "Noida",
        "Gurugram/Gurgaon",
        "Outside Delhi NCR / other Indian cities",
        "Outside India",
    ],
    "work_modes": ["On-site", "Hybrid", "Remote"],
    "minimum_score": 50,
    "freshness_days": 0,
    "refresh_hours": 6,
    "ranking_weights": {"role": 40, "skills": 10, "internship": 10, "location": 10, "compensation": 15, "freshness": 5, "availability": 5, "completeness": 5},
    "salary_preference": "paid_preferred",  # paid_only | paid_preferred | exclude_unpaid
}

ROLE_PATTERNS = {
    "Full-Stack Engineer": [
        r"\bfull[\s-]?stack\b", r"\bfullstack\b", r"\bweb develop(er|ment)\b",
        r"\breact\b", r"\bnode(\.js)?\b", r"\bfrontend and backend\b"
    ],
    "Software Engineer": [
        r"\bsoftware (engineer|developer|dev)\b", r"\bswe\b", r"\bsde\b",
        r"\bsoftware engineering\b", r"\bprogrammer\b"
    ],
    "Backend Engineer": [
        r"\bback[\s-]?end\b", r"\bapi (engineer|developer)\b", r"\bserver engineer\b",
        r"\bgolang\b", r"\bgo (engineer|developer)\b", r"\bjava (engineer|developer)\b",
        r"\bdjango\b", r"\bflask\b", r"\bfastapi\b", r"\bspring boot\b"
    ],
    "Python Developer": [r"\bpython\b"],
    "AI Engineer": [r"\b(?:applied )?ai\b", r"\bartificial intelligence\b"],
    "Machine Learning Engineer": [r"\bmachine learning\b", r"\bml engineer\b"],
    "Python/AI Engineer": [
        r"\bpython\b", r"\bai (engineer|developer)\b", r"\bmachine learning\b",
        r"\bml (engineer|developer)\b", r"\bdata scientist\b", r"\bdata science\b",
        r"\bllm\b", r"\bartificial intelligence\b", r"\bdeep learning\b", r"\bnlp\b",
        r"\bcomputer vision\b", r"\bgen(erative)?\s?ai\b"
    ],
    "DevOps Engineer": [
        r"\bdevops\b", r"\bsre\b", r"\bcloud (engineer|architect)\b",
        r"\binfrastructure\b", r"\bplatform engineer\b", r"\bsite reliability\b",
        r"\bkubernetes\b", r"\bci/cd\b"
    ],
    "Android Developer": [
        r"\bandroid\b", r"\bkotlin (developer|engineer)\b", r"\bmobile (engineer|developer)\b"
    ],
}

DELHI_NCR_KEYWORDS = ["delhi", "new delhi", "noida", "greater noida", "gurgaon", "gurugram", "ncr", "delhi ncr"]
INDIA_OTHER_KEYWORDS = [
    "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "chennai", "kolkata",
    "ahmedabad", "jaipur", "chandigarh", "indore", "kochi", "cochin", "kerala",
    "karnataka", "maharashtra", "tamil nadu", "telangana", "india", "remote india",
]
OUTSIDE_INDIA_RESTRICTION_PATTERNS = [
    re.compile(r"\b(us|usa|united states|north america|canada|uk|united kingdom|germany|eu|europe|emea|latin america|latam|australia)\s+(only|citizens?|residents?|based)\b", re.IGNORECASE),
    re.compile(r"must (reside|be located|live) in (the\s+)?(us|usa|united states|uk|canada|germany|europe|north america)", re.IGNORECASE),
    re.compile(r"requires? (us|eu|uk|canada) work authorization", re.IGNORECASE),
    re.compile(r"only candidates (in|from) (the\s+)?(us|usa|europe|germany|uk|canada)", re.IGNORECASE),
    re.compile(r"(us|eu|uk|germany|canada) applicants only", re.IGNORECASE),
    re.compile(r"authorized to work in (the\s+)?(us|usa|germany|uk|canada|eu)", re.IGNORECASE),
]
OUTSIDE_INDIA_WORLDWIDE_KEYWORDS = [
    "worldwide", "anywhere in the world", "open to candidates worldwide", "global remote",
    "hire anywhere", "remote (worldwide)", "remote worldwide", "work from anywhere", "anywhere",
]

INTERN_PATTERN = re.compile(
    r"\b(intern|interns|internship|internships|trainee|trainees|working student|werkstudent|werkstudenten|apprentice|apprenticeship|fellow|fellowship)\b",
    re.IGNORECASE,
)
SENIOR_PATTERN = re.compile(
    r"\b(senior|sr\.?|lead|staff|principal|director|head of|vp|manager|architect|chief)\b",
    re.IGNORECASE,
)

def is_internship(job: dict) -> bool:
    """
    Verify if listing is genuinely an internship, trainee, or apprentice position.
    Strictly excludes senior, lead, staff, principal, director, manager, or regular full-time positions.
    """
    title = (job.get("title") or "").strip()
    if not title:
        return False
    if SENIOR_PATTERN.search(title):
        return False
    return bool(INTERN_PATTERN.search(title))

NON_TECH_TITLES = [
    "sales", "recruiter", "talent acquisition", "copywriter", "writer", "accountant",
    "office assistant", "executive assistant", "art director", "marketing manager",
    "content reviewer", "customer support", "support specialist", "operations manager"
]


def detect_work_mode(job: dict) -> str:
    explicit = str(job.get("source_work_mode") or job.get("work_mode") or "").lower().replace("-", "")
    if explicit in ("remote", "hybrid", "onsite"): return {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}[explicit]
    loc_title = f"{job.get('location', '')} {job.get('title', '')}".lower()
    desc = (job.get("description") or "").lower()
    if re.search(r"hybrid|days (?:a week )?in office", loc_title + " " + desc): return "Hybrid"
    if re.search(r"on[ -]?site|office[ -]based", loc_title + " " + desc): return "On-site"
    if job.get("source") == "Remotive" or re.search(r"remote|worldwide|anywhere", loc_title): return "Remote"
    if re.search(r"100% remote|work from home|(?:role|position|internship) is (?:fully )?remote", desc): return "Remote"
    return "unknown"

def detect_location_category(location: str, description: str = "") -> str:
    """Categorize location into Delhi NCR, other Indian cities, outside India, or unknown."""
    loc_low = (location or "").lower().strip()
    if not loc_low or loc_low in ["unknown", "not set", "n/a"]:
        return "unknown"
    if any(k in loc_low for k in DELHI_NCR_KEYWORDS):
        return "Delhi, Noida, Gurugram"
    if any(k in loc_low for k in INDIA_OTHER_KEYWORDS):
        return "Outside Delhi NCR / other Indian cities"
    return "Outside India"

def detect_eligibility(job: dict, loc_cat: str) -> tuple[str, str]:
    """
    Determine India applicant eligibility:
    - Jobs in India: 'eligible'
    - International remote: 'eligible' if explicitly open to India/worldwide;
      'ineligible' if restricted to applicants outside India;
      otherwise 'unknown' (never assume international remote accepts Indian applicants).
    """
    loc = (job.get("location") or "")
    desc = (job.get("description") or "")
    title = (job.get("title") or "")
    comb = f"{loc} {title} {desc}".lower()
    loc_low = loc.lower().strip()

    # Explicit country restrictions excluding India
    for p in OUTSIDE_INDIA_RESTRICTION_PATTERNS:
        if p.search(comb) or p.search(loc):
            return "ineligible", "Ineligible: Restricted to applicants outside India"

    for r in ["usa only", "us only", "europe only", "uk only", "canada only", "germany only", "emea only", "latam only"]:
        if loc_low == r or loc_low.startswith(r + " ") or loc_low.endswith(" " + r) or f"({r})" in loc_low:
            return "ineligible", f"Ineligible: Restricted to {r.upper()}"

    region = str(job.get('eligible_region') or '').lower()
    if region and not re.search(r'\bindia\b|worldwide|anywhere|global',region) and re.search(r'\bus\b|\busa\b|united states|europe|\beu\b|\buk\b|united kingdom|canada|germany|emea|latam|australia',region):
        return "ineligible", "Restricted: source applicant region excludes India"
    countries = job.get("eligible_countries")
    if isinstance(countries, list) and countries:
        allowed = {str(x).lower() for x in countries}
        if not allowed.intersection({"india", "in", "ind", "worldwide"}):
            return "ineligible", "Restricted: explicit eligible countries exclude India"
        return "eligible", "Explicit eligible countries include India"
    if re.search(r"(?:not|except|excluding|outside) india|india (?:excluded|not eligible)", comb):
        return "ineligible", "Restricted: applicants residing in India excluded"
    if loc_cat in ["Delhi, Noida, Gurugram", "Outside Delhi NCR / other Indian cities"]:
        return "eligible", "Based in India / Open to Indian candidates"
    if re.search(r"(?:open to|accepting|eligible) (?:candidates|applicants) (?:in|from) india", comb):
        return "eligible", "Explicitly open to India"
    if job.get('source') == 'Jobicy' and region == 'anywhere':
        return 'unknown', 'Eligibility unknown: source uses Anywhere when no region is specified'
    # Explicit global / worldwide / India eligibility
    if any(w in loc_low for w in OUTSIDE_INDIA_WORLDWIDE_KEYWORDS) or any(w in comb for w in ["open to candidates worldwide", "work from anywhere in the world", "hire anywhere in the world"]):
        return "eligible", "Eligible: Explicitly open to candidates worldwide / India"

    # Otherwise: international remote / outside India without explicit India confirmation
    return "unknown", "Eligibility unknown: International listing does not confirm applicants in India are accepted"

def match_roles(job: dict, preferred_roles: list[str]) -> list[str]:
    """Match job title and description against preferred roles list."""
    title = job.get("title") or ""
    desc = job.get("description") or ""
    title_low = title.lower()
    desc_low = desc.lower()

    # Exclude obvious non-tech titles unless tech keywords present
    if any(nt in title_low for nt in NON_TECH_TITLES) and not any(k in title_low for k in ["engineer", "developer", "software", "tech", "programmer"]):
        return []

    matched = []
    for role in preferred_roles:
        patterns = ROLE_PATTERNS.get(role)
        if patterns:
            # Check title first
            if any(re.search(pat, title_low) for pat in patterns):
                matched.append(role)
            # If title is generic developer/intern, check description
            elif any(t in title_low for t in ["developer", "engineer", "software", "technical"]):
                if any(re.search(pat, desc_low) for pat in patterns) and re.search(r"build|develop|implement|design|maintain|deploy", desc_low):
                    matched.append(role)
        else:
            # Custom user role
            role_kw = role.lower()
            if role_kw in title_low or (any(t in title_low for t in ["intern", "developer", "engineer"]) and role_kw in desc_low):
                matched.append(role)
    return matched

def evaluate_job(job: dict, prefs: dict = None) -> dict:
    from .normalization import valid_url, job_type, parse_date
    from datetime import datetime, timezone
    prefs = {**DEFAULT_PREFERENCES, **(prefs or {})}
    mode = detect_work_mode(job)
    category = detect_location_category(job.get("location", ""))
    eligibility, why = detect_eligibility(job, category)
    roles = match_roles(job, prefs["preferred_roles"])
    kind = job.get("job_type") or job_type(job)
    hard, review, reasons = [], [], []
    if not roles: hard.append("Irrelevant role: Does not match preferred roles; incidental keywords are insufficient")
    else: reasons.append("Role match: " + ", ".join(roles))
    title_roles = match_roles({**job, 'description':''}, prefs['preferred_roles'])
    role_strength = 'strong' if title_roles else 'partial' if roles else 'irrelevant'
    if roles: reasons.append('Title matches ' + ', '.join(title_roles) if title_roles else 'Responsibilities support preferred role; partial match')
    if kind not in ('internship', 'unknown'): hard.append("Excluded: not an internship (" + kind + ")")
    elif kind == 'unknown':
        if not is_internship(job) and not re.search(r"intern|trainee|apprentice|student|fellow", job.get('title',''), re.I):
            hard.append("Excluded: not an internship; job type unverified")
        else: review.append("internship classification")
    else: reasons.append("Internship classification supported")
    if eligibility == "ineligible": hard.append(why)
    if mode in ('On-site', 'Hybrid') and category != 'Delhi, Noida, Gurugram':
        hard.append(f"Rule violation: {mode} outside Delhi NCR (remote only acceptable)")
    if mode != 'unknown' and mode not in prefs['work_modes']: hard.append("Work mode not selected in preferences")
    selected = prefs['preferred_locations']
    loc = (job.get('location') or '').lower()
    if category == 'Delhi, Noida, Gurugram':
        cities = [(r'noida', 'Noida'), (r'gurgaon|gurugram', 'Gurugram/Gurgaon'), (r'delhi', 'Delhi')]
        found = [name for pattern,name in cities if re.search(pattern,loc)]
        if found and not any(name in selected for name in found): hard.append("Location not selected in preferences")
        elif not found and not any(name in selected for _,name in cities): hard.append("Location not selected in preferences")
    elif category != 'unknown' and category not in selected: hard.append("Location not selected in preferences")
    pay = job.get('pay_status') or 'unknown'
    if pay == 'unpaid': hard.append("Unpaid: excluded by salary preference")
    elif pay == 'paid': reasons.append("Confirmed paid compensation")
    elif prefs['salary_preference'] != 'exclude_unpaid': review.append("salary / compensation")
    if job.get('compensation_confidence') == 'conflicting': review.append('conflicting compensation evidence')
    if mode == 'unknown': review.append('work mode')
    if category == 'unknown': review.append('location')
    if eligibility == 'unknown': review.append('country eligibility')
    if 'url' in job and not valid_url(job.get('url')): review.append('valid original listing URL')
    if 'application_url' in job and not valid_url(job.get('application_url')): review.append('valid application URL')
    if 'company' in job and not (job.get('company') or '').strip(): review.append('company')
    if job.get('description_truncated'): review.append('description exceeds safety ceiling')
    if job.get('duplicate_candidates'): review.append('possible duplicate vacancy')
    if job.get('availability') == 'possibly_unavailable': review.append('listing absent from latest complete source response')
    now = datetime.now(timezone.utc)
    deadline = parse_date(job.get('deadline'))
    if job.get('availability') in ('confirmed_closed', 'expired') or (deadline and datetime.fromisoformat(deadline) < now): hard.append('Listing closed or expired')
    pub = parse_date(job.get('publication_date'))
    age = (now - datetime.fromisoformat(pub)).days if pub else None
    if age is not None and age < 0: review.append('future publication date')
    if prefs['freshness_days'] and (age is None or age > prefs['freshness_days']): review.append('publication freshness')
    weights = {**DEFAULT_PREFERENCES['ranking_weights'], **prefs.get('ranking_weights', {})}
    skills = [x for x in ('react','node','python','java','sql','docker','kubernetes','android') if re.search(r'\b'+x+r'\b', (job.get('description') or '').lower())]
    components = {
        'role': weights['role'] * (1 if prefs['primary_role'] in roles else .8 if roles else 0),
        'skills': weights['skills'] * min(len(skills)/3, 1) if roles else 0,
        'internship': weights['internship'] if kind == 'internship' else 0,
        'location': weights['location'] if eligibility == 'eligible' and mode != 'unknown' and not hard else 0,
        'compensation': weights['compensation'] if pay == 'paid' else weights['compensation'] * .1 if pay == 'unknown' else 0,
        'freshness': weights['freshness'] if age is not None and 0 <= age <= 30 else 0,
        'availability': weights['availability'] if job.get('availability') == 'active' else 0,
        'completeness': weights['completeness'] if all(job.get(x) for x in ('title','company','description','location','url')) else 0,
    }
    score = round(100 * sum(components.values()) / max(1, sum(weights.values())))
    if roles and score < prefs['minimum_score']: review.append('minimum match score')
    section = 'other' if hard else 'needs_review' if review else 'best_matches'
    reasons += ['Eligibility: ' + why] + hard
    if review: reasons.append('Needs review: Missing/ambiguous ' + ', '.join(review))
    return dict(section=section, work_mode=mode, eligibility=eligibility, location_category=category,
                score=score, reasons=reasons, job_type=kind, matched_roles=roles, score_components=components,
                decision={'other':'ineligible','needs_review':'review_required','best_matches':'eligible'}[section],
                exclusion_reasons=hard, review_reasons=review, role_strength=role_strength, classification_version='2')
