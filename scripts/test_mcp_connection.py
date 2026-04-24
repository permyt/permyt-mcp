"""
Diagnostic script to test MCP server connectivity end-to-end.

Tests each step of the MCP connection flow that a client like Claude AI
would perform: OAuth discovery, DCR, authorize redirect, and (with a
valid token) the MCP initialize + tools/list handshake.

Usage:
    python scripts/test_mcp_connection.py [BASE_URL]

    # Test production
    python scripts/test_mcp_connection.py https://mcp.permyt.io

    # Test local
    python scripts/test_mcp_connection.py http://localhost:9020

    # Test with a valid auth token (skips OAuth, tests MCP directly)
    python scripts/test_mcp_connection.py https://mcp.permyt.io --token <token>
"""

import argparse
import json
import sys
import urllib.request
import urllib.error


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
INFO = "\033[94mINFO\033[0m"


USER_AGENT = "model-context-protocol/1.0 (permyt-mcp diagnostic)"


def request(url, method="GET", data=None, headers=None, follow_redirects=False):
    """Make an HTTP request and return (status, headers_dict, body)."""
    headers = headers or {}
    headers.setdefault("User-Agent", USER_AGENT)
    if data and isinstance(data, dict):
        data = json.dumps(data).encode()
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect) if not follow_redirects else urllib.request.build_opener()

    try:
        resp = opener.open(req)
        return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return e.code, dict(e.headers), body


def test_protected_resource_metadata(base_url):
    """Test /.well-known/oauth-protected-resource/mcp endpoint."""
    url = f"{base_url}/.well-known/oauth-protected-resource/mcp"
    print(f"\n{'='*60}")
    print(f"1. Protected Resource Metadata (RFC 9728)")
    print(f"   GET {url}")

    status, headers, body = request(url)
    print(f"   Status: {status}")

    if status != 200:
        print(f"   [{FAIL}] Expected 200, got {status}")
        print(f"   Body: {body[:200]}")
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print(f"   [{FAIL}] Response is not valid JSON")
        return None

    resource = data.get("resource")
    auth_servers = data.get("authorization_servers", [])

    print(f"   resource: {resource}")
    print(f"   authorization_servers: {auth_servers}")
    print(f"   [{PASS}] Metadata endpoint works")

    if not resource:
        print(f"   [{WARN}] Missing 'resource' field")
    if not auth_servers:
        print(f"   [{WARN}] Missing 'authorization_servers' field")

    return data


def test_authorization_server_metadata(base_url):
    """Test /.well-known/oauth-authorization-server/mcp endpoint."""
    url = f"{base_url}/.well-known/oauth-authorization-server/mcp"
    print(f"\n{'='*60}")
    print(f"2. Authorization Server Metadata (RFC 8414)")
    print(f"   GET {url}")

    status, headers, body = request(url)
    print(f"   Status: {status}")

    if status != 200:
        print(f"   [{FAIL}] Expected 200, got {status}")
        print(f"   Body: {body[:200]}")
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print(f"   [{FAIL}] Response is not valid JSON")
        return None

    required_fields = [
        "issuer", "authorization_endpoint", "token_endpoint",
        "response_types_supported", "code_challenge_methods_supported",
    ]
    for field in required_fields:
        val = data.get(field)
        status_str = PASS if val else FAIL
        print(f"   {field}: {val} [{status_str}]")

    optional_fields = ["registration_endpoint", "revocation_endpoint"]
    for field in optional_fields:
        val = data.get(field)
        if val:
            print(f"   {field}: {val}")

    if "S256" not in data.get("code_challenge_methods_supported", []):
        print(f"   [{WARN}] S256 not in code_challenge_methods_supported (required by MCP)")

    print(f"   [{PASS}] Authorization server metadata works")
    return data


