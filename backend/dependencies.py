from fastapi import Header, Request

from backend.security import check_rate_limit, require_role



def require_agent_or_supervisor(
    request: Request,
    x_api_key: str = Header(None, alias="X-API-Key"),
) -> str:
    check_rate_limit(request, x_api_key)
    return require_role(x_api_key, {"agent", "supervisor"})


def require_supervisor(
    request: Request,
    x_api_key: str = Header(None, alias="X-API-Key"),
) -> str:
    check_rate_limit(request, x_api_key)
    return require_role(x_api_key, {"supervisor"})
