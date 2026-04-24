"""
FastMCP server exposing PERMYT requester tools for AI agents.

Supports two transport modes:
    - Streamable HTTP (hosted): OAuth 2.0 auth (with DRF token fallback)
    - stdio (local): Management command with --token flag

Tools:
    permyt_request_access  — Submit natural-language data request
    permyt_check_access    — Poll status; if completed, fetch data from providers
"""

import asyncio
import json
import logging

from django.conf import settings

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware

from app.core.requests.client import PermytClient
from app.core.users.authtoken.models import Token
from app.core.users.models import User

from .provider import PermytOAuthProvider

logger = logging.getLogger("console")

# ---------------------------------------------------------------------------
# Status messages for user-facing feedback
# ---------------------------------------------------------------------------

STATUS_MESSAGES = {
    "queued": "Request queued, waiting for broker...",
    "analyzing": "Broker analyzing request and determining required permissions...",
    "awaiting": "Waiting for user to approve on their PERMYT mobile app...",
    "processing": "User approved! Issuing access tokens...",
}

FAILURE_MESSAGES = {
    "rejected": (
        "The user denied this request on their PERMYT app. "
        "Do not retry the same request. Ask the user if they'd like to "
        "try a different approach or need something else."
    ),
    "incomplete": (
        "The broker couldn't determine what data you need from your description. "
        "Ask the user to clarify what specific data they want (e.g. which account, "
        "what time period, what document) and submit a new request with "
        "permyt_request_access using a more detailed description."
    ),
    "unavailable": (
        "No connected provider can satisfy this request. The user may not have "
        "the relevant service connected to PERMYT. Let the user know and ask if "
        "they have another way to provide the data, or if they'd like to connect "
        "the service first via the PERMYT mobile app."
    ),
}

MCP_INSTRUCTIONS = (
    "PERMYT lets you request access to user data held by external services "
    "(banks, healthcare, employers, etc.) on behalf of the user.\n\n"
    "HOW IT WORKS:\n"
    "0. (Optional) Call permyt_view_scopes to see what data is available "
    "before making a request. This returns services and their scopes "
    "(data types) the user has connected.\n"
    "1. Call permyt_request_access with a plain-language description of the data "
    "you need. This returns a request_id immediately.\n"
    "2. Tell the user you're waiting for their approval on the PERMYT mobile app.\n"
    "3. Poll permyt_check_access with the request_id every few seconds. Each call "
    "returns the current status so you can keep the user informed:\n"
    "   - queued: request received, waiting for broker\n"
    "   - analyzing: broker AI is evaluating required permissions\n"
    "   - awaiting: user has been notified, waiting for their approval\n"
    "   - processing: user approved, issuing access tokens\n"
    "   - completed: data is included in the response\n"
    "4. When status is 'completed', the data from the provider(s) is included "
    "in the response. Present it to the user.\n\n"
    "HANDLING FAILURES:\n"
    "- incomplete: Your description was too vague for the broker to determine "
    "what data you need. Ask the user to clarify (which account? what time period? "
    "what document?) and submit a NEW request with a more detailed description.\n"
    "- unavailable: No provider the user has connected can satisfy this request. "
    "Tell the user — they may need to connect the relevant service via the "
    "PERMYT mobile app first.\n"
    "- rejected: The user denied the request. Do NOT retry the same request. "
    "Ask if they'd like something different.\n\n"
    "TIPS:\n"
    "- Use permyt_view_scopes first to understand what data is available, then "
    "craft a precise description for permyt_request_access.\n"
    "- Be specific. 'Read the user's latest bank statement for March 2025' "
    "works better than 'get financial data'.\n"
    "- Tell the user what's happening at each status change — especially when "
    "status is 'awaiting', so they know to check their PERMYT mobile app.\n"
    "- Keep polling until you reach a terminal status (completed, rejected, "
    "incomplete, unavailable). Non-terminal statuses mean the request is still "
    "being processed."
)