def test_dcr(base_url, registration_endpoint):
    """Test Dynamic Client Registration."""
    print(f"\n{'='*60}")
    print(f"3. Dynamic Client Registration (DCR)")
    print(f"   POST {registration_endpoint}")

    client_data = {
        "client_name": "mcp-diagnostic-test",
        "redirect_uris": ["http://localhost:19999/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }

    status, headers, body = request(registration_endpoint, method="POST", data=client_data)
    print(f"   Status: {status}")

    if status != 201:
        print(f"   [{FAIL}] Expected 201, got {status}")
        print(f"   Body: {body[:200]}")
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print(f"   [{FAIL}] Response is not valid JSON")
        return None

    client_id = data.get("client_id")
    print(f"   client_id: {client_id}")
    print(f"   [{PASS}] DCR works")
    return data


def test_unauthenticated_mcp(base_url):
    """Test MCP endpoint without auth — should return 401 with proper headers."""
    mcp_url = f"{base_url}/mcp"
    print(f"\n{'='*60}")
    print(f"4. MCP Endpoint (unauthenticated)")
    print(f"   POST {mcp_url}")

    mcp_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "diagnostic", "version": "1.0.0"},
        },
        "id": 1,
    }

    status, headers, body = request(
        mcp_url,
        method="POST",
        data=mcp_request,
        headers={"Accept": "application/json, text/event-stream"},
    )
    print(f"   Status: {status}")

    www_auth = headers.get("Www-Authenticate") or headers.get("www-authenticate", "")
    print(f"   WWW-Authenticate: {www_auth[:120]}")

    if status == 401:
        if "resource_metadata" in www_auth:
            print(f"   [{PASS}] Returns 401 with resource_metadata in WWW-Authenticate")
        else:
            print(f"   [{WARN}] Returns 401 but no resource_metadata in WWW-Authenticate")
    else:
        print(f"   [{WARN}] Expected 401, got {status}")
        print(f"   Body: {body[:200]}")


def test_cors_preflight(base_url):
    """Test CORS preflight on MCP endpoint."""
    mcp_url = f"{base_url}/mcp"
    print(f"\n{'='*60}")
    print(f"5. CORS Preflight (OPTIONS)")
    print(f"   OPTIONS {mcp_url}")

    status, headers, body = request(
        mcp_url,
        method="OPTIONS",
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, authorization",
        },
    )
    print(f"   Status: {status}")

    acao = headers.get("Access-Control-Allow-Origin", headers.get("access-control-allow-origin", ""))
    acam = headers.get("Access-Control-Allow-Methods", headers.get("access-control-allow-methods", ""))
    acah = headers.get("Access-Control-Allow-Headers", headers.get("access-control-allow-headers", ""))

    if status == 200 and acao:
        print(f"   Access-Control-Allow-Origin: {acao}")
        print(f"   Access-Control-Allow-Methods: {acam}")
        print(f"   Access-Control-Allow-Headers: {acah}")
        print(f"   [{PASS}] CORS preflight works")
    elif status == 401:
        print(f"   [{FAIL}] CORS preflight returns 401 (auth required for OPTIONS)")
        print(f"   This blocks browser-based MCP clients (including Claude AI web).")
        print(f"   The MCP SDK's RequireAuthMiddleware rejects OPTIONS requests.")
    else:
        print(f"   [{WARN}] Unexpected status {status}")
        print(f"   Body: {body[:200]}")


def test_authorize_redirect(base_url, authorization_endpoint, client_id):
    """Test the authorize endpoint redirect chain."""
    print(f"\n{'='*60}")
    print(f"6. Authorization Redirect")

    url = (
        f"{authorization_endpoint}"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri=http%3A%2F%2Flocalhost%3A19999%2Fcallback"
        f"&code_challenge=test_challenge_1234567890abcdef1234567890abcdef"
        f"&code_challenge_method=S256"
        f"&state=test_state"
    )
    print(f"   GET {url[:100]}...")

    status, headers, body = request(url)
    location = headers.get("Location") or headers.get("location", "")
    print(f"   Status: {status}")
    print(f"   Location: {location}")

    if status == 302 and location:
        print(f"   [{PASS}] Authorize redirects to QR login page")

        # Follow redirect to check QR page loads
        print(f"\n   Following redirect to QR page...")
        status2, headers2, body2 = request(location)
        print(f"   Status: {status2}")

        if status2 == 200:
            has_qr = "qr-container" in body2
            has_polling = "login/status" in body2
            print(f"   QR container in HTML: {has_qr}")
            print(f"   Login polling in JS: {has_polling}")

            # Check for problematic headers
            xfo = headers2.get("X-Frame-Options") or headers2.get("x-frame-options", "")
            coop = headers2.get("Cross-Origin-Opener-Policy") or headers2.get("cross-origin-opener-policy", "")
            cookie = headers2.get("Set-Cookie") or headers2.get("set-cookie", "")

            if xfo:
                print(f"   X-Frame-Options: {xfo}")
                if xfo.upper() == "DENY":
                    print(f"   [{WARN}] X-Frame-Options: DENY prevents iframe embedding")
                    print(f"   (OK for popups, but blocks iframe-based OAuth)")
            if coop:
                print(f"   Cross-Origin-Opener-Policy: {coop}")
            if "SameSite" in cookie:
                samesite = [p for p in cookie.split(";") if "SameSite" in p]
                print(f"   Cookie SameSite: {'; '.join(samesite)}")

            print(f"   [{PASS}] QR login page loads correctly")
        else:
            print(f"   [{FAIL}] QR page returned {status2}")
    else:
        print(f"   [{FAIL}] Expected 302 redirect, got {status}")


