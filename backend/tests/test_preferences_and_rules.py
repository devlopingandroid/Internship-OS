"""
tests/test_preferences_and_rules.py

Comprehensive tests for:
  1. Location rules (Delhi/Noida/Gurugram vs Other Indian Cities vs Outside India)
  2. Work-mode detection and rules (On-site, Hybrid, Remote)
  3. India applicant eligibility (India-based, Worldwide, restricted non-India, unknown)
  4. Compensation detection and false-positive avoidance
  5. Role matching (primary, additional, custom roles, non-tech exclusions)
  6. Section assignment (Best Matches, Needs Review, Other Jobs)
  7. Preferences persistence and reclassification API
"""

import json
import sqlite3
import pytest
from app.rules import (
    DEFAULT_PREFERENCES,
    detect_work_mode,
    detect_location_category,
    detect_eligibility,
    match_roles,
    evaluate_job,
)
from app.database import (
    connect,
    init_db,
    get_preferences,
    save_preferences,
    reclassify_all_jobs,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Location Rules & Categorization
# ─────────────────────────────────────────────────────────────────────────────

class TestLocationRules:
    @pytest.mark.parametrize("loc", [
        "Delhi", "New Delhi", "Noida", "Greater Noida", "Gurugram", "Gurgaon", "Delhi NCR", "ncr"
    ])
    def test_delhi_ncr_categorization(self, loc):
        cat = detect_location_category(loc)
        assert cat == "Delhi, Noida, Gurugram"

    @pytest.mark.parametrize("loc", [
        "Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Chennai",
        "Kolkata", "Ahmedabad", "Jaipur", "Chandigarh", "India", "Remote India"
    ])
    def test_other_indian_cities_categorization(self, loc):
        cat = detect_location_category(loc)
        assert cat == "Outside Delhi NCR / other Indian cities"

    @pytest.mark.parametrize("loc", [
        "Berlin, Germany", "Munich", "London, UK", "New York, USA", "San Francisco",
        "Toronto, Canada", "Worldwide", "Europe", "Global"
    ])
    def test_outside_india_categorization(self, loc):
        cat = detect_location_category(loc)
        assert cat == "Outside India"

    def test_unknown_location(self):
        assert detect_location_category("") == "unknown"
        assert detect_location_category("not set") == "unknown"
        assert detect_location_category("n/a") == "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Work-Mode Rules & Detection
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkModeRules:
    def test_delhi_ncr_allows_onsite_hybrid_and_remote(self):
        for mode, loc in [("On-site", "Delhi"), ("Hybrid", "Noida"), ("Remote", "Gurugram")]:
            job = {
                "title": "Full Stack Intern",
                "location": f"{loc} ({mode})",
                "description": f"This is an {mode.lower()} position in {loc}.",
                "pay_status": "paid",
            }
            ev = evaluate_job(job, DEFAULT_PREFERENCES)
            assert ev["section"] == "best_matches", f"Failed for {mode} in {loc}"

    def test_other_indian_cities_allows_remote_only(self):
        # Remote in Bengaluru -> Best Match
        remote_job = {
            "title": "Full Stack Intern",
            "location": "Bengaluru (Remote)",
            "description": "100% remote work from home.",
            "pay_status": "paid",
        }
        ev_remote = evaluate_job(remote_job, DEFAULT_PREFERENCES)
        assert ev_remote["section"] == "best_matches"

        # On-site in Bengaluru -> Rule violation -> Other Jobs
        onsite_job = {
            "title": "Full Stack Intern",
            "location": "Bengaluru",
            "description": "Work from our Bangalore office on-site.",
            "pay_status": "paid",
        }
        ev_onsite = evaluate_job(onsite_job, DEFAULT_PREFERENCES)
        assert ev_onsite["section"] == "other"
        assert any("remote only acceptable" in r for r in ev_onsite["reasons"])

        # Hybrid in Pune -> Rule violation -> Other Jobs
        hybrid_job = {
            "title": "Full Stack Intern",
            "location": "Pune",
            "description": "Hybrid model with 3 days in office.",
            "pay_status": "paid",
        }
        ev_hybrid = evaluate_job(hybrid_job, DEFAULT_PREFERENCES)
        assert ev_hybrid["section"] == "other"
        assert any("remote only acceptable" in r for r in ev_hybrid["reasons"])

    def test_outside_india_allows_remote_only(self):
        # On-site in Berlin -> Rule violation -> Other Jobs
        berlin_onsite = {
            "title": "Full Stack Intern",
            "location": "Berlin, Germany",
            "description": "Office based in Berlin.",
            "pay_status": "paid",
        }
        ev = evaluate_job(berlin_onsite, DEFAULT_PREFERENCES)
        assert ev["section"] == "other"
        assert any("remote only acceptable" in r for r in ev["reasons"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. India Applicant Eligibility
# ─────────────────────────────────────────────────────────────────────────────

class TestCountryEligibility:
    def test_india_based_jobs_are_eligible(self):
        job = {"location": "Noida", "title": "Developer", "description": ""}
        status, reason = detect_eligibility(job, "Delhi, Noida, Gurugram")
        assert status == "eligible"

        job2 = {"location": "Bengaluru", "title": "Developer", "description": ""}
        status2, reason2 = detect_eligibility(job2, "Outside Delhi NCR / other Indian cities")
        assert status2 == "eligible"

    def test_explicit_worldwide_remote_is_eligible(self):
        job = {
            "location": "Worldwide",
            "title": "Full Stack Engineer",
            "description": "Open to candidates worldwide. Work from anywhere in the world.",
        }
        status, reason = detect_eligibility(job, "Outside India")
        assert status == "eligible"

    def test_explicit_non_india_restrictions_are_ineligible(self):
        restricted_cases = [
            ("USA Only", "Build software."),
            ("Remote", "Must reside in the US. No visa sponsorship provided."),
            ("Remote", "Only candidates in Europe (EU only)."),
            ("Remote", "Requires US work authorization."),
            ("Germany Only", "Must be located in Germany."),
            ("Remote", "UK applicants only."),
        ]
        for loc, desc in restricted_cases:
            job = {"location": loc, "title": "Software Engineer", "description": desc}
            status, reason = detect_eligibility(job, "Outside India")
            assert status == "ineligible", f"Expected ineligible for loc='{loc}', desc='{desc}'"

    def test_international_remote_without_explicit_india_is_unknown(self):
        # "Never assume that an international remote job accepts applicants living in India.
        # Check eligibility when the listing provides that information; otherwise mark it 'Eligibility unknown'."
        job = {
            "location": "Remote",
            "title": "Full Stack Engineer",
            "description": "Join our distributed engineering team. Competitive compensation.",
        }
        status, reason = detect_eligibility(job, "Outside India")
        assert status == "unknown"
        assert "Eligibility unknown" in reason


# ─────────────────────────────────────────────────────────────────────────────
# 4. Compensation & Salary Preferences
# ─────────────────────────────────────────────────────────────────────────────

class TestCompensationPreferences:
    def test_paid_leave_does_not_trigger_paid(self):
        from app.main import _infer_pay
        desc = "Benefits include 20 days paid leave, paid vacation, and comprehensive health insurance."
        assert _infer_pay(desc) == "unknown"

    def test_paid_only_preference_routes_unknown_to_needs_review(self):
        prefs = {**DEFAULT_PREFERENCES, "salary_preference": "paid_only"}
        job = {
            "title": "Full Stack Intern",
            "location": "Delhi",
            "description": "Exciting internship opportunity building web apps.",
            "pay_status": "unknown",
        }
        ev = evaluate_job(job, prefs)
        assert ev["section"] == "needs_review"
        assert any("salary" in r for r in ev["reasons"])

    def test_paid_only_preference_routes_paid_to_best_matches(self):
        prefs = {**DEFAULT_PREFERENCES, "salary_preference": "paid_only"}
        job = {
            "title": "Full Stack Intern",
            "location": "Delhi",
            "description": "Stipend of 35000 per month.",
            "source_work_mode": "On-site",
            "pay_status": "paid",
        }
        ev = evaluate_job(job, prefs)
        assert ev["section"] == "best_matches"

    def test_exclude_unpaid_routes_unpaid_to_other(self):
        for pref in ["paid_only", "paid_preferred", "exclude_unpaid"]:
            p = {**DEFAULT_PREFERENCES, "salary_preference": pref}
            job = {
                "title": "Full Stack Intern",
                "location": "Delhi",
                "description": "Unpaid volunteer internship.",
                "pay_status": "unpaid",
            }
            ev = evaluate_job(job, p)
            assert ev["section"] == "other"
            assert any("Unpaid" in r for r in ev["reasons"])


# ─────────────────────────────────────────────────────────────────────────────
# 5. Role Matching
# ─────────────────────────────────────────────────────────────────────────────

class TestRoleMatching:
    def test_primary_role_full_stack_matches(self):
        job = {"title": "Junior Full-Stack Developer", "description": "React and Node."}
        matched = match_roles(job, DEFAULT_PREFERENCES["preferred_roles"])
        assert "Full-Stack Engineer" in matched

    def test_additional_roles_match(self):
        roles_to_titles = [
            ("Software Engineer", "Software Engineer Intern"),
            ("Backend Engineer", "Back-End Developer (FastAPI)"),
            ("Python/AI Engineer", "Python & Machine Learning Intern"),
            ("DevOps Engineer", "Cloud & DevOps SRE Intern"),
            ("Android Developer", "Android Developer (Kotlin)"),
        ]
        for role, title in roles_to_titles:
            job = {"title": title, "description": ""}
            matched = match_roles(job, DEFAULT_PREFERENCES["preferred_roles"])
            assert role in matched, f"Expected {role} to match title '{title}'"

    def test_irrelevant_roles_are_excluded(self):
        irrelevant_titles = [
            "Inside Sales Contractor", "Art Director", "Content Reviewer",
            "Freelance Copywriter", "HR Recruiter", "Executive Assistant"
        ]
        for title in irrelevant_titles:
            job = {"title": title, "description": "Join our team."}
            matched = match_roles(job, DEFAULT_PREFERENCES["preferred_roles"])
            assert matched == [], f"Expected '{title}' to match NO preferred roles"

    def test_custom_user_role(self):
        custom_prefs = ["Blockchain Engineer", "Full-Stack Engineer"]
        job = {"title": "Junior Blockchain Engineer", "description": "Solidity and Ethereum."}
        matched = match_roles(job, custom_prefs)
        assert "Blockchain Engineer" in matched


# ─────────────────────────────────────────────────────────────────────────────
# 6. Section Classification
# ─────────────────────────────────────────────────────────────────────────────

class TestSectionClassification:
    def test_best_match_criteria(self):
        # Valid role, valid location, valid work mode, verified eligible, verified paid
        job = {
            "title": "Full-Stack Intern",
            "company": "TechCorp",
            "location": "Delhi NCR",
            "description": "Stipend of 30,000 INR per month.",
            "source_work_mode": "On-site",
            "pay_status": "paid",
        }
        ev = evaluate_job(job, DEFAULT_PREFERENCES)
        assert ev["section"] == "best_matches"

    def test_needs_review_when_international_remote_eligibility_unknown(self):
        # Relevant role, Remote, Paid, but international remote with unverified India eligibility
        job = {
            "title": "Software Engineer Intern",
            "company": "GlobalCo",
            "location": "Remote",
            "description": "Stipend $2000 per month.",
            "pay_status": "paid",
        }
        ev = evaluate_job(job, DEFAULT_PREFERENCES)
        assert ev["section"] == "needs_review"
        assert any("country eligibility" in r for r in ev["reasons"])

    def test_needs_review_when_salary_is_unknown(self):
        # Relevant role, Delhi NCR, on-site, but unknown compensation
        job = {
            "title": "Backend Intern",
            "company": "Startup Hub",
            "location": "Noida",
            "description": "FastAPI APIs.",
            "pay_status": "unknown",
        }
        ev = evaluate_job(job, DEFAULT_PREFERENCES)
        assert ev["section"] == "needs_review"
        assert any("salary" in r for r in ev["reasons"])

    def test_other_when_ineligible_for_india(self):
        job = {
            "title": "Python/AI Engineer Intern",
            "company": "US Corp",
            "location": "Remote",
            "description": "US Only. Must be US citizen. $30/hr.",
            "pay_status": "paid",
        }
        ev = evaluate_job(job, DEFAULT_PREFERENCES)
        assert ev["section"] == "other"
        assert any("Restricted" in r for r in ev["reasons"])


# ─────────────────────────────────────────────────────────────────────────────
# 7. Persistence & Reclassification DB Operations
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabasePersistence:
    def test_preferences_get_and_save(self):
        init_db()
        original = get_preferences()
        assert "preferred_roles" in original
        assert "primary_role" in original

        updated = {
            "primary_role": "Full-Stack Engineer",
            "preferred_roles": ["Full-Stack Engineer", "Python/AI Engineer"],
            "preferred_locations": ["Delhi", "Noida"],
            "work_modes": ["Remote"],
            "salary_preference": "paid_only",
        }
        saved = save_preferences(updated)
        assert saved["salary_preference"] == "paid_only"
        assert saved["work_modes"] == ["Remote"]

        fetched = get_preferences()
        assert fetched["salary_preference"] == "paid_only"
        assert fetched["work_modes"] == ["Remote"]

        # Restore default preferences
        save_preferences(DEFAULT_PREFERENCES)

    def test_reclassify_all_jobs_returns_counts(self):
        init_db()
        counts = reclassify_all_jobs()
        assert "best_matches" in counts
        assert "needs_review" in counts
        assert "other" in counts
        assert counts["total"] >= 0
        assert counts["best_matches"] + counts["needs_review"] + counts["other"] == counts["total"]


# ─────────────────────────────────────────────────────────────────────────────
# 8. Internship-Only Strict Validation
# ─────────────────────────────────────────────────────────────────────────────

class TestInternshipOnlyValidation:
    def test_rejects_senior_and_regular_jobs(self):
        from app.rules import is_internship
        non_interns = [
            "Senior React Full-stack Developer",
            "Director, International Delivery Management",
            "Staff Software Engineer",
            "Lead Backend Engineer",
            "Principal Cloud Architect",
            "Engineering Manager",
            "Internal Tools Developer",
            "Full Stack Developer",  # No intern/trainee keyword
        ]
        for t in non_interns:
            assert is_internship({"title": t}) is False, f"Expected {t} to NOT be an internship"

    def test_accepts_genuine_internships(self):
        from app.rules import is_internship
        genuine_interns = [
            "Full-Stack Engineer Intern",
            "Python/AI Internship",
            "Software Engineering Trainee",
            "Working Student - Fullstack",
            "Werkstudent Softwareentwicklung",
            "AI & Software Engineering Apprentice",
            "Research Fellow - Computer Vision",
        ]
        for t in genuine_interns:
            assert is_internship({"title": t}) is True, f"Expected {t} to be an internship"

    def test_non_internship_is_excluded_from_best_matches(self):
        regular_job = {
            "title": "Senior Full-Stack Engineer",
            "company": "TopCo",
            "location": "Delhi NCR",
            "description": "Build high-scale distributed systems.",
            "pay_status": "paid",
        }
        ev = evaluate_job(regular_job, DEFAULT_PREFERENCES)
        assert ev["section"] == "other"
        assert any("not an internship" in r for r in ev["reasons"])


