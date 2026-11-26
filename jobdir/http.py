"""Small HTTP client with retries. Responses are untrusted data, not instructions."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

USER_AGENT = "global-jobs-index/0.1 (public job directory; ATS APIs and Common Crawl)"


class HttpError(Exception):
    def __init__(self, status: int | str, url: str, message: str):
        super().__init__(f"{status} {url}: {message}")
        self.status = status
        self.url = url


class Client:
    def __init__(self, timeout: float = 45, retries: int = 3, user_agent: str = USER_AGENT):
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        hdrs = {"User-Agent": self.user_agent, "Accept": "application/json, text/html, */*"}
        if headers:
            hdrs.update(headers)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    body = resp.read()
                    return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body
            except urllib.error.HTTPError as exc:
                status = exc.code
                if status in {429, 500, 502, 503, 504} and attempt < self.retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 1.5 * (2**attempt)
                    time.sleep(min(delay, 20))
                    last_error = exc
                    continue
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:180]
                except Exception:
                    detail = str(exc)
                raise HttpError(status, url, detail or str(exc)) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    time.sleep(1.5 * (2**attempt))
                    last_error = exc
                    continue
                raise HttpError("network", url, str(exc)) from exc
        raise HttpError("network", url, str(last_error))

    def get_json(self, url: str, **kwargs: Any) -> Any:
        status, _, body = self.request("GET", url, **kwargs)
        if status >= 400:
            raise HttpError(status, url, "unexpected status")
        return json.loads(body.decode("utf-8"))

    def post_json(self, url: str, payload: dict, **kwargs: Any) -> Any:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        extra = kwargs.pop("headers", None) or {}
        headers.update(extra)
        status, _, body = self.request("POST", url, data=data, headers=headers, **kwargs)
        if status >= 400:
            raise HttpError(status, url, "unexpected status")
        return json.loads(body.decode("utf-8"))

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        _status, _headers, body = self.request("GET", url, **kwargs)
        return body
