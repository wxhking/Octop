"""Exercise real discovery/registration/URL creation with a simulated provider.

Only DNS and the HTTP transport are mocked; no Octop business function is replaced.
Run with --expect broken before the fix, --expect fixed after the fix.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import socket
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

parser = argparse.ArgumentParser()
parser.add_argument("--expect", choices=["broken", "fixed"], required=True)
parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Octop repository directory")
args = parser.parse_args()
sys.path.insert(0, str(args.repo.resolve() / "src"))

import httpx
from octop.infra.connectors.oauth import discovery, registry
from octop.infra.utils import ssrf_guard


async def run_case(query):
    issuer = "https://auth.example.com"
    mcp_url = "https://mcp.example.com/mcp"
    endpoint = issuer + "/authorize" + query
    trace = []
    verifier = ""

    def provider(request):
        trace.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if request.url.host == "mcp.example.com" and path == "/mcp":
            return httpx.Response(401, headers={"WWW-Authenticate":
                'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"'})
        if path == "/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json={"resource": mcp_url, "authorization_servers": [issuer]})
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={"issuer": issuer, "authorization_endpoint": endpoint,
                "token_endpoint": issuer + "/token", "registration_endpoint": issuer + "/register",
                "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": ["tools:read"]})
        if path == "/register":
            body = json.loads(request.content)
            assert body["response_types"] == ["code"]
            assert body["redirect_uris"] == ["https://client.example/callback"]
            return httpx.Response(201, json={"client_id": "demo-client"})
        if path == "/authorize":
            parsed = parse_qs(urlsplit(str(request.url)).query, keep_blank_values=True)
            original = parse_qs(urlsplit(endpoint).query, keep_blank_values=True)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            expected = {"response_type": ["code"], "client_id": ["demo-client"],
                "redirect_uri": ["https://client.example/callback"], "state": ["demo-state"],
                "code_challenge": [challenge], "code_challenge_method": ["S256"],
                "scope": ["tools:read"], "resource": [mcp_url]}
            errors = [k for k, v in {**original, **expected}.items() if parsed.get(k) != v]
            return httpx.Response(400 if errors else 200, json={"invalid_parameters": errors})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    # Public IP is synthetic: MockTransport handles every request without a socket.
    dns = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))])
    discovery.clear_oauth_discovery_cache()
    with patch.object(asyncio.get_running_loop(), "getaddrinfo", dns), patch.object(
        ssrf_guard, "PinnedIPTransport", side_effect=lambda *_: httpx.MockTransport(provider)
    ):
        url, verifier, context = await registry.start_oauth_for_target(
            target={"type": "custom_mcp", "server_name": "query-demo", "mcp_url": mcp_url},
            redirect_uri="https://client.example/callback", state="demo-state", settings_repo=None)
        assert context["flow"] == "custom_mcp"
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            response = await client.get(url)
    parsed = parse_qs(urlsplit(url).query, keep_blank_values=True)
    # Do not publish random PKCE data or absolute local paths.
    parsed.pop("code_challenge", None)
    result = {"endpoint_query": query or "(none)", "provider_status": response.status_code,
        "invalid_parameters": response.json()["invalid_parameters"], "parsed_query": parsed, "trace": trace}
    print(json.dumps(result, ensure_ascii=False))
    should_pass = args.expect == "fixed" or not query
    assert response.status_code == (200 if should_pass else 400), result


async def main():
    for query in ["", "?", "?tenant=acme", "?tenant=acme&prompt=consent",
                  "?tenant=acme%20corp&tag=a+b", "?tenant=&tag=a&tag=b"]:
        await run_case(query)
    print("PASS: " + args.expect + " behavior confirmed across six public-entry flow cases")


asyncio.run(main())