# ---------------------------------------------------------------------------
# OAuth provider + FastMCP setup
# ---------------------------------------------------------------------------

_oauth_provider = PermytOAuthProvider()

_issuer_url = getattr(settings, "MCP_ISSUER_URL", settings.BASE_URL.rstrip("/") + "/mcp")
_server_url = getattr(settings, "MCP_SERVER_URL", settings.BASE_URL.rstrip("/") + "/mcp")

# Derive hostname from BASE_URL for DNS rebinding protection
_base_host = settings.BASE_URL.split("://", 1)[-1].rstrip("/")

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
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_base_host, "localhost:*", "127.0.0.1:*"],
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

    Wraps the FastMCP app in CORS middleware so browser-based MCP clients
    (and Claude AI's web interface) can reach the MCP endpoint.
    The MCP SDK adds CORS to auth routes (token, register, revoke) but NOT
    to the main MCP endpoint — we add it here.

    Returns a Starlette ASGI app with OAuth auth routes + CORS.
    ASGI router strips /mcp prefix, so streamable_http_path="/" matches
    external /mcp path after stripping.
    """

    app = mcp.streamable_http_app()
    app = CORSMiddleware(
        app=app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "authorization", "mcp-session-id", "mcp-protocol-version"],
        expose_headers=["mcp-session-id", "mcp-protocol-version"],
    )

    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    logger.info(f"MCP app created: {len(tool_names)} tools registered: {tool_names}")
    return app


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
async def permyt_view_scopes(ctx: Context = None) -> str:
    """View available data scopes the user has connected to PERMYT.

    Returns the list of services and their scopes (data types) that can be
    requested via permyt_request_access. Use this to understand what data
    is available before making a request.

    Each scope includes a name, description, and any required inputs
    that will be locked at approval time.
    """
    client, user = await _get_user_from_context(ctx)

    try:
        result = await asyncio.to_thread(client.view_scopes, str(user.permyt_user_id))
    except Exception as exc:
        logger.error(f"view_scopes failed: {exc}", exc_info=True)
        return json.dumps(
            {"status": "error", "message": "Failed to retrieve available scopes."},
            default=str,
        )

    return json.dumps(result, default=str)


TERMINAL_STATUSES = {"completed", "rejected", "incomplete", "unavailable"}


@mcp.tool()
async def permyt_check_access(request_id: str, ctx: Context = None) -> str:
    """Check status of a pending request and fetch data if completed.

    Poll this after permyt_request_access. When the user approves,
    this automatically calls the provider(s) and returns the actual data.

    Args:
        request_id: The request_id from permyt_request_access.

    Returns:
        JSON with status and message. If completed, includes data from provider(s).
        Statuses: queued (waiting for broker), analyzing (evaluating scopes),
        awaiting (pending user approval), processing (issuing tokens),
        completed (data included), rejected (user denied),
        incomplete (description too vague),
        unavailable (no provider can satisfy this request).
    """
    client, _user = await _get_user_from_context(ctx)

    result = await asyncio.to_thread(client.check_access, request_id)
    status = result.get("status")

    # If completed with services, call providers to get actual data
    if status == "completed" and result.get("services"):
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
                    "message": "Failed to fetch data from provider.",
                },
                default=str,
            )

    # Terminal failure — include actionable message
    if status in FAILURE_MESSAGES:
        return json.dumps(
            {
                "request_id": request_id,
                "status": status,
                "reason": result.get("reason"),
                "message": FAILURE_MESSAGES[status],
            },
            default=str,
        )

    # Intermediate status — include progress message + polling hint
    message = STATUS_MESSAGES.get(status, f"Status: {status}")
    if status not in TERMINAL_STATUSES:
        message += " Poll again with permyt_check_access."

    return json.dumps(
        {"request_id": request_id, "status": status, "message": message},
        default=str,
    )
