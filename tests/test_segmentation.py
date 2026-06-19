import pytest
from backend.segmentation import (
    run_segmentation,
    determine_preliminary_segment,
    determine_preliminary_action,
    estimate_recovery_probability,
    calculate_priority_score,
    SEGMENTS,
    ACTIONS,
)


@pytest.fixture
def willing_borrower():
    return {
        "name": "Priya Sharma",
        "days_past_due": 12,
        "overdue_amount": 4200,
        "loan_amount": 50000,
        "prior_payment_behavior": "on_time",
        "preferred_channel": "sms",
        "hardship_indicators": [],
        "response_history": [{"channel": "sms", "date": "2026-06-08", "responded": True}],
        "repayment_promises": [],
        "partial_payments_last_30d": 0,
    }


@pytest.fixture
def unresponsive_borrower():
    return {
        "name": "Vikram Singh",
        "days_past_due": 67,
        "overdue_amount": 45000,
        "loan_amount": 200000,
        "prior_payment_behavior": "chronic_late",
        "preferred_channel": "sms",
        "hardship_indicators": [],
        "response_history": [
            {"channel": "sms", "date": "2026-05-01", "responded": False},
            {"channel": "call", "date": "2026-05-15", "responded": False},
            {"channel": "email", "date": "2026-05-30", "responded": False},
        ],
        "repayment_promises": [
            {"date": "2026-04-20", "amount": 20000, "kept": False},
            {"date": "2026-05-10", "amount": 15000, "kept": False},
        ],
        "partial_payments_last_30d": 0,
    }


@pytest.fixture
def hardship_borrower():
    return {
        "name": "Anita Desai",
        "days_past_due": 25,
        "overdue_amount": 9200,
        "loan_amount": 80000,
        "prior_payment_behavior": "on_time",
        "preferred_channel": "email",
        "hardship_indicators": ["job_loss"],
        "response_history": [{"channel": "email", "date": "2026-06-01", "responded": True}],
        "repayment_promises": [],
        "partial_payments_last_30d": 2000,
    }


def test_segments_and_actions_defined():
    assert len(SEGMENTS) == 5
    assert len(ACTIONS) >= 5


def test_willing_but_delayed_segment(willing_borrower):
    signals = run_segmentation(willing_borrower)
    segment = determine_preliminary_segment(willing_borrower, signals)
    assert segment == "Willing but Delayed"
    assert len(signals) >= 2


def test_unresponsive_segment(unresponsive_borrower):
    signals = run_segmentation(unresponsive_borrower)
    segment = determine_preliminary_segment(unresponsive_borrower, signals)
    assert segment in ("Unresponsive", "High-Risk Escalation")
    types = {s.type for s in signals}
    assert "Unresponsive Borrower" in types or "Multiple Broken Promises" in types


def test_hardship_segment(hardship_borrower):
    signals = run_segmentation(hardship_borrower)
    segment = determine_preliminary_segment(hardship_borrower, signals)
    assert segment == "Hardship Case"
    assert any(s.type == "Hardship Indicators" for s in signals)


def test_hardship_action(hardship_borrower):
    signals = run_segmentation(hardship_borrower)
    segment = determine_preliminary_segment(hardship_borrower, signals)
    action = determine_preliminary_action(segment, hardship_borrower, signals)
    assert action in ("Hardship Support", "Payment Plan Offer")


def test_recovery_probability_bounds(willing_borrower, unresponsive_borrower):
    willing_signals = run_segmentation(willing_borrower)
    unresp_signals = run_segmentation(unresponsive_borrower)
    willing_prob = estimate_recovery_probability(willing_borrower, willing_signals)
    unresp_prob = estimate_recovery_probability(unresponsive_borrower, unresp_signals)
    assert 0.05 <= willing_prob <= 0.95
    assert 0.05 <= unresp_prob <= 0.95
    assert willing_prob > unresp_prob


def test_priority_score_higher_for_severe_cases(willing_borrower, unresponsive_borrower):
    w_signals = run_segmentation(willing_borrower)
    u_signals = run_segmentation(unresponsive_borrower)
    assert calculate_priority_score(unresponsive_borrower, u_signals) > calculate_priority_score(
        willing_borrower, w_signals
    )
