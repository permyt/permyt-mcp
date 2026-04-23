from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from django.contrib.auth import login, logout

from .models import Token
from .serializers import AuthTokenSerializer, TokenSerializer


class LoginView(APIView):
    """Login with email/password, returns a system token."""

    permission_classes = ()
    authentication_classes = ()

    def post(self, request):
        serializer = AuthTokenSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        login(request, user)
        token, _ = Token.objects.get_or_create(user=user, system=True)
        return Response({"token": token.key})


class LogoutView(APIView):
    """Logout the current user."""

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        logout(request)
        return Response({"done": True})


class TokenViewSet(ModelViewSet):
    """CRUD for user API tokens (non-system tokens only)."""

    serializer_class = TokenSerializer
    pagination_class = None

    def get_queryset(self):
        return Token.objects.filter(user=self.request.user, system=False)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = Token.objects.create(
            user=self.request.user, **serializer.validated_data, system=False
        )
        serializer = self.get_serializer(token)
        return Response({**serializer.data, "key": token.key}, status=status.HTTP_201_CREATED)
