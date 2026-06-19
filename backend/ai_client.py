import os
import re
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

from backend.models import StrategySignal
from backend import segmentation

load_dotenv()

LLM_WRAPPER_URL = os.environ.get("LLM_WRAPPER_URL", "https://llm-wrapper-741152993481.asia-south1.run.app/llm/query")
LLM_WRAPPER_TOKEN = os.environ.get("LLM_WRAPPER_TOKEN", "")

KNOWN_SEGMENTS = set(segmentation.SEGMENTS)
KNOWN_ACTIONS = set(segmentation.ACTIONS)

# Regex pattern to detect non-compliant/threatening language in AI-generated message drafts.
# Covers direct phrases AND common paraphrased variants, including inflected forms
# (e.g. arrest/arrested, repossess/repossessed) to prevent compliance violations.
_THREAT_PATTERN = re.compile(
    r"\b("
    # Legal threats & proceedings (all forms)
    r"legal\s+(action|proceeding|notice|consequence|step|measure|recourse|remedy)"
    r"|file\s+(a\s+)?suit"
    r"|take\s+(legal|court|judicial)"
    r"|court\s+(notice|order|summons?|action|proceeding)"
    r"|summons?\b"
    r"|litigation"
    r"|lawsuit"
    r"|sue\s+you"
    # Criminal threats — stem + optional suffix to catch inflections
    r"|arrest\w*"          # arrest, arrests, arrested, arresting
    r"|jail\w*"            # jail, jailed, jailing
    r"|prison\w*"          # prison, prisoner, imprisonment
    r"|imprison\w*"        # imprison, imprisoned, imprisonment
    r"|detain\w*"          # detain, detained, detention
    r"|criminal\s+(action|charge|complaint|case|proceeding)"
    r"|prosecut\w*"        # prosecute, prosecuted, prosecution
    r"|fir\b"              # First Information Report (India-specific)
    # Asset threats — stem + optional suffix
    r"|seiz\w*"            # seize, seized, seizure
    r"|attach\s+(your\s+)?(property|asset|account)"
    r"|repossess\w*"       # repossess, repossessed, repossession
    r"|foreclos\w*"        # foreclose, foreclosed, foreclosure
    r"|wage\s+garnish\w*"  # wage garnish, wage garnishment
    # Direct harassment / coercion — stem + optional suffix
    r"|harass\w*"          # harass, harassed, harassment, harassing
    r"|threaten\w*"        # threaten, threatened, threatening, threat
    r"|\bthreat\b"         # standalone 'threat'
    r"|intimidat\w*"       # intimidate, intimidated, intimidation
    r"|coerc\w*"           # coerce, coerced, coercion
    r"|blackmail\w*"       # blackmail, blackmailed, blackmailing
    r")",
    re.IGNORECASE,
)


def clean_json_response(raw_text):
    text = raw_text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1], strict=False)
        raise


