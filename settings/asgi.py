"""
ASGI entrypoint for permyt-mcp.

Routes:
    /mcp/*                                          → FastMCP Starlette app (Streamable HTTP, OAuth)
    /.well-known/oauth-authorization-server/mcp     → FastMCP (RFC 8414 metadata)
    /.well-known/oauth-protected-resource/mcp       → FastMCP (RFC 9728 metadata)
    /*                                              → Django ASGI app (REST API, web pages, OAuth login)
"""

import logging
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.base")

# Django ASGI app must be created before importing MCP server
from django.core.asgi import get_asgi_application

django_app = get_asgi_application()

# Import after Django setup
from app.mcp.server import create_mcp_app

logger = logging.getLogger("console")

_mcp_app = create_mcp_app()


def _log_mcp_request(scope, label):
    """Log incoming MCP/OAuth request for debugging client connections."""
    method = scope.get("method", "?")
    path = scope.get("path", "?")
    headers = dict(scope.get("headers", []))
    # ASGI headers are bytes tuples
    user_agent = ""
    origin = ""
    auth = ""
    for key, val in scope.get("headers", []):
        if key == b"user-agent":
            user_agent = val.decode(errors="replace")[:80]
        elif key == b"origin":
            origin = val.decode(errors="replace")
        elif key == b"authorization":
            auth = val.decode(errors="replace")[:20] + "..."

    parts = [f"MCP {label}: {method} {path}"]
    if user_agent:
        parts.append(f"ua={user_agent}")
    if origin:
        parts.append(f"origin={origin}")
    if auth:
        parts.append(f"auth={auth}")
    logger.info(" | ".join(parts))


async def application(scope, receive, send):
    """Route MCP traffic to Starlette app, everything else to Django."""
    # Forward lifespan to MCP app (StreamableHTTPSessionManager cleanup)
    if scope["type"] == "lifespan":
        await _mcp_app(scope, receive, send)
        return

    path = scope.get("path", "")

    if scope["type"] == "http":
        if path.startswith("/mcp"):
            _log_mcp_request(scope, "endpoint")
            # Strip /mcp prefix so Starlette routes match at app root.
            scope = dict(scope)
            scope["path"] = path[4:] or "/"
            scope["root_path"] = scope.get("root_path", "") + "/mcp"
            await _mcp_app(scope, receive, send)
            return

        # RFC 8414: clients look for /.well-known/oauth-authorization-server/mcp
        # but SDK registers route at /.well-known/oauth-authorization-server.
        # Strip the /mcp suffix so the route matches.
        if path.startswith("/.well-known/oauth-authorization-server"):
            _log_mcp_request(scope, "oauth-as-meta")
            scope = dict(scope)
            scope["path"] = "/.well-known/oauth-authorization-server"
            await _mcp_app(scope, receive, send)
            return

        # RFC 9728: SDK registers route at /.well-known/oauth-protected-resource/mcp
        # (full path including /mcp suffix). Pass through as-is.
        if path.startswith("/.well-known/oauth-protected-resource"):
            _log_mcp_request(scope, "resource-meta")
            await _mcp_app(scope, receive, send)
            return

    await django_app(scope, receive, send)
