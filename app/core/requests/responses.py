"""Shared response helpers for MCP tools and REST views.

Both surfaces speak the PERMYT lifecycle: submit → poll → execute. The
payloads they emit (error envelopes, completed-status schema, flattened
service responses) must stay aligned, so the small helpers live here.
"""

from django.db import transaction
from django.utils import timezone

from permyt.exceptions import PermytError, TransportError

from .models import PendingServiceCall

CONSUME_ERROR_MESSAGES = {
    "unknown_request": (
        "No pending call for this request_id. "
        "Has the request been polled to status='completed' yet?"
    ),
    "already_consumed": (
        "This request has already been executed. Submit a new request_access " "for another action."
    ),
    "expired": (
        "The provider token for this request expired before execution. "
        "Submit a new request_access."
    ),
}


def flatten_service_data(raw: list) -> list:
    """Flatten provider responses from ``{scope_ref: data}`` to ``{scope, data}`` pairs."""
    flattened: list = []
    for item in raw:
        if isinstance(item, dict):
            for scope_ref, data in item.items():
                flattened.append({"scope": scope_ref, "data": data})
        else:
            flattened.append(item)
    return flattened


def endpoint_schema(services: list) -> list:
    """Extract the schema the AI needs to call ``call_service``.

    Drops the encrypted token, provider public key, and full URL — those stay
    server-side. Surfaces just the per-endpoint description + dynamic
    ``input_fields`` so the AI can build the ``inputs`` dict.
    """
    schema: list = []
    for service in services or []:
        for endpoint in service.get("endpoints") or []:
            schema.append(
                {
                    "description": endpoint.get("description"),
                    "input_fields": endpoint.get("input_fields") or {},
                }
            )
    return schema


def error_envelope(exc: Exception) -> dict:
    """Map an exception to a stable JSON error envelope for the AI/REST client.

    ``retryable=True`` signals the call may succeed on retry (network blip,
    transient broker issue). Clients should retry up to ~3 times before
    surfacing the failure.
    """
    if isinstance(exc, TransportError):
        return {
            "status": "error",
            "code": exc.code,
            "message": str(exc) or exc.default_message,
            "retryable": True,
        }
    if isinstance(exc, PermytError):
        return {
            "status": "error",
            "code": exc.code,
            "message": str(exc) or exc.default_message,
            "retryable": False,
        }
    return {
        "status": "error",
        "code": "unexpected_error",
        "message": "An upstream error occurred.",
        "retryable": True,
    }


def store_pending_service_call(request_id: str, user, services: list) -> None:
    """Persist the encrypted credential bundle for later ``call_service``.

    Idempotent: safe to call on every poll that lands on ``completed``.
    """
    if not services:
        return
    expires_at = PendingServiceCall.expires_at_from_services(services)
    PendingServiceCall.objects.update_or_create(
        request_id=request_id,
        defaults={
            "user": user,
            "services": services,
            "expires_at": expires_at,
        },
    )


def consume_pending_service_call(request_id: str, user) -> PendingServiceCall:
    """Atomically claim a ``PendingServiceCall`` row for execution.

    Raises ``LookupError`` with one of ``unknown_request``, ``already_consumed``,
    ``expired`` when the row cannot be claimed. The row is marked consumed
    *before* the provider call; SDK errors below leave the row consumed
    because the underlying token is single-use anyway.
    """
    with transaction.atomic():
        try:
            pending = PendingServiceCall.objects.select_for_update().get(
                request_id=request_id, user=user
            )
        except PendingServiceCall.DoesNotExist as exc:
            raise LookupError("unknown_request") from exc

        if pending.consumed_at is not None:
            raise LookupError("already_consumed")
        if pending.expires_at <= timezone.now():
            raise LookupError("expired")

        pending.consumed_at = timezone.now()
        pending.save(update_fields=["consumed_at", "updated_at"])
    return pending
