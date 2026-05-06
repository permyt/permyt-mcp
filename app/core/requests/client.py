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

    # Dynamic per-call inputs supplied by the AI through ``permyt_call_service``.
    # Read by ``_prepare_data_for_endpoint`` when ``call_services`` runs. Class
    # default is empty so existing read-scope flows behave as before.
    _endpoint_inputs: dict[str, Any] = {}

    def __init__(self):
        super().__init__(host=settings.PERMYT_HOST)
        self._endpoint_inputs = {}

    def set_endpoint_inputs(self, inputs: dict[str, Any] | None) -> None:
        """Set the dynamic inputs applied to every endpoint of the next ``call_services``.

        The same dict is used for every endpoint of the approved request — the
        provider validates and ignores extras. Pass ``None`` or ``{}`` for
        scopes that declare no dynamic inputs.
        """
        self._endpoint_inputs = dict(inputs) if inputs else {}

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

        Returns the dynamic inputs set via :meth:`set_endpoint_inputs` (empty
        dict by default). Locked/force inputs are enforced by the provider
        from the token's :class:`~permyt.typing.ScopeGrant`; only dynamic
        fields declared in ``endpoint["input_fields"]`` flow through here.
        """
        return dict(self._endpoint_inputs)

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
    # User disconnect
    # ------------------------------------------------------------------

    def process_user_disconnect(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Handle the ``user_disconnect`` callback from the PERMYT broker.

        Revoke the system auth token, clear the PERMYT identity from the
        local user, and invalidate any active QR-login sessions. Idempotent
        for already-disconnected users.
        """
        permyt_user_id = data.get("permyt_user_id")
        if not permyt_user_id:
            raise exceptions.InvalidInputError("permyt_user_id is required for user disconnect.")

        try:
            user = User.objects.get(permyt_user_id=permyt_user_id)
        except User.DoesNotExist:
            return {"disconnected": True}

        Token.objects.filter(user=user).delete()
        LoginToken.objects.filter(user=user).delete()
        user.permyt_user_id = None
        user.save()
        return {"disconnected": True}

    # ------------------------------------------------------------------
    # Status callbacks
    # ------------------------------------------------------------------

    def process_request_status(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Acknowledge a broker status callback.

        Provider calls are deferred to ``permyt_call_service`` (which the AI
        invokes after ``permyt_check_access`` reports ``completed``) so dynamic
        inputs can be supplied. The webhook just acknowledges receipt.
        """
        return {"received": True}
