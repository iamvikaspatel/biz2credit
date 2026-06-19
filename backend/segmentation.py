from typing import List, Optional, Tuple
from backend.models import StrategySignal

SEGMENTS = [
    "Willing but Delayed",
    "Habitual Late Payer",
    "Hardship Case",
    "Unresponsive",
    "High-Risk Escalation",
]

ACTIONS = [
    "SMS Reminder",
    "Email",
    "Agent Call",
    "Payment Plan Offer",
    "Hardship Support",
    "Escalation",
    "Manual Review",
]


def _get_val(record, key):
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def _count_unresponsive_attempts(response_history) -> int:
    if not response_history:
        return 0
    streak = 0
    for entry in reversed(response_history):
        responded = _get_val(entry, "responded")
        if responded is False:
            streak += 1
        else:
            break
    return streak


def _count_broken_promises(repayment_promises) -> int:
    if not repayment_promises:
        return 0
    return sum(1 for p in repayment_promises if not _get_val(p, "kept"))


def _response_rate(response_history) -> float:
    if not response_history:
        return 0.0
    responded = sum(1 for r in response_history if _get_val(r, "responded"))
    return responded / len(response_history)


def _best_response_window(response_history) -> str:
    """Infer best outreach time from historical responses."""
    responded = [r for r in (response_history or []) if _get_val(r, "responded")]
    if not responded:
        return "Weekday 10:00–11:00 AM (default business hours)"

    channel_counts = {}
    for r in responded:
        ch = (_get_val(r, "channel") or "unknown").lower()
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    best_channel = max(channel_counts, key=channel_counts.get)
    time_hint = {
        "sms": "Weekday 10:00–11:00 AM",
        "email": "Tuesday or Thursday 9:00–10:00 AM",
        "call": "Weekday 4:00–6:00 PM",
    }.get(best_channel, "Weekday 10:00–11:00 AM")
    return time_hint


def _best_channel(borrower, response_history) -> str:
    preferred = (_get_val(borrower, "preferred_channel") or "sms").lower()
    responded = [r for r in (response_history or []) if _get_val(r, "responded")]
    if responded:
        channel_counts = {}
        for r in responded:
            ch = (_get_val(r, "channel") or preferred).lower()
            channel_counts[ch] = channel_counts.get(ch, 0) + 1
        return max(channel_counts, key=channel_counts.get)
    return preferred


def check_dpd_severity(borrower) -> Optional[StrategySignal]:
    dpd = _get_val(borrower, "days_past_due") or 0
    if dpd <= 0:
        return None
    if dpd <= 15:
        return StrategySignal(
            type="Early Delinquency",
            severity="Low",
            confidence="High (90%)",
            evidence=f"Account is {dpd} days past due — early-stage delinquency.",
        )
    if dpd <= 45:
        return StrategySignal(
            type="Moderate Delinquency",
            severity="Medium",
            confidence="High (90%)",
            evidence=f"Account is {dpd} days past due — moderate delinquency requiring active follow-up.",
        )
    if dpd <= 90:
        return StrategySignal(
            type="Advanced Delinquency",
            severity="High",
            confidence="High (95%)",
            evidence=f"Account is {dpd} days past due — advanced delinquency with elevated recovery risk.",
        )
    return StrategySignal(
        type="Severe Delinquency",
        severity="High",
        confidence="High (95%)",
        evidence=f"Account is {dpd} days past due — severe delinquency; escalation may be warranted.",
    )


def check_overdue_ratio(borrower) -> Optional[StrategySignal]:
    overdue = _get_val(borrower, "overdue_amount") or 0
    loan = _get_val(borrower, "loan_amount") or 1
    if overdue <= 0:
        return None
    ratio = overdue / loan if loan else 1.0
    if ratio < 0.15:
        return StrategySignal(
            type="Low Overdue Ratio",
            severity="Low",
            confidence="High (85%)",
            evidence=f"Overdue ₹{overdue:,.0f} is {ratio:.0%} of loan — relatively small balance outstanding.",
        )
    if ratio < 0.40:
        return StrategySignal(
            type="Moderate Overdue Ratio",
            severity="Medium",
            confidence="High (90%)",
            evidence=f"Overdue ₹{overdue:,.0f} is {ratio:.0%} of loan — meaningful balance at risk.",
        )
    return StrategySignal(
        type="High Overdue Ratio",
        severity="High",
        confidence="High (90%)",
        evidence=f"Overdue ₹{overdue:,.0f} is {ratio:.0%} of loan — substantial balance at risk.",
    )


