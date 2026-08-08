"""Private HTTP transport primitives shared by ABI adapters."""

import math
from urllib.parse import quote

import httpx


def build_httpx_client(
    base_url: str,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None,
) -> httpx.Client:
    if type(timeout_seconds) not in {int, float}:
        raise TypeError("timeout_seconds must be a number")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")

    url = httpx.URL(base_url)
    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("base_url must be an absolute HTTP(S) URL")

    selected_transport = transport
    if selected_transport is None:
        selected_transport = httpx.HTTPTransport(retries=0)
    return httpx.Client(
        base_url=url,
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        transport=selected_transport,
    )


def encode_opaque_path_segment(value: str) -> str:
    encoded = quote(value, safe="", encoding="utf-8", errors="strict")
    if value in {".", ".."}:
        return encoded.replace(".", "%2E")
    return encoded
