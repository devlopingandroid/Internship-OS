import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app, active_preparations, active_preparations_lock
from app import database, engine

client = TestClient(app)

def create_sample_job(idx: int, **overrides):
    base = {
        "url": f"https://example.com/job/{idx}",
        "title": f"Software Engineer Intern {idx}",
        "company": f"Company {idx}",
        "description": f"Work on Python and React services. Monthly stipend INR {20000 + idx}.",
        "location": "Delhi",
        "source": "Manual",
        "source_work_mode": "On-site",
        "pay_status": "paid",
    }
    base.update(overrides)
    res = client.post("/api/jobs", json=base)
    assert res.status_code == 200, res.text
    return res.json()


# ── Task 3: Pagination Tests ──────────────────────────────────────────────────

class TestJobsPagination:
    def test_pagination_first_page(self):
        # Insert 15 test jobs
        for i in range(1, 16):
            create_sample_job(i)

        res = client.get("/api/jobs?limit=5&offset=0")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert len(data["items"]) == 5
        assert data["total"] == 15
        assert data["limit"] == 5
        assert data["offset"] == 0
        assert res.headers.get("X-Total-Count") == "15"

    def test_pagination_subsequent_pages(self):
        for i in range(1, 16):
            create_sample_job(i)

        page1 = client.get("/api/jobs?limit=5&offset=0").json()
        page2 = client.get("/api/jobs?limit=5&offset=5").json()
        page3 = client.get("/api/jobs?limit=5&offset=10").json()

        assert len(page1["items"]) == 5
        assert len(page2["items"]) == 5
        assert len(page3["items"]) == 5

        ids_p1 = [j["id"] for j in page1["items"]]
        ids_p2 = [j["id"] for j in page2["items"]]
        ids_p3 = [j["id"] for j in page3["items"]]

        # Verify no overlap between pages
        assert set(ids_p1).isdisjoint(set(ids_p2))
        assert set(ids_p2).isdisjoint(set(ids_p3))
        assert set(ids_p1).isdisjoint(set(ids_p3))

    def test_pagination_empty_results(self):
        for i in range(1, 6):
            create_sample_job(i)

        # Offset beyond total
        res = client.get("/api/jobs?limit=5&offset=50")
        assert res.status_code == 200
        data = res.json()
        assert data["items"] == []
        assert data["total"] == 5
        assert data["offset"] == 50

        # Query with no matches
        res_empty = client.get("/api/jobs?query=nonexistentxyz999&limit=5&offset=0")
        assert res_empty.status_code == 200
        data_empty = res_empty.json()
        assert data_empty["items"] == []
        assert data_empty["total"] == 0

    def test_pagination_invalid_limits_and_offsets(self):
        # Limit < 1
        res = client.get("/api/jobs?limit=0&offset=0")
        assert res.status_code == 422

        # Limit > MAX_PAGE_SIZE (100)
        res = client.get("/api/jobs?limit=101&offset=0")
        assert res.status_code == 422

        # Negative limit
        res = client.get("/api/jobs?limit=-5&offset=0")
        assert res.status_code == 422

        # Negative offset
        res = client.get("/api/jobs?limit=10&offset=-1")
        assert res.status_code == 422

    def test_pagination_total_counts(self):
        for i in range(1, 12):
            create_sample_job(i)

        res = client.get("/api/jobs?limit=10&offset=0")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 11
        assert res.headers.get("X-Total-Count") == "11"

    def test_pagination_stable_ordering(self):
        for i in range(1, 16):
            create_sample_job(i)

        all_paged = client.get("/api/jobs?limit=15&offset=0").json()
        page1 = client.get("/api/jobs?limit=5&offset=0").json()
        page2 = client.get("/api/jobs?limit=5&offset=5").json()
        page3 = client.get("/api/jobs?limit=5&offset=10").json()

        combined_ids = [j["id"] for j in page1["items"]] + [j["id"] for j in page2["items"]] + [j["id"] for j in page3["items"]]
        expected_ids = [j["id"] for j in all_paged["items"]]
        assert combined_ids == expected_ids

    def test_existing_endpoint_compatibility(self):
        for i in range(1, 4):
            create_sample_job(i)

        # Calling without limit or offset returns a list directly for legacy compatibility
        res = client.get("/api/jobs")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) == 3
        assert res.headers.get("X-Total-Count") == "3"


