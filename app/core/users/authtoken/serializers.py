from rest_framework import serializers

from django.contrib.auth import authenticate

from app.utils.crypto import hide_token

from .models import Token


class AuthTokenSerializer(serializers.Serializer):
    """Validates username/password for login."""

    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})

    def validate(self, attrs):
        username = attrs.get("username")
        password = attrs.get("password")

        if username and password:
            user = authenticate(self.context["request"], username=username, password=password)
            if user:
                if not user.is_active:
                    raise serializers.ValidationError("Account is disabled.")
            else:
                raise serializers.ValidationError("Invalid username or password.")
        else:
            raise serializers.ValidationError("Invalid username or password.")

        attrs["user"] = user
        return attrs


class TokenSerializer(serializers.ModelSerializer):
    """Serializer for auth tokens. Shows hidden_key, full key only on create."""

    hidden_key = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Token
        fields = ("id", "hidden_key", "created", "last_used", "name")
        read_only_fields = ("id", "created", "last_used", "hidden_key")

    def get_hidden_key(self, obj):
        return hide_token(obj.key, chars=4)
