import pytest
from unittest.mock import patch


def test_health_public(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert "borrowers_count" not in res.json()


def test_unauthenticated_request_rejected(client):
    res = client.get("/borrowers")
    assert res.status_code == 401


def test_invalid_api_key_rejected(client):
    res = client.get("/borrowers", headers={"X-API-Key": "bad-key"})
    assert res.status_code == 401


def test_agent_can_list_borrowers(client, agent_headers):
    res = client.get("/borrowers", headers=agent_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3
    # PII masked in list view for agents
    assert "***" in data[0]["phone"] or "*" in data[0]["phone"]


def test_supervisor_sees_full_pii_in_list(client, supervisor_headers):
    res = client.get("/borrowers", headers=supervisor_headers)
    assert res.status_code == 200
    data = res.json()
    assert "+91" in data[0]["phone"]


def test_agent_cannot_ingest(client, agent_headers, sample_borrower_payload):
    res = client.post("/borrowers", json=sample_borrower_payload, headers=agent_headers)
    assert res.status_code == 403


def test_supervisor_can_ingest(client, supervisor_headers, sample_borrower_payload):
    with patch("backend.ai_client.call_llm_wrapper", side_effect=ValueError("no ai")):
        res = client.post("/borrowers", json=sample_borrower_payload, headers=supervisor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["borrower_id"].startswith("BOR")
    assert body["segment"]
    assert body["next_best_action"]


def test_get_borrower_detail(client, agent_headers):
    res = client.get("/borrowers/BOR001", headers=agent_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Priya Sharma"
    assert "strategy_signals" in body
    assert "ai_prompt_sent" not in body


def test_invalid_borrower_id_rejected(client, agent_headers):
    res = client.get("/borrowers/INVALID", headers=agent_headers)
    assert res.status_code == 400


def test_borrower_not_found(client, agent_headers):
    res = client.get("/borrowers/BOR999", headers=agent_headers)
    assert res.status_code == 404


def test_query_endpoint(client, agent_headers):
    with patch("backend.ai_client.call_llm_wrapper", return_value='{"answer": "Hardship due to job loss."}'):
        res = client.post(
            "/borrowers/BOR003/query",
            json={"question": "Why is this borrower assigned to hardship support?"},
            headers=agent_headers,
        )
    assert res.status_code == 200
    assert "answer" in res.json()


def test_query_rejects_short_question(client, agent_headers):
    res = client.post(
        "/borrowers/BOR001/query",
        json={"question": "??"},
        headers=agent_headers,
    )
    assert res.status_code == 422


def test_re_strategize(client, supervisor_headers):
    with patch("backend.ai_client.call_llm_wrapper", side_effect=ValueError("offline")):
        res = client.post("/borrowers/BOR001/re-strategize", headers=supervisor_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["segment"]
    assert "ai_prompt_sent" in body


def test_agent_re_strategize_hides_audit(client, agent_headers):
    with patch("backend.ai_client.call_llm_wrapper", side_effect=ValueError("offline")):
        res = client.post("/borrowers/BOR001/re-strategize", headers=agent_headers)
    assert res.status_code == 200
    assert "ai_prompt_sent" not in res.json()


def test_priority_dashboard(client, agent_headers):
    res = client.get("/dashboard/priority", headers=agent_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert len(body["queue"]) == 3
    assert body["queue"][0]["priority_score"] >= body["queue"][-1]["priority_score"]


def test_ingest_validation_rejects_bad_email(client, supervisor_headers, sample_borrower_payload):
    sample_borrower_payload["email"] = "not-an-email"
    res = client.post("/borrowers", json=sample_borrower_payload, headers=supervisor_headers)
    assert res.status_code == 422


def test_ingest_validation_accepts_email_with_spaces(client, supervisor_headers, sample_borrower_payload):
    sample_borrower_payload["email"] = "  test.borrower@example.com  "
    res = client.post("/borrowers", json=sample_borrower_payload, headers=supervisor_headers)
    assert res.status_code == 200


def test_security_headers_present(client):
    res = client.get("/health")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in res.headers
