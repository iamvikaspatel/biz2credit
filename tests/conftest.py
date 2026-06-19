import json
import os
import tempfile
import pytest

# Set test environment before app imports
os.environ["AGENT_API_KEY"] = "test-agent-key"
os.environ["SUPERVISOR_API_KEY"] = "test-supervisor-key"
os.environ["APP_ENV"] = "test"

TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix=".json")
os.close(TEST_DB_FD)
os.environ["BORROWERS_DB_PATH"] = TEST_DB_PATH

# Seed minimal test data
_SEED = [
    {
        "id": "BOR001",
        "name": "Priya Sharma",
        "phone": "+91-9876543210",
        "email": "priya.sharma@gmail.com",
        "loan_amount": 50000,
        "days_past_due": 12,
        "overdue_amount": 4200,
        "prior_payment_behavior": "on_time",
        "preferred_channel": "sms",
        "hardship_indicators": [],
        "response_history": [
            {"channel": "sms", "date": "2026-06-08", "responded": True, "outcome": "Promised payment"}
        ],
        "repayment_promises": [],
        "partial_payments_last_30d": 0,
        "ingested_timestamp": "2026-06-10T09:00:00Z",
        "segment": "Willing but Delayed",
        "next_best_action": "SMS Reminder",
        "recommended_channel": "sms",
        "recommended_time": "Weekday 10:00 AM",
        "recovery_probability": 0.72,
        "priority_score": 28.6,
        "action_audit_log": [],
    },
    {
        "id": "BOR002",
        "name": "Vikram Singh",
        "phone": "+91-9123456789",
        "email": "vikram.s@hotmail.com",
        "loan_amount": 200000,
        "days_past_due": 95,
        "overdue_amount": 45000,
        "prior_payment_behavior": "chronic_late",
        "preferred_channel": "sms",
        "hardship_indicators": [],
        "response_history": [
            {"channel": "sms", "date": "2026-05-01", "responded": False, "outcome": "No response"},
            {"channel": "call", "date": "2026-05-15", "responded": False, "outcome": "No answer"},
            {"channel": "email", "date": "2026-05-30", "responded": False, "outcome": "No response"},
        ],
        "repayment_promises": [
            {"date": "2026-04-20", "amount": 20000, "kept": False},
            {"date": "2026-05-10", "amount": 15000, "kept": False},
        ],
        "partial_payments_last_30d": 0,
        "ingested_timestamp": "2026-05-20T08:00:00Z",
        "segment": "Unresponsive",
        "next_best_action": "Agent Call",
        "recovery_probability": 0.22,
        "priority_score": 68.3,
        "action_audit_log": [],
    },
    {
        "id": "BOR003",
        "name": "Anita Desai",
        "phone": "+91-9988776655",
        "email": "anita.desai@yahoo.com",
        "loan_amount": 80000,
        "days_past_due": 25,
        "overdue_amount": 9200,
        "prior_payment_behavior": "on_time",
        "preferred_channel": "email",
        "hardship_indicators": ["job_loss"],
        "response_history": [
            {"channel": "email", "date": "2026-06-01", "responded": True, "outcome": "Explained job loss"}
        ],
        "repayment_promises": [],
        "partial_payments_last_30d": 2000,
        "ingested_timestamp": "2026-06-12T11:00:00Z",
        "segment": "Hardship Case",
        "next_best_action": "Hardship Support",
        "recovery_probability": 0.61,
        "priority_score": 45.1,
        "action_audit_log": [],
    },
]

with open(TEST_DB_PATH, "w") as f:
    json.dump(_SEED, f)


def _reset_test_db():
    with open(TEST_DB_PATH, "w") as f:
        json.dump(_SEED, f)


from backend.security import reset_rate_limits  # noqa: E402
from backend.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state():
    _reset_test_db()
    reset_rate_limits()
    yield
    _reset_test_db()
    reset_rate_limits()


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def agent_headers():
    return {"X-API-Key": "test-agent-key"}


@pytest.fixture
def supervisor_headers():
    return {"X-API-Key": "test-supervisor-key"}


@pytest.fixture
def sample_borrower_payload():
    return {
        "name": "Test Borrower",
        "phone": "+91-9000012345",
        "email": "test.borrower@example.com",
        "loan_amount": 60000,
        "days_past_due": 20,
        "overdue_amount": 8000,
        "prior_payment_behavior": "occasional_late",
        "preferred_channel": "sms",
        "hardship_indicators": [],
        "response_history": [],
        "repayment_promises": [],
        "partial_payments_last_30d": 0,
    }
