"""Azure AI Content Understanding — analyzer prebuilt-layout (bảng, hình, OCR) qua REST.

GA (2025-11-01): POST .../analyzers/{id}:analyzeBinary ; bản preview cũ dùng :analyze với body nhị phân.
Kết quả là operation dài: poll Operation-Location đến khi Succeeded.
"""

from __future__ import annotations

import time

import httpx

from app.adapters.azure._auth import headers_for
from app.ports import LayoutResult

SCOPE = "https://cognitiveservices.azure.com/.default"


class ContentUnderstanding:
    def __init__(self, cfg: dict, secrets: dict):
        self.endpoint = cfg["endpoint"].rstrip("/")
        self.analyzer = cfg.get("analyzer_id") or "prebuilt-layout"
        self.api_version = cfg.get("api_version") or "2025-11-01"
        self.headers = headers_for(cfg, secrets, SCOPE, key_header="Ocp-Apim-Subscription-Key")

    @classmethod
    def from_config(cls, cfg: dict, secrets: dict) -> ContentUnderstanding:
        return cls(cfg, secrets)

    def _url(self, suffix: str = "") -> str:
        return f"{self.endpoint}/contentunderstanding/analyzers/{self.analyzer}{suffix}?api-version={self.api_version}"

    def analyze(self, data: bytes, content_type: str = "application/pdf") -> LayoutResult:
        op = ":analyze" if "preview" in self.api_version else ":analyzeBinary"
        r = httpx.post(
            self._url(op), content=data, timeout=120, headers={**self.headers(), "Content-Type": content_type}
        )
        if r.status_code >= 400:
            raise RuntimeError(f"CU HTTP {r.status_code}: {r.text[:300]}")
        loc = r.headers.get("operation-location")
        result = r.json() if not loc else None
        deadline = time.time() + 600
        while loc and time.time() < deadline:
            time.sleep(2)
            pr = httpx.get(loc, headers=self.headers(), timeout=60)
            if pr.status_code >= 400:
                raise RuntimeError(f"CU poll HTTP {pr.status_code}: {pr.text[:300]}")
            body = pr.json()
            status = str(body.get("status", "")).lower()
            if status == "succeeded":
                result = body
                break
            if status in ("failed", "canceled", "cancelled"):
                raise RuntimeError(f"CU {status}: {str(body.get('error'))[:300]}")
        if result is None:
            raise TimeoutError("CU không trả kết quả trong 10 phút")
        contents = (result.get("result") or {}).get("contents") or []
        md = "\n\n".join(c.get("markdown", "") for c in contents if c.get("markdown"))
        return LayoutResult(md, result)

    def health(self) -> None:
        r = httpx.get(self._url(), headers=self.headers(), timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"CU HTTP {r.status_code}: {r.text[:300]}")
