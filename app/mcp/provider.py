"""
OAuth 2.0 Authorization Server Provider for MCP Streamable HTTP transport.

Implements the MCP library's OAuthAuthorizationServerProvider protocol,
backed by Django ORM models. Supports Dynamic Client Registration (DCR)
and dual auth (OAuth + DRF token fallback).
"""

import logging
import secrets
import time

from asgiref.sync import sync_to_async
from django.conf import settings

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.core.users.authtoken.models import Token
from app.core.users.models import User

from .models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthAuthorizationSession,
    OAuthClient,
    OAuthRefreshToken,
)

logger = logging.getLogger("console")

ACCESS_TOKEN_TTL = 3600  # 1 hour
AUTH_CODE_TTL = 300  # 5 minutes
AUTH_SESSION_TTL = 600  # 10 minutes


class PermytAccessToken(AccessToken):
    """Access token extended with Django User ID for user lookup in MCP tools."""

    user_id: str


class PermytAuthorizationCode(AuthorizationCode):
    """Authorization code extended with Django User ID."""

    user_id: str


class PermytOAuthProvider:
    """OAuthAuthorizationServerProvider backed by Django ORM."""

    # -- Client management (DCR) -------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        db_client = await sync_to_async(OAuthClient.objects.filter(client_id=client_id).first)()
        if not db_client:
            logger.info(f"OAuth get_client: not found client_id={client_id[:12]}")
            return None
        logger.info(
            f"OAuth get_client: found client_id={client_id[:12]} name={db_client.client_name}"
        )

        return OAuthClientInformationFull(
            client_id=db_client.client_id,
            client_secret=db_client.client_secret,
            client_id_issued_at=db_client.client_id_issued_at,
            client_secret_expires_at=db_client.client_secret_expires_at,
            redirect_uris=db_client.redirect_uris,
            client_name=db_client.client_name or None,
            client_uri=db_client.client_uri or None,
            grant_types=db_client.grant_types,
            response_types=db_client.response_types,
            token_endpoint_auth_method=db_client.token_endpoint_auth_method,
            scope=db_client.scope,
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await sync_to_async(OAuthClient.objects.create)(
            client_id=client_info.client_id,
            client_secret=client_info.client_secret,
            client_id_issued_at=client_info.client_id_issued_at,
            client_secret_expires_at=client_info.client_secret_expires_at,
            redirect_uris=[str(u) for u in (client_info.redirect_uris or [])],
            client_name=client_info.client_name or "",
            client_uri=str(client_info.client_uri) if client_info.client_uri else "",
            grant_types=client_info.grant_types,
            response_types=client_info.response_types,
            token_endpoint_auth_method=(
                client_info.token_endpoint_auth_method or "client_secret_post"
            ),
            scope=client_info.scope,
        )

    # -- Authorization flow ------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        session = await sync_to_async(OAuthAuthorizationSession.objects.create)(
            client_id=client.client_id,
            state=params.state,
            scopes=params.scopes,
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            expires_at=int(time.time()) + AUTH_SESSION_TTL,
        )

        base_url = settings.BASE_URL.rstrip("/")
        logger.info(f"OAuth authorize: client={client.client_id[:12]} session={session.id}")
        return f"{base_url}/oauth/authorize/?session={session.id}"

    # -- Authorization code ------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> PermytAuthorizationCode | None:
        db_code = await sync_to_async(
            OAuthAuthorizationCode.objects.filter(
                code=authorization_code, client_id=client.client_id
            )
            .select_related("user")
            .first
        )()
        if not db_code:
            return None

        return PermytAuthorizationCode(
            code=db_code.code,
            scopes=db_code.scopes or [],
            expires_at=db_code.expires_at,
            client_id=db_code.client_id,
            code_challenge=db_code.code_challenge,
            redirect_uri=db_code.redirect_uri,
            redirect_uri_provided_explicitly=db_code.redirect_uri_provided_explicitly,
            resource=db_code.resource,
            user_id=str(db_code.user.id),
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: PermytAuthorizationCode,
    ) -> OAuthToken:
        user = await sync_to_async(User.objects.get)(id=authorization_code.user_id)

        now = int(time.time())
        access_token_str = secrets.token_urlsafe(48)
        refresh_token_str = secrets.token_urlsafe(48)

        await sync_to_async(OAuthAccessToken.objects.create)(
            token=access_token_str,
            client_id=client.client_id,
            user=user,
            scopes=authorization_code.scopes or [],
            expires_at=now + ACCESS_TOKEN_TTL,
            resource=authorization_code.resource,
        )

        await sync_to_async(OAuthRefreshToken.objects.create)(
            token=refresh_token_str,
            client_id=client.client_id,
            user=user,
            scopes=authorization_code.scopes or [],
        )

        # Delete used authorization code
        await sync_to_async(
            OAuthAuthorizationCode.objects.filter(code=authorization_code.code).delete
        )()

        logger.info(f"OAuth token exchange: user={user.id} client={client.client_id[:12]}")

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh_token_str,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    # -- Refresh token -----------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        db_token = await sync_to_async(
            OAuthRefreshToken.objects.filter(token=refresh_token, client_id=client.client_id)
            .select_related("user")
            .first
        )()
        if not db_token:
            return None

        return RefreshToken(
            token=db_token.token,
            client_id=db_token.client_id,
            scopes=db_token.scopes or [],
            expires_at=db_token.expires_at,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        db_refresh = await sync_to_async(
            OAuthRefreshToken.objects.filter(token=refresh_token.token, client_id=client.client_id)
            .select_related("user")
            .first
        )()
        if not db_refresh:
            raise TokenError(error="invalid_grant", error_description="Refresh token not found")

        user = db_refresh.user
        now = int(time.time())
        new_access_token = secrets.token_urlsafe(48)
        new_refresh_token = secrets.token_urlsafe(48)

        # Rotate: delete old tokens, create new ones
        await sync_to_async(
            OAuthAccessToken.objects.filter(client_id=client.client_id, user=user).delete
        )()
        await sync_to_async(db_refresh.delete)()

        await sync_to_async(OAuthAccessToken.objects.create)(
            token=new_access_token,
            client_id=client.client_id,
            user=user,
            scopes=scopes,
            expires_at=now + ACCESS_TOKEN_TTL,
        )

        await sync_to_async(OAuthRefreshToken.objects.create)(
            token=new_refresh_token,
            client_id=client.client_id,
            user=user,
            scopes=scopes,
        )

        return OAuthToken(
            access_token=new_access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=new_refresh_token,
            scope=" ".join(scopes) if scopes else None,
        )

    # -- Access token verification (dual auth) -----------------------------

    async def load_access_token(self, token: str) -> PermytAccessToken | None:
        token_preview = token[:8] + "..." if len(token) > 8 else token

        # Try OAuth access token first
        db_token = await sync_to_async(
            OAuthAccessToken.objects.filter(token=token).select_related("user").first
        )()
        if db_token:
            if db_token.expires_at and db_token.expires_at < int(time.time()):
                logger.info(f"OAuth load_access_token: expired token={token_preview}")
                return None
            logger.info(
                f"OAuth load_access_token: valid OAuth token={token_preview} "
                f"user={db_token.user.id} client={db_token.client_id[:12]}"
            )
            return PermytAccessToken(
                token=db_token.token,
                client_id=db_token.client_id,
                scopes=db_token.scopes or [],
                expires_at=db_token.expires_at,
                resource=db_token.resource,
                user_id=str(db_token.user.id),
            )

        # Fallback: DRF token (unless disabled via setting)
        if not getattr(settings, "DISABLE_DRF_TOKEN_FALLBACK", False):
            drf_token = await sync_to_async(
                Token.objects.filter(key=token).select_related("user").first
            )()
            if drf_token and drf_token.user.permyt_user_id:
                logger.info(
                    f"OAuth load_access_token: DRF fallback token={token_preview} user={drf_token.user.id}"
                )
                return PermytAccessToken(
                    token=token,
                    client_id="drf-legacy",
                    scopes=[],
                    user_id=str(drf_token.user.id),
                )

        logger.info(f"OAuth load_access_token: no match for token={token_preview}")
        return None

    # -- Token revocation --------------------------------------------------

    async def revoke_token(self, token: PermytAccessToken | RefreshToken) -> None:
        """Revoke all access and refresh tokens for the client+user pair."""
        model = OAuthAccessToken if isinstance(token, PermytAccessToken) else OAuthRefreshToken
        db_token = await sync_to_async(
            model.objects.filter(token=token.token).select_related("user").first
        )()
        if not db_token:
            return

        filters = {"client_id": token.client_id, "user": db_token.user}
        await sync_to_async(OAuthAccessToken.objects.filter(**filters).delete)()
        await sync_to_async(OAuthRefreshToken.objects.filter(**filters).delete)()
