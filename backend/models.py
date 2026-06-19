import re
from typing import Optional, List, Literal

from pydantic import BaseModel, Field, field_validator

ALLOWED_BEHAVIORS = {"on_time", "occasional_late", "chronic_late"}
ALLOWED_CHANNELS = {"sms", "email", "call"}
ALLOWED_HARDSHIP = {
    "job_loss", "medical", "business_closure", "family_emergency",
    "disability", "natural_disaster", "other",
}


class OutreachRecord(BaseModel):
    channel: Literal["sms", "email", "call"]
    date: str = Field(max_length=20)
    responded: bool
    outcome: Optional[str] = Field(default=None, max_length=200)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("date must be YYYY-MM-DD")
        return v


class RepaymentPromise(BaseModel):
    date: str = Field(max_length=20)
    amount: float = Field(ge=0, le=10_000_000)
    kept: bool

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("date must be YYYY-MM-DD")
        return v


class BorrowerInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=8, max_length=20)
    email: str = Field(max_length=120)
    loan_amount: float = Field(gt=0, le=10_000_000)
    days_past_due: int = Field(ge=0, le=999)
    overdue_amount: float = Field(ge=0, le=10_000_000)
    prior_payment_behavior: Literal["on_time", "occasional_late", "chronic_late"]
    preferred_channel: Literal["sms", "email", "call"]
    hardship_indicators: List[str] = Field(default_factory=list, max_length=10)
    response_history: List[OutreachRecord] = Field(default_factory=list, max_length=50)
    repayment_promises: List[RepaymentPromise] = Field(default_factory=list, max_length=20)
    partial_payments_last_30d: float = Field(ge=0, le=10_000_000, default=0.0)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v_clean):
            raise ValueError("invalid email format")
        return v_clean

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-()]", "", v)
        if not re.match(r"^\+?\d{8,15}$", cleaned):
            raise ValueError("invalid phone format")
        return v.strip()

    @field_validator("hardship_indicators")
    @classmethod
    def validate_hardship(cls, indicators: List[str]) -> List[str]:
        cleaned = []
        for item in indicators:
            key = item.strip().lower().replace(" ", "_")
            if key and key not in ALLOWED_HARDSHIP:
                raise ValueError(f"unsupported hardship indicator: {item}")
            if key:
                cleaned.append(key)
        return cleaned


class StrategySignal(BaseModel):
    type: str
    severity: str
    evidence: str
    confidence: str


class StrategyReport(BaseModel):
    borrower_id: str
    segment: str
    next_best_action: str
    recommended_channel: str
    recommended_time: str
    message_draft: str
    strategy_rationale: str
    strategy_signals: List[StrategySignal]
    recovery_probability: Optional[float] = None
    priority_score: Optional[float] = None


class AgentQuery(BaseModel):
    question: str = Field(min_length=3, max_length=500)

    @field_validator("question")
    @classmethod
    def sanitize_question(cls, v: str) -> str:
        v = v.strip()
        if re.search(r"<script|javascript:|on\w+\s*=", v, re.IGNORECASE):
            raise ValueError("question contains disallowed content")
        return v


class AgentAnswer(BaseModel):
    answer: str


class BorrowerRecord(BaseModel):
    id: str
    name: str
    phone: str
    email: str
    loan_amount: float
    days_past_due: int
    overdue_amount: float
    prior_payment_behavior: str
    preferred_channel: str
    hardship_indicators: List[str] = []
    response_history: List[OutreachRecord] = []
    repayment_promises: List[RepaymentPromise] = []
    partial_payments_last_30d: float = 0.0
    ingested_timestamp: str
    segment: Optional[str] = None
    next_best_action: Optional[str] = None
    recommended_channel: Optional[str] = None
    recommended_time: Optional[str] = None
    message_draft: Optional[str] = None
    strategy_rationale: Optional[str] = None
    recovery_probability: Optional[float] = None
    priority_score: Optional[float] = None
    ai_prompt_sent: Optional[str] = None
    ai_raw_response: Optional[str] = None
    ai_analysis_timestamp: Optional[str] = None
    analysis_method: Optional[str] = None
    action_audit_log: List[dict] = []
