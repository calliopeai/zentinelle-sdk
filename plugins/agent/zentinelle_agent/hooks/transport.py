"""Bounded, strict JSON transport shared by coding-agent hook adapters."""
from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

MAX_BYTES = 1024 * 1024
HTTP_SECONDS = 5


class PolicyError(Exception):
    """A fixed, credential-free reason safe to send to the harness."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError("Duplicate JSON field")
        result[key] = value
    return result


def _invalid_number(_value):
    raise PolicyError("Non-finite JSON number")


def parse_json(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_number)
        # json.loads accepts exponent overflow (1e999) independently of NaN.
        json.dumps(value, allow_nan=False)
        return value
    except PolicyError:
        raise
    except Exception:
        raise PolicyError("Invalid JSON") from None


def read_event(stream):
    results = queue.Queue(maxsize=1)

    def work():
        try:
            # Unbuffered reads avoid holding Python's global stdin buffer lock
            # when a deadline ends a one-shot process with an unfinished pipe.
            raw = bytearray()
            while True:
                chunk = os.read(stream.fileno(), min(8192, MAX_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise PolicyError("Tool event exceeds the limit")
            value = parse_json(raw)
        except Exception as error:
            results.put(error)
        else:
            results.put(value)

    threading.Thread(target=work, daemon=True).start()
    try:
        value = results.get(timeout=HTTP_SECONDS)
    except queue.Empty:
        raise PolicyError("Tool input deadline exceeded") from None
    if isinstance(value, Exception):
        raise value
    return value


def base_url(endpoint):
    try:
        parts = urllib.parse.urlsplit(endpoint)
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise ValueError()
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
        if any(ord(char) <= 32 or ord(char) == 127 for char in endpoint):
            raise ValueError()
        _ = parts.port
    except Exception:
        raise PolicyError("Invalid Zentinelle endpoint; HTTPS is required except for loopback") from None
    return endpoint.rstrip("/")


def credential(env):
    first, second = env.get("ZENTINELLE_KEY", ""), env.get("ZENTINELLE_AGENT_HOST_KEY", "")
    if first and second and first != second:
        raise PolicyError("Conflicting Zentinelle credentials")
    key = first or second
    if len(key) > 8192 or any(ord(char) <= 32 or ord(char) == 127 for char in key):
        raise PolicyError("Invalid Zentinelle credential")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _fp, _code, _message, _headers, _url):
        raise PolicyError("Policy redirects are refused")


def request_json(endpoint, key, path, body=None, deadline=None):
    remaining = HTTP_SECONDS if deadline is None else min(HTTP_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        raise PolicyError("Policy check deadline exceeded")
    results = queue.Queue(maxsize=1)

    def work():
        try:
            payload = None if body is None else json.dumps(body, allow_nan=False).encode()
            if payload is not None and len(payload) > MAX_BYTES:
                raise PolicyError("Policy input exceeds the limit")
            request = urllib.request.Request(endpoint + path, data=payload,
                                             headers={"Content-Type": "application/json", "X-Zentinelle-Key": key},
                                             method="GET" if body is None else "POST")
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=remaining) as response:
                if response.status != 200:
                    raise PolicyError("Policy service returned an unsuccessful response")
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise PolicyError("Policy response exceeds the limit")
                result = parse_json(raw)
                if not isinstance(result, dict):
                    raise PolicyError("Invalid policy response")
        except PolicyError as error:
            results.put(error)
        except Exception:
            # URLs, HTTP bodies and library errors can carry keys/tool content.
            results.put(PolicyError("Policy service unavailable or returned invalid JSON"))
        else:
            results.put(result)

    threading.Thread(target=work, daemon=True).start()
    try:
        result = results.get(timeout=remaining)
    except queue.Empty:
        raise PolicyError("Policy check deadline exceeded") from None
    if isinstance(result, Exception):
        raise result
    if deadline is not None and time.monotonic() >= deadline:
        raise PolicyError("Policy check deadline exceeded")
    return result


def decision(result, invocation=None):
    value = result.get("decision")
    if value not in ("allow", "deny", "ask") or type(result.get("allowed")) is not bool:
        raise PolicyError("Policy did not return a valid explicit decision")
    if result["allowed"] != (value == "allow"):
        raise PolicyError("Conflicting policy decision")
    context = result.get("context", {})
    if not isinstance(context, dict):
        raise PolicyError("Invalid policy response context")
    if "contract_version" in result and result["contract_version"] != "1":
        raise PolicyError("Unsupported policy contract")
    if invocation is not None:
        if "action" in result and result["action"] != invocation["action"]:
            raise PolicyError("Policy action changed")
        subject = result.get("subject", {})
        if not isinstance(subject, dict):
            raise PolicyError("Invalid policy subject")
        for name in ("user_id", "agent_id"):
            if name in invocation and name in subject and subject[name] != invocation[name]:
                raise PolicyError("Policy subject changed")
        for name, original in invocation["context"].items():
            if name in context and json.dumps(context[name], sort_keys=True) != json.dumps(original, sort_keys=True):
                raise PolicyError("Policy invocation changed")
    if value == "allow" and context.get("require_human_approval"):
        raise PolicyError("Human approval is still required")
    return value


def expiry(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError()
        seconds = (date - datetime.now(timezone.utc)).total_seconds()
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError()
        return time.monotonic() + seconds
    except Exception:
        raise PolicyError("Approval expiry is invalid or elapsed") from None
