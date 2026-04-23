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

        # RFC 8414: clients look for /.well-known/oauth-authorization-server/mcp
        # but SDK registers route at /.well-known/oauth-authorization-server.
        # Strip the /mcp suffix so the route matches.
        if path.startswith("/.well-known/oauth-authorization-server"):
            scope = dict(scope)
            scope["path"] = "/.well-known/oauth-authorization-server"
            await _mcp_app(scope, receive, send)
            return

        # RFC 9728: SDK registers route at /.well-known/oauth-protected-resource/mcp
        # (full path including /mcp suffix). Pass through as-is.
        if path.startswith("/.well-known/oauth-protected-resource"):
            await _mcp_app(scope, receive, send)
            return

    await django_app(scope, receive, send)
