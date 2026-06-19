import pytest
from unittest.mock import patch

from backend.ai_client import (
    get_strategy_recommendation,
    answer_agent_query,
    sanitize_message_draft,
    clean_json_response,
)
from backend.segmentation import run_segmentation


@pytest.mark.parametrize("draft,blocked_term", [
    # Original banned phrases still caught
    ("Pay now or we will take legal action against you.", "legal action"),
    ("You will be arrested if you do not pay.", "arrested"),
    ("You could go to jail for this.", "jail"),
    ("We will seize your assets immediately.", "seize"),
    ("We will harass you until you pay.", "harass"),
    ("We will threaten your family.", "threaten"),
    # Paraphrased legal threats — previously NOT caught
    ("We will initiate legal proceedings against you.", "legal proceedings"),
    ("A court notice will be issued to your address.", "court notice"),
    ("We are filing a lawsuit against your account.", "lawsuit"),
    ("This will lead to litigation if unresolved.", "litigation"),
    ("A summons will be delivered to your home.", "summons"),
    # Criminal language — previously NOT caught
    ("A criminal complaint will be filed.", "criminal complaint"),
    ("You may face prosecution.", "prosecution"),
    ("We will file an FIR against you.", "FIR"),
    ("Your assets may be repossessed.", "repossessed"),
    # Asset threats — previously NOT caught
    ("We will foreclose on your property.", "foreclose"),
    ("Wage garnishment proceedings may begin.", "wage garnish"),
    # Harassment variants — previously NOT caught
    ("This is a form of coercion and you must comply.", "coercion"),
    ("We will blackmail you into paying.", "blackmail"),
])
def test_sanitize_message_draft_removes_threats(draft, blocked_term):
    result = sanitize_message_draft(draft)
    assert blocked_term.lower() not in result.lower(), (
        f"Expected '{blocked_term}' to be removed but it was still present in: {result!r}"
    )


def test_sanitize_message_draft_preserves_safe_content():
    safe = "Hi Priya, we noticed your account has an overdue balance. Please contact us to discuss a repayment plan."
    result = sanitize_message_draft(safe)
    assert result == safe.strip()


def test_sanitize_message_draft_truncates_to_600():
    long_draft = "This is a safe message. " * 50
    result = sanitize_message_draft(long_draft)
    assert len(result) <= 600


def test_clean_json_response_strips_markdown():
    raw = '```json\n{"answer": "test"}\n```'
    parsed = clean_json_response(raw)
    assert parsed["answer"] == "test"


def test_strategy_fallback_without_api_key(sample_borrower_payload):
    borrower = sample_borrower_payload
    signals = run_segmentation(borrower)
    with patch("backend.ai_client.call_llm_wrapper", side_effect=ValueError("no key")):
        result = get_strategy_recommendation(borrower, signals)
    assert result["segment"] in (
        "Willing but Delayed", "Habitual Late Payer", "Hardship Case",
        "Unresponsive", "High-Risk Escalation",
    )
    assert result["message_draft"]
    assert result["analysis_method"] == "rule_based_fallback"


def test_query_fallback_without_api_key():
    borrower = {
        "name": "Anita Desai",
        "days_past_due": 25,
        "overdue_amount": 9200,
        "loan_amount": 80000,
        "prior_payment_behavior": "on_time",
        "preferred_channel": "email",
        "hardship_indicators": ["job_loss"],
        "response_history": [],
        "repayment_promises": [],
        "partial_payments_last_30d": 2000,
        "segment": "Hardship Case",
        "next_best_action": "Hardship Support",
    }
    signals = run_segmentation(borrower)
    with patch("backend.ai_client.call_llm_wrapper", side_effect=Exception("offline")):
        answer = answer_agent_query(borrower, signals, "Why hardship support?")
    assert "Hardship" in answer or "hardship" in answer.lower()


def test_strategy_with_mocked_ai(sample_borrower_payload):
    borrower = sample_borrower_payload
    signals = run_segmentation(borrower)
    mock_response = (
        '{"segment": "Habitual Late Payer", "next_best_action": "Payment Plan Offer", '
        '"recommended_channel": "sms", "recommended_time": "Weekday 10 AM", '
        '"message_draft": "Hi Test, we can help with a payment plan.", '
        '"strategy_rationale": "• Occasional late history", "recovery_probability": 0.55}'
    )
    with patch("backend.ai_client.call_llm_wrapper", return_value=mock_response):
        result = get_strategy_recommendation(borrower, signals)
    assert result["segment"] == "Habitual Late Payer"
    assert result["analysis_method"] == "ai"
    assert "payment plan" in result["message_draft"].lower()
