import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .client import PermytClient
from .responses import (
    CONSUME_ERROR_MESSAGES,
    consume_pending_service_call,
    endpoint_schema,
    error_envelope,
    flatten_service_data,
    store_pending_service_call,
)
from .serializers import (
    CallServiceSerializer,
    CheckAccessSerializer,
    RequestAccessSerializer,
)

logger = logging.getLogger("console")


COMPLETED_MESSAGE = (
    "User approved. Call /rest/requests/call/ with the dynamic input values "
    "parsed from the user's original request to execute."
)


class RequestAccessView(APIView):
    """Submit an access request through PERMYT on behalf of the authenticated user."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RequestAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.permyt_user_id:
            return Response(
                {"error": "User has no permyt_user_id. Please connect via QR login first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client = PermytClient()
        try:
            result = client.request_access(
                {
                    "user_id": str(user.permyt_user_id),
                    "description": serializer.validated_data["description"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"request_access failed: {exc}", exc_info=True)
            return Response(error_envelope(exc), status=status.HTTP_502_BAD_GATEWAY)

        return Response(result)


class CheckAccessView(APIView):
    """Poll request status. On ``completed`` returns the call_service schema (no auto-execute)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = serializer.validated_data["request_id"]
        user = request.user
        client = PermytClient()

        try:
            result = client.check_access(request_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"check_access failed: {exc}", exc_info=True)
            return Response(error_envelope(exc), status=status.HTTP_502_BAD_GATEWAY)

        if result.get("status") == "completed":
            services = result.get("services") or []
            try:
                store_pending_service_call(request_id, user, services)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"check_access storage failed: {exc}", exc_info=True)
                return Response(error_envelope(exc), status=status.HTTP_502_BAD_GATEWAY)

            return Response(
                {
                    "request_id": request_id,
                    "status": "completed",
                    "endpoints": endpoint_schema(services),
                    "next_action": "/rest/requests/call/",
                    "message": COMPLETED_MESSAGE,
                }
            )

        return Response(result)


class CallServiceView(APIView):
    """Execute the approved request with dynamic inputs and return the provider response."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CallServiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = serializer.validated_data["request_id"]
        inputs = serializer.validated_data.get("inputs") or {}
        user = request.user

        try:
            pending = consume_pending_service_call(request_id, user)
        except LookupError as exc:
            code = str(exc)
            return Response(
                {
                    "request_id": request_id,
                    "status": "error",
                    "code": code,
                    "message": CONSUME_ERROR_MESSAGES.get(code, "Cannot execute this request."),
                    "retryable": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        client = PermytClient()
        client.set_endpoint_inputs(inputs)

        try:
            raw_data = client.call_services(pending.services)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"call_service failed: {exc}", exc_info=True)
            envelope = error_envelope(exc)
            envelope["request_id"] = request_id
            return Response(envelope, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "request_id": request_id,
                "status": "completed",
                "data": flatten_service_data(raw_data),
            }
        )


class ViewScopesView(APIView):
    """View available scopes across all providers connected to the authenticated user."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.permyt_user_id:
            return Response(
                {"error": "User has no permyt_user_id. Please connect via QR login first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client = PermytClient()
        try:
            result = client.view_scopes(str(user.permyt_user_id))  # pylint: disable=no-member
        except Exception as exc:  # noqa: BLE001
            logger.error(f"view_scopes failed: {exc}", exc_info=True)
            return Response(error_envelope(exc), status=status.HTTP_502_BAD_GATEWAY)

        return Response(result)


class PermytInboundView(APIView):
    """
    Webhook endpoint for PERMYT broker callbacks.

    Handles: user_connect, user_disconnect, request_status.
    No auth required — requests are signed + encrypted by the broker.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        client = PermytClient()
        try:
            result = client.handle_inbound(request.data)
            return Response(result)
        except Exception as exc:
            logger.error(f"Inbound webhook error: {exc}", exc_info=True)
            return Response(
                {"error": "Unable to process inbound request."},
                status=status.HTTP_400_BAD_REQUEST,
            )
