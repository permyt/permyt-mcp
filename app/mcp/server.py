"""
FastMCP server exposing PERMYT requester tools for AI agents.

Supports two transport modes:
    - Streamable HTTP (hosted): OAuth 2.0 auth (with DRF token fallback)
    - stdio (local): Management command with --token flag

Tools:
    permyt_request_access  — Submit natural-language data request
    permyt_check_access    — Poll status; if completed, fetch data from providers
    permyt_request_and_fetch — Submit + poll until resolved (convenience)
"""

import asyncio
import json
import logging
import time

from django.conf import settings

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context

from app.core.requests.client import PermytClient
from app.core.users.authtoken.models import Token
from app.core.users.models import User

from .provider import PermytOAuthProvider

logger = logging.getLogger("console")

MCP_INSTRUCTIONS = (
    "PERMYT lets you request access to user data held by external services "
    "(banks, healthcare, employers, etc.) on behalf of the user.\n\n"
    "HOW IT WORKS:\n"
    "- Describe what data you need in plain language. You do NOT need to know "
    "what services or providers the user has connected — the PERMYT broker's AI "
    "figures out which provider(s) can satisfy your request and what minimal "
    "permissions are needed.\n"
    "- The user sees a summary of your request on their PERMYT mobile app and "
    "chooses to approve or deny it.\n"
    "- If approved, you receive the actual data from the provider(s).\n\n"
    "TIPS:\n"
    "- Be specific in your description. 'Read the user's latest bank statement' "
    "works better than 'get financial data'.\n"
    "- If a request returns 'unavailable', no connected provider can satisfy it — "
    "this is normal, not an error.\n"
    "- If a request returns 'incomplete', the broker couldn't extract required "
    "parameters from your description. Try being more specific.\n"
    "- Use permyt_request_and_fetch for simple one-shot requests.\n"
    "- Use permyt_request_access + permyt_check_access separately when you want "
    "to do other work while waiting for user approval.\n"
    "- The user must approve on their mobile device — tell them you're waiting "
    "for their approval if using the polling approach."
)


# ---------------------------------------------------------------------------
# OAuth provider + FastMCP setup
# ---------------------------------------------------------------------------

_oauth_provider = PermytOAuthProvider()

_issuer_url = getattr(settings, "MCP_ISSUER_URL", settings.BASE_URL.rstrip("/") + "/mcp")
_server_url = getattr(settings, "MCP_SERVER_URL", settings.BASE_URL.rstrip("/") + "/mcp")

mcp = FastMCP(
    "permyt",
    instructions=MCP_INSTRUCTIONS,
    streamable_http_path="/",
    auth_server_provider=_oauth_provider,
    auth=AuthSettings(
        issuer_url=_issuer_url,
        resource_server_url=_server_url,
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
    ),
)


# ---------------------------------------------------------------------------
# Auth: per-request (OAuth) with fallback to module-level (stdio)
# ---------------------------------------------------------------------------

# Module-level token — set by management command for stdio mode
_stdio_auth_token: str | None = None


def set_stdio_auth_token(token: str):
    """Set the auth token for stdio mode (called by management command)."""
    global _stdio_auth_token
    _stdio_auth_token = token


def _get_client_and_user(auth_token: str):
    """Look up Django User by DRF auth token, return (PermytClient, User).

    Used only for stdio mode fallback.
    """
    try:
        token_obj = Token.objects.select_related("user").get(key=auth_token)
    except Token.DoesNotExist as exc:
        raise ValueError(f"Invalid auth token: {auth_token[:8]}...") from exc

    user = token_obj.user
    if not user.permyt_user_id:
        raise ValueError("User has no permyt_user_id. Please connect via QR login first.")

    return PermytClient(), user


async def _get_user_from_context(ctx: Context):
    """Extract authenticated user from Context.

    OAuth mode: Uses the MCP auth middleware contextvar (PermytAccessToken with user_id).
    stdio mode: Falls back to module-level _stdio_auth_token.

    Returns (PermytClient, User).
    """
    # OAuth mode: get user from auth context (set by MCP auth middleware)
    access_token = get_access_token()
    if access_token:
        user_id = getattr(access_token, "user_id", None)
        if user_id:
            user = await asyncio.to_thread(User.objects.get, id=user_id)
            if not user.permyt_user_id:
                raise ValueError("User has no permyt_user_id. Please connect via QR login first.")
            return PermytClient(), user

    # stdio mode fallback
    if _stdio_auth_token:
        return await asyncio.to_thread(_get_client_and_user, _stdio_auth_token)

    raise ValueError(
        "No auth token found. "
        "Hosted: OAuth authentication required. "
        "stdio: set PERMYT_AUTH_TOKEN env var."
    )