def truncate_rationale(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    processed = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        content = stripped.lstrip("•-* ").strip()
        words = content.split()
        if len(words) > 25:
            content = " ".join(words[:25]) + "..."
        processed.append(f"• {content}")
    return "\n".join(processed[:5])


def sanitize_message_draft(draft: str) -> str:
    """Strip threatening, coercive, or legally non-compliant language from AI-generated drafts.

    Uses a compiled regex covering direct banned phrases AND common paraphrased
    variants (e.g. 'legal proceedings', 'court notice', 'criminal complaint') to
    prevent compliance violations even when the LLM rephrases threat language.
    """
    if not draft:
        return ""
    cleaned = _THREAT_PATTERN.sub("[removed — non-compliant language]", draft)
    return cleaned.strip()[:600]


def _format_history(response_history) -> str:
    if not response_history:
        return "No prior outreach recorded"
    lines = []
    for i, entry in enumerate(response_history, 1):
        ch = segmentation._get_val(entry, "channel") or "unknown"
        date = segmentation._get_val(entry, "date") or "N/A"
        responded = "Yes" if segmentation._get_val(entry, "responded") else "No"
        outcome = segmentation._get_val(entry, "outcome") or "N/A"
        lines.append(f"{i}. {date} via {ch} — Responded: {responded} — Outcome: {outcome}")
    return "\n".join(lines)


def _format_promises(promises) -> str:
    if not promises:
        return "No repayment promises on record"
    lines = []
    for i, p in enumerate(promises, 1):
        date = segmentation._get_val(p, "date") or "N/A"
        amount = segmentation._get_val(p, "amount") or 0
        kept = "Kept" if segmentation._get_val(p, "kept") else "Broken"
        lines.append(f"{i}. {date} — ₹{amount:,.0f} — {kept}")
    return "\n".join(lines)


def _format_signals(signals: list) -> str:
    if not signals:
        return "No strategy signals detected"
    lines = []
    for i, sig in enumerate(signals, 1):
        sig_type = segmentation._get_val(sig, "type")
        severity = segmentation._get_val(sig, "severity")
        evidence = segmentation._get_val(sig, "evidence")
        lines.append(f"{i}. {sig_type} (Severity: {severity}) — {evidence}")
    return "\n".join(lines)


def build_strategy_prompt(borrower, signals, summary: dict):
    name = segmentation._get_val(borrower, "name") or "N/A"
    phone = segmentation._get_val(borrower, "phone") or "N/A"
    email = segmentation._get_val(borrower, "email") or "N/A"
    loan_amount = segmentation._get_val(borrower, "loan_amount") or 0
    dpd = segmentation._get_val(borrower, "days_past_due") or 0
    overdue = segmentation._get_val(borrower, "overdue_amount") or 0
    behavior = segmentation._get_val(borrower, "prior_payment_behavior") or "N/A"
    preferred = segmentation._get_val(borrower, "preferred_channel") or "N/A"
    hardship = ", ".join(segmentation._get_val(borrower, "hardship_indicators") or []) or "None"
    partial = segmentation._get_val(borrower, "partial_payments_last_30d") or 0
    history_str = _format_history(segmentation._get_val(borrower, "response_history"))
    promises_str = _format_promises(segmentation._get_val(borrower, "repayment_promises"))
    signals_str = _format_signals(signals)

    prelim_segment = summary["preliminary_segment"]
    prelim_action = summary["preliminary_action"]
    prelim_channel = summary["recommended_channel"]
    prelim_time = summary["recommended_time"]
    recovery_prob = summary["recovery_probability"]

    prompt = f"""You are a collections strategy assistant for a regulated fintech lender. Recommend respectful, compliant outreach grounded ONLY in the data below.

BORROWER DATA:
Name: {name}
Phone: {phone}
Email: {email}
Loan Amount: ₹{loan_amount:,.0f}
Days Past Due: {dpd}
Overdue Amount: ₹{overdue:,.0f}
Prior Payment Behavior: {behavior}
Preferred Channel: {preferred}
Hardship Indicators: {hardship}
Partial Payments (last 30 days): ₹{partial:,.0f}

OUTREACH HISTORY:
{history_str}

REPAYMENT PROMISES:
{promises_str}

STRATEGY SIGNALS (from rule engine — do NOT invent new ones):
{signals_str}

RULE-ENGINE PRELIMINARY RECOMMENDATION:
Segment: {prelim_segment}
Next Best Action: {prelim_action}
Suggested Channel: {prelim_channel}
Suggested Time: {prelim_time}
Estimated Recovery Probability: {recovery_prob:.0%}

ALLOWED SEGMENTS (use exactly one): {", ".join(sorted(KNOWN_SEGMENTS))}
ALLOWED ACTIONS (use exactly one): {", ".join(sorted(KNOWN_ACTIONS))}

COMPLIANCE & TONE RULES:
- Use empathetic, respectful language. Never threaten, harass, or use aggressive legal language.
- The message_draft must be customer-safe and suitable for SMS/email — warm, clear, and professional.
- Ground every decision in the signals and borrower data above. Do NOT invent facts.
- segment and next_best_action should align with the preliminary recommendation unless signals clearly contradict it.
- strategy_rationale: one bullet (•) per strategy signal, max 5 bullets, each under 25 words.

TASK:
1. Confirm or refine the segment and next_best_action.
2. Confirm recommended_channel and recommended_time.
3. Write a short, empathetic message_draft (2–4 sentences, use borrower first name).
4. Write strategy_rationale bullets explaining the recommendation.
5. Provide recovery_probability as a decimal between 0 and 1.

Respond with ONLY valid JSON, no markdown:
{{"segment": "...", "next_best_action": "...", "recommended_channel": "...", "recommended_time": "...", "message_draft": "...", "strategy_rationale": "• point one\\n• point two", "recovery_probability": 0.65}}"""
    return prompt


def call_llm_wrapper(prompt):
    url = os.environ.get("LLM_WRAPPER_URL") or LLM_WRAPPER_URL
    token = os.environ.get("LLM_WRAPPER_TOKEN") or LLM_WRAPPER_TOKEN
    if not url or not token:
        raise ValueError("LLM_WRAPPER_URL or LLM_WRAPPER_TOKEN is not set.")

    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        },
        json={"prompt": prompt},
        timeout=30
    )
    response.raise_for_status()
    res_json = response.json()

    raw_text = None
    for key in ["reply", "response", "content", "text"]:
        if key in res_json:
            raw_text = res_json[key]
            break
    if raw_text is None:
        raw_text = res_json.get("reply", json.dumps(res_json))

    return raw_text