def check_payment_history(borrower) -> Optional[StrategySignal]:
    behavior = (_get_val(borrower, "prior_payment_behavior") or "").lower().replace(" ", "_")
    mapping = {
        "on_time": ("Strong Payment History", "Low", "Borrower historically pays on time — likely temporary delay."),
        "occasional_late": ("Occasional Late Payments", "Medium", "Borrower has occasional late payments but generally engages."),
        "chronic_late": ("Chronic Late Payer", "High", "Borrower has a pattern of chronic late payments."),
    }
    if behavior not in mapping:
        return StrategySignal(
            type="Unknown Payment History",
            severity="Low",
            confidence="Medium (60%)",
            evidence="Prior payment behavior not specified — treat with cautious outreach.",
        )
    sig_type, severity, evidence = mapping[behavior]
    return StrategySignal(
        type=sig_type,
        severity=severity,
        confidence="High (85%)",
        evidence=evidence,
    )


def check_broken_promises(borrower) -> Optional[StrategySignal]:
    promises = _get_val(borrower, "repayment_promises") or []
    broken = _count_broken_promises(promises)
    if broken == 0:
        return None
    if broken == 1:
        return StrategySignal(
            type="Broken Repayment Promise",
            severity="Medium",
            confidence="High (90%)",
            evidence="1 prior repayment promise was not kept — follow-up recommended.",
        )
    return StrategySignal(
        type="Multiple Broken Promises",
        severity="High",
        confidence="High (95%)",
        evidence=f"{broken} prior repayment promises were not kept — trust deficit increasing.",
    )


def check_unresponsive(borrower) -> Optional[StrategySignal]:
    history = _get_val(borrower, "response_history") or []
    streak = _count_unresponsive_attempts(history)
    total = len(history)
    if total == 0:
        return StrategySignal(
            type="No Outreach History",
            severity="Low",
            confidence="Medium (70%)",
            evidence="No prior outreach recorded — initial contact recommended.",
        )
    if streak >= 3:
        return StrategySignal(
            type="Unresponsive Borrower",
            severity="High",
            confidence="High (90%)",
            evidence=f"No response to last {streak} consecutive outreach attempts.",
        )
    if streak == 2:
        return StrategySignal(
            type="Declining Responsiveness",
            severity="Medium",
            confidence="High (85%)",
            evidence="No response to last 2 outreach attempts — channel change may help.",
        )
    rate = _response_rate(history)
    if rate >= 0.5:
        return StrategySignal(
            type="Responsive Borrower",
            severity="Low",
            confidence="High (85%)",
            evidence=f"Response rate {rate:.0%} across {total} prior outreach attempts — borrower engages when contacted.",
        )
    return StrategySignal(
        type="Low Response Rate",
        severity="Medium",
        confidence="Medium (75%)",
        evidence=f"Response rate {rate:.0%} across {total} prior outreach attempts.",
    )


def check_hardship(borrower) -> Optional[StrategySignal]:
    indicators = _get_val(borrower, "hardship_indicators") or []
    if not indicators:
        return None
    items = ", ".join(indicators)
    return StrategySignal(
        type="Hardship Indicators",
        severity="Medium",
        confidence="High (90%)",
        evidence=f"Hardship indicators reported: {items}. Empathetic, support-oriented outreach recommended.",
    )


def check_partial_payment_intent(borrower) -> Optional[StrategySignal]:
    partial = _get_val(borrower, "partial_payments_last_30d") or 0
    if partial <= 0:
        return None
    return StrategySignal(
        type="Partial Payment Intent",
        severity="Low",
        confidence="High (85%)",
        evidence=f"₹{partial:,.0f} in partial payments in the last 30 days — shows willingness to pay.",
    )


def check_data_quality(borrower) -> Optional[StrategySignal]:
    missing = []
    for field in ("name", "phone", "email", "loan_amount", "days_past_due", "overdue_amount", "prior_payment_behavior"):
        val = _get_val(borrower, field)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(field)
    if missing:
        return StrategySignal(
            type="Insufficient Data",
            severity="Low",
            confidence="High (100%)",
            evidence=f"Missing or incomplete fields: {', '.join(missing)}.",
        )
    return None


def run_segmentation(borrower) -> List[StrategySignal]:
    signals = []
    for check in (
        check_data_quality,
        check_dpd_severity,
        check_overdue_ratio,
        check_payment_history,
        check_broken_promises,
        check_unresponsive,
        check_hardship,
        check_partial_payment_intent,
    ):
        result = check(borrower)
        if result:
            signals.append(result)
    return signals


