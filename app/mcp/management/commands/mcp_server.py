import os

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Start the PERMYT MCP server (stdio transport for local development)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--token",
            type=str,
            default=os.environ.get("PERMYT_AUTH_TOKEN"),
            help="DRF auth token for user identification (or set PERMYT_AUTH_TOKEN env var)",
        )

    def handle(self, *args, **options):
        token = options["token"]
        if not token:
            self.stderr.write(
                self.style.ERROR(
                    "No auth token provided. Set PERMYT_AUTH_TOKEN env var or pass --token."
                )
            )
            return

        # Validate token before starting
        from app.core.users.authtoken.models import Token

        try:
            token_obj = Token.objects.select_related("user").get(key=token)
        except Token.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Invalid auth token: {token[:8]}..."))
            return

        user = token_obj.user
        if not user.permyt_user_id:
            self.stderr.write(
                self.style.ERROR(
                    f"User {user} has no permyt_user_id. Please connect via QR login first."
                )
            )
            return

        self.stderr.write(
            self.style.SUCCESS(
                f"Starting PERMYT MCP server for user {user} "
                f"(permyt_user_id: {user.permyt_user_id})"
            )
        )

        # Set stdio auth token (fallback for tools when no request context)
        from app.mcp.server import mcp, set_stdio_auth_token

        set_stdio_auth_token(token)
        mcp.run(transport="stdio")
