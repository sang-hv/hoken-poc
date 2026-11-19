"""Xác thực Azure: Managed Identity (DefaultAzureCredential) hoặc API key."""

from __future__ import annotations

import threading
import time
from functools import lru_cache


@lru_cache(maxsize=1)
def credential():
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


class TokenHeaders:
    """Header xác thực cho REST: `api-key` nếu có key, ngược lại Bearer token từ Managed Identity."""

    def __init__(self, scope: str, api_key: str = "", key_header: str = "api-key"):
        self.scope, self.api_key, self.key_header = scope, api_key, key_header
        self._token, self._exp = "", 0.0
        self._lock = threading.Lock()

    def __call__(self) -> dict[str, str]:
        if self.api_key:
            return {self.key_header: self.api_key}
        with self._lock:
            if time.time() > self._exp - 300:
                tok = credential().get_token(self.scope)
                self._token, self._exp = tok.token, float(tok.expires_on)
            return {"Authorization": f"Bearer {self._token}"}


def headers_for(cfg: dict, secrets: dict, scope: str, key_header: str = "api-key") -> TokenHeaders:
    key = secrets.get("api_key", "") if cfg.get("auth", "managed_identity") == "key" else ""
    return TokenHeaders(scope, key, key_header)