def determine_preliminary_segment(borrower, signals: List[StrategySignal]) -> str:
    dpd = _get_val(borrower, "days_past_due") or 0
    hardship = bool(_get_val(borrower, "hardship_indicators"))
    partial = (_get_val(borrower, "partial_payments_last_30d") or 0) > 0
    behavior = (_get_val(borrower, "prior_payment_behavior") or "").lower()
    unresponsive_streak = _count_unresponsive_attempts(_get_val(borrower, "response_history") or [])
    broken = _count_broken_promises(_get_val(borrower, "repayment_promises") or [])
    signal_types = {s.type for s in signals}

    if dpd >= 90 and broken >= 2 and unresponsive_streak >= 3:
        return "High-Risk Escalation"
    if dpd >= 90 or "Severe Delinquency" in signal_types:
        return "High-Risk Escalation"
    if unresponsive_streak >= 3 or "Unresponsive Borrower" in signal_types:
        return "Unresponsive"
    if hardship or "Hardship Indicators" in signal_types:
        return "Hardship Case"
    if behavior in ("chronic_late", "occasional_late") or "Chronic Late Payer" in signal_types:
        return "Habitual Late Payer"
    if partial or "Partial Payment Intent" in signal_types or "Responsive Borrower" in signal_types:
        return "Willing but Delayed"
    if dpd <= 30 and broken == 0:
        return "Willing but Delayed"
    return "Habitual Late Payer"


def determine_preliminary_action(segment: str, borrower, signals: List[StrategySignal]) -> str:
    dpd = _get_val(borrower, "days_past_due") or 0
    unresponsive_streak = _count_unresponsive_attempts(_get_val(borrower, "response_history") or [])

    if segment == "High-Risk Escalation":
        return "Escalation" if dpd >= 90 else "Manual Review"
    if segment == "Unresponsive":
        return "Agent Call" if unresponsive_streak >= 3 else "Email"
    if segment == "Hardship Case":
        return "Hardship Support" if dpd <= 60 else "Payment Plan Offer"
    if segment == "Habitual Late Payer":
        return "Payment Plan Offer" if dpd >= 30 else "SMS Reminder"
    # Willing but Delayed
    preferred = (_get_val(borrower, "preferred_channel") or "sms").lower()
    if preferred == "email":
        return "Email"
    if preferred == "call":
        return "Agent Call"
    return "SMS Reminder"


def get_channel_and_time(borrower) -> Tuple[str, str]:
    history = _get_val(borrower, "response_history") or []
    channel = _best_channel(borrower, history)
    time_window = _best_response_window(history)
    return channel, time_window


def calculate_priority_score(borrower, signals: List[StrategySignal]) -> float:
    """Higher score = higher agent priority (recovery opportunity + urgency)."""
    dpd = _get_val(borrower, "days_past_due") or 0
    overdue = _get_val(borrower, "overdue_amount") or 0
    partial = _get_val(borrower, "partial_payments_last_30d") or 0
    recovery_prob = estimate_recovery_probability(borrower, signals)

    urgency = min(dpd / 120.0, 1.0) * 40
    value = min(overdue / 100000.0, 1.0) * 30
    engagement = (1.0 - _count_unresponsive_attempts(_get_val(borrower, "response_history") or []) / 5.0) * 15
    engagement = max(0, min(engagement, 15))
    intent_boost = 10 if partial > 0 else 0
    prob_boost = recovery_prob * 5

    return round(urgency + value + engagement + intent_boost + prob_boost, 1)


def estimate_recovery_probability(borrower, signals: List[StrategySignal]) -> float:
    """Rule-based recovery probability estimate (0–1)."""
    score = 0.55
    behavior = (_get_val(borrower, "prior_payment_behavior") or "").lower()
    if behavior == "on_time":
        score += 0.15
    elif behavior == "occasional_late":
        score += 0.05
    elif behavior == "chronic_late":
        score -= 0.10

    dpd = _get_val(borrower, "days_past_due") or 0
    score -= min(dpd / 200.0, 0.25)

    if (_get_val(borrower, "partial_payments_last_30d") or 0) > 0:
        score += 0.10
    if _get_val(borrower, "hardship_indicators"):
        score += 0.05  # hardship with support often recovers

    broken = _count_broken_promises(_get_val(borrower, "repayment_promises") or [])
    score -= broken * 0.08

    unresponsive = _count_unresponsive_attempts(_get_val(borrower, "response_history") or [])
    score -= unresponsive * 0.05

    return round(max(0.05, min(0.95, score)), 2)


def build_segmentation_summary(borrower, signals: List[StrategySignal]) -> dict:
    segment = determine_preliminary_segment(borrower, signals)
    action = determine_preliminary_action(segment, borrower, signals)
    channel, time_window = get_channel_and_time(borrower)
    recovery_prob = estimate_recovery_probability(borrower, signals)
    priority = calculate_priority_score(borrower, signals)
    return {
        "preliminary_segment": segment,
        "preliminary_action": action,
        "recommended_channel": channel,
        "recommended_time": time_window,
        "recovery_probability": recovery_prob,
        "priority_score": priority,
    }