def _fallback_strategy(borrower, signals, summary, prompt, raw_text=None, error=None):
    first_name = (segmentation._get_val(borrower, "name") or "there").split()[0]
    overdue = segmentation._get_val(borrower, "overdue_amount") or 0
    action = summary["preliminary_action"]
    segment = summary["preliminary_segment"]

    draft_templates = {
        "SMS Reminder": f"Hi {first_name}, this is a friendly reminder that your payment of ₹{overdue:,.0f} is overdue. We're here to help if you need support — please reply or call us to discuss options.",
        "Email": f"Dear {first_name}, we noticed your account has an overdue balance of ₹{overdue:,.0f}. Please contact us at your convenience — we can work with you on a suitable repayment plan.",
        "Agent Call": f"Hi {first_name}, we'd like to speak with you about your overdue balance of ₹{overdue:,.0f}. Our team is ready to discuss flexible options at a time that works for you.",
        "Payment Plan Offer": f"Hi {first_name}, we understand managing payments can be challenging. We'd like to offer a structured payment plan for your ₹{overdue:,.0f} balance. Please reach out so we can find a plan that works for you.",
        "Hardship Support": f"Hi {first_name}, we're aware you may be going through a difficult time. Our hardship support team can help review your account and explore accommodations for your ₹{overdue:,.0f} balance.",
        "Escalation": f"Dear {first_name}, your account requires urgent attention with an overdue balance of ₹{overdue:,.0f}. Please contact us promptly to discuss resolution options before further steps are considered.",
        "Manual Review": f"Hi {first_name}, your account has been flagged for a specialist review. A team member will contact you shortly regarding your ₹{overdue:,.0f} overdue balance.",
    }

    rationale_lines = [f"• {segmentation._get_val(s, 'evidence')}" for s in signals[:5]]
    if not rationale_lines:
        rationale_lines = ["• No significant strategy signals — standard outreach recommended."]

    err_note = f" ({type(error).__name__})" if error else ""
    rationale_lines.append(f"• AI unavailable{err_note} — using rule-based fallback strategy.")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "segment": segment,
        "next_best_action": action,
        "recommended_channel": summary["recommended_channel"],
        "recommended_time": summary["recommended_time"],
        "message_draft": draft_templates.get(action, draft_templates["SMS Reminder"]),
        "strategy_rationale": "\n".join(rationale_lines),
        "recovery_probability": summary["recovery_probability"],
        "priority_score": summary["priority_score"],
        "ai_prompt_sent": prompt,
        "ai_raw_response": raw_text or (str(error) if error else None),
        "ai_analysis_timestamp": ts,
        "analysis_method": "rule_based_fallback",
    }


def get_strategy_recommendation(borrower, signals):
    summary = segmentation.build_segmentation_summary(borrower, signals)
    prompt = build_strategy_prompt(borrower, signals, summary)
    raw_text = None
    try:
        raw_text = call_llm_wrapper(prompt)
        parsed = clean_json_response(raw_text)

        segment = parsed.get("segment") or summary["preliminary_segment"]
        if segment not in KNOWN_SEGMENTS:
            segment = summary["preliminary_segment"]

        action = parsed.get("next_best_action") or summary["preliminary_action"]
        if action not in KNOWN_ACTIONS:
            action = summary["preliminary_action"]

        rationale = truncate_rationale(parsed.get("strategy_rationale", ""))
        if not rationale.strip():
            rationale = "• Strategy based on borrower delinquency profile and outreach history."

        recovery = parsed.get("recovery_probability")
        if recovery is None:
            recovery = summary["recovery_probability"]
        else:
            recovery = round(max(0.0, min(1.0, float(recovery))), 2)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "segment": segment,
            "next_best_action": action,
            "recommended_channel": parsed.get("recommended_channel") or summary["recommended_channel"],
            "recommended_time": parsed.get("recommended_time") or summary["recommended_time"],
            "message_draft": sanitize_message_draft(parsed.get("message_draft", "")),
            "strategy_rationale": rationale,
            "recovery_probability": recovery,
            "priority_score": summary["priority_score"],
            "ai_prompt_sent": prompt,
            "ai_raw_response": raw_text,
            "ai_analysis_timestamp": ts,
            "analysis_method": "ai",
        }
    except Exception as e:
        return _fallback_strategy(borrower, signals, summary, prompt, raw_text, error=e)


def build_query_prompt(borrower, signals, question):
    name = segmentation._get_val(borrower, "name") or "N/A"
    segment = segmentation._get_val(borrower, "segment") or segmentation.determine_preliminary_segment(
        borrower, signals
    )
    action = segmentation._get_val(borrower, "next_best_action") or "N/A"
    signals_str = _format_signals(signals)

    prompt = f"""You are a collections strategy assistant. Answer the agent's question using ONLY the borrower data and strategy signals below. Be concise, factual, and explain the reasoning behind the recommended approach.

BORROWER: {name}
CURRENT SEGMENT: {segment}
RECOMMENDED ACTION: {action}

STRATEGY SIGNALS:
{signals_str}

AGENT QUESTION:
{question}

Respond with ONLY valid JSON: {{"answer": "..."}}"""
    return prompt


def answer_agent_query(borrower, signals, question):
    prompt = build_query_prompt(borrower, signals, question)
    try:
        raw_text = call_llm_wrapper(prompt)
        parsed = clean_json_response(raw_text)
        return parsed.get("answer", "Unable to generate an answer from the available data.")
    except Exception:
        segment = segmentation.determine_preliminary_segment(borrower, signals)
        action = segmentation.determine_preliminary_action(segment, borrower, signals)
        return (
            f"Based on rule-engine analysis: segment is '{segment}' and recommended action is '{action}'. "
            "Refer to strategy signals in the borrower detail panel for supporting evidence."
        )