def test_authenticated_mcp(base_url, token):
    """Test MCP initialize + tools/list with a valid auth token."""
    mcp_url = f"{base_url}/mcp"
    print(f"\n{'='*60}")
    print(f"7. MCP Endpoint (authenticated)")
    print(f"   POST {mcp_url}")

    # Initialize
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "diagnostic", "version": "1.0.0"},
        },
        "id": 1,
    }

    status, headers, body = request(
        mcp_url,
        method="POST",
        data=init_request,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )
    print(f"   initialize status: {status}")

    if status == 401:
        print(f"   [{FAIL}] Token rejected (401). Token may be expired or invalid.")
        return
    if status != 200:
        print(f"   [{WARN}] Unexpected status {status}")
        print(f"   Body: {body[:300]}")
        return

    # Check if response is SSE or JSON
    content_type = headers.get("Content-Type") or headers.get("content-type", "")
    print(f"   Content-Type: {content_type}")

    if "text/event-stream" in content_type:
        print(f"   [{INFO}] SSE response (streaming)")
        # Parse SSE
        for line in body.split("\n"):
            if line.startswith("data:"):
                data_str = line[5:].strip()
                try:
                    data = json.loads(data_str)
                    print(f"   Response: {json.dumps(data, indent=2)[:300]}")
                except json.JSONDecodeError:
                    print(f"   Raw: {data_str[:200]}")
    else:
        print(f"   [{INFO}] JSON response")
        try:
            data = json.loads(body)
            print(f"   Response: {json.dumps(data, indent=2)[:300]}")
        except json.JSONDecodeError:
            print(f"   Raw: {body[:200]}")

    # Check for Mcp-Session-Id header
    session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id", "")
    if session_id:
        print(f"   Mcp-Session-Id: {session_id}")
        print(f"   [{PASS}] Initialize succeeded with session")

        # Now send initialized notification + tools/list
        print(f"\n   Sending initialized notification + tools/list...")
        tools_request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 2,
        }

        status2, headers2, body2 = request(
            mcp_url,
            method="POST",
            data=tools_request,
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
                "Mcp-Session-Id": session_id,
            },
        )
        print(f"   tools/list status: {status2}")

        if "text/event-stream" in (headers2.get("Content-Type") or headers2.get("content-type", "")):
            for line in body2.split("\n"):
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        data = json.loads(data_str)
                        tools = data.get("result", {}).get("tools", [])
                        if tools:
                            print(f"   [{PASS}] Found {len(tools)} tools:")
                            for t in tools:
                                print(f"     - {t.get('name')}: {t.get('description', '')[:60]}")
                        else:
                            print(f"   [{WARN}] tools/list returned no tools")
                            print(f"   Response: {json.dumps(data, indent=2)[:300]}")
                    except json.JSONDecodeError:
                        print(f"   Raw: {data_str[:200]}")
        else:
            print(f"   Body: {body2[:300]}")
    else:
        print(f"   [{WARN}] No Mcp-Session-Id in response")


def main():
    parser = argparse.ArgumentParser(description="Test MCP server connectivity")
    parser.add_argument("base_url", nargs="?", default="https://mcp.permyt.io",
                        help="Base URL of the MCP server (default: https://mcp.permyt.io)")
    parser.add_argument("--token", help="Auth token for authenticated MCP testing")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"Testing MCP server at: {base_url}")

    # Step 1: Protected resource metadata
    resource_meta = test_protected_resource_metadata(base_url)

    # Step 2: Authorization server metadata
    auth_meta = test_authorization_server_metadata(base_url)

    # Step 3: DCR
    client_info = None
    if auth_meta and auth_meta.get("registration_endpoint"):
        client_info = test_dcr(base_url, auth_meta["registration_endpoint"])

    # Step 4: Unauthenticated MCP request
    test_unauthenticated_mcp(base_url)

    # Step 5: CORS preflight
    test_cors_preflight(base_url)

    # Step 6: Authorization redirect
    if auth_meta and client_info:
        test_authorize_redirect(
            base_url,
            auth_meta["authorization_endpoint"],
            client_info["client_id"],
        )

    # Step 7: Authenticated MCP (if token provided)
    if args.token:
        test_authenticated_mcp(base_url, args.token)
    else:
        print(f"\n{'='*60}")
        print(f"7. Authenticated MCP (skipped)")
        print(f"   Pass --token <auth_token> to test initialize + tools/list")

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    if not args.token:
        print(f"  OAuth discovery + DCR: working")
        print(f"  To test full MCP flow, get a token via the OAuth flow")
        print(f"  or use a DRF auth token: --token <token>")
    print()


if __name__ == "__main__":
    main()
