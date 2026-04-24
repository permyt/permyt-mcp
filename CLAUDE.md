# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with permyt-mcp.

## Project Overview

**permyt-mcp/** is a Django service that exposes **MCP** (Model Context Protocol) and **REST API** interfaces so AI agents (Claude, ChatGPT, OpenClaw) can act as **Requesters** in the PERMYT protocol. Users connect via QR code, and agents request access to their data through the PERMYT broker.

### Sibling projects

- `../permyt` — the PERMYT broker (Django, port 8000). AI scope evaluation, consent routing, token brokering.
- `../permyt-api-python` — the `permyt` Python SDK. Published on PyPI as `permyt`.
- `../permyt-demo/requester` — demo requester app (Django, port 9010). This project was derived from it.
- `../permyt-demo/provider` — demo NoteVault provider (Django, port 9011).

## Commands

### Development

```bash
python -m venv env && source env/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                       # then fill in secrets
python manage.py migrate                   # apply migrations
python manage.py runserver 9020            # REST API + QR login page
```

### MCP Server (hosted — Streamable HTTP)

```bash
# Production: serves both Django + MCP Streamable HTTP at /mcp
uvicorn settings.asgi:application --host 0.0.0.0 --port 9020
```

### MCP Server (local — stdio)

```bash
python manage.py mcp_server --token <auth-token>
# Or via env var:
PERMYT_AUTH_TOKEN=<token> python manage.py mcp_server
```

### Testing

```bash
pytest                                     # all tests
pytest app/core/requests/tests/            # contract + view tests
pytest -v -k "test_nonce"                  # by keyword
```

### Key generation (one-time)

```bash
mkdir -p keys/connector keys/permyt
openssl ecparam -name prime256v1 -genkey -noout -out keys/connector/private.pem
openssl ec -in keys/connector/private.pem -pubout -out keys/connector/public.pem
# Download PERMYT public key from dashboard -> keys/permyt/public.pem
```

## Architecture

```
permyt-mcp/
  app/
    mixins/             # Simplified AppModel — UUID PK + timestamps
    core/
      users/            # User model, LoginToken, QR login, token auth
      requests/         # PermytClient (requester), Nonce, REST API views, webhook
    common/
      pages/            # IndexView (QR login / dashboard), templates
    mcp/                # FastMCP server + management command
    utils/              # Fields, encoders, middleware, authentication, crypto
  settings/             # Django settings (base, dev, test)
  conftest.py           # Shared test fixtures
```

### Key classes

| Class | File | Role |
|-------|------|------|
| `AppModel` | `app/mixins/models.py` | Abstract base model (UUID pk, created_at, updated_at) |
| `User` | `app/core/users/models.py` | Custom user with `permyt_user_id` for PERMYT identity |
| `LoginToken` | `app/core/users/models.py` | Short-lived QR-login session binding |
| `Nonce` | `app/core/requests/models.py` | Replay protection (unique nonce values) |
| `PermytClient` | `app/core/requests/client.py` | Requester-side PermytClient — QR login, nonce, status callbacks |
| `RequestAccessView` | `app/core/requests/views.py` | REST endpoint: submit access request |
| `CheckAccessView` | `app/core/requests/views.py` | REST endpoint: poll status, fetch data |
| `PermytInboundView` | `app/core/requests/views.py` | Inbound webhook for PERMYT broker callbacks |
| `IndexView` | `app/common/pages/views.py` | QR login / dashboard page |
| `ViewScopesView` | `app/core/requests/views.py` | REST endpoint: view available scopes |
| `mcp` (FastMCP) | `app/mcp/server.py` | MCP server with 4 tools for AI agents |
| `create_mcp_app` | `app/mcp/server.py` | Factory for Streamable HTTP Starlette ASGI app |
| `TokenRegenerateView` | `app/core/users/views.py` | Token revoke + regenerate endpoint |

### Transport modes

**Streamable HTTP (hosted, production)**: ASGI router at `settings/asgi.py` mounts MCP Starlette app at `/mcp` alongside Django. OAuth 2.0 auth with dynamic client registration. ASGI router also forwards `/.well-known/oauth-protected-resource/*` for RFC 9728 compliance.

**stdio (local, development)**: Management command `mcp_server` sets module-level token. Tools fallback to it when no request context.

### Dual interface

**REST API** (for ChatGPT / OpenClaw / any HTTP client):
- `POST /rest/auth/token/` — login, get DRF auth token
- `POST /rest/requests/access/` — submit access request (token auth)
- `POST /rest/requests/status/` — poll status / fetch data (token auth)
- `POST /rest/requests/scopes/` — view available scopes (token auth)
- `POST /rest/permyt/inbound/` — broker webhook (signed, no auth)
- `GET /rest/login/status/?id=<id>` — QR login polling

**MCP tools** (for Claude Code / Claude Desktop):
- `permyt_view_scopes` — view available scopes
- `permyt_request_access` — submit request
- `permyt_check_access` — poll + fetch

### Request flow

```
Agent calls tool/API → PermytClient.request_access()
  → Broker AI evaluates scopes → User approves on mobile
  → Agent polls via check_access → PermytClient.call_services()
  → Provider returns data → Agent receives data
```

## Settings

Django settings in `settings/`. Entry points:

- `manage.py` → `settings.dev` (extends base with DEBUG=True, open CORS/hosts)
- `uvicorn`/`gunicorn` → `settings.base` (production defaults: DEBUG=False, SECURE_* headers)
- `pytest.ini` → `settings.test`

All config via environment variables — see `.env.example`.

## Testing

Tests use **pure pytest** (not `django.test.TestCase`). DB-touching tests use `@pytest.mark.django_db`.

Shared fixtures in `conftest.py`:
- `user` — pre-created User via factory
- `mock_permyt_client` — PermytClient with mocked key loading

## Code standards

- **Imports at the top.** All imports go at module level. Only defer an import if there is a proven circular dependency — never for laziness or "might be needed later".
- **No dead code.** Delete unused functions, variables, imports, and files. Don't leave stubs, commented-out code, or empty placeholder files.
- **Classes over loose functions.** Group related behaviour into classes. Use standalone functions only when a class adds no value (e.g. a pure utility with no shared state).
- **Constants over magic values.** Extract repeated literals (TTLs, byte sizes, status strings) into named constants at the top of the module.
- **Clean, readable, debuggable.** Code should read top-down with no surprises. Favour explicit over clever.

## Patterns to follow

- All models extend `AppModel` from `app/mixins/models.py`.
- Tests use pytest fixtures from `conftest.py`, not `setUp`/`TestCase`.
- REST API uses DRF `TokenAuthentication`.
- MCP server uses same PermytClient as REST views.
- Provider-only methods use SDK base defaults (`NotImplementedError`) — no stubs needed.

## PERMYT Protocol Reference

### Actors

| Actor | Description |
|-------|-------------|
| **Broker** | The PERMYT server. Orchestrates flows, AI scope evaluation, consent, token brokering. Never sees data. |
| **Requester** | Service wanting user data. This project is a Requester. |
| **Provider** | Service holding user data, issues tokens. |
| **Mobile App** | User's device for QR connect and approve/deny. |

### Security Model

All communication uses **ES256 signing** (proof JWT over payload hash) + **JWE encryption** (ECDH-ES+A256KW + A256GCM). Every request has unique **nonce** + **timestamp** for replay protection. Tokens are **single-use**.
