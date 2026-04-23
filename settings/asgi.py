"""
ASGI entrypoint for permyt-mcp.

Routes:
    /mcp/*  → FastMCP Starlette app (SSE transport, OAuth auth)
    /*      → Django ASGI app (REST API, web pages, OAuth login)
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.base")

# Django ASGI app must be created before importing MCP server
from django.core.asgi import get_asgi_application

django_app = get_asgi_application()

# Import after Django setup
from app.mcp.server import create_sse_app

_mcp_app = create_sse_app()


async def application(scope, receive, send):
    """Route /mcp/* to MCP SSE app (with OAuth), everything else to Django."""
    if scope["type"] == "http" and scope.get("path", "").startswith("/mcp"):
        # Strip /mcp prefix so Starlette routes match (they're relative to app root).
        # mount_path="/mcp" in create_sse_app() ensures SSE transport advertises
        # the correct external message endpoint URL (/mcp/messages/).
        scope = dict(scope)
        scope["path"] = scope["path"][4:] or "/"
        scope["root_path"] = scope.get("root_path", "") + "/mcp"
        await _mcp_app(scope, receive, send)
    else:
        await django_app(scope, receive, send)
