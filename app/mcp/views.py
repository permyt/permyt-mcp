"""
OAuth 2.0 authorization views for MCP.

OAuthAuthorizeView: Shows QR code for PERMYT mobile app login.
OAuthCallbackView: Creates authorization code after QR login, redirects to client.
"""

import secrets
import time

from django.contrib.auth import login
from django.contrib.sessions.models import Session
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from mcp.server.auth.provider import construct_redirect_uri

from app.core.requests.client import PermytClient
from app.core.users.models import LoginToken

from .models import OAuthAuthorizationCode, OAuthAuthorizationSession
from .provider import AUTH_CODE_TTL


class OAuthAuthorizeView(View):
    """Show QR code for PERMYT login during OAuth authorization flow.

    GET /oauth/authorize/?session=<uuid>

    After the user scans the QR code with the PERMYT mobile app,
    the JS polls LoginStatusView and then redirects to OAuthCallbackView.
    """

    def get(self, request):
        session_id = request.GET.get("session")
        if not session_id:
            return HttpResponseBadRequest("Missing session parameter.")

        try:
            oauth_session = OAuthAuthorizationSession.objects.get(id=session_id)
        except OAuthAuthorizationSession.DoesNotExist:
            return HttpResponseBadRequest("Invalid or expired authorization session.")

        if oauth_session.is_expired():
            oauth_session.delete()
            return HttpResponseBadRequest("Authorization session expired.")

        # Create Django session if needed (LoginToken requires a Session FK)
        if not request.session.session_key:
            request.session.create()

        # Generate QR connect token (same flow as IndexView._login)
        session = Session.objects.get(session_key=request.session.session_key)
        client = PermytClient()
        connect = client.generate_connect_token(system_user_id=None)

        token_obj = LoginToken.objects.create(
            token=connect["token"],
            session=session,
        )

        return render(
            request,
            "mcp/authorize.html",
            {
                "login_id": str(token_obj.id),
                "qr_data": connect["data"],
                "oauth_session_id": str(oauth_session.id),
                "title": "Authorize — PERMYT MCP",
            },
        )


class OAuthCallbackView(View):
    """Create OAuth authorization code after QR login and redirect to client.

    GET /oauth/callback/?login_id=<uuid>&session=<uuid>

    Called by JS after LoginStatusView reports authentication.
    Authenticates the user via the LoginToken (passed as URL param to avoid
    relying on session cookies from fetch responses in popup contexts),
    creates the authorization code, and redirects to the client's redirect_uri.
    """

    def _authenticate(self, request):
        """Authenticate the user via LoginToken URL param or existing session."""
        login_id = request.GET.get("login_id")
        if login_id:
            try:
                token_obj = LoginToken.objects.select_related("user").get(id=login_id)
            except LoginToken.DoesNotExist as exc:
                raise ValueError("Invalid or expired login token.") from exc

            if not token_obj.user:
                raise ValueError("QR login not completed.")

            login(request, token_obj.user, backend="django.contrib.auth.backends.ModelBackend")
            token_obj.delete()

        if not request.user.is_authenticated:
            raise ValueError("Not authenticated. Please complete QR login first.")

    def _load_oauth_session(self, request):
        """Load and validate the OAuth authorization session."""
        oauth_session_id = request.GET.get("session")
        if not oauth_session_id:
            raise ValueError("No OAuth session found.")

        try:
            oauth_session = OAuthAuthorizationSession.objects.get(id=oauth_session_id)
        except OAuthAuthorizationSession.DoesNotExist as exc:
            raise ValueError("Authorization session not found or expired.") from exc

        if oauth_session.is_expired():
            oauth_session.delete()
            raise ValueError("Authorization session expired.")

        return oauth_session

    def get(self, request):
        try:
            self._authenticate(request)
            oauth_session = self._load_oauth_session(request)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

        user = request.user
        if not user.permyt_user_id:
            return HttpResponseBadRequest(
                "User has no PERMYT identity. Please connect via the PERMYT app first."
            )

        # Create authorization code (160+ bits of entropy)
        code = secrets.token_urlsafe(32)

        OAuthAuthorizationCode.objects.create(
            code=code,
            client_id=oauth_session.client_id,
            user=user,
            scopes=oauth_session.scopes or [],
            code_challenge=oauth_session.code_challenge,
            redirect_uri=oauth_session.redirect_uri,
            redirect_uri_provided_explicitly=oauth_session.redirect_uri_provided_explicitly,
            resource=oauth_session.resource,
            expires_at=int(time.time()) + AUTH_CODE_TTL,
        )

        # Build redirect URI with code and state
        redirect_uri = construct_redirect_uri(
            oauth_session.redirect_uri,
            code=code,
            state=oauth_session.state,
        )

        # Clean up
        oauth_session.delete()

        return HttpResponseRedirect(redirect_uri)
