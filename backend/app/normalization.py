"""Conservative, deterministic normalization. Missing evidence stays missing."""
import html
import ipaddress
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
        if tag in ('p', 'br', 'li', 'div', 'h2', 'h3'): self.parts.append('\n')
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if valid_url(href): self.parts.append(' ' + href + ' ')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'li', 'div'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def clean_html(value):
    parser = TextParser()
    parser.feed(html.unescape(html.unescape(str(value or ''))))
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def valid_url(value):
    try:
        u = urlsplit(str(value or ''))
        if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password or len(value) > 2000:
            return False
        host = u.hostname.lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')): return False
        try: return ipaddress.ip_address(host).is_global
        except ValueError: return '.' in host and not any(c.isspace() for c in host)
    except (ValueError, TypeError): return False


def canonical_url(value):
    if not valid_url(value): return ''
    u = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip('/') or '/', urlencode(sorted(query)), ''))


def parse_date(value):
    if value is None or value == '': return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        else: dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError): return None


def compensation(text):
    text = clean_html(text)
    filtered = re.sub(r'paid\s+(?:time\s+off|leave|vacation|holidays?|training|courses?)', '', text, flags=re.I)
    unpaid = bool(re.search(r'\bunpaid\b|\bno (?:stipend|salary|pay)\b|without pay|volunteer position', filtered, re.I))
    positive = re.sub(r'\bno (?:stipend|salary|pay)\b', '', filtered, flags=re.I)
    paid = bool(re.search(r'\bpaid internship\b|\b(?:stipend|salary|hourly wage|remuneration)\s*(?:of|:|is|will be|provided|offered|[₹$€£\d])|\b(?:competitive|monthly|annual|hourly)\s+(?:salary|stipend|wage)\b|(?:INR|USD|EUR|GBP|₹|\$|€|£)\s*[\d,]+(?:\.\d+)?\s*(?:k\b|/|per\b)|\d[\d,]*\s*(?:INR|USD|EUR|GBP)\b', positive, re.I))
    evidence = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if re.search(r'stipend|salary|wage|unpaid|compensation|₹|\$|€|£', s, re.I)]
    amount = re.search(r'\b(INR|USD|EUR|GBP)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(INR|USD|EUR|GBP)\b', ' '.join(evidence), re.I)
    number = float((amount.group(2) or amount.group(3)).replace(',', '')) if amount and paid and not unpaid else None
    currency = (amount.group(1) or amount.group(4)).upper() if number is not None else None
    return {'pay_status': 'unknown' if paid == unpaid else ('paid' if paid else 'unpaid'),
            'compensation_confidence': 'conflicting' if paid and unpaid else ('explicit' if paid or unpaid else 'unknown'),
            'compensation_text': ' '.join(evidence), 'compensation_amount': number, 'currency': currency}


def job_type(job):
    title = (job.get('title') or '').lower()
    supplied = re.sub(r'[\s_-]', '', str(job.get('employment_type') or '').lower())
    if re.search(r'\b(senior|staff|principal|director|manager|lead)\b', title): return 'full_time'
    if supplied in ('intern', 'internship'): return 'internship'
    if re.search(r'\bintern(?:ship|s|ships)?\b|\bpraktikum\b', title): return 'internship'
    if re.search(r'new.grad|graduate', title): return 'graduate'
    if supplied in ('contract', 'freelance') or re.search(r'contract|freelance', title): return 'contract'
    if supplied == 'parttime': return 'part_time'
    if supplied == 'fulltime': return 'full_time'
    if re.search(r'trainee|apprentice|fellow|working student|werkstudent', title): return 'unknown'
    return 'unknown'


def normalize(job):
    d = dict(job)
    for key in ('title', 'company', 'location', 'description'):
        d[key] = clean_html(d.get(key))
    d['description_truncated'] = len(d['description']) > 100000
    # Classification operates on all text up to this explicit safety ceiling.
    d['description'] = d['description'][:100000]
    d['url'] = canonical_url(d.get('url', ''))
    d['application_url'] = canonical_url(d.get('application_url') or d['url'])
    inferred = compensation(' '.join([d['description'], str(d.get('compensation_text') or '')]))
    if d.get('source') != 'Manual' or d.get('pay_status', 'unknown') == 'unknown': d.update(inferred)
    else:
        d.setdefault('compensation_confidence', 'user_verified')
        if inferred['compensation_confidence'] == 'conflicting' or (inferred['pay_status'] == 'unpaid' and d['pay_status'] == 'paid'):
            d.update(inferred); d['pay_status'] = 'unknown'; d['compensation_confidence'] = 'conflicting'
    d['job_type'] = job_type(d)
    for key in ('publication_date', 'source_updated_at', 'deadline'): d[key] = parse_date(d.get(key))
    d.setdefault('availability', 'unknown')
    d.setdefault('source', 'Manual')
    d.setdefault('country', None)
    d.setdefault('eligible_countries', None)
    d.setdefault('employer_location', None)
    d.setdefault('relocation_required', None)
    return d