# ---------------------------------------------------------------------------
# Streamable HTTP app factory
# ---------------------------------------------------------------------------


def create_mcp_app():
    """Create the Starlette ASGI app for Streamable HTTP transport.

    Returns a FastMCP Streamable HTTP app with OAuth auth routes.
    ASGI router strips /mcp prefix, so streamable_http_path="/" matches
    external /mcp path after stripping.
    """
    return mcp.streamable_http_app()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def permyt_request_access(description: str, ctx: Context = None) -> str:
    """Request access to user data through PERMYT.

    Describe what data you need in plain language. You don't need to know
    what services or providers the user has — PERMYT's AI determines the
    minimal permissions needed and routes the request for user approval.

    After calling this, tell the user you're waiting for their approval
    on the PERMYT mobile app, then poll with permyt_check_access.

    Args:
        description: What data you need, in natural language. Be specific.
                     Good: "Read the user's latest bank statement for March 2025"
                     Good: "Get the user's employment verification letter"
                     Bad:  "get financial data" (too vague, may return incomplete)
    """
    client, user = await _get_user_from_context(ctx)

    result = await asyncio.to_thread(
        client.request_access,
        {
            "user_id": str(user.permyt_user_id),
            "description": description,
        },
    )

    return json.dumps(result, default=str)


@mcp.tool()
async def permyt_check_access(request_id: str, ctx: Context = None) -> str:
    """Check status of a pending request and fetch data if approved.

    Poll this after permyt_request_access. When the user approves,
    this automatically calls the provider(s) and returns the actual data.

    Args:
        request_id: The request_id from permyt_request_access.

    Returns:
        JSON with status. If completed, includes data from provider(s).
        Statuses: pending (waiting for user), completed (data included),
        rejected (user denied), incomplete (description too vague),
        unavailable (no provider can satisfy this request).
    """
    client, _user = await _get_user_from_context(ctx)

    result = await asyncio.to_thread(client.check_access, request_id)

    # If approved with services, call providers to get actual data
    if result.get("status") == "approved" and result.get("services"):
        try:
            data = await asyncio.to_thread(client.call_services, result["services"])
            return json.dumps(
                {"request_id": request_id, "status": "completed", "data": data},
                default=str,
            )
        except Exception as exc:
            logger.error(f"check_access call_services failed: {exc}", exc_info=True)
            return json.dumps(
                {
                    "request_id": request_id,
                    "status": "error",
                    "error": "Failed to fetch data from provider.",
                },
                default=str,
            )

    return json.dumps(result, default=str)


@mcp.tool()
async def permyt_request_and_fetch(
    description: str, max_wait_seconds: int = 120, ctx: Context = None
) -> str:
    """Request user data and wait for the result in one step.

    Best for simple requests. Submits the request, then polls until the
    user approves/denies on their PERMYT mobile app or timeout is reached.

    Tell the user you're waiting for their approval while this runs.

    Args:
        description: What data you need, in natural language. Be specific.
                     Good: "Read the user's mission log"
                     Good: "Get the user's health insurance policy number"
        max_wait_seconds: How long to wait for user approval (default 120).

    Returns:
        JSON with status and data (if approved), or timeout/rejection reason.
    """
    client, user = await _get_user_from_context(ctx)

    # Submit request
    status = await asyncio.to_thread(
        client.request_access,
        {
            "user_id": str(user.permyt_user_id),
            "description": description,
        },
    )

    request_id = status.get("request_id")
    if not request_id:
        return json.dumps({"error": "No request_id returned", "raw": status}, default=str)

    # Poll until resolved
    terminal = {"approved", "denied", "rejected", "incomplete", "unavailable"}
    deadline = time.time() + max_wait_seconds

    while time.time() < deadline:
        await asyncio.sleep(3)

        result = await asyncio.to_thread(client.check_access, request_id)
        result_status = result.get("status")

        if result_status in terminal:
            # If approved with services, call providers
            if result_status == "approved" and result.get("services"):
                try:
                    data = await asyncio.to_thread(client.call_services, result["services"])
                    return json.dumps(
                        {"request_id": request_id, "status": "completed", "data": data},
                        default=str,
                    )
                except Exception as exc:
                    logger.error(f"request_and_fetch call_services failed: {exc}", exc_info=True)
                    return json.dumps(
                        {
                            "request_id": request_id,
                            "status": "error",
                            "error": "Failed to fetch data from provider.",
                        },
                        default=str,
                    )

            return json.dumps(
                {
                    "request_id": request_id,
                    "status": result_status,
                    "reason": result.get("reason"),
                },
                default=str,
            )

    return json.dumps(
        {"request_id": request_id, "status": "timeout"},
        default=str,
    )
