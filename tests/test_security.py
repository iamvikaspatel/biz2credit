import pytest
from backend.security import (
    resolve_role_from_api_key,
    require_role,
    validate_borrower_id,
    mask_phone,
    mask_email,
    redact_borrower_for_list,
    redact_borrower_for_detail,
    check_rate_limit,
    reset_rate_limits,
)
from fastapi import HTTPException
from unittest.mock import MagicMock


def test_resolve_role_agent():
    assert resolve_role_from_api_key("test-agent-key") == "agent"


def test_resolve_role_supervisor():
    assert resolve_role_from_api_key("test-supervisor-key") == "supervisor"


def test_resolve_role_invalid():
    assert resolve_role_from_api_key("wrong-key") is None
    assert resolve_role_from_api_key(None) is None


def test_require_role_raises_on_missing_key():
    with pytest.raises(HTTPException) as exc:
        require_role(None, {"agent"})
    assert exc.value.status_code == 401


def test_require_role_raises_on_wrong_role():
    with pytest.raises(HTTPException) as exc:
        require_role("test-agent-key", {"supervisor"})
    assert exc.value.status_code == 403


def test_validate_borrower_id_valid():
    assert validate_borrower_id("BOR001") == "BOR001"


def test_validate_borrower_id_invalid():
    with pytest.raises(HTTPException) as exc:
        validate_borrower_id("../etc/passwd")
    assert exc.value.status_code == 400


def test_mask_phone():
    assert mask_phone("+91-9876543210") != "+91-9876543210"
    assert mask_phone("+91-9876543210").endswith("210")


def test_mask_email():
    masked = mask_email("priya.sharma@gmail.com")
    assert "@" in masked
    assert "priya.sharma" not in masked


def test_redact_list_for_agent():
    record = {
        "phone": "+91-9876543210",
        "email": "priya@gmail.com",
        "ai_prompt_sent": "secret prompt",
        "ai_raw_response": "secret response",
    }
    redacted = redact_borrower_for_list(record, "agent")
    assert redacted["phone"] != record["phone"]
    assert "ai_prompt_sent" not in redacted


def test_redact_detail_for_supervisor():
    record = {"ai_prompt_sent": "prompt", "ai_raw_response": "raw"}
    redacted = redact_borrower_for_detail(record, "supervisor")
    assert redacted["ai_prompt_sent"] == "prompt"


def test_rate_limit_blocks_excess():
    reset_rate_limits()
    request = MagicMock()
    request.headers = {}
    request.client = MagicMock(host="127.0.0.1")

    import backend.security as sec
    original_limit = sec.RATE_LIMIT_REQUESTS
    sec.RATE_LIMIT_REQUESTS = 3
    try:
        for _ in range(3):
            check_rate_limit(request, "test-key")
        with pytest.raises(HTTPException) as exc:
            check_rate_limit(request, "test-key")
        assert exc.value.status_code == 429
    finally:
        sec.RATE_LIMIT_REQUESTS = original_limit
        reset_rate_limits()
