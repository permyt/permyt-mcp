from django.contrib.auth import login

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .authtoken.models import Token
from .models import LoginToken


class LoginStatusView(APIView):
    """Poll endpoint for QR login status."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        login_id = request.query_params.get("id")
        if not login_id:
            return Response({"error": "id is required."}, status=400)

        try:
            token_obj = LoginToken.objects.select_related("user").get(id=login_id)
        except LoginToken.DoesNotExist:
            return Response({"error": "Unknown login id."}, status=404)

        if token_obj.user:
            # OAuth mode: don't consume the token here — the OAuthCallbackView
            # will authenticate and clean up via a top-level navigation, which
            # is more reliable for session cookies in popup/redirect contexts.
            if request.query_params.get("mode") == "oauth":
                return Response({"status": "authenticated"})

            login(request, token_obj.user, backend="django.contrib.auth.backends.ModelBackend")

            # Return system auth token for API/MCP use
            auth_token, _ = Token.objects.get_or_create(user=token_obj.user, system=True)
            token_obj.delete()
            return Response({"status": "authenticated", "auth_token": auth_token.key})

        return Response({"status": "pending"})
