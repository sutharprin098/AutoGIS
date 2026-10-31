"""Resilient, bounded Overpass API client helpers."""
from __future__ import annotations

import concurrent.futures
import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "AutoGIS-Studio/1.1 (+https://autogis.princesite.in/)"
DEFAULT_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
)


def fetch_overpass(endpoint: str, query: str, timeout: float = 35.0) -> dict:
    """POST an Overpass query and validate JSON. Timeout is per endpoint."""
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Overpass endpoint must be a valid HTTPS URL.")
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=max(5.0, min(float(timeout), 90.0))) as response:  # nosec B310
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass returned an unexpected response.")
    remark = str(payload.get("remark") or "")
    if remark and not payload["elements"]:
        raise RuntimeError(f"Overpass query warning: {remark}")
    return payload


def query_overpass(query: str, endpoints=DEFAULT_ENDPOINTS, timeout: float = 35.0,
                   max_workers: int = 3) -> tuple[dict | None, str, str]:
    """Race a limited number of mirrors, then fail with actionable diagnostics."""
    errors: list[str] = []
    candidates = list(endpoints)[:max(1, min(int(max_workers), 5))]
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates))
    futures = {executor.submit(fetch_overpass, endpoint, query, timeout): endpoint for endpoint in candidates}
    try:
        for future in concurrent.futures.as_completed(futures, timeout=max(8.0, timeout + 3.0)):
            endpoint = futures[future]
            try:
                data = future.result()
                return data, endpoint, ""
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
                errors.append(f"{endpoint}: {str(exc)[:180]}")
    except concurrent.futures.TimeoutError:
        errors.append("Mirror race exceeded the overall request deadline.")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return None, "", "; ".join(errors[:3]) or "All Overpass mirrors failed."
