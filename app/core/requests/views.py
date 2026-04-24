import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .client import PermytClient
from .serializers import RequestAccessSerializer, CheckAccessSerializer

logger = logging.getLogger("console")


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
        except Exception as exc:
            logger.error(f"request_access failed: {exc}", exc_info=True)
            return Response(
                {"error": "An upstream service error occurred. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(result)


class CheckAccessView(APIView):
    """Check status of a pending access request. If completed, calls providers."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = serializer.validated_data["request_id"]
        client = PermytClient()

        try:
            result = client.check_access(request_id)
        except Exception as exc:
            logger.error(f"check_access failed: {exc}", exc_info=True)
            return Response(
                {"error": "An upstream service error occurred. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # If approved with services, call providers to get actual data
        if result.get("status") == "approved" and result.get("services"):
            try:
                data = client.call_services(result["services"])
                return Response(
                    {
                        "request_id": request_id,
                        "status": "completed",
                        "data": data,
                    }
                )
            except Exception as exc:
                logger.error(f"call_services failed: {exc}", exc_info=True)
                return Response(
                    {
                        "request_id": request_id,
                        "status": "error",
                        "error": "Failed to fetch data from provider.",
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        return Response(result)


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
        except Exception as exc:
            logger.error(f"view_scopes failed: {exc}", exc_info=True)
            return Response(
                {"error": "An upstream service error occurred. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(result)


class PermytInboundView(APIView):
    """
    Webhook endpoint for PERMYT broker callbacks.

    Handles: user_connect, request_status.
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
