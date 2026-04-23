"""
ASGI entrypoint for permyt-mcp.

Routes:
    /mcp/*                                          → FastMCP Starlette app (Streamable HTTP, OAuth)
    /.well-known/oauth-authorization-server/mcp     → FastMCP (RFC 8414 metadata)
    /.well-known/oauth-protected-resource/mcp       → FastMCP (RFC 9728 metadata)
    /*                                              → Django ASGI app (REST API, web pages, OAuth login)
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.base")

# Django ASGI app must be created before importing MCP server
from django.core.asgi import get_asgi_application

django_app = get_asgi_application()

# Import after Django setup
from app.mcp.server import create_mcp_app

_mcp_app = create_mcp_app()

# RFC 8414 / RFC 9728: well-known paths that must reach the MCP Starlette app.
# Clients look for these at /.well-known/{type}/mcp (issuer path appended),
# but the SDK registers routes without the /mcp suffix. We strip it here.
_WELL_KNOWN_PREFIXES = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
)


async def application(scope, receive, send):
    """Route MCP traffic to Starlette app, everything else to Django."""
    # Forward lifespan to MCP app (StreamableHTTPSessionManager cleanup)
    if scope["type"] == "lifespan":
        await _mcp_app(scope, receive, send)
        return

    path = scope.get("path", "")

    if scope["type"] == "http":
        if path.startswith("/mcp"):
            # Strip /mcp prefix so Starlette routes match at app root.
            scope = dict(scope)
            scope["path"] = path[4:] or "/"
            scope["root_path"] = scope.get("root_path", "") + "/mcp"
            await _mcp_app(scope, receive, send)
            return

        for prefix in _WELL_KNOWN_PREFIXES:
            if path.startswith(prefix):
                # RFC 8414/9728: /.well-known/{type}/mcp → strip /mcp suffix
                # so the SDK's route at /.well-known/{type} matches.
                scope = dict(scope)
                scope["path"] = prefix
                await _mcp_app(scope, receive, send)
                return

    await django_app(scope, receive, send)
