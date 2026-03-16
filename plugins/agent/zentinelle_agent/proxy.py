"""
Zentinelle proxy server for Claude Code.

Sits between Claude Code and a provider API:

  Claude Code  →  http://127.0.0.1:PORT  →  Zentinelle proxy endpoint
                                              (adds X-Zentinelle-Key header)
                                              → /zentinelle/proxy/<provider>/

Configure Claude Code:
  export <PROVIDER_BASE_URL>=http://127.0.0.1:PORT

The Zentinelle backend proxy strips X-Zentinelle-Key for agent identification,
evaluates policies, and forwards clean requests to the provider API.
"""
import os
import sys
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8742
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 300.0  # Long — Claude can take a while

_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_BASE_URL",
    "openai": "OPENAI_BASE_URL",
    "google": "GOOGLE_API_BASE",
}


class ProxyHandler(BaseHTTPRequestHandler):
    """
    HTTP handler that forwards requests to the Zentinelle proxy endpoint,
    injecting the X-Zentinelle-Key header for agent identification.

    The Zentinelle endpoint (/zentinelle/proxy/<provider>/) is a transparent
    passthrough: it strips X-Zentinelle-Key, identifies the agent, evaluates
    policies, then forwards the request to the provider API.

    SSE streaming is handled by chunked transfer to the client.
    """

    # Set by ProxyServer before creating instances
    zentinelle_endpoint: str = ""
    zentinelle_key: str = ""

    def log_message(self, format, *args):
        logger.debug("proxy: " + format % args)

    def do_POST(self):
        self._proxy_request("POST")

    def do_GET(self):
        self._proxy_request("GET")

    def do_DELETE(self):
        self._proxy_request("DELETE")

    def _proxy_request(self, method: str):
        # Build target URL
        target = self.zentinelle_endpoint.rstrip("/") + self.path

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Forward headers, stripping hop-by-hop and injecting Zentinelle key
        forward_headers = {}
        hop_by_hop = {
            "connection", "keep-alive", "proxy-authenticate",
            "proxy-authorization", "te", "trailers", "transfer-encoding",
            "upgrade", "host",
        }
        for name, value in self.headers.items():
            if name.lower() not in hop_by_hop:
                forward_headers[name] = value

        # Inject the Zentinelle agent key — the proxy uses this to identify
        # which agent is making the request for policy evaluation
        forward_headers["X-Zentinelle-Key"] = self.zentinelle_key

        try:
            with httpx.Client(
                timeout=httpx.Timeout(_CONNECT_TIMEOUT, read=_READ_TIMEOUT),
                follow_redirects=True,
            ) as client:
                with client.stream(
                    method,
                    target,
                    content=body,
                    headers=forward_headers,
                ) as response:
                    # Send status line
                    self.send_response(response.status_code)

                    # Forward response headers (strip hop-by-hop)
                    for name, value in response.headers.items():
                        if name.lower() not in hop_by_hop:
                            self.send_header(name, value)
                    self.end_headers()

                    # Stream body — handles both SSE and regular JSON
                    for chunk in response.iter_bytes():
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()

        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Zentinelle at {self.zentinelle_endpoint}: {e}")
            self.send_error(502, f"Cannot reach Zentinelle: {e}")
        except httpx.TimeoutException as e:
            logger.error(f"Timeout proxying request: {e}")
            self.send_error(504, "Gateway timeout")
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            self.send_error(500, f"Proxy error: {e}")


class ProxyServer:
    """Local proxy server that injects Zentinelle credentials into provider API calls."""

    def __init__(
        self,
        zentinelle_endpoint: str,
        zentinelle_key: str,
        provider: str = "anthropic",
        port: int = _DEFAULT_PORT,
        host: str = "127.0.0.1",
    ):
        self.provider = provider
        self.zentinelle_endpoint = zentinelle_endpoint.rstrip("/") + f"/proxy/{provider}"
        self.zentinelle_key = zentinelle_key
        self.port = port
        self.host = host
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, blocking: bool = True):
        # Patch class-level attributes (handler instances don't accept __init__ args)
        ProxyHandler.zentinelle_endpoint = self.zentinelle_endpoint
        ProxyHandler.zentinelle_key = self.zentinelle_key

        self._server = HTTPServer((self.host, self.port), ProxyHandler)

        print(f"Zentinelle proxy started on http://{self.host}:{self.port}")
        print(f"Forwarding to: {self.zentinelle_endpoint}")
        print()
        print("Configure your agent:")
        env_var = _PROVIDER_ENV_VARS.get(self.provider, "ANTHROPIC_BASE_URL")
        print(f"  export {env_var}=http://{self.host}:{self.port}")
        print()
        print("Press Ctrl+C to stop.")

        if blocking:
            try:
                self._server.serve_forever()
            except KeyboardInterrupt:
                self.stop()
        else:
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="zentinelle-proxy",
            )
            self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            print("\nProxy stopped.")


def run_proxy(
    zentinelle_endpoint: str,
    zentinelle_key: str,
    provider: str = "anthropic",
    port: int = _DEFAULT_PORT,
    host: str = "127.0.0.1",
):
    """Start the proxy (blocking). Called by CLI."""
    server = ProxyServer(
        zentinelle_endpoint=zentinelle_endpoint,
        zentinelle_key=zentinelle_key,
        provider=provider,
        port=port,
        host=host,
    )
    server.start(blocking=True)
