"""
OAuth 2.0 models for MCP SSE transport.

Stores OAuth clients (via DCR), authorization codes, access tokens,
refresh tokens, and temporary authorization sessions for the QR login flow.
"""

import time

from django.conf import settings
from django.db import models

from app.mixins.models import AppModel


class OAuthClient(AppModel):
    """OAuth 2.0 client registered via Dynamic Client Registration (RFC 7591)."""

    client_id = models.CharField(max_length=255, unique=True, db_index=True)
    client_secret = models.CharField(max_length=255, blank=True, null=True)
    client_id_issued_at = models.IntegerField(null=True, blank=True)
    client_secret_expires_at = models.IntegerField(null=True, blank=True)

    # Client metadata (RFC 7591 Section 2)
    redirect_uris = models.JSONField(default=list)
    client_name = models.CharField(max_length=255, blank=True, default="")
    client_uri = models.URLField(blank=True, default="")
    grant_types = models.JSONField(default=list)
    response_types = models.JSONField(default=list)
    token_endpoint_auth_method = models.CharField(max_length=50, default="client_secret_post")
    scope = models.CharField(max_length=1024, blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"OAuthClient({self.client_id[:8]}... {self.client_name})"


class OAuthAuthorizationCode(AppModel):
    """Temporary authorization code issued during OAuth authorize flow."""

    code = models.CharField(max_length=255, unique=True, db_index=True)
    client_id = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_authorization_codes",
    )
    scopes = models.JSONField(default=list)
    code_challenge = models.CharField(max_length=255)
    redirect_uri = models.TextField()
    redirect_uri_provided_explicitly = models.BooleanField(default=True)
    resource = models.CharField(max_length=1024, blank=True, null=True)
    expires_at = models.FloatField()

    class Meta:
        ordering = ("-created_at",)

    def is_expired(self):
        return self.expires_at < time.time()


class OAuthAccessToken(AppModel):
    """OAuth 2.0 access token linked to a Django User."""

    token = models.CharField(max_length=255, unique=True, db_index=True)
    client_id = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_access_tokens",
    )
    scopes = models.JSONField(default=list)
    expires_at = models.IntegerField(null=True, blank=True)
    resource = models.CharField(max_length=1024, blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"OAuthAccessToken({self.token[:8]}... user={self.user_id})"


class OAuthRefreshToken(AppModel):
    """OAuth 2.0 refresh token linked to a Django User."""

    token = models.CharField(max_length=255, unique=True, db_index=True)
    client_id = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_refresh_tokens",
    )
    scopes = models.JSONField(default=list)
    expires_at = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class OAuthAuthorizationSession(AppModel):
    """Temporary session linking /mcp/authorize to the QR login page.

    Created by provider.authorize(), consumed by OAuthCallbackView
    after the user completes QR login.
    """

    client_id = models.CharField(max_length=255)
    state = models.CharField(max_length=1024, blank=True, null=True)
    scopes = models.JSONField(default=list, null=True, blank=True)
    code_challenge = models.CharField(max_length=255)
    redirect_uri = models.TextField()
    redirect_uri_provided_explicitly = models.BooleanField(default=True)
    resource = models.CharField(max_length=1024, blank=True, null=True)
    expires_at = models.FloatField()

    class Meta:
        ordering = ("-created_at",)

    def is_expired(self):
        return self.expires_at < time.time()
