# PERMYT MCP

A Django service that exposes **MCP** and **REST API** interfaces so AI agents can act as **Requesters** in the PERMYT protocol.

## What is PERMYT

PERMYT is a zero-knowledge authorization broker. Users control who can access their data and under what conditions — the broker orchestrates consent and token exchange without ever seeing the data itself.

## What this does

- **MCP server** for Claude Code / Claude Desktop — 3 tools for requesting user data
- **REST API** for ChatGPT / OpenClaw / any HTTP client — token-authenticated endpoints
- **QR login** — users connect via mobile app, no manual setup needed
- **Multi-user** — DRF token authentication, each user has their own PERMYT identity

## Quick Start

```bash
python -m venv env
source env/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                       # fill in secrets
python manage.py migrate
python manage.py createsuperuser           # or use QR login
python manage.py runserver 9020            # dev server (REST + QR + MCP SSE)
# Production:
uvicorn settings.asgi:application --host 0.0.0.0 --port 9020
```

## Setup: PERMYT broker

### 1. Generate connector keys

```bash
mkdir -p keys/connector keys/permyt
openssl ecparam -name prime256v1 -genkey -noout -out keys/connector/private.pem
openssl ec -in keys/connector/private.pem -pubout -out keys/connector/public.pem
```

### 2. Register the service

Create a new service in the PERMYT dashboard:

- **Name**: "MCP Requester"
- **Callback URL**: `https://mcp.permyt.io/rest/permyt/inbound`
- **Public key**: upload `keys/connector/public.pem`

Note the **Service ID** for `.env`.

### 3. Download PERMYT public key

Save the broker's public key to `keys/permyt/public.pem`.

### 4. Update `.env`

```env
PERMYT_SERVICE_ID=<your-service-id>
# For local development with a local broker:
# PERMYT_HOST=http://localhost:8000
# BASE_URL=http://localhost:9020
```

## Getting Started (All Platforms)

### 1. Connect your PERMYT account

1. Visit [https://mcp.permyt.io](https://mcp.permyt.io)
2. Scan the QR code with your **PERMYT mobile app**
3. Your account is linked — copy your **auth token** from the dashboard

### 2. Add to your AI agent

Pick your platform below. No local installation needed — the server runs hosted.

---

### Claude Code

Add via CLI:

```bash
claude mcp add permyt -- --url https://mcp.permyt.io/mcp/sse --header "Authorization: Bearer <your-auth-token>"
```

Or add manually to `~/.claude.json`:

```json
{
  "mcpServers": {
    "permyt": {
      "url": "https://mcp.permyt.io/mcp/sse",
      "headers": {
        "Authorization": "Bearer <your-auth-token>"
      }
    }
  }
}
```

---

### Claude Desktop

1. Open **Settings > Developer > Edit Config**
2. Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "permyt": {
      "url": "https://mcp.permyt.io/mcp/sse",
      "headers": {
        "Authorization": "Bearer <your-auth-token>"
      }
    }
  }
}
```

3. Restart Claude Desktop.

---

### Claude.ai (Web)

1. Go to **Settings > MCP Servers > Add**
2. Enter:
   - **URL**: `https://mcp.permyt.io/mcp/sse`
   - **Header**: `Authorization: Bearer <your-auth-token>`

---

### ChatGPT (via GPT Actions)

ChatGPT uses REST API endpoints instead of MCP. Create a custom GPT with these actions:

**Request access:**

```
POST https://mcp.permyt.io/rest/requests/access/
Authorization: Token <your-auth-token>
Content-Type: application/json

{"description": "describe what data you need"}
```

**Check status / fetch data:**

```
POST https://mcp.permyt.io/rest/requests/status/
Authorization: Token <your-auth-token>
Content-Type: application/json

{"request_id": "<request-id from above>"}
```

The GPT should call `requests/access/` with a natural-language description, then poll `requests/status/` until the user approves (status changes from `pending` to `completed` with data).

---

### OpenClaw

OpenClaw can connect via MCP (if supported) or REST API:

**MCP (if supported):** Use the same config as Claude — URL `https://mcp.permyt.io/mcp/sse` with Bearer token header.

