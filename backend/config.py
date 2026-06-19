import os
from dotenv import load_dotenv

load_dotenv()

# API keys — role is derived from key, not from a spoofable header.
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "dev-agent-key-change-me")
SUPERVISOR_API_KEY = os.getenv("SUPERVISOR_API_KEY", "dev-supervisor-key-change-me")

# Data store path (override in tests via env)
BORROWERS_DB_PATH = os.getenv(
    "BORROWERS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "borrowers.json"),
)

# Rate limiting
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# CORS — comma-separated origins; empty means same-origin only
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if o.strip()
]

# Borrower ID format
BORROWER_ID_PATTERN = r"^BOR\d{3,6}$"

# Production safety check
if os.getenv("APP_ENV") == "production":
    if AGENT_API_KEY == "dev-agent-key-change-me" or SUPERVISOR_API_KEY == "dev-supervisor-key-change-me":
        raise RuntimeError("Default API keys must be changed when APP_ENV=production")