# ── Task 4: Role Filtering Tests ──────────────────────────────────────────────

class TestRoleFiltering:
    def test_role_filtering_by_matched_roles_when_title_differs(self):
        # Create a job classified as Backend Engineer via description / stack keywords
        # but title does not have "Backend"
        job1 = create_sample_job(
            101,
            title="Senior Shopify Developer Intern",
            description="Build scalable server APIs using Python, Django, FastAPI, and PostgreSQL. Paid monthly.",
            source_work_mode="On-site",
            location="Delhi",
        )
        assert "Backend Engineer" in job1["matched_roles"]

        # Job without Backend Engineer classification
        job2 = create_sample_job(
            102,
            title="Android Mobile Intern",
            description="Build Android apps with Kotlin. Paid monthly.",
            source_work_mode="On-site",
            location="Delhi",
        )
        assert "Backend Engineer" not in job2["matched_roles"]

        # Filter by Backend Engineer
        res = client.get("/api/jobs?role=Backend Engineer&paginate=true")
        assert res.status_code == 200
        data = res.json()
        matching_ids = [j["id"] for j in data["items"]]
        assert job1["id"] in matching_ids
        assert job2["id"] not in matching_ids

    def test_role_filter_safe_with_no_matched_roles(self):
        # Create a job with irrelevant role
        job_none = create_sample_job(
            103,
            title="General Research Trainee",
            description="Perform generic data collection and filing duties.",
            source_work_mode="On-site",
            location="Delhi",
        )
        res = client.get("/api/jobs?role=Backend Engineer&paginate=true")
        assert res.status_code == 200
        matching_ids = [j["id"] for j in res.json()["items"]]
        assert job_none["id"] not in matching_ids

    def test_text_search_is_independent_of_role_filter(self):
        job = create_sample_job(
            104,
            title="Senior Shopify Developer Intern",
            description="Build scalable server APIs using Python and Django.",
            source_work_mode="On-site",
            location="Delhi",
        )
        # Search text for 'Shopify' with role 'all'
        res = client.get("/api/jobs?query=Shopify&role=all&paginate=true")
        assert res.status_code == 200
        assert any(j["id"] == job["id"] for j in res.json()["items"])


# ── Task 5: Prepare Safe Repeated Clicks Protection ───────────────────────────

class TestPrepareSafety:
    def test_prepare_concurrent_duplicate_returns_409(self):
        job = create_sample_job(201, title="Backend Intern", url="https://httpbin.org/get")
        job_id = job["id"]

        # Simulate job_id already in active_preparations
        active_preparations.add(job_id)
        try:
            res = client.post(f"/api/jobs/{job_id}/prepare")
            assert res.status_code == 409
            assert "already in progress" in res.json()["detail"]
        finally:
            active_preparations.discard(job_id)

    def test_prepare_lock_released_on_error(self):
        job = create_sample_job(202, title="Test Error Intern", url="https://example.com/job/202")
        job_id = job["id"]

        with patch("app.main.prepare_application", side_effect=RuntimeError("Browser launch failure")):
            with pytest.raises(RuntimeError, match="Browser launch failure"):
                client.post(f"/api/jobs/{job_id}/prepare")

        # Verify lock was released even though prepare_application threw an exception
        assert job_id not in active_preparations

    def test_unrelated_jobs_not_blocked_by_active_preparation(self):
        job1 = create_sample_job(203, title="Job 1 Intern", url="https://example.com/job/203")
        job2 = create_sample_job(204, title="Job 2 Intern", url="https://example.com/job/204")

        active_preparations.add(job1["id"])
        try:
            with patch("app.main.prepare_application", return_value={"message": "ok", "filled_fields": []}):
                res = client.post(f"/api/jobs/{job2['id']}/prepare")
                assert res.status_code == 200
        finally:
            active_preparations.discard(job1["id"])
