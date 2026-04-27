"""
FastMCP server exposing PERMYT requester tools for AI agents.

Supports two transport modes:
    - Streamable HTTP (hosted): OAuth 2.0 auth (with DRF token fallback)
    - stdio (local): Management command with --token flag

Tools:
    permyt_view_scopes     — List the scopes connected to the user.
    permyt_request_access  — Submit a natural-language data request.
    permyt_check_access    — Poll status; on ``completed`` returns the
                             dynamic-input schema for the next step.
    permyt_call_service    — Execute the approved request with dynamic inputs.
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
from app.core.requests.responses import (
    CONSUME_ERROR_MESSAGES,
    consume_pending_service_call,
    endpoint_schema,
    error_envelope,
    flatten_service_data,
    store_pending_service_call,
)
from app.core.users.authtoken.models import Token
from app.core.users.models import User

from .provider import PermytOAuthProvider

logger = logging.getLogger("console")

# ---------------------------------------------------------------------------
# Status messages — user-facing only (no LLM/client instructions)
# ---------------------------------------------------------------------------

STATUS_MESSAGES = {
    "queued": "Request queued, waiting for broker...",
    "analyzing": "Analyzing request and determining required permissions...",
    "awaiting": "Waiting for user to approve on their PERMYT mobile app...",
    "processing": "User approved! Issuing access tokens...",
}

CLIENT_HINTS = {
    "queued": "Poll permyt_check_access in a few seconds.",
    "analyzing": "Poll permyt_check_access in a few seconds.",
    "awaiting": (
        "Poll permyt_check_access every few seconds. "
        "Tell the user to check their PERMYT mobile app."
    ),
    "processing": (
        "Poll permyt_check_access in a few seconds. "
        "Data will be included when status is completed."
    ),
}

FAILURE_MESSAGES = {
    "rejected": {
        "message": "The user denied this request on their PERMYT app.",
        "client_hint": (
            "Do not retry the same request. Ask the user if they'd like a different approach."
        ),
    },
    "incomplete": {
        "message": "The request description was too vague to determine what data is needed.",
        "client_hint": (
            "Ask the user to clarify what specific data they want "
            "and submit a new, more detailed request."
        ),
    },
    "unavailable": {
        "message": "No connected service can provide the requested data.",
        "client_hint": (
            "Let the user know. They may need to connect "
            "the relevant service via the PERMYT mobile app."
        ),
    },
}

COMPLETED_MESSAGE = (
    "User approved. Call permyt_call_service with the dynamic input values "
    "parsed from the user's original request to execute."
)
COMPLETED_HINT = (
    "Build `inputs` from the user's original request, matching every name in "
    "`endpoints[].input_fields`. Pass {} when input_fields is empty. Then call "
    "permyt_call_service(request_id, inputs)."
)


MCP_INSTRUCTIONS = (
    "PERMYT lets you request access to user data held by external services "
    "(banks, healthcare, employers, etc.) on behalf of the user. Action "
    "scopes (payments, write operations) work the same way as read scopes — "
    "the user approves on mobile, then you execute.\n\n"
    "HOW IT WORKS:\n"
    "0. (Optional) Call permyt_view_scopes to see what services and scopes "
    "the user has connected, including any input fields each scope declares.\n"
    "1. Call permyt_request_access(description) with a precise plain-language "
    "description. Returns a request_id immediately.\n"
    "2. Tell the user you're waiting for their approval on the PERMYT mobile "
    "app.\n"
    "3. Poll permyt_check_access(request_id) every few seconds. Statuses:\n"
    "   - queued: request received, waiting for broker\n"
    "   - analyzing: broker AI is evaluating required permissions\n"
    "   - awaiting: user has been notified, waiting for their approval\n"
    "   - processing: user approved, issuing access tokens\n"
    "   - completed: approval done. Response carries `endpoints[]` with the "
    "dynamic `input_fields` schema for the next step. NOTE: completed means "
    "approved, NOT executed.\n"
    "4. Call permyt_call_service(request_id, inputs) to execute. Build "
    "`inputs` from the user's original request, matching every name in the "
    "schema. For pure read scopes the schema is empty — pass `inputs={}`.\n"
    "5. The provider response is returned by permyt_call_service. Present it "
    "to the user.\n\n"
    "WORKED EXAMPLE (action scope, payment):\n"
    "  user: 'pay 50 EUR to Fred Russias (IBAN PT50…) for computer services'\n"
    "  → permyt_request_access(description=<the user's sentence>)\n"
    "  → poll permyt_check_access until status='completed'; response has\n"
    "      endpoints=[{input_fields: {account, value, currency, name, "
    "description}}]\n"
    "  → permyt_call_service(request_id, inputs={\n"
    "      'account': 'PT50…', 'value': '50.00', 'currency': 'EUR',\n"
    "      'name': 'Fred Russias', 'description': 'computer services'})\n"
    "  → present the provider's confirmation to the user.\n\n"
    "WORKED EXAMPLE (read scope, no dynamic inputs):\n"
    "  → permyt_request_access(description='read the latest bank statement '\n"
    "    'for March 2025')\n"
    "  → poll until completed; endpoints[].input_fields is {}.\n"
    "  → permyt_call_service(request_id, inputs={}) — returns the statement.\n\n"
    "HANDLING FAILURES:\n"
    "- incomplete: description too vague. Ask the user to clarify (which "
    "account? what time period?) and submit a NEW request_access.\n"
    "- unavailable: no connected provider can satisfy this request. The user "
    "may need to connect the service via the PERMYT mobile app.\n"
    "- rejected: user denied. Do NOT retry the same request.\n\n"
    "TRANSIENT ERRORS:\n"
    "If permyt_request_access or permyt_check_access returns an error with "
    "`retryable: true` (e.g. network blip, broker session expired), retry up "
    "to 3 times with a short delay before surfacing the failure. "
    "permyt_check_access is idempotent for the same request_id. "
    "permyt_request_access retries produce fresh request_ids — only poll the "
    "most recent successful one.\n\n"
    "TIPS:\n"
    "- Be specific. 'Read the latest bank statement for March 2025' beats "
    "'get financial data'.\n"
    "- Tell the user what's happening at each status change — especially "
    "when status is 'awaiting', so they know to check their PERMYT mobile "
    "app.\n"
    "- Keep polling until you reach a terminal status (completed, rejected, "
    "incomplete, unavailable)."
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

    Known limitation — transient -32600 "Session not found" errors:
        Sessions are held in-memory by the SDK's StreamableHTTPSessionManager.
        Server restarts (deploys) wipe all sessions, so clients holding a stale
        mcp-session-id will receive INVALID_REQUEST (-32600). This is an upstream
        SDK limitation — FastMCP does not expose session_idle_timeout or EventStore
        (for resumability) as constructor parameters. Tool docstrings tell the
        AI to retry on `retryable=true` envelopes; -32600 is similar.
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
    """Submit a natural-language request for user data or an action.

    Returns a request_id immediately and starts the broker's evaluation +
    user-approval flow. Poll status with permyt_check_access; once the
    status reaches `completed`, execute with permyt_call_service.

    The PERMYT broker AI extracts any locked/force inputs (e.g. recipient,
    amount on a payment) from your description and shows them to the user
    on the mobile app for approval. Be specific so the user sees the right
    bound values.

    Args:
        description: What you want, in natural language. Be specific.
            Good: "Read the user's latest bank statement for March 2025"
            Good: "Pay 50 EUR to Fred Russias (IBAN PT50XDW…) for computer services"
            Good: "Get the user's employment verification letter"
            Bad:  "get financial data" (too vague — broker will return `incomplete`)

    Retries: if the call returns an error envelope with `retryable: true`
    (e.g. transient network/session error), retry up to 3 times with a short
    delay. Each retry produces a fresh request_id — only poll the most recent
    successful one.
    """
    client, user = await _get_user_from_context(ctx)

    try:
        result = await asyncio.to_thread(
            client.request_access,
            {
                "user_id": str(user.permyt_user_id),
                "description": description,
            },
        )
    except Exception as exc:  # noqa: BLE001 — surfaced via envelope
        logger.error(f"request_access failed: {exc}", exc_info=True)
        return json.dumps(error_envelope(exc), default=str)

    return json.dumps(result, default=str)


@mcp.tool()
async def permyt_view_scopes(ctx: Context = None) -> str:
    """View available data scopes the user has connected to PERMYT.

    Returns the list of services and their scopes (data types) that can be
    requested via permyt_request_access. Each scope includes a name,
    description, and the input fields it declares — locked inputs are bound
    at approval time, dynamic inputs are supplied at call time via
    permyt_call_service.
    """
    client, user = await _get_user_from_context(ctx)

    try:
        result = await asyncio.to_thread(client.view_scopes, str(user.permyt_user_id))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"view_scopes failed: {exc}", exc_info=True)
        return json.dumps(error_envelope(exc), default=str)

    return json.dumps(result, default=str)


TERMINAL_STATUSES = {"completed", "rejected", "incomplete", "unavailable"}


@mcp.tool()
async def permyt_check_access(request_id: str, ctx: Context = None) -> str:
    """Poll the status of a permyt_request_access call.

    Statuses: queued (waiting for broker), analyzing (evaluating scopes),
    awaiting (pending user approval), processing (issuing tokens),
    completed (APPROVED — call permyt_call_service to execute), rejected
    (user denied), incomplete (description too vague), unavailable (no
    provider can satisfy this request).

    On `completed`, the response carries `endpoints` — a list with each
    approved endpoint's `description` and `input_fields` (dynamic field
    name → human description). Build the `inputs` dict for
    permyt_call_service from these names. For read scopes with no dynamic
    inputs, `input_fields` is an empty dict; pass `inputs={}`.

    Args:
        request_id: id from permyt_request_access.

    Retries: idempotent for the same request_id. If the call returns an
    error envelope with `retryable: true`, retry up to 3 times with a short
    delay before surfacing.
    """
    client, user = await _get_user_from_context(ctx)

    try:
        result = await asyncio.to_thread(client.check_access, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"check_access failed: {exc}", exc_info=True)
        return json.dumps(error_envelope(exc), default=str)

    status = result.get("status")
    services = result.get("services") or []

    if status == "completed":
        try:
            await asyncio.to_thread(store_pending_service_call, request_id, user, services)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"check_access storage failed: {exc}", exc_info=True)
            return json.dumps(error_envelope(exc), default=str)

        return json.dumps(
            {
                "request_id": request_id,
                "status": "completed",
                "endpoints": endpoint_schema(services),
                "next_action": "permyt_call_service",
                "message": COMPLETED_MESSAGE,
                "client_hint": COMPLETED_HINT,
            },
            default=str,
        )

    # Terminal failure — user-facing message + separate client hint
    if status in FAILURE_MESSAGES:
        failure = FAILURE_MESSAGES[status]
        return json.dumps(
            {
                "request_id": request_id,
                "status": status,
                "reason": result.get("reason"),
                "message": failure["message"],
                "client_hint": failure["client_hint"],
            },
            default=str,
        )

    # Intermediate status — progress message + separate client hint
    return json.dumps(
        {
            "request_id": request_id,
            "status": status,
            "message": STATUS_MESSAGES.get(status, f"Status: {status}"),
            "client_hint": CLIENT_HINTS.get(status),
        },
        default=str,
    )


@mcp.tool()
async def permyt_call_service(
    request_id: str,
    inputs: dict | None = None,
    ctx: Context = None,
) -> str:
    """Execute an approved request and return the provider's response.

    Call this AFTER permyt_check_access reports status='completed'.
    `completed` means the user has approved your request and tokens have
    been issued — `permyt_call_service` does the actual provider call.

    Locked/force inputs (extracted by the broker AI from the original
    description and approved by the user on mobile) are baked into the
    token. You only supply DYNAMIC inputs here, matching the field names
    declared in `endpoints[].input_fields` returned by permyt_check_access.

    Args:
        request_id: id from permyt_request_access.
        inputs: flat dict of dynamic field name → value. The same dict is
            applied to every endpoint approved under this request. Pass
            ``{}`` (or omit) for scopes with no dynamic inputs (most read
            scopes).

    Example (action scope, payment):
        inputs={
            "account":     "PT50XDW90995819083863",
            "value":       "50.00",
            "currency":    "EUR",
            "name":        "Fred Russias",
            "description": "computer services",
        }

    Single-use: a successful call consumes the pending request. To execute
    another action, submit a new permyt_request_access.
    """
    client, user = await _get_user_from_context(ctx)

    try:
        pending = await asyncio.to_thread(consume_pending_service_call, request_id, user)
    except LookupError as exc:
        return json.dumps(
            {
                "request_id": request_id,
                "status": "error",
                "code": str(exc),
                "message": CONSUME_ERROR_MESSAGES.get(str(exc), "Cannot execute this request."),
                "retryable": False,
            },
            default=str,
        )

    client.set_endpoint_inputs(inputs)

    try:
        raw_data = await asyncio.to_thread(client.call_services, pending.services)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"call_service failed: {exc}", exc_info=True)
        envelope = error_envelope(exc)
        envelope["request_id"] = request_id
        return json.dumps(envelope, default=str)

    return json.dumps(
        {
            "request_id": request_id,
            "status": "completed",
            "data": flatten_service_data(raw_data),
        },
        default=str,
    )