**REST API:** Same endpoints as ChatGPT above.

---

### 3. Start using

Ask your AI agent something that requires external data:

> "Summarize my latest bank statement"
> "Check my employment history for the last 3 years"
> "What does my health insurance cover?"

The agent describes what data it needs, and you **approve or deny each request on your PERMYT mobile app**. The agent never knows what services you have connected — it just asks, and the PERMYT broker figures out the rest.

### How it works

- Agent describes what data it needs in plain language
- PERMYT's AI determines the minimal permissions needed
- You see a summary on your phone and choose to approve or deny
- If approved, the agent receives the data directly from the provider
- PERMYT never sees your actual data — only brokers the connection

### MCP Tools

| Tool                       | Description                                                           |
| -------------------------- | --------------------------------------------------------------------- |
| `permyt_request_access`    | Submit natural-language data request. Returns `{request_id, status}`. |
| `permyt_check_access`      | Poll status. If approved, calls providers and returns actual data.    |
| `permyt_request_and_fetch` | Submit + poll until resolved (convenience, default 120s timeout).     |

### REST API Endpoints

| Method | Path                           | Auth            | Description               |
| ------ | ------------------------------ | --------------- | ------------------------- |
| POST   | `/rest/requests/access/`       | `Token <token>` | Submit access request     |
| POST   | `/rest/requests/status/`       | `Token <token>` | Poll status / fetch data  |
| POST   | `/rest/auth/token/regenerate/` | `Token <token>` | Revoke + regenerate token |

## All Endpoints

| Method | Path                           | Auth             | Description                 |
| ------ | ------------------------------ | ---------------- | --------------------------- |
| GET    | `/mcp/sse`                     | `Bearer <token>` | MCP SSE connection (Claude) |
| POST   | `/mcp/messages/`               | Session          | MCP message transport       |
| POST   | `/rest/requests/access/`       | `Token <token>`  | Submit access request       |
| POST   | `/rest/requests/status/`       | `Token <token>`  | Poll status / fetch data    |
| POST   | `/rest/auth/token/`            | None             | Login, get auth token       |
| POST   | `/rest/auth/token/regenerate/` | `Token <token>`  | Revoke + regenerate token   |
| POST   | `/rest/permyt/inbound/`        | Signed           | Broker webhook              |
| GET    | `/rest/login/status/`          | None             | QR login polling            |
| GET    | `/`                            | Session          | QR login / dashboard        |

## Testing

```bash
pytest                                     # all tests
pytest app/core/requests/tests/            # contract + view tests
pytest -v -k "test_nonce"                  # by keyword
```

## Project Structure

```
permyt-mcp/
├── app/
│   ├── mixins/             # Simplified AppModel (UUID pk, timestamps)
│   ├── core/
│   │   ├── users/          # User, LoginToken, token auth, factories
│   │   ├── requests/       # PermytClient, Nonce, REST views, tests
│   │   └── logs/           # Log model with activity context manager
│   ├── common/pages/       # QR login page, dashboard
│   ├── mcp/                # FastMCP server + management command
│   └── utils/              # Fields, encoders, middleware, crypto
├── settings/               # Django settings (base, dev, test)
├── conftest.py             # Shared test fixtures
├── requirements.txt        # Production dependencies
└── requirements-dev.txt    # Dev + test dependencies
```

## Configuration

| Variable                 | Description                      | Default                      |
| ------------------------ | -------------------------------- | ---------------------------- |
| `PERMYT_SERVICE_ID`      | Service ID from broker dashboard | —                            |
| `PERMYT_PUBLIC_KEY_PATH` | Broker public key path           | `keys/permyt/public.pem`     |
| `PRIVATE_KEY_PATH`       | Connector private key path       | `keys/connector/private.pem` |
| `BASE_URL`               | This service's public URL        | `https://mcp.permyt.io`      |
| `NONCE_TTL_SECONDS`      | Replay protection window         | `60`                         |
| `PERMYT_HOST`            | Broker URL                       | `https://permyt.io`          |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR guidelines.

## Security

See [SECURITY.md](SECURITY.md) for responsible disclosure policy.

## License

[MIT](LICENSE)
