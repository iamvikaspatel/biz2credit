import json
import os
import tempfile
import pytest

from backend import data


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    monkeypatch.setenv("BORROWERS_DB_PATH", path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_add_and_get_borrower(temp_db):
    record = {
        "name": "Test User",
        "phone": "+91-9000012345",
        "email": "test@example.com",
        "loan_amount": 50000,
        "days_past_due": 10,
        "overdue_amount": 5000,
        "prior_payment_behavior": "on_time",
        "preferred_channel": "sms",
    }
    saved = data.add_borrower(record)
    assert saved["id"] == "BOR001"

    fetched = data.get_borrower_by_id("BOR001")
    assert fetched["name"] == "Test User"


def test_invalid_borrower_id_raises(temp_db):
    with pytest.raises(ValueError):
        data.get_borrower_by_id("INVALID")


def test_update_borrower(temp_db):
    data.add_borrower({"name": "A", "phone": "+9112345678", "email": "a@b.com",
                       "loan_amount": 1, "days_past_due": 1, "overdue_amount": 1,
                       "prior_payment_behavior": "on_time", "preferred_channel": "sms"})
    updated = data.update_borrower("BOR001", {"id": "BOR001", "name": "Updated"})
    assert updated["name"] == "Updated"


def test_file_locking_does_not_corrupt(temp_db):
    for i in range(5):
        data.add_borrower({
            "name": f"User {i}",
            "phone": f"+911234567{i}",
            "email": f"u{i}@example.com",
            "loan_amount": 10000,
            "days_past_due": 5,
            "overdue_amount": 1000,
            "prior_payment_behavior": "on_time",
            "preferred_channel": "sms",
        })
    all_records = data.get_all_borrowers()
    assert len(all_records) == 5
    with open(temp_db) as f:
        json.load(f)  # valid JSON
