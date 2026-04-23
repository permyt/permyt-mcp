"""
ASGI entrypoint for permyt-mcp.

Routes:
    /mcp/*                                  → FastMCP Starlette app (Streamable HTTP, OAuth)
    /.well-known/oauth-protected-resource/* → FastMCP (RFC 9728 metadata)
    /*                                      → Django ASGI app (REST API, web pages, OAuth login)
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

    if scope["type"] == "http" and (
        path.startswith("/mcp")
        or path.startswith("/.well-known/oauth-protected-resource")
    ):
        scope = dict(scope)
        if path.startswith("/mcp"):
            # Strip /mcp prefix so Starlette routes match at app root.
            scope["path"] = path[4:] or "/"
            scope["root_path"] = scope.get("root_path", "") + "/mcp"
        # /.well-known/* paths pass through without stripping
        await _mcp_app(scope, receive, send)
    else:
        await django_app(scope, receive, send)
