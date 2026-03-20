"""HTTP middleware — IP whitelist, API key auth, request logging."""

from __future__ import annotations

import hmac
import time
from ipaddress import IPv4Address

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from s_peach.server.models import AppState

logger = structlog.get_logger()


async def ip_whitelist_middleware(request: Request, call_next) -> Response:
    """Check client IP against configured whitelist."""
    state: AppState = request.app.state.app_state
    client_ip = request.client.host if request.client else None

    if client_ip is None:
        return JSONResponse(
            status_code=403,
            content={"detail": "Could not determine client IP"},
        )

    networks = state.settings.ip_networks
    if not networks:
        return await call_next(request)
    try:
        ip = IPv4Address(client_ip)
    except ValueError:
        logger.warning("ip_invalid", client_ip=client_ip)
        return JSONResponse(
            status_code=403,
            content={"detail": f"Invalid client IP: {client_ip}"},
        )
    if not any(ip in net for net in networks):
        logger.warning("ip_denied", client_ip=client_ip)
        return JSONResponse(
            status_code=403,
            content={"detail": f"IP {client_ip} not in whitelist"},
        )

    return await call_next(request)


async def api_key_middleware(request: Request, call_next) -> Response:
    """Check X-API-Key header when api_key is configured. /health is exempt."""
    state: AppState = request.app.state.app_state
    expected_key = state.settings.api_key

    if expected_key is None:
        return await call_next(request)

    if request.url.path == "/health":
        return await call_next(request)

    provided_key = request.headers.get("X-API-Key")
    if not provided_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing API key. Provide X-API-Key header."},
        )
    if not hmac.compare_digest(provided_key, expected_key):
        logger.warning("api_key_rejected", client_ip=request.client.host if request.client else "unknown")
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid API key"},
        )

    return await call_next(request)


async def request_logging_middleware(request: Request, call_next) -> Response:
    """Log all requests with method, path, status, duration, client IP."""
    client_ip = request.client.host if request.client else "unknown"
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.debug(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        client_ip=client_ip,
    )
    return response
