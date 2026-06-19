import logging
import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from backend.models import BorrowerInput, StrategyReport, AgentQuery, AgentAnswer, StrategySignal
from backend.segmentation import run_segmentation, calculate_priority_score
from backend.data import get_all_borrowers, get_borrower_by_id, add_borrower, update_borrower
from backend.ai_client import get_strategy_recommendation, answer_agent_query
from backend.config import ALLOWED_ORIGINS
from backend.dependencies import require_agent_or_supervisor, require_supervisor
from backend.security import (
    SecurityHeadersMiddleware,
    validate_borrower_id,
    redact_borrower_for_list,
    redact_borrower_for_detail,
)

load_dotenv()
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")


def create_app() -> FastAPI:
    application = FastAPI(
        title="AI-Based Collections Strategy Optimizer",
        docs_url="/docs" if os.getenv("APP_ENV") != "production" else None,
        redoc_url=None,
    )

    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/")
    def read_root():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @application.get("/health")
    def health_check():
        return {"status": "ok"}

    @application.post("/borrowers", response_model=StrategyReport)
    def ingest_borrower(
        borrower: BorrowerInput,
        role: str = Depends(require_supervisor),
    ):
        try:
            borrower_dict = borrower.model_dump()
            borrower_dict["ingested_timestamp"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            signals = run_segmentation(borrower_dict)
            ai_result = get_strategy_recommendation(borrower_dict, signals)
            borrower_dict = _apply_strategy_to_borrower(borrower_dict, ai_result, signals)

            saved = add_borrower(borrower_dict)

            return StrategyReport(
                borrower_id=saved["id"],
                segment=ai_result["segment"],
                next_best_action=ai_result["next_best_action"],
                recommended_channel=ai_result["recommended_channel"],
                recommended_time=ai_result["recommended_time"],
                message_draft=ai_result["message_draft"],
                strategy_rationale=ai_result["strategy_rationale"],
                strategy_signals=[s.model_dump() for s in signals],
                recovery_probability=ai_result.get("recovery_probability"),
                priority_score=borrower_dict.get("priority_score"),
            )
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception:
            logger.exception("ingest_borrower failed")
            raise HTTPException(status_code=500, detail="Internal server error.")

    @application.get("/borrowers")
    def list_borrowers(role: str = Depends(require_agent_or_supervisor)):
        try:
            borrowers = get_all_borrowers()
            borrowers.sort(key=lambda b: b.get("priority_score") or 0, reverse=True)
            return [redact_borrower_for_list(b, role) for b in borrowers]
        except HTTPException:
            raise
        except Exception:
            logger.exception("list_borrowers failed")
            raise HTTPException(status_code=500, detail="Internal server error.")

    @application.get("/dashboard/priority")
    def priority_dashboard(role: str = Depends(require_agent_or_supervisor)):
        try:
            borrowers = get_all_borrowers()
            queue = []
            for b in borrowers:
                priority = b.get("priority_score")
                if priority is None:
                    signals = run_segmentation(b)
                    priority = calculate_priority_score(b, signals)
                entry = {
                    "id": b.get("id"),
                    "name": b.get("name"),
                    "days_past_due": b.get("days_past_due"),
                    "overdue_amount": b.get("overdue_amount"),
                    "segment": b.get("segment") or "Unassigned",
                    "next_best_action": b.get("next_best_action") or "No Action",
                    "recovery_probability": b.get("recovery_probability"),
                    "priority_score": priority,
                }
                if role == "agent":
                    entry.pop("name", None)
                    entry["name_masked"] = (b.get("name") or "")[:1] + "***"
                queue.append(entry)
            queue.sort(key=lambda x: x["priority_score"], reverse=True)
            return {"total": len(queue), "queue": queue}
        except HTTPException:
            raise
        except Exception:
            logger.exception("priority_dashboard failed")
            raise HTTPException(status_code=500, detail="Internal server error.")

    @application.get("/borrowers/{borrower_id}")
    def get_borrower_detail(
        borrower_id: str,
        role: str = Depends(require_agent_or_supervisor),
    ):
        try:
            validate_borrower_id(borrower_id)
            borrower = get_borrower_by_id(borrower_id)
            if borrower is None:
                raise HTTPException(status_code=404, detail="Borrower not found")

            signals = run_segmentation(borrower)
            detail = redact_borrower_for_detail(borrower, role)
            return {**detail, "strategy_signals": [s.model_dump() for s in signals]}
        except HTTPException:
            raise
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid borrower ID format.")
        except Exception:
            logger.exception("get_borrower_detail failed")
            raise HTTPException(status_code=500, detail="Internal server error.")

    @application.post("/borrowers/{borrower_id}/query", response_model=AgentAnswer)
    def query_borrower(
        borrower_id: str,
        query: AgentQuery,
        role: str = Depends(require_agent_or_supervisor),
    ):
        try:
            validate_borrower_id(borrower_id)
            borrower = get_borrower_by_id(borrower_id)
            if borrower is None:
                raise HTTPException(status_code=404, detail="Borrower not found")

            signals = run_segmentation(borrower)
            answer = answer_agent_query(borrower, signals, query.question)
            return AgentAnswer(answer=answer)
        except HTTPException:
            raise
        except Exception:
            logger.exception("query_borrower failed")
            raise HTTPException(status_code=500, detail="Internal server error.")

    @application.post("/borrowers/{borrower_id}/re-strategize")
    def re_strategize(
        borrower_id: str,
        role: str = Depends(require_agent_or_supervisor),
    ):
        try:
            validate_borrower_id(borrower_id)
            borrower = get_borrower_by_id(borrower_id)
            if borrower is None:
                raise HTTPException(status_code=404, detail="Borrower not found")

            signals = run_segmentation(borrower)
            ai_result = get_strategy_recommendation(borrower, signals)
            borrower = _apply_strategy_to_borrower(borrower, ai_result, signals)
            update_borrower(borrower_id, borrower)

            response = {
                "segment": ai_result["segment"],
                "next_best_action": ai_result["next_best_action"],
                "recommended_channel": ai_result["recommended_channel"],
                "recommended_time": ai_result["recommended_time"],
                "message_draft": ai_result["message_draft"],
                "strategy_rationale": ai_result["strategy_rationale"],
                "recovery_probability": ai_result.get("recovery_probability"),
                "priority_score": borrower.get("priority_score"),
                "ai_analysis_timestamp": ai_result.get("ai_analysis_timestamp"),
                "analysis_method": ai_result.get("analysis_method"),
            }
            if role == "supervisor":
                response["ai_prompt_sent"] = ai_result.get("ai_prompt_sent")
                response["ai_raw_response"] = ai_result.get("ai_raw_response")
            return response
        except HTTPException:
            raise
        except Exception:
            logger.exception("re_strategize failed")
            raise HTTPException(status_code=500, detail="Internal server error.")

    return application


def _apply_strategy_to_borrower(borrower_dict, ai_result, signals):
    borrower_dict["segment"] = ai_result.get("segment")
    borrower_dict["next_best_action"] = ai_result.get("next_best_action")
    borrower_dict["recommended_channel"] = ai_result.get("recommended_channel")
    borrower_dict["recommended_time"] = ai_result.get("recommended_time")
    borrower_dict["message_draft"] = ai_result.get("message_draft")
    borrower_dict["strategy_rationale"] = ai_result.get("strategy_rationale")
    borrower_dict["recovery_probability"] = ai_result.get("recovery_probability")
    borrower_dict["priority_score"] = ai_result.get("priority_score") or calculate_priority_score(
        borrower_dict, signals
    )
    borrower_dict["ai_prompt_sent"] = ai_result.get("ai_prompt_sent")
    borrower_dict["ai_raw_response"] = ai_result.get("ai_raw_response")
    borrower_dict["ai_analysis_timestamp"] = ai_result.get("ai_analysis_timestamp")
    borrower_dict["analysis_method"] = ai_result.get("analysis_method")

    audit_entry = {
        "timestamp": ai_result.get("ai_analysis_timestamp"),
        "action_recommended": ai_result.get("next_best_action"),
        "segment": ai_result.get("segment"),
        "method": ai_result.get("analysis_method"),
        "status": "recommended",
    }
    log = borrower_dict.get("action_audit_log") or []
    log.append(audit_entry)
    borrower_dict["action_audit_log"] = log[-20:]
    return borrower_dict


app = create_app()
