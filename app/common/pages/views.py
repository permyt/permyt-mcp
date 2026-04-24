import json

from django.conf import settings
from django.contrib.sessions.models import Session
from django.shortcuts import render
from django.views import View

from app.core.requests.client import PermytClient
from app.core.users.models import LoginToken
from app.utils.qr import generate_qr_svg


class IndexView(View):
    """
    Single entry point at /.
    Dispatches to login or dashboard based on auth state.
    """

    def get(self, request):
        if not request.user.is_authenticated:
            return self._login(request)
        return self._dashboard(request)

    def _login(self, request):
        """Render the QR-code login page."""
        if not request.session.session_key:
            request.session.create()

        session = Session.objects.get(session_key=request.session.session_key)

        client = PermytClient()
        connect = client.generate_connect_token(system_user_id=None)

        token_obj = LoginToken.objects.create(
            token=connect["token"],
            session=session,
        )

        qr_svg = generate_qr_svg(json.dumps(connect["data"]))

        return render(
            request,
            "pages/login/index.html",
            {
                "login_id": str(token_obj.id),
                "qr_svg": qr_svg,
                "title": "Login — PERMYT MCP",
            },
        )

    def _dashboard(self, request):
        """Dashboard with token management and per-agent setup instructions."""
        from app.core.users.authtoken.models import Token

        tokens = Token.objects.filter(user=request.user, system=False).order_by("-created")

        return render(
            request,
            "pages/dashboard/index.html",
            {
                "title": "Dashboard — PERMYT MCP",
                "tokens": tokens,
                "base_url": settings.BASE_URL.rstrip("/"),
                "permyt_user_id": (
                    str(request.user.permyt_user_id) if request.user.permyt_user_id else ""
                ),
            },
        )
