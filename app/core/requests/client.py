from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from permyt import PermytClient as BasePermytClient, exceptions
from permyt.typing import ServiceCallEndpoint

from django.conf import settings
from django.db import IntegrityError, transaction

from app.core.users.authtoken.models import Token
from app.core.users.models import User, LoginToken

from .models import Nonce


class PermytClient(BasePermytClient):
    """Requester-side PERMYT client for the MCP server.

    Implements identity, replay protection, user connect (QR login),
    and status-callback handling. Provider-only methods use the SDK
    defaults (``NotImplementedError``).
    """

    DEFAULT_CALLBACK_URL = settings.REQUESTER_CALLBACK_URL

    def __init__(self):
        super().__init__(host=settings.PERMYT_HOST)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def get_service_id(self) -> str:
        return settings.PERMYT_SERVICE_ID

    def get_private_key(self) -> str:
        return settings.PRIVATE_KEY_PATH

    def get_permyt_public_key(self) -> str:
        return Path(settings.PERMYT_PUBLIC_KEY_PATH).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Replay protection
    # ------------------------------------------------------------------

    def _validate_nonce_and_timestamp(self, nonce: str, timestamp: str) -> None:
        """Reject replayed or expired inbound requests."""
        ts = datetime.fromisoformat(timestamp)
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=settings.NONCE_TTL_SECONDS)

        if abs(now - ts) > window:
            raise exceptions.ExpiredRequestError("Request timestamp is outside the valid window.")

        try:
            with transaction.atomic():
                Nonce.objects.create(value=nonce)
        except IntegrityError as exc:
            raise exceptions.ExpiredRequestError("Nonce has already been used.") from exc

    # ------------------------------------------------------------------
    # Requester: build per-endpoint payloads
    # ------------------------------------------------------------------

    def _prepare_data_for_endpoint(
        self, request_id: str, endpoint: ServiceCallEndpoint
    ) -> dict[str, Any]:
        """Build the payload for a single provider endpoint call.
        Returns empty dict — inputs are locked by the broker.
        """
        return {}

    # ------------------------------------------------------------------
    # User connect (QR-login)
    # ------------------------------------------------------------------

    def process_user_connect(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Handle the ``user_connect`` callback from the PERMYT broker.

        Creates or links the local User via ``permyt_user_id``, authenticates
        the session, and generates a DRF auth token for REST API / MCP use.
        """
        permyt_user_id = data.get("permyt_user_id")
        if not permyt_user_id:
            raise exceptions.InvalidInputError("permyt_user_id is required for user connect.")

        try:
            token = LoginToken.objects.get(token=data.get("token"))
        except LoginToken.DoesNotExist as exc:
            raise exceptions.InvalidInputError("Invalid login token.") from exc

        if token.user:
            if token.user.permyt_user_id != permyt_user_id:
                raise exceptions.InvalidUserError(
                    "User already linked to a different permyt profile."
                )
            user = token.user
        else:
            user = User.objects.get_or_create(
                permyt_user_id=permyt_user_id,
                defaults={"username": permyt_user_id},
            )[0]

        token.login(user)

        # Generate system auth token for REST API / MCP use
        auth_token, _ = Token.objects.get_or_create(user=user, system=True)
        return {"logged": True, "auth_token": auth_token.key}

    # ------------------------------------------------------------------
    # Status callbacks
    # ------------------------------------------------------------------

    def process_request_status(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Handle status callbacks pushed by the broker.

        On ``completed``, calls provider endpoints.
        """
        data = data or {}
        status = data.get("status")

        if status == "completed":
            services = data.get("services") or []
            if services:
                self.call_services(services)

        return {"received": True}
