"""Tests for Finance Pipeline — component 1.6."""

import uuid
from unittest.mock import patch

ENDPOINT = "/finance/pipeline"


class TestTriggerPipeline:
    """Happy-path: trigger a pipeline run and verify it completes."""

    def test_pipeline_completes_all_steps(self, client):
        r = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-01"})
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "completed"
        assert body["steps_completed"] == 6
        assert body["steps_total"] == 6
        assert body["run_date"] == "2025-07-01"
        assert body["finished_at"] is not None

    def test_pipeline_sets_inputs_hash(self, client):
        r = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-01"})
        body = r.json()
        assert len(body["inputs_hash"]) == 64  # SHA-256 hex


class TestPipelineIdempotency:
    """Re-running the pipeline for the same date returns the same run."""

    def test_idempotent_same_date(self, client):
        r1 = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-02"})
        run_id_1 = r1.json()["id"]
        r2 = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-02"})
        run_id_2 = r2.json()["id"]
        assert run_id_1 == run_id_2

    def test_different_dates_different_runs(self, client):
        r1 = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-03"})
        r2 = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-04"})
        assert r1.json()["id"] != r2.json()["id"]


class TestPipelinePartialFailure:
    """When a step fails, the pipeline should be partial and stop."""

    def test_step_failure_marks_partial(self, client):
        with patch(
            "app.services.finance_pipeline_service.FinancePipelineService._step_mtm_computation",
            side_effect=RuntimeError("MTM service down"),
        ):
            r = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-08-01"})
            body = r.json()
            assert body["status"] == "partial"
            assert "mtm_computation" in (body.get("error_message") or "")
            # step 1 completed, step 2 failed
            assert body["steps_completed"] == 1


class TestPipelineResume:
    """A partial pipeline can be resumed."""

    def test_resume_after_failure(self, client):
        # First run — force step 2 to fail
        with patch(
            "app.services.finance_pipeline_service.FinancePipelineService._step_mtm_computation",
            side_effect=RuntimeError("down"),
        ):
            r1 = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-08-04"})
            assert r1.json()["status"] == "partial"
            run_id = r1.json()["id"]

        # Second run — no mocking, step 2 should succeed now
        r2 = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-08-04"})
        assert r2.json()["id"] == run_id
        assert r2.json()["status"] == "completed"
        assert r2.json()["steps_completed"] == 6

    def test_holiday_returns_409(self, client):
        r = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-08-02"})
        assert r.status_code == 409


class TestListRuns:
    def test_list_empty(self, client):
        r = client.get(f"{ENDPOINT}/runs")
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_list_after_trigger(self, client):
        client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-10"})
        client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-11"})
        r = client.get(f"{ENDPOINT}/runs")
        assert len(r.json()["items"]) == 2


class TestGetRunDetail:
    def test_detail_includes_steps(self, client):
        r = client.post(f"{ENDPOINT}/run", json={"run_date": "2025-07-15"})
        run_id = r.json()["id"]
        r2 = client.get(f"{ENDPOINT}/runs/{run_id}")
        assert r2.status_code == 200
        body = r2.json()
        assert len(body["steps"]) == 6
        step_names = [s["step_name"] for s in body["steps"]]
        assert step_names == [
            "market_snapshot",
            "mtm_computation",
            "pl_snapshot",
            "cashflow_baseline",
            "risk_flags",
            "summary",
        ]
        for step in body["steps"]:
            assert step["status"] == "completed"

    def test_detail_not_found(self, client):
        r = client.get(f"{ENDPOINT}/runs/{uuid.uuid4()}")
        assert r.status_code == 404
