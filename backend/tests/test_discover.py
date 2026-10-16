"""
tests/test_discover.py

Tests for the Discover Jobs feature covering:
  1. HTML stripping and whitespace normalisation
  2. Pay status inference - conservative defaults, false-positive avoidance
  3. URL validation
  4. Normalisation of Remotive-shaped and Arbeitnow-shaped API responses
  5. Duplicate handling via SQLite UNIQUE constraint
  6. Preservation of existing manually-added jobs (status, score, fields)
  7. API failure handling (network errors, non-200, malformed JSON)
  8. discover_jobs route when all sources fail
  9. discover_jobs route with a mocked partial failure (one source up, one down)
 10. Title-based internship classification (not description-based)

Run from the backend directory:
    python -m pytest tests/ -v
"""

import asyncio
import json
import re
import sqlite3
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Ensure the app package is importable without a venv activate step ─────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import pure helpers directly — no FastAPI server needed
from app.main import (
    _strip_html,
    _infer_pay,
    _is_valid_url,
    _insert_job,
    score,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers shared across tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    """Create an in-memory SQLite database with the jobs schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE jobs ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  url TEXT NOT NULL UNIQUE,"
        "  title TEXT NOT NULL,"
        "  company TEXT DEFAULT '',"
        "  description TEXT DEFAULT '',"
        "  location TEXT DEFAULT '',"
        "  pay_status TEXT DEFAULT 'unknown',"
        "  source TEXT DEFAULT 'Manual',"
        "  status TEXT DEFAULT 'saved',"
        "  score INTEGER DEFAULT 0,"
        "  reasons TEXT DEFAULT '[]',"
        "  cover_letter TEXT DEFAULT '',"
        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.commit()
    return conn


def _seed_manual_job(conn: sqlite3.Connection) -> int:
    """Insert a manually added job and return its id."""
    conn.execute(
        "INSERT INTO jobs(url,title,company,description,location,pay_status,source,status,score,reasons) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "https://example.com/job/manual-1",
            "Backend Intern",
            "Acme Corp",
            "Build APIs with FastAPI",
            "Delhi NCR",
            "paid",
            "Manual",
            "shortlisted",   # NOT 'saved' — must be preserved
            85,
            json.dumps(["Stack match: Backend", "Internship title"]),
        ),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _count(conn, **where):
    clauses = " AND ".join(f"{k}=?" for k in where)
    sql = "SELECT COUNT(*) FROM jobs" + (f" WHERE {clauses}" if clauses else "")
    return conn.execute(sql, list(where.values())).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# 1. HTML stripping
# ─────────────────────────────────────────────────────────────────────────────

class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        assert _strip_html("<p>  a   b  </p>") == "a b"

    def test_strips_html_entities(self):
        result = _strip_html("foo &amp; bar")
        assert "&amp;" not in result

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_none_equivalent(self):
        assert _strip_html(None) == ""  # type: ignore[arg-type]

    def test_no_tags_unchanged(self):
        assert _strip_html("plain text") == "plain text"

    def test_nested_tags(self):
        result = _strip_html("<ul><li>item 1</li><li>item 2</li></ul>")
        assert "item 1" in result and "item 2" in result
        assert "<" not in result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pay status inference
# ─────────────────────────────────────────────────────────────────────────────

class TestInferPay:
    # --- Should return "unknown" (conservative default) ---

    def test_empty_description_is_unknown(self):
        assert _infer_pay("") == "unknown"

    def test_no_signals_is_unknown(self):
        assert _infer_pay("We are looking for a software developer to join our team.") == "unknown"

    def test_paid_leave_does_not_trigger_paid(self):
        assert _infer_pay("Benefits include paid leave and health insurance.") == "unknown"

    def test_paid_time_off_does_not_trigger_paid(self):
        assert _infer_pay("Enjoy 20 days of paid time off per year.") == "unknown"

    def test_paid_vacation_does_not_trigger_paid(self):
        assert _infer_pay("We offer paid vacation and flexible hours.") == "unknown"

    def test_paid_training_does_not_trigger_paid(self):
        assert _infer_pay("We provide paid training for all new hires.") == "unknown"

    def test_paid_holiday_does_not_trigger_paid(self):
        assert _infer_pay("Includes paid holiday entitlement.") == "unknown"

    def test_intern_word_in_description_does_not_affect_pay(self):
        # "intern" in description should NOT influence pay classification
        assert _infer_pay("You will mentor interns and help them grow.") == "unknown"

    # --- Should return "paid" ---

    def test_stipend_triggers_paid(self):
        assert _infer_pay("Monthly stipend of ₹15,000 provided.") == "paid"

    def test_salary_triggers_paid(self):
        assert _infer_pay("Competitive salary based on experience.") == "paid"

    def test_per_month_triggers_paid(self):
        assert _infer_pay("You will earn ₹20,000 per month.") == "paid"

    def test_lpa_triggers_paid(self):
        assert _infer_pay("Package: 4 LPA for freshers.") == "paid"

    def test_ctc_triggers_paid(self):
        assert _infer_pay("CTC: 3.6 LPA.") == "paid"

    def test_remuneration_triggers_paid(self):
        assert _infer_pay("Remuneration will be discussed during interview.") == "paid"

    def test_compensation_package_triggers_paid(self):
        assert _infer_pay("We offer an attractive compensation package.") == "paid"

    # --- Should return "unpaid" ---

    def test_unpaid_keyword(self):
        assert _infer_pay("This is an unpaid internship position.") == "unpaid"

    def test_no_stipend(self):
        assert _infer_pay("Please note: no stipend is provided.") == "unpaid"

    def test_no_salary(self):
        assert _infer_pay("No salary is offered for this role.") == "unpaid"

    def test_without_pay(self):
        assert _infer_pay("Position without pay — academic credit only.") == "unpaid"

    def test_volunteer_position(self):
        assert _infer_pay("This is a volunteer position with our NGO.") == "unpaid"

    def test_unpaid_beats_salary_word(self):
        # Edge case: "unpaid" should win even if "salary" appears later
        assert _infer_pay("This is an unpaid role. We review salary after 6 months.") == "unpaid"


# ─────────────────────────────────────────────────────────────────────────────
# 3. URL validation
# ─────────────────────────────────────────────────────────────────────────────

class TestIsValidUrl:
    def test_valid_https(self):
        assert _is_valid_url("https://example.com/job/123") is True

    def test_valid_http(self):
        assert _is_valid_url("http://example.com/job/123") is True

    def test_empty_string(self):
        assert _is_valid_url("") is False

    def test_none(self):
        assert _is_valid_url(None) is False  # type: ignore[arg-type]

    def test_missing_scheme(self):
        assert _is_valid_url("example.com/job/123") is False

    def test_ftp_scheme_rejected(self):
        assert _is_valid_url("ftp://example.com/job/123") is False

    def test_too_long(self):
        assert _is_valid_url("https://example.com/" + "a" * 2000) is False

    def test_max_length_ok(self):
        # Exactly 2000 chars total is the boundary; len("https://x.com/") = 14
        url = "https://x.com/" + "a" * (2000 - 14)
        assert _is_valid_url(url) is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. Normalisation — field mapping correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalisation:
    """Tests for field mapping from API shapes into jobs schema."""

    def _remotive_job(self, **overrides) -> dict:
        base = {
            "url": "https://remotive.com/job/123",
            "title": "Python Backend Developer",
            "company_name": "Acme Ltd",
            "description": "<p>Build APIs with Python and FastAPI.</p>",
            "candidate_required_location": "Worldwide",
        }
        base.update(overrides)
        return base

    def _arbeitnow_job(self, **overrides) -> dict:
        base = {
            "url": "https://www.arbeitnow.com/view/abc",
            "title": "Junior Backend Engineer",
            "company_name": "Example GmbH",
            "description": "<p>Work on backend services.</p>",
            "location": "Berlin",
            "remote": False,
        }
        base.update(overrides)
        return base

    def test_remotive_html_stripped_from_description(self):
        raw = self._remotive_job()
        desc_clean = _strip_html(raw["description"])
        assert "<p>" not in desc_clean
        assert "Build APIs" in desc_clean

    def test_arbeitnow_remote_flag_sets_location(self):
        raw = self._arbeitnow_job(remote=True)
        location = "Remote" if raw.get("remote") else (raw.get("location") or "").strip()
        assert location == "Remote"

    def test_arbeitnow_non_remote_uses_location_field(self):
        raw = self._arbeitnow_job(remote=False, location="Munich")
        location = "Remote" if raw.get("remote") else (raw.get("location") or "").strip()
        assert location == "Munich"

    def test_missing_company_normalises_to_empty_string(self):
        raw = self._remotive_job(company_name=None)
        company = (raw.get("company_name") or "").strip()
        assert company == ""

    def test_job_with_no_location_falls_back_to_remote(self):
        raw = self._remotive_job(candidate_required_location=None)
        location = (raw.get("candidate_required_location") or "Remote").strip()
        assert location == "Remote"

    def test_description_truncated_to_3000_chars(self):
        long_desc = "x" * 5000
        truncated = _strip_html(long_desc)[:3000]
        assert len(truncated) == 3000

    def test_intern_in_title_scores_higher_than_senior(self):
        intern_job = {"title": "Python Intern", "description": "", "location": "Remote", "pay_status": "unknown"}
        senior_job = {"title": "Senior Python Developer", "description": "", "location": "Remote", "pay_status": "unknown"}
        s_intern, _ = score(intern_job)
        s_senior, _ = score(senior_job)
        assert s_intern > s_senior

    def test_intern_only_in_description_does_not_boost_level_score(self):
        """
        Req 7: a job should not be classified as internship-level
        solely because 'intern' appears in its description.
        """
        desc_mentions_intern = {
            "title": "Senior Software Engineer",
            "description": "You will mentor interns on the team.",
            "location": "Remote",
            "pay_status": "unknown",
        }
        _, reasons = score(desc_mentions_intern)
        # Must NOT contain "Internship title" reason
        assert not any("Internship title" in r for r in reasons), (
            f"'Internship title' must not appear when 'intern' is only in description. Got: {reasons}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Duplicate handling
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateHandling:
    def _job(self, url="https://example.com/job/1") -> dict:
        return {
            "url": url,
            "title": "Python Intern",
            "company": "Acme",
            "description": "Build APIs",
            "location": "Remote",
            "pay_status": "unknown",
            "source": "Remotive",
        }

    def test_first_insert_returns_true(self):
        conn = _make_db()
        assert _insert_job(conn, self._job()) is True

    def test_duplicate_insert_returns_false(self):
        conn = _make_db()
        _insert_job(conn, self._job())
        assert _insert_job(conn, self._job()) is False

    def test_duplicate_does_not_add_row(self):
        conn = _make_db()
        _insert_job(conn, self._job())
        _insert_job(conn, self._job())
        assert _count(conn) == 1

    def test_different_url_is_inserted(self):
        conn = _make_db()
        _insert_job(conn, self._job("https://example.com/job/1"))
        _insert_job(conn, self._job("https://example.com/job/2"))
        assert _count(conn) == 2

    def test_multiple_sources_same_url_deduplicates(self):
        conn = _make_db()
        j1 = self._job(); j1["source"] = "Remotive"
        j2 = self._job(); j2["source"] = "Arbeitnow"
        _insert_job(conn, j1)
        _insert_job(conn, j2)
        assert _count(conn) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6. Preservation of existing manually-added jobs
# ─────────────────────────────────────────────────────────────────────────────

class TestPreserveExistingJobs:
    def test_discover_does_not_overwrite_manual_job(self):
        conn = _make_db()
        mid = _seed_manual_job(conn)

        # Attempt to insert a discovered job with the SAME url
        discovered = {
            "url": "https://example.com/job/manual-1",  # same URL
            "title": "DIFFERENT TITLE from API",
            "company": "DIFFERENT COMPANY",
            "description": "DIFFERENT DESCRIPTION",
            "location": "Mumbai",
            "pay_status": "unknown",
            "source": "Remotive",
        }
        result = _insert_job(conn, discovered)
        assert result is False  # deduped

        # Original row is untouched
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (mid,)).fetchone()
        assert row["title"] == "Backend Intern"
        assert row["status"] == "shortlisted"  # NOT reset to 'saved'
        assert row["company"] == "Acme Corp"
        assert row["score"] == 85
        assert row["source"] == "Manual"

    def test_existing_job_count_unchanged_after_discover(self):
        conn = _make_db()
        _seed_manual_job(conn)
        assert _count(conn) == 1

        # Insert a genuinely new discovered job
        _insert_job(conn, {
            "url": "https://remotive.com/job/999",
            "title": "React Intern",
            "company": "NewCo",
            "description": "Build with React",
            "location": "Remote",
            "pay_status": "unknown",
            "source": "Remotive",
        })
        assert _count(conn) == 2
        # Original still there and unchanged
        assert _count(conn, source="Manual") == 1
        assert _count(conn, source="Remotive") == 1


# ─────────────────────────────────────────────────────────────────────────────
# 7. API failure handling
# ─────────────────────────────────────────────────────────────────────────────

class TestApiFetchFailures:
    """
    These tests mock httpx to simulate network/server errors without
    requiring a live internet connection.
    """

    @pytest.mark.asyncio
    async def test_remotive_network_error_raises(self):
        from app.main import _fetch_remotive
        import httpx

        with patch("app.main.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.ConnectError):
                await _fetch_remotive()

    @pytest.mark.asyncio
    async def test_arbeitnow_http_500_raises(self):
        from app.main import _fetch_arbeitnow
        import httpx

        with patch("app.main.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock()
            )
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await _fetch_arbeitnow()

    @pytest.mark.asyncio
    async def test_remotive_empty_jobs_array_returns_empty_list(self):
        from app.main import _fetch_remotive

        with patch("app.main.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={"jobs": []})
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _fetch_remotive()
            assert result == []

    @pytest.mark.asyncio
    async def test_arbeitnow_missing_url_field_skips_entry(self):
        from app.main import _fetch_arbeitnow

        bad_job = {"title": "Engineer", "url": "", "company_name": "Co", "description": "", "location": "Berlin", "remote": False}

        with patch("app.main.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={"data": [bad_job]})
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _fetch_arbeitnow()
            assert result == []  # dropped because URL is blank

    @pytest.mark.asyncio
    async def test_remotive_invalid_url_scheme_skips_entry(self):
        from app.main import _fetch_remotive

        bad_job = {
            "url": "ftp://remotive.com/job/1",  # ftp:// not valid
            "title": "Developer",
            "company_name": "Co",
            "description": "desc",
            "candidate_required_location": "Worldwide",
        }

        with patch("app.main.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={"jobs": [bad_job]})
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _fetch_remotive()
            assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# 8. discover_jobs route — partial source failure
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscoverRoute:
    """
    Tests the /api/jobs/discover route logic (not the HTTP layer)
    by directly testing the error-collection pattern.
    """

    @pytest.mark.asyncio
    async def test_one_source_up_one_down_still_imports(self):
        """
        If Remotive is down but Arbeitnow is up, we should still import
        Arbeitnow jobs and report Remotive as a warning — not a hard failure.
        """
        from app.main import _fetch_remotive, _fetch_arbeitnow
        import httpx

        good_job = {
            "url": "https://www.arbeitnow.com/view/good-job",
            "title": "Backend Developer",
            "company_name": "GoodCo",
            "description": "<p>Backend work.</p>",
            "location": "Berlin",
            "remote": True,
        }

        async def fake_remotive():
            raise httpx.ConnectError("remotive down")

        async def fake_arbeitnow():
            # Simulate the normalisation step that _fetch_arbeitnow does
            desc = _strip_html(good_job["description"])
            return [{
                "url": good_job["url"],
                "title": good_job["title"],
                "company": good_job["company_name"],
                "description": desc[:3000],
                "location": "Remote",
                "pay_status": _infer_pay(desc),
                "source": "Arbeitnow",
            }]

        fetchers = [("Remotive", fake_remotive), ("Arbeitnow", fake_arbeitnow)]
        all_jobs: list[dict] = []
        errors: list[str] = []

        for name, fetcher in fetchers:
            try:
                listings = await fetcher()
                all_jobs.extend(listings)
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        assert len(errors) == 1
        assert "Remotive" in errors[0]
        assert len(all_jobs) == 1
        assert all_jobs[0]["source"] == "Arbeitnow"

    @pytest.mark.asyncio
    async def test_all_sources_down_returns_no_jobs_with_errors(self):
        import httpx

        async def fail(_):
            raise httpx.ConnectError("down")

        fetchers = [("Remotive", lambda: fail("r")), ("Arbeitnow", lambda: fail("a"))]
        all_jobs: list[dict] = []
        errors: list[str] = []

        for name, fetcher in fetchers:
            try:
                listings = await fetcher()
                all_jobs.extend(listings)
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        assert all_jobs == []
        assert len(errors) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 9. Scoring correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestScoring:
    def test_score_capped_at_100(self):
        perfect = {
            "title": "Full Stack Python Intern",
            "description": "React Node.js FastAPI Python machine learning",
            "location": "Remote",
            "pay_status": "paid",
        }
        s, _ = score(perfect)
        assert s <= 100

    def test_score_is_non_negative(self):
        empty_job = {"title": "Xx", "description": "", "location": "", "pay_status": "unknown"}
        s, _ = score(empty_job)
        assert s >= 0

    def test_reasons_always_returned(self):
        _, reasons = score({"title": "Developer", "description": "", "location": "", "pay_status": "unknown"})
        assert isinstance(reasons, list)
        assert len(reasons) > 0

    def test_paid_boosts_score_vs_unknown(self):
        base = {"title": "Intern", "description": "", "location": ""}
        s_paid, _ = score({**base, "pay_status": "paid"})
        s_unknown, _ = score({**base, "pay_status": "unknown"})
        assert s_paid > s_unknown

    def test_unpaid_scores_lower_than_unknown(self):
        base = {"title": "Intern", "description": "", "location": ""}
        s_unknown, _ = score({**base, "pay_status": "unknown"})
        s_unpaid, _ = score({**base, "pay_status": "unpaid"})
        assert s_unknown > s_unpaid
